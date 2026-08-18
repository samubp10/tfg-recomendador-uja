"""Chat de consola contra el sistema RAG, para evaluarlo a mano (IT-37).

No es la aplicación web de la Fase 3 ni sustituye a la evaluación con métricas
de IT-38: es la herramienta para sentarse delante y ver qué contesta el sistema,
que es lo que ninguna cifra enseña. Permite cambiar de modelo sin reiniciar,
para poder comparar candidatos con la misma pregunta.

Arrastra los últimos turnos, y hace falta que los arrastre: una pregunta como
«¿y en primer año?» no menciona la titulación, así que incrustada sola recupera
fragmentos de las doce. Pero solo cuando la pregunta lo necesita: si ya nombra
una titulación, se incrusta sola, porque arrastrarla llegó a desviar la
recuperación entera hacia el tema anterior. Es lo mínimo para poder encadenar
tres preguntas; el manejo serio de la conversación es de la Fase 3.

Cada sesión se guarda en un fichero de notas **fuera del repositorio**, para
poder releer después qué se preguntó y qué se respondió sin que las pruebas
acaben versionadas.

Uso::

    py scripts/chat_rag.py                       # modelo por defecto
    py scripts/chat_rag.py --modelo ministral-3:3b
    py scripts/chat_rag.py --k 5 --grado "Grado en Ingeniería Informática"
    py scripts/chat_rag.py --sin-registro        # no escribe el fichero

Dentro del chat:

    /modelo <nombre>    cambia de modelo generativo
    /k <n>              cambia cuántos fragmentos se recuperan
    /grado <nombre>     acota la búsqueda a una titulación ("/grado ." la quita)
    /fuentes            muestra los fragmentos de la última respuesta
    /olvida             vacía la conversación y empieza de cero
    /salir
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from tfg_uja.conversacion import Conversacion  # noqa: E402
from tfg_uja.generador import (  # noqa: E402
    ErrorDelModelo,
    cortesia,
    responder,
)
from tfg_uja.incrustaciones import MODELO, incrustador_de_consultas  # noqa: E402
from tfg_uja.recuperador import (  # noqa: E402
    K_MAXIMO,
    Fragmento,
    ModeloDiscrepante,
    TitulacionDesconocida,
    abrir_indice,
    acotar_por_distancia,
    catalogo_del_indice,
    distancia_del_indice,
    recuperar,
)

#: Turnos que se recuerdan. Tres son los que el autor encadena al probar; más
#: no aportan y sí llenan la ventana con respuestas viejas.
TURNOS_RECORDADOS = 3

#: Dónde se guardan las sesiones. Está fuera del repositorio a propósito: son
#: pruebas manuales, no material versionable, y algunas contienen respuestas
#: equivocadas que no deben confundirse con el corpus.
CARPETA_REGISTRO = RAIZ.parent / "Notas_TFG" / "pruebas_chat"


def _uno_solo(ambito: list[str]) -> str | None:
    """El ámbito para el prompt, solo si no hay ambigüedad.

    El prompt declara una titulación, no varias: decirle «responde sobre estas
    tres» no acota nada. Cuando la conversación no ha podido reducirlo a una
    ---«electrónica» sitúa en tres titulaciones--- el prompt no declara ámbito
    y quien acota es el filtro, que sí admite la lista entera.

    Args:
        ambito: Titulaciones deducidas de la conversación.

    Returns:
        La única titulación, o ``None`` si hay cero o más de una.
    """
    return ambito[0] if len(ambito) == 1 else None


def formatear_fuentes(fragmentos: list[Fragmento]) -> str:
    """Lista las unidades de las que salió el contexto, sin repetir."""
    vistas: dict[str, float] = {}
    for f in fragmentos:
        vistas.setdefault(f"{f.nombre} ({f.origen})", f.distancia)
    return "\n".join(
        f"    - {nombre}  ·  distancia {d:.3f}" for nombre, d in vistas.items()
    )


def abrir_registro(carpeta: Path, modelo: str, k: int, fragmentos: int) -> Path:
    """Crea el fichero de la sesión y le escribe la cabecera.

    Args:
        carpeta: Carpeta donde se guardan las sesiones.
        modelo: Modelo generativo con el que arranca la sesión.
        k: Cuántos fragmentos se recuperan por consulta.
        fragmentos: Tamaño del índice, para saber contra qué corpus se probó.

    Returns:
        Ruta del fichero recién creado.
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    momento = datetime.now()
    ruta = carpeta / f"sesion_{momento:%Y-%m-%d_%H%M}_{modelo.replace(':', '-')}.md"
    ruta.write_text(
        f"# Sesión de pruebas del chat RAG\n\n"
        f"- **Fecha:** {momento:%d/%m/%Y %H:%M}\n"
        f"- **Modelo generativo:** `{modelo}`\n"
        f"- **Modelo de incrustaciones:** `{MODELO}`\n"
        f"- **Índice:** {fragmentos} fragmentos · K = {k}\n\n"
        f"---\n",
        encoding="utf-8",
    )
    return ruta


def anotar_turno(
    ruta: Path,
    numero: int,
    pregunta: str,
    respuesta: str,
    fragmentos: list[Fragmento],
    modelo: str,
    grado: str | None,
    tiempos: tuple[float, float],
) -> None:
    """Añade un turno al fichero de la sesión.

    Se escribe turno a turno, y no al cerrar, para que una sesión interrumpida
    conserve lo que ya se había preguntado.

    Args:
        ruta: Fichero de la sesión.
        numero: Número de turno, desde 1.
        pregunta: Lo que se preguntó.
        respuesta: Lo que contestó el modelo.
        fragmentos: Fragmentos que formaron el contexto.
        modelo: Modelo que respondió, que puede cambiar dentro de la sesión.
        grado: Titulación a la que estaba acotada la búsqueda, si lo estaba.
        tiempos: Segundos de recuperación y de generación.
    """
    acotado = f" · acotado a «{grado}»" if grado else ""
    fuentes = "\n".join(
        f"| {f.nombre} | {f.origen} | {f.chunk_index + 1}/{f.total_chunks} "
        f"| {f.distancia:.3f} |"
        for f in fragmentos
    )
    with ruta.open("a", encoding="utf-8") as fichero:
        fichero.write(
            f"\n## Turno {numero}\n\n"
            f"**Pregunta:** {pregunta}\n\n"
            f"**Respuesta** (`{modelo}`, recuperar {tiempos[0]:.2f} s, "
            f"generar {tiempos[1]:.2f} s{acotado}):\n\n"
            f"{respuesta}\n\n"
            f"<details><summary>Contexto recuperado "
            f"({len(fragmentos)} fragmentos)</summary>\n\n"
            f"| Unidad | Origen | Parte | Distancia |\n"
            f"| --- | --- | --- | --- |\n{fuentes}\n\n"
            f"</details>\n"
        )


def main(argumentos: list[str]) -> None:
    """Punto de entrada del chat.

    Args:
        argumentos: Argumentos de línea de comandos.
    """
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--indice", default=str(RAIZ / "data" / "indice_lance"))
    analizador.add_argument("--modelo", default="gemma3:latest")
    analizador.add_argument("--k", type=int, default=K_MAXIMO)
    analizador.add_argument("--grado", default=None)
    analizador.add_argument(
        "--curso", default=None, help='acota a un curso, p. ej. "primer"'
    )
    analizador.add_argument(
        "--k-fijo",
        action="store_true",
        help="trae siempre K fragmentos, sin recortar por distancia",
    )
    analizador.add_argument("--registro", default=str(CARPETA_REGISTRO))
    analizador.add_argument("--sin-registro", action="store_true")
    opciones = analizador.parse_args(argumentos)

    ruta_indice = Path(opciones.indice)
    if not ruta_indice.exists():
        sys.exit(
            f"No hay índice en {ruta_indice}.\n"
            f"Constrúyelo con: py -m tfg_uja.indexer data/chunks.json {ruta_indice}"
        )

    print("Cargando el modelo de incrustaciones...")
    incrustar = incrustador_de_consultas(MODELO)
    try:
        tabla = abrir_indice(ruta_indice, MODELO)
    except ModeloDiscrepante as error:
        sys.exit(f"El índice no casa con el modelo: {error}")
    distancia = distancia_del_indice(ruta_indice)
    catalogo = catalogo_del_indice(ruta_indice)
    if not catalogo:
        sys.exit(
            "El índice no declara su catálogo de titulaciones. Reconstrúyelo:\n"
            f"  py -m tfg_uja.indexer data/chunks.json {ruta_indice}"
        )

    modelo = opciones.modelo
    k = opciones.k
    grado = opciones.grado
    curso = opciones.curso
    ultimos: list[Fragmento] = []
    conversacion = Conversacion(catalogo, turnos_recordados=TURNOS_RECORDADOS)
    # Contador propio: el historial se recorta a los últimos turnos, así que su
    # longitud deja de servir para numerarlos en cuanto se pasa del tercero.
    turno = 0

    registro = (
        None
        if opciones.sin_registro
        else abrir_registro(Path(opciones.registro), modelo, k, tabla.count_rows())
    )

    print(f"\nÍndice:  {ruta_indice}  ({tabla.count_rows()} fragmentos, {distancia})")
    print(
        f"Modelo:  {modelo}   ·   K = {k}"
        + (f"   ·   acotado a «{grado}»" if grado else "")
    )
    print(f"Memoria: {TURNOS_RECORDADOS} turnos")
    print(
        "Fragmentos: "
        + (f"K fijo = {k}" if opciones.k_fijo else f"dinámicos, hasta {k}")
        + f"   ·   {len(catalogo)} titulaciones en el índice"
    )
    print(f"Registro: {registro}" if registro else "Registro: desactivado")
    print("Escribe tu pregunta, o /salir para terminar.\n")

    while True:
        try:
            entrada = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not entrada:
            continue

        if entrada.startswith("/"):
            orden, _, resto = entrada.partition(" ")
            resto = resto.strip()
            if orden == "/salir":
                return
            if orden == "/modelo" and resto:
                modelo = resto
                print(f"  modelo → {modelo}\n")
            elif orden == "/k" and resto.isdigit():
                k = int(resto)
                print(f"  K → {k}\n")
            elif orden == "/grado" and resto:
                grado = None if resto == "." else resto
                print(f"  titulación → {grado or 'sin acotar'}\n")
            elif orden == "/fuentes":
                print(formatear_fuentes(ultimos) if ultimos else "  (aún no hay)")
                print()
            elif orden == "/curso" and resto:
                curso = None if resto == "." else resto
                print(f"  curso → {curso or 'sin acotar'}\n")
            elif orden == "/olvida":
                conversacion.olvidar()
                print("  conversación olvidada\n")
            elif orden == "/ambito":
                vigente = conversacion.ambito
                dice = ", ".join(vigente) if vigente else "todavía nada"
                print(f"  de lo que se habla ahora: {dice}\n")
            else:
                print(
                    "  órdenes: /modelo /k /grado /curso /fuentes /ambito "
                    "/olvida /salir\n"
                )
            continue

        t0 = time.perf_counter()
        # La cortesía se resuelve antes de buscar. No es solo ahorro: el
        # registro anotaba los veinte fragmentos que la búsqueda traía para un
        # «gracias» como si hubieran formado el contexto de la respuesta, y no
        # se usa ninguno. Una sesión que documenta un contexto que no existió
        # no sirve para auditar nada.
        fija = cortesia(entrada)
        if fija is not None:
            print(f"\n{fija}\n")
            conversacion.anotar(entrada, fija)
            turno += 1
            ultimos = []
            if registro is not None:
                anotar_turno(
                    registro, turno, entrada, fija, [], modelo, grado, (0.0, 0.0)
                )
            continue

        consulta = conversacion.preparar(entrada)
        try:
            traidos = recuperar(
                consulta.texto,
                tabla,
                incrustar,
                distancia=distancia,
                k=k,
                grado=grado,
                catalogo=catalogo,
                curso=curso,
                ambito=consulta.ambito,
            )
        except TitulacionDesconocida as error:
            print(f"\n  {error}. Las que hay:")
            for t in catalogo:
                print(f"    - {t}")
            print()
            continue
        ultimos = traidos if opciones.k_fijo else acotar_por_distancia(traidos)
        t_recuperar = time.perf_counter() - t0

        t1 = time.perf_counter()
        try:
            respuesta = responder(
                entrada,
                ultimos,
                modelo,
                [(p, "") for p in conversacion.preguntas()],
                ambito=grado or _uno_solo(consulta.ambito),
                catalogo=catalogo,
            )
        except ErrorDelModelo as error:
            # Se avisa y se sigue. Un fallo pasajero del servidor no puede
            # costar la sesion entera: el 18/08/2026 un 500 por falta de
            # memoria, con una descarga de 9 GB en marcha, se llevo por delante
            # la conversacion de pruebas completa.
            print(
                f"\n  [!] {error}\n"
                f"      La pregunta no se ha respondido; puedes repetirla.\n"
            )
            continue
        t_generar = time.perf_counter() - t1

        conversacion.anotar(entrada, respuesta)
        turno += 1

        print(f"\n{respuesta}\n")
        print(
            f"  [{modelo} · recuperar {t_recuperar:.2f} s · "
            f"generar {t_generar:.2f} s · {len(ultimos)} fragmentos]"
        )
        print(formatear_fuentes(ultimos))
        print()

        if registro is not None:
            anotar_turno(
                registro,
                turno,
                entrada,
                respuesta,
                ultimos,
                modelo,
                grado,
                (t_recuperar, t_generar),
            )


if __name__ == "__main__":
    main(sys.argv[1:])

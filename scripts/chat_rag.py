"""Chat de consola contra el sistema RAG, para evaluarlo a mano (IT-37).

No es la aplicación web de la Fase 3 ni sustituye a la evaluación con métricas
de IT-38: es la herramienta para sentarse delante y ver qué contesta el sistema,
que es lo que ninguna cifra enseña. Permite cambiar de modelo sin reiniciar,
para poder comparar candidatos con la misma pregunta.

La conversación la lleva :class:`tfg_uja.conversacion.Conversacion` (IT-106),
que recuerda de qué titulación se habla ---también si la nombró el asistente y
no el estudiante--- y acota la búsqueda con un filtro exacto. Sin eso, «¿y qué
asignaturas tiene en primero?» recuperaba fragmentos de las doce titulaciones.

De qué titulación se habla lo decide el modelo en cada turno
(:mod:`tfg_uja.ambito`), porque las reglas deterministas sabían fijar el sujeto
pero no soltarlo: una vez dentro de una titulación no se salía de ella ni
escribiendo «olvídalo, cuéntame de topografía». Con ``--ambito-determinista`` se
vuelve al mecanismo anterior, que es con lo que se comparan los dos.

Cada sesión se guarda en un fichero de notas **fuera del repositorio**, para
poder releer después qué se preguntó y qué se respondió sin que las pruebas
acaben versionadas.

Uso::

    py scripts/chat_rag.py                       # modelo por defecto
    py scripts/chat_rag.py --modelo ministral-3:3b
    py scripts/chat_rag.py --k 5 --grado "Grado en Ingeniería Informática"
    py scripts/chat_rag.py --sin-registro        # no escribe el fichero
    py scripts/chat_rag.py --ambito-determinista # el mecanismo de antes

Dentro del chat:

    /modelo <nombre>    cambia de modelo generativo
    /k <n>              cambia cuántos fragmentos se recuperan
    /grado <nombre>     acota la búsqueda a una titulación ("/grado ." la quita)
    /curso <nombre>     acota a un curso ("/curso ." lo quita)
    /fuentes            muestra los fragmentos de la última respuesta
    /ambito             dice de qué titulación cree el sistema que se habla
    /olvida             vacía la conversación y empieza de cero
    /salir
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from tfg_uja.dialogo.ambito import Decisor, decisor_con_modelo  # noqa: E402
from tfg_uja.dialogo.conversacion import Conversacion  # noqa: E402
from tfg_uja.dialogo.generador import (  # noqa: E402
    ErrorDelModelo,
    cortesia,
    responder,
)
from tfg_uja.indexacion.incrustaciones import (  # noqa: E402
    MODELO,
    incrustador_de_consultas,
)
from tfg_uja.dialogo.recuperador import (  # noqa: E402
    K_MAXIMO,
    Fragmento,
    ModeloDiscrepante,
    TitulacionDesconocida,
    abrir_indice,
    catalogo_del_indice,
    contexto_para,
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

#: Recordatorio que se imprime cuando la orden tecleada no se reconoce.
AYUDA_ORDENES = "  órdenes: /modelo /k /grado /curso /fuentes /ambito /olvida /salir\n"


@dataclass
class Ajustes:
    """Lo que las órdenes del chat pueden cambiar sin reiniciar la sesión.

    Van juntas porque las cuatro se leen en cada turno y las cambia el mismo
    sitio: sueltas, quien atiende las órdenes tendría que devolver cuatro
    valores para que el bucle los reasignara.

    Attributes:
        modelo: Modelo generativo con el que se responde.
        k: Cuántos fragmentos se recuperan por consulta.
        grado: Titulación a la que se acota la búsqueda, si se acota.
        curso: Curso al que se acota la búsqueda, si se acota.
    """

    modelo: str
    k: int
    grado: str | None
    curso: str | None


@dataclass
class Indice:
    """El índice ya abierto y lo que hace falta para consultarlo.

    Attributes:
        tabla: Tabla del índice vectorial.
        incrustar: Incrustador de consultas.
        distancia: Métrica con la que se construyó el índice.
        catalogo: Titulaciones que declara el índice.
    """

    tabla: Any
    incrustar: Any
    distancia: str
    catalogo: list[str]


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


def _decisor_del_chat(indice: Indice, ajustes: Ajustes) -> Decisor:
    """Decisor de ámbito que respeta el modelo que esté puesto en la sesión.

    Se compone en cada llamada, y no una vez al arrancar, porque ``/modelo``
    cambia el generativo sin reiniciar: con el decisor construido de antemano se
    seguiría decidiendo con el modelo anterior y la sesión estaría comparando
    dos cosas a la vez sin decirlo.

    Args:
        indice: Índice abierto, de donde sale el catálogo.
        ajustes: Opciones de la sesión, que dicen qué modelo está puesto.

    Returns:
        El decisor que se le pasa a la conversación.
    """

    def decidir(
        pregunta: str,
        ambito: list[str],
        ultimo_turno: tuple[str, str] | None,
    ) -> Any:
        elegir = decisor_con_modelo(indice.catalogo, ajustes.modelo)
        return elegir(pregunta, ambito, ultimo_turno)

    return decidir


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


def _analizar_argumentos(argumentos: list[str]) -> argparse.Namespace:
    """Declara y lee las opciones de línea de órdenes.

    Args:
        argumentos: Argumentos de línea de comandos.

    Returns:
        Las opciones ya analizadas.
    """
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--indice", default=str(RAIZ / "data" / "indice_lance"))
    # El modelo del sistema, no el que hubiera a mano: `gemma3:latest` es el de
    # 3,3 GB, descartado por tamaño en el cribado, y arrancar con él significaba
    # que el chat no ejecutaba el sistema que se está midiendo.
    analizador.add_argument("--modelo", default="gemma3:12b")
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
    analizador.add_argument(
        "--ambito-determinista",
        action="store_true",
        help=(
            "no le pregunta al modelo de qué titulación se habla; usa las "
            "reglas de IT-106, que aciertan el seguimiento pero no sueltan "
            "el sujeto"
        ),
    )
    analizador.add_argument("--registro", default=str(CARPETA_REGISTRO))
    analizador.add_argument("--sin-registro", action="store_true")
    return analizador.parse_args(argumentos)


def _preparar_indice(ruta_indice: Path) -> Indice:
    """Abre el índice y comprueba que sirve para conversar.

    Termina el programa, en vez de propagar la excepción, cuando falta el
    índice, cuando no casa con el modelo de incrustaciones o cuando no declara
    su catálogo: sin cualquiera de las tres cosas no hay chat que valga, y el
    mensaje dice cómo arreglarlo.

    Args:
        ruta_indice: Carpeta del índice vectorial.

    Returns:
        El índice abierto, listo para consultar.
    """
    if not ruta_indice.exists():
        sys.exit(
            f"No hay índice en {ruta_indice}.\n"
            f"Constrúyelo con: py -m tfg_uja.indexacion.indexer "
            f"data/chunks.json {ruta_indice}"
        )

    print("Cargando el modelo de incrustaciones...")
    incrustar = incrustador_de_consultas(MODELO)
    try:
        tabla = abrir_indice(ruta_indice, MODELO)
    except ModeloDiscrepante as error:
        sys.exit(f"El índice no casa con el modelo: {error}")
    catalogo = catalogo_del_indice(ruta_indice)
    if not catalogo:
        sys.exit(
            "El índice no declara su catálogo de titulaciones. Reconstrúyelo:\n"
            f"  py -m tfg_uja.indexacion.indexer data/chunks.json {ruta_indice}"
        )
    return Indice(
        tabla=tabla,
        incrustar=incrustar,
        distancia=distancia_del_indice(ruta_indice),
        catalogo=catalogo,
    )


def _imprimir_cabecera(
    ruta_indice: Path,
    indice: Indice,
    ajustes: Ajustes,
    k_fijo: bool,
    registro: Path | None,
    decide_el_modelo: bool,
) -> None:
    """Escribe en pantalla contra qué se está probando.

    Args:
        ruta_indice: Carpeta del índice vectorial.
        indice: Índice ya abierto.
        ajustes: Opciones con las que arranca la sesión.
        k_fijo: Si se traen siempre K fragmentos, sin recortar por distancia.
        registro: Fichero de la sesión, o ``None`` si no se registra.
        decide_el_modelo: Si el ámbito lo decide el modelo en cada turno.
    """
    fragmentos = indice.tabla.count_rows()
    print(f"\nÍndice:  {ruta_indice}  ({fragmentos} fragmentos, {indice.distancia})")
    print(
        f"Modelo:  {ajustes.modelo}   ·   K = {ajustes.k}"
        + (f"   ·   acotado a «{ajustes.grado}»" if ajustes.grado else "")
    )
    print(f"Memoria: {TURNOS_RECORDADOS} turnos")
    print(
        "Ámbito:  "
        + (
            "lo decide el modelo en cada turno (+2-3 s, van en «recuperar»)"
            if decide_el_modelo
            else "reglas deterministas, no se suelta solo"
        )
    )
    print(
        "Fragmentos: "
        + (f"K fijo = {ajustes.k}" if k_fijo else f"dinámicos, hasta {ajustes.k}")
        + f"   ·   {len(indice.catalogo)} titulaciones en el índice"
    )
    print(f"Registro: {registro}" if registro else "Registro: desactivado")
    print("Escribe tu pregunta, o /salir para terminar.\n")


def _atender_orden(
    entrada: str,
    ajustes: Ajustes,
    conversacion: Conversacion,
    ultimos: list[Fragmento],
) -> bool:
    """Ejecuta una orden del chat y dice si hay que terminar la sesión.

    Args:
        entrada: Lo tecleado, que empieza por ``/``.
        ajustes: Opciones de la sesión, que algunas órdenes cambian.
        conversacion: Conversación en curso.
        ultimos: Fragmentos de la última respuesta, para ``/fuentes``.

    Returns:
        ``True`` si la orden era ``/salir``.
    """
    orden, _, resto = entrada.partition(" ")
    resto = resto.strip()
    if orden == "/salir":
        return True
    if orden == "/modelo" and resto:
        ajustes.modelo = resto
        print(f"  modelo → {ajustes.modelo}\n")
    elif orden == "/k" and resto.isdigit():
        ajustes.k = int(resto)
        print(f"  K → {ajustes.k}\n")
    elif orden == "/grado" and resto:
        ajustes.grado = None if resto == "." else resto
        print(f"  titulación → {ajustes.grado or 'sin acotar'}\n")
    elif orden == "/fuentes":
        print(formatear_fuentes(ultimos) if ultimos else "  (aún no hay)")
        print()
    elif orden == "/curso" and resto:
        ajustes.curso = None if resto == "." else resto
        print(f"  curso → {ajustes.curso or 'sin acotar'}\n")
    elif orden == "/olvida":
        conversacion.olvidar()
        print("  conversación olvidada\n")
    elif orden == "/ambito":
        vigente = conversacion.ambito
        dice = ", ".join(vigente) if vigente else "todavía nada"
        print(f"  de lo que se habla ahora: {dice}\n")
    else:
        print(AYUDA_ORDENES)
    return False


def _recuperar_contexto(
    entrada: str,
    conversacion: Conversacion,
    ajustes: Ajustes,
    indice: Indice,
    k_fijo: bool,
) -> tuple[list[Fragmento], list[str]] | None:
    """Busca en el índice el contexto con el que se responderá.

    Args:
        entrada: La pregunta tal como se tecleó.
        conversacion: Conversación en curso, que resuelve el seguimiento.
        ajustes: Opciones de la sesión.
        indice: Índice ya abierto.
        k_fijo: Si se traen siempre K fragmentos, sin recortar por distancia.

    Returns:
        ``(fragmentos, ámbito de la consulta)``, o ``None`` si se nombró una
        titulación que no existe, en cuyo caso ya se ha avisado por pantalla.
    """
    consulta = conversacion.preparar(entrada)
    opciones = {
        "distancia": indice.distancia,
        "k": ajustes.k,
        "grado": ajustes.grado,
        "catalogo": indice.catalogo,
        "curso": ajustes.curso,
        "ambito": consulta.ambito,
    }
    try:
        if k_fijo:
            traidos = recuperar(
                consulta.texto, indice.tabla, indice.incrustar, **opciones
            )
        else:
            traidos = contexto_para(
                consulta.texto,
                indice.tabla,
                indice.incrustar,
                respaldo=consulta.respaldo,
                abierta=consulta.abierta,
                **opciones,
            )
    except TitulacionDesconocida as error:
        print(f"\n  {error}. Las que hay:")
        for t in indice.catalogo:
            print(f"    - {t}")
        print()
        return None
    return traidos, consulta.ambito


def _generar_respuesta(
    entrada: str,
    fragmentos: list[Fragmento],
    ajustes: Ajustes,
    conversacion: Conversacion,
    catalogo: list[str],
    ambito: list[str],
) -> str | None:
    """Pide la respuesta al modelo generativo.

    Args:
        entrada: La pregunta tal como se tecleó.
        fragmentos: Contexto recuperado.
        ajustes: Opciones de la sesión.
        conversacion: Conversación en curso, de la que sale el historial.
        catalogo: Titulaciones que declara el índice.
        ambito: Titulaciones deducidas de la conversación.

    Returns:
        La respuesta, o ``None`` si el turno se pierde y hay que seguir
        preguntando, en cuyo caso ya se ha avisado por pantalla.
    """
    try:
        return responder(
            entrada,
            fragmentos,
            ajustes.modelo,
            [(p, "") for p in conversacion.preguntas()],
            ambito=ajustes.grado or _uno_solo(ambito),
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
        return None
    except KeyboardInterrupt:
        # Ctrl+C durante la generacion cancela la pregunta, no la sesion.
        # Los modelos grandes tardan minutos y el tope de espera es de
        # diez; sin esto, cortar una respuesta lenta obligaba a rearrancar
        # y a recargar el indice, y se perdian los turnos ya anotados.
        print("\n  [!] pregunta cancelada. Sigue preguntando o /salir.\n")
        return None


def _mostrar_respuesta(
    respuesta: str,
    ajustes: Ajustes,
    fragmentos: list[Fragmento],
    tiempos: tuple[float, float],
) -> None:
    """Escribe en pantalla la respuesta, sus tiempos y sus fuentes.

    Args:
        respuesta: Lo que contestó el modelo.
        ajustes: Opciones de la sesión, de donde sale el modelo que respondió.
        fragmentos: Contexto que formó la respuesta.
        tiempos: Segundos de recuperación y de generación.
    """
    print(f"\n{respuesta}\n")
    print(
        f"  [{ajustes.modelo} · recuperar {tiempos[0]:.2f} s · "
        f"generar {tiempos[1]:.2f} s · {len(fragmentos)} fragmentos]"
    )
    print(formatear_fuentes(fragmentos))
    print()


def main(argumentos: list[str]) -> None:
    """Punto de entrada del chat.

    Args:
        argumentos: Argumentos de línea de comandos.
    """
    opciones = _analizar_argumentos(argumentos)
    ruta_indice = Path(opciones.indice)
    indice = _preparar_indice(ruta_indice)

    ajustes = Ajustes(
        modelo=opciones.modelo,
        k=opciones.k,
        grado=opciones.grado,
        curso=opciones.curso,
    )
    ultimos: list[Fragmento] = []
    conversacion = Conversacion(
        indice.catalogo,
        turnos_recordados=TURNOS_RECORDADOS,
        decisor=(
            None if opciones.ambito_determinista else _decisor_del_chat(indice, ajustes)
        ),
    )
    # Contador propio: el historial se recorta a los últimos turnos, así que su
    # longitud deja de servir para numerarlos en cuanto se pasa del tercero.
    turno = 0

    registro = (
        None
        if opciones.sin_registro
        else abrir_registro(
            Path(opciones.registro),
            ajustes.modelo,
            ajustes.k,
            indice.tabla.count_rows(),
        )
    )
    _imprimir_cabecera(
        ruta_indice,
        indice,
        ajustes,
        opciones.k_fijo,
        registro,
        conversacion.decisor is not None,
    )

    while True:
        try:
            entrada = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not entrada:
            continue

        if entrada.startswith("/"):
            if _atender_orden(entrada, ajustes, conversacion, ultimos):
                return
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
                    registro,
                    turno,
                    entrada,
                    fija,
                    [],
                    ajustes.modelo,
                    ajustes.grado,
                    (0.0, 0.0),
                )
            continue

        contexto = _recuperar_contexto(
            entrada, conversacion, ajustes, indice, opciones.k_fijo
        )
        if contexto is None:
            continue
        ultimos, ambito = contexto
        t_recuperar = time.perf_counter() - t0

        t1 = time.perf_counter()
        respuesta = _generar_respuesta(
            entrada, ultimos, ajustes, conversacion, indice.catalogo, ambito
        )
        if respuesta is None:
            continue
        t_generar = time.perf_counter() - t1

        conversacion.anotar(entrada, respuesta)
        turno += 1

        _mostrar_respuesta(respuesta, ajustes, ultimos, (t_recuperar, t_generar))

        if registro is not None:
            anotar_turno(
                registro,
                turno,
                entrada,
                respuesta,
                ultimos,
                ajustes.modelo,
                ajustes.grado,
                (t_recuperar, t_generar),
            )


if __name__ == "__main__":
    main(sys.argv[1:])

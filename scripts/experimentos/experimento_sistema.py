"""Evaluación del sistema completo sobre el banco de IT-37.

Se separa de ``experimento_generacion.py`` porque mide otra cosa. Aquel compara
modelos generativos con preguntas sueltas; este pasa por el mismo tubo que el
chat ---conversación, recuperación, cortesía, verificación--- y comprueba
familias que allí no existen: turnos encadenados, peticiones de consejo,
mensajes que no preguntan nada y preguntas ajenas al dominio.

**Ninguna comprobación usa un modelo que juzgue a otro.** Las seis son
comparaciones de cadena contra el corpus o contra las respuestas fijas del
generador, de modo que cualquiera puede recalcularlas.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "scripts"))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from experimento_generacion import (  # noqa: E402
    acierto_escalar,
    asignaturas_del_corpus,
    menciones_del_corpus,
    universo,
    version_del_servidor,
)

from tfg_uja import generador  # noqa: E402
from tfg_uja.conversacion import (  # noqa: E402
    Conversacion,
    titulaciones_de_la_respuesta,
)
from tfg_uja.generador import responder  # noqa: E402
from tfg_uja.text_cleaner import palabras  # noqa: E402
from tfg_uja.incrustaciones import MODELO, incrustador_de_consultas  # noqa: E402
from tfg_uja.recuperador import (  # noqa: E402
    K_MAXIMO,
    abrir_indice,
    catalogo_del_indice,
    contexto_para,
    distancia_del_indice,
)
from tfg_uja.verificacion import (  # noqa: E402
    cotejar_listado,
    titulaciones_inventadas,
    titulaciones_nombradas,
)

#: Modelos que se comparan cuando no se dice otra cosa. Uno de cada talla
#: ---8B, 9B y 12B--- y de tres familias distintas, para que la comparación no
#: dependa de las decisiones de un solo fabricante.
MODELOS: tuple[str, ...] = (
    "ministral-8b:latest",
    "qwen3.5:9b",
    "gemma3:12b",
)


def corregir_fija(respuesta: str, esperado: list[str]) -> tuple[bool, str]:
    """Comprueba que la respuesta sea literalmente una de las del generador.

    Args:
        respuesta: Lo que devolvió el sistema.
        esperado: Nombre de la constante del módulo, p. ej. ``RESPUESTA_SALUDO``.

    Returns:
        ``(acierta, detalle)``.
    """
    quería = getattr(generador, esperado[0])
    if respuesta == quería:
        return True, ""
    return False, f"esperaba {esperado[0]}"


def corregir_sin_invencion(respuesta: str, catalogo: list[str]) -> tuple[bool, str]:
    """Comprueba que recomiende algo real y no se invente nada.

    Es lo único exigible a una recomendación sin ponerse a juzgar si el consejo
    es acertado, que es justo lo que este trabajo no puede medir sin un juez.

    Args:
        respuesta: Lo que devolvió el sistema.
        catalogo: Titulaciones que declara el índice.

    Returns:
        ``(acierta, detalle)``.
    """
    inventadas = titulaciones_inventadas(respuesta, catalogo)
    if inventadas:
        return False, "inventa " + ", ".join(sorted(inventadas))
    if respuesta == generador.RESPUESTA_TITULACION_INVENTADA:
        return False, "la barrera retiró la respuesta"
    if not titulaciones_nombradas(respuesta):
        return False, "no recomienda ninguna titulación"
    return True, ""


#: Respuestas fijas que ya son un rechazo correcto por construcción.
_RECHAZOS_FIJOS: tuple[str, ...] = (
    generador.RESPUESTA_SIN_CONTEXTO,
    generador.RESPUESTA_OTRA_UNIVERSIDAD,
)

#: Con qué se niega en español. No solo con «no»: el modelo niega tanto con
#: «ninguna de las titulaciones encaja» como con «no encaja ninguna», y las dos
#: son la misma respuesta. Buscar una palabra concreta mediría cómo está
#: redactado el rechazo en vez de si rechaza.
_NEGACIONES: frozenset[str] = frozenset(
    {"no", "ninguna", "ninguno", "ningun", "nada", "tampoco", "nunca", "ni"}
)


def corregir_rechazo(respuesta: str, catalogo: list[str]) -> tuple[bool, str]:
    """Comprueba que a una pregunta ajena se le responda que no.

    La primera versión de este criterio exigía que la respuesta **no nombrara
    ninguna titulación**, y con eso daba por fallada la mejor de las tres que se
    midieron: «No, no puedes estudiar Medicina en la Escuela Politécnica
    Superior de Jaén. Las titulaciones que ofrece son...» seguida de la lista
    correcta. Enumerar lo que sí hay después de negar lo que no hay es mejor
    servicio, no un error, y un criterio que lo penaliza mide la parquedad en
    vez del acierto.

    Lo que sí hay que exigir son dos cosas comprobables: que no aparezca
    ninguna titulación inventada y que la respuesta **niegue**. Una que
    empezara «Sí, puedes estudiar Medicina aquí» no lleva negación y es
    exactamente el fallo que este criterio busca.

    La negación no se busca solo como la palabra «no». La versión anterior lo
    hacía y daba por fallada esta respuesta, que es un rechazo impecable:
    «ninguna de las titulaciones que ofrece la Escuela encaja con tus
    intereses. Todas son de ingeniería y no tienen relación con el ámbito
    legal». La negación estaba en «ninguna», y en la segunda frase. Un criterio
    que exige una palabra concreta mide la redacción y no el rechazo, que es el
    mismo defecto que la precisión del cribado tuvo antes de IT-110.

    Args:
        respuesta: Lo que devolvió el sistema.
        catalogo: Titulaciones que declara el índice.

    Returns:
        ``(acierta, detalle)``.
    """
    if respuesta in _RECHAZOS_FIJOS:
        return True, ""
    inventadas = titulaciones_inventadas(respuesta, catalogo)
    if inventadas:
        return False, "inventa " + ", ".join(sorted(inventadas))
    apertura = re.split("[.!?" + chr(10) + "]", respuesta, maxsplit=2)[:2]
    if not (palabras(" ".join(apertura)) & _NEGACIONES):
        return False, "no niega lo preguntado"
    return True, ""


def corregir_ambito(
    respuesta: str, pregunta: dict[str, Any], catalogo: list[str]
) -> tuple[bool, str]:
    """Comprueba que la respuesta hable de la titulación que toca.

    Es la comprobación que habría detectado el fallo del 19/08/2026, cuando a
    una pregunta sobre las optativas de Organización Industrial el sistema
    contestó con las quince de Ingeniería Mecánica: quince nombres reales, cero
    invenciones y la titulación equivocada.

    Args:
        respuesta: Lo que devolvió el sistema.
        pregunta: Entrada del banco, con ``esperado`` y ``prohibido``.
        catalogo: Titulaciones que declara el índice.

    Returns:
        ``(acierta, detalle)``.
    """
    dichas = set(titulaciones_de_la_respuesta(respuesta, catalogo))
    for prohibida in pregunta.get("prohibido", []):
        if prohibida in dichas:
            return False, f"habla de «{prohibida}», que no es"
    for querida in pregunta["esperado"]:
        if querida not in dichas:
            return False, f"no nombra «{querida}»"
    return True, ""


def corregir(
    respuesta: str,
    pregunta: dict[str, Any],
    catalogo: list[str],
    nombres: set[str],
) -> dict[str, Any]:
    """Aplica a una respuesta el criterio que le corresponde.

    Args:
        respuesta: Lo que devolvió el sistema.
        pregunta: Entrada del banco.
        catalogo: Titulaciones que declara el índice.
        nombres: Todo lo que el corpus nombra, para la precisión.

    Returns:
        Lo medido, listo para guardar en el registro.
    """
    criterio = pregunta["respuesta"]
    salida: dict[str, Any] = {"criterio": criterio}
    if criterio == "conjunto":
        precision, cobertura, inventadas, omitidas = cotejar_listado(
            respuesta, pregunta["esperado"], nombres
        )
        # Una respuesta en prosa no enumera nada y su precisión es None: no se
        # ha encontrado nada falso, se ha medido sobre nada. Entonces quien
        # decide es la cobertura, que se mide sobre el texto entero y no
        # depende del formato. Exigir `precision == 1.0` suspendía respuestas
        # correctas por no usar viñetas.
        precision_ok = precision is None or precision == 1.0
        salida.update(
            precision=precision,
            cobertura=cobertura,
            omitidas=len(omitidas),
            acierta=precision_ok and cobertura == 1.0,
            detalle=(
                f"{len(omitidas)} omitidas, {len(inventadas)} de más"
                if not precision_ok or cobertura < 1.0
                else ""
            ),
        )
        return salida
    if criterio == "escalar":
        acierta, dicho = acierto_escalar(
            respuesta, pregunta["esperado"][0], pregunta["familia"]
        )
        salida.update(acierta=acierta, detalle=dicho)
        return salida
    if criterio == "fija":
        acierta, detalle = corregir_fija(respuesta, pregunta["esperado"])
    elif criterio == "sin_invencion":
        acierta, detalle = corregir_sin_invencion(respuesta, catalogo)
    elif criterio == "rechazo":
        acierta, detalle = corregir_rechazo(respuesta, catalogo)
    elif criterio == "ambito":
        acierta, detalle = corregir_ambito(respuesta, pregunta, catalogo)
    else:
        raise ValueError(f"criterio desconocido: {criterio}")
    salida.update(acierta=acierta, detalle=detalle)
    return salida


def responder_entrada(
    pregunta: dict[str, Any],
    modelo: str,
    tabla: Any,
    incrustar: Any,
    distancia: str,
    catalogo: list[str],
) -> tuple[str, float, int, int, dict[str, object]]:
    """Pasa una entrada del banco por el sistema, turno a turno.

    La conversación se lleva con la misma clase que usa el chat, de modo que el
    ámbito, la anáfora y la memoria de turnos funcionan igual que en una sesión
    real. Lo que se corrige es **el último turno**: los anteriores existen para
    construir el estado.

    Args:
        pregunta: Entrada del banco.
        modelo: Nombre del modelo en el servidor local.
        tabla: Tabla del índice ya abierta.
        incrustar: Incrustador de consultas.
        distancia: Métrica del índice.
        catalogo: Titulaciones que declara el índice.

    Returns:
        ``(respuesta del último turno, segundos, fragmentos, turnos, traza)``,
        donde la traza trae lo que la barrera haya retirado en el último turno.
    """
    turnos = pregunta.get("turnos") or [pregunta["pregunta"]]
    conversacion = Conversacion(catalogo)
    respuesta = ""
    fragmentos: list[Any] = []
    traza: dict[str, object] = {}
    t0 = time.perf_counter()
    for texto in turnos:
        consulta = conversacion.preparar(texto)
        fragmentos = contexto_para(
            consulta.texto,
            tabla,
            incrustar,
            respaldo=consulta.respaldo,
            distancia=distancia,
            k=K_MAXIMO,
            catalogo=catalogo,
            ambito=consulta.ambito,
        )
        # Se vacía en cada turno porque lo que se corrige es el último: una
        # retirada de un turno intermedio contaría contra una respuesta que no
        # es la suya.
        traza.clear()
        respuesta = responder(
            texto,
            fragmentos,
            modelo,
            historial=[(p, "") for p in conversacion.preguntas()],
            ambito=consulta.ambito[0] if len(consulta.ambito) == 1 else None,
            catalogo=catalogo,
            traza=traza,
        )
        conversacion.anotar(texto, respuesta)
    return respuesta, time.perf_counter() - t0, len(fragmentos), len(turnos), traza


def ejecutar(
    modelos: list[str],
    banco: list[dict[str, Any]],
    tabla: Any,
    incrustar: Any,
    distancia: str,
    catalogo: list[str],
    nombres: set[str],
    registro: Path,
) -> list[dict[str, Any]]:
    """Mide todos los modelos sobre todo el banco.

    Args:
        modelos: Modelos a comparar.
        banco: Entradas del banco.
        tabla: Tabla del índice.
        incrustar: Incrustador de consultas.
        distancia: Métrica del índice.
        catalogo: Titulaciones del índice.
        nombres: Todo lo que el corpus nombra.
        registro: Fichero donde se van guardando las respuestas.

    Returns:
        Todas las filas medidas.
    """
    version = version_del_servidor()
    print(f"Servidor de inferencia: {version}")
    filas: list[dict[str, Any]] = []
    with registro.open("w", encoding="utf-8") as fichero:
        for modelo in modelos:
            print(f"\n=== {modelo} — {len(banco)} entradas ===")
            for i, pregunta in enumerate(banco, 1):
                respuesta, segundos, cuantos, turnos, traza = responder_entrada(
                    pregunta, modelo, tabla, incrustar, distancia, catalogo
                )
                fila = {
                    "modelo": modelo,
                    "servidor": version,
                    "id": pregunta["id"],
                    "familia": pregunta["familia"],
                    "turnos": turnos,
                    "segundos": round(segundos, 2),
                    "fragmentos": cuantos,
                    "respuesta": respuesta,
                    **traza,
                    **corregir(respuesta, pregunta, catalogo, nombres),
                }
                filas.append(fila)
                fichero.write(json.dumps(fila, ensure_ascii=False) + "\n")
                fichero.flush()
                marca = "ok " if fila["acierta"] else "FALLA"
                print(
                    f"  [{i}/{len(banco)}] {pregunta['id']:<12} {marca} "
                    f"{segundos:5.1f}s {fila['familia']}"
                    + (f" — {fila['detalle']}" if fila["detalle"] else "")
                )
    return filas


def informe(filas: list[dict[str, Any]], destino: Path) -> None:
    """Escribe el informe en Markdown.

    Args:
        filas: Todas las respuestas medidas.
        destino: Fichero de salida.
    """
    modelos = sorted({f["modelo"] for f in filas})
    familias = sorted({f["familia"] for f in filas})
    lineas = [
        "# Evaluación del sistema completo (IT-37)",
        "",
        "> Lo escribe `scripts/experimento_sistema.py`. **No editar a mano.**",
        "",
        f"- Entradas del banco: **{len(filas) // max(len(modelos), 1)}**",
        f"- Servidor de inferencia: {filas[0]['servidor'] if filas else '?'}",
        "",
        "## Aciertos por modelo",
        "",
        "| Modelo | Aciertos | Tasa | Mediana (s) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for modelo in modelos:
        suyas = [f for f in filas if f["modelo"] == modelo]
        aciertos = sum(1 for f in suyas if f["acierta"])
        tiempos = sorted(f["segundos"] for f in suyas)
        mediana = tiempos[len(tiempos) // 2] if tiempos else 0.0
        lineas.append(
            f"| `{modelo}` | {aciertos} de {len(suyas)} | "
            f"{aciertos / len(suyas):.3f} | {mediana:.1f} |"
        )

    lineas += [
        "",
        "## Aciertos por familia",
        "",
        "| Familia | n | " + " | ".join(f"`{m}`" for m in modelos) + " |",
        "| --- | ---: | " + " | ".join("---:" for _ in modelos) + " |",
    ]
    for familia in familias:
        de_familia = [f for f in filas if f["familia"] == familia]
        n = len(de_familia) // max(len(modelos), 1)
        celdas = []
        for modelo in modelos:
            suyas = [f for f in de_familia if f["modelo"] == modelo]
            celdas.append(f"{sum(1 for f in suyas if f['acierta'])}/{len(suyas)}")
        lineas.append(f"| {familia} | {n} | " + " | ".join(celdas) + " |")

    lineas += ["", "## Lo que falla", ""]
    fallos = [f for f in filas if not f["acierta"]]
    if not fallos:
        lineas.append("Nada.")
    for fallo in fallos:
        lineas.append(
            f"- `{fallo['modelo']}` · {fallo['id']} ({fallo['familia']})"
            + (f": {fallo['detalle']}" if fallo["detalle"] else "")
        )
    lineas.append("")
    destino.write_text("\n".join(lineas), encoding="utf-8")
    print(f"\nInforme escrito en {destino}")


def main(argumentos: list[str] | None = None) -> None:
    """Punto de entrada."""
    analizador = argparse.ArgumentParser(description="Evaluación del sistema.")
    analizador.add_argument("--modelos", nargs="+", default=list(MODELOS))
    analizador.add_argument(
        "--banco", default=str(RAIZ / "eval" / "preguntas_sistema.json")
    )
    analizador.add_argument("--indice", default=str(RAIZ / "data" / "indice_lance"))
    analizador.add_argument("--datos", default=str(RAIZ / "data" / "grados.json"))
    analizador.add_argument("--registro", required=True)
    analizador.add_argument("--salida", required=True)
    analizador.add_argument(
        "--recorregir",
        action="store_true",
        help="vuelve a corregir lo ya guardado sin llamar a ningún modelo",
    )
    opciones = analizador.parse_args(argumentos)

    banco = json.loads(Path(opciones.banco).read_text(encoding="utf-8"))["preguntas"]
    datos = json.loads(Path(opciones.datos).read_text(encoding="utf-8"))
    ruta_indice = Path(opciones.indice)
    catalogo = catalogo_del_indice(ruta_indice)
    nombres = universo(
        catalogo, asignaturas_del_corpus(datos), menciones_del_corpus(datos)
    )

    if opciones.recorregir:
        # Los criterios cambian cuando aparece un defecto en ellos, y ha
        # aparecido nueve veces. Volver a generar 141 respuestas para aplicar un
        # corrector nuevo cuesta horas y además cambiaría lo medido; recorregir
        # lo guardado deja todas las tandas comparables con la misma vara.
        registro = Path(opciones.registro)
        preguntas = {p["id"]: p for p in banco}
        filas = []
        for linea in registro.read_text(encoding="utf-8").splitlines():
            fila = json.loads(linea)
            fila.update(
                corregir(fila["respuesta"], preguntas[fila["id"]], catalogo, nombres)
            )
            filas.append(fila)
        registro.write_text(
            "".join(json.dumps(f, ensure_ascii=False) + chr(10) for f in filas),
            encoding="utf-8",
        )
        print(f"Recorregidas {len(filas)} respuestas sin llamar a ningún modelo.")
        informe(filas, Path(opciones.salida))
        return

    print("Cargando el modelo de incrustaciones...")
    filas = ejecutar(
        opciones.modelos,
        banco,
        abrir_indice(ruta_indice, MODELO),
        incrustador_de_consultas(MODELO),
        distancia_del_indice(ruta_indice),
        catalogo,
        nombres,
        Path(opciones.registro),
    )
    informe(filas, Path(opciones.salida))


if __name__ == "__main__":
    main()

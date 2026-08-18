"""Compara cómo se resuelve una pregunta de seguimiento (IT-106).

Mide tres formas de convertir una pregunta de seguimiento en algo que se pueda
buscar, sobre las mismas conversaciones y el mismo índice:

``sola``
    Se incrusta la pregunta tal cual, sin mirar la conversación. Es el estado
    en que nació el chat.
``concatenada``
    Se pega delante la última pregunta que nombraba una titulación. Es el
    mecanismo de IT-37, y es contra el que la tarjeta pide comparar.
``conversacion``
    Se deduce el sujeto ---también de las respuestas--- y se acota la búsqueda
    con un filtro exacto. Es lo que introduce IT-106.

**Las conversaciones no están escritas a mano.** Se derivan de
``data/grados.json``, igual que el banco de preguntas: para cada una se sabe por
construcción qué unidad tendría que recuperar el sistema, así que no hace falta
que nadie juzgue el resultado.

Las respuestas del asistente en las conversaciones de la familia ``sujeto`` sí
son de plantilla: hacen falta porque el fallo que se mide es precisamente que
la titulación aparezca **solo en la respuesta**, y generarlas con un modelo
metería su variabilidad en un experimento que no va de eso.

Uso::

    py scripts/experimento_conversacion.py
    py scripts/experimento_conversacion.py --k 10
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Iterable

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from tfg_uja.conversacion import (  # noqa: E402
    Conversacion,
    titulaciones_de_la_pregunta,
)
from tfg_uja.incrustaciones import MODELO, incrustador_de_consultas  # noqa: E402
from tfg_uja.recuperador import (  # noqa: E402
    K_MAXIMO,
    abrir_indice,
    catalogo_del_indice,
    distancia_del_indice,
    recuperar,
)

#: Cursos consecutivos, para poder encadenar «¿y en segundo?». Se escriben con
#: el rótulo exacto de la fuente, que es el que lleva el encabezado del
#: fragmento.
SEGUIDOS: list[tuple[str, str, str]] = [
    ("Primer curso", "Segundo curso", "¿Y en segundo?"),
    ("Segundo curso", "Tercer curso", "¿Y en tercero?"),
    ("Tercer curso", "Cuarto curso", "¿Y en cuarto?"),
]

#: Nombre corto con el que un estudiante se refiere a cada titulación. Sale del
#: propio catálogo: es la palabra distintiva más larga de su nombre.
Conversaciones = list[dict[str, Any]]


def _unidad(grado: str, curso: str) -> str:
    """Encabezado del fragmento de plan de estudios de ese grado y curso."""
    return f"Asignaturas obligatorias de {curso.lower()} del {grado}"


def _nombre_corto(grado: str, catalogo: list[str]) -> str | None:
    """Palabra con la que se distingue a esa titulación de las demás.

    Se busca la más larga de las que sitúan **solo** en ella: si la palabra
    sitúa en varias, la conversación derivada sería ambigua y no serviría para
    medir nada.

    Args:
        grado: Titulación.
        catalogo: Titulaciones que declara el índice.

    Returns:
        La palabra, o ``None`` si ninguna la identifica en solitario.
    """
    from tfg_uja.recuperador import palabras_distintivas
    from tfg_uja.text_cleaner import palabras

    candidatas = sorted(palabras(grado) & palabras_distintivas(catalogo), key=len)
    for palabra in reversed(candidatas):
        if titulaciones_de_la_pregunta(palabra, catalogo) == [grado]:
            return palabra
    return None


def construir_conversaciones(
    datos: list[dict[str, Any]], catalogo: list[str]
) -> Conversaciones:
    """Deriva las conversaciones de prueba del dataset.

    Args:
        datos: Contenido de ``grados.json``.
        catalogo: Titulaciones que declara el índice.

    Returns:
        Conversaciones, cada una con sus turnos y la unidad que el último
        turno tendría que recuperar.
    """
    no_optativas = {"FB", "OB", "OB-IS", "OB-SI", "OB-TI", "TFG"}
    por_curso: dict[tuple[str, str], int] = collections.Counter()
    for a in datos:
        if a.get("tipo") != "asignatura":
            continue
        if a["tipo_asignatura"] in no_optativas and a["curso"]:
            por_curso[(a["grado"], a["curso"])] += 1

    con_plan = sorted({g for g, _ in por_curso} & set(catalogo))
    conversaciones: Conversaciones = []

    # 1. El sujeto lo introduce el asistente, no el estudiante.
    for grado in con_plan:
        if (grado, "Primer curso") not in por_curso:
            continue
        conversaciones.append(
            {
                "familia": "sujeto_en_la_respuesta",
                "turnos": [
                    (
                        "Estoy en bachillerato y no sé qué estudiar",
                        f"Por lo que cuentas podrías mirar el {grado}.",
                    ),
                ],
                "pregunta": "¿Y qué asignaturas tiene en primero?",
                "esperado": _unidad(grado, "Primer curso"),
            }
        )

    # 2. Seguimiento que solo cambia el curso.
    for grado in con_plan:
        for desde, hasta, pregunta in SEGUIDOS:
            if (grado, desde) not in por_curso or (grado, hasta) not in por_curso:
                continue
            conversaciones.append(
                {
                    "familia": "cambia_el_curso",
                    "turnos": [
                        (
                            f"¿Qué asignaturas se cursan en {desde.lower()} "
                            f"del {grado}?",
                            "...",
                        )
                    ],
                    "pregunta": pregunta,
                    "esperado": _unidad(grado, hasta),
                }
            )

    # 3. Seguimiento que solo cambia la titulación.
    for anterior, grado in zip(con_plan, con_plan[1:] + con_plan[:1]):
        corto = _nombre_corto(grado, catalogo)
        if corto is None or (grado, "Primer curso") not in por_curso:
            continue
        if (anterior, "Primer curso") not in por_curso:
            continue
        conversaciones.append(
            {
                "familia": "cambia_la_titulacion",
                "turnos": [
                    (
                        f"¿Qué asignaturas se cursan en primer curso del "
                        f"{anterior}?",
                        "...",
                    )
                ],
                "pregunta": f"¿Y en {corto}?",
                "esperado": _unidad(grado, "Primer curso"),
            }
        )
    return conversaciones


def _concatenada(pregunta: str, turnos: list[tuple[str, str]], catalogo: list[str]):
    """Reproduce el mecanismo de IT-37, que es la línea base a batir."""
    if titulaciones_de_la_pregunta(pregunta, catalogo):
        return pregunta, []
    sujeto = next(
        (p for p, _ in reversed(turnos) if titulaciones_de_la_pregunta(p, catalogo)),
        None,
    )
    return (f"{sujeto} {pregunta}" if sujeto else pregunta), []


def _sola(pregunta: str, turnos: list[tuple[str, str]], catalogo: list[str]):
    """Sin mirar la conversación: el estado en que nació el chat."""
    return pregunta, []


def _conversacion(pregunta: str, turnos: list[tuple[str, str]], catalogo: list[str]):
    """Lo que introduce IT-106."""
    c = Conversacion(catalogo)
    for p, r in turnos:
        c.anotar(p, r)
    consulta = c.preparar(pregunta)
    return consulta.texto, consulta.ambito


ESTRATEGIAS = {
    "sola": _sola,
    "concatenada": _concatenada,
    "conversacion": _conversacion,
}


def _posicion(unidades: Iterable[str], esperado: str) -> int | None:
    """Puesto en el que aparece la unidad esperada, desde 1."""
    for i, nombre in enumerate(unidades, 1):
        if nombre == esperado:
            return i
    return None


def main(argumentos: list[str]) -> None:
    """Punto de entrada."""
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--indice", default=str(RAIZ / "data" / "indice_lance"))
    analizador.add_argument("--dataset", default=str(RAIZ / "data" / "grados.json"))
    analizador.add_argument("--k", type=int, default=K_MAXIMO)
    opciones = analizador.parse_args(argumentos)

    ruta = Path(opciones.indice)
    catalogo = catalogo_del_indice(ruta)
    datos = json.loads(Path(opciones.dataset).read_text(encoding="utf-8"))
    conversaciones = construir_conversaciones(datos, catalogo)

    reparto = collections.Counter(c["familia"] for c in conversaciones)
    print(f"Conversaciones derivadas del dataset: {len(conversaciones)}")
    for familia, n in sorted(reparto.items()):
        print(f"   {familia:<24} {n:>3}")
    print(f"\nÍndice: {ruta.name} · K = {opciones.k} · modelo {MODELO}\n")

    incrustar = incrustador_de_consultas(MODELO)
    tabla = abrir_indice(ruta, MODELO)
    distancia = distancia_del_indice(ruta)

    resultados: dict[str, dict[str, list[float]]] = {}
    coste: dict[str, list[float]] = collections.defaultdict(list)

    for nombre, estrategia in ESTRATEGIAS.items():
        aciertos: dict[str, list[float]] = collections.defaultdict(list)
        for caso in conversaciones:
            t0 = time.perf_counter()
            texto, ambito = estrategia(caso["pregunta"], caso["turnos"], catalogo)
            coste[nombre].append((time.perf_counter() - t0) * 1000)
            traidos = recuperar(
                texto,
                tabla,
                incrustar,
                distancia=distancia,
                k=opciones.k,
                catalogo=catalogo,
                ambito=ambito or None,
            )
            puesto = _posicion((f.nombre for f in traidos), caso["esperado"])
            aciertos[caso["familia"]].append(0.0 if puesto is None else 1.0)
            aciertos[f"{caso['familia']}:mrr"].append(
                0.0 if puesto is None else 1.0 / puesto
            )
        resultados[nombre] = aciertos

    familias = sorted(reparto)
    print(
        f"{'estrategia':<14}"
        + "".join(f"{f[:18]:>20}" for f in familias)
        + f"{'TOTAL':>9}"
    )
    print("-" * (14 + 20 * len(familias) + 9))
    for nombre in ESTRATEGIAS:
        fila = f"{nombre:<14}"
        todos: list[float] = []
        for familia in familias:
            valores = resultados[nombre][familia]
            todos.extend(valores)
            fila += f"{statistics.mean(valores):>20.3f}"
        fila += f"{statistics.mean(todos):>9.3f}"
        print(fila)

    print("\nMRR de la unidad esperada (mismo orden de familias):")
    for nombre in ESTRATEGIAS:
        fila = f"{nombre:<14}"
        todos = []
        for familia in familias:
            valores = resultados[nombre][f"{familia}:mrr"]
            todos.extend(valores)
            fila += f"{statistics.mean(valores):>20.3f}"
        fila += f"{statistics.mean(todos):>9.3f}"
        print(fila)

    print("\nCoste de preparar la consulta (ms por pregunta):")
    for nombre, tiempos in coste.items():
        print(
            f"   {nombre:<14} mediana {statistics.median(tiempos):.3f} · "
            f"máximo {max(tiempos):.3f}"
        )


if __name__ == "__main__":
    main(sys.argv[1:])

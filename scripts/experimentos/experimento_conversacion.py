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

RAIZ = Path(__file__).resolve().parent.parent.parent
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
    palabras_distintivas,
    recuperar,
)
from tfg_uja.text_cleaner import palabras  # noqa: E402

#: Cursos consecutivos, para poder encadenar «¿y en segundo?». Se escriben con
#: el rótulo exacto de la fuente, que es el que lleva el encabezado del
#: fragmento.
SEGUIDOS: list[tuple[str, str, str]] = [
    ("Primer curso", "Segundo curso", "¿Y en segundo?"),
    ("Segundo curso", "Tercer curso", "¿Y en tercero?"),
    ("Tercer curso", "Cuarto curso", "¿Y en cuarto?"),
]

#: Una conversación de prueba: sus turnos, la pregunta de seguimiento y la
#: unidad que esa pregunta tendría que recuperar.
Conversaciones = list[dict[str, Any]]

#: Ancho de las columnas de familia en las tablas de resultados.
_COLUMNA = 20

#: Ancho de la primera columna, la del nombre de la estrategia.
_ETIQUETA = 14

#: Ancho de la columna final, la del total.
_TOTAL = 9


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
    candidatas = sorted(palabras(grado) & palabras_distintivas(catalogo), key=len)
    for palabra in reversed(candidatas):
        if titulaciones_de_la_pregunta(palabra, catalogo) == [grado]:
            return palabra
    return None


def _asignaturas_por_curso(datos: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    """Cuenta las asignaturas no optativas de cada par (titulación, curso).

    Solo se usa para saber qué pares existen: una conversación sobre un curso
    que la fuente no publica no tendría unidad esperada que recuperar.

    Args:
        datos: Contenido de ``grados.json``.

    Returns:
        Cuántas asignaturas tiene cada par que exista de verdad.
    """
    no_optativas = {"FB", "OB", "OB-IS", "OB-SI", "OB-TI", "TFG"}
    por_curso: dict[tuple[str, str], int] = collections.Counter()
    for a in datos:
        if a.get("tipo") != "asignatura":
            continue
        if a["tipo_asignatura"] in no_optativas and a["curso"]:
            por_curso[(a["grado"], a["curso"])] += 1
    return por_curso


def _sujeto_en_la_respuesta(
    con_plan: list[str], por_curso: dict[tuple[str, str], int]
) -> Conversaciones:
    """Conversaciones en las que el sujeto lo introduce el asistente.

    Es el caso que ninguna heurística sobre la pregunta puede resolver: el
    estudiante no ha nombrado la titulación en ningún momento.

    Args:
        con_plan: Titulaciones con plan publicado y presentes en el índice.
        por_curso: Pares (titulación, curso) que existen.

    Returns:
        Una conversación por titulación con primer curso.
    """
    return [
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
        for grado in con_plan
        if (grado, "Primer curso") in por_curso
    ]


def _cambia_el_curso(
    con_plan: list[str], por_curso: dict[tuple[str, str], int]
) -> Conversaciones:
    """Conversaciones de seguimiento en las que solo cambia el curso.

    Args:
        con_plan: Titulaciones con plan publicado y presentes en el índice.
        por_curso: Pares (titulación, curso) que existen.

    Returns:
        Una conversación por cada salto de curso que la fuente publique.
    """
    conversaciones: Conversaciones = []
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
    return conversaciones


def _cambia_la_titulacion(
    con_plan: list[str], por_curso: dict[tuple[str, str], int], catalogo: list[str]
) -> Conversaciones:
    """Conversaciones de seguimiento en las que solo cambia la titulación.

    Se encadena cada titulación con la siguiente de la lista, y la última con
    la primera, para no tener que escoger pares a mano.

    Args:
        con_plan: Titulaciones con plan publicado y presentes en el índice.
        por_curso: Pares (titulación, curso) que existen.
        catalogo: Titulaciones que declara el índice.

    Returns:
        Una conversación por cada titulación que tenga nombre corto propio.
    """
    conversaciones: Conversaciones = []
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
    por_curso = _asignaturas_por_curso(datos)
    con_plan = sorted({g for g, _ in por_curso} & set(catalogo))
    return [
        *_sujeto_en_la_respuesta(con_plan, por_curso),
        *_cambia_el_curso(con_plan, por_curso),
        *_cambia_la_titulacion(con_plan, por_curso, catalogo),
    ]


def _concatenada(
    pregunta: str, turnos: list[tuple[str, str]], catalogo: list[str]
) -> tuple[str, list[str]]:
    """Reproduce el mecanismo de IT-37, que es la línea base a batir."""
    if titulaciones_de_la_pregunta(pregunta, catalogo):
        return pregunta, []
    sujeto = next(
        (p for p, _ in reversed(turnos) if titulaciones_de_la_pregunta(p, catalogo)),
        None,
    )
    return (f"{sujeto} {pregunta}" if sujeto else pregunta), []


def _sola(
    pregunta: str, turnos: list[tuple[str, str]], catalogo: list[str]
) -> tuple[str, list[str]]:
    """Sin mirar la conversación: el estado en que nació el chat."""
    return pregunta, []


def _conversacion(
    pregunta: str, turnos: list[tuple[str, str]], catalogo: list[str]
) -> tuple[str, list[str]]:
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


def _medir_estrategia(
    estrategia: Any,
    conversaciones: Conversaciones,
    tabla: Any,
    incrustar: Any,
    distancia: str,
    catalogo: list[str],
    k: int,
    coste: list[float],
) -> dict[str, list[float]]:
    """Pasa una estrategia por todas las conversaciones.

    Args:
        estrategia: Función que convierte la pregunta en consulta.
        conversaciones: Casos derivados del dataset.
        tabla: Tabla del índice ya abierta.
        incrustar: Incrustador de consultas.
        distancia: Métrica del índice.
        catalogo: Titulaciones que declara el índice.
        k: Cuántos fragmentos se recuperan.
        coste: Lista a la que se añaden los milisegundos de cada preparación.

    Returns:
        Por familia, los aciertos; y bajo la clave ``familia:mrr``, el inverso
        del puesto en que apareció la unidad esperada.
    """
    aciertos: dict[str, list[float]] = collections.defaultdict(list)
    for caso in conversaciones:
        t0 = time.perf_counter()
        texto, ambito = estrategia(caso["pregunta"], caso["turnos"], catalogo)
        coste.append((time.perf_counter() - t0) * 1000)
        traidos = recuperar(
            texto,
            tabla,
            incrustar,
            distancia=distancia,
            k=k,
            catalogo=catalogo,
            ambito=ambito or None,
        )
        puesto = _posicion((f.nombre for f in traidos), caso["esperado"])
        aciertos[caso["familia"]].append(0.0 if puesto is None else 1.0)
        aciertos[f"{caso['familia']}:mrr"].append(
            0.0 if puesto is None else 1.0 / puesto
        )
    return aciertos


def _imprimir_filas(
    resultados: dict[str, dict[str, list[float]]],
    familias: list[str],
    sufijo: str = "",
) -> None:
    """Escribe una fila por estrategia, con la media de cada familia.

    Args:
        resultados: Medidas de cada estrategia, por familia.
        familias: Familias, en el orden en que se imprimen.
        sufijo: Qué medida se lee de cada familia (``":mrr"`` para el MRR).
    """
    for nombre in ESTRATEGIAS:
        fila = f"{nombre:<{_ETIQUETA}}"
        todos: list[float] = []
        for familia in familias:
            valores = resultados[nombre][f"{familia}{sufijo}"]
            todos.extend(valores)
            fila += f"{statistics.mean(valores):>{_COLUMNA}.3f}"
        fila += f"{statistics.mean(todos):>{_TOTAL}.3f}"
        print(fila)


def _imprimir_reparto(conversaciones: Conversaciones) -> collections.Counter[str]:
    """Dice cuántas conversaciones salieron de cada familia.

    Args:
        conversaciones: Casos derivados del dataset.

    Returns:
        El recuento por familia, que luego ordena las columnas de las tablas.
    """
    reparto = collections.Counter(c["familia"] for c in conversaciones)
    print(f"Conversaciones derivadas del dataset: {len(conversaciones)}")
    for familia, n in sorted(reparto.items()):
        print(f"   {familia:<24} {n:>3}")
    return reparto


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

    reparto = _imprimir_reparto(conversaciones)
    print(f"\nÍndice: {ruta.name} · K = {opciones.k} · modelo {MODELO}\n")

    incrustar = incrustador_de_consultas(MODELO)
    tabla = abrir_indice(ruta, MODELO)
    distancia = distancia_del_indice(ruta)

    resultados: dict[str, dict[str, list[float]]] = {}
    coste: dict[str, list[float]] = collections.defaultdict(list)

    for nombre, estrategia in ESTRATEGIAS.items():
        resultados[nombre] = _medir_estrategia(
            estrategia,
            conversaciones,
            tabla,
            incrustar,
            distancia,
            catalogo,
            opciones.k,
            coste[nombre],
        )

    familias = sorted(reparto)
    print(
        f"{'estrategia':<{_ETIQUETA}}"
        + "".join(f"{f[:18]:>{_COLUMNA}}" for f in familias)
        + f"{'TOTAL':>{_TOTAL}}"
    )
    print("-" * (_ETIQUETA + _COLUMNA * len(familias) + _TOTAL))
    _imprimir_filas(resultados, familias)

    print("\nMRR de la unidad esperada (mismo orden de familias):")
    _imprimir_filas(resultados, familias, ":mrr")

    print("\nCoste de preparar la consulta (ms por pregunta):")
    for nombre, tiempos in coste.items():
        print(
            f"   {nombre:<{_ETIQUETA}} mediana {statistics.median(tiempos):.3f} · "
            f"máximo {max(tiempos):.3f}"
        )


if __name__ == "__main__":
    main(sys.argv[1:])

"""Verificador del conjunto de evaluación (IT-27) contra el dataset real.

Comprueba que cada selector de unidad anotado en
``eval/preguntas_evaluacion.json`` resuelve a al menos un chunk del
``data/chunks.json`` real, e imprime la cobertura por tipo de pregunta y por
grado. Igual que los demás verificadores, se ejecuta SOLO en local (data/ no
está versionado y no existe en un checkout limpio de CI):

    py scripts/verificadores/check_evalset.py

Acepta rutas alternativas como argumentos::

    py scripts/verificadores/check_evalset.py otro/evalset.json otra/ruta/chunks.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Las rutas se resuelven relativas a la raíz del repositorio, no a scripts/.
RAIZ = Path(__file__).resolve().parent.parent.parent
RUTA_EVAL = RAIZ / "eval" / "preguntas_evaluacion.json"
RUTA_CHUNKS = RAIZ / "data" / "chunks.json"

#: Claves admitidas en un selector de unidad. Se comprueban de forma estricta,
#: y no por comodidad: una clave mal escrita no rompe nada visible. Poner
#: ``grados`` en vez de ``grado`` supera el ``"grado" not in selector`` de
#: ``chunks_de_unidad`` y el selector deja de filtrar por titulación **en
#: silencio**; pasaría a resolver a todas las asignaturas homónimas del centro
#: y a inflar el número de relevantes de esa pregunta sin que nadie lo note.
_CLAVES_SELECTOR = frozenset({"origen", "nombre", "grado"})

#: Claves sin las que un selector no señala ninguna unidad.
_CLAVES_SELECTOR_OBLIGATORIAS = frozenset({"origen", "nombre"})

#: Campos que toda pregunta debe traer. Sin esta comprobación, un fichero mal
#: editado a mano revienta con un ``KeyError`` a medio recorrido y deja el
#: informe sin escribir, en vez de decir qué pregunta está mal.
_CLAVES_PREGUNTA = frozenset({"id", "tipo", "pregunta", "relevantes"})

#: Tipo de pregunta cuya respuesta correcta es no recuperar nada (IT-86).
#: Se nombra una vez y se usa en los dos sitios que lo tratan aparte: la
#: comprobación de esquema y el recuento de cobertura.
FUERA_DE_DOMINIO = "fuera_de_dominio"

#: Número mínimo de preguntas. Es un suelo heredado del diseño de IT-27, no el
#: tamaño de diseño del conjunto: hoy son 50. Sirve para detectar que alguien
#: se ha dejado media lista, no para acreditar potencia estadística.
_MINIMO_PREGUNTAS = 30


def chunks_de_unidad(
    selector: dict[str, str], chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Devuelve los chunks que pertenecen a la unidad que describe el selector.

    Args:
        selector: Unidad anotada: ``origen``, ``nombre`` y, opcionalmente,
            ``grado`` para desambiguar.
        chunks: Chunks del dataset completo.

    Returns:
        Chunks cuya unidad coincide con el selector.
    """
    return [
        chunk
        for chunk in chunks
        if chunk["origen"] == selector["origen"]
        and chunk["nombre"] == selector["nombre"]
        and ("grado" not in selector or selector["grado"] in chunk["grados"])
    ]


def _errores_de_selectores(etiqueta: str, relevantes: list[dict]) -> list[str]:
    """Comprueba la forma de los selectores de una sola pregunta.

    Args:
        etiqueta: Identificador de la pregunta, para poder nombrarla.
        relevantes: Selectores de unidad anotados en esa pregunta.

    Returns:
        Un mensaje por cada problema de forma; vacío si están todos bien.
    """
    errores: list[str] = []
    vistos: list[tuple] = []
    for selector in relevantes:
        faltan = sorted(_CLAVES_SELECTOR_OBLIGATORIAS - set(selector))
        if faltan:
            errores.append(f"{etiqueta}: un selector no trae {faltan}")
            continue
        desconocidas = sorted(set(selector) - _CLAVES_SELECTOR)
        if desconocidas:
            errores.append(
                f"{etiqueta}: el selector {selector['nombre']!r} trae la(s) "
                f"clave(s) {desconocidas}, que este verificador no mira. Si "
                f"era `grado` mal escrito, el selector no está filtrando "
                f"por titulación y resuelve a todas"
            )
        clave = tuple(sorted(selector.items()))
        if clave in vistos:
            errores.append(
                f"{etiqueta}: el selector {selector['nombre']!r} está "
                f"repetido; sus chunks contarían dos veces"
            )
        vistos.append(clave)
    return errores


def errores_de_esquema(preguntas: list[dict[str, Any]]) -> list[str]:
    """Comprueba la forma de cada pregunta antes de resolver sus selectores.

    Va aparte y va primero porque el resto del verificador indexa campos por
    su nombre: una pregunta a la que le falte ``relevantes``, o un selector sin
    ``origen``, aborta el recorrido con un ``KeyError`` a mitad de camino y
    deja sin escribir el informe que diría qué pregunta hay que arreglar.

    Args:
        preguntas: Preguntas tal como vienen del fichero de evaluación.

    Returns:
        Un mensaje por cada problema de forma; vacío si todas están bien.
    """
    errores: list[str] = []
    for posicion, pregunta in enumerate(preguntas):
        etiqueta = pregunta.get("id", f"(pregunta {posicion} sin id)")

        ausentes = sorted(_CLAVES_PREGUNTA - set(pregunta))
        if ausentes:
            errores.append(f"{etiqueta}: le faltan los campos {ausentes}")
            continue

        relevantes = pregunta["relevantes"]
        # Las de fuera de dominio (IT-86) son el caso contrario: su lista vacía
        # es la anotación correcta, porque lo que se les pide al sistema es que
        # no recupere nada. Quedan fuera de Recall@K y de MRR por el mismo
        # motivo que hunde a las demás, y se miden con su propio criterio.
        if pregunta["tipo"] == FUERA_DE_DOMINIO:
            if relevantes:
                errores.append(
                    f"{etiqueta}: es de fuera de dominio y anota "
                    f"{len(relevantes)} unidad(es) relevante(s). Si hay algo "
                    f"que recuperar, la pregunta no es de fuera de dominio"
                )
            continue

        # Una pregunta sin unidades anotadas no mide nada: ningún chunk puede
        # ser relevante, así que aporta un 0 fijo a Recall@K y a MRR y hunde
        # las dos métricas sin que haya fallado el recuperador.
        if not relevantes:
            errores.append(
                f"{etiqueta}: no anota ninguna unidad relevante, así que "
                f"cuenta como fallo pase lo que pase y baja las métricas sin "
                f"que el recuperador tenga la culpa"
            )
            continue

        errores += _errores_de_selectores(etiqueta, relevantes)
    return errores


def unidades_por_nombre(
    chunks: list[dict[str, Any]],
) -> dict[tuple[str, str], set[tuple[str, ...]]]:
    """Agrupa las unidades del corpus por ``(origen, nombre)``.

    Todos los fragmentos de una misma unidad comparten su lista de
    titulaciones, porque salen de un único item del dataset. Así, dos juegos
    de titulaciones distintos bajo el mismo ``(origen, nombre)`` son dos
    unidades distintas que se llaman igual, y un selector que no diga a cuál
    apunta las recogerá todas.

    Args:
        chunks: Fragmentos del corpus completo.

    Returns:
        Para cada ``(origen, nombre)``, los juegos de titulaciones distintos
        que aparecen con ese nombre.
    """
    unidades: dict[tuple[str, str], set[tuple[str, ...]]] = {}
    for chunk in chunks:
        clave = (chunk["origen"], chunk["nombre"])
        unidades.setdefault(clave, set()).add(tuple(sorted(chunk["grados"])))
    return unidades


def _informar_procedencia(procedencia: dict) -> None:
    """Muestra de qué extracción y de qué curso es el corpus consultado.

    Args:
        procedencia: Item ``procedencia`` del ``chunks.json``, o vacío si el
            fichero se generó antes de IT-90.
    """
    if procedencia.get("fecha_extraccion"):
        cursos = ", ".join(procedencia.get("cursos") or []) or "sin determinar"
        print(
            f"Procedencia del corpus: extraccion "
            f"{procedencia['fecha_extraccion']} | curso(s) {cursos}"
        )
    else:
        print("Procedencia del corpus: sin determinar (dataset anterior a IT-90).")


def _resolver_selectores(
    preguntas: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> tuple[list[str], set[str], set[str]]:
    """Resuelve cada selector contra el corpus y anota lo que alcanza.

    Args:
        preguntas: Preguntas ya validadas de forma.
        chunks: Fragmentos del corpus completo.

    Returns:
        Los errores encontrados, las titulaciones alcanzadas al resolver y las
        titulaciones que algún selector nombra explícitamente.
    """
    unidades = unidades_por_nombre(chunks)
    errores: list[str] = []
    alcanzados: set[str] = set()
    nombrados: set[str] = set()
    for pregunta in preguntas:
        for selector in pregunta["relevantes"]:
            if "grado" in selector:
                nombrados.add(selector["grado"])
            encontrados = chunks_de_unidad(selector, chunks)
            if not encontrados:
                errores.append(
                    f"{pregunta['id']}: el selector {selector} no resuelve "
                    "a ningún chunk del dataset"
                )
                continue
            # Un selector sin `grado` sobre un nombre que se repite en varias
            # titulaciones no señala una unidad: las señala todas. Los
            # fragmentos de las otras entran como relevantes y el Recall sale
            # más alto de lo que corresponde. En el corpus del 05/08/2026 hay
            # 14 nombres así ---«Prácticas externas», «Trabajo fin de Grado»,
            # «Estadística»---, y ningún selector cae hoy sobre ellos.
            juegos = unidades[(selector["origen"], selector["nombre"])]
            if "grado" not in selector and len(juegos) > 1:
                errores.append(
                    f"{pregunta['id']}: el selector {selector['nombre']!r} es "
                    f"ambiguo: hay {len(juegos)} unidades distintas con ese "
                    f"nombre y sin `grado` las recoge todas. Añade `grado`"
                )
            for chunk in encontrados:
                alcanzados.update(chunk["grados"])
    return errores, alcanzados, nombrados


def _informar_cobertura(
    preguntas: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    alcanzados: set[str],
    nombrados: set[str],
) -> None:
    """Imprime cuántas preguntas hay de cada tipo y qué titulaciones cubren.

    Se dan dos cifras de titulaciones y no una. «Grados cubiertos» decía 11/11
    contando también las titulaciones a las que ninguna pregunta apunta y que
    solo aparecen porque comparten una guía con otra: sobre el corpus del
    05/08/2026, las cuatro dobles entran así. Que una asignatura suya salga
    recuperada al preguntar por Mecánica no acredita que el conjunto pruebe esa
    titulación.

    Args:
        preguntas: Preguntas del conjunto de evaluación.
        chunks: Fragmentos del corpus completo.
        alcanzados: Titulaciones alcanzadas al resolver los selectores.
        nombrados: Titulaciones que algún selector nombra explícitamente.
    """
    grados_corpus = {g for c in chunks for g in c["grados"]}
    por_tipo: dict[str, int] = {}
    for pregunta in preguntas:
        por_tipo[pregunta["tipo"]] = por_tipo.get(pregunta["tipo"], 0) + 1

    fuera = por_tipo.get(FUERA_DE_DOMINIO, 0)
    print(f"Preguntas: {len(preguntas)}")
    print(f"Por tipo: {por_tipo}")
    if fuera:
        print(
            f"  De ellas {fuera} son de fuera de dominio "
            f"({100 * fuera / len(preguntas):.1f} %). No entran en Recall@K "
            f"ni en MRR: su criterio es el contrario, rechazar es acierto."
        )
    print(
        f"Titulaciones del corpus: {len(grados_corpus)} | "
        f"nombradas en algún selector: {len(nombrados)} | "
        f"alcanzadas al resolver: {len(alcanzados)}"
    )
    for grado in sorted(grados_corpus - alcanzados):
        print(f"  SIN CUBRIR: {grado}")
    for grado in sorted(alcanzados - nombrados):
        print(f"  SOLO POR ARRASTRE (ninguna pregunta la nombra): {grado}")


def main(argv: list[str] | None = None) -> int:
    """Valida el conjunto de evaluación y muestra sus estadísticas.

    Args:
        argv: Ruta del conjunto de evaluación y del corpus de fragmentos; por
            defecto ``eval/preguntas_evaluacion.json`` y ``data/chunks.json``.
            Los otros tres verificadores ya admitían rutas alternativas: sin
            ellas, este solo se podía ejercitar contra el corpus real, que no
            está versionado y no existe en CI.

    Returns:
        0 si todas las comprobaciones pasan; 1 en caso contrario.
    """
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    argumentos = argv if argv is not None else sys.argv[1:]
    ruta_eval = Path(argumentos[0]) if len(argumentos) > 0 else RUTA_EVAL
    ruta_chunks = Path(argumentos[1]) if len(argumentos) > 1 else RUTA_CHUNKS

    evalset = json.loads(ruta_eval.read_text(encoding="utf-8"))
    items = json.loads(ruta_chunks.read_text(encoding="utf-8"))
    # El item de procedencia (IT-90) no es contenido recuperable: se separa
    # por tipo, nunca por posición.
    chunks = [i for i in items if i.get("tipo") == "chunk"]
    procedencia: dict = next((i for i in items if i.get("tipo") == "procedencia"), {})
    _informar_procedencia(procedencia)
    preguntas = evalset["preguntas"]

    # El esquema va antes que todo lo demás: si una pregunta está mal formada,
    # resolver sus selectores aborta con KeyError y no se llega a informar de
    # nada. Con errores de forma no se sigue adelante, porque las cifras que
    # saldrían estarían calculadas sobre un fichero que ya se sabe roto.
    errores_forma = errores_de_esquema(preguntas)
    if errores_forma:
        print("\nERRORES DE FORMA (no se comprueba nada más hasta arreglarlos):")
        for error in errores_forma:
            print(f"  - {error}")
        return 1

    errores: list[str] = []
    if len(preguntas) < _MINIMO_PREGUNTAS:
        errores.append(
            f"solo hay {len(preguntas)} preguntas (mínimo {_MINIMO_PREGUNTAS})"
        )

    ids = [p["id"] for p in preguntas]
    if len(ids) != len(set(ids)):
        errores.append("hay ids de pregunta duplicados")

    errores_resolucion, alcanzados, nombrados = _resolver_selectores(preguntas, chunks)
    errores += errores_resolucion

    _informar_cobertura(preguntas, chunks, alcanzados, nombrados)

    if errores:
        print("\nERRORES:")
        for error in errores:
            print(f"  - {error}")
        return 1
    print("\nTodo correcto: todos los selectores resuelven contra el dataset.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

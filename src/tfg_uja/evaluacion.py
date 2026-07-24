"""Métricas de recuperación para el experimento comparativo de embeddings (IT-28).

Calcula Recall@K y MRR de un modelo de embeddings sobre el conjunto de
evaluación de IT-27 (``eval/preguntas_evaluacion.json``), a partir de los
chunks reales del dataset (``data/chunks.json``).

El emparejamiento pregunta -> chunks relevantes reutiliza el mismo criterio
que ``scripts/check_evalset.py`` (``origen``, ``nombre`` y, si lo lleva el
selector, ``grado`` dentro de la lista paralela ``grados`` del chunk): ambos
deben coincidir porque son dos lecturas del mismo contrato de datos.

Este módulo solo calcula métricas a partir de vectores ya calculados; no
descarga ni ejecuta ningún modelo de embeddings (eso lo hace
``scripts/experimento_embeddings.py``, que sí necesita red y la dependencia
opcional ``sentence-transformers``). Así las pruebas de este módulo son
deterministas y no requieren red, igual que ``test_indexer.py``.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

#: Firma de la función de incrustación: recibe una lista de textos y
#: devuelve un vector de números reales por texto, en el mismo orden.
Incrustador = Callable[[list[str]], list[list[float]]]


def chunks_relevantes(
    pregunta: dict[str, Any], chunks: list[dict[str, Any]]
) -> set[int]:
    """Índices (posición en ``chunks``) relevantes para una pregunta.

    Une los chunks que resuelve cada selector de ``pregunta["relevantes"]``:
    una pregunta puede anotar varias unidades (p. ej. P-008, que pregunta por
    las salidas de cuatro grados a la vez).

    Args:
        pregunta: Item del conjunto de evaluación, con su lista
            ``relevantes`` de selectores ``(origen, nombre[, grado])``.
        chunks: Chunks completos del dataset, en el mismo orden que se van a
            incrustar (el índice de esta lista es el identificador usado en
            el ranking).

    Returns:
        Conjunto de índices de ``chunks`` que satisfacen algún selector.
    """
    relevantes: set[int] = set()
    for selector in pregunta["relevantes"]:
        for indice, chunk in enumerate(chunks):
            if (
                chunk["origen"] == selector["origen"]
                and chunk["nombre"] == selector["nombre"]
                and ("grado" not in selector or selector["grado"] in chunk["grados"])
            ):
                relevantes.add(indice)
    return relevantes


def rankear(
    vector_pregunta: list[float], vectores_chunks: list[list[float]]
) -> list[int]:
    """Ordena los índices de chunk de mayor a menor similitud coseno.

    Args:
        vector_pregunta: Incrustación de la pregunta.
        vectores_chunks: Incrustaciones de todos los chunks, en el mismo
            orden que el dataset.

    Returns:
        Índices de ``vectores_chunks`` ordenados de más a menos similar.
    """
    consulta = np.asarray(vector_pregunta, dtype=np.float64)
    matriz = np.asarray(vectores_chunks, dtype=np.float64)
    norma_consulta = np.linalg.norm(consulta)
    normas_chunks = np.linalg.norm(matriz, axis=1)
    # Denominador a 1 donde la norma es 0 (vector nulo): evita división por
    # cero: la similitud de un vector nulo con cualquier otro es 0, no NaN.
    denominador = normas_chunks * norma_consulta
    denominador[denominador == 0] = 1.0
    similitudes = (matriz @ consulta) / denominador
    return list(np.argsort(-similitudes))


def recall_en_k(ranking: list[int], relevantes: set[int], k: int) -> float:
    """Fracción de chunks relevantes que aparecen entre los ``k`` primeros.

    Definición estándar de Recall@K: ``|relevantes ∩ top-k| / |relevantes|``.
    Como 189 de las 892 unidades del dataset están fragmentadas en varios
    chunks (IT-08/IT-09), esta definición SÍ puede penalizar una pregunta
    cuya unidad relevante ocupe más de un chunk y solo se recupere uno: es
    intencional, refleja mejor la cobertura real que un simple acierto/fallo.

    Args:
        ranking: Índices de chunk ordenados por similitud descendente.
        relevantes: Índices de chunk considerados relevantes para la
            pregunta (no puede ser vacío: toda pregunta del conjunto de
            evaluación anota al menos un selector que resuelve a un chunk).
        k: Punto de corte del ranking.

    Returns:
        Valor en ``[0, 1]``.

    Raises:
        ValueError: Si ``relevantes`` está vacío (pregunta sin gold standard,
            no evaluable).
    """
    if not relevantes:
        raise ValueError("una pregunta sin chunks relevantes no es evaluable")
    recuperados = set(ranking[:k])
    return len(recuperados & relevantes) / len(relevantes)


def mrr_de_pregunta(ranking: list[int], relevantes: set[int]) -> float:
    """Recíproco de la posición (1-indexada) del primer chunk relevante.

    Args:
        ranking: Índices de chunk ordenados por similitud descendente.
        relevantes: Índices de chunk considerados relevantes.

    Returns:
        ``1/posición`` del primer acierto, o ``0.0`` si ninguno de los
        chunks del ranking es relevante.
    """
    for posicion, indice in enumerate(ranking, start=1):
        if indice in relevantes:
            return 1.0 / posicion
    return 0.0


def evaluar_modelo(
    chunks: list[dict[str, Any]],
    preguntas: list[dict[str, Any]],
    incrustar_chunks: Incrustador,
    incrustar_preguntas: Incrustador,
    ks: tuple[int, ...] = (3, 5),
) -> dict[str, Any]:
    """Evalúa un modelo de embeddings ya cargado sobre el conjunto de IT-27.

    Recibe dos funciones de incrustación en lugar de una porque algunos
    modelos (p. ej. la familia E5) son asimétricos: exigen anteponer
    prefijos distintos a la consulta y al documento para rendir según lo
    documentado. Los modelos simétricos simplemente pasan la misma función
    dos veces.

    Args:
        chunks: Chunks completos del dataset (``data/chunks.json``).
        preguntas: Preguntas del conjunto de evaluación
            (``eval/preguntas_evaluacion.json``).
        incrustar_chunks: Función de incrustación para el lado documento.
        incrustar_preguntas: Función de incrustación para el lado consulta.
        ks: Valores de K para Recall@K.

    Returns:
        Diccionario con ``"agregados"`` (medias de ``recall@k`` y ``mrr``
        sobre todas las preguntas) y ``"detalle"`` (una fila por pregunta,
        para poder auditar casos concretos).
    """
    vectores_chunks = incrustar_chunks([chunk["texto"] for chunk in chunks])
    vectores_preguntas = incrustar_preguntas([p["pregunta"] for p in preguntas])

    detalle: list[dict[str, Any]] = []
    acumulado: dict[str, list[float]] = {f"recall@{k}": [] for k in ks}
    acumulado["mrr"] = []

    for pregunta, vector_pregunta in zip(preguntas, vectores_preguntas):
        relevantes = chunks_relevantes(pregunta, chunks)
        ranking = rankear(vector_pregunta, vectores_chunks)
        fila: dict[str, Any] = {"id": pregunta["id"], "tipo": pregunta["tipo"]}
        for k in ks:
            valor = recall_en_k(ranking, relevantes, k)
            fila[f"recall@{k}"] = valor
            acumulado[f"recall@{k}"].append(valor)
        valor_mrr = mrr_de_pregunta(ranking, relevantes)
        fila["mrr"] = valor_mrr
        acumulado["mrr"].append(valor_mrr)
        detalle.append(fila)

    agregados = {
        clave: sum(valores) / len(valores) for clave, valores in acumulado.items()
    }
    return {"agregados": agregados, "detalle": detalle}

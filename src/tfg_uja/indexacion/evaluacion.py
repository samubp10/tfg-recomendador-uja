"""Métricas de recuperación para el experimento comparativo de embeddings (IT-28)."""

from __future__ import annotations

from typing import Any, Callable, Final

import numpy as np

from tfg_uja.invariantes import exigir

#: Firma de la función de incrustación: recibe una lista de textos y
#: devuelve un vector de números reales por texto, en el mismo orden.
Incrustador = Callable[[list[str]], list[list[float]]]


#: Tipo de pregunta cuya respuesta correcta es no recuperar nada (IT-86).
FUERA_DE_DOMINIO: Final[str] = "fuera_de_dominio"


def chunks_relevantes(
    pregunta: dict[str, Any], chunks: list[dict[str, Any]]
) -> set[int]:
    """Índices (posición en ``chunks``) relevantes para una pregunta."""
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


def unidad_de_chunk(chunk: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    """Identidad de la unidad semántica a la que pertenece un chunk."""
    return (chunk["origen"], chunk["nombre"], tuple(chunk["grados"]))


def rankear(
    vector_pregunta: list[float], vectores_chunks: list[list[float]]
) -> list[int]:
    """Ordena los índices de chunk de mayor a menor similitud coseno."""
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

    Raises:
        ValueError: Si ``relevantes`` está vacío (pregunta sin gold standard,
            no evaluable).
    """
    if not relevantes:
        raise ValueError("una pregunta sin chunks relevantes no es evaluable")
    recuperados = set(ranking[:k])
    return len(recuperados & relevantes) / len(relevantes)


def recall_de_unidad_en_k(
    ranking: list[int],
    relevantes: set[int],
    chunks: list[dict[str, Any]],
    k: int,
) -> float:
    """Recall@K contando UNIDADES recuperadas, no fragmentos.

    Raises:
        ValueError: Si ``relevantes`` está vacío.
    """
    if not relevantes:
        raise ValueError("una pregunta sin chunks relevantes no es evaluable")
    unidades_relevantes = {unidad_de_chunk(chunks[i]) for i in relevantes}
    recuperadas: list[tuple[str, str, tuple[str, ...]]] = []
    for indice in ranking:
        unidad = unidad_de_chunk(chunks[indice])
        if unidad not in recuperadas:
            recuperadas.append(unidad)
        if len(recuperadas) == k:
            break
    aciertos = len(set(recuperadas) & unidades_relevantes)
    return aciertos / len(unidades_relevantes)


def mrr_de_pregunta(ranking: list[int], relevantes: set[int]) -> float:
    """Recíproco de la posición (1-indexada) del primer chunk relevante."""
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
    """Evalúa un modelo de embeddings ya cargado sobre el conjunto de IT-27."""
    # Las preguntas ajenas no tienen unidades relevantes; su rechazo se mide aparte.
    preguntas = [p for p in preguntas if p["tipo"] != FUERA_DE_DOMINIO]

    vectores_chunks = incrustar_chunks([chunk["texto"] for chunk in chunks])
    vectores_preguntas = incrustar_preguntas([p["pregunta"] for p in preguntas])

    # Comprueba longitudes antes del zip para no evaluar solo una parte del conjunto.
    exigir(
        len(vectores_preguntas) == len(preguntas),
        lambda: (
            f"se han incrustado {len(vectores_preguntas)} vectores para "
            f"{len(preguntas)} preguntas del conjunto de evaluación"
        ),
    )
    exigir(
        len(vectores_chunks) == len(chunks),
        lambda: (
            f"se han incrustado {len(vectores_chunks)} vectores para "
            f"{len(chunks)} chunks del corpus"
        ),
    )

    detalle: list[dict[str, Any]] = []
    metricas = [f"recall@{k}" for k in ks] + [f"recall_unidad@{k}" for k in ks]
    metricas.append("mrr")
    acumulado: dict[str, list[float]] = {m: [] for m in metricas}

    for pregunta, vector_pregunta in zip(preguntas, vectores_preguntas):
        relevantes = chunks_relevantes(pregunta, chunks)
        ranking = rankear(vector_pregunta, vectores_chunks)
        fila: dict[str, Any] = {"id": pregunta["id"], "tipo": pregunta["tipo"]}
        for k in ks:
            fila[f"recall@{k}"] = recall_en_k(ranking, relevantes, k)
            fila[f"recall_unidad@{k}"] = recall_de_unidad_en_k(
                ranking, relevantes, chunks, k
            )
        fila["mrr"] = mrr_de_pregunta(ranking, relevantes)
        for m in metricas:
            acumulado[m].append(fila[m])
        detalle.append(fila)

    agregados = {
        clave: sum(valores) / len(valores) for clave, valores in acumulado.items()
    }

    # Desglosa por tipo: las preguntas de listado tienen techos distintos.
    por_tipo: dict[str, dict[str, float]] = {}
    for tipo in sorted({f["tipo"] for f in detalle}):
        filas = [f for f in detalle if f["tipo"] == tipo]
        por_tipo[tipo] = {"n": float(len(filas))}
        for m in metricas:
            por_tipo[tipo][m] = sum(f[m] for f in filas) / len(filas)

    return {"agregados": agregados, "por_tipo": por_tipo, "detalle": detalle}

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

from typing import Any, Callable, Final

import numpy as np

#: Firma de la función de incrustación: recibe una lista de textos y
#: devuelve un vector de números reales por texto, en el mismo orden.
Incrustador = Callable[[list[str]], list[list[float]]]


#: Tipo de pregunta cuya respuesta correcta es no recuperar nada (IT-86).
FUERA_DE_DOMINIO: Final[str] = "fuera_de_dominio"


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


def unidad_de_chunk(chunk: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    """Identidad de la unidad semántica a la que pertenece un chunk.

    Una unidad es una asignatura, un bloque de salidas o un listado del plan
    de estudios; el troceo puede repartirla en varios chunks, pero sigue
    siendo una sola cosa. Es la misma identidad que usa
    ``scripts/check_chunks.py`` para numerar los chunks de cada unidad.

    Args:
        chunk: Item ``chunk`` del dataset.

    Returns:
        Terna ``(origen, nombre, grados)`` que identifica la unidad.
    """
    return (chunk["origen"], chunk["nombre"], tuple(chunk["grados"]))


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


def recall_de_unidad_en_k(
    ranking: list[int],
    relevantes: set[int],
    chunks: list[dict[str, Any]],
    k: int,
) -> float:
    """Recall@K contando UNIDADES recuperadas, no fragmentos.

    Responde a una pregunta distinta que :func:`recall_en_k`, y la diferencia
    entre las dos es informativa. Por fragmento se mide *cobertura*: cuántos
    de los trozos de la asignatura correcta se han traído. Por unidad se mide
    *acierto*: si se ha encontrado la asignatura correcta, sin castigar que
    haya quedado fuera alguno de sus trozos.

    Importa porque el criterio de relevancia declarado en
    ``eval/preguntas_evaluacion.json`` anota **unidades semánticas**, mientras
    que la métrica original cuenta fragmentos. Ese desajuste tiene una
    consecuencia medida el 01/08/2026: 12 de las 36 preguntas apuntan a más de
    tres fragmentos, así que el techo de Recall@3 por fragmento es 0,868 y no
    1. Por unidad el techo vuelve a ser 1 y la cifra se interpreta sola.

    Las dos se reportan juntas a propósito: por fragmento describe el sistema
    tal como está hoy, que le pasa al generador solo los fragmentos
    recuperados; por unidad describe el sistema con expansión por unidad, que
    todavía no existe. Dar solo la segunda prometería algo que el sistema no
    hace.

    Se toman las ``k`` primeras unidades DISTINTAS del ranking, no los ``k``
    primeros fragmentos: de lo contrario dos fragmentos de la misma asignatura
    gastarían dos posiciones de las k.

    Args:
        ranking: Índices de chunk ordenados por similitud descendente.
        relevantes: Índices de chunk relevantes para la pregunta.
        chunks: Chunks completos, para resolver a qué unidad pertenece cada
            índice.
        k: Número de unidades distintas que se consideran recuperadas.

    Returns:
        Valor en ``[0, 1]``.

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
    # Las de fuera de dominio (IT-86) no anotan unidades relevantes porque lo
    # correcto ante ellas es no recuperar nada. Aquí aportarían un 0 fijo a
    # Recall@K y a MRR y hundirían las medias sin que el recuperador hubiera
    # fallado, que es exactamente el defecto contra el que avisa el
    # verificador del conjunto. Su criterio es el contrario y se mide aparte.
    preguntas = [p for p in preguntas if p["tipo"] != FUERA_DE_DOMINIO]

    vectores_chunks = incrustar_chunks([chunk["texto"] for chunk in chunks])
    vectores_preguntas = incrustar_preguntas([p["pregunta"] for p in preguntas])

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

    # Desglose por tipo de pregunta. Sin él la media general deja de ser
    # interpretable en cuanto conviven tipos con techos muy distintos: una
    # pregunta de listado tiene un techo de Recall@5 de 0,042 por su propia
    # naturaleza, y arrastra la media sin que el sistema haya empeorado.
    por_tipo: dict[str, dict[str, float]] = {}
    for tipo in sorted({f["tipo"] for f in detalle}):
        filas = [f for f in detalle if f["tipo"] == tipo]
        por_tipo[tipo] = {"n": float(len(filas))}
        for m in metricas:
            por_tipo[tipo][m] = sum(f[m] for f in filas) / len(filas)

    return {"agregados": agregados, "por_tipo": por_tipo, "detalle": detalle}

"""Pruebas de las métricas de recuperación del experimento IT-28.

Deterministas y sin red: los vectores de embedding son artesanales (no un
modelo real), porque lo que se prueba aquí es la aritmética de Recall@K y
MRR, no la calidad de ningún modelo concreto (eso lo mide
``scripts/experimentos/experimento_embeddings.py`` contra el dataset real).
"""

from __future__ import annotations

import pytest

from tfg_uja.indexacion import evaluacion
from tfg_uja.invariantes import InvarianteRoto

from tfg_uja.indexacion.evaluacion import (
    chunks_relevantes,
    evaluar_modelo,
    mrr_de_pregunta,
    recall_en_k,
    rankear,
)


def _chunk(origen: str, nombre: str, grados: list[str], texto: str = "x") -> dict:
    return {
        "origen": origen,
        "nombre": nombre,
        "grados": grados,
        "codigos": [""] * len(grados) if grados else [None],
        "texto": texto,
        "chunk_index": 0,
        "total_chunks": 1,
    }


CHUNKS = [
    _chunk("guia", "Estructuras de datos", ["Grado en Ingeniería Informática"]),  # 0
    _chunk(
        "guia", "Estructuras de datos", ["Grado en Ingeniería Informática"]
    ),  # 1 (2º fragmento)
    _chunk("guia", "Diseño de software", ["Grado en Ingeniería Informática"]),  # 2
    _chunk(
        "guia",
        "Electrotecnia",
        ["Grado en Ingeniería Eléctrica", "Grado en Ingeniería Mecánica"],
    ),  # 3, guía compartida
]


def test_chunks_relevantes_empareja_por_origen_nombre_y_grado():
    pregunta = {
        "relevantes": [
            {
                "origen": "guia",
                "nombre": "Estructuras de datos",
                "grado": "Grado en Ingeniería Informática",
            }
        ]
    }
    assert chunks_relevantes(pregunta, CHUNKS) == {0, 1}


def test_chunks_relevantes_sin_grado_no_filtra_por_titulacion():
    pregunta = {"relevantes": [{"origen": "guia", "nombre": "Electrotecnia"}]}
    assert chunks_relevantes(pregunta, CHUNKS) == {3}


def test_chunks_relevantes_grado_que_no_imparte_la_asignatura_no_cuenta():
    pregunta = {
        "relevantes": [
            {
                "origen": "guia",
                "nombre": "Estructuras de datos",
                "grado": "Grado en Ingeniería Mecánica",
            }
        ]
    }
    assert chunks_relevantes(pregunta, CHUNKS) == set()


def test_chunks_relevantes_une_varios_selectores():
    pregunta = {
        "relevantes": [
            {"origen": "guia", "nombre": "Diseño de software"},
            {"origen": "guia", "nombre": "Electrotecnia"},
        ]
    }
    assert chunks_relevantes(pregunta, CHUNKS) == {2, 3}


def test_rankear_ordena_por_similitud_coseno_descendente():
    consulta = [1.0, 0.0]
    vectores = [
        [-1.0, 0.0],  # opuesto: similitud -1
        [1.0, 0.0],  # idéntico: similitud 1
        [0.0, 1.0],  # ortogonal: similitud 0
    ]
    assert rankear(consulta, vectores) == [1, 2, 0]


def test_rankear_vector_nulo_no_produce_nan():
    consulta = [1.0, 0.0]
    vectores = [[0.0, 0.0], [1.0, 0.0]]
    ranking = rankear(consulta, vectores)
    assert ranking[0] == 1  # el vector nulo nunca puede quedar primero


@pytest.mark.parametrize(
    "k, esperado",
    [(1, 0.0), (2, 0.5), (3, 1.0)],
)
def test_recall_en_k(k, esperado):
    ranking = [2, 0, 1]
    relevantes = {0, 1}
    assert recall_en_k(ranking, relevantes, k) == esperado


def test_recall_en_k_sin_relevantes_lanza_error():
    with pytest.raises(ValueError):
        recall_en_k([0, 1, 2], set(), 3)


def test_mrr_de_pregunta_usa_la_primera_posicion_relevante():
    assert mrr_de_pregunta([2, 0, 1], {0, 1}) == pytest.approx(0.5)


def test_mrr_de_pregunta_sin_acierto_es_cero():
    assert mrr_de_pregunta([2, 0, 1], {99}) == 0.0


def test_evaluar_modelo_agrega_recall_y_mrr_sobre_todas_las_preguntas():
    # Incrustador falso: cada chunk/pregunta lleva su vector "real" en un
    # diccionario, indexado por el propio texto (que aquí hacemos único).
    vectores = {
        "ed1": [1.0, 0.0],
        "ed2": [1.0, 0.0],
        "ds": [0.0, 1.0],
        "electro": [0.0, -1.0],
        "pregunta ed": [0.9, 0.1],  # más cerca de Estructuras de datos
        "pregunta electro": [0.0, -1.0],  # idéntico a Electrotecnia
    }
    chunks = [
        _chunk("guia", "Estructuras de datos", ["G1"], texto="ed1"),
        _chunk("guia", "Estructuras de datos", ["G1"], texto="ed2"),
        _chunk("guia", "Diseño de software", ["G1"], texto="ds"),
        _chunk("guia", "Electrotecnia", ["G2"], texto="electro"),
    ]
    preguntas = [
        {
            "id": "P-1",
            "tipo": "temario",
            "pregunta": "pregunta ed",
            "relevantes": [{"origen": "guia", "nombre": "Estructuras de datos"}],
        },
        {
            "id": "P-2",
            "tipo": "temario",
            "pregunta": "pregunta electro",
            "relevantes": [{"origen": "guia", "nombre": "Electrotecnia"}],
        },
    ]

    def incrustar(textos: list[str]) -> list[list[float]]:
        return [vectores[t] for t in textos]

    resultado = evaluar_modelo(chunks, preguntas, incrustar, incrustar, ks=(1, 2))

    # P-1: relevantes {0,1}; ranking esperado [0,1,2,3] (o [1,0,2,3], empate)
    # -> recall@1=0.5, recall@2=1.0, mrr=1.0
    # P-2: relevante {3}; electro es idéntico a la pregunta -> primero en el
    # ranking -> recall@1=1.0, mrr=1.0
    fila_1 = next(f for f in resultado["detalle"] if f["id"] == "P-1")
    fila_2 = next(f for f in resultado["detalle"] if f["id"] == "P-2")
    assert fila_1["recall@1"] == pytest.approx(0.5)
    assert fila_1["recall@2"] == pytest.approx(1.0)
    assert fila_1["mrr"] == pytest.approx(1.0)
    assert fila_2["recall@1"] == pytest.approx(1.0)
    assert fila_2["mrr"] == pytest.approx(1.0)

    agregados = resultado["agregados"]
    assert agregados["recall@1"] == pytest.approx((0.5 + 1.0) / 2)
    assert agregados["recall@2"] == pytest.approx((1.0 + 1.0) / 2)
    assert agregados["mrr"] == pytest.approx(1.0)


def test_las_preguntas_fuera_de_dominio_no_entran_en_las_metricas():
    """Regresión de IT-86.

    Su lista de relevantes está vacía a propósito ---lo correcto ante ellas es
    no recuperar nada--- así que aquí aportarían un 0 fijo a Recall@K y a MRR.
    Diez preguntas así sobre sesenta bajarían las medias un 17 % sin que el
    recuperador hubiera fallado en ninguna.
    """
    chunks = [
        {
            "texto": "Álgebra del Grado en Ingeniería Informática.",
            "origen": "guia",
            "nombre": "Álgebra",
            "grados": ["Grado en Ingeniería Informática"],
        },
    ]
    dentro = {
        "id": "P-001",
        "tipo": "temario",
        "pregunta": "¿qué se ve en Álgebra?",
        "relevantes": [{"origen": "guia", "nombre": "Álgebra"}],
    }
    fuera = {
        "id": "P-051",
        "tipo": "fuera_de_dominio",
        "pregunta": "¿cuál es la capital de Francia?",
        "relevantes": [],
    }

    def incrustar(textos):
        return [[1.0, 0.0] for _ in textos]

    solo_dentro = evaluacion.evaluar_modelo(
        chunks, [dentro], incrustar, incrustar, ks=(1,)
    )
    con_fuera = evaluacion.evaluar_modelo(
        chunks, [dentro, fuera], incrustar, incrustar, ks=(1,)
    )
    assert con_fuera["agregados"] == solo_dentro["agregados"]
    assert [f["id"] for f in con_fuera["detalle"]] == ["P-001"]


def test_recall_de_unidad_exige_que_la_pregunta_tenga_relevantes():
    """Una pregunta sin unidades relevantes no es evaluable, y se dice.

    Es el caso de las diez preguntas fuera de dominio del conjunto: su lista de
    relevantes está vacía a propósito. Devolver 0,0 en vez de fallar las metería
    en la media y hundiría el Recall con un valor que no significa nada, que es
    justo lo que el conjunto de evaluación evita dejándolas fuera.
    """
    chunks = [{"origen": "guia", "grados": ["G"], "codigos": ["1"], "nombre": "A"}]

    with pytest.raises(ValueError, match="no es evaluable"):
        evaluacion.recall_de_unidad_en_k([0], set(), chunks, 3)


def test_menos_vectores_de_preguntas_aborta_en_vez_de_medir_de_menos():
    """Regresión de IT-127: el bucle iba con ``zip`` y perdía preguntas.

    ``zip`` se para en la más corta, así que un incrustador que devolviera menos
    vectores hacía desaparecer preguntas del detalle **y de las medias**, sin
    lanzar error. La cifra publicada sería un Recall@K medido sobre un banco
    distinto del declarado, y nada en la salida lo delataría.
    """
    relevante = [{"origen": "guia", "nombre": "A"}]
    chunks = [_chunk("guia", "A", ["G1"], texto="a")]
    preguntas = [
        {"id": "P-1", "tipo": "temario", "pregunta": "p1", "relevantes": relevante},
        {"id": "P-2", "tipo": "temario", "pregunta": "p2", "relevantes": relevante},
    ]

    def incrustar_corto(textos: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in textos][:1]

    def incrustar(textos: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in textos]

    with pytest.raises(InvarianteRoto, match="1 vectores para 2 preguntas"):
        evaluar_modelo(chunks, preguntas, incrustar, incrustar_corto)


def test_menos_vectores_de_chunks_aborta_antes_de_rankear():
    """La otra mitad: rankear contra menos vectores mide otra colección.

    El ranking se construye sobre ``vectores_chunks``, de modo que un chunk sin
    vector queda fuera de todo ranking y **nunca puede recuperarse**. El Recall
    saldría más bajo sin que el recuperador hubiera fallado.
    """
    chunks = [
        _chunk("guia", "A", ["G1"], texto="a"),
        _chunk("guia", "B", ["G1"], texto="b"),
    ]
    preguntas = [
        {
            "id": "P-1",
            "tipo": "temario",
            "pregunta": "p1",
            "relevantes": [{"origen": "guia", "nombre": "A"}],
        }
    ]

    def incrustar_corto(textos: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in textos][:1]

    def incrustar(textos: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in textos]

    with pytest.raises(InvarianteRoto, match="1 vectores para 2 chunks"):
        evaluar_modelo(chunks, preguntas, incrustar_corto, incrustar)

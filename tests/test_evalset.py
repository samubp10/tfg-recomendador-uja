"""Pruebas de estructura del conjunto de evaluación (IT-27).

Estas pruebas validan el fichero versionado ``eval/preguntas_evaluacion.json``
sin necesitar ``data/`` (que no existe en CI): el contraste de los selectores
contra el dataset real lo hace ``scripts/check_evalset.py`` en local, igual
que el resto de verificadores del proyecto.
"""

from __future__ import annotations

import json
from pathlib import Path

RUTA_EVAL = Path(__file__).parent.parent / "eval" / "preguntas_evaluacion.json"

ORIGENES_VALIDOS = {"guia", "salidas", "asignatura_sin_guia"}
TIPOS_VALIDOS = {"salidas", "temario", "metadatos", "sin_guia"}


def cargar():
    return json.loads(RUTA_EVAL.read_text(encoding="utf-8"))


def test_hay_al_menos_30_preguntas():
    """La Definición de Hecho de IT-27 exige un mínimo de 30 preguntas."""
    assert len(cargar()["preguntas"]) >= 30


def test_ids_unicos_y_bien_formados():
    ids = [p["id"] for p in cargar()["preguntas"]]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("P-") for i in ids)


def test_toda_pregunta_tiene_relevantes_anotados():
    """Cada pregunta anota al menos una unidad relevante (es el gold standard)."""
    for pregunta in cargar()["preguntas"]:
        assert pregunta["pregunta"].strip()
        assert pregunta["tipo"] in TIPOS_VALIDOS
        assert len(pregunta["relevantes"]) >= 1
        for selector in pregunta["relevantes"]:
            assert selector["origen"] in ORIGENES_VALIDOS
            assert selector["nombre"].strip()


def test_cubre_varios_tipos_de_pregunta():
    """La DoD pide variedad: temario, salidas y más de un tipo en total."""
    tipos = {p["tipo"] for p in cargar()["preguntas"]}
    assert {"salidas", "temario"} <= tipos
    assert len(tipos) >= 3

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

ORIGENES_VALIDOS = {"guia", "salidas", "asignatura_sin_guia", "plan_de_estudios"}
# `listado` (IT-100): preguntas que piden TODAS las asignaturas de un grupo de
# una titulación. Se separan de los demás tipos porque miden otra cosa —
# agregación, no recuperación de una unidad concreta— y porque su media hay que
# poder mirarla aparte.
TIPOS_VALIDOS = {"salidas", "temario", "metadatos", "sin_guia", "listado"}

#: Tipo cuya respuesta correcta es no recuperar nada (IT-86). Va aparte de
#: los demás porque su anotación es la contraria: la lista vacía es lo
#: correcto, no un descuido.
FUERA_DE_DOMINIO = "fuera_de_dominio"


def cargar():
    return json.loads(RUTA_EVAL.read_text(encoding="utf-8"))


def test_hay_al_menos_30_preguntas():
    """La Definición de Hecho de IT-27 exige un mínimo de 30 preguntas."""
    assert len(cargar()["preguntas"]) >= 30


def test_ids_unicos_y_bien_formados():
    ids = [p["id"] for p in cargar()["preguntas"]]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("P-") for i in ids)


def test_toda_pregunta_de_dominio_tiene_relevantes_anotados():
    """Cada pregunta anota al menos una unidad relevante (es el gold standard)."""
    for pregunta in cargar()["preguntas"]:
        if pregunta["tipo"] == FUERA_DE_DOMINIO:
            continue
        assert pregunta["pregunta"].strip()
        assert pregunta["tipo"] in TIPOS_VALIDOS
        assert len(pregunta["relevantes"]) >= 1
        for selector in pregunta["relevantes"]:
            assert selector["origen"] in ORIGENES_VALIDOS
            assert selector["nombre"].strip()


def test_las_de_fuera_de_dominio_no_anotan_nada():
    """IT-86: si hay algo que recuperar, la pregunta no es de fuera de dominio."""
    fuera = [p for p in cargar()["preguntas"] if p["tipo"] == FUERA_DE_DOMINIO]
    assert len(fuera) == 10
    for pregunta in fuera:
        assert pregunta["pregunta"].strip()
        assert pregunta["relevantes"] == []
        assert pregunta["clase"].strip()


def test_las_de_fuera_de_dominio_cubren_varias_clases():
    """Con una sola clase, esa clase decidiría ella sola la cifra de rechazo."""
    clases = {
        p["clase"] for p in cargar()["preguntas"] if p["tipo"] == FUERA_DE_DOMINIO
    }
    assert len(clases) == 5


def test_el_criterio_de_fuera_de_dominio_esta_escrito():
    """Su criterio de acierto es el contrario al del resto del conjunto."""
    criterio = cargar()["criterio_fuera_de_dominio"]
    assert "rechazar es acierto" in criterio
    assert "Recall@K" in criterio


def test_cubre_varios_tipos_de_pregunta():
    """La DoD pide variedad: temario, salidas y más de un tipo en total."""
    tipos = {p["tipo"] for p in cargar()["preguntas"]}
    assert {"salidas", "temario"} <= tipos
    assert len(tipos) >= 3

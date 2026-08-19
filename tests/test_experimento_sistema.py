"""Pruebas de los correctores del banco del sistema (IT-37).

Ninguna llama al servidor de inferencia: lo que se comprueba aquí es que cada
criterio da por buena la respuesta correcta y por mala la equivocada, que es lo
único que sostiene las cifras del experimento. Los criterios nuevos son los que
no existían en el banco de IT-35 y, por tanto, los que nunca se habían probado.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

import experimento_sistema as sistema  # noqa: E402

from tfg_uja import generador  # noqa: E402

CATALOGO = [
    "Doble Grado en Ingeniería Mecánica y Organización Industrial",
    "Grado en Ingeniería Informática",
    "Grado en Ingeniería Mecánica",
    "Grado en Ingeniería de Organización Industrial",
]


# --- Respuestas fijas ---


def test_la_respuesta_fija_se_compara_entera():
    acierta, _ = sistema.corregir_fija(generador.RESPUESTA_SALUDO, ["RESPUESTA_SALUDO"])
    assert acierta


def test_una_respuesta_parecida_no_es_la_fija():
    """Se compara literal a propósito: es la comprobación más dura que hay."""
    acierta, detalle = sistema.corregir_fija("¡Hola!", ["RESPUESTA_SALUDO"])
    assert not acierta
    assert "RESPUESTA_SALUDO" in detalle


def test_la_despedida_no_vale_por_el_saludo():
    acierta, _ = sistema.corregir_fija(
        generador.RESPUESTA_DESPEDIDA, ["RESPUESTA_SALUDO"]
    )
    assert not acierta


# --- Recomendaciones ---


def test_recomendar_una_titulacion_real_es_acertar():
    acierta, _ = sistema.corregir_sin_invencion(
        "Te encaja el Grado en Ingeniería Informática.", CATALOGO
    )
    assert acierta


def test_inventarse_una_titulacion_es_fallar():
    acierta, detalle = sistema.corregir_sin_invencion(
        "Te recomiendo el Grado en Ingeniería Biomédica.", CATALOGO
    )
    assert not acierta
    assert "Biomédica" in detalle


def test_no_recomendar_ninguna_tambien_es_fallar():
    """A quien pide consejo hay que darle alguno: escurrir el bulto no vale."""
    acierta, detalle = sistema.corregir_sin_invencion(
        "Depende de lo que te guste.", CATALOGO
    )
    assert not acierta
    assert "ninguna" in detalle


# --- Preguntas ajenas al dominio ---


def test_no_nombrar_ninguna_titulacion_es_rechazar_bien():
    acierta, _ = sistema.corregir_rechazo(
        "No he encontrado información sobre eso en la web de la Escuela."
    )
    assert acierta


def test_recomendar_una_carrera_a_quien_pregunta_otra_cosa_es_fallar():
    """Aunque la titulación exista: la pregunta era de otro centro."""
    acierta, detalle = sistema.corregir_rechazo(
        "En la Escuela puedes estudiar el Grado en Ingeniería Informática."
    )
    assert not acierta
    assert "Informática" in detalle


# --- Ámbito de la conversación ---


def test_hablar_de_la_titulacion_correcta_es_acertar():
    pregunta = {
        "esperado": ["Grado en Ingeniería de Organización Industrial"],
        "prohibido": ["Grado en Ingeniería Mecánica"],
    }
    acierta, _ = sistema.corregir_ambito(
        "El Grado en Ingeniería de Organización Industrial tiene 15 optativas.",
        pregunta,
        CATALOGO,
    )
    assert acierta


def test_responder_de_otra_titulacion_es_fallar():
    """Regresión del turno 7 del 19/08/2026, que ninguna métrica detectaba.

    Quince asignaturas reales, cero invenciones y la titulación equivocada: la
    precisión y la cobertura salían perfectas.
    """
    pregunta = {
        "esperado": ["Grado en Ingeniería de Organización Industrial"],
        "prohibido": ["Grado en Ingeniería Mecánica"],
    }
    acierta, detalle = sistema.corregir_ambito(
        "El Grado en Ingeniería Mecánica tiene 15 asignaturas optativas.",
        pregunta,
        CATALOGO,
    )
    assert not acierta
    assert "Mecánica" in detalle


def test_el_doble_grado_no_dispara_la_prohibicion_del_simple():
    """El nombre del simple está dentro del doble, y eso no es nombrarlo."""
    pregunta = {
        "esperado": ["Doble Grado en Ingeniería Mecánica y Organización Industrial"],
        "prohibido": ["Grado en Ingeniería Mecánica"],
    }
    acierta, detalle = sistema.corregir_ambito(
        "El Doble Grado en Ingeniería Mecánica y Organización Industrial dura "
        "cinco cursos.",
        pregunta,
        CATALOGO,
    )
    assert acierta, detalle


# --- El despachador ---


def test_un_criterio_desconocido_no_pasa_en_silencio():
    """Un banco con una errata daría cifras sin que nadie se enterase."""
    with pytest.raises(ValueError, match="criterio desconocido"):
        sistema.corregir("lo que sea", {"respuesta": "inventado"}, CATALOGO, set())


def test_el_criterio_de_conjunto_exige_precision_y_cobertura_perfectas():
    pregunta = {
        "respuesta": "conjunto",
        "familia": "optativas",
        "esperado": ["Álgebra", "Cálculo"],
    }
    nombres = {"Álgebra", "Cálculo", "Física I"}
    entero = sistema.corregir(
        "- Álgebra (6 ECTS)\n- Cálculo (6 ECTS)", pregunta, CATALOGO, nombres
    )
    assert entero["acierta"]
    falta = sistema.corregir("- Álgebra (6 ECTS)", pregunta, CATALOGO, nombres)
    assert not falta["acierta"]
    assert falta["omitidas"] == 1

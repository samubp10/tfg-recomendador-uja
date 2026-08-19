"""Pruebas del generador del banco de preguntas de generación (IT-35).

Los registros de este fichero están **copiados literalmente** de
``data/grados.json``. No son inventados a propósito: las anomalías que importan
---la asignatura sin ECTS, el nombre en mayúsculas, el rótulo «Común a todas
las menciones» que no es una mención--- no aparecerían en datos escritos a mano,
y son justo las que el generador tiene que tratar bien.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "generar_banco", RAIZ / "scripts" / "generar_banco_generacion.py"
)
assert _spec is not None and _spec.loader is not None
generar_banco = importlib.util.module_from_spec(_spec)
sys.modules["generar_banco"] = generar_banco
_spec.loader.exec_module(generar_banco)


# --- Registros reales de data/grados.json ---

#: Asignatura normal, con ECTS y con curso.
_NORMAL = {
    "tipo": "asignatura",
    "grado": "Grado en Ingeniería Informática",
    "codigo": "13312001",
    "nombre": "Fundamentos de la programación",
    "tipo_asignatura": "FB",
    "menciones": [],
    "ects": "6",
    "curso": "Primer curso",
    "cuatrimestre": "Primer cuatrimestre",
    "ofertada": True,
    "url_guia": None,
    "tiene_guia": False,
}

#: La única asignatura que la fuente publica **sin créditos**. El dataset la
#: deja ausente a propósito (los datos faltantes se reflejan, no se imputan).
_SIN_ECTS = {
    "tipo": "asignatura",
    "grado": "Grado en Ingeniería Electrónica Industrial",
    "codigo": "13113013",
    "nombre": "Sistemas Digitales",
    "tipo_asignatura": "OP",
    "menciones": ["Sistemas electrónicos"],
    "ects": "",
    "curso": "",
    "cuatrimestre": "Segundo cuatrimestre",
    "ofertada": True,
    "url_guia": None,
    "tiene_guia": True,
}

#: Nombre en mayúsculas, con la sigla de la titulación entre paréntesis.
_EN_MAYUSCULAS = {
    "tipo": "asignatura",
    "grado": "Doble Grado en Ingeniería Electrónica Industrial y Mecánica",
    "codigo": "13811009",
    "nombre": "CINEMÁTICA Y DINÁMICA DE MÁQUINAS (GIM)",
    "tipo_asignatura": "OB",
    "menciones": [],
    "ects": "6",
    "curso": "Cuarto o tercer curso",
    "cuatrimestre": "Primer cuatrimestre",
    "ofertada": True,
    "url_guia": None,
    "tiene_guia": False,
}

#: Optativa marcada con el rótulo que **no es una mención**.
_COMUN = {
    "tipo": "asignatura",
    "grado": "Grado en Ingeniería Mecánica",
    "codigo": "13413012",
    "nombre": "Prácticas externas",
    "tipo_asignatura": "OP",
    "menciones": ["Común a todas las menciones"],
    "ects": "6",
    "curso": "",
    "cuatrimestre": "Primer cuatrimestre",
    "ofertada": True,
    "url_guia": None,
    "tiene_guia": True,
}

_GRADO = {
    "tipo": "grado",
    "nombre": "Grado en Ingeniería Informática",
    "es_doble_grado": False,
    "url_asignaturas": None,
    "url_salidas": None,
}

_DATOS = [_GRADO, _NORMAL, _SIN_ECTS, _EN_MAYUSCULAS, _COMUN]


# --- Caja de los nombres ---


def test_un_nombre_en_mayusculas_se_escribe_como_lo_escribiria_alguien():
    assert (
        generar_banco._como_se_escribe("CINEMÁTICA Y DINÁMICA DE MÁQUINAS (GIM)")
        == "Cinemática y dinámica de máquinas (GIM)"
    )


def test_un_nombre_que_ya_venia_bien_no_se_toca():
    assert (
        generar_banco._como_se_escribe("Fundamentos de la programación")
        == "Fundamentos de la programación"
    )


def test_ninguna_pregunta_del_banco_grita_en_mayusculas():
    for p in generar_banco.construir(_DATOS):
        gritan = [
            palabra
            for palabra in p["pregunta"].split()
            if palabra.isupper() and len(palabra) > 4 and not palabra.startswith("(")
        ]
        assert gritan == [], p["pregunta"]


# --- Lo que no se puede computar, no se pregunta ---


def test_la_asignatura_sin_creditos_no_genera_pregunta_de_creditos():
    """Exigir un dato que el corpus no tiene sería imputarlo."""
    creditos = [
        p
        for p in generar_banco.preguntas_de_asignatura(_DATOS)
        if p["familia"] == "creditos"
    ]
    assert all(p["ambito"]["asignatura"] != "Sistemas Digitales" for p in creditos)


def test_la_asignatura_sin_curso_no_genera_pregunta_de_curso():
    cursos = [
        p
        for p in generar_banco.preguntas_de_asignatura(_DATOS)
        if p["familia"] == "curso_de_asignatura"
    ]
    assert all(p["ambito"]["asignatura"] != "Prácticas externas" for p in cursos)


def test_ninguna_pregunta_se_queda_sin_respuesta_esperada():
    assert all(p["esperado"] for p in generar_banco.construir(_DATOS))


# --- El rótulo que no es una mención ---


def test_comun_a_todas_las_menciones_no_es_una_mencion():
    """Darla por buena obligaría al modelo a nombrar un itinerario inexistente."""
    for p in generar_banco.preguntas_de_mencion(_DATOS):
        assert "Común a todas las menciones" not in p["esperado"]
        assert "Común a todas las menciones" not in p["pregunta"]


# --- Las respuestas salen del dataset, no de la redacción ---


def test_el_curso_esperado_es_el_rotulo_literal_de_la_fuente():
    """La fuente publica rangos («Cuarto o tercer curso») y se respetan."""
    pregunta = next(
        p
        for p in generar_banco.preguntas_de_asignatura(_DATOS)
        if p["familia"] == "curso_de_asignatura"
        and p["ambito"]["asignatura"] == "CINEMÁTICA Y DINÁMICA DE MÁQUINAS (GIM)"
    )
    assert pregunta["esperado"] == ["Cuarto o tercer curso"]


def test_el_catalogo_espera_las_titulaciones_del_dataset():
    pregunta = generar_banco.preguntas_de_catalogo(_DATOS)[0]
    assert pregunta["esperado"] == ["Grado en Ingeniería Informática"]


def test_las_optativas_no_se_mezclan_con_las_de_curso():
    porcurso = generar_banco.preguntas_de_curso(_DATOS)
    listados = [n for p in porcurso for n in p["esperado"]]
    assert "Prácticas externas" not in listados
    assert "Sistemas Digitales" not in listados


def test_no_se_pregunta_por_lo_que_el_corpus_no_puede_responder():
    """La familia de ubicación se retiró: su respuesta no está en ningún sitio.

    Se computa sin problema del dataset ---en qué titulaciones se imparte una
    asignatura compartida---, pero los fragmentos se componen por titulación y
    curso y nadie los cruza. Medido el 18/08/2026, los dos modelos contestaron
    2 y 6 titulaciones donde el dataset dice 10, habiendo leído bien lo que se
    les dio. Eran 86 preguntas que habrían suspendido a todos los candidatos
    por un hueco del corpus.
    """
    familias = {p["familia"] for p in generar_banco.construir(_DATOS)}
    assert "ubicacion" not in familias
    assert not hasattr(generar_banco, "preguntas_de_ubicacion")


def test_los_identificadores_no_se_repiten():
    banco = generar_banco.construir(_DATOS)
    assert len({p["id"] for p in banco}) == len(banco)


# --- La muestra de decisión ---


def test_la_muestra_representa_todas_las_familias():
    banco = generar_banco.construir(_DATOS)
    familias = {p["familia"] for p in banco}
    muestra = generar_banco.muestra_estratificada(banco, len(familias), semilla=42)
    assert {p["familia"] for p in muestra} == familias


def test_la_misma_semilla_da_la_misma_muestra():
    """Sin esto el experimento no se podría repetir."""
    banco = generar_banco.construir(_DATOS)
    a = generar_banco.muestra_estratificada(banco, 5, semilla=42)
    b = generar_banco.muestra_estratificada(banco, 5, semilla=42)
    assert [p["id"] for p in a] == [p["id"] for p in b]


def test_pedir_mas_preguntas_de_las_que_hay_devuelve_todas():
    banco = generar_banco.construir(_DATOS)
    muestra = generar_banco.muestra_estratificada(banco, 10_000, semilla=42)
    assert len(muestra) == len(banco)

"""Tests del troceado del dataset (IT-08 e IT-09).

La fixture ``dataset_muestra.json`` contiene items REALES extraídos del
dataset generado por el spider: la guía más corta del dataset ("Sistemas de
información para el negocio electrónico", 395 caracteres), una guía larga
("Aprovechamiento y ahorro energético", ~6.000), una guía que activó el
fallback en producción ("Cartografía"), una asignatura sin guía con mención
("Microelectrónica") y las salidas profesionales de Informática, junto a
sus items de asignatura para los metadatos de encabezado.
"""

import json
from pathlib import Path

import pytest

from tfg_uja.chunker import (
    TAMANO_MAXIMO,
    trocear_dataset,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def muestra():
    return json.loads((FIXTURES / "dataset_muestra.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def chunks(muestra):
    return trocear_dataset(muestra)


def _de(chunks, codigo):
    return [c for c in chunks if c["codigo"] == codigo]


# --- IT-08: troceo semántico base ---


def test_una_guia_corta_produce_un_solo_chunk(chunks):
    # "Sistemas de información para el negocio electrónico": 395 caracteres.
    resultado = _de(chunks, "13312032")
    assert len(resultado) == 1
    assert resultado[0]["chunk_index"] == 0
    assert resultado[0]["total_chunks"] == 1


def test_una_guia_larga_se_divide_en_varios_chunks(chunks):
    # "Aprovechamiento y ahorro energético": ~6.000 caracteres reales.
    resultado = _de(chunks, "13013001")
    assert len(resultado) > 1
    assert [c["chunk_index"] for c in resultado] == list(range(len(resultado)))
    assert all(c["total_chunks"] == len(resultado) for c in resultado)


def test_ningun_chunk_supera_el_maximo(chunks):
    # Invariante estricto: el chunk COMPLETO (encabezado incluido) respeta
    # el máximo. La fixture incluye la guía real 13013009 («Manutención y
    # almacenaje»), que violaba este invariante antes de descontar el
    # encabezado del presupuesto de tamaño.
    assert all(len(c["texto"]) <= TAMANO_MAXIMO for c in chunks)


def test_ningun_chunk_mezcla_asignaturas(chunks):
    # Cada chunk lleva el código de UNA asignatura y su texto no contiene
    # el nombre de las demás asignaturas de la muestra.
    nombres = {
        "13312032": "Sistemas de información para el negocio electrónico",
        "13013001": "Aprovechamiento y ahorro energético",
    }
    for codigo, nombre_ajeno in nombres.items():
        for chunk in chunks:
            if chunk["codigo"] not in (codigo, None) and chunk["origen"] == "guia":
                assert nombre_ajeno not in chunk["texto"]


def test_cada_chunk_es_autocontenido(chunks):
    # Todo chunk de guía empieza por el encabezado con nombre y grado.
    for chunk in chunks:
        if chunk["origen"] == "guia":
            assert chunk["texto"].startswith("«")
            assert chunk["grado"] in chunk["texto"].split("\n")[0]


def test_una_guia_con_fallback_tambien_se_trocea(chunks):
    # "Cartografía" (13212001) activó el fallback en producción: su
    # cuerpo_general (~6.400 chars) debe trocearse igualmente.
    resultado = _de(chunks, "13212001")
    assert len(resultado) > 1


def test_el_troceo_es_determinista(muestra):
    assert trocear_dataset(muestra) == trocear_dataset(muestra)


# --- IT-09: fusión de pequeños y asignaturas sin guía ---

def test_asignatura_sin_guia_genera_chunk_explicito(chunks):
    # En el dataset de muestra, "Microelectrónica" (código 13113006) es un
    # item de tipo 'asignatura' pero no tiene item 'guia' emparejado.
    resultado = _de(chunks, "13113006")
    assert len(resultado) == 1
    assert resultado[0]["origen"] == "asignatura_sin_guia"
    assert "no está publicada" in resultado[0]["texto"]
    assert "Microelectrónica" in resultado[0]["texto"]

def test_fusion_de_chunks_pequenos(chunks):
    # Las guías largas pueden dejar un fragmento residual muy pequeño al
    # final de la división. _fusionar_pequenos se encarga de reempaquetarlos
    # para que ningún chunk (excepto el origen=asignatura_sin_guia o salidas cortas)
    # se quede por debajo de un umbral ridículo (ej: 200).
    from tfg_uja.chunker import TAMANO_MINIMO
    for chunk in chunks:
        if chunk["origen"] == "guia" and chunk["total_chunks"] > 1:
            assert len(chunk["texto"]) >= TAMANO_MINIMO

def test_las_salidas_de_un_grado_forman_su_propia_unidad(chunks):
    resultado = [c for c in chunks if c["origen"] == "salidas"]
    assert resultado
    for chunk in resultado:
        assert chunk["codigo"] is None
        assert chunk["texto"].startswith("Salidas profesionales del ")
        assert "Programador de aplicaciones" in chunk["texto"] or chunk[
            "chunk_index"
        ] > 0

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
    TAMANO_MINIMO,
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
    return [c for c in chunks if codigo in c["codigos"]]


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
            if codigo not in chunk["codigos"] and chunk["origen"] == "guia":
                assert nombre_ajeno not in chunk["texto"]


def test_cada_chunk_es_autocontenido(chunks):
    # Todo chunk de guía empieza por el encabezado con nombre y grado.
    for chunk in chunks:
        if chunk["origen"] == "guia":
            assert chunk["texto"].startswith("«")
            assert any(g in chunk["texto"].split("\n")[0] for g in chunk["grados"])


def test_una_guia_con_fallback_tambien_se_trocea(chunks):
    # "Cartografía" (13212001) activó el fallback en producción: su
    # cuerpo_general (~6.400 chars) debe trocearse igualmente.
    resultado = _de(chunks, "13212001")
    assert len(resultado) > 1


def test_el_troceo_es_determinista(muestra):
    assert trocear_dataset(muestra) == trocear_dataset(muestra)


# --- IT-09: fusión de pequeños y asignaturas sin guía ---


def test_ningun_chunk_queda_por_debajo_del_minimo(chunks):
    # La fusión debe absorber los fragmentos residuales del troceo.
    assert all(len(c["texto"]) >= TAMANO_MINIMO for c in chunks)


def test_asignatura_sin_guia_genera_chunk_informativo(chunks):
    # "Microelectrónica" (13113006) no tiene guía publicada.
    resultado = [c for c in chunks if c["origen"] == "asignatura_sin_guia"]
    assert len(resultado) == 1
    chunk = resultado[0]
    assert chunk["codigos"] == ["13113006"]
    assert "Microelectrónica" in chunk["texto"]
    assert "no está publicada" in chunk["texto"]
    # Sus metadatos básicos viajan en el encabezado (tipo y mención reales).
    assert "optativa" in chunk["texto"]
    assert "Sistemas electrónicos" in chunk["texto"]


def test_asignatura_no_ofertada_lo_indica_en_el_encabezado(chunks):
    # Microelectrónica está además marcada como no ofertada en el dataset.
    chunk = next(c for c in chunks if c["origen"] == "asignatura_sin_guia")
    assert "No ofertada" in chunk["texto"]


# --- Salidas profesionales ---


def test_las_salidas_de_un_grado_forman_su_propia_unidad(chunks):
    resultado = [c for c in chunks if c["origen"] == "salidas"]
    assert resultado
    for chunk in resultado:
        assert chunk["codigos"] == [None]
        assert chunk["texto"].startswith("Salidas profesionales del ")
        assert (
            "Programador de aplicaciones" in chunk["texto"] or chunk["chunk_index"] > 0
        )


# --- IT (deduplicación): guías compartidas entre titulaciones ---


def test_una_asignatura_compartida_se_deduplica_en_una_unidad(muestra):
    # Se construye una guía idéntica en dos titulaciones distintas (mismo
    # nombre y mismo contenido): deben fusionarse en una sola unidad cuyo
    # campo grados enumere ambas, en vez de duplicar el texto en el índice.
    guia_a = {
        "tipo": "guia",
        "grado": "Grado A",
        "codigo": "10000001",
        "nombre": "Álgebra",
        "fallback": False,
        "resumen": "Espacios vectoriales y aplicaciones lineales.",
        "temario": "Tema 1. Matrices. Tema 2. Determinantes. Tema 3. Diagonalización.",
    }
    guia_b = {**guia_a, "grado": "Grado B", "codigo": "20000001"}
    asig_a = {
        "tipo": "asignatura",
        "grado": "Grado A",
        "codigo": "10000001",
        "nombre": "Álgebra",
        "tipo_asignatura": "FB",
        "ects": "6",
        "menciones": [],
        "ofertada": True,
        "tiene_guia": True,
    }
    asig_b = {**asig_a, "grado": "Grado B", "codigo": "20000001"}
    chunks = trocear_dataset([asig_a, asig_b, guia_a, guia_b])
    algebra = [c for c in chunks if c["nombre"] == "Álgebra"]
    # Una sola unidad (no dos), con las dos titulaciones y sus dos códigos.
    assert {tuple(c["grados"]) for c in algebra} == {("Grado A", "Grado B")}
    assert algebra[0]["codigos"] == ["10000001", "20000001"]
    assert "2 titulaciones" in algebra[0]["texto"]


def test_no_fusiona_asignaturas_distintas_con_el_mismo_texto(muestra):
    # Dos asignaturas DISTINTAS (nombres distintos) con texto idéntico —el
    # caso real del fallback de Smart Grids y Técnicas gráfica— no deben
    # fusionarse: la clave de deduplicación incluye el nombre.
    base_guia = {
        "tipo": "guia",
        "grado": "Grado A",
        "fallback": True,
        "cuerpo_general": "Texto genérico idéntico de respaldo.",
    }
    g1 = {**base_guia, "codigo": "30000001", "nombre": "Asignatura Uno"}
    g2 = {**base_guia, "codigo": "30000002", "nombre": "Asignatura Dos"}
    chunks = trocear_dataset([g1, g2])
    nombres = {c["nombre"] for c in chunks}
    assert nombres == {"Asignatura Uno", "Asignatura Dos"}
    assert all(len(c["grados"]) == 1 for c in chunks)

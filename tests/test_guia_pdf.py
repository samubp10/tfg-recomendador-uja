"""Pruebas de la extracción de guías docentes en PDF (IT-67).

Las fixtures son tres PDF reales descargados de la web de la EPSJ (curso
2026-27), uno por grado distinto, con sus anomalías reales: la maquetación a
dos columnas, el pie de página repetido en cada hoja, los títulos de tema en
mayúsculas dentro del temario y, sobre todo, el bloque de profesorado con
nombres, correos y teléfonos que la colección excluye a propósito.

Ninguna prueba hace peticiones de red: los PDF ya están en ``tests/fixtures``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tfg_uja.guia_pdf import es_pdf, extraer_guia

FIXTURES = Path(__file__).parent / "fixtures"

# Un correo o un teléfono en el texto extraído es un fallo de privacidad, no un
# defecto estético: se comprueba con los mismos patrones en todas las guías.
_CORREO = re.compile(r"[\w.\-]+@[\w.\-]+\.\w+")
_TELEFONO = re.compile(r"\b\d{9}\b")

# (fixture, subcadena que debe aparecer en el temario). Se elige un fragmento
# inequívoco de cada temario real para confirmar que se extrae el contenido
# correcto y completo, no solo que hay texto.
_GUIAS = [
    ("guia_estadistica_iayc.pdf", "estadística descriptiva univariante"),
    ("guia_matematica_discreta_informatica.pdf", "fundamentos de lógica"),
    ("guia_cartografia_geomatica2025.pdf", "el marco espacial de referencia"),
]


def _bytes(fixture: str) -> bytes:
    return (FIXTURES / fixture).read_bytes()


@pytest.mark.parametrize("fixture, esperado_en_temario", _GUIAS)
def test_extrae_resumen_y_temario(fixture: str, esperado_en_temario: str) -> None:
    datos = extraer_guia(_bytes(fixture))
    assert datos is not None
    assert len(datos["resumen"]) > 100
    assert esperado_en_temario in datos["temario"].lower()


@pytest.mark.parametrize("fixture, _", _GUIAS)
def test_no_filtra_datos_personales(fixture: str, _: str) -> None:
    # El requisito legal: de los PDF reales, que traen correos y teléfonos del
    # profesorado, no puede salir ninguno hacia la colección.
    datos = extraer_guia(_bytes(fixture))
    assert datos is not None
    texto = datos["resumen"] + datos["temario"]
    assert not _CORREO.findall(texto), "se ha filtrado un correo"
    assert not _TELEFONO.findall(texto), "se ha filtrado un teléfono"


def test_no_incluye_el_bloque_de_profesorado() -> None:
    # Comprobación directa por nombre: la coordinadora de Estadística aparece en
    # el PDF crudo; su apellido no puede estar en lo extraído.
    datos = extraer_guia(_bytes("guia_estadistica_iayc.pdf"))
    assert datos is not None
    assert "gallardo" not in (datos["resumen"] + datos["temario"]).lower()


def test_el_temario_no_se_corta_en_el_primer_tema_en_mayusculas() -> None:
    # Regresión del defecto del prototipo: en Cartografía los títulos de tema
    # van en mayúsculas ("INTRODUCCIÓN A LA CARTOGRAFÍA Y SIG"); si se tomaran
    # por rótulos de sección, el temario se cortaría en el primero. Debe llegar
    # hasta los temas finales.
    datos = extraer_guia(_bytes("guia_cartografia_geomatica2025.pdf"))
    assert datos is not None
    assert "fuentes primarias" in datos["temario"].lower()
    assert len(datos["temario"]) > 2000


def test_no_arrastra_el_pie_de_pagina() -> None:
    datos = extraer_guia(_bytes("guia_estadistica_iayc.pdf"))
    assert datos is not None
    texto = datos["resumen"] + datos["temario"]
    assert "página" not in texto.lower()
    assert "guía docente" not in texto.lower()


def test_un_pdf_ilegible_devuelve_none() -> None:
    # Un PDF corrupto no debe romper el rastreo: se trata como guía ausente.
    assert extraer_guia(b"esto no es un PDF") is None


def test_es_pdf_detecta_por_cabecera_y_por_firma() -> None:
    contenido = _bytes("guia_estadistica_iayc.pdf")
    assert es_pdf(b"application/pdf", contenido)
    # Aunque la cabecera mienta y diga HTML, la firma %PDF del cuerpo manda.
    assert es_pdf(b"text/html; charset=utf-8", contenido)
    # Un HTML de verdad no es PDF.
    assert not es_pdf(b"text/html", b"<!DOCTYPE html><html>...")

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

from tfg_uja.extraccion import guia_pdf
from tfg_uja.extraccion.guia_pdf import (
    ILEGIBLE,
    es_pdf,
    extraer_guia,
    motivo_sin_guia,
    rotulos_ausentes,
    rotulos_presentes,
)

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


# --- IT-95: la plantilla de la fuente sigue siendo la que el código supone ---
#
# Toda la extracción se apoya en una lista de rótulos escrita a mano contra la
# plantilla observada, y desde el curso 2026-27 el 100 % del contenido de la
# colección pasa por ahí. Si la Universidad cambia un rótulo, la sección deja de
# terminar donde debe: o se pierde contenido, o se arrastra el bloque de
# profesorado hasta el corpus. Ninguna de las dos cosas falla de forma visible,
# así que hace falta comprobarlo explícitamente.


@pytest.mark.parametrize("fixture, _", _GUIAS)
def test_no_le_falta_a_la_guia_ningun_rotulo_de_la_plantilla(
    fixture: str, _: str
) -> None:
    assert rotulos_ausentes(_bytes(fixture)) == []


@pytest.mark.parametrize("fixture, _", _GUIAS)
def test_encuentra_los_rotulos_de_las_dos_secciones_permitidas(
    fixture: str, _: str
) -> None:
    rotulos = rotulos_presentes(_bytes(fixture))
    assert "RESUMEN" in rotulos
    assert "DESCRIPCIÓN DE CONTENIDOS" in rotulos


def test_se_detecta_que_la_fuente_renombre_un_rotulo(monkeypatch) -> None:
    # El caso que importa: si la Universidad renombra un rótulo, la sección que
    # delimitaba deja de terminar donde debe. Se simula esperando un rótulo que
    # la plantilla actual no trae, que es exactamente lo que ocurriría.
    monkeypatch.setattr(
        guia_pdf,
        "_ROTULOS_ESPERADOS",
        frozenset({"RESUMEN", "CONTENIDOS DE LA MATERIA"}),
    )
    assert rotulos_ausentes(_bytes("guia_estadistica_iayc.pdf")) == [
        "CONTENIDOS DE LA MATERIA"
    ]


def test_ni_el_profesorado_ni_la_cabecera_se_confunden_con_un_rotulo() -> None:
    # Este es el motivo de que la comprobación vaya por ausencia y no buscando
    # rótulos desconocidos. Se intentó localizarlos por su tipografía (negrita a
    # doce puntos) y sobre las 293 guías reales dio 68 avisos distintos, todos
    # legítimos: la plantilla usa esa misma tipografía para el nombre de la
    # asignatura en la cabecera y para resaltar contenido dentro de las
    # secciones. Aquí se comprueba con casos reales de las dos familias.
    rotulos = rotulos_presentes(_bytes("guia_cartografia_geomatica2025.pdf"))
    assert not [r for r in rotulos if "ARIZA" in r]
    assert not [r for r in rotulos if r.startswith("CAMPUS LAS LAGUNILLAS")]
    assert "Guía Docente" not in rotulos
    assert not [r for r in rotulos if r.startswith("Curso Académico")]


def test_los_rotulos_salen_en_orden_de_lectura() -> None:
    # El orden importa: `_seccion` recorta desde un rótulo hasta el siguiente,
    # así que una lista desordenada delataría que se están leyendo mal.
    rotulos = rotulos_presentes(_bytes("guia_estadistica_iayc.pdf"))
    assert rotulos.index("FICHA IDENTIFICATIVA") < rotulos.index("PROFESORADO")
    assert rotulos.index("RESUMEN") < rotulos.index("DESCRIPCIÓN DE CONTENIDOS")


# --- IT-95: por qué una guía en PDF no aporta contenido ---


def test_un_pdf_ilegible_se_distingue_como_tal() -> None:
    assert motivo_sin_guia(b"esto no es un PDF") == ILEGIBLE
    assert motivo_sin_guia(b"") == ILEGIBLE


def test_una_guia_correcta_no_necesita_motivo() -> None:
    # Coherencia entre las dos funciones: si extraer_guia devuelve algo, no
    # tiene sentido preguntar por qué falló.
    for fixture, _ in _GUIAS:
        assert extraer_guia(_bytes(fixture)) is not None


# --- Por qué una guía publicada se queda sin contenido (DQA-0004) ---
#
# Los cuatro motivos existen porque durante el rastreo los cuatro casos eran
# indistinguibles y se llamaban todos «PDF ilegible», que era falso: los seis
# casos reales del 29/07/2026 se leían perfectamente y lo vacío eran las
# secciones en el origen. Distinguirlos es lo que permite decir en la memoria
# que 86 asignaturas no tienen contenido SIN afirmar que el extractor falla.


def test_un_pdf_corrupto_se_declara_ilegible():
    """Lo que ni siquiera se abre es ilegible, y así se cuenta."""
    assert guia_pdf.motivo_sin_guia(b"esto no es un PDF") == guia_pdf.ILEGIBLE


def test_una_guia_real_con_rotulos_se_declara_de_secciones_vacias():
    """Se abre, tiene texto y se le reconocen los rótulos: lo vacío es la fuente.

    Es el motivo que sostiene la lectura del corpus. Si este caso se contase
    como «ilegible», la memoria estaría diciendo que el extractor pierde
    guías cuando lo que ocurre es que la Escuela las publica sin contenido.
    """
    datos = (
        Path(__file__).parent / "fixtures" / "guia_estadistica_iayc.pdf"
    ).read_bytes()

    assert guia_pdf.motivo_sin_guia(datos) == guia_pdf.SECCIONES_VACIAS


def test_un_pdf_legible_cuyos_rotulos_no_se_reconocen_lo_dice(monkeypatch):
    """Si la plantilla cambia, se dice que cambió, no que el PDF esté roto.

    Es la anomalía que ya ocurrió con las tablas de asignaturas (IT-76): la
    fuente cambia de forma y el sistema tiene que distinguir «no lo entiendo»
    de «no hay nada», porque la primera se arregla y la segunda no.
    """
    datos = (
        Path(__file__).parent / "fixtures" / "guia_estadistica_iayc.pdf"
    ).read_bytes()
    monkeypatch.setattr(guia_pdf, "_lineas_utiles", lambda texto: ["Otro rótulo"])

    assert guia_pdf.motivo_sin_guia(datos) == guia_pdf.ROTULOS_DESCONOCIDOS


def test_un_pdf_que_se_abre_pero_no_trae_texto_se_declara_escaneado(monkeypatch):
    """Un PDF sin capa de texto es un escaneo, no un fichero corrupto."""
    datos = (
        Path(__file__).parent / "fixtures" / "guia_estadistica_iayc.pdf"
    ).read_bytes()
    monkeypatch.setattr(guia_pdf, "_texto_del_pdf", lambda datos: "   \n  ")

    assert guia_pdf.motivo_sin_guia(datos) == guia_pdf.SIN_TEXTO

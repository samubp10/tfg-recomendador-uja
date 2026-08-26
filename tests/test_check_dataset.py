"""Pruebas del verificador del dataset (IT-10, ampliado en IT-78).

El verificador vive en ``scripts/`` y se ejecuta a mano contra el dataset
completo, que no está versionado. Estas pruebas no necesitan ese dataset:
comprueban la lógica de la comprobación con casos mínimos construidos a
propósito, del mismo modo que ``test_indexer.py`` prueba la indexación sin
descargar ningún modelo.

``scripts/`` no es un paquete importable, así que el módulo se carga por su
ruta en lugar de con un ``import`` normal.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_RUTA = RAIZ / "scripts" / "verificadores" / "check_dataset.py"
_spec = importlib.util.spec_from_file_location("check_dataset", _RUTA)
assert _spec is not None and _spec.loader is not None
check_dataset = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_dataset)


def _grado(nombre: str, url_asignaturas: str | None) -> dict:
    return {
        "tipo": "grado",
        "nombre": nombre,
        "es_doble_grado": nombre.startswith("Doble Grado"),
        "url_asignaturas": url_asignaturas,
        "url_salidas": None,
    }


def _asignatura(grado: str, nombre: str) -> dict:
    return {"tipo": "asignatura", "grado": grado, "nombre": nombre}


def test_detecta_la_titulacion_que_se_queda_sin_asignaturas():
    # Es el caso real de Geomática: la fuente cambió el formato de sus tablas,
    # el rastreador las descartó con un aviso y el verificador decía «OK».
    datos = [
        _grado("Grado en Ingeniería Informática", "https://eps.ujaen.es/a"),
        _grado("Grado en Ingeniería Geomática y Topográfica", "https://eps.ujaen.es/b"),
        _asignatura("Grado en Ingeniería Informática", "Matemática discreta"),
    ]
    assert check_dataset.grados_sin_asignaturas(datos) == [
        "Grado en Ingeniería Geomática y Topográfica"
    ]


def test_un_dataset_completo_no_da_falsos_positivos():
    datos = [
        _grado("Grado en Ingeniería Informática", "https://eps.ujaen.es/a"),
        _asignatura("Grado en Ingeniería Informática", "Matemática discreta"),
    ]
    assert check_dataset.grados_sin_asignaturas(datos) == []


def test_los_dobles_grados_no_cuentan_como_vacios():
    # Un doble grado no tiene página propia de asignaturas: es la unión de sus
    # dos grados base, que se rastrean por separado (decisión de IT-04/IT-07).
    # Sin asignaturas propias es lo normal, no un fallo.
    datos = [
        _grado("Doble Grado en Ingeniería Eléctrica y Mecánica", None),
        _grado("Grado en Ingeniería Mecánica", "https://eps.ujaen.es/a"),
        _asignatura("Grado en Ingeniería Mecánica", "Diseño de máquinas"),
    ]
    assert check_dataset.grados_sin_asignaturas(datos) == []


def test_varias_titulaciones_vacias_se_informan_todas():
    # Al cambiar la fuente cayeron las dos titulaciones de Geomática a la vez;
    # informar solo de la primera obligaría a repetir el rastreo entero para
    # descubrir la segunda. El mensaje del verificador interpola esta lista,
    # así que devolverlas todas es lo que hace el aviso accionable.
    datos = [
        _grado("Grado A", "https://eps.ujaen.es/a"),
        _grado("Grado B", "https://eps.ujaen.es/b"),
    ]
    assert check_dataset.grados_sin_asignaturas(datos) == ["Grado A", "Grado B"]


def test_una_titulacion_sin_pagina_de_asignaturas_no_se_exige():
    # Si la fuente deja de publicar la página de un grado, eso es otro
    # problema distinto y no debe confundirse con "no supe leer sus tablas".
    datos = [_grado("Grado en Ingeniería Informática", None)]
    assert check_dataset.grados_sin_asignaturas(datos) == []

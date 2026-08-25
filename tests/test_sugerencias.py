"""Pruebas de las sugerencias de preguntas (Fase 3).

Sin red y sin modelo: el incrustador es falso e inyectado, y el índice se
construye con el propio ``indexer`` en la carpeta temporal de la prueba, igual
que en ``test_recuperador.py``. Se usa un índice de verdad, y no un doble que
finja contar filas, porque lo que hay que comprobar es que la expresión de
filtrado la entiende LanceDB: una expresión mal escrita no da error, devuelve
cero filas, y el resultado sería no ofrecer nunca esa pregunta.

Los nombres de titulación y el reparto de orígenes son los del corpus real
---rastreo del 16/08/2026, troceado del 19/08/2026, curso 2026-27---:
Informática con menciones, Organización Industrial sin ellas y el doble grado
internacional con Schmalkalden, que no tiene ni una asignatura indexada.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tfg_uja.incrustaciones import MODELO
from tfg_uja.indexer import reconstruir_indice
from tfg_uja.recuperador import abrir_indice
from tfg_uja.sugerencias import (
    ARRANQUE_CATALOGO,
    MAXIMO,
    PETICION_DE_CONSEJO,
    sugerencias_para,
)

DIMENSION = 8

ELECTRICA = "Grado en Ingeniería Eléctrica"
ELECTRONICA = "Grado en Ingeniería Electrónica Industrial"
INFORMATICA = "Grado en Ingeniería Informática"
MECANICA = "Grado en Ingeniería Mecánica"
ORGANIZACION = "Grado en Ingeniería de Organización Industrial"
SCHMALKALDEN = (
    "Doble Grado en Ingeniería Mecánica (Internacional - University of "
    "Applied Sciences Schmalkalden, Alemania)"
)

#: Catálogo que el índice graba de sí mismo, tal como lo devuelve
#: ``catalogo_del_indice``.
CATALOGO = [
    ELECTRICA,
    ELECTRONICA,
    INFORMATICA,
    MECANICA,
    ORGANIZACION,
    SCHMALKALDEN,
]


def incrustador_falso(textos: list[str]) -> list[list[float]]:
    """Incrustador determinista. Aquí no se busca por similitud, pero el
    indexador necesita vectores para construir la tabla."""
    return [[float(len(t) % 97)] + [0.0] * (DIMENSION - 1) for t in textos]


def chunk(origen: str, nombre: str, grados: list[str]) -> dict[str, Any]:
    """Fragmento con la forma exacta que emite el fragmentador."""
    return {
        "tipo": "chunk",
        "origen": origen,
        "grados": grados,
        "codigos": [None] * len(grados),
        "nombre": nombre,
        "texto": f"{nombre}. Contenido de prueba.",
        "tipo_asignatura": "",
        "curso": "",
        "chunk_index": 0,
        "total_chunks": 1,
    }


#: Reparto de orígenes copiado del índice real: Informática tiene de todo;
#: Organización Industrial no tiene menciones; el doble internacional solo
#: tiene ficha, porque la EPSJ no le publica asignaturas.
CHUNKS = [
    chunk("catalogo", "Titulaciones que se imparten en la EPSJ", CATALOGO),
    chunk("ficha_titulacion", f"Datos generales del {INFORMATICA}", [INFORMATICA]),
    chunk(
        "plan_de_estudios", f"Obligatorias de primero del {INFORMATICA}", [INFORMATICA]
    ),
    chunk("mencion", f"Menciones del {INFORMATICA}", [INFORMATICA]),
    chunk("salidas", INFORMATICA, [INFORMATICA]),
    chunk("guia", "Fundamentos de la programación", [INFORMATICA]),
    chunk("ficha_titulacion", f"Datos generales del {ORGANIZACION}", [ORGANIZACION]),
    chunk(
        "plan_de_estudios",
        f"Obligatorias de primero del {ORGANIZACION}",
        [ORGANIZACION],
    ),
    chunk("salidas", ORGANIZACION, [ORGANIZACION]),
    chunk("ficha_titulacion", f"Datos generales del {SCHMALKALDEN}", [SCHMALKALDEN]),
    chunk("ficha_titulacion", f"Datos generales del {ELECTRICA}", [ELECTRICA]),
    chunk("plan_de_estudios", f"Obligatorias de primero del {ELECTRICA}", [ELECTRICA]),
    chunk("ficha_titulacion", f"Datos generales del {ELECTRONICA}", [ELECTRONICA]),
    chunk(
        "plan_de_estudios", f"Obligatorias de primero del {ELECTRONICA}", [ELECTRONICA]
    ),
    chunk("ficha_titulacion", f"Datos generales del {MECANICA}", [MECANICA]),
    chunk("plan_de_estudios", f"Obligatorias de primero del {MECANICA}", [MECANICA]),
]


def construir(ruta: Path, chunks: list[dict[str, Any]]) -> Any:
    """Construye un índice con esos fragmentos y devuelve la tabla abierta."""
    ruta_chunks = ruta / "chunks.json"
    ruta_chunks.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    ruta_indice = ruta / "indice"
    reconstruir_indice(ruta_chunks, ruta_indice, incrustador_falso, MODELO)
    return abrir_indice(ruta_indice, MODELO)


@pytest.fixture()
def tabla(tmp_path) -> Any:
    """Índice con el reparto de orígenes del corpus real."""
    return construir(tmp_path, CHUNKS)


# --- Conversación recién empezada ---


def test_sin_ambito_se_ofrece_el_catalogo_y_la_peticion_de_consejo(tabla):
    """Al arrancar solo se ofrece lo que siempre se puede responder."""
    assert sugerencias_para(tabla, [], CATALOGO) == [
        *ARRANQUE_CATALOGO,
        PETICION_DE_CONSEJO,
    ]


def test_sin_fragmentos_de_catalogo_solo_queda_la_peticion_de_consejo(tmp_path):
    """Un índice de un corpus sin fragmentos de catálogo no ofrece esa pregunta.

    No es un caso inventado: los fragmentos de catálogo los empezó a emitir el
    fragmentador más tarde que el resto, y reindexar un ``chunks.json`` viejo
    no falla ---el indexador lo admite a propósito---, así que la tabla existe
    y responde, pero sin esas tres filas.
    """
    sin_catalogo = [c for c in CHUNKS if c["origen"] != "catalogo"]
    tabla = construir(tmp_path, sin_catalogo)
    assert sugerencias_para(tabla, [], CATALOGO) == [PETICION_DE_CONSEJO]


def test_un_nombre_fuera_del_catalogo_no_llega_al_filtro(tabla):
    """Lo que no declara el índice no se filtra: se cae al arranque.

    Filtrar por una titulación que el índice no tiene devuelve cero fragmentos
    y todas sus preguntas serían un rechazo garantizado, que es justo lo que
    este módulo existe para evitar.
    """
    ajena = ["Grado en Medicina"]
    assert sugerencias_para(tabla, ajena, CATALOGO) == sugerencias_para(
        tabla, [], CATALOGO
    )


# --- Una sola titulación ---


def test_se_ofrece_todo_lo_que_el_indice_tiene_de_la_titulacion(tabla):
    """Informática tiene los cuatro orígenes, así que salen las cuatro."""
    assert sugerencias_para(tabla, [INFORMATICA], CATALOGO) == [
        f"¿Qué asignaturas tiene el {INFORMATICA}?",
        f"¿Qué menciones ofrece el {INFORMATICA}?",
        f"¿Qué salidas profesionales tiene el {INFORMATICA}?",
        f"¿Cuántas asignaturas tiene el {INFORMATICA} y cómo se reparten por curso?",
    ]


def test_no_se_pregunta_por_menciones_a_quien_no_las_tiene(tabla):
    """Regresión de lo que motiva el módulo entero.

    Organización Industrial no tiene ni una mención indexada. Con una lista
    fija de sugerencias se le ofrecería igual, y lo que llegaría al modelo
    serían fragmentos de otra cosa: sobre el índice real esa pregunta trae
    cinco fragmentos de plan de estudios, salidas y ficha, y ninguno de
    mención.
    """
    preguntas = sugerencias_para(tabla, [ORGANIZACION], CATALOGO)
    assert not any("menciones" in p for p in preguntas)
    assert preguntas == [
        f"¿Qué asignaturas tiene el {ORGANIZACION}?",
        f"¿Qué salidas profesionales tiene el {ORGANIZACION}?",
        f"¿Cuántas asignaturas tiene el {ORGANIZACION} y cómo se reparten por curso?",
    ]


def test_una_titulacion_sin_asignaturas_solo_ofrece_su_ficha(tabla):
    """El doble grado internacional no tiene ni una asignatura en el índice."""
    assert sugerencias_para(tabla, [SCHMALKALDEN], CATALOGO) == [
        f"¿Cuántas asignaturas tiene el {SCHMALKALDEN} y cómo se reparten por curso?",
    ]


# --- Varias titulaciones ---


def test_con_varias_se_ofrece_una_pregunta_por_cada_una(tabla):
    """Con el ámbito ambiguo, cada sugerencia nombra a una titulación distinta.

    Es lo que permite deshacer la ambigüedad: al pulsar una, el ámbito se
    queda en esa sola.
    """
    preguntas = sugerencias_para(tabla, [INFORMATICA, ORGANIZACION], CATALOGO)
    assert preguntas == [
        f"¿Qué asignaturas tiene el {INFORMATICA}?",
        f"¿Qué asignaturas tiene el {ORGANIZACION}?",
    ]


def test_nunca_se_pasa_del_maximo(tabla):
    """Cinco titulaciones en el ámbito siguen dando cuatro botones."""
    ambito = [ELECTRICA, ELECTRONICA, INFORMATICA, MECANICA, ORGANIZACION]
    preguntas = sugerencias_para(tabla, ambito, CATALOGO)
    assert len(preguntas) == MAXIMO
    assert len(set(preguntas)) == MAXIMO

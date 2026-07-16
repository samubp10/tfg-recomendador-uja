"""Pruebas del pipeline de indexación (IT-30).

La fixture ``chunks_muestra_real.json`` contiene chunks REALES copiados del
``chunks.json`` del dataset completo (no inventados), elegidos para cubrir
las anomalías reales de la fuente: una guía compartida entre cuatro
titulaciones (listas paralelas ``grados``/``codigos``), un bloque de salidas
profesionales (``codigos=[None]``) y una asignatura sin guía.

El incrustador es falso e inyectado: determinista y sin red, porque estas
pruebas verifican el pipeline de indexación, no el modelo de embeddings
(cuya elección es objeto del experimento IT-28).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import chromadb
import pytest

from tfg_uja.indexer import (
    COLECCION,
    SEPARADOR_LISTAS,
    indexar_chunks,
    metadatos_de_chunk,
    reconstruir_indice,
)

FIXTURES = Path(__file__).parent / "fixtures"
RUTA_MUESTRA = FIXTURES / "chunks_muestra_real.json"

#: Dimensión del incrustador falso. Pequeña a propósito: el contenido de los
#: vectores es irrelevante para estas pruebas.
DIMENSION = 8


def incrustador_falso(textos: list[str]) -> list[list[float]]:
    """Incrustador determinista sin red: un vector fijo por longitud del texto."""
    return [
        [float(len(texto) % 97)] + [0.0] * (DIMENSION - 1) for texto in textos
    ]


@pytest.fixture()
def chunks_reales() -> list[dict[str, Any]]:
    """Chunks reales del dataset, con sus anomalías conocidas."""
    datos: list[dict[str, Any]] = json.loads(
        RUTA_MUESTRA.read_text(encoding="utf-8")
    )
    return datos


@pytest.fixture()
def coleccion() -> chromadb.Collection:
    """Colección efímera de ChromaDB (en memoria, sin persistencia).

    El nombre lleva un sufijo único porque el cliente efímero de ChromaDB
    comparte estado dentro del proceso: un nombre fijo colisionaría entre
    tests.
    """
    cliente = chromadb.EphemeralClient()
    return cliente.create_collection(
        f"prueba_chunks_{uuid4().hex}", metadata={"hnsw:space": "cosine"}
    )


def test_indexa_todos_los_chunks(chunks_reales, coleccion):
    """El nº de vectores indexados coincide con el nº de chunks (DoD IT-30)."""
    total = indexar_chunks(chunks_reales, coleccion, incrustador_falso)
    assert total == len(chunks_reales)
    assert coleccion.count() == len(chunks_reales)


def test_metadatos_sin_perdida(chunks_reales, coleccion):
    """Grados, códigos, nombre y numeración sobreviven al viaje de ida y vuelta."""
    indexar_chunks(chunks_reales, coleccion, incrustador_falso)
    guardado = coleccion.get(ids=["chunk-0000"], include=["metadatas", "documents"])
    original = chunks_reales[0]
    metadatos = guardado["metadatas"][0]
    assert metadatos["nombre"] == original["nombre"]
    assert metadatos["origen"] == original["origen"]
    assert metadatos["grados"] == SEPARADOR_LISTAS.join(original["grados"])
    assert metadatos["chunk_index"] == original["chunk_index"]
    assert metadatos["total_chunks"] == original["total_chunks"]
    assert guardado["documents"][0] == original["texto"]


def test_guia_compartida_conserva_las_listas_paralelas(chunks_reales):
    """Una guía impartida en 4 titulaciones conserva sus 4 grados y 4 códigos."""
    compartido = next(c for c in chunks_reales if len(c["grados"]) == 4)
    metadatos = metadatos_de_chunk(compartido)
    assert metadatos["grados"].count(SEPARADOR_LISTAS) == 3
    assert metadatos["codigos"].count(SEPARADOR_LISTAS) == 3
    # El orden de ambas listas debe ser el mismo (son paralelas).
    assert metadatos["grados"].split(SEPARADOR_LISTAS) == compartido["grados"]
    assert metadatos["codigos"].split(SEPARADOR_LISTAS) == compartido["codigos"]


def test_codigo_ausente_se_refleja_como_vacio(chunks_reales):
    """Las salidas profesionales (codigos=[None]) no rompen ni se imputan."""
    salidas = next(c for c in chunks_reales if c["origen"] == "salidas")
    assert salidas["codigos"] == [None]  # anomalía real de la fuente
    metadatos = metadatos_de_chunk(salidas)
    assert metadatos["codigos"] == ""


def test_reconstruir_no_duplica(tmp_path, chunks_reales):
    """Reindexar dos veces deja exactamente un vector por chunk, no dos."""
    ruta_chunks = tmp_path / "chunks.json"
    ruta_chunks.write_text(
        json.dumps(chunks_reales, ensure_ascii=False), encoding="utf-8"
    )
    ruta_indice = tmp_path / "indice"
    reconstruir_indice(ruta_chunks, ruta_indice, incrustador_falso)
    total = reconstruir_indice(ruta_chunks, ruta_indice, incrustador_falso)
    assert total == len(chunks_reales)
    cliente = chromadb.PersistentClient(path=str(ruta_indice))
    assert cliente.get_collection(COLECCION).count() == len(chunks_reales)

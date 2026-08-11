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
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

import chromadb
import pytest

from tfg_uja.incrustaciones import MODELO, PREFIJO_DOCUMENTO
from tfg_uja.indexer import (
    COLECCION,
    AlmacenChroma,
    AlmacenVectorial,
    Metadatos,
    cargar_chunks,
    crear_almacen_chroma,
    indexar_chunks,
    metadatos_de_chunk,
    procedencia_de_indice,
    reconstruir_indice,
)

FIXTURES = Path(__file__).parent / "fixtures"
RUTA_MUESTRA = FIXTURES / "chunks_muestra_real.json"

#: Dimensión del incrustador falso. Pequeña a propósito: el contenido de los
#: vectores es irrelevante para estas pruebas.
DIMENSION = 8


def incrustador_falso(textos: list[str]) -> list[list[float]]:
    """Incrustador determinista sin red: un vector fijo por longitud del texto."""
    return [[float(len(texto) % 97)] + [0.0] * (DIMENSION - 1) for texto in textos]


@pytest.fixture()
def chunks_reales() -> list[dict[str, Any]]:
    """Chunks reales del dataset, con sus anomalías conocidas."""
    datos: list[dict[str, Any]] = json.loads(RUTA_MUESTRA.read_text(encoding="utf-8"))
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


@pytest.fixture()
def almacen(coleccion) -> AlmacenVectorial:
    """El almacén de hoy: ChromaDB en memoria."""
    return AlmacenChroma(coleccion)


def test_indexa_todos_los_chunks(chunks_reales, almacen, coleccion):
    """El nº de vectores indexados coincide con el nº de chunks (DoD IT-30)."""
    total = indexar_chunks(chunks_reales, almacen, incrustador_falso)
    assert total == len(chunks_reales)
    assert coleccion.count() == len(chunks_reales)


def test_metadatos_sin_perdida(chunks_reales, almacen, coleccion):
    """Grados, códigos, nombre y numeración sobreviven al viaje de ida y vuelta."""
    indexar_chunks(chunks_reales, almacen, incrustador_falso)
    guardado = coleccion.get(ids=["chunk-0000"], include=["metadatas", "documents"])
    original = chunks_reales[0]
    metadatos = guardado["metadatas"][0]
    assert metadatos["nombre"] == original["nombre"]
    assert metadatos["origen"] == original["origen"]
    assert list(metadatos["grados"]) == original["grados"]
    assert metadatos["chunk_index"] == original["chunk_index"]
    assert metadatos["total_chunks"] == original["total_chunks"]
    assert guardado["documents"][0] == original["texto"]


def test_guia_compartida_conserva_las_listas_paralelas(chunks_reales):
    """Una guía impartida en 4 titulaciones conserva sus 4 grados y 4 códigos."""
    compartido = next(c for c in chunks_reales if len(c["grados"]) == 4)
    metadatos = metadatos_de_chunk(compartido)
    # Se guardan como listas, no serializadas: es lo que permite filtrar por
    # pertenencia exacta en vez de por subcadena.
    assert metadatos["grados"] == compartido["grados"]
    assert metadatos["codigos"] == compartido["codigos"]


def test_codigo_ausente_se_refleja_como_vacio(chunks_reales):
    """Las salidas profesionales (codigos=[None]) no rompen ni se imputan."""
    salidas = next(c for c in chunks_reales if c["origen"] == "salidas")
    assert salidas["codigos"] == [None]  # anomalía real de la fuente
    metadatos = metadatos_de_chunk(salidas)
    assert metadatos["codigos"] == [""]


def test_un_codigo_ausente_no_impide_almacenar(chunks_reales, almacen, coleccion):
    """ChromaDB rechaza una lista de metadatos con None: hay que traducirlo.

    Regresión: 55 fragmentos del corpus llegan con ``codigos=[None]`` porque
    hablan de la titulación entera. Guardar la lista en crudo lanzaría
    ``ValueError`` y la indexación entera se caería.
    """
    salidas = [c for c in chunks_reales if c["origen"] == "salidas"]
    assert salidas, "la fixture debe incluir un bloque de salidas"
    indexar_chunks(salidas, almacen, incrustador_falso)
    assert coleccion.count() == len(salidas)


# --- IT-31: filtrar por una titulación no puede arrastrar al doble grado ---


def test_filtrar_por_una_titulacion_no_arrastra_el_doble_grado(coleccion):
    """El caso real que decide guardar listas en vez de una cadena unida.

    Cuatro nombres de titulación del corpus son subcadena de otro: «Grado en
    Ingeniería Eléctrica» lo es de «Doble Grado en Ingeniería Eléctrica y
    Mecánica». Con las listas serializadas en una cadena, filtrar por el grado
    simple devolvía también los fragmentos que solo pertenecen al doble.
    Guardándolas como listas, ``$contains`` casa por elemento exacto.
    """
    simple = "Grado en Ingeniería Eléctrica"
    doble = "Doble Grado en Ingeniería Eléctrica y Mecánica"
    chunks = [
        {
            "tipo": "chunk",
            "origen": "guia",
            "grados": [simple, doble],
            "codigos": ["13112002", "13612001"],
            "nombre": "Compartida",
            "texto": "Se imparte en el grado simple y en el doble.",
            "tipo_asignatura": "OB",
            "chunk_index": 0,
            "total_chunks": 1,
        },
        {
            "tipo": "chunk",
            "origen": "guia",
            "grados": [doble],
            "codigos": ["13612002"],
            "nombre": "Solo del doble",
            "texto": "Solo se imparte en la titulación doble.",
            "tipo_asignatura": "OB",
            "chunk_index": 0,
            "total_chunks": 1,
        },
    ]
    indexar_chunks(chunks, AlmacenChroma(coleccion), incrustador_falso)

    recuperado = coleccion.get(where={"grados": {"$contains": simple}})
    nombres = {m["nombre"] for m in recuperado["metadatas"]}
    assert nombres == {"Compartida"}, "el del doble grado es un falso positivo"


def test_filtrar_por_titulacion_y_tipo_a_la_vez(coleccion):
    """La consulta que motiva el metadato de tipo: «obligatorias de este grado»."""
    grado = "Grado en Ingeniería Informática"
    chunks = [
        {
            "tipo": "chunk",
            "origen": "guia",
            "grados": [grado],
            "codigos": ["13312001"],
            "nombre": "Obligatoria",
            "texto": "Asignatura obligatoria.",
            "tipo_asignatura": "OB",
            "chunk_index": 0,
            "total_chunks": 1,
        },
        {
            "tipo": "chunk",
            "origen": "guia",
            "grados": [grado],
            "codigos": ["13312002"],
            "nombre": "Optativa",
            "texto": "Asignatura optativa.",
            "tipo_asignatura": "OP",
            "chunk_index": 0,
            "total_chunks": 1,
        },
    ]
    indexar_chunks(chunks, AlmacenChroma(coleccion), incrustador_falso)

    recuperado = coleccion.get(
        where={
            "$and": [
                {"grados": {"$contains": grado}},
                {"tipo_asignatura": {"$eq": "OB"}},
            ]
        }
    )
    assert [m["nombre"] for m in recuperado["metadatas"]] == ["Obligatoria"]


# --- IT-31: el pipeline no depende de ChromaDB ---


def test_el_pipeline_escribe_en_cualquier_almacen(chunks_reales):
    """El recorrido de indexación no conoce la base: IT-31 compara tres.

    Si el pipeline estuviera soldado a una base concreta, comparar varias
    obligaría a reimplementar la indexación una vez por candidata, y entonces
    el experimento no mediría las bases sino el código escrito para cada una.
    """
    escrito: list[Metadatos] = []

    class AlmacenDePrueba:
        def anadir(
            self,
            ids: list[str],
            vectores: list[Sequence[float]],
            textos: list[str],
            metadatos: list[Metadatos],
        ) -> None:
            escrito.extend(metadatos)

    total = indexar_chunks(chunks_reales, AlmacenDePrueba(), incrustador_falso)
    assert total == len(chunks_reales)
    assert len(escrito) == len(chunks_reales)
    assert all(isinstance(m["grados"], list) for m in escrito)


def test_reconstruir_admite_otro_almacen(tmp_path, chunks_reales):
    """`reconstruir_indice` acepta el creador de almacén como parámetro."""
    ruta_chunks = tmp_path / "chunks.json"
    ruta_chunks.write_text(
        json.dumps(chunks_reales, ensure_ascii=False), encoding="utf-8"
    )
    recibidos: dict[str, str] = {}

    class AlmacenDePrueba:
        def anadir(
            self,
            ids: list[str],
            vectores: list[Sequence[float]],
            textos: list[str],
            metadatos: list[Metadatos],
        ) -> None:
            pass

    def crear(ruta: Path, metadatos_coleccion: dict[str, str]) -> AlmacenVectorial:
        recibidos.update(metadatos_coleccion)
        return AlmacenDePrueba()

    total = reconstruir_indice(
        ruta_chunks, tmp_path / "indice", incrustador_falso, MODELO, crear
    )
    assert total == len(chunks_reales)
    # El creador recibe con qué se construyó el índice, sea cual sea la base.
    assert recibidos["modelo"] == MODELO
    assert recibidos["prefijo_documento"] == PREFIJO_DOCUMENTO


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


def test_el_almacen_de_chroma_parte_vacio(tmp_path):
    """El creador borra el índice anterior: es un artefacto regenerable."""
    ruta = tmp_path / "indice"
    crear_almacen_chroma(ruta, {"modelo": MODELO})
    cliente = chromadb.PersistentClient(path=str(ruta))
    assert cliente.get_collection(COLECCION).count() == 0


# --- IT-90: el item de procedencia no se indexa ---


def test_no_se_indexa_la_procedencia_del_corpus(tmp_path):
    # chunks.json encabeza la lista con la procedencia (IT-90). No es contenido
    # recuperable: si acabara en el índice, una consulta podría devolverla como
    # si fuera información sobre una titulación.
    fichero = tmp_path / "chunks.json"
    fichero.write_text(
        json.dumps(
            [
                {
                    "tipo": "procedencia",
                    "fecha_extraccion": "2026-07-28",
                    "cursos": ["2025-26"],
                },
                {
                    "tipo": "chunk",
                    "origen": "guia",
                    "grados": ["Grado A"],
                    "codigos": ["10000001"],
                    "nombre": "Álgebra",
                    "texto": "«Álgebra»...\nMatrices y determinantes.",
                    "chunk_index": 0,
                    "total_chunks": 1,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunks = cargar_chunks(fichero)
    assert len(chunks) == 1
    assert chunks[0]["nombre"] == "Álgebra"


def test_la_procedencia_sigue_siendo_consultable(tmp_path):
    # Descartarla al indexar no significa perderla: el índice debe poder decir
    # de cuándo y de qué curso es el corpus que contiene.
    fichero = tmp_path / "chunks.json"
    fichero.write_text(
        json.dumps(
            [{"tipo": "procedencia", "fecha_extraccion": "2026-07-28"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert procedencia_de_indice(fichero)["fecha_extraccion"] == "2026-07-28"


def test_un_chunks_json_anterior_a_it90_no_rompe_al_indexar(tmp_path):
    fichero = tmp_path / "chunks.json"
    fichero.write_text(json.dumps([]), encoding="utf-8")
    assert cargar_chunks(fichero) == []
    assert procedencia_de_indice(fichero) == {}


# --- IT-98: el índice dice con qué modelo se construyó ---


def test_el_indice_registra_el_modelo_y_el_prefijo(tmp_path, chunks_reales):
    # Dos modelos distintos pueden dar vectores de la misma dimensión (384
    # tanto el del ADR-0003 como el anterior), así que consultar un índice con
    # el modelo equivocado NO da ningún error: solo resultados peores. Sin este
    # registro, nadie tiene forma de detectarlo.
    ruta_chunks = tmp_path / "chunks.json"
    ruta_chunks.write_text(
        json.dumps(chunks_reales, ensure_ascii=False), encoding="utf-8"
    )
    ruta_indice = tmp_path / "indice"
    reconstruir_indice(ruta_chunks, ruta_indice, incrustador_falso, MODELO)

    cliente = chromadb.PersistentClient(path=str(ruta_indice))
    metadatos = cliente.get_collection(COLECCION).metadata
    assert metadatos["modelo"] == MODELO
    assert metadatos["prefijo_documento"] == PREFIJO_DOCUMENTO

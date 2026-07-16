"""Pipeline de indexación: de los chunks al índice vectorial (IT-30).

Toma los chunks generados por el fragmentador (``chunks.json``), calcula la
incrustación (*embedding*) de cada uno y los almacena, junto con sus
metadatos, en una colección persistente de ChromaDB lista para la fase de
recuperación del RAG.

El índice se reconstruye completo en cada ejecución: reindexar es barato
(minutos) frente al coste de mantener actualizaciones incrementales, y
garantiza que el índice refleja exactamente el ``chunks.json`` de entrada,
igual que re-fragmentar garantiza reflejar el dataset (mismo argumento de
reproducibilidad que separa el spider del chunker).

PROVISIONAL (Fase 1): tanto el modelo de embeddings por defecto como la
elección de ChromaDB son valores de trabajo para poder construir y probar el
pipeline; las elecciones definitivas se decidirán experimentalmente en
IT-28/IT-31 y se justificarán en los ADR-0003 y ADR-0004. El modelo es un
parámetro de la función precisamente para que el experimento de IT-28 pueda
intercambiarlo sin tocar este módulo.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable, Final

import chromadb

#: Modelo de embeddings por defecto. PROVISIONAL hasta el experimento IT-28
#: (ADR-0003): es el punto de partida razonable por ser multilingüe (el
#: corpus está en español), compacto (ejecutable en CPU doméstica, requisito
#: del proyecto) y un modelo de referencia de la librería sentence-transformers.
#: No se presenta como óptimo: es el valor de trabajo del pipeline.
MODELO_PROVISIONAL: Final[str] = "paraphrase-multilingual-MiniLM-L12-v2"

#: Nombre de la colección dentro del índice de ChromaDB.
COLECCION: Final[str] = "chunks_epsj"

#: Chunks que se incrustan y almacenan por lote. Limita la memoria usada por
#: el modelo de embeddings sin penalizar apenas el rendimiento.
TAMANO_LOTE: Final[int] = 64

#: Separador con el que se serializan las listas paralelas ``grados`` y
#: ``codigos`` en los metadatos, porque ChromaDB solo admite valores
#: escalares (str/int/float/bool) como metadato. Se eligió una secuencia que
#: no aparece en ningún nombre de grado ni código del dataset real.
SEPARADOR_LISTAS: Final[str] = " | "

#: Firma de la función de incrustación: recibe una lista de textos y
#: devuelve un vector de números reales por texto, en el mismo orden.
Incrustador = Callable[[list[str]], list[list[float]]]


def cargar_chunks(ruta: Path) -> list[dict[str, Any]]:
    """Carga los chunks desde el JSON exportado por el fragmentador.

    Args:
        ruta: Ruta del ``chunks.json``.

    Returns:
        Lista de items ``chunk`` tal como los emite ``chunker.py``.
    """
    chunks: list[dict[str, Any]] = json.loads(ruta.read_text(encoding="utf-8"))
    return chunks


def metadatos_de_chunk(chunk: dict[str, Any]) -> dict[str, str | int]:
    """Convierte los metadatos de un chunk al formato escalar de ChromaDB.

    Las listas paralelas ``grados`` y ``codigos`` se serializan con
    :data:`SEPARADOR_LISTAS` porque ChromaDB no admite listas como metadato.
    Un código ausente (las salidas profesionales llevan ``codigos=[None]``)
    se representa como cadena vacía, fiel a la decisión del proyecto de
    reflejar los datos faltantes en lugar de imputarlos.

    Args:
        chunk: Item ``chunk`` del dataset.

    Returns:
        Metadatos escalares: origen, nombre, grados, codigos,
        ``chunk_index`` y ``total_chunks``.
    """
    return {
        "origen": chunk["origen"],
        "nombre": chunk["nombre"],
        "grados": SEPARADOR_LISTAS.join(chunk["grados"]),
        "codigos": SEPARADOR_LISTAS.join(
            codigo if codigo is not None else "" for codigo in chunk["codigos"]
        ),
        "chunk_index": chunk["chunk_index"],
        "total_chunks": chunk["total_chunks"],
    }


def indexar_chunks(
    chunks: list[dict[str, Any]],
    coleccion: chromadb.Collection,
    incrustar: Incrustador,
) -> int:
    """Incrusta y almacena todos los chunks en la colección, por lotes.

    El identificador de cada chunk es su posición en la lista de entrada:
    como el índice se reconstruye completo en cada ejecución, la posición es
    determinista para un ``chunks.json`` dado y no puede colisionar.

    Args:
        chunks: Items ``chunk`` a indexar.
        coleccion: Colección de ChromaDB destino (vacía).
        incrustar: Función que convierte una lista de textos en sus vectores.

    Returns:
        Número de chunks indexados.
    """
    for inicio in range(0, len(chunks), TAMANO_LOTE):
        lote = chunks[inicio : inicio + TAMANO_LOTE]
        textos = [chunk["texto"] for chunk in lote]
        # Anotación explícita: la firma de ChromaDB pide Sequence[float] y la
        # invarianza de list impide pasar list[list[float]] directamente.
        vectores: list[Sequence[float] | Sequence[int]] = list(incrustar(textos))
        coleccion.add(
            ids=[f"chunk-{inicio + i:04d}" for i in range(len(lote))],
            embeddings=vectores,
            documents=textos,
            metadatas=[metadatos_de_chunk(chunk) for chunk in lote],
        )
    return len(chunks)


def crear_incrustador(nombre_modelo: str) -> Incrustador:
    """Construye la función de incrustación a partir de un modelo.

    La importación de ``sentence_transformers`` es perezosa: solo la
    ejecución real del pipeline la necesita (extra ``[index]`` del
    proyecto); las pruebas usan un incrustador falso inyectado y no
    requieren descargar ningún modelo.

    Args:
        nombre_modelo: Nombre del modelo en el Hub de Hugging Face.

    Returns:
        Función que incrusta lotes de textos con ese modelo.
    """
    from sentence_transformers import SentenceTransformer

    modelo = SentenceTransformer(nombre_modelo)

    def incrustar(textos: list[str]) -> list[list[float]]:
        return modelo.encode(textos, show_progress_bar=False).tolist()

    return incrustar


def reconstruir_indice(
    ruta_chunks: Path,
    ruta_indice: Path,
    incrustar: Incrustador,
) -> int:
    """Reconstruye desde cero el índice vectorial persistente.

    Si la colección ya existía se elimina primero: el índice es un artefacto
    derivado y regenerable, nunca la fuente de verdad (esa es el pipeline
    ``scrapy`` → ``chunker`` → este módulo).

    Args:
        ruta_chunks: Ruta del ``chunks.json`` de entrada.
        ruta_indice: Carpeta donde persiste el índice de ChromaDB.
        incrustar: Función de incrustación a utilizar.

    Returns:
        Número de chunks indexados.
    """
    chunks = cargar_chunks(ruta_chunks)
    cliente = chromadb.PersistentClient(path=str(ruta_indice))
    try:
        cliente.delete_collection(COLECCION)
    except Exception:
        # La colección no existía todavía: primera ejecución.
        pass
    # Distancia coseno: la métrica habitual para embeddings de texto de
    # sentence-transformers. PROVISIONAL como el resto de elecciones de este
    # módulo (se revisará en IT-31 junto con la base de datos vectorial).
    coleccion = cliente.create_collection(
        COLECCION, metadata={"hnsw:space": "cosine"}
    )
    return indexar_chunks(chunks, coleccion, incrustar)


def main(argumentos: list[str]) -> None:
    """Punto de entrada de línea de comandos.

    Uso::

        py -m tfg_uja.indexer data/chunks.json data/indice [modelo]

    Args:
        argumentos: ``[ruta_chunks, ruta_indice]`` y, opcionalmente, el
            nombre del modelo de embeddings (por defecto,
            :data:`MODELO_PROVISIONAL`).
    """
    ruta_chunks = Path(argumentos[0])
    ruta_indice = Path(argumentos[1])
    modelo = argumentos[2] if len(argumentos) > 2 else MODELO_PROVISIONAL
    total = reconstruir_indice(ruta_chunks, ruta_indice, crear_incrustador(modelo))
    print(f"{total} chunks indexados en {ruta_indice} con el modelo {modelo}")


if __name__ == "__main__":
    main(sys.argv[1:])

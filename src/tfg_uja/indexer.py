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

El **modelo de embeddings ya no es provisional** (IT-98): lo fija el ADR-0003
y vive en ``incrustaciones.py``, junto con la convención de prefijos que ese
modelo exige. Este módulo no la conoce ni debe conocerla; recibe una función
de incrustación ya construida, que es lo que además permite probarlo sin red.

La elección de **ChromaDB sí sigue siendo provisional**: es un valor de
trabajo para poder construir el pipeline, y se decidirá experimentalmente en
IT-31, con su ADR-0004.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import chromadb

from tfg_uja.incrustaciones import (
    MODELO,
    PREFIJO_DOCUMENTO,
    Incrustador,
    incrustador_de_documentos,
)

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


def cargar_chunks(ruta: Path) -> list[dict[str, Any]]:
    """Carga los chunks desde el JSON exportado por el fragmentador.

    El fichero encabeza la lista con un item ``procedencia`` (IT-90), que
    describe de cuándo y de qué curso es el corpus pero no es contenido a
    indexar; se descarta filtrando por ``tipo`` en vez de por posición, para
    que el orden del fichero no sea un contrato implícito.

    Args:
        ruta: Ruta del ``chunks.json``.

    Returns:
        Lista de items ``chunk`` tal como los emite ``chunker.py``.
    """
    items: list[dict[str, Any]] = json.loads(ruta.read_text(encoding="utf-8"))
    return [item for item in items if item.get("tipo") == "chunk"]


def procedencia_de_indice(ruta: Path) -> dict[str, Any]:
    """Devuelve la procedencia registrada en un ``chunks.json``.

    Args:
        ruta: Ruta del ``chunks.json``.

    Returns:
        El item ``procedencia``, o un diccionario vacío si el fichero es
        anterior a IT-90 y no lo lleva.
    """
    items: list[dict[str, Any]] = json.loads(ruta.read_text(encoding="utf-8"))
    return next((i for i in items if i.get("tipo") == "procedencia"), {})


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
        # IT-100: el tipo viaja como metadato para poder filtrar el índice por
        # él («solo obligatorias de esta titulación»), que es una consulta que
        # la búsqueda vectorial no sabe hacer y el estudiante sí pregunta. Se
        # usa `.get` porque un chunks.json anterior a IT-100 no lo lleva y
        # reindexar un corpus viejo no tiene por qué fallar.
        "tipo_asignatura": chunk.get("tipo_asignatura", ""),
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


def reconstruir_indice(
    ruta_chunks: Path,
    ruta_indice: Path,
    incrustar: Incrustador,
    modelo: str = MODELO,
) -> int:
    """Reconstruye desde cero el índice vectorial persistente.

    Si la colección ya existía se elimina primero: el índice es un artefacto
    derivado y regenerable, nunca la fuente de verdad (esa es el pipeline
    ``scrapy`` → ``chunker`` → este módulo).

    El nombre del modelo y el prefijo de documento quedan grabados en los
    metadatos de la colección. No es adorno: dos modelos distintos pueden
    producir vectores de la misma dimensión —384 tanto el actual como el
    anterior—, así que consultar un índice con el modelo equivocado **no da
    ningún error**, solo resultados peores. Grabarlo es lo que permite al
    recuperador comprobarlo en vez de suponerlo.

    Args:
        ruta_chunks: Ruta del ``chunks.json`` de entrada.
        ruta_indice: Carpeta donde persiste el índice de ChromaDB.
        incrustar: Función de incrustación a utilizar.
        modelo: Nombre del modelo que se registra en la colección. Debe
            corresponder al que usa ``incrustar``; se pasa aparte porque el
            incrustador es una función y no se le puede preguntar de dónde
            viene, y porque las pruebas inyectan uno falso.

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
    # sentence-transformers. PROVISIONAL (se revisará en IT-31 junto con la
    # base de datos vectorial), a diferencia del modelo, que ya lo fija el
    # ADR-0003.
    coleccion = cliente.create_collection(
        COLECCION,
        metadata={
            "hnsw:space": "cosine",
            "modelo": modelo,
            "prefijo_documento": PREFIJO_DOCUMENTO,
        },
    )
    return indexar_chunks(chunks, coleccion, incrustar)


def main(argumentos: list[str]) -> None:
    """Punto de entrada de línea de comandos.

    Uso::

        py -m tfg_uja.indexer data/chunks.json data/indice [modelo]

    Args:
        argumentos: ``[ruta_chunks, ruta_indice]`` y, opcionalmente, el
            nombre del modelo de embeddings (por defecto,
            :data:`tfg_uja.incrustaciones.MODELO`, el del ADR-0003). Sigue
            siendo un parámetro para poder repetir el experimento con otro
            modelo sin tocar el código, no porque la elección esté abierta.
    """
    ruta_chunks = Path(argumentos[0])
    ruta_indice = Path(argumentos[1])
    modelo = argumentos[2] if len(argumentos) > 2 else MODELO
    total = reconstruir_indice(
        ruta_chunks, ruta_indice, incrustador_de_documentos(modelo), modelo
    )
    print(f"{total} chunks indexados en {ruta_indice} con el modelo {modelo}")


if __name__ == "__main__":
    main(sys.argv[1:])

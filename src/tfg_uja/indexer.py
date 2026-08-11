"""Pipeline de indexación: de los chunks al índice vectorial (IT-30).

Toma los chunks generados por el fragmentador (``chunks.json``), calcula la
incrustación (*embedding*) de cada uno y los almacena, junto con sus
metadatos, en un índice vectorial listo para la fase de recuperación del RAG.

El índice se reconstruye completo en cada ejecución: reindexar es barato
(minutos) frente al coste de mantener actualizaciones incrementales, y
garantiza que el índice refleja exactamente el ``chunks.json`` de entrada,
igual que re-fragmentar garantiza reflejar el dataset (mismo argumento de
reproducibilidad que separa el spider del chunker).

El **modelo de embeddings ya no es provisional** (IT-98): lo fija el ADR-0003
y vive en ``incrustaciones.py``, junto con la convención de prefijos que ese
modelo exige. Este módulo no la conoce ni debe conocerla; recibe una función
de incrustación ya construida, que es lo que además permite probarlo sin red.

La elección de **la base vectorial sí sigue siendo provisional**: se decide
experimentalmente en IT-31, con su ADR-0004. Por eso el recorrido ---leer,
incrustar por lotes, componer metadatos--- está separado de dónde se guarda:
:class:`AlmacenVectorial` describe lo único que el pipeline necesita de una
base, y :func:`crear_almacen_chroma` es la implementación de hoy. Comparar
tres bases en IT-31 es entonces escribir tres creadores, no tres pipelines;
si se midiera con tres implementaciones distintas no se estaría comparando
la base, sino el código escrito para la ocasión.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, Protocol

import chromadb

from tfg_uja.incrustaciones import (
    MODELO,
    PREFIJO_DOCUMENTO,
    Incrustador,
    incrustador_de_documentos,
)

#: Nombre de la colección dentro del índice.
COLECCION: Final[str] = "chunks_epsj"

#: Chunks que se incrustan y almacenan por lote. Limita la memoria usada por
#: el modelo de embeddings sin penalizar apenas el rendimiento.
TAMANO_LOTE: Final[int] = 64

#: Valor con el que se representa un código de asignatura ausente. Las salidas
#: profesionales y los planes de estudio llegan con ``codigos=[None]`` porque
#: hablan de la titulación entera y no de una asignatura. Se traduce a cadena
#: vacía, no se omite: el dato ausente se refleja, no se imputa. Y hay una
#: razón técnica además de la de principios: ChromaDB rechaza una lista de
#: metadatos que contenga ``None`` (comprobado con 1.5.9).
CODIGO_AUSENTE: Final[str] = ""

#: Metadatos de un chunk. Las listas paralelas ``grados`` y ``codigos`` se
#: guardan **como listas**, no serializadas en una cadena: es lo que permite
#: filtrar por pertenencia exacta. Serializarlas convertiría el filtro en una
#: coincidencia de subcadena, y cuatro nombres de titulación del corpus son
#: subcadena de otro ---«Grado en Ingeniería Eléctrica» lo es de «Doble Grado
#: en Ingeniería Eléctrica y Mecánica»---, de modo que filtrar por el grado
#: simple arrastraría fragmentos del doble.
Metadatos = dict[str, str | int | list[str]]


class AlmacenVectorial(Protocol):
    """Lo único que el pipeline de indexación necesita de una base vectorial.

    Deliberadamente mínimo: describe la operación de escritura y nada más. La
    consulta no aparece porque este módulo no consulta, y añadirla ahora sería
    diseñar contra un recuperador que todavía no existe.
    """

    def anadir(
        self,
        ids: list[str],
        vectores: list[Sequence[float]],
        textos: list[str],
        metadatos: list[Metadatos],
    ) -> None:
        """Almacena un lote de vectores con su texto y sus metadatos."""


#: Función que prepara un almacén vacío donde escribir. Recibe la carpeta de
#: destino y los metadatos que describen con qué se construyó el índice.
CreadorDeAlmacen = Callable[[Path, dict[str, str]], AlmacenVectorial]


class AlmacenChroma:
    """Adaptador de una colección de ChromaDB a :class:`AlmacenVectorial`."""

    def __init__(self, coleccion: chromadb.Collection) -> None:
        self.coleccion = coleccion

    def anadir(
        self,
        ids: list[str],
        vectores: list[Sequence[float]],
        textos: list[str],
        metadatos: list[Metadatos],
    ) -> None:
        """Almacena un lote en la colección.

        Args:
            ids: Identificadores del lote.
            vectores: Incrustaciones, una por texto.
            textos: Texto de cada chunk.
            metadatos: Metadatos de cada chunk.
        """
        # Anotaciones explícitas: las firmas de ChromaDB piden tipos más
        # amplios y la invarianza de list impide pasar los nuestros directos.
        embeddings: list[Sequence[float] | Sequence[int]] = list(vectores)
        self.coleccion.add(
            ids=ids,
            embeddings=embeddings,
            documents=textos,
            metadatas=[dict(m) for m in metadatos],  # type: ignore[arg-type]
        )


def crear_almacen_chroma(
    ruta_indice: Path, metadatos_coleccion: dict[str, str]
) -> AlmacenVectorial:
    """Crea un índice persistente de ChromaDB vacío, borrando el anterior.

    Args:
        ruta_indice: Carpeta donde persiste el índice.
        metadatos_coleccion: Metadatos que describen el índice (modelo,
            prefijo y métrica de distancia).

    Returns:
        Almacén listo para recibir vectores.
    """
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
    return AlmacenChroma(
        cliente.create_collection(
            COLECCION, metadata={"hnsw:space": "cosine", **metadatos_coleccion}
        )
    )


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


def metadatos_de_chunk(chunk: dict[str, Any]) -> Metadatos:
    """Compone los metadatos con los que viaja un chunk en el índice.

    ``grados`` y ``codigos`` se conservan como listas paralelas, que es como
    los emite el fragmentador y lo que permite filtrar por pertenencia exacta
    a una titulación (ver :data:`Metadatos`). Un código ausente se traduce a
    :data:`CODIGO_AUSENTE`.

    Args:
        chunk: Item ``chunk`` del dataset.

    Returns:
        Metadatos: origen, nombre, grados, codigos, tipo de asignatura y la
        numeración del fragmento dentro de su unidad.
    """
    return {
        "origen": chunk["origen"],
        "nombre": chunk["nombre"],
        "grados": list(chunk["grados"]),
        "codigos": [
            codigo if codigo is not None else CODIGO_AUSENTE
            for codigo in chunk["codigos"]
        ],
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
    almacen: AlmacenVectorial,
    incrustar: Incrustador,
) -> int:
    """Incrusta y almacena todos los chunks, por lotes.

    El identificador de cada chunk es su posición en la lista de entrada:
    como el índice se reconstruye completo en cada ejecución, la posición es
    determinista para un ``chunks.json`` dado y no puede colisionar.

    Args:
        chunks: Items ``chunk`` a indexar.
        almacen: Almacén vacío donde escribir.
        incrustar: Función que convierte una lista de textos en sus vectores.

    Returns:
        Número de chunks indexados.
    """
    for inicio in range(0, len(chunks), TAMANO_LOTE):
        lote = chunks[inicio : inicio + TAMANO_LOTE]
        textos = [chunk["texto"] for chunk in lote]
        almacen.anadir(
            ids=[f"chunk-{inicio + i:04d}" for i in range(len(lote))],
            vectores=list(incrustar(textos)),
            textos=textos,
            metadatos=[metadatos_de_chunk(chunk) for chunk in lote],
        )
    return len(chunks)


def reconstruir_indice(
    ruta_chunks: Path,
    ruta_indice: Path,
    incrustar: Incrustador,
    modelo: str = MODELO,
    crear_almacen: CreadorDeAlmacen = crear_almacen_chroma,
) -> int:
    """Reconstruye desde cero el índice vectorial persistente.

    El índice es un artefacto derivado y regenerable, nunca la fuente de
    verdad (esa es el pipeline ``scrapy`` → ``chunker`` → este módulo), así
    que el almacén anterior se descarta antes de escribir.

    El nombre del modelo y el prefijo de documento quedan grabados en los
    metadatos del índice. No es adorno: dos modelos distintos pueden producir
    vectores de la misma dimensión —384 tanto el actual como el anterior—, así
    que consultar un índice con el modelo equivocado **no da ningún error**,
    solo resultados peores. Grabarlo es lo que permite al recuperador
    comprobarlo en vez de suponerlo.

    Args:
        ruta_chunks: Ruta del ``chunks.json`` de entrada.
        ruta_indice: Carpeta donde persiste el índice.
        incrustar: Función de incrustación a utilizar.
        modelo: Nombre del modelo que se registra en el índice. Debe
            corresponder al que usa ``incrustar``; se pasa aparte porque el
            incrustador es una función y no se le puede preguntar de dónde
            viene, y porque las pruebas inyectan uno falso.
        crear_almacen: Base vectorial donde escribir. Por defecto la de hoy;
            es un parámetro para que IT-31 pueda comparar varias con este
            mismo pipeline.

    Returns:
        Número de chunks indexados.
    """
    chunks = cargar_chunks(ruta_chunks)
    almacen = crear_almacen(
        ruta_indice, {"modelo": modelo, "prefijo_documento": PREFIJO_DOCUMENTO}
    )
    return indexar_chunks(chunks, almacen, incrustar)


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

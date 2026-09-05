"""Pipeline de indexación: de los chunks al índice vectorial (IT-30)."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, Protocol

import lancedb
import pyarrow as pa

from tfg_uja.indexacion.incrustaciones import (
    MODELO,
    PREFIJO_DOCUMENTO,
    Incrustador,
    incrustador_de_documentos,
)
from tfg_uja.invariantes import exigir

#: Nombre de la colección dentro del índice. En LanceDB es el nombre de la
#: tabla; se conserva el término genérico porque nombra al conjunto de
#: fragmentos del dominio, no a la estructura de una base concreta.
COLECCION: Final[str] = "chunks_epsj"

# La distancia se especifica en cada consulta: LanceDB usa l2 por defecto.
CATALOGO: Final[str] = "titulaciones"

DISTANCIA: Final[str] = "cosine"

#: Chunks que se incrustan y almacenan por lote. Limita la memoria usada por
#: el modelo de embeddings sin penalizar apenas el rendimiento.
TAMANO_LOTE: Final[int] = 64

# Representación del código ausente para fragmentos que describen una titulación.
CODIGO_AUSENTE: Final[str] = ""

# Grados y códigos siguen siendo listas paralelas para filtrar por pertenencia exacta.
Metadatos = dict[str, str | int | list[str]]


class AlmacenVectorial(Protocol):
    """Lo único que el pipeline de indexación necesita de una base vectorial."""

    def anadir(
        self,
        ids: list[str],
        vectores: list[Sequence[float]],
        textos: list[str],
        metadatos: list[Metadatos],
    ) -> None:
        """Almacena un lote como filas de la tabla.

        Raises:
            InvarianteRoto: Si las listas difieren en longitud.
        """


#: Función que prepara un almacén vacío donde escribir. Recibe la carpeta de
#: destino y los metadatos que describen con qué se construyó el índice.
CreadorDeAlmacen = Callable[[Path, dict[str, str]], AlmacenVectorial]


def catalogo_de(chunks: list[dict[str, Any]]) -> list[str]:
    """Titulaciones distintas que aparecen en los fragmentos, ordenadas."""
    return sorted({g for c in chunks for g in c.get("grados", []) if g})


def esquema_lance(dimension: int, metadatos_coleccion: dict[str, str]) -> pa.Schema:
    """Compone el esquema Arrow de la tabla de fragmentos."""
    return pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimension)),
            pa.field("texto", pa.string()),
            pa.field("origen", pa.string()),
            pa.field("nombre", pa.string()),
            pa.field("grados", pa.list_(pa.string())),
            pa.field("codigos", pa.list_(pa.string())),
            pa.field("tipo_asignatura", pa.string()),
            # El curso como columna permite filtrar sin depender de la búsqueda textual.
            pa.field("curso", pa.string()),
            pa.field("chunk_index", pa.int64()),
            pa.field("total_chunks", pa.int64()),
        ],
        metadata=metadatos_coleccion,
    )


class AlmacenLance:
    """Adaptador de una tabla de LanceDB a :class:`AlmacenVectorial`."""

    def __init__(self, base: Any, metadatos_coleccion: dict[str, str]) -> None:
        self.base = base
        self.metadatos_coleccion = metadatos_coleccion
        self.tabla: Any | None = None

    def anadir(
        self,
        ids: list[str],
        vectores: list[Sequence[float]],
        textos: list[str],
        metadatos: list[Metadatos],
    ) -> None:
        """Almacena un lote como filas de la tabla.

        Raises:
            InvarianteRoto: Si las listas difieren en longitud.
        """
        exigir(
            len(ids) == len(vectores) == len(textos) == len(metadatos),
            lambda: (
                "el lote no cuadra: "
                f"{len(ids)} identificadores, {len(vectores)} vectores, "
                f"{len(textos)} textos y {len(metadatos)} metadatos"
            ),
        )
        if not ids:
            return
        if self.tabla is None:
            self.tabla = self.base.create_table(
                COLECCION,
                schema=esquema_lance(len(vectores[0]), self.metadatos_coleccion),
                mode="overwrite",
            )
        self.tabla.add(
            [
                {"id": id_, "vector": list(vector), "texto": texto, **metadato}
                for id_, vector, texto, metadato in zip(
                    ids, vectores, textos, metadatos
                )
            ]
        )


def crear_almacen_lance(
    ruta_indice: Path, metadatos_coleccion: dict[str, str]
) -> AlmacenVectorial:
    """Crea un índice persistente de LanceDB vacío, borrando el anterior."""
    # ignore_missing permite crear el índice también en la primera ejecución.
    base: Any = lancedb.connect(str(ruta_indice))
    base.drop_table(COLECCION, ignore_missing=True)
    return AlmacenLance(base, dict(metadatos_coleccion))


def metadatos_de_indice(ruta_indice: Path) -> dict[str, str]:
    """Devuelve los metadatos con los que se construyó un índice."""
    base = lancedb.connect(str(ruta_indice))
    metadatos = base.open_table(COLECCION).schema.metadata or {}
    return {
        clave.decode("utf-8"): valor.decode("utf-8")
        for clave, valor in metadatos.items()
    }


def cargar_chunks(ruta: Path) -> list[dict[str, Any]]:
    """Carga los chunks desde el JSON exportado por el fragmentador."""
    items: list[dict[str, Any]] = json.loads(ruta.read_text(encoding="utf-8"))
    return [item for item in items if item.get("tipo") == "chunk"]


def procedencia_de_indice(ruta: Path) -> dict[str, Any]:
    """Devuelve la procedencia registrada en un ``chunks.json``."""
    items: list[dict[str, Any]] = json.loads(ruta.read_text(encoding="utf-8"))
    return next((i for i in items if i.get("tipo") == "procedencia"), {})


def metadatos_de_chunk(chunk: dict[str, Any]) -> Metadatos:
    """Compone los metadatos con los que viaja un chunk en el índice."""
    return {
        "origen": chunk["origen"],
        "nombre": chunk["nombre"],
        "grados": list(chunk["grados"]),
        "codigos": [
            codigo if codigo is not None else CODIGO_AUSENTE
            for codigo in chunk["codigos"]
        ],
        # El tipo de asignatura permite filtrar, por ejemplo, solo las obligatorias.
        "tipo_asignatura": chunk.get("tipo_asignatura", ""),
        # Vacío cuando la fuente no lo publica (las optativas), no un valor de
        # relleno: la decisión 9 vale también dentro del índice.
        "curso": chunk.get("curso", ""),
        "chunk_index": chunk["chunk_index"],
        "total_chunks": chunk["total_chunks"],
    }


def indexar_chunks(
    chunks: list[dict[str, Any]],
    almacen: AlmacenVectorial,
    incrustar: Incrustador,
) -> int:
    """Incrusta y almacena todos los chunks, por lotes."""
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
    crear_almacen: CreadorDeAlmacen = crear_almacen_lance,
) -> int:
    """Reconstruye desde cero el índice vectorial persistente."""
    chunks = cargar_chunks(ruta_chunks)
    almacen = crear_almacen(
        ruta_indice,
        {
            "modelo": modelo,
            "prefijo_documento": PREFIJO_DOCUMENTO,
            "distancia": DISTANCIA,
            # El catálogo se guarda en el índice para que la consulta use sus mismos
            # nombres.
            CATALOGO: json.dumps(catalogo_de(chunks), ensure_ascii=False),
        },
    )
    return indexar_chunks(chunks, almacen, incrustar)


def main(argumentos: list[str]) -> None:
    """Punto de entrada de línea de comandos."""
    ruta_chunks = Path(argumentos[0])
    ruta_indice = Path(argumentos[1])
    modelo = argumentos[2] if len(argumentos) > 2 else MODELO
    total = reconstruir_indice(
        ruta_chunks, ruta_indice, incrustador_de_documentos(modelo), modelo
    )
    print(f"{total} chunks indexados en {ruta_indice} con el modelo {modelo}")


if __name__ == "__main__":
    main(sys.argv[1:])

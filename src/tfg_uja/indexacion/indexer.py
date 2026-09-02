"""Pipeline de indexación: de los chunks al índice vectorial (IT-30).

Toma los chunks generados por el fragmentador (``chunks.json``), calcula la
incrustación (*embedding*) de cada uno y los almacena, junto con sus
metadatos, en un índice vectorial listo para la fase de recuperación del RAG.

El índice se reconstruye completo en cada ejecución: reindexar es barato
(minutos) frente al coste de mantener actualizaciones incrementales, y
garantiza que el índice refleja exactamente el ``chunks.json`` de entrada,
igual que re-fragmentar garantiza reflejar el dataset (mismo argumento de
reproducibilidad que separa el spider del chunker).

El **modelo de embeddings** lo fija el ADR-0003 (IT-98) y vive en
``incrustaciones.py``, junto con la convención de prefijos que ese modelo
exige. Este módulo no la conoce ni debe conocerla; recibe una función de
incrustación ya construida, que es lo que además permite probarlo sin red.

La **base vectorial es LanceDB**, que fija el ADR-0004 tras comparar tres
candidatas contra una línea base de búsqueda exacta (IT-31). El recorrido
---leer, incrustar por lotes, componer metadatos--- sigue separado de dónde
se guarda: :class:`AlmacenVectorial` describe lo único que el pipeline
necesita de una base y :func:`crear_almacen_lance` es su implementación.
Esa separación no es especulativa: es lo que permitió comparar tres bases
escribiendo tres creadores en vez de tres pipelines, porque medir cada
candidata con una implementación distinta habría comparado el código escrito
para la ocasión y no las bases.

Este módulo **escribe el índice y no lo consulta**. Lo que la recuperación
necesita saber para no equivocarse ---con qué modelo se construyó, con qué
prefijo y con qué métrica de distancia hay que consultarlo--- queda grabado
en los metadatos del propio índice y se lee con :func:`metadatos_de_indice`.
"""

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

#: Métrica de distancia con la que hay que consultar este índice. LanceDB la
#: recibe **en cada consulta**, no al crear la tabla, y su valor por defecto es
#: ``l2``: si el recuperador la omitiera, la base ordenaría por otra métrica sin
#: dar ningún error. Hoy el ranking coincidiría ---el modelo del ADR-0003
#: entrega vectores de norma 1, y para vectores normalizados ordenar por
#: distancia euclídea o por coseno es lo mismo---, pero eso es una propiedad del
#: modelo y no de la base, así que dejarla implícita haría que un cambio de
#: modelo rompiera el ranking en silencio. Se graba en el índice para que la
#: recuperación la lea en vez de suponerla.
#: Clave con la que el índice guarda el catálogo de titulaciones que contiene.
#: Se graba al construirlo para que el recuperador pueda resolver contra él lo
#: que escriba el usuario, en vez de interpolar texto libre en el filtro.
CATALOGO: Final[str] = "titulaciones"

DISTANCIA: Final[str] = "cosine"

#: Chunks que se incrustan y almacenan por lote. Limita la memoria usada por
#: el modelo de embeddings sin penalizar apenas el rendimiento.
TAMANO_LOTE: Final[int] = 64

#: Valor con el que se representa un código de asignatura ausente. Las salidas
#: profesionales y los planes de estudio llegan con ``codigos=[None]`` porque
#: hablan de la titulación entera y no de una asignatura. Se traduce a cadena
#: vacía y no se omite la entrada: el dato ausente se refleja, no se imputa, y
#: la lista de códigos tiene que seguir siendo paralela a la de titulaciones.
#: La base admitiría el nulo tal cual (comprobado con LanceDB 0.37.1), pero
#: entonces la columna mezclaría nulos y cadenas y el filtro por pertenencia
#: trataría de forma distinta a dos fragmentos que representan lo mismo.
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


def catalogo_de(chunks: list[dict[str, Any]]) -> list[str]:
    """Titulaciones distintas que aparecen en los fragmentos, ordenadas.

    Se saca del propio corpus y no de una lista escrita a mano porque una lista
    aparte se queda vieja en silencio: el día que la EPSJ abra una titulación,
    el filtro seguiría sin conocerla y nadie se enteraría.

    Args:
        chunks: Fragmentos que se van a indexar.

    Returns:
        Nombres de titulación, sin repetir y en orden alfabético.
    """
    return sorted({g for c in chunks for g in c.get("grados", []) if g})


def esquema_lance(dimension: int, metadatos_coleccion: dict[str, str]) -> pa.Schema:
    """Compone el esquema Arrow de la tabla de fragmentos.

    El esquema se declara entero en vez de dejar que LanceDB lo infiera del
    primer lote: inferirlo ataría el tipo de cada columna a los valores que
    tuviera ese lote concreto, y basta con que el primero traiga una lista de
    códigos vacía para que la columna nazca con el tipo equivocado.

    El vector va como lista de tamaño **fijo**, que es lo que permite a la base
    tratarlo como un vector y no como una lista cualquiera. ``grados`` y
    ``codigos`` van como listas nativas de cadenas, no serializadas: es lo que
    hace que filtrar por una titulación case por elemento exacto (ver
    :data:`Metadatos`).

    Args:
        dimension: Longitud de los vectores que produce el incrustador.
        metadatos_coleccion: Metadatos que describen con qué se construyó el
            índice; viajan dentro del propio esquema.

    Returns:
        Esquema Arrow de la tabla.
    """
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
            # IT-105: el curso también como columna, no solo dentro del texto.
            # Escrito solo en el texto sirve para que el modelo lo lea, pero no
            # para acotar la búsqueda a un curso, que es una consulta que la
            # similitud vectorial no sabe hacer y un preuniversitario sí hace.
            # Cadena y no entero: en los dobles grados la fuente publica
            # «Tercer o cuarto curso», y meterlo en un entero obligaría a
            # escoger uno de los dos, que es inventarse el dato.
            pa.field("curso", pa.string()),
            pa.field("chunk_index", pa.int64()),
            pa.field("total_chunks", pa.int64()),
        ],
        metadata=metadatos_coleccion,
    )


class AlmacenLance:
    """Adaptador de una tabla de LanceDB a :class:`AlmacenVectorial`.

    La tabla se crea al recibir el primer lote y no al construir el almacén,
    porque su esquema declara el vector como lista de tamaño fijo y ese tamaño
    lo fija el modelo de incrustaciones que se esté usando. El pipeline no lo
    conoce hasta ver el primer vector, y escribirlo como constante sería fijar
    un contrato que nadie compara con el modelo real: bastaría con indexar con
    otro modelo para que el índice declarase una dimensión y contuviera otra.
    """

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

        Args:
            ids: Identificadores del lote.
            vectores: Incrustaciones, una por texto.
            textos: Texto de cada chunk.
            metadatos: Metadatos de cada chunk.

        Raises:
            InvarianteRoto: Si las cuatro listas no miden lo mismo. La
                comprobación no es defensiva: ``zip`` se para en la más corta y
                **descarta el resto sin avisar**, de modo que un incrustador que
                devolviera un vector de menos escribiría una fila de menos
                mientras :func:`indexar_chunks` sigue informando del total de
                entrada. El índice quedaría incompleto y nadie se enteraría.
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
    """Crea un índice persistente de LanceDB vacío, borrando el anterior.

    La tabla anterior se descarta aquí, antes de escribir nada, y no al crear
    la nueva: si el corpus de entrada estuviera vacío no llegaría a haber
    primer lote, y el índice conservaría el contenido de la ejecución anterior
    haciéndolo pasar por recién construido.

    Args:
        ruta_indice: Carpeta donde persiste el índice.
        metadatos_coleccion: Metadatos que describen el índice (modelo,
            prefijo y métrica de distancia).

    Returns:
        Almacén listo para recibir vectores.
    """
    # `ignore_missing` es imprescindible, no defensivo: sin él, borrar una
    # tabla que todavía no existe lanza ValueError y la primera ejecución no
    # llegaría a construir nada. La conexión se anota como Any porque el
    # argumento lo declara la conexión concreta, no el tipo abstracto que la
    # biblioteca expone en la firma de `connect`.
    base: Any = lancedb.connect(str(ruta_indice))
    base.drop_table(COLECCION, ignore_missing=True)
    return AlmacenLance(base, dict(metadatos_coleccion))


def metadatos_de_indice(ruta_indice: Path) -> dict[str, str]:
    """Devuelve los metadatos con los que se construyó un índice.

    Es la contraparte de :func:`crear_almacen_lance`: dice con qué modelo,
    con qué prefijo y con qué métrica de distancia hay que consultar el índice.
    Existe como función y no como acceso directo al esquema porque Arrow
    devuelve esos metadatos **en bytes**, y comparar bytes con una cadena no
    da error: da ``False``. Sin este paso intermedio, comprobar que el índice
    se construyó con el modelo esperado fallaría siempre y en silencio.

    Args:
        ruta_indice: Carpeta donde persiste el índice.

    Returns:
        Metadatos del índice, ya decodificados. Vacío si la tabla no tiene
        ninguno.
    """
    base = lancedb.connect(str(ruta_indice))
    metadatos = base.open_table(COLECCION).schema.metadata or {}
    return {
        clave.decode("utf-8"): valor.decode("utf-8")
        for clave, valor in metadatos.items()
    }


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
    crear_almacen: CreadorDeAlmacen = crear_almacen_lance,
) -> int:
    """Reconstruye desde cero el índice vectorial persistente.

    El índice es un artefacto derivado y regenerable, nunca la fuente de
    verdad (esa es el pipeline ``scrapy`` → ``chunker`` → este módulo), así
    que el almacén anterior se descarta antes de escribir.

    El nombre del modelo, el prefijo de documento y la métrica de distancia
    quedan grabados en los metadatos del índice. No es adorno: dos modelos
    distintos pueden producir vectores de la misma dimensión —384 tanto el
    actual como el anterior—, así que consultar un índice con el modelo
    equivocado **no da ningún error**, solo resultados peores; y la métrica se
    pasa en cada consulta, de modo que omitirla tampoco falla, solo ordena por
    otra cosa. Grabarlas es lo que permite al recuperador comprobarlas en vez
    de suponerlas.

    Args:
        ruta_chunks: Ruta del ``chunks.json`` de entrada.
        ruta_indice: Carpeta donde persiste el índice.
        incrustar: Función de incrustación a utilizar.
        modelo: Nombre del modelo que se registra en el índice. Debe
            corresponder al que usa ``incrustar``; se pasa aparte porque el
            incrustador es una función y no se le puede preguntar de dónde
            viene, y porque las pruebas inyectan uno falso.
        crear_almacen: Base vectorial donde escribir. Por defecto, la que fija
            el ADR-0004; es un parámetro porque es lo que permitió a IT-31
            comparar varias con este mismo pipeline.

    Returns:
        Número de chunks indexados.
    """
    chunks = cargar_chunks(ruta_chunks)
    almacen = crear_almacen(
        ruta_indice,
        {
            "modelo": modelo,
            "prefijo_documento": PREFIJO_DOCUMENTO,
            "distancia": DISTANCIA,
            # El catálogo viaja dentro del índice por el mismo motivo que el
            # modelo y la métrica: quien consulta no tiene por qué saberlo de
            # antemano, y una lista escrita aparte se queda vieja en silencio
            # el día que la EPSJ abra una titulación.
            CATALOGO: json.dumps(catalogo_de(chunks), ensure_ascii=False),
        },
    )
    return indexar_chunks(chunks, almacen, incrustar)


def main(argumentos: list[str]) -> None:
    """Punto de entrada de línea de comandos.

    Uso::

        py -m tfg_uja.indexacion.indexer data/chunks.json data/indice [modelo]

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

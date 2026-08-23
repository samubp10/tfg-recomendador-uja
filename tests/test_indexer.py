"""Pruebas del pipeline de indexación (IT-30).

La fixture ``chunks_muestra_real.json`` contiene chunks REALES copiados del
``chunks.json`` del dataset completo (no inventados), elegidos para cubrir
las anomalías reales de la fuente: una guía compartida entre cuatro
titulaciones (listas paralelas ``grados``/``codigos``), un bloque de salidas
profesionales (``codigos=[None]``) y una asignatura sin guía.

El incrustador es falso e inyectado: determinista y sin red, porque estas
pruebas verifican el pipeline de indexación, no el modelo de embeddings
(cuya elección es objeto del experimento IT-28).

La base es LanceDB (ADR-0004), que **no ofrece cliente en memoria**: persiste
siempre en disco. Las pruebas usan por tanto la carpeta temporal que pytest
crea por prueba, no un directorio compartido, para que ninguna herede el
índice que dejó otra.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
import pytest

from tfg_uja.incrustaciones import MODELO, PREFIJO_DOCUMENTO
from tfg_uja.indexer import (
    COLECCION,
    DISTANCIA,
    AlmacenLance,
    AlmacenVectorial,
    Metadatos,
    cargar_chunks,
    crear_almacen_lance,
    indexar_chunks,
    metadatos_de_chunk,
    main,
    metadatos_de_indice,
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


def filas(almacen: AlmacenLance) -> list[dict[str, Any]]:
    """Devuelve el contenido de la tabla tal como quedó almacenado."""
    return list(almacen.tabla.to_arrow().to_pylist())


def filtrar(almacen: AlmacenLance, expresion: str) -> list[str]:
    """Nombres de los fragmentos que casan con un filtro de metadatos.

    Es un escaneo con filtro, no una búsqueda vectorial: aquí se comprueba que
    el dato quedó almacenado de forma que se pueda filtrar por él, que es un
    invariante de la escritura. La recuperación es cosa de IT-37.
    """
    encontradas = almacen.tabla.search().where(expresion, prefilter=True).to_list()
    return [f["nombre"] for f in encontradas]


@pytest.fixture()
def chunks_reales() -> list[dict[str, Any]]:
    """Chunks reales del dataset, con sus anomalías conocidas."""
    datos: list[dict[str, Any]] = json.loads(RUTA_MUESTRA.read_text(encoding="utf-8"))
    return datos


@pytest.fixture()
def almacen(tmp_path) -> AlmacenLance:
    """El almacén que fija el ADR-0004: una tabla de LanceDB en disco."""
    base = lancedb.connect(str(tmp_path / "indice"))
    return AlmacenLance(base, {"modelo": MODELO, "distancia": DISTANCIA})


def test_indexa_todos_los_chunks(chunks_reales, almacen):
    """El nº de vectores indexados coincide con el nº de chunks (DoD IT-30)."""
    total = indexar_chunks(chunks_reales, almacen, incrustador_falso)
    assert total == len(chunks_reales)
    assert almacen.tabla.count_rows() == len(chunks_reales)


def test_metadatos_sin_perdida(chunks_reales, almacen):
    """Grados, códigos, nombre y numeración sobreviven al viaje de ida y vuelta."""
    indexar_chunks(chunks_reales, almacen, incrustador_falso)
    guardado = next(f for f in filas(almacen) if f["id"] == "chunk-0000")
    original = chunks_reales[0]
    assert guardado["nombre"] == original["nombre"]
    assert guardado["origen"] == original["origen"]
    assert list(guardado["grados"]) == original["grados"]
    assert guardado["chunk_index"] == original["chunk_index"]
    assert guardado["total_chunks"] == original["total_chunks"]
    assert guardado["texto"] == original["texto"]


def test_el_esquema_declara_el_vector_y_las_listas(chunks_reales, almacen):
    """El esquema no se infiere del primer lote: se declara entero.

    El vector va como lista de tamaño fijo ---es lo que permite a la base
    tratarlo como vector--- y las dos listas paralelas como listas nativas de
    cadenas. Si alguna de las tres se almacenara como otra cosa, nada fallaría
    al indexar: el defecto aparecería al recuperar.
    """
    indexar_chunks(chunks_reales, almacen, incrustador_falso)
    esquema = almacen.tabla.schema
    # Los tipos esperados se escriben aquí en vez de pedírselos a
    # `esquema_lance`: comparar el esquema con el que produce la propia
    # función que se está probando daría verde con cualquier tipo.
    assert esquema.field("vector").type == pa.list_(pa.float32(), DIMENSION)
    assert esquema.field("grados").type == pa.list_(pa.string())
    assert esquema.field("codigos").type == pa.list_(pa.string())


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


def test_un_codigo_ausente_no_impide_almacenar(chunks_reales, almacen):
    """Regresión: 55 fragmentos del corpus llegan con ``codigos=[None]``.

    Son las salidas profesionales y los planes de estudio, que hablan de la
    titulación entera y no de una asignatura. La base admitiría el nulo tal
    cual, así que aquí no se comprueba que no reviente, sino que el ausente
    llega almacenado como el mismo valor explícito para todos: una columna que
    mezclara nulos y cadenas trataría distinto a dos fragmentos que
    representan lo mismo.
    """
    salidas = [c for c in chunks_reales if c["origen"] == "salidas"]
    assert salidas, "la fixture debe incluir un bloque de salidas"
    indexar_chunks(salidas, almacen, incrustador_falso)
    assert almacen.tabla.count_rows() == len(salidas)
    assert all(fila["codigos"] == [""] for fila in filas(almacen))


# --- IT-31: filtrar por una titulación no puede arrastrar al doble grado ---


def test_filtrar_por_una_titulacion_no_arrastra_el_doble_grado(almacen):
    """El caso real que decide guardar listas en vez de una cadena unida.

    Cuatro nombres de titulación del corpus son subcadena de otro: «Grado en
    Ingeniería Eléctrica» lo es de «Doble Grado en Ingeniería Eléctrica y
    Mecánica». Con las listas serializadas en una cadena, filtrar por el grado
    simple devolvía también los fragmentos que solo pertenecen al doble.
    Guardándolas como listas, ``array_has_any`` casa por elemento exacto.
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
    indexar_chunks(chunks, almacen, incrustador_falso)

    nombres = set(filtrar(almacen, f"array_has_any(grados, ['{simple}'])"))
    assert nombres == {"Compartida"}, "el del doble grado es un falso positivo"


def test_filtrar_por_titulacion_y_tipo_a_la_vez(almacen):
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
    indexar_chunks(chunks, almacen, incrustador_falso)

    encontrados = filtrar(
        almacen,
        f"array_has_any(grados, ['{grado}']) AND tipo_asignatura = 'OB'",
    )
    assert encontrados == ["Obligatoria"]


# --- IT-31: el pipeline no depende de una base concreta ---


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
    assert recibidos["distancia"] == DISTANCIA


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
    tabla = lancedb.connect(str(ruta_indice)).open_table(COLECCION)
    assert tabla.count_rows() == len(chunks_reales)


def test_el_creador_descarta_el_indice_anterior(tmp_path, chunks_reales):
    """El creador borra el índice previo aunque después no se escriba nada.

    La tabla se crea al llegar el primer lote, porque su esquema necesita la
    dimensión del vector. Si el borrado del índice anterior viajara con esa
    creación, reconstruir a partir de un corpus vacío dejaría en pie el índice
    de la ejecución anterior y lo haría pasar por recién construido.
    """
    ruta = tmp_path / "indice"
    indexar_chunks(
        chunks_reales, crear_almacen_lance(ruta, {"modelo": MODELO}), incrustador_falso
    )
    assert lancedb.connect(str(ruta)).open_table(COLECCION).count_rows() == len(
        chunks_reales
    )

    crear_almacen_lance(ruta, {"modelo": MODELO})
    assert COLECCION not in lancedb.connect(str(ruta)).list_tables()


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

    metadatos = metadatos_de_indice(ruta_indice)
    assert metadatos["modelo"] == MODELO
    assert metadatos["prefijo_documento"] == PREFIJO_DOCUMENTO


# --- IT-103: el índice dice también con qué distancia hay que consultarlo ---


def test_el_indice_registra_la_distancia(tmp_path, chunks_reales):
    # La métrica no se declara al crear la tabla, sino en cada consulta, y por
    # defecto es `l2`. Una consulta que la omita no falla: ordena por otra cosa.
    # Con los vectores normalizados del ADR-0003 el orden coincide, así que el
    # defecto sería invisible hasta que se cambiara de modelo. Grabarla en el
    # índice es lo que permitirá al recuperador (IT-37) declararla sin suponer.
    ruta_chunks = tmp_path / "chunks.json"
    ruta_chunks.write_text(
        json.dumps(chunks_reales, ensure_ascii=False), encoding="utf-8"
    )
    ruta_indice = tmp_path / "indice"
    reconstruir_indice(ruta_chunks, ruta_indice, incrustador_falso, MODELO)

    assert metadatos_de_indice(ruta_indice)["distancia"] == DISTANCIA


def test_los_metadatos_del_indice_vuelven_como_texto(tmp_path, chunks_reales):
    # Arrow los devuelve en bytes. Comparar b"..." con "..." no da error: da
    # False, así que cualquier comprobación del modelo pasaría a fallar en
    # silencio. Por eso se leen con `metadatos_de_indice` y no a mano.
    ruta_chunks = tmp_path / "chunks.json"
    ruta_chunks.write_text(
        json.dumps(chunks_reales, ensure_ascii=False), encoding="utf-8"
    )
    ruta_indice = tmp_path / "indice"
    reconstruir_indice(ruta_chunks, ruta_indice, incrustador_falso, MODELO)

    metadatos = metadatos_de_indice(ruta_indice)
    assert all(
        isinstance(clave, str) and isinstance(valor, str)
        for clave, valor in metadatos.items()
    )


# --- Los dos extremos del indexador ---


def test_un_lote_vacio_no_llega_a_crear_la_tabla(almacen):
    """Un lote sin nada no debe dejar rastro, ni siquiera una tabla vacía.

    La guarda existe porque el esquema de la tabla se deduce de la dimensión del
    primer vector del lote: sin ella, un lote vacío reventaría al mirar
    ``vectores[0]``, y lo haría durante la reconstrucción del índice y no en una
    prueba. El caso llega solo cuando el troceado deja una tanda sin fragmentos.
    """
    almacen.anadir([], [], [], [])

    assert almacen.tabla is None


def test_main_reconstruye_el_indice_y_dice_cuantos(tmp_path, chunks_reales, capsys):
    """El punto de entrada de consola indexa y cuenta lo que ha indexado.

    Es la orden que documenta el README y la que hay que ejecutar tras cada
    troceado, así que conviene que esté probada y no solo escrita.
    """
    ruta_chunks = tmp_path / "chunks.json"
    ruta_chunks.write_text(
        json.dumps(chunks_reales, ensure_ascii=False), encoding="utf-8"
    )
    ruta_indice = tmp_path / "indice"

    def incrustador_falso(textos: list[str]) -> list[list[float]]:
        return [[float(len(t) % 97)] + [0.0] * 7 for t in textos]

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "tfg_uja.indexer.incrustador_de_documentos", lambda modelo: incrustador_falso
    )
    try:
        main([str(ruta_chunks), str(ruta_indice)])
    finally:
        monkeypatch.undo()

    salida = capsys.readouterr().out
    assert f"chunks indexados en {ruta_indice}" in salida
    assert MODELO in salida

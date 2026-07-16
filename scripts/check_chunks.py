"""Verificación del dataset de chunks (IT-10).

Recorre ``data/chunks.json`` (salida de ``tfg_uja.chunker``) y comprueba los
invariantes del troceo, además de reportar las estadísticas que permiten
detectar regresiones cada vez que se regenera el dataset. Debe ejecutarse
tras cada regeneración::

    py -m tfg_uja.chunker data/grados.json data/chunks.json
    py scripts/check_chunks.py

Acepta rutas alternativas como argumentos::

    py scripts/check_chunks.py otra/ruta/chunks.json otra/ruta/grados.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

#: Deben coincidir con ``tfg_uja.chunker``; se duplican aquí para que el
#: script no dependa del paquete instalado (se ejecuta también en CI).
TAMANO_MAXIMO = 1500
TAMANO_MINIMO = 200


def _clave_item(item: dict) -> tuple:
    """Identifica la unidad de un item del dataset (grado y código singulares).

    El código no basta como identificador: las asignaturas de las
    titulaciones en implantación aún no tienen código publicado (cadena
    vacía) y agrupar solo por código las colapsaría. Cuando falta el código
    se usa el nombre.

    Args:
        item: Item del dataset (``asignatura``, ``guia`` o ``salidas``).

    Returns:
        Tupla ``(grado, codigo_o_nombre)`` que identifica la unidad.
    """
    return (item["grado"], item.get("codigo") or item.get("nombre"))


def _claves_chunk(chunk: dict) -> set[tuple]:
    """Expande un chunk a las unidades (grado, código) que representa.

    Tras la deduplicación, un chunk de guía puede pertenecer a varias
    titulaciones: su clave se expande a un par por cada titulación, para
    poder cotejarlo con los items individuales del dataset.

    Args:
        chunk: Chunk con ``grados`` y ``codigos`` como listas paralelas.

    Returns:
        Conjunto de pares ``(grado, codigo_o_nombre)``.
    """
    return {
        (grado, codigo or chunk["nombre"])
        for grado, codigo in zip(chunk["grados"], chunk["codigos"])
    }


def main(argv: list[str] | None = None) -> int:
    """Ejecuta las comprobaciones y reporta las estadísticas del troceo.

    Args:
        argv: Rutas del fichero de chunks y del dataset; por defecto,
            ``data/chunks.json`` y ``data/grados.json``.

    Returns:
        Código de salida (0 si todos los invariantes se cumplen).
    """
    argumentos = argv if argv is not None else sys.argv[1:]
    datos = Path(__file__).resolve().parent.parent / "data"
    ruta_chunks = Path(argumentos[0]) if len(argumentos) > 0 else datos / "chunks.json"
    ruta_dataset = Path(argumentos[1]) if len(argumentos) > 1 else datos / "grados.json"

    chunks = json.loads(ruta_chunks.read_text(encoding="utf-8"))
    dataset = json.loads(ruta_dataset.read_text(encoding="utf-8"))
    asignaturas = [d for d in dataset if d["tipo"] == "asignatura"]
    guias = [d for d in dataset if d["tipo"] == "guia"]
    salidas = [d for d in dataset if d["tipo"] == "salidas"]

    # --- Invariantes de forma ---
    assert chunks, "no hay chunks"
    assert all(c["texto"].strip() for c in chunks), "hay chunks vacíos"
    assert all(
        len(c["texto"]) <= TAMANO_MAXIMO for c in chunks
    ), "hay chunks por encima del máximo (encabezado incluido)"
    assert all(
        isinstance(c["grados"], list)
        and isinstance(c["codigos"], list)
        and len(c["grados"]) == len(c["codigos"])
        and c["grados"]
        for c in chunks
    ), "grados/codigos deben ser listas paralelas no vacías"

    # --- Numeración consistente dentro de cada unidad ---
    por_unidad: dict[tuple, list] = {}
    for c in chunks:
        clave = (c["nombre"], tuple(c["grados"]), c["origen"])
        por_unidad.setdefault(clave, []).append(c)
    for unidad, lista in por_unidad.items():
        lista.sort(key=lambda c: c["chunk_index"])
        indices = [c["chunk_index"] for c in lista]
        assert indices == list(range(len(lista))), f"índices rotos en {unidad}"
        assert all(
            c["total_chunks"] == len(lista) for c in lista
        ), f"total_chunks inconsistente en {unidad}"
        if len(lista) > 1:
            assert all(
                len(c["texto"]) >= TAMANO_MINIMO for c in lista
            ), f"chunk bajo el mínimo tras la fusión en {unidad}"

    # --- Cobertura: cada item del dataset queda representado ---
    # Se expanden los chunks a pares (grado, código) por la deduplicación.
    con_guia = {_clave_item(g) for g in guias}
    unidades_guia = set()
    for c in chunks:
        if c["origen"] == "guia":
            unidades_guia |= _claves_chunk(c)
    assert con_guia == unidades_guia, (
        "descuadre guía<->chunk: "
        f"faltan {len(con_guia - unidades_guia)}, "
        f"sobran {len(unidades_guia - con_guia)}"
    )

    sin_guia = {_clave_item(a) for a in asignaturas if not a["tiene_guia"]}
    informativos = set()
    for c in chunks:
        if c["origen"] == "asignatura_sin_guia":
            informativos |= _claves_chunk(c)
    assert sin_guia == informativos, "asignaturas sin guía sin chunk informativo"

    grados_salidas = {s["grado"] for s in salidas}
    grados_chunk_salidas = {
        g for c in chunks if c["origen"] == "salidas" for g in c["grados"]
    }
    assert grados_salidas == grados_chunk_salidas, "salidas sin trocear"

    # --- Estadísticas ---
    origenes = Counter(c["origen"] for c in chunks)
    compartidas = sum(
        1 for c in chunks if len(c["grados"]) > 1 and c["chunk_index"] == 0
    )
    print(f"Chunks totales: {len(chunks)}  {dict(origenes)}")
    print(
        f"Unidades: {len(por_unidad)} (guías {len(con_guia)}, "
        f"sin guía {len(sin_guia)}, salidas {len(grados_salidas)})"
    )
    print(f"Unidades de guía compartidas entre titulaciones: {compartidas}")

    tamanos = sorted(len(c["texto"]) for c in chunks)
    n = len(tamanos)
    print(
        f"Tamaño (chars): min={tamanos[0]} mediana={tamanos[n // 2]} "
        f"p90={tamanos[int(n * 0.9)]} max={tamanos[-1]}"
    )

    print("Chunks OK: invariantes verificados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

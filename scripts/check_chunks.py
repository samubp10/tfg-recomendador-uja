"""Verificación del dataset de chunks (IT-10).

Recorre ``data/chunks.json`` (salida de ``tfg_uja.chunker``) y comprueba
los invariantes del troceo, además de reportar las estadísticas que
permiten detectar regresiones cada vez que se regenera el dataset. Debe
ejecutarse tras cada regeneración::

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


def _clave_unidad(item: dict) -> tuple:
    """Identifica la unidad semántica de un chunk o item.

    El código no basta como identificador: las asignaturas de los grados en
    implantación aún no tienen código publicado (cadena vacía), y agrupar
    por código colapsaría asignaturas distintas en una sola unidad. Cuando
    falta el código se usa el nombre.

    Args:
        item: Chunk o item del dataset, con ``grado``, ``codigo`` y
            ``nombre``.

    Returns:
        Tupla que identifica la unidad de forma única.
    """
    return (item["grado"], item.get("codigo") or item.get("nombre"))


def main(argv: list[str] | None = None) -> int:
    """Ejecuta las comprobaciones y reporta las estadísticas del troceo.

    Args:
        argv: Rutas del fichero de chunks y del dataset; por defecto,
            ``chunks.json`` y ``grados.json`` junto a este script.

    Returns:
        Código de salida (0 si todos los invariantes se cumplen).
    """
    argumentos = argv if argv is not None else sys.argv[1:]
    # El script vive en scripts/; los datos, en data/ junto a la raíz del repo.
    datos = Path(__file__).resolve().parent.parent / "data"
    ruta_chunks = Path(argumentos[0]) if len(argumentos) > 0 else datos / "chunks.json"
    ruta_dataset = Path(argumentos[1]) if len(argumentos) > 1 else datos / "grados.json"

    chunks = json.loads(ruta_chunks.read_text(encoding="utf-8"))
    dataset = json.loads(ruta_dataset.read_text(encoding="utf-8"))
    asignaturas = [d for d in dataset if d["tipo"] == "asignatura"]
    guias = [d for d in dataset if d["tipo"] == "guia"]
    salidas = [d for d in dataset if d["tipo"] == "salidas"]

    # --- Invariantes ---
    assert chunks, "no hay chunks"
    assert all(c["texto"].strip() for c in chunks), "hay chunks vacíos"
    assert all(
        len(c["texto"]) <= TAMANO_MAXIMO for c in chunks
    ), "hay chunks por encima del máximo (encabezado incluido)"

    # Numeración consistente dentro de cada unidad (clave por código o, si
    # falta, por nombre: ver _clave_unidad).
    por_unidad: dict[tuple, list] = {}
    for c in chunks:
        por_unidad.setdefault((*_clave_unidad(c), c["origen"]), []).append(c)
    for unidad, lista in por_unidad.items():
        lista.sort(key=lambda c: c["chunk_index"])
        indices = [c["chunk_index"] for c in lista]
        assert indices == list(range(len(lista))), f"índices rotos en {unidad}"
        assert all(
            c["total_chunks"] == len(lista) for c in lista
        ), f"total_chunks inconsistente en {unidad}"
        # El mínimo solo aplica a unidades multi-chunk: una unidad cuyo
        # contenido completo es corto produce un único chunk legítimo.
        if len(lista) > 1:
            assert all(
                len(c["texto"]) >= TAMANO_MINIMO for c in lista
            ), f"chunk bajo el mínimo tras la fusión en {unidad}"

    # Cobertura: toda guía y todo bloque de salidas produce chunks; toda
    # asignatura sin guía tiene su chunk informativo.
    con_guia = {_clave_unidad(g) for g in guias}
    unidades_guia = {
        _clave_unidad(c) for c in chunks if c["origen"] == "guia"
    }
    assert con_guia == unidades_guia, "hay guías sin chunks o chunks huérfanos"

    sin_guia = {
        _clave_unidad(a) for a in asignaturas if not a["tiene_guia"]
    }
    informativos = {
        _clave_unidad(c)
        for c in chunks
        if c["origen"] == "asignatura_sin_guia"
    }
    assert sin_guia == informativos, "asignaturas sin guía sin chunk informativo"

    grados_salidas = {s["grado"] for s in salidas}
    grados_chunk_salidas = {
        c["grado"] for c in chunks if c["origen"] == "salidas"
    }
    assert grados_salidas == grados_chunk_salidas, "salidas sin trocear"

    # --- Estadísticas ---
    origenes = Counter(c["origen"] for c in chunks)
    print(f"Chunks totales: {len(chunks)}  {dict(origenes)}")
    print(f"Unidades: {len(por_unidad)} (guías {len(con_guia)}, "
          f"sin guía {len(sin_guia)}, salidas {len(grados_salidas)})")

    tamanos = sorted(len(c["texto"]) for c in chunks)
    n = len(tamanos)
    print(f"Tamaño (chars): min={tamanos[0]} mediana={tamanos[n // 2]} "
          f"p90={tamanos[int(n * 0.9)]} max={tamanos[-1]}")

    print("Sin guía por grado:")
    sin_por_grado = Counter(a["grado"] for a in asignaturas if not a["tiene_guia"])
    for grado, cuantas in sorted(sin_por_grado.items()):
        print(f"  {cuantas:3}  {grado}")

    print("Chunks OK: invariantes verificados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

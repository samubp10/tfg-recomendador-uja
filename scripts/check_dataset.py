"""Verificación del dataset extraído por el spider (IT-10).

Comprueba los invariantes de ``data/grados.json`` tras cada regeneración::

    scrapy runspider src/tfg_uja/grados_spider.py -O data/grados.json
    py scripts/check_dataset.py

Acepta una ruta alternativa como argumento.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Ejecuta las comprobaciones del dataset del spider.

    Args:
        argv: Ruta del dataset; por defecto ``data/grados.json`` en la raíz
            del repositorio (el script vive en ``scripts/``).

    Returns:
        Código de salida (0 si todos los invariantes se cumplen).
    """
    argumentos = argv if argv is not None else sys.argv[1:]
    por_defecto = Path(__file__).resolve().parent.parent / "data" / "grados.json"
    ruta = Path(argumentos[0]) if argumentos else por_defecto

    datos = json.loads(ruta.read_text(encoding="utf-8"))
    asignaturas = [d for d in datos if d["tipo"] == "asignatura"]
    grados = [d for d in datos if d["tipo"] == "grado"]
    guias = [d for d in datos if d["tipo"] == "guia"]
    salidas = [d for d in datos if d["tipo"] == "salidas"]

    assert len(asignaturas) == 361, f"asignaturas: {len(asignaturas)} (esperado 361)"
    assert len(grados) == 13, f"grados: {len(grados)} (esperado 13)"
    assert len(guias) == 296, f"guias: {len(guias)} (esperado 296)"
    # Los dobles grados no emiten salidas (decisión de IT-07): 8, no 9.
    assert len(salidas) == 8, f"salidas: {len(salidas)} (esperado 8)"
    assert all("ofertada" in a for a in asignaturas), "falta el campo ofertada"
    no_ofertadas = sum(1 for a in asignaturas if not a["ofertada"])
    assert no_ofertadas == 9, f"no ofertadas: {no_ofertadas} (esperado 9)"
    assert not [a for a in asignaturas if "(" in a["nombre"]], "nombres sucios"
    assert not [
        a for a in asignaturas if any("/" in m for m in a["menciones"])
    ], "menciones con barra sin separar"
    sin_ects = [a for a in asignaturas if not a["ects"]]
    assert (
        len(sin_ects) == 1
    ), f"sin ECTS: {len(sin_ects)} (esperado 1, fiel a la fuente)"

    print(
        f"Dataset OK: {len(asignaturas)} asignaturas, {len(guias)} guías, "
        f"{len(salidas)} salidas, {no_ofertadas} no ofertadas, "
        f"{len(sin_ects)} sin ECTS (fiel a la fuente)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

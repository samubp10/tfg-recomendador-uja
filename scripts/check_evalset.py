"""Verificador del conjunto de evaluación (IT-27) contra el dataset real.

Comprueba que cada selector de unidad anotado en
``eval/preguntas_evaluacion.json`` resuelve a al menos un chunk del
``data/chunks.json`` real, e imprime la cobertura por tipo de pregunta y por
grado. Igual que los demás verificadores, se ejecuta SOLO en local (data/ no
está versionado y no existe en un checkout limpio de CI):

    py scripts/check_evalset.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Las rutas se resuelven relativas a la raíz del repositorio, no a scripts/.
RAIZ = Path(__file__).resolve().parent.parent
RUTA_EVAL = RAIZ / "eval" / "preguntas_evaluacion.json"
RUTA_CHUNKS = RAIZ / "data" / "chunks.json"


def chunks_de_unidad(
    selector: dict[str, str], chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Devuelve los chunks que pertenecen a la unidad que describe el selector.

    Args:
        selector: Unidad anotada: ``origen``, ``nombre`` y, opcionalmente,
            ``grado`` para desambiguar.
        chunks: Chunks del dataset completo.

    Returns:
        Chunks cuya unidad coincide con el selector.
    """
    return [
        chunk
        for chunk in chunks
        if chunk["origen"] == selector["origen"]
        and chunk["nombre"] == selector["nombre"]
        and ("grado" not in selector or selector["grado"] in chunk["grados"])
    ]


def main() -> int:
    """Valida el conjunto de evaluación y muestra sus estadísticas.

    Returns:
        0 si todas las comprobaciones pasan; 1 en caso contrario.
    """
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    evalset = json.loads(RUTA_EVAL.read_text(encoding="utf-8"))
    items = json.loads(RUTA_CHUNKS.read_text(encoding="utf-8"))
    # El item de procedencia (IT-90) no es contenido recuperable: se separa
    # por tipo, nunca por posición.
    chunks = [i for i in items if i.get("tipo") == "chunk"]
    procedencia = next((i for i in items if i.get("tipo") == "procedencia"), {})
    if procedencia.get("fecha_extraccion"):
        cursos = ", ".join(procedencia.get("cursos") or []) or "sin determinar"
        print(
            f"Procedencia del corpus: extraccion "
            f"{procedencia['fecha_extraccion']} | curso(s) {cursos}"
        )
    else:
        print("Procedencia del corpus: sin determinar (dataset anterior a IT-90).")
    preguntas = evalset["preguntas"]
    errores: list[str] = []

    if len(preguntas) < 30:
        errores.append(f"solo hay {len(preguntas)} preguntas (mínimo 30)")

    ids = [p["id"] for p in preguntas]
    if len(ids) != len(set(ids)):
        errores.append("hay ids de pregunta duplicados")

    grados_cubiertos: set[str] = set()
    for pregunta in preguntas:
        for selector in pregunta["relevantes"]:
            encontrados = chunks_de_unidad(selector, chunks)
            if not encontrados:
                errores.append(
                    f"{pregunta['id']}: el selector {selector} no resuelve "
                    "a ningún chunk del dataset"
                )
                continue
            for chunk in encontrados:
                grados_cubiertos.update(chunk["grados"])

    grados_dataset = {g for c in chunks for g in c["grados"]}
    por_tipo: dict[str, int] = {}
    for pregunta in preguntas:
        por_tipo[pregunta["tipo"]] = por_tipo.get(pregunta["tipo"], 0) + 1

    print(f"Preguntas: {len(preguntas)}")
    print(f"Por tipo: {por_tipo}")
    print(f"Grados cubiertos: {len(grados_cubiertos)}/{len(grados_dataset)}")
    for grado in sorted(grados_dataset - grados_cubiertos):
        print(f"  SIN CUBRIR: {grado}")

    if errores:
        print("\nERRORES:")
        for error in errores:
            print(f"  - {error}")
        return 1
    print("\nTodo correcto: todos los selectores resuelven contra el dataset.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

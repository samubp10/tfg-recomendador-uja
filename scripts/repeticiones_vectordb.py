"""Reproducibilidad de la comparativa de bases vectoriales (IT-31, umbral U6).

Ejecuta el procedimiento completo de ``experimento_vectordb.py`` N veces y
cuenta en cuántas falla cada candidata. Existe porque una sola pasada **no
puede** comprobar U6 («los resultados se repiten a tres decimales»), y porque
una fidelidad que unas veces sale 1,000 y otras no es justo lo que un umbral
fijado en el 1,000 exacto está puesto para detectar.

Requiere lo mismo que el experimento: la dependencia ``[comparativa-vectordb]``
y el contenedor de Qdrant levantado. Se ejecuta SOLO en local, y **desde el
entorno virtual del proyecto**::

    source .venv/Scripts/activate      # Git Bash
    .venv\\Scripts\\activate.bat         # cmd.exe
    python scripts/repeticiones_vectordb.py [N]
"""

from __future__ import annotations

import importlib.util
import statistics
import sys
from pathlib import Path
from typing import Any, Final

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

# El guion del experimento se carga por su ruta, igual que hacen las pruebas
# del proyecto con los verificadores de `scripts/`: esa carpeta no es un
# paquete importable, y un `import` normal solo funcionaría por un `sys.path`
# manipulado en tiempo de ejecución, que ningún analizador estático puede
# seguir. Se registra en `sys.modules` antes de ejecutarlo porque el módulo
# define un `@dataclass`, y `dataclasses` resuelve las anotaciones buscando el
# módulo por su nombre.
_RUTA_EXPERIMENTO = RAIZ / "scripts" / "experimento_vectordb.py"
_spec = importlib.util.spec_from_file_location(
    "experimento_vectordb", _RUTA_EXPERIMENTO
)
assert _spec is not None and _spec.loader is not None
exp = importlib.util.module_from_spec(_spec)
sys.modules["experimento_vectordb"] = exp
_spec.loader.exec_module(exp)

#: Ciclos por defecto. Con 20, un fallo que ocurra una de cada cinco veces
#: aparece varias veces y deja de poder atribuirse al azar de una ejecución.
CICLOS: Final[int] = 20


def resumir(nombre: str, fidelidades: list[float], latencias: list[float]) -> None:
    """Imprime el resumen de una candidata sobre todos los ciclos.

    Args:
        nombre: Nombre de la candidata.
        fidelidades: Fidelidad obtenida en cada ciclo.
        latencias: Latencia mediana de cada ciclo, en milisegundos.
    """
    fallos = sum(1 for f in fidelidades if f < 1.0)
    distintos = sorted({f"{f:.4f}" for f in fidelidades})
    print(f"\n{nombre}")
    print(
        f"  U1 fidelidad : min={min(fidelidades):.4f} max={max(fidelidades):.4f} "
        f"valores distintos={distintos}"
    )
    print(
        f"  U1 FALLA en  : {fallos} de {len(fidelidades)} ciclos "
        f"({fallos / len(fidelidades) * 100:.0f} %)"
    )
    print(
        f"  U3 latencia  : min={min(latencias):.2f} "
        f"mediana={statistics.median(latencias):.2f} max={max(latencias):.2f} ms"
    )


def main(argumentos: list[str]) -> None:
    """Ejecuta N ciclos completos y resume la reproducibilidad.

    Args:
        argumentos: Opcionalmente, el número de ciclos (por defecto
            :data:`CICLOS`).
    """
    ciclos = int(argumentos[0]) if argumentos else CICLOS

    chunks = exp.cargar_corpus()
    preguntas = exp.cargar_preguntas()
    print(f"corpus {len(chunks)} · preguntas {len(preguntas)} · {ciclos} ciclos")

    from tfg_uja.incrustaciones import (
        incrustador_de_consultas,
        incrustador_de_documentos,
    )

    print("Incrustando una sola vez...")
    vectores = np.asarray(
        incrustador_de_documentos()([c["texto"] for c in chunks]), dtype=np.float32
    )
    consultas = np.asarray(incrustador_de_consultas()(preguntas), dtype=np.float32)

    _, exactos = exp.medir_numpy(vectores, consultas)

    registro: dict[str, dict[str, list[Any]]] = {
        nombre: {"fidelidad": [], "latencia": []}
        for nombre in ("ChromaDB", "LanceDB", "Qdrant")
    }

    for ciclo in range(1, ciclos + 1):
        with exp.carpeta_temporal() as tmp:
            m = exp.medir_chroma(chunks, vectores, consultas, exactos, tmp / "idx")
        registro["ChromaDB"]["fidelidad"].append(m.fidelidad)
        registro["ChromaDB"]["latencia"].append(m.latencia_mediana_ms)
        fid_chroma = m.fidelidad

        with exp.carpeta_temporal() as tmp:
            m = exp.medir_lancedb(chunks, vectores, consultas, exactos, tmp / "idx")
        registro["LanceDB"]["fidelidad"].append(m.fidelidad)
        registro["LanceDB"]["latencia"].append(m.latencia_mediana_ms)
        fid_lance = m.fidelidad

        m = exp.medir_qdrant(chunks, vectores, consultas, exactos)
        registro["Qdrant"]["fidelidad"].append(m.fidelidad)
        registro["Qdrant"]["latencia"].append(m.latencia_mediana_ms)

        print(
            f"  ciclo {ciclo:2d}/{ciclos}: chroma={fid_chroma:.4f} "
            f"lance={fid_lance:.4f} qdrant={m.fidelidad:.4f}"
        )

    print(f"\n{'=' * 70}\nRESUMEN DE {ciclos} CICLOS\n{'=' * 70}")
    for nombre, datos in registro.items():
        resumir(nombre, datos["fidelidad"], datos["latencia"])


if __name__ == "__main__":
    main(sys.argv[1:])

"""Experimento comparativo de modelos de embeddings (IT-28).

Descarga (o reutiliza de caché) cada modelo candidato, incrusta el
``data/chunks.json`` real y el conjunto de evaluación de IT-27
(``eval/preguntas_evaluacion.json``), y calcula Recall@3, Recall@5 y MRR
sobre las 36 preguntas anotadas. Imprime una tabla de resultados y la deja
también en ``docs/experimentos/it28-embeddings.md`` para no perder el
resultado real de la ejecución.

Necesita la dependencia opcional ``[index]`` (arrastra PyTorch) y red para
descargar los modelos la primera vez; por eso, igual que el resto de
verificadores del proyecto, se ejecuta SOLO en local y no en CI:

    py scripts/experimento_embeddings.py
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
RUTA_CHUNKS = RAIZ / "data" / "chunks.json"
RUTA_EVAL = RAIZ / "eval" / "preguntas_evaluacion.json"
RUTA_RESULTADOS = RAIZ / "docs" / "experimentos" / "it28-embeddings.md"

KS = (3, 5)


@dataclass(frozen=True)
class ModeloCandidato:
    """Un modelo a comparar y cómo se le debe pedir que incruste texto."""

    nombre: str
    descripcion: str
    prefijo_consulta: str = ""
    prefijo_documento: str = ""


#: Selección de modelos (DoD IT-28: mínimo 3, multilingües o específicos de
#: español, ninguno monolingüe-inglés). Los 3 multilingües representan
#: puntos distintos del espacio tamaño/arquitectura; el cuarto es la única
#: alternativa específica de español disponible en sentence-transformers con
#: cobertura y mantenimiento razonables en el momento de este experimento.
CANDIDATOS = [
    ModeloCandidato(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "Modelo provisional actual del indexador (IT-30): línea base.",
    ),
    ModeloCandidato(
        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "Misma familia que la línea base, mayor tamaño (mpnet-base vs MiniLM-L12).",
    ),
    ModeloCandidato(
        "intfloat/multilingual-e5-small",
        "Modelo orientado a recuperación; exige prefijos 'query:'/'passage:' "
        "según su model card, aplicados aquí.",
        prefijo_consulta="query: ",
        prefijo_documento="passage: ",
    ),
    ModeloCandidato(
        "hiiamsid/sentence_similarity_spanish_es",
        "Específico de español (no multilingüe): contraste frente a los "
        "tres anteriores.",
    ),
]


def cargar_datos() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Carga los chunks reales y las preguntas del conjunto de evaluación.

    Returns:
        Tupla ``(chunks, preguntas)``.
    """
    chunks = json.loads(RUTA_CHUNKS.read_text(encoding="utf-8"))
    preguntas = json.loads(RUTA_EVAL.read_text(encoding="utf-8"))["preguntas"]
    return chunks, preguntas


def crear_incrustadores(candidato: ModeloCandidato):
    """Construye las funciones de incrustación (documento y consulta) del modelo.

    Args:
        candidato: Modelo a cargar.

    Returns:
        Tupla ``(incrustar_chunks, incrustar_preguntas)``.
    """
    from sentence_transformers import SentenceTransformer

    modelo = SentenceTransformer(candidato.nombre)

    def incrustar_documentos(textos: list[str]) -> list[list[float]]:
        con_prefijo = [candidato.prefijo_documento + t for t in textos]
        return modelo.encode(con_prefijo, show_progress_bar=False).tolist()

    def incrustar_consultas(textos: list[str]) -> list[list[float]]:
        con_prefijo = [candidato.prefijo_consulta + t for t in textos]
        return modelo.encode(con_prefijo, show_progress_bar=False).tolist()

    return incrustar_documentos, incrustar_consultas


def formatear_tabla(filas: list[dict[str, Any]]) -> str:
    """Da formato Markdown a los resultados agregados por modelo.

    Args:
        filas: Una fila por modelo, con sus métricas agregadas y el tiempo
            de ejecución.

    Returns:
        Tabla Markdown lista para pegar en la memoria o en un documento.
    """
    cabecera = "| Modelo | Recall@3 | Recall@5 | MRR | Tiempo (s) |"
    separador = "|---|---|---|---|---|"
    lineas = [cabecera, separador]
    for fila in filas:
        lineas.append(
            f"| {fila['nombre']} | {fila['recall@3']:.3f} | {fila['recall@5']:.3f} "
            f"| {fila['mrr']:.3f} | {fila['tiempo_s']:.1f} |"
        )
    return "\n".join(lineas)


def main() -> int:
    """Ejecuta el experimento completo y muestra/guarda los resultados.

    Returns:
        0 si todos los modelos se evaluaron correctamente; 1 si alguno falló
        (p. ej. por no poder descargarse), para no ocultar un experimento a
        medias.
    """
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    # Import perezoso: solo evaluar_modelo, no crear_incrustadores, para dar
    # un error claro y rápido si faltan los chunks/eval antes de tocar red.
    from tfg_uja.evaluacion import evaluar_modelo

    chunks, preguntas = cargar_datos()
    print(f"Chunks: {len(chunks)} | Preguntas: {len(preguntas)}\n")

    filas: list[dict[str, Any]] = []
    fallos: list[str] = []
    for candidato in CANDIDATOS:
        print(f"Evaluando {candidato.nombre} ({candidato.descripcion}) ...")
        inicio = time.monotonic()
        try:
            incrustar_doc, incrustar_consulta = crear_incrustadores(candidato)
            resultado = evaluar_modelo(
                chunks, preguntas, incrustar_doc, incrustar_consulta, ks=KS
            )
        except Exception as error:  # noqa: BLE001 - se informa y se sigue con el resto
            print(f"  FALLÓ: {error}")
            fallos.append(f"{candidato.nombre}: {error}")
            continue
        tiempo = time.monotonic() - inicio
        fila = {
            "nombre": candidato.nombre,
            "tiempo_s": tiempo,
            **resultado["agregados"],
        }
        filas.append(fila)
        print(
            f"  Recall@3={fila['recall@3']:.3f}  Recall@5={fila['recall@5']:.3f}  "
            f"MRR={fila['mrr']:.3f}  ({tiempo:.1f}s)"
        )

    if not filas:
        print("\nNingún modelo pudo evaluarse.")
        return 1

    tabla = formatear_tabla(filas)
    print("\n" + tabla)

    RUTA_RESULTADOS.parent.mkdir(parents=True, exist_ok=True)
    cabecera_md = (
        "# IT-28 — Resultados del experimento comparativo de embeddings\n\n"
        f"Generado ejecutando `py scripts/experimento_embeddings.py` contra el "
        f"dataset real ({len(chunks)} chunks, {len(preguntas)} preguntas de "
        "eval/preguntas_evaluacion.json).\n\n"
    )
    pie_md = "\n\n## Modelos evaluados\n\n" + "\n".join(
        f"- `{c.nombre}`: {c.descripcion}" for c in CANDIDATOS
    )
    if fallos:
        pie_md += "\n\n## Fallos\n\n" + "\n".join(f"- {f}" for f in fallos)
    RUTA_RESULTADOS.write_text(cabecera_md + tabla + pie_md + "\n", encoding="utf-8")
    print(f"\nResultados guardados en {RUTA_RESULTADOS}")

    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())

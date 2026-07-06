"""Troceado (chunking) del dataset extraído por el spider.

Convierte los items del dataset (asignaturas, guías docentes y salidas
profesionales) en chunks listos para indexar en el sistema RAG. Cada chunk
pertenece a una única unidad semántica: una asignatura o el bloque de
salidas de un grado; nunca se mezclan dos asignaturas en un mismo chunk.

La estrategia y sus parámetros se justifican en el ADR-0001 a partir de la
distribución real de tamaños del dataset (mediana de 2.675 caracteres por
guía, percentil 90 de 6.450): la mayoría de guías no cabe en un solo chunk
del tamaño que admiten los modelos de embeddings habituales, por lo que se
trocea respetando párrafos y frases, y cada chunk se hace autocontenido
anteponiendo un encabezado con la asignatura y el grado.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Final

#: Tamaño objetivo de un chunk, en caracteres. Aproximación conservadora a
#: los ~512 tokens que admiten los modelos de embeddings multilingües más
#: comunes (≈4 caracteres por token en español deja margen para el
#: encabezado). Valor de referencia inicial; el definitivo se fijará
#: experimentalmente en la Fase 1 (ver ADR-0001).
TAMANO_OBJETIVO: Final[int] = 1200

#: Tamaño máximo estricto de un chunk. Ningún chunk lo supera: un párrafo
#: más largo se divide por frases.
TAMANO_MAXIMO: Final[int] = 1500

#: Nombres legibles de los tipos de asignatura, para los encabezados.
_NOMBRE_TIPO: Final[dict[str, str]] = {
    "FB": "asignatura de formación básica",
    "OB": "asignatura obligatoria",
    "OP": "asignatura optativa",
    "OB-IS": "asignatura obligatoria de la especialidad Ingeniería del Software",
    "OB-SI": "asignatura obligatoria de la especialidad Sistemas de Información",
    "OB-TI": "asignatura obligatoria de la especialidad Tecnologías de la Información",
    "TFG": "Trabajo Fin de Grado",
}

_FRONTERA_FRASE: Final[re.Pattern[str]] = re.compile(r"(?<=[.;!?])\s+")


def _dividir_en_piezas(texto: str, maximo: int) -> list[str]:
    """Divide un texto en piezas que no superan el tamaño máximo.

    Primero separa por párrafos (dobles saltos de línea); un párrafo que
    exceda el máximo se subdivide por fronteras de frase. Solo como último
    recurso (una "frase" más larga que el máximo, p. ej. un listado sin
    puntuación) se corta por el último espacio antes del límite, nunca en
    mitad de una palabra.

    Args:
        texto: Texto completo de la unidad semántica.
        maximo: Longitud máxima de cada pieza, en caracteres.

    Returns:
        Piezas no vacías, en el orden original del texto.
    """
    piezas: list[str] = []
    for parrafo in re.split(r"\n{2,}", texto):
        parrafo = parrafo.strip()
        if not parrafo:
            continue
        if len(parrafo) <= maximo:
            piezas.append(parrafo)
            continue
        for frase in _FRONTERA_FRASE.split(parrafo):
            frase = frase.strip()
            while len(frase) > maximo:
                corte = frase.rfind(" ", 0, maximo)
                if corte <= 0:
                    corte = maximo
                piezas.append(frase[:corte].strip())
                frase = frase[corte:].strip()
            if frase:
                piezas.append(frase)
    return piezas


def _empaquetar(piezas: list[str], objetivo: int, maximo: int) -> list[str]:
    """Agrupa piezas consecutivas en chunks cercanos al tamaño objetivo.

    Acumula piezas mientras el resultado no supere el objetivo; nunca
    produce un chunk por encima del máximo. El orden se conserva.

    Args:
        piezas: Fragmentos producidos por :func:`_dividir_en_piezas`.
        objetivo: Tamaño al que se aspira por chunk.
        maximo: Tamaño que ningún chunk debe superar.

    Returns:
        Textos de los chunks resultantes.
    """
    chunks: list[str] = []
    actual = ""
    for pieza in piezas:
        candidata = f"{actual}\n{pieza}".strip() if actual else pieza
        if actual and len(candidata) > objetivo:
            chunks.append(actual)
            actual = pieza
        else:
            actual = candidata
    if actual:
        chunks.append(actual)
    return chunks



def _encabezado_asignatura(asignatura: dict[str, Any]) -> str:
    """Compone el encabezado autocontenido de los chunks de una asignatura.

    El encabezado repite los metadatos clave (nombre, tipo, créditos,
    menciones y grado) para que cada chunk tenga sentido por sí solo al
    recuperarse de forma aislada en el RAG.

    Args:
        asignatura: Item de tipo ``asignatura`` del dataset.

    Returns:
        Encabezado en una sola línea, terminado en punto.
    """
    tipo = _NOMBRE_TIPO.get(
        asignatura["tipo_asignatura"], f"asignatura ({asignatura['tipo_asignatura']})"
    )
    partes = [f"«{asignatura['nombre']}», {tipo}"]
    if asignatura.get("ects"):
        partes.append(f"de {asignatura['ects']} ECTS")
    partes.append(f"del {asignatura['grado']}")
    encabezado = " ".join(partes)
    if asignatura.get("menciones"):
        encabezado += f" (mención: {', '.join(asignatura['menciones'])})"
    if not asignatura.get("ofertada", True):
        encabezado += ". No ofertada en el curso rastreado"
    return encabezado + "."


def _chunks_de_unidad(
    encabezado: str,
    texto: str,
    base: dict[str, Any],
    origen: str,
) -> list[dict[str, Any]]:
    """Genera los chunks de una unidad semántica completa.

    Divide, empaqueta y fusiona el texto, antepone el encabezado a cada
    chunk y numera ``chunk_index``/``total_chunks`` de forma consistente.

    Args:
        encabezado: Línea de contexto que se antepone a cada chunk.
        texto: Contenido de la unidad (guía, ficha o salidas).
        base: Campos comunes del item (grado, codigo, nombre).
        origen: Procedencia del contenido (``"guia"``, ``"asignatura_sin_guia"``
            o ``"salidas"``).

    Returns:
        Items de tipo ``chunk``, en orden.
    """
    # El encabezado y su salto de línea restan espacio al cuerpo: se
    # descuentan del presupuesto para que el chunk completo (encabezado +
    # cuerpo) nunca supere TAMANO_MAXIMO. Sin este descuento, 40 chunks del
    # dataset real superaban el máximo (hasta 1.758 caracteres).
    hueco = len(encabezado) + 1
    maximo = max(TAMANO_MAXIMO - hueco, 1)
    objetivo = max(TAMANO_OBJETIVO - hueco, 1)
    piezas = _dividir_en_piezas(texto, maximo)
    cuerpos = _empaquetar(piezas, objetivo, maximo)
    total = len(cuerpos)
    return [
        {
            "tipo": "chunk",
            "origen": origen,
            **base,
            "texto": f"{encabezado}\n{cuerpo}".strip(),
            "chunk_index": indice,
            "total_chunks": total,
        }
        for indice, cuerpo in enumerate(cuerpos)
    ]


def trocear_dataset(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convierte el dataset del spider en la lista de chunks del RAG.

    Recorre las guías docentes (contenido principal), y las salidas profesionales
    de cada grado. Cada chunk pertenece a una sola unidad semántica.

    Args:
        items: Dataset completo tal como lo exporta el spider
            (items ``grado``, ``asignatura``, ``guia`` y ``salidas``).

    Returns:
        Lista de items ``chunk`` con ``chunk_index``/``total_chunks``.
    """
    asignaturas = {
        (a["grado"], a["codigo"]): a for a in items if a["tipo"] == "asignatura"
    }
    chunks: list[dict[str, Any]] = []

    for item in items:
        if item["tipo"] == "guia":
            asignatura = asignaturas.get((item["grado"], item["codigo"]))
            encabezado = (
                _encabezado_asignatura(asignatura)
                if asignatura
                else f"«{item['nombre']}», asignatura del {item['grado']}."
            )
            if item.get("fallback"):
                texto = item.get("cuerpo_general", "")
            else:
                texto = "\n\n".join(
                    parte
                    for parte in (item.get("resumen", ""), item.get("temario", ""))
                    if parte
                )
            base = {
                "grado": item["grado"],
                "codigo": item["codigo"],
                "nombre": item["nombre"],
            }
            chunks.extend(_chunks_de_unidad(encabezado, texto, base, "guia"))

        elif item["tipo"] == "salidas":
            encabezado = f"Salidas profesionales del {item['grado']}:"
            base = {"grado": item["grado"], "codigo": None, "nombre": item["grado"]}
            chunks.extend(
                _chunks_de_unidad(encabezado, item["texto"], base, "salidas")
            )

    return chunks


def main(ruta_entrada: str, ruta_salida: str) -> None:
    """Trocea un dataset JSON y escribe los chunks resultantes.

    Args:
        ruta_entrada: Ruta del ``grados.json`` exportado por el spider.
        ruta_salida: Ruta donde escribir el ``chunks.json`` resultante.
    """
    items = json.loads(Path(ruta_entrada).read_text(encoding="utf-8"))
    chunks = trocear_dataset(items)
    Path(ruta_salida).write_text(
        json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"{len(chunks)} chunks escritos en {ruta_salida}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

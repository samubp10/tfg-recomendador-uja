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
from datetime import date
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

#: Tamaño mínimo de un chunk. Un fragmento residual por debajo de este
#: umbral se fusiona con el chunk anterior de su misma unidad (IT-09) para
#: no contaminar el índice con fragmentos sin entidad.
TAMANO_MINIMO: Final[int] = 200

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


def _fusionar_pequenos(chunks: list[str], minimo: int, maximo: int) -> list[str]:
    """Fusiona con su vecino los chunks por debajo del mínimo (IT-09).

    Un fragmento residual (típicamente el último de la unidad) se une al
    chunk anterior. Si la suma superase el máximo, el par se reequilibra:
    el texto combinado se reempaqueta en dos mitades, de modo que ninguna
    supere el máximo y ambas queden por encima del mínimo. El máximo es la
    restricción dura (un chunk que excede la ventana del modelo de
    embeddings se truncaría en silencio, perdiendo contenido); el mínimo es
    una preferencia de calidad.

    Esa jerarquía es la que decide el caso en el que reequilibrar no sirve
    de nada. El texto combinado solo se puede repartir por sus fronteras
    naturales (párrafos y frases), y a veces las únicas disponibles son las
    que ya separaban el par: el reempaquetado devuelve entonces el mismo
    reparto de partida. Como el par no cabe junto sin superar el máximo y no
    hay forma de repartirlo mejor, se acepta el fragmento corto y se sigue
    adelante: incumplir una preferencia es admisible, romper la restricción
    dura no lo es.

    Reconocer ese caso es además lo que garantiza que el bucle termine. Solo
    se vuelve a empezar cuando el número de fragmentos ha disminuido de
    verdad, y como no puede bajar de uno, el número de reinicios está
    acotado; en cualquier otra situación se avanza. Sin esa condición, un
    par irreducible hacía que la función no terminara nunca (caso real:
    «Minería web», 13313008, en el corpus de 2026-27).

    Args:
        chunks: Chunks de una misma unidad semántica, en orden.
        minimo: Umbral por debajo del cual un chunk no tiene entidad.
        maximo: Tamaño que ningún chunk resultante supera.

    Returns:
        Chunks tras la fusión, en orden. Ninguno supera el máximo; alguno
        puede quedar por debajo del mínimo si no había manera de evitarlo.
    """
    resultado = list(chunks)
    i = 0
    while i < len(resultado):
        if len(resultado[i]) >= minimo or len(resultado) == 1:
            i += 1
            continue
        vecino = i - 1 if i > 0 else i + 1
        primero, segundo = min(i, vecino), max(i, vecino)
        combinado = f"{resultado[primero]}\n{resultado[segundo]}"
        if len(combinado) <= maximo:
            # El par cabe junto: dos fragmentos pasan a ser uno.
            resultado[primero : segundo + 1] = [combinado]
            i = 0  # hay progreso, se re-evalúa desde el principio
            continue
        # Reequilibrar: dos mitades equilibradas en lugar de un chunk
        # desbordado (caso real: la guía de Geofísica, 13212010).
        objetivo_local = min(len(combinado) // 2 + 1, maximo)
        piezas = _dividir_en_piezas(combinado, maximo)
        reequilibrado = _empaquetar(piezas, objetivo_local, maximo)
        resultado[primero : segundo + 1] = reequilibrado
        if len(reequilibrado) < 2:
            i = 0  # el reparto ha reducido el número de fragmentos
        else:
            # El reparto no reduce nada: puede ser el mismo de partida. Se
            # avanza en vez de reiniciar, para no repetirlo indefinidamente.
            i = segundo + 1
    return resultado


def _encabezado_asignatura(asignatura: dict[str, Any], grados: list[str]) -> str:
    """Compone el encabezado autocontenido de los chunks de una asignatura.

    El encabezado repite los metadatos clave (nombre, tipo, créditos,
    menciones y titulaciones) para que cada chunk tenga sentido por sí solo
    al recuperarse de forma aislada en el RAG. Cuando la misma asignatura se
    imparte en varias titulaciones (guías de contenido idéntico fusionadas
    en una sola unidad), el encabezado las enuncia todas; el tipo y los ECTS
    son comunes a todas ellas (verificado: nunca varían entre titulaciones
    que comparten guía).

    Args:
        asignatura: Item de tipo ``asignatura`` del dataset (aporta tipo,
            ECTS, menciones y estado de oferta).
        grados: Titulaciones en las que se imparte la asignatura, ordenadas.

    Returns:
        Encabezado en una sola línea, terminado en punto.
    """
    tipo = _NOMBRE_TIPO.get(
        asignatura["tipo_asignatura"], f"asignatura ({asignatura['tipo_asignatura']})"
    )
    partes = [f"«{asignatura['nombre']}», {tipo}"]
    if asignatura.get("ects"):
        partes.append(f"de {asignatura['ects']} ECTS")
    if len(grados) == 1:
        partes.append(f"del {grados[0]}")
    else:
        # Las menciones son específicas de cada titulación, por lo que no se
        # enuncian en una unidad compartida por varias.
        partes.append(f"impartida en {len(grados)} titulaciones: {'; '.join(grados)}")
    encabezado = " ".join(partes)
    if len(grados) == 1 and asignatura.get("menciones"):
        encabezado += f" (mención: {', '.join(asignatura['menciones'])})"
    if not asignatura.get("ofertada", True):
        encabezado += ". No ofertada en el curso rastreado"
    return encabezado + "."


def _encabezado_sin_metadatos(nombre: str, grados: list[str]) -> str:
    """Encabezado de respaldo cuando no hay asignatura asociada a la guía.

    Args:
        nombre: Nombre de la asignatura.
        grados: Titulaciones en las que se imparte, ordenadas.

    Returns:
        Encabezado en una sola línea, terminado en punto.
    """
    if len(grados) == 1:
        return f"«{nombre}», asignatura del {grados[0]}."
    return f"«{nombre}», asignatura impartida en: {'; '.join(grados)}."


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
    minimo = min(TAMANO_MINIMO, maximo)
    piezas = _dividir_en_piezas(texto, maximo)
    cuerpos = _empaquetar(piezas, objetivo, maximo)
    cuerpos = _fusionar_pequenos(cuerpos, minimo, maximo)
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


def _clave_asignatura(grado: str, codigo: str | None, nombre: str) -> tuple[str, str]:
    """Identifica una asignatura dentro de su titulación.

    El código no basta como identificador: las asignaturas de los planes de
    implantación reciente todavía no lo tienen publicado (cadena vacía), y
    agrupar solo por código las colapsa todas en una misma entrada, de modo
    que la última sobrescribe en silencio a las anteriores. Cuando falta el
    código se usa el nombre, que la fuente sí publica siempre.

    Es la misma regla que aplican :mod:`~tfg_uja.grados_spider` al fusionar
    las menciones y ``scripts/check_chunks.py`` al cotejar las unidades: los
    tres deben identificar una asignatura igual o dejan de hablar del mismo
    objeto. Cualquier código nuevo que necesite identificarla debe usarla.

    Args:
        grado: Titulación en la que se imparte la asignatura.
        codigo: Código publicado por la fuente, o vacío si no lo hay.
        nombre: Nombre de la asignatura.

    Returns:
        Par ``(grado, codigo_o_nombre)`` que identifica la asignatura.
    """
    return (grado, codigo or nombre)


def trocear_dataset(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convierte el dataset del spider en la lista de chunks del RAG.

    Recorre las guías docentes (contenido principal), las asignaturas sin
    guía (chunk informativo explícito, IT-09) y las salidas profesionales
    de cada grado. Cada chunk pertenece a una sola unidad semántica.

    Args:
        items: Dataset completo tal como lo exporta el spider
            (items ``grado``, ``asignatura``, ``guia`` y ``salidas``).

    Returns:
        Lista de items ``chunk`` con ``chunk_index``/``total_chunks``.
    """
    asignaturas = {
        _clave_asignatura(a["grado"], a["codigo"], a["nombre"]): a
        for a in items
        if a["tipo"] == "asignatura"
    }
    chunks: list[dict[str, Any]] = []

    # Deduplicación de guías compartidas (ADR-0001, decisión revisada): muchas
    # asignaturas de primeros cursos (Matemáticas I, Física...) se imparten en
    # varias titulaciones con la MISMA guía, byte a byte. Se agrupan por
    # (nombre, contenido) para no repetir su texto en el índice: la clave
    # incluye el nombre y no solo el contenido porque el fallback de IT-06
    # puede producir texto idéntico para asignaturas DISTINTAS, y fusionarlas
    # sería un error. Cada grupo produce una sola unidad con la lista de
    # titulaciones en las que se imparte.
    grupos_guia: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in items:
        if item["tipo"] != "guia":
            continue
        if item.get("fallback"):
            texto = item.get("cuerpo_general", "")
        else:
            texto = "\n\n".join(
                parte
                for parte in (item.get("resumen", ""), item.get("temario", ""))
                if parte
            )
        grupos_guia.setdefault((item["nombre"], texto), []).append(item)

    for (nombre, texto), guias in grupos_guia.items():
        # Orden estable de titulaciones para que el troceo sea determinista.
        guias = sorted(guias, key=lambda g: g["grado"])
        grados = [g["grado"] for g in guias]
        codigos = [g["codigo"] for g in guias]
        asignatura = asignaturas.get(
            _clave_asignatura(guias[0]["grado"], guias[0]["codigo"], nombre)
        )
        encabezado = (
            _encabezado_asignatura(asignatura, grados)
            if asignatura
            else _encabezado_sin_metadatos(nombre, grados)
        )
        base = {"grados": grados, "codigos": codigos, "nombre": nombre}
        chunks.extend(_chunks_de_unidad(encabezado, texto, base, "guia"))

    for item in items:
        if item["tipo"] == "salidas":
            encabezado = f"Salidas profesionales del {item['grado']}:"
            base = {
                "grados": [item["grado"]],
                "codigos": [None],
                "nombre": item["grado"],
            }
            chunks.extend(_chunks_de_unidad(encabezado, item["texto"], base, "salidas"))

    # IT-09: las asignaturas sin guía generan un chunk informativo explícito,
    # no un hueco silencioso: el RAG debe poder nombrarlas y situarlas. No se
    # deduplican entre titulaciones porque su chunk solo contiene metadatos y
    # son casi todas de las titulaciones en implantación (sin solapamiento).
    for asignatura in (
        a for a in items if a["tipo"] == "asignatura" and not a["tiene_guia"]
    ):
        encabezado = _encabezado_asignatura(asignatura, [asignatura["grado"]])
        texto = (
            "La guía docente de esta asignatura no está publicada en la web "
            "de la EPSJ, por lo que solo se dispone de sus datos básicos."
        )
        base = {
            "grados": [asignatura["grado"]],
            "codigos": [asignatura["codigo"]],
            "nombre": asignatura["nombre"],
        }
        chunks.append(
            {
                "tipo": "chunk",
                "origen": "asignatura_sin_guia",
                **base,
                "texto": f"{encabezado}\n{texto}",
                "chunk_index": 0,
                "total_chunks": 1,
            }
        )
    return chunks


def procedencia_de(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Compone la procedencia de los fragmentos a partir del dataset (IT-90).

    Arrastra la fecha de extracción que el spider dejó en el dataset y añade
    los cursos académicos realmente presentes, leídos del campo ``curso`` de
    cada guía (que el spider dedujo de su URL). Los cursos se enumeran todos:
    desde que la EPSJ publica las guías de un curso nuevo según las va
    teniendo, un mismo rastreo puede mezclar dos, y resumirlo a uno solo
    ocultaría de qué año es cada parte del corpus.

    Args:
        items: Dataset completo tal como lo exporta el spider.

    Returns:
        Item ``procedencia`` listo para encabezar el ``chunks.json``.
    """
    del_spider = next(
        (i for i in items if i.get("tipo") == "procedencia"),
        {},
    )
    cursos = sorted(
        {
            item["curso"]
            for item in items
            if item.get("tipo") == "guia" and item.get("curso")
        }
    )
    guias_sin_curso = sum(
        1 for i in items if i.get("tipo") == "guia" and not i.get("curso")
    )
    return {
        "tipo": "procedencia",
        "fecha_extraccion": del_spider.get("fecha_extraccion"),
        "fecha_troceado": date.today().isoformat(),
        "cursos": cursos,
        "guias_sin_curso": guias_sin_curso,
    }


def main(ruta_entrada: str, ruta_salida: str) -> None:
    """Trocea un dataset JSON y escribe los chunks resultantes.

    El fichero de salida empieza por el item ``procedencia`` (IT-90) para que
    los fragmentos digan por sí mismos de cuándo y de qué curso son, sin
    depender de una nota escrita aparte que se puede quedar atrás al copiar
    el fichero.

    Args:
        ruta_entrada: Ruta del ``grados.json`` exportado por el spider.
        ruta_salida: Ruta donde escribir el ``chunks.json`` resultante.
    """
    items = json.loads(Path(ruta_entrada).read_text(encoding="utf-8"))
    chunks = trocear_dataset(items)
    procedencia = procedencia_de(items)
    Path(ruta_salida).write_text(
        json.dumps([procedencia, *chunks], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    cursos = ", ".join(procedencia["cursos"]) or "sin determinar"
    print(
        f"{len(chunks)} chunks escritos en {ruta_salida} "
        f"(extraccion {procedencia['fecha_extraccion']}, curso {cursos})"
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

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

#: Agrupaciones del plan de estudios que el corpus publica como listado
#: (IT-100). La clave es el nombre que aparece en el encabezado del fragmento;
#: el valor, los tipos de asignatura que agrupa.
#:
#: «Obligatorias» reúne formación básica, obligatorias comunes, obligatorias de
#: especialidad y el TFG, porque desde el punto de vista de un estudiante
#: preuniversitario son lo mismo: asignaturas que hay que superar sí o sí. La
#: distinción entre FB y OB es administrativa y sigue estando en el fragmento
#: de cada asignatura, que es donde importa.
_GRUPOS_PLAN: Final[dict[str, frozenset[str]]] = {
    "obligatorias": frozenset({"FB", "OB", "OB-IS", "OB-SI", "OB-TI", "TFG"}),
    "optativas": frozenset({"OP"}),
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

    Reconocer ese caso es además parte de lo que garantiza que el bucle
    termine. Solo se vuelve a empezar cuando el número de fragmentos ha
    disminuido de verdad; en cualquier otra situación se avanza. Sin esa
    condición, un par irreducible hacía que la función no terminara nunca
    (caso real: «Minería web», 13313008, en el corpus de 2026-27).

    Eso, por sí solo, resultó no bastar. El argumento de terminación suponía
    que el número de fragmentos únicamente podía bajar, y **el reparto también
    puede subirlo**: devolver tres fragmentos donde había dos. Alternando
    fusiones que lo bajan con repartos que lo suben, el recuento oscilaba
    (7, 8, 7, 8...) y no se llegaba nunca al final. Por eso se descarta todo
    reparto que produzca más fragmentos de los que había: así el recuento es
    monótono no creciente, no puede bajar de uno, y los reinicios quedan
    acotados.

    Con los tamaños del ADR-0001 el caso no se alcanzaba, y salió a la luz al
    hacerlos parametrizables y probar valores pequeños: con un
    máximo de 380 caracteres, el fragmentador se colgaba sobre el dataset
    completo. Es la segunda vez que esta función no termina por un motivo que
    las pruebas en verde no veían.

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
        if len(reequilibrado) > segundo - primero + 1:
            # El reparto devuelve MÁS fragmentos de los que había: no
            # reequilibra, empeora. Se descarta y se acepta el fragmento
            # corto, igual que cuando el reparto no cambia nada.
            #
            # Esto es lo que garantiza que el bucle termine, y es la parte que
            # a IT-92 se le escapó. Aquel arreglo razonaba que el número de
            # fragmentos solo podía bajar, y por eso reiniciar en `i = 0` tras
            # cada fusión estaba acotado. Pero el reparto SÍ podía subirlo, de
            # 2 a 3, con lo que el recuento oscilaba (7, 8, 7, 8...) y el
            # bucle no acababa nunca. Con esta guarda el número de fragmentos
            # es monótono no creciente, así que los reinicios están acotados.
            i = segundo + 1
            continue
        resultado[primero : segundo + 1] = reequilibrado
        if len(reequilibrado) < segundo - primero + 1:
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
    tamanos: tuple[int, int, int] = (TAMANO_OBJETIVO, TAMANO_MAXIMO, TAMANO_MINIMO),
) -> list[dict[str, Any]]:
    """Genera los chunks de una unidad semántica completa.

    Divide, empaqueta y fusiona el texto, antepone el encabezado a cada
    chunk y numera ``chunk_index``/``total_chunks`` de forma consistente.

    Args:
        encabezado: Línea de contexto que se antepone a cada chunk.
        texto: Contenido de la unidad (guía, ficha o salidas).
        base: Campos comunes del item (grado, codigo, nombre).
        origen: Procedencia del contenido (``"guia"``,
            ``"asignatura_sin_guia"``, ``"salidas"`` o ``"plan_de_estudios"``).
        tamanos: Terna ``(objetivo, máximo, mínimo)`` en caracteres. Por
            defecto, los del ADR-0001.

    Returns:
        Items de tipo ``chunk``, en orden.
    """
    # El encabezado y su salto de línea restan espacio al cuerpo: se
    # descuentan del presupuesto para que el chunk completo (encabezado +
    # cuerpo) nunca supere el máximo. Sin este descuento, 40 chunks del
    # dataset real superaban el máximo (hasta 1.758 caracteres).
    tam_objetivo, tam_maximo, tam_minimo = tamanos
    hueco = len(encabezado) + 1
    maximo = max(tam_maximo - hueco, 1)
    objetivo = max(tam_objetivo - hueco, 1)
    minimo = min(tam_minimo, maximo)
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


def _chunks_de_plan_de_estudios(
    items: list[dict[str, Any]],
    tamanos: tuple[int, int, int],
) -> list[dict[str, Any]]:
    """Genera el listado de asignaturas de cada titulación, por grupo (IT-100).

    Resuelve un problema que el troceo por asignatura no puede resolver. Una
    pregunta como «dime todas las obligatorias de Informática» tiene, en el
    corpus troceado por asignatura, **118 fragmentos relevantes**: ningún
    top-K razonable los recupera, y no por un fallo del recuperador sino
    porque es una pregunta de agregación y la recuperación devuelve los K
    mejores, no todos. Medido el 01/08/2026: el techo de Recall@5 de esa
    pregunta es 0,042.

    Con el listado ya agregado en el corpus, la misma pregunta pasa a tener
    **un solo fragmento relevante**. Y el generador copia una lista completa
    en vez de reconstruirla a partir de cincuenta trozos, que es donde se deja
    asignaturas.

    Es contenido **derivado**, no literal de la fuente, igual que los
    fragmentos informativos de las asignaturas sin guía (IT-09) y por el mismo
    motivo: se compone de forma determinista a partir de datos que la fuente
    sí publica, sin añadir nada. Queda declarado en el ADR-0001.

    Args:
        items: Dataset completo tal como lo exporta el spider.

    Returns:
        Items ``chunk`` de origen ``plan_de_estudios``, uno o más por cada par
        (titulación, grupo) que tenga asignaturas.
    """
    por_grado: dict[str, list[dict[str, Any]]] = {}
    for a in items:
        if a["tipo"] == "asignatura":
            por_grado.setdefault(a["grado"], []).append(a)

    chunks: list[dict[str, Any]] = []
    for grado in sorted(por_grado):
        for grupo, tipos in _GRUPOS_PLAN.items():
            asignaturas = [a for a in por_grado[grado] if a["tipo_asignatura"] in tipos]
            if not asignaturas:
                continue
            # Orden alfabético y no el de la fuente: el de la fuente depende
            # del orden de las filas de la tabla, que ya ha cambiado una vez
            # (IT-76). Alfabético es estable y además se lee mejor.
            lineas = []
            for a in sorted(asignaturas, key=lambda x: x["nombre"]):
                # El ECTS ausente se refleja, no se imputa (decisión 9).
                ects = f" ({a['ects']} ECTS)" if a["ects"] else ""
                lineas.append(f"{a['nombre']}{ects}.")
            encabezado = (
                f"Asignaturas {grupo} del {grado}. " f"En total son {len(asignaturas)}:"
            )
            base = {
                "grados": [grado],
                "codigos": [None],
                "nombre": f"Asignaturas {grupo} del {grado}",
                "tipo_asignatura": "",
            }
            chunks.extend(
                _chunks_de_unidad(
                    # Cada asignatura es su propio párrafo, no una frase de una
                    # lista corrida. Así el troceo corta siempre entre
                    # asignaturas y nunca a mitad de una, y el formato es el
                    # mismo tanto si el listado cabe en un fragmento como si
                    # necesita dos.
                    encabezado,
                    "\n\n".join(lineas),
                    base,
                    "plan_de_estudios",
                    tamanos,
                )
            )
    return chunks


def trocear_dataset(
    items: list[dict[str, Any]],
    tamanos: tuple[int, int, int] = (
        TAMANO_OBJETIVO,
        TAMANO_MAXIMO,
        TAMANO_MINIMO,
    ),
) -> list[dict[str, Any]]:
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
        # IT-100: el tipo viaja también como metadato, no solo dentro del
        # encabezado. Sin él no se puede filtrar el índice por «obligatorias»
        # ni anotar una pregunta de listado sin enumerar cincuenta nombres.
        # Se toma de la primera titulación del grupo: el ADR-0001 verificó que
        # el tipo y los ECTS nunca varían entre titulaciones que comparten
        # guía (0 de 28 grupos), así que colapsarlo no pierde información.
        base = {
            "grados": grados,
            "codigos": codigos,
            "nombre": nombre,
            "tipo_asignatura": asignatura["tipo_asignatura"] if asignatura else "",
        }
        chunks.extend(_chunks_de_unidad(encabezado, texto, base, "guia", tamanos))

    for item in items:
        if item["tipo"] == "salidas":
            encabezado = f"Salidas profesionales del {item['grado']}:"
            base = {
                "grados": [item["grado"]],
                "codigos": [None],
                "nombre": item["grado"],
                # Las salidas no son una asignatura: el campo queda vacío en
                # lugar de inventarle un tipo, con el mismo criterio que se
                # aplica al ECTS ausente.
                "tipo_asignatura": "",
            }
            chunks.extend(
                _chunks_de_unidad(encabezado, item["texto"], base, "salidas", tamanos)
            )

    chunks.extend(_chunks_de_plan_de_estudios(items, tamanos))

    # IT-09: las asignaturas sin guía generan un chunk informativo explícito,
    # no un hueco silencioso: el RAG debe poder nombrarlas y situarlas. No se
    # deduplican entre titulaciones porque su chunk solo contiene metadatos y
    # son casi todas de las titulaciones en implantación (sin solapamiento).
    #
    # IT-94: «sin guía» se decide por lo que hay en el dataset, no por lo que
    # el rastreador anunció en `tiene_guia`. Una guía servida como PDF
    # ilegible no llega a emitirse (IT-67), pero su asignatura ya salió con
    # `tiene_guia=True` porque en la tabla sí había enlace. Fiarse de ese
    # campo dejaba a esas asignaturas sin chunk de guía y sin chunk
    # informativo: desaparecían del corpus (5 casos en el rastreo del
    # 28/07/2026). El fragmentador ve el dataset entero y puede comprobarlo.
    guias_presentes = {
        _clave_asignatura(g["grado"], g["codigo"], g["nombre"])
        for g in items
        if g["tipo"] == "guia"
    }
    for asignatura in (
        a
        for a in items
        if a["tipo"] == "asignatura"
        and _clave_asignatura(a["grado"], a["codigo"], a["nombre"])
        not in guias_presentes
    ):
        encabezado = _encabezado_asignatura(asignatura, [asignatura["grado"]])
        # Los dos motivos por los que una asignatura se queda sin guía no son
        # el mismo, y el corpus no puede afirmar el que no es: decir que no
        # está publicada cuando sí lo está sería dar por buena una respuesta
        # falsa al estudiante que pregunte por ella.
        #
        # IT-95 corrige el segundo texto. Decía «no ha podido obtenerse», que
        # insinúa un fallo del sistema, y resultó ser falso: descargadas las
        # seis guías implicadas el 29/07/2026, las seis se leen perfectamente y
        # lo que está vacío son sus secciones de contenido en el origen. El
        # corpus tampoco puede atribuirse un fallo que no ha cometido.
        if asignatura["tiene_guia"]:
            texto = (
                "La guía docente de esta asignatura está publicada en la web de "
                "la EPSJ, pero no recoge ni resumen ni temario, por lo que solo "
                "se dispone de sus datos básicos."
            )
        else:
            texto = (
                "La guía docente de esta asignatura no está publicada en la web "
                "de la EPSJ, por lo que solo se dispone de sus datos básicos."
            )
        base = {
            "grados": [asignatura["grado"]],
            "codigos": [asignatura["codigo"]],
            "nombre": asignatura["nombre"],
            "tipo_asignatura": asignatura["tipo_asignatura"],
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


def main(
    ruta_entrada: str,
    ruta_salida: str,
    tamanos: tuple[int, int, int] = (
        TAMANO_OBJETIVO,
        TAMANO_MAXIMO,
        TAMANO_MINIMO,
    ),
) -> None:
    """Trocea un dataset JSON y escribe los chunks resultantes.

    El fichero de salida empieza por el item ``procedencia`` (IT-90) para que
    los fragmentos digan por sí mismos de cuándo y de qué curso son, sin
    depender de una nota escrita aparte que se puede quedar atrás al copiar
    el fichero.

    Args:
        ruta_entrada: Ruta del ``grados.json`` exportado por el spider.
        ruta_salida: Ruta donde escribir el ``chunks.json`` resultante.
        tamanos: Terna ``(objetivo, máximo, mínimo)`` en caracteres. Por
            defecto, los del ADR-0001.
    """
    items = json.loads(Path(ruta_entrada).read_text(encoding="utf-8"))
    chunks = trocear_dataset(items, tamanos)
    procedencia = procedencia_de(items)
    procedencia["tamanos"] = list(tamanos)
    Path(ruta_salida).write_text(
        json.dumps([procedencia, *chunks], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    cursos = ", ".join(procedencia["cursos"]) or "sin determinar"
    print(
        f"{len(chunks)} chunks escritos en {ruta_salida} "
        f"(extraccion {procedencia['fecha_extraccion']}, curso {cursos}, "
        f"tamanos {tamanos[0]}/{tamanos[1]}/{tamanos[2]})"
    )


if __name__ == "__main__":
    # Los tamaños son opcionales y solo se pasan para experimentar (IT-100:
    # re-trocear a la ventana de los modelos de 128 tokens para compararlos en
    # igualdad de condiciones). Sin ellos, el comportamiento es el de siempre.
    #
    #     py -m tfg_uja.chunker entrada.json salida.json [objetivo maximo minimo]
    if len(sys.argv) >= 6:
        main(
            sys.argv[1],
            sys.argv[2],
            (int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])),
        )
    else:
        main(sys.argv[1], sys.argv[2])

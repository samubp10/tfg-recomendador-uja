"""Troceado (chunking) del dataset extraído por el spider.

Convierte los items del dataset (asignaturas, guías docentes y salidas
profesionales) en chunks listos para indexar en el sistema RAG. Cada chunk
pertenece a una única unidad semántica: una asignatura o el bloque de
salidas de un grado; nunca se mezclan dos asignaturas en un mismo chunk.

La estrategia y sus parámetros se justifican en el ADR-0001 a partir de la
distribución real de tamaños del dataset (mediana de 2.656 caracteres por
guía, percentil 90 de 6.023, máximo de 24.046): la mayoría de guías no cabe
en un solo chunk del tamaño que admite el modelo de incrustaciones elegido,
por lo que se trocea respetando párrafos y frases, y cada chunk se hace
autocontenido anteponiendo un encabezado con la asignatura y el grado.

Los tamaños dejaron de ser provisionales en IT-16: salen de una búsqueda en
rejilla de 45 configuraciones (tres estrategias × cinco máximos × tres
valores del parámetro propio de cada una) medida sobre el conjunto de
evaluación, no de una estimación de cuántos tokens caben en un carácter.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Final

#: Tamaño objetivo de un chunk, en caracteres. Coincide a propósito con el
#: máximo: la rejilla de IT-16 midió las tres proporciones (60 %, 80 % y
#: 100 % del máximo) y la de 100 % fue la mejor de la estrategia estructural,
#: así que no hay motivo para dejar hueco sin usar.
#:
#: Valía 1200, elegido como aproximación a los ~512 tokens que se suponía que
#: admitían los modelos multilingües habituales. Esa premisa resultó falsa
#: —dos de los cuatro candidatos de IT-28 servían 128 tokens— y la estimación
#: nunca se contrastó con el analizador léxico del modelo que acabó
#: eligiéndose. Ahora sale de la medición y no de una regla de tres.
TAMANO_OBJETIVO: Final[int] = 900

#: Tamaño máximo estricto de un chunk. Ningún chunk lo supera: un párrafo
#: más largo se divide por frases.
#:
#: Valía 1500. La rejilla de IT-16 recorrió 600, 900, 1200, 1500 y 1800 con
#: las tres estrategias y encontró que este parámetro pesa mucho más que la
#: estrategia: a igualdad de estrategia, cuanto menor es el máximo, mejor se
#: recupera. Se elige 900 y no 600 porque 600 gana en las métricas pero
#: multiplica los fragmentos, y esa ventaja no sobrevive al controlar por su
#: número; la de 900 sí (ver ADR-0001).
#:
#: El argumento que no depende de ninguna métrica discutible es el truncado:
#: con 900 ningún fragmento supera la ventana del modelo de incrustaciones,
#: con 1500 aparecen los primeros y con 1800 llegan a 29. El modelo los
#: recortaría en silencio, sin avisar ni fallar.
TAMANO_MAXIMO: Final[int] = 900

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

#: Ordinales de curso, en el orden en que se estudian. Se usan para ordenar
#: los listados por curso: un rótulo disyuntivo como «Tercer o cuarto curso»
#: ordena por el primero que nombra, que es lo antes que puede cursarse.
#:
#: Es público porque el generador ordena con él los listados que llegan al
#: contexto. Si cada módulo tuviera el suyo podrían discrepar en silencio, que
#: es el mismo motivo por el que la convención de prefijos vive en un solo
#: sitio desde el ADR-0003.
ORDEN_CURSOS: Final[tuple[str, ...]] = (
    "primer",
    "segundo",
    "tercer",
    "cuarto",
    "quinto",
    "sexto",
)

_FRONTERA_FRASE: Final[re.Pattern[str]] = re.compile(r"(?<=[.;!?])\s+")


#: Acrónimo del grado de procedencia que los planes de los dobles grados
#: añaden al final del nombre de una asignatura, entre paréntesis: «CIRCUITOS
#: (GIE)», «MARKETING INDUSTRIAL (GIOI)». No forma parte del nombre con el que
#: la asignatura figura en su grado simple.
_SUFIJO_GRADO: Final[re.Pattern[str]] = re.compile(r"\s*\([A-Z]{2,8}\)\s*$")


def _normalizar(nombre: str) -> str:
    """Devuelve un nombre de asignatura en forma comparable.

    Los planes de los dobles grados escriben los nombres en mayúsculas
    («MATEMÁTICAS I») y los de los grados simples en minúsculas
    («Matemáticas I»). Comparando en crudo no casaba ni uno solo de los 178
    nombres, y las asignaturas del doble grado acababan con un fragmento que
    afirmaba en falso que no tenían guía publicada.

    Args:
        nombre: Nombre de la asignatura tal como llega de la fuente.

    Returns:
        El nombre en minúsculas, sin tildes y con los espacios colapsados.
    """
    sin_tildes = (
        unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode("ascii")
    )
    return " ".join(sin_tildes.split()).lower()


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
    # IT-105: el curso va DENTRO del texto y no solo como metadato. Un dato que
    # no aparece en el fragmento el modelo generativo no lo ve, y sin verlo se
    # lo inventa: preguntado por el primer año, respondió con el listado entero
    # del grado y atribuyó cursos y cuatrimestres que nadie le había dado.
    situacion = _situacion_en_el_plan(asignatura)
    if situacion:
        encabezado += f". Se imparte en {situacion}"
    if not asignatura.get("ofertada", True):
        encabezado += ". No ofertada en el curso rastreado"
    return encabezado + "."


def _situacion_en_el_plan(asignatura: dict[str, Any]) -> str:
    """Redacta en qué curso y cuatrimestre se imparte una asignatura.

    Lo que no consta no se rellena (decisión 9). Las optativas de los grados
    simples no llevan curso publicado, y los dobles grados lo publican de forma
    disyuntiva ---«Tercer o cuarto curso»--- porque a partir de tercero el
    estudiante elige por qué especialidad empieza.

    Args:
        asignatura: Item de tipo ``asignatura`` del dataset.

    Returns:
        La situación en el plan, o cadena vacía si la fuente no la publica.
    """
    curso = (asignatura.get("curso") or "").strip()
    cuatrimestre = (asignatura.get("cuatrimestre") or "").strip()
    if curso and cuatrimestre:
        return f"el {cuatrimestre.lower()} de {curso.lower()}"
    if curso:
        return f"el {curso.lower()}"
    if cuatrimestre:
        # El hueco se dice, no se deja en blanco. Medido el 16/08/2026: con el
        # encabezado diciendo solo «Se imparte en el segundo cuatrimestre», el
        # modelo respondió que la asignatura era «optativa en 2º curso»,
        # convirtiendo el cuatrimestre en un curso que la fuente no publica.
        return f"el {cuatrimestre.lower()}, sin curso asignado en el plan"
    return ""


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
            for curso, del_curso in _por_curso(asignaturas):
                # Orden alfabético y no el de la fuente: el de la fuente depende
                # del orden de las filas de la tabla, que ya ha cambiado una vez
                # (IT-76). Alfabético es estable y además se lee mejor.
                lineas = []
                for a in sorted(del_curso, key=lambda x: x["nombre"]):
                    # El ECTS ausente se refleja, no se imputa (decisión 9).
                    ects = f" ({a['ects']} ECTS)" if a["ects"] else ""
                    lineas.append(f"{a['nombre']}{ects}.")
                titulo = f"Asignaturas {grupo} de {curso.lower()} del {grado}"
                if not curso:
                    titulo = f"Asignaturas {grupo} del {grado}"
                encabezado = f"{titulo}. En total son {len(del_curso)}:"
                base = {
                    "grados": [grado],
                    "codigos": [None],
                    "nombre": titulo,
                    "tipo_asignatura": "",
                    "curso": curso,
                }
                chunks.extend(
                    _chunks_de_unidad(
                        # Cada asignatura es su propio párrafo, no una frase de
                        # una lista corrida. Así el troceo corta siempre entre
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


def _duracion_en_cursos(asignaturas: list[dict[str, Any]]) -> int:
    """Cuántos cursos abarca un plan, según el ordinal más alto que rotula.

    Se deduce de los rótulos que publica la fuente y no de una regla del tipo
    «un grado dura cuatro años»: los dobles duran cinco y el corpus tiene los
    dos casos. Un rótulo disyuntivo ---«Tercer o cuarto curso»--- cuenta por el
    más alto que nombra, porque el plan llega hasta ahí.

    Args:
        asignaturas: Asignaturas de una misma titulación.

    Returns:
        Número de cursos, o 0 si ninguna asignatura lleva curso rotulado.
    """
    tope = 0
    for asignatura in asignaturas:
        rotulo = (asignatura.get("curso") or "").lower()
        for posicion, ordinal in enumerate(ORDEN_CURSOS, start=1):
            if ordinal in rotulo:
                tope = max(tope, posicion)
    return tope


def _chunks_de_catalogo(
    items: list[dict[str, Any]],
    tamanos: tuple[int, int, int],
) -> list[dict[str, Any]]:
    """Genera el fragmento que enumera la oferta de la Escuela (IT-107).

    «¿Qué se puede estudiar en la EPSJ?» es la primera pregunta de un
    preuniversitario y el corpus **no la contestaba**: la respuesta está
    repartida entre doce titulaciones y ningún fragmento la reúne, así que la
    recuperación no traía nada pertinente y el sistema contestaba que no tenía
    información. Medido el 17/08/2026: preguntado por las titulaciones de la
    rama industrial, un modelo de 7B nombró cinco reales y se inventó una
    especialidad que no existe.

    Args:
        items: Dataset completo tal como lo exporta el spider.
        tamanos: Objetivo, máximo y mínimo de fragmento.

    Returns:
        Los fragmentos del catálogo, de origen ``catalogo``.
    """
    grados = sorted(
        (g for g in items if g["tipo"] == "grado"), key=lambda g: g["nombre"]
    )
    if not grados:
        return []
    simples = [g["nombre"] for g in grados if not g.get("es_doble_grado")]
    dobles = [g["nombre"] for g in grados if g.get("es_doble_grado")]

    def base_de(nombres: list[str], titulo: str) -> dict[str, Any]:
        return {
            # Las titulaciones de las que habla el fragmento. La lista no puede
            # ir vacía: el verificador exige que `grados` y `codigos` sean
            # listas paralelas y no vacías.
            "grados": nombres,
            "codigos": [None] * len(nombres),
            "nombre": titulo,
            "tipo_asignatura": "",
            "curso": "",
        }

    titulo = "Titulaciones que se imparten en la Escuela Politécnica Superior de Jaén"
    encabezado = (
        f"{titulo}. En total son {len(grados)}: {len(simples)} grados y "
        f"{len(dobles)} dobles grados."
    )
    bloques = []
    if simples:
        bloques.append("Grados:\n" + "\n".join(f"{n}." for n in simples))
    if dobles:
        bloques.append("Dobles grados:\n" + "\n".join(f"{n}." for n in dobles))
    chunks = _chunks_de_unidad(
        encabezado,
        "\n\n".join(bloques),
        base_de([g["nombre"] for g in grados], titulo),
        "catalogo",
        tamanos,
    )

    # Y uno por familia. No es redundancia gratuita: medido sobre el índice
    # completo, «¿qué dobles grados hay?» no recuperaba el catálogo sino
    # **veinte fichas** de titulaciones sueltas, porque los nombres propios
    # («Doble Grado en Ingeniería Eléctrica y Mecánica») se parecen más a la
    # pregunta que un encabezado que habla de las doce a la vez. Con su propio
    # fragmento, la pregunta cae donde tiene que caer.
    for familia, nombres in (("Grados", simples), ("Dobles grados", dobles)):
        if not nombres:
            continue
        titulo_familia = (
            f"{familia} que se imparten en la Escuela Politécnica Superior de Jaén"
        )
        chunks.extend(
            _chunks_de_unidad(
                f"{titulo_familia}. En total son {len(nombres)}:",
                "\n\n".join(f"{n}." for n in nombres),
                base_de(nombres, titulo_familia),
                "catalogo",
                tamanos,
            )
        )
    return chunks


def _chunks_de_ficha(
    items: list[dict[str, Any]],
    tamanos: tuple[int, int, int],
) -> list[dict[str, Any]]:
    """Genera la ficha de cifras de cada titulación (IT-107).

    Contesta las preguntas de recuento ---cuántas asignaturas tiene, cuántas
    optativas, cuántos cursos dura--- que el corpus contenía pero no decía.
    Medido el 17/08/2026: preguntado por cuántas asignaturas tiene Ingeniería
    Informática, un modelo de 7B contestó que **una**. La cifra real es 67 y no
    existía en el corpus como texto: había que contar 67 fragmentos.

    **No se emite el total de créditos.** Sumar los ECTS de todo lo que se
    oferta da 408 en Informática, y un grado son 240: la diferencia son las
    optativas, de las que solo se cursa una parte, y el corpus no publica
    cuántas. Un número que se lee como «los créditos de la carrera» y no lo es
    sería peor que no darlo.

    Una titulación sin asignaturas en el corpus recibe **su propio fragmento
    diciéndolo**, en vez de quedarse fuera. Es el mismo criterio que aplica
    IT-09 a las asignaturas sin guía: un hueco silencioso hace que el sistema
    responda como si la titulación no existiera, y sí existe.

    Args:
        items: Dataset completo tal como lo exporta el spider.
        tamanos: Objetivo, máximo y mínimo de fragmento.

    Returns:
        Los fragmentos de ficha, de origen ``ficha_titulacion``.
    """
    por_grado: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if item["tipo"] == "asignatura":
            por_grado.setdefault(item["grado"], []).append(item)

    chunks: list[dict[str, Any]] = []
    for grado in sorted(
        (g for g in items if g["tipo"] == "grado"), key=lambda g: g["nombre"]
    ):
        nombre = grado["nombre"]
        titulo = f"Datos generales del {nombre}"
        base = {
            "grados": [nombre],
            "codigos": [None],
            "nombre": titulo,
            "tipo_asignatura": "",
            "curso": "",
        }
        suyas = por_grado.get(nombre, [])
        if not suyas:
            chunks.extend(
                _chunks_de_unidad(
                    f"{titulo}.",
                    "La web de la EPSJ no publica el plan de estudios de esta "
                    "titulación, por lo que no se dispone de sus asignaturas.",
                    base,
                    "ficha_titulacion",
                    tamanos,
                )
            )
            continue

        optativas = [
            a for a in suyas if a["tipo_asignatura"] in _GRUPOS_PLAN["optativas"]
        ]
        obligatorias = [a for a in suyas if a not in optativas]
        cursos = _duracion_en_cursos(suyas)
        frases = [
            f"En total tiene {len(suyas)} asignaturas: {len(obligatorias)} "
            f"obligatorias y {len(optativas)} optativas."
        ]
        if cursos:
            frases.append(f"El plan de estudios se organiza en {cursos} cursos.")
        if not optativas:
            frases.append(
                "La web de la EPSJ no publica optativas para esta titulación."
            )
        reparto = [
            f"{curso}: {len(del_curso)} asignaturas."
            for curso, del_curso in _por_curso(obligatorias)
            if curso
        ]
        cuerpo = " ".join(frases)
        if reparto:
            cuerpo += "\n\nReparto de las obligatorias por curso:\n" + "\n".join(
                reparto
            )
        if optativas:
            cuerpo += (
                f"\n\nLas {len(optativas)} optativas no llevan curso asignado en "
                "el plan que publica la EPSJ."
            )
        chunks.extend(
            _chunks_de_unidad(f"{titulo}.", cuerpo, base, "ficha_titulacion", tamanos)
        )
    return chunks


def _chunks_de_mencion(
    items: list[dict[str, Any]],
    tamanos: tuple[int, int, int],
) -> list[dict[str, Any]]:
    """Genera el listado de asignaturas de cada mención (IT-107).

    La mención viaja como metadato de cada asignatura y aparece en el
    encabezado de su fragmento, pero ninguna unidad reúne las de una misma
    mención. Medido el 17/08/2026: preguntado por las asignaturas de una
    mención concreta de Informática, el sistema contestó que no estaban en el
    contexto. Estaban en el corpus, repartidas en cuatro unidades distintas.

    Los nombres son **los que publica la fuente, sin desarrollar**. Dos de
    Geomática son las siglas «TIA» y «TIG», y el corpus no dice qué significan:
    inventar el desarrollo sería añadir información que la EPSJ no publica.

    Args:
        items: Dataset completo tal como lo exporta el spider.
        tamanos: Objetivo, máximo y mínimo de fragmento.

    Returns:
        Los fragmentos de mención, de origen ``mencion``.
    """
    por_mencion: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in items:
        if item["tipo"] != "asignatura":
            continue
        for mencion in item.get("menciones") or []:
            por_mencion.setdefault((item["grado"], mencion), []).append(item)

    chunks: list[dict[str, Any]] = []
    for grado, mencion in sorted(por_mencion):
        asignaturas = sorted(por_mencion[(grado, mencion)], key=lambda a: a["nombre"])
        titulo = f"Asignaturas de la mención «{mencion}» del {grado}"
        lineas = []
        for a in asignaturas:
            ects = f" ({a['ects']} ECTS)" if a["ects"] else ""
            lineas.append(f"{a['nombre']}{ects}.")
        base = {
            "grados": [grado],
            "codigos": [None],
            "nombre": titulo,
            "tipo_asignatura": "",
            "curso": "",
        }
        chunks.extend(
            _chunks_de_unidad(
                f"{titulo}. En total son {len(asignaturas)}:",
                "\n\n".join(lineas),
                base,
                "mencion",
                tamanos,
            )
        )
    return chunks


def _por_curso(
    asignaturas: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Agrupa un listado por el curso en que se imparte (IT-105).

    Antes el listado se troceaba por tamaño, y salían tercios alfabéticos: las
    cincuenta obligatorias de Informática se partían en tres fragmentos que
    repetían el mismo encabezado «En total son 50» y ninguno decía cuál era.
    Medido el 16/08/2026, el modelo recibió los tres y aun así se dejó diez
    asignaturas sin nombrar, las del tercero.

    Por curso, cada fragmento es una unidad que significa algo por sí sola
    ---«las obligatorias de primer curso»---, cabe entera y además contesta
    directamente la pregunta que un preuniversitario hace de verdad.

    Los grupos salen ordenados por el primer curso que nombra el rótulo, de
    modo que «Tercer o cuarto curso» va donde va tercero. Lo que no lleva curso
    ---las optativas--- va al final, en un grupo propio.

    Args:
        asignaturas: Asignaturas de una misma titulación y un mismo grupo.

    Returns:
        Pares ``(curso, asignaturas)``. El curso es cadena vacía cuando la
        fuente no lo publica.
    """
    grupos: dict[str, list[dict[str, Any]]] = {}
    for a in asignaturas:
        grupos.setdefault((a.get("curso") or "").strip(), []).append(a)

    def orden(curso: str) -> tuple[int, str]:
        if not curso:
            return (99, "")
        for posicion, ordinal in enumerate(ORDEN_CURSOS, start=1):
            if curso.lower().startswith(ordinal):
                return (posicion, curso)
        return (98, curso)

    return [(curso, grupos[curso]) for curso in sorted(grupos, key=orden)]


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

    # IT-101: un doble grado no publica guías propias. Sus asignaturas son, casi
    # todas, las mismas que las de sus dos grados base, pero con códigos de otra
    # serie, así que no se pueden cruzar por código: se cruzan por nombre. En vez
    # de duplicar el temario bajo la titulación doble ---unos 200 fragmentos de
    # contenido idéntico, que además rompería la deduplicación de arriba--- se
    # añade el doble grado a la lista de titulaciones de la unidad que ya existe.
    # El fragmento recuperado dice entonces que esa asignatura se imparte también
    # en el doble grado, sin que el corpus crezca ni un carácter.
    dobles = {
        g["nombre"] for g in items if g["tipo"] == "grado" and g.get("es_doble_grado")
    }
    grupos_por_nombre: dict[str, list[tuple[str, str]]] = {}
    for clave in grupos_guia:
        grupos_por_nombre.setdefault(_normalizar(clave[0]), []).append(clave)
    dobles_por_grupo: dict[tuple[str, str], list[tuple[str, str | None]]] = {}
    atendidas: set[tuple[str, str]] = set()
    ambiguas: list[tuple[str, str]] = []
    for asig_doble in (
        a for a in items if a["tipo"] == "asignatura" and a["grado"] in dobles
    ):
        candidatos = grupos_por_nombre.get(_normalizar(asig_doble["nombre"]), [])
        if not candidatos:
            # El plan del doble grado desambigua algunas asignaturas anotando
            # entre paréntesis el acrónimo del grado del que provienen
            # («GESTIÓN FINANCIERA (GIOI)»). Ese sufijo no forma parte del
            # nombre en el grado base, así que se reintenta sin él: recupera 90
            # de las 98 que quedaban sueltas. Se prueba en segundo lugar para
            # no arriesgar una coincidencia falsa cuando el nombre completo ya
            # casa por sí solo.
            candidatos = grupos_por_nombre.get(
                _normalizar(_SUFIJO_GRADO.sub("", asig_doble["nombre"])), []
            )
        if len(candidatos) != 1:
            # Ni se adivina ni se reparte entre varios: con más de un grupo
            # candidato no se sabe de cuál cuelga, y con ninguno la asignatura
            # es realmente propia del doble grado (los dos TFG). En ambos casos
            # sigue su camino y acaba con su fragmento informativo.
            if candidatos:
                ambiguas.append((asig_doble["grado"], asig_doble["nombre"]))
            continue

        dobles_por_grupo.setdefault(candidatos[0], []).append(
            (asig_doble["grado"], asig_doble["codigo"])
        )
        atendidas.add(
            _clave_asignatura(
                asig_doble["grado"], asig_doble["codigo"], asig_doble["nombre"]
            )
        )

    if ambiguas:
        # Un nombre que casa con varios grupos de guía no se reparte a ojo. Se
        # avisa porque este proyecto ya ha pagado cuatro veces el precio de un
        # dato que se pierde sin decir nada.
        print(
            f"AVISO: {len(ambiguas)} asignaturas de dobles grados con nombre "
            "ambiguo entre varias guías; no se enganchan a ninguna.",
            file=sys.stderr,
        )
        for grado_doble, nombre_asig in ambiguas:
            print(f"   {grado_doble} - {nombre_asig}", file=sys.stderr)

    for (nombre, texto), guias in grupos_guia.items():
        # Orden estable de titulaciones para que el troceo sea determinista.
        guias = sorted(guias, key=lambda g: g["grado"])
        grados = [g["grado"] for g in guias]
        codigos = [g["codigo"] for g in guias]
        # Los dobles grados se añaden DESPUÉS de ordenar y de calcular
        # `guias[0]`: los metadatos del encabezado (ECTS, tipo) tienen que
        # seguir saliendo de una titulación que sí publica la guía.
        for grado_doble, codigo_doble in sorted(
            dobles_por_grupo.get((nombre, texto), [])
        ):
            grados.append(grado_doble)
            codigos.append(codigo_doble)
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
            # IT-105. Se toma de la asignatura del grupo con el mismo criterio
            # que el tipo. Ojo: una guía compartida entre titulaciones puede
            # impartirse en cursos distintos en cada una, así que este valor es
            # el de la primera y no vale para afirmar nada de las demás.
            "curso": (asignatura.get("curso", "") if asignatura else ""),
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
                # aplica al ECTS ausente. Lo mismo con el curso.
                "tipo_asignatura": "",
                "curso": "",
            }
            chunks.extend(
                _chunks_de_unidad(encabezado, item["texto"], base, "salidas", tamanos)
            )

    chunks.extend(_chunks_de_plan_de_estudios(items, tamanos))

    # IT-107: fragmentos derivados que contestan las preguntas de agregación.
    # Mismo argumento que el listado del plan y la misma frontera: todo sale de
    # contar y agrupar lo que la fuente publica. Nada de comparar titulaciones
    # ni de agrupar asignaturas por tema, que serían criterios nuestros metidos
    # en un corpus que se defiende por ser información oficial de la EPSJ.
    chunks.extend(_chunks_de_catalogo(items, tamanos))
    chunks.extend(_chunks_de_ficha(items, tamanos))
    chunks.extend(_chunks_de_mencion(items, tamanos))

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
        # IT-101: las asignaturas de un doble grado que ya se han enganchado a
        # la guía de su grado base no van por aquí. Emitirles un fragmento
        # informativo diciendo que «no tiene guía publicada» sería falso: la
        # tiene, y está en el corpus bajo la titulación simple.
        and _clave_asignatura(a["grado"], a["codigo"], a["nombre"]) not in atendidas
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
            "curso": asignatura.get("curso", ""),
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

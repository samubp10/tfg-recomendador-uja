"""Comprobaciones deterministas de una respuesta generada (IT-35).

Existe para que elegir el modelo generativo deje de depender de la impresión
que deja probarlo a mano. IT-28 e IT-31 comparaban candidatos con un número
sobre una tarea de respuesta conocida; la generación de texto no ofrece eso, y
la salida fácil ---una nota de calidad puesta por quien mira--- no se sostiene
ante un tribunal.

Lo que sí se puede medir sin juez y sin criterio propio es **si lo que la
respuesta nombra existe**. El corpus contiene todos los nombres de titulación y
de asignatura de la EPSJ, así que comprobar una respuesta contra él son
comparaciones de cadena: sin modelo adicional, reproducible y del todo
independiente del modelo que se esté evaluando.

Dos límites que hay que tener presentes al leer estas cifras:

* **No mide si la respuesta es buena**, mide si nombra cosas que existen y si
  nombra las que debía. Una respuesta correcta y sosa puntúa igual que una
  correcta y bien escrita.
* **Solo aplica a las preguntas cuya respuesta se puede calcular** del dataset.
  Sobre un temario no se puede: eso queda fuera del criterio de decisión y se
  reporta aparte.
"""

from __future__ import annotations

import re
from typing import Final, NamedTuple

from tfg_uja.text_cleaner import normalizar, palabras

#: Palabra que puede formar parte del nombre de una titulación, y partículas
#: que la fuente escribe en minúscula dentro de ellos («de Organización», «y
#: Ciberseguridad»).
_MAYUSCULA: Final[str] = r"[A-ZÁÉÍÓÚÑ][\wáéíóúñüÁÉÍÓÚÑÜ]*"
_ENLACE: Final[str] = r"(?:y|e|de|del|la|las|los|con)"

#: Cómo nombra la fuente a una titulación. Sirve para encontrar en una
#: respuesta libre lo que el modelo presenta como titulación, incluso cuando se
#: la ha inventado: no se puede enumerar lo que no existe, pero sí reconocer la
#: forma con la que se escribe.
#:
#: Una partícula solo continúa el nombre si detrás va otra palabra en
#: mayúscula. Sin esa condición el patrón se comía la frase entera: de «el
#: Grado en Ingeniería Geomática es de la rama industrial» extraía «Grado en
#: Ingeniería Geomática e», que no casa con el catálogo y contaba como
#: titulación inventada.
_TITULACION: Final[re.Pattern[str]] = re.compile(
    rf"(?:Doble\s+Grado|Grado)\s+en\s+{_MAYUSCULA}"
    rf"(?:\s+(?:{_ENLACE}\s+)*{_MAYUSCULA})*"
)

#: Marcas con las que un modelo abre un elemento de lista. Se admiten las tres
#: que usan de hecho los candidatos probados: guion, asterisco y numeración.
_VINETA: Final[re.Pattern[str]] = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")

#: Marcas de énfasis de Markdown que los modelos ponen alrededor del nombre.
#: No forman parte de él, pero sí impedían reconocerlo: medido el 18/08/2026,
#: ministral-3:3b y qwen3.5:4b enumeraron **las diez asignaturas correctas** de
#: primer curso de Informática en negrita, y esta función devolvía
#: «**Álgebra**», que no casa con ninguna del corpus. Las dos respuestas, que
#: son perfectas, puntuaban precisión 0,000 y salían las peores de la tabla.
_ENFASIS: Final[re.Pattern[str]] = re.compile(r"[*_`]+")

#: Cola que los listados arrastran detrás del nombre: los créditos, el curso o
#: el tipo. No forma parte del nombre de la asignatura.
#:
#: El guion corto solo separa cuando lleva espacio delante. Pegado a la palabra
#: es parte del nombre, y cortando ahí se partían las dos asignaturas del
#: corpus que lo llevan: «Interacción persona-ordenador» quedaba en
#: «Interacción persona» y «Técnicas de animación 3D y post-procesamiento» en
#: «...y post», ninguna de las dos casaba con el corpus y las dos respuestas,
#: que eran correctas, perdían precisión.
_COLA: Final[re.Pattern[str]] = re.compile(
    r"\s*[(\[–—:,]\s*.*$|\s+-\s*.*$|\s*\d+[.,]?\d*\s*(?:ECTS|cr[ée]ditos).*$",
    re.IGNORECASE,
)

#: Asignatura enumerada **dentro de un párrafo**, reconocida porque el modelo
#: le pone los créditos detrás: «Algoritmos geométricos (6 ECTS), Minería web
#: (6 ECTS)...».
#:
#: Hace falta porque los modelos no siempre usan viñetas. Medido el 17/08/2026:
#: preguntado por las optativas de Informática, mistral-7b enumeró las
#: diecisiete **en prosa separadas por comas**, y un extractor que solo mirase
#: viñetas habría contado cero y puntuado 0,0 una respuesta correcta.
_ENUMERADA: Final[re.Pattern[str]] = re.compile(
    r"([^,;:.()\n]{3,90}?)\s*\(\s*\d+[.,]?\d*\s*(?:ECTS|cr[ée]ditos)[^)]*\)",
    re.IGNORECASE,
)


#: Paréntesis con el que la fuente distingue de qué titulación del doble grado
#: viene una asignatura: «MÁQUINAS TÉRMICAS (GIM)», «CONTROL POR COMPUTADOR
#: (GIEI)». Son 54 de los 316 nombres del corpus, y el mismo mecanismo marca el
#: plan en «Grado en Ingeniería Geomática y Topográfica (plan 2025)».
_CALIFICADOR: Final[re.Pattern[str]] = re.compile(r"\s*\([^)]*\)")

#: Abreviaturas que la fuente usa dentro de un nombre. Son las de los seis
#: trabajos de fin de grado y nada más; se enumeran en vez de resolverlas por
#: regla porque una regla general convertiría cualquier punto en abreviatura.
_ABREVIATURAS: Final[dict[str, str]] = {"ing.": "ingenieria"}

#: Fórmula con la que la fuente antepone el tipo de estudios al nombre de la
#: titulación: «Grado en Ingeniería Eléctrica», «Doble Grado en Ingeniería
#: Eléctrica y Mecánica». Un modelo puede nombrar la titulación sin ella.
_TIPO_DE_ESTUDIOS: Final[re.Pattern[str]] = re.compile(r"^(?:doble\s+)?grado\s+en\s+")


def sin_tipo_de_estudios(nombre: str) -> str:
    """Quita la fórmula «Grado en» del principio de un nombre ya normalizado.

    Args:
        nombre: Nombre pasado antes por :func:`nucleo`.

    Returns:
        El nombre sin la fórmula. Si no la lleva, el nombre tal cual.
    """
    return _TIPO_DE_ESTUDIOS.sub("", nombre)


def nucleo(nombre: str) -> str:
    """Deja un nombre en la forma con la que se puede comparar de verdad.

    Normalizar no basta. El corpus escribe «AUTOMÁTICA AVANZADA (GIEI)» y
    cualquier modelo responde «Automática Avanzada», porque el paréntesis no es
    parte del nombre de la asignatura: es la marca con la que la fuente dice a
    cuál de las dos titulaciones de un doble grado pertenece. Comparando con él
    puesto, **una respuesta perfecta puntúa cero**.

    No es una hipótesis: medido el 18/08/2026, ministral-8b enumeró las diez
    obligatorias de tercer o cuarto curso del Doble Grado en Ingeniería
    Electrónica Industrial y Mecánica, las diez correctas y ninguna de más, y
    la cobertura salía 0,000 con las diez contadas como omitidas.

    Quitar el calificador no confunde asignaturas distintas: comprobado sobre
    el corpus entero, los nombres que colapsan son la misma asignatura con y
    sin sigla ---la que se imparte en el grado simple y en el doble---, y
    dentro de ninguna pregunta del banco colapsan dos respuestas esperadas.

    Args:
        nombre: Nombre tal como lo publica la fuente o como lo escribe el
            modelo.

    Returns:
        El nombre en minúsculas, sin tildes, sin el calificador entre
        paréntesis y con las abreviaturas de la fuente resueltas.
    """
    limpio = normalizar(_CALIFICADOR.sub(" ", nombre))
    return " ".join(_ABREVIATURAS.get(p, p) for p in limpio.split())


def titulaciones_nombradas(respuesta: str) -> set[str]:
    """Titulaciones que la respuesta presenta como tales.

    Args:
        respuesta: Texto tal como lo devuelve el modelo.

    Returns:
        Los nombres encontrados, sin normalizar, tal como aparecen escritos.
    """
    return {" ".join(m.group(0).split()) for m in _TITULACION.finditer(respuesta)}


def titulaciones_inventadas(respuesta: str, catalogo: list[str]) -> set[str]:
    """Titulaciones nombradas que no están en el catálogo del corpus.

    Es el fallo más grave del sistema y el que fija el umbral eliminatorio de
    IT-35: el 16/08/2026 se recomendaron seis titulaciones a un estudiante y
    dos no existen en la EPSJ. Un estudiante no tiene forma de saberlo.

    La comparación es por prefijo normalizado en los dos sentidos, porque una
    respuesta puede recortar el nombre oficial ---«Grado en Ingeniería
    Geomática» por «...y Topográfica (plan 2025)»--- sin estar inventándoselo.
    Recortar no es inventar.

    Y tampoco lo es **abreviar por dentro**. El 19/08/2026 esta comprobación
    retiró una respuesta entera y correcta ---cuatro titulaciones reales
    recomendadas a un estudiante--- porque una de ellas venía escrita «Grado en
    Mecánica»: ningún prefijo casa, pero todas sus palabras están en «Grado en
    Ingeniería Mecánica». Se admite por tanto que las palabras de lo dicho sean
    un subconjunto de las de alguna titulación real.

    El coste de admitirlo es un falso negativo posible: si la Escuela ofreciera
    un doble grado y no el simple que lo compone, el simple pasaría por bueno.
    Se acepta porque los dos errores no son simétricos. Dejar pasar un nombre
    de una titulación que existe en otra combinación despista; retirar una
    recomendación correcta y decirle al estudiante que se ha inventado algo lo
    deja sin respuesta y sin motivo.

    Args:
        respuesta: Texto tal como lo devuelve el modelo.
        catalogo: Titulaciones que declara el índice.

    Returns:
        Las que no casan con ninguna del catálogo.
    """
    reales = [normalizar(t) for t in catalogo]
    en_palabras = [palabras(t) for t in catalogo]
    inventadas = set()
    for nombrada in titulaciones_nombradas(respuesta):
        dicha = normalizar(nombrada)
        if any(r.startswith(dicha) or dicha.startswith(r) for r in reales):
            continue
        if any(palabras(nombrada) <= reales_en for reales_en in en_palabras):
            continue
        inventadas.add(nombrada)
    return inventadas


def elementos_de_lista(respuesta: str) -> list[str]:
    """Nombres que la respuesta presenta como elementos de una enumeración.

    Se reconocen de dos formas, las dos observadas en las sesiones reales: como
    elemento de viñeta, y dentro de un párrafo con los créditos detrás.

    **Lo que la respuesta menciona en prosa corrida y sin créditos no se
    considera enumerado**, y por tanto no entra en la precisión. Es una
    limitación consciente: extraer nombres de prosa libre sin un modelo pediría
    reglas que este corpus no permite fijar, y una regla frágil produciría
    invenciones donde no las hay. Ese modo de fallo se recoge en el recuento
    cualitativo, no en esta métrica.

    Args:
        respuesta: Texto tal como lo devuelve el modelo.

    Returns:
        Los nombres en el orden en que aparecen, sin créditos ni curso.
    """
    elementos = []
    encabezado = ""
    for linea in respuesta.splitlines():
        encabezado = _factoriza(linea) or encabezado
        encontrado = _VINETA.match(linea)
        if not encontrado:
            continue
        crudo = _ENFASIS.sub("", encontrado.group(1)).strip()
        # Una viñeta que termina en dos puntos no enumera: encabeza la sublista
        # que viene debajo. Gemma3 respondió «* Primer curso:» y luego las diez
        # asignaturas, y contar el rótulo como una más daba una invención que
        # no existe. Se mira antes de recortar la cola, que se come el signo.
        if crudo.endswith(":"):
            continue
        nombre = _COLA.sub("", crudo).strip(" .;:")
        if nombre:
            elementos.append(f"{encabezado} {nombre}" if encabezado else nombre)
    if elementos:
        return elementos
    return [
        _desde_la_mayuscula(_ENFASIS.sub("", m.group(1)).strip(" .;:"))
        for m in _ENUMERADA.finditer(respuesta)
    ]


#: Encabezado que **saca el tipo de estudios fuera** de los elementos de la
#: lista: «**Grado en:**» seguido de «Ingeniería Informática», «Ingeniería
#: Mecánica»... No es un capricho de redacción, es lo que hace cualquiera al
#: enumerar doce titulaciones que empiezan igual, y es mejor prosa que repetir
#: la fórmula doce veces.
#:
#: Medido el 20/08/2026: `ministral-8b` enumeró **las doce correctas** así y el
#: cotejo devolvió «12 omitidas, 10 de más», porque comparaba «Ingeniería
#: Informática» contra «Grado en Ingeniería Informática». Precisión y cobertura
#: salían por los suelos en una respuesta perfecta.
#:
#: Solo se reconoce el encabezado que termina en «en:», que es la marca de que
#: lo factorizado es el principio del nombre. «Primer curso:» no la lleva y no
#: se antepone a nada, que es lo correcto: ahí lo factorizado es el curso, no
#: parte del nombre de la asignatura.
_ENCABEZADO_FACTOR: Final[re.Pattern[str]] = re.compile(
    r"^[\s*_#>-]*((?:doble\s+)?grado\s+en)\s*:\s*[*_]*\s*$", re.IGNORECASE
)


def _factoriza(linea: str) -> str:
    """Devuelve el prefijo que esta línea saca fuera de la lista, si lo hace.

    Args:
        linea: Línea de la respuesta, tal cual.

    Returns:
        El prefijo sin los dos puntos, o cadena vacía si la línea no es uno de
        esos encabezados.
    """
    encontrado = _ENCABEZADO_FACTOR.match(linea.strip())
    return encontrado.group(1) if encontrado else ""


def _desde_la_mayuscula(texto: str) -> str:
    """Quita lo que el modelo antepone al nombre al redactar.

    Dentro de un párrafo, el nombre llega precedido de lo que lo introducía:
    «incluyendo Algoritmos geométricos», «y Web semántica y social». En la
    fuente **todo nombre de asignatura empieza por mayúscula**, así que las
    palabras iniciales en minúscula no son parte del nombre.

    Args:
        texto: Nombre tal como se extrajo del párrafo.

    Returns:
        El nombre desde su primera palabra en mayúscula. Si no hay ninguna, el
        texto tal cual: no se puede recortar lo que no se sabe dónde empieza.
    """
    palabras = texto.split()
    for i, palabra in enumerate(palabras):
        if palabra[:1].isupper():
            return " ".join(palabras[i:])
    return texto


def cotejar_listado(
    respuesta: str, esperadas: set[str], del_corpus: set[str]
) -> tuple[float | None, float, set[str], set[str]]:
    """Compara un listado generado con el que dice el dataset.

    Las dos cifras miden cosas distintas y las dos hacen falta: un modelo puede
    no inventarse nada y dejarse la mitad de la lista, que es exactamente lo
    que pasó el 16/08/2026 con las cincuenta obligatorias de Informática.

    **La precisión solo existe si hay algo enumerado.** Cuando la respuesta
    está redactada en prosa, `elementos_de_lista` no extrae ningún nombre y la
    precisión es ``None``, no cero: no se ha encontrado nada falso, se ha
    medido sobre nada. Devolver 0,0 puntuaba con la peor nota posible
    respuestas correctas por el mero hecho de no usar viñetas, y ordenaba a los
    modelos por su estilo de redacción en lugar de por su veracidad. Quien no
    contestó de verdad ya queda retratado por la cobertura, que se mide sobre
    el texto entero y no depende del formato.

    Límite conocido: un nombre oficial formado por dos títulos unidos por un
    punto solo se reconoce entero. «Smart Grids. Redes Eléctricas
    Inteligentes» citada como «Redes Eléctricas Inteligentes» se cuenta como
    inventada aunque exista. Es el único nombre así de todo el corpus, de modo
    que una regla de alias se estaría escribiendo para un caso único.

    Args:
        respuesta: Texto tal como lo devuelve el modelo.
        esperadas: Nombres que el dataset dice que debería enumerar.
        del_corpus: Todos los nombres de asignatura del corpus, para poder
            distinguir «se ha inventado esta» de «ha nombrado una de otra
            titulación».

    Returns:
        ``(precision, cobertura, inventadas, omitidas)``. La precisión es la
        proporción de lo enumerado que existe en el corpus, o ``None`` si la
        respuesta no enumeró nada; la cobertura, la proporción de lo esperado
        que aparece.
    """
    dichas = [nucleo(e) for e in elementos_de_lista(respuesta)]
    esperadas_norm = {nucleo(e) for e in esperadas}
    corpus_norm = {nucleo(e) for e in del_corpus}
    texto = nucleo(respuesta)
    # La fuente escribe «Grado en Ingeniería Eléctrica» y un modelo puede
    # escribir «Ingeniería Eléctrica»: es la misma titulación. Se decide una
    # vez por respuesta, mirando si usa la fórmula, en vez de quitarla
    # siempre; quitarla siempre juntaría el Grado en Ingeniería Mecánica con
    # el Doble Grado en Ingeniería Mecánica (Internacional), que se
    # distinguen justo por ahí una vez retirado el paréntesis.
    con_formula = "grado en" in texto

    def comparable(nombre: str) -> str:
        return nombre if con_formula else sin_tipo_de_estudios(nombre)

    comparables = {comparable(c) for c in corpus_norm}

    def existe(dicha: str) -> bool:
        # Por sufijo, no por igualdad: dentro de un párrafo el nombre arrastra
        # delante lo que lo introducía ---«incluyendo Algoritmos geométricos»---
        # y eso es del modelo redactando, no una asignatura distinta.
        return any(dicha == c or dicha.endswith(" " + c) for c in comparables)

    inventadas = {d for d in dichas if not existe(d)}
    # La cobertura se mide sobre el texto entero y no sobre lo enumerado: da
    # igual si el modelo respondió con viñetas o en prosa, lo que se pregunta
    # es si el nombre está. Así la métrica no premia un formato sobre otro.
    #
    # Se mira además lo enumerado, porque hay una forma de escribir el nombre
    # que no deja rastro en el texto: sacar el tipo de estudios a un encabezado
    # y listar debajo solo lo que cambia. La cadena «grado en ingenieria
    # informatica» no aparece en ninguna parte de esa respuesta, y sin embargo
    # la titulación está nombrada. `elementos_de_lista` ya devuelve el nombre
    # recompuesto; aquí solo hay que hacerle caso.
    enumeradas = {comparable(nucleo(d)) for d in elementos_de_lista(respuesta)}
    aciertos = {
        e
        for e in esperadas_norm
        if comparable(e) in texto or comparable(e) in enumeradas
    }
    precision = (len(dichas) - len(inventadas)) / len(dichas) if dichas else None
    cobertura = len(aciertos) / len(esperadas_norm) if esperadas_norm else 0.0
    return precision, cobertura, inventadas, esperadas_norm - aciertos


# --------------------------------------------------------- atributos de plan

#: Ordinales de curso y de cuatrimestre tal y como los escribe el troceador,
#: mas las formas en las que el modelo generativo los suele reescribir. La
#: clave es el numero; el valor, todo lo que significa ese numero.
_ORDINALES: Final[dict[str, int]] = {
    "primer": 1,
    "primero": 1,
    "1": 1,
    "1o": 1,
    "1er": 1,
    "segundo": 2,
    "2": 2,
    "2o": 2,
    "tercer": 3,
    "tercero": 3,
    "3": 3,
    "3o": 3,
    "cuarto": 4,
    "4": 4,
    "4o": 4,
    # El indicador ordinal masculino, que es como se escribe de verdad en
    # espanol y lo que el modelo produce la mitad de las veces. Sobrevive a
    # `normalizar` ---no es una marca diacritica---, asi que sin estas cuatro
    # entradas «2º cuatrimestre» no casaba con nada y la correccion no llegaba
    # ni a intentarse. La alternancia de `_ORDINAL` va ordenada de mas larga a
    # mas corta, de modo que «2º» gana a «2» y no deja el indicador suelto.
    "1º": 1,
    "2º": 2,
    "3º": 3,
    "4º": 4,
}

#: Como se escribe cada ordinal al corregir. Se usa la forma del troceador,
#: que es la que ya aparece en el corpus.
_ORDINAL_ESCRITO: Final[dict[int, str]] = {
    1: "primer",
    2: "segundo",
    3: "tercer",
    4: "cuarto",
}

_ORDINAL: Final[str] = "|".join(sorted(_ORDINALES, key=len, reverse=True))

#: «Se imparte en el primer cuatrimestre de tercer curso», que es como lo
#: escribe `chunker._situacion_en_el_plan`. El curso puede faltar.
_SITUACION: Final[re.Pattern[str]] = re.compile(
    rf"\bse imparte en el ({_ORDINAL})\s+cuatrimestre"
    rf"(?:\s+de\s+({_ORDINAL})\s+curso)?",
    re.IGNORECASE,
)

#: «Se imparte en el tercer curso», cuando la fuente no publica cuatrimestre.
_SITUACION_SOLO_CURSO: Final[re.Pattern[str]] = re.compile(
    rf"\bse imparte en el ({_ORDINAL})\s+curso\b", re.IGNORECASE
)

#: «de 6 ECTS», que es como lo escribe el encabezado del troceador.
_ECTS_CONTEXTO: Final[re.Pattern[str]] = re.compile(
    r"\bde\s+(\d+(?:[.,]\d+)?)\s+ECTS\b", re.IGNORECASE
)

#: Marca que el troceador pone cuando una unidad se imparte en mas de una
#: titulacion: «impartida en 4 titulaciones: ...». Es la senal de que la frase
#: «Se imparte en...» que viene detras vale para UNA de ellas y no se sabe cual.
_UNIDAD_COMPARTIDA: Final[re.Pattern[str]] = re.compile(
    r"\bimpartida en \d+ titulaciones\b", re.IGNORECASE
)

#: El nombre de la unidad, entre comillas angulares, al principio del
#: encabezado. Es lo que ata los atributos a una asignatura y no a otra.
_NOMBRE_ENCABEZADO: Final[re.Pattern[str]] = re.compile(r"^\s*[«\"]([^»\"]+)[»\"]")

#: Como nombra el modelo una asignatura al responder: entre comillas de
#: cualquier tipo o en negrita de Markdown.
_MENCION: Final[re.Pattern[str]] = re.compile(
    r"\*\*([^*\n]+?)\*\*|[«\"\u201c]([^»\"\u201d\n]+)[»\"\u201d]"
)

#: Lo que el modelo afirma sobre el cuatrimestre de una asignatura. Mas suelto
#: que la plantilla del corpus porque el modelo parafrasea: «se imparte en el
#: segundo cuatrimestre», «(2º cuatrimestre)», «del primer cuatrimestre».
_AFIRMA_CUATRIMESTRE: Final[re.Pattern[str]] = re.compile(
    rf"\b({_ORDINAL})\s+cuatrimestre\b", re.IGNORECASE
)

#: Lo mismo para el curso.
_AFIRMA_CURSO: Final[re.Pattern[str]] = re.compile(
    rf"\b({_ORDINAL})\s+curso\b", re.IGNORECASE
)

#: Y para los creditos, que el modelo escribe con «ECTS» o con «creditos».
_AFIRMA_ECTS: Final[re.Pattern[str]] = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(?:ECTS|cr[eé]ditos?)\b", re.IGNORECASE
)


class Atributos(NamedTuple):
    """Lo que el contexto dice de una asignatura, o ``None`` si no lo dice.

    Attributes:
        cuatrimestre: 1 o 2, o ``None`` si el fragmento no lo enuncia.
        curso: De 1 a 4, o ``None``.
        ects: Creditos tal y como vienen escritos, o ``None``.
    """

    cuatrimestre: int | None = None
    curso: int | None = None
    ects: str | None = None


def atributos_del_contexto(textos: list[str]) -> dict[str, Atributos]:
    """Saca de los fragmentos lo que dicen del plan de cada asignatura.

    Se leen los fragmentos y no ``grados.json`` a proposito. Lo que interesa
    comprobar es la **fidelidad al contexto**: si la respuesta contradice algo
    que estaba escrito, con esas palabras, en lo que se le entrego al modelo.
    Cotejar contra el dataset mediria otra cosa ---si el sistema acierta---, y
    ademas obligaria a este modulo a abrir un fichero, cuando hasta ahora solo
    compara cadenas.

    Se aprovecha que el encabezado lo redacta ``chunker`` con una plantilla:
    «Fotogrametria y teledeteccion III», asignatura obligatoria de 6 ECTS del
    Grado en... Se imparte en el primer cuatrimestre de tercer curso. Al ser
    texto generado y no prosa de la fuente, se puede leer sin ambiguedad.

    Args:
        textos: Textos de los fragmentos entregados al modelo.

    **Una unidad compartida no suministra el valor, pero si lo contradice.** Son
    dos reglas y hacen falta las dos:

    * La unidad compartida enuncia un solo curso para varias titulaciones y no
      siempre coinciden ---medido: el curso cambia segun la titulacion en 26
      asignaturas, el cuatrimestre en 2 y los ECTS en 1---, asi que no puede
      ser la fuente del dato.
    * Pero tiene que poder vetarlo, porque **dos asignaturas distintas pueden
      llamarse igual**: hay una «Electronica digital» de 9 ECTS en Electronica
      Industrial y otra de 6 en Informatica y en IAyC. Mirando solo las
      unidades propias sobreviviria la de 9 y se reescribirian a 9 los 6
      correctos.

    Es la misma leccion que la clave de deduplicacion del troceador: el nombre
    a solas no identifica una asignatura.

    Returns:
        Nombre normalizado de la asignatura -> lo que el contexto afirma. Si
        dos fragmentos discrepan sobre una asignatura, se descarta: un
        contexto que se contradice a si mismo no puede corregir a nadie.
    """
    # `dichos` recoge lo que dice CUALQUIER unidad; `propios`, solo lo que
    # dicen las de una sola titulacion. La diferencia entre los dos es lo que
    # hace segura la correccion, y se explica arriba.
    dichos: dict[str, set[Atributos]] = {}
    propios: dict[str, set[Atributos]] = {}
    for texto in textos:
        cabeza = _NOMBRE_ENCABEZADO.match(texto)
        if not cabeza:
            continue
        primera = texto.split("\n", 1)[0]
        compartida = bool(_UNIDAD_COMPARTIDA.search(primera))
        nombre = normalizar(cabeza.group(1))

        cuatrimestre = curso = None
        situacion = _SITUACION.search(primera)
        if situacion:
            cuatrimestre = _ORDINALES[normalizar(situacion.group(1))]
            if situacion.group(2):
                curso = _ORDINALES[normalizar(situacion.group(2))]
        else:
            solo_curso = _SITUACION_SOLO_CURSO.search(primera)
            if solo_curso:
                curso = _ORDINALES[normalizar(solo_curso.group(1))]

        creditos = _ECTS_CONTEXTO.search(primera)
        atributos = Atributos(
            cuatrimestre, curso, creditos.group(1) if creditos else None
        )
        if atributos == Atributos():
            continue
        dichos.setdefault(nombre, set()).add(atributos)
        if not compartida:
            propios.setdefault(nombre, set()).add(atributos)

    return {
        nombre: next(iter(unico))
        for nombre, unico in propios.items()
        if len(unico) == 1 and len(dichos[nombre]) == 1
    }


def _sin_adornos(nombre: str) -> str:
    """Deja el nombre de una asignatura como para poder compararlo.

    El modelo no lo escribe pelado: lo envuelve en negrita y le cuelga lo que
    haga falta ---«**Fotogrametria y teledeteccion III (6 ECTS):**»---. Sin
    quitar el calificador entre parentesis y los dos puntos finales, el nombre
    no casa con el del contexto y la comprobacion no llega ni a intentarse.

    Args:
        nombre: Lo que el modelo escribio entre comillas o en negrita.

    Returns:
        El nombre normalizado, sin calificadores ni puntuacion de cierre.
    """
    return normalizar(_CALIFICADOR.sub("", nombre).strip(" :.,;-"))


def asignatura_del_segmento(
    segmento: str, atributos: dict[str, Atributos]
) -> str | None:
    """De que asignatura habla un segmento, si habla de una sola.

    Con dos o mas nombres no se devuelve ninguno, y eso es deliberado: el error
    que se persigue nace precisamente de mezclar asignaturas de nombre casi
    igual, asi que atribuir a ciegas seria repetirlo desde el otro lado. Ante
    la duda no se corrige nada.

    Es publica porque quien emite la respuesta por partes necesita saber de que
    asignatura se venia hablando: parte el texto en frases antes de que llegue
    aqui, y sin ese dato la frase que lleva el atributo no sabe a quien se lo
    esta atribuyendo. Ver el argumento entero en :func:`corregir_atributos`.

    Args:
        segmento: Un trozo de la respuesta.
        atributos: Lo que el contexto dice de cada asignatura.

    Returns:
        El nombre normalizado, o ``None`` si hay cero o mas de uno.
    """
    nombrados = {
        _sin_adornos(m.group(1) or m.group(2)) for m in _MENCION.finditer(segmento)
    }
    # Y la forma mas comun de todas, que no lleva ningun adorno: la asignatura
    # como elemento de lista. Se reutiliza la vineta que ya reconoce
    # `elementos_de_lista`, para que las dos comprobaciones entiendan por
    # «elemento» exactamente lo mismo.
    vineta = _VINETA.match(segmento)
    if vineta:
        crudo = _ENFASIS.sub("", vineta.group(1)).strip()
        # Una vineta terminada en dos puntos encabeza la sublista de debajo, no
        # enumera: «* Primer curso:» no es una asignatura.
        if not crudo.endswith(":"):
            nombrados.add(_sin_adornos(_COLA.sub("", crudo)))
    conocidos = {n for n in nombrados if n in atributos}
    if len(conocidos) != 1:
        return None
    return conocidos.pop()


def _corrige_ordinal(
    segmento: str,
    patron: re.Pattern[str],
    esperado: int | None,
    sustantivo: str,
    asignatura: str,
    avisos: list[str],
) -> str:
    """Reescribe un ordinal que contradiga al contexto."""
    if esperado is None:
        return segmento

    def cambia(m: re.Match[str]) -> str:
        dicho = _ORDINALES[normalizar(m.group(1))]
        if dicho == esperado:
            return m.group(0)
        avisos.append(
            f"«{asignatura}»: el contexto dice {_ORDINAL_ESCRITO[esperado]} "
            f"{sustantivo} y la respuesta decia {_ORDINAL_ESCRITO.get(dicho, dicho)}"
        )
        return f"{_ORDINAL_ESCRITO[esperado]} {sustantivo}"

    return patron.sub(cambia, segmento)


def corregir_atributos(
    texto: str, atributos: dict[str, Atributos], sujeto: str | None = None
) -> tuple[str, list[str]]:
    """Devuelve el texto con curso, cuatrimestre y ECTS puestos al del contexto.

    Es la respuesta a un fallo real: preguntado por Topografia, el sistema dijo
    que «Fotogrametria y teledeteccion III se imparte en el segundo
    cuatrimestre» cuando su fragmento decia, con esas palabras, «primer
    cuatrimestre». La asignatura existia, los creditos eran correctos y las
    tres barreras de dominio la dejaron pasar, porque **comprueban identidades
    y no afirmaciones**: lo unico falso era un atributo.

    No hay ningun modelo juzgando a otro. Los tres atributos existen como dato
    estructurado y el encabezado del fragmento los enuncia con una plantilla,
    asi que la comprobacion es una comparacion de cadenas.

    Se corrige por segmentos, y solo cuando el segmento nombra **una sola**
    asignatura conocida. Un segmento que mezcle dos se deja intacto: el defecto
    nace de confundir asignaturas casi homonimas y arriesgarse a atribuir mal
    seria cometerlo al reves.

    **El segmento es la linea, no la frase, y eso obliga a ``sujeto``.** Quien
    emite la respuesta por partes la corta antes en frases (ADR-0006), asi que
    el nombre puede llegar en una llamada y el atributo en la siguiente. Medido
    con «Automatica avanzada», que el contexto situa en el segundo cuatrimestre:
    escrito «**Automatica avanzada** (6 ECTS) se imparte en el primer
    cuatrimestre.» se corregia, y escrito con un punto en medio ---dos frases,
    que es como se enumera en vinetas--- pasaba **sin corregir y sin aviso**,
    porque la segunda frase no nombra a nadie. Con ``sujeto`` la asignatura de
    la que se venia hablando sigue en pie hasta que la linea se cierra.

    Args:
        texto: Lo que ha redactado el modelo.
        atributos: Lo que dice el contexto, de :func:`atributos_del_contexto`.
        sujeto: Asignatura de la que venia hablando la linea, cuando este texto
            es la continuacion de un trozo anterior. Solo se aplica al primer
            segmento: a partir del primer salto de linea empieza una viñeta
            nueva, y arrastrar el sujeto ahi atribuiria a una asignatura lo que
            se dice de la siguiente.

    Returns:
        ``(texto corregido, avisos)``. Los avisos describen cada cambio, para
        que quede registrado que se corrigio y por que.
    """
    if not atributos:
        return texto, []

    avisos: list[str] = []
    corregidos = []
    for posicion, segmento in enumerate(texto.split("\n")):
        nombre = asignatura_del_segmento(segmento, atributos)
        if nombre is None and posicion == 0 and sujeto in atributos:
            nombre = sujeto
        if nombre is None:
            corregidos.append(segmento)
            continue
        dice = atributos[nombre]
        segmento = _corrige_ordinal(
            segmento,
            _AFIRMA_CUATRIMESTRE,
            dice.cuatrimestre,
            "cuatrimestre",
            nombre,
            avisos,
        )
        segmento = _corrige_ordinal(
            segmento,
            _AFIRMA_CURSO,
            dice.curso,
            "curso",
            nombre,
            avisos,
        )
        if dice.ects is not None:

            def cambia_ects(m: re.Match[str], esperado: str = dice.ects) -> str:
                if m.group(1).replace(",", ".") == esperado.replace(",", "."):
                    return m.group(0)
                avisos.append(
                    f"«{nombre}»: el contexto dice {esperado} ECTS y la "
                    f"respuesta decia {m.group(1)}"
                )
                return m.group(0).replace(m.group(1), esperado, 1)

            segmento = _AFIRMA_ECTS.sub(cambia_ects, segmento)
        corregidos.append(segmento)

    return "\n".join(corregidos), avisos

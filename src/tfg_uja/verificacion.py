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
from typing import Final

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
    for linea in respuesta.splitlines():
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
            elementos.append(nombre)
    if elementos:
        return elementos
    return [
        _desde_la_mayuscula(_ENFASIS.sub("", m.group(1)).strip(" .;:"))
        for m in _ENUMERADA.finditer(respuesta)
    ]


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
) -> tuple[float, float, set[str], set[str]]:
    """Compara un listado generado con el que dice el dataset.

    Las dos cifras miden cosas distintas y las dos hacen falta: un modelo puede
    no inventarse nada y dejarse la mitad de la lista, que es exactamente lo
    que pasó el 16/08/2026 con las cincuenta obligatorias de Informática.

    Args:
        respuesta: Texto tal como lo devuelve el modelo.
        esperadas: Nombres que el dataset dice que debería enumerar.
        del_corpus: Todos los nombres de asignatura del corpus, para poder
            distinguir «se ha inventado esta» de «ha nombrado una de otra
            titulación».

    Returns:
        ``(precision, cobertura, inventadas, omitidas)``. La precisión es la
        proporción de lo enumerado que existe en el corpus; la cobertura, la
        proporción de lo esperado que aparece. Sin elementos enumerados la
        precisión es 0,0: no haber dicho nada no es haber acertado.
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
    aciertos = {e for e in esperadas_norm if comparable(e) in texto}
    precision = (len(dichas) - len(inventadas)) / len(dichas) if dichas else 0.0
    cobertura = len(aciertos) / len(esperadas_norm) if esperadas_norm else 0.0
    return precision, cobertura, inventadas, esperadas_norm - aciertos

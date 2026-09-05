"""Comprobaciones deterministas de una respuesta generada (IT-35)."""

from __future__ import annotations

import re
from typing import Final, NamedTuple

from tfg_uja.text_cleaner import normalizar, palabras

#: Palabra que puede formar parte del nombre de una titulación, y partículas
#: que la fuente escribe en minúscula dentro de ellos («de Organización», «y
#: Ciberseguridad»).
_MAYUSCULA: Final[str] = r"[A-ZÁÉÍÓÚÑ][\wáéíóúñüÁÉÍÓÚÑÜ]*"
_ENLACE: Final[str] = r"(?:y|e|de|del|la|las|los|con)"

# Reconoce la forma de los nombres de titulación, incluso si no existen.

# Una partícula continúa el nombre solo si la siguiente palabra empieza en mayúscula.
_TITULACION: Final[re.Pattern[str]] = re.compile(
    rf"(?:Doble\s+Grado|Grado)\s+en\s+{_MAYUSCULA}"
    rf"(?:\s+(?:{_ENLACE}\s+)*{_MAYUSCULA})*"
)

#: Marcas con las que un modelo abre un elemento de lista. Se admiten las tres
#: que usan de hecho los candidatos probados: guion, asterisco y numeración.
_VINETA: Final[re.Pattern[str]] = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")

# El énfasis Markdown no forma parte del nombre de una asignatura.
_ENFASIS: Final[re.Pattern[str]] = re.compile(r"[*_`]+")

#: Cola que los listados arrastran detrás del nombre: los créditos, el curso o
#: el tipo. No forma parte del nombre de la asignatura.

# El guion pegado pertenece al nombre, como en «Interacción persona-ordenador».
_COLA: Final[re.Pattern[str]] = re.compile(
    r"\s*[(\[–—:,]\s*.*$|\s+-\s*.*$|\s*\d+[.,]?\d*\s*(?:ECTS|cr[ée]ditos).*$",
    re.IGNORECASE,
)

#: Asignatura enumerada dentro de un párrafo, reconocida porque el modelo
#: le pone los créditos detrás: «Algoritmos geométricos (6 ECTS), Minería web
#: (6 ECTS)...».

# Admite enumeraciones en prosa separadas por comas, además de viñetas.
_ENUMERADA: Final[re.Pattern[str]] = re.compile(
    r"([^,;:.()\n]{3,90}?)\s*\(\s*\d+[.,]?\d*\s*(?:ECTS|cr[ée]ditos)[^)]*\)",
    re.IGNORECASE,
)


# El paréntesis distingue el grado base o la versión del plan.
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
    """Quita la fórmula «Grado en» del principio de un nombre ya normalizado."""
    return _TIPO_DE_ESTUDIOS.sub("", nombre)


def nucleo(nombre: str) -> str:
    """Deja un nombre en la forma con la que se puede comparar de verdad."""
    limpio = normalizar(_CALIFICADOR.sub(" ", nombre))
    return " ".join(_ABREVIATURAS.get(p, p) for p in limpio.split())


def titulaciones_nombradas(respuesta: str) -> set[str]:
    """Titulaciones que la respuesta presenta como tales."""
    return {" ".join(m.group(0).split()) for m in _TITULACION.finditer(respuesta)}


def titulaciones_inventadas(respuesta: str, catalogo: list[str]) -> set[str]:
    """Titulaciones nombradas que no están en el catálogo del corpus."""
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
    """Nombres que la respuesta presenta como elementos de una enumeración."""
    elementos = []
    encabezado = ""
    for linea in respuesta.splitlines():
        encabezado = _factoriza(linea) or encabezado
        encontrado = _VINETA.match(linea)
        if not encontrado:
            continue
        crudo = _ENFASIS.sub("", encontrado.group(1)).strip()
        # Un rótulo terminado en dos puntos no es un elemento; compruébalo antes de
        # recortar.
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


# Recompone nombres cuyo prefijo común está en un encabezado «Grado en:».

# Sin recomponer el prefijo, las titulaciones correctas contarían como omitidas.

# Solo «en:» factoriza el nombre; «Primer curso:» no se antepone a las asignaturas.
_ENCABEZADO_FACTOR: Final[re.Pattern[str]] = re.compile(
    r"^[\s*_#>-]*((?:doble\s+)?grado\s+en)\s*:\s*[*_]*\s*$", re.IGNORECASE
)


def _factoriza(linea: str) -> str:
    """Devuelve el prefijo que esta línea saca fuera de la lista, si lo hace."""
    encontrado = _ENCABEZADO_FACTOR.match(linea.strip())
    return encontrado.group(1) if encontrado else ""


def _desde_la_mayuscula(texto: str) -> str:
    """Quita lo que el modelo antepone al nombre al redactar."""
    palabras = texto.split()
    for i, palabra in enumerate(palabras):
        if palabra[:1].isupper():
            return " ".join(palabras[i:])
    return texto


def cotejar_listado(
    respuesta: str, esperadas: set[str], del_corpus: set[str]
) -> tuple[float | None, float, set[str], set[str]]:
    """Compara un listado generado con el que dice el dataset."""
    dichas = [nucleo(e) for e in elementos_de_lista(respuesta)]
    esperadas_norm = {nucleo(e) for e in esperadas}
    corpus_norm = {nucleo(e) for e in del_corpus}
    texto = nucleo(respuesta)
    # Adapta el prefijo al formato de la respuesta sin confundir grados simples con
    # dobles.
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
    # Busca en el texto completo y en los elementos recompuestos para admitir prosa y
    # encabezados comunes.
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
    # Reconoce «2º» antes que «2» para no dejar el indicador ordinal sin consumir.
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
    """Lo que el contexto dice de una asignatura, o ``None`` si no lo dice."""

    cuatrimestre: int | None = None
    curso: int | None = None
    ects: str | None = None


def atributos_del_contexto(textos: list[str]) -> dict[str, Atributos]:
    """Saca de los fragmentos lo que dicen del plan de cada asignatura."""
    # Solo corrige datos inequívocos respaldados por una unidad no compartida.
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
    """Deja el nombre de una asignatura como para poder compararlo."""
    return normalizar(_CALIFICADOR.sub("", nombre).strip(" :.,;-"))


def asignatura_del_segmento(
    segmento: str, atributos: dict[str, Atributos]
) -> str | None:
    """De que asignatura habla un segmento, si habla de una sola."""
    nombrados = {
        _sin_adornos(m.group(1) or m.group(2)) for m in _MENCION.finditer(segmento)
    }
    # Reutiliza el reconocimiento de viñetas para identificar asignaturas sin énfasis.
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
    """Devuelve el texto con curso, cuatrimestre y ECTS puestos al del contexto."""
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

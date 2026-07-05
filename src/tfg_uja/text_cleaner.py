"""Funciones de limpieza y normalización de texto extraído de las guías."""
from __future__ import annotations

import re
import urllib.parse

_ESPACIO_DURO = "\xa0"
_ANCHO_CERO = "\u200b"

#: Marca de asignatura no ofertada, añadida al final del nombre (por ejemplo,
#: "Métodos cuantitativos avanzados (No ofertada en 2025/26)"). El patrón es
#: genérico respecto al curso (no fija ningún año) y al género gramatical, pero
#: reconoce solo la fórmula observada ("no ofertad{a,o} ..."), para no capturar
#: paréntesis legítimos. Otras redacciones futuras se añadirían con evidencia.
_NO_OFERTADA: re.Pattern[str] = re.compile(r"\s*\(\s*no\s+ofertad[ao][^)]*\)\s*$", re.IGNORECASE)


def limpiar_texto(texto: str | None) -> str:
    """Normaliza espacios, saltos y caracteres residuales de un texto.

    Args:
        texto: Texto en crudo extraído del HTML, o None.

    Returns:
        El texto limpio; cadena vacía si la entrada es None o vacía.
    """
    if not texto:
        return ""
    texto = texto.replace(_ESPACIO_DURO, " ").replace(_ANCHO_CERO, "")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def reparar_url(url: str | None, base: str | None = None) -> str:
    """Repara y normaliza una URL relativa o mal formada."""
    if not url:
        return ""
    indice = url.find(".html")
    if indice != -1:
        url = url[: indice + len(".html")]
    if base:
        url = urllib.parse.urljoin(base, url)
    return url


def quitar_nota_al_pie(nombre: str | None) -> str:
    """Elimina el marcador de nota al pie del nombre de una asignatura.

    En las tablas de asignaturas, algunos nombres arrastran un asterisco
    final que remite a una nota al pie de la tabla (por ejemplo,
    "Prácticas externas *"). Ese asterisco no forma parte del nombre de la
    asignatura, por lo que se retira. Los asteriscos que no estén al final
    del texto no se tocan.

    Args:
        nombre: Nombre de la asignatura, ya limpio, o None.

    Returns:
        Nombre sin el asterisco final ni los espacios que lo rodean. 
        Cadena vacía si la entrada es None o vacía.
    """
    if not nombre:
        return nombre
    return re.sub(r"\s*\*+\s*$", "", nombre).strip()


def separar_oferta(nombre: str | None) -> tuple[str, bool]:
    """Separa del nombre la marca de asignatura no ofertada.

    Algunas asignaturas (optativas que no se imparten en el curso) llevan al
    final del nombre el estado "(No ofertada en 2025/26)". Ese estado no es
    parte del nombre, sino un dato aparte, por lo que se extrae a un valor
    booleano y se devuelve el nombre limpio. El patrón no depende de un año
    concreto, de modo que sigue funcionando en cursos posteriores.

    El valor devuelto es relativo al curso rastreado: una asignatura no
    ofertada este curso puede volver a ofertarse en otro, por lo que este
    dato debe interpretarse como una foto del momento de la extracción.

    Args:
        nombre: Nombre de la asignatura, ya limpio de espacios, o None.

    Returns:
        Una tupla con el nombre sin la marca y un booleano (``True`` si la 
        asignatura se oferta, ``False`` si lleva la marca de no ofertada).
    """
    if not nombre:
        return "", True
    if _NO_OFERTADA.search(nombre):
        return _NO_OFERTADA.sub("", nombre).strip(), False
    return nombre, True

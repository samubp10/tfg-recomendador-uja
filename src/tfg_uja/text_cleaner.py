"""Utilidades para limpiar texto y URLs extraídos de las páginas de la EPSJ.

La web publica el contenido con ruido que no aporta significado: espacios
duros, caracteres de ancho cero y, en el caso de las guías docentes, URLs
con el sufijo ".html" duplicado por un error de generación del propio sitio.
"""

from __future__ import annotations

import re
from typing import Final

_ESPACIO_DURO = "\xa0"
_ANCHO_CERO: Final[str] = "\u200b"


def limpiar_texto(texto: str | None) -> str:
    """Normaliza un texto extraído de la web.

    Sustituye los espacios duros por espacios normales, elimina los
    caracteres de ancho cero y colapsa los espacios múltiples y los saltos
    de línea en uno solo.

    Args:
        texto (str): Texto tal como se extrajo del HTML.

    Returns:
        str: Texto normalizado, sin espacios sobrantes al principio ni al
            final.
    """
    if not texto:
        return ""
    texto = texto.replace(_ESPACIO_DURO, " ").replace(_ANCHO_CERO, "")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def reparar_url(url: str | None) -> str | None:
    """Repara una URL de guía docente con el sufijo ".html" duplicado.

    Se ha observado que algunas URLs del catálogo de guías docentes
    incluyen contenido sobrante después de la extensión ".html" (por
    ejemplo, "...es.htmles.html" o "...es.html13312025_es.html"). Al no
    existir ningún caso legítimo con contenido útil tras el primer
    ".html", se trunca la URL en ese punto.

    Args:
        url (str): URL tal como se extrajo del HTML.

    Returns:
        str: URL reparada, o la URL original si no contiene ".html".
    """
    if not url:
        return url
    indice = url.find(".html")
    if indice == -1:
        return url
    return url[: indice + len(".html")]


def quitar_nota_al_pie(nombre: str | None) -> str | None:
    """Elimina el marcador de nota al pie del nombre de una asignatura.

    En las tablas de asignaturas, algunos nombres arrastran un asterisco
    final que remite a una nota al pie de la tabla (por ejemplo,
    "Prácticas externas *"). Ese asterisco no forma parte del nombre de la
    asignatura, por lo que se retira. Los asteriscos que no estén al final
    del texto no se tocan.

    Args:
        nombre (str): Nombre de la asignatura, ya limpio.

    Returns:
        str: Nombre sin el asterisco final ni los espacios que lo rodean.
    """
    if not nombre:
        return nombre
    return re.sub(r"\s*\*+\s*$", "", nombre).strip()


#: Marca de asignatura no ofertada, añadida al final del nombre (por ejemplo,
#: "Métodos cuantitativos avanzados (No ofertada en 2025/26)"). El patrón es
#: genérico respecto al curso (no fija ningún año) y al género gramatical, pero
#: reconoce solo la fórmula observada ("no ofertad{a,o} ..."), para no capturar
#: paréntesis legítimos. Otras redacciones futuras se añadirían con evidencia.
_NO_OFERTADA: Final[re.Pattern[str]] = re.compile(
    r"\s*\(\s*no\s+ofertad[ao][^)]*\)\s*$", re.IGNORECASE
)


def separar_oferta(nombre: str | None) -> tuple[str | None, bool]:
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
        nombre (str): Nombre de la asignatura, ya limpio de espacios.

    Returns:
        tuple[str, bool]: El nombre sin la marca y ``True`` si la asignatura
            se oferta, ``False`` si lleva la marca de no ofertada.
    """
    if not nombre:
        return nombre, True
    if _NO_OFERTADA.search(nombre):
        return _NO_OFERTADA.sub("", nombre).strip(), False
    return nombre, True

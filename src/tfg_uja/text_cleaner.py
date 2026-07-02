"""Utilidades para limpiar texto y URLs extraídos de las páginas de la EPSJ.

La web publica el contenido con ruido que no aporta significado: espacios
duros, caracteres de ancho cero y, en el caso de las guías docentes, URLs
con el sufijo ".html" duplicado por un error de generación del propio sitio.
"""

import re

_ESPACIO_DURO = "\xa0"
_ANCHO_CERO = "\u200b"


def limpiar_texto(texto):
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


def reparar_url(url):
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


def quitar_nota_al_pie(nombre):
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

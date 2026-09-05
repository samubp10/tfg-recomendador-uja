"""Utilidades para limpiar texto y URLs extraídos de las páginas de la EPSJ."""

from __future__ import annotations

import re
import unicodedata
from typing import Final

_ESPACIO_DURO = "\xa0"
_ANCHO_CERO: Final[str] = "\u200b"


def normalizar(texto: str) -> str:
    """Normaliza texto libre con NFD; conserva símbolos y colapsa espacios."""
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    limpio = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    return " ".join(limpio.split())


def normalizar_rotulo(texto: str) -> str:
    """Normaliza rótulos con NFKD y ASCII, colapsando espacios interiores.

    A diferencia de ``normalizar``, descarta caracteres sin equivalente ASCII.
    IT-137 sustituyó los dos ``_normalizar``: el del fragmentador colapsaba
    espacios interiores y el del spider solo recortaba extremos. No eran
    intercambiables en general; se unificaron tras contrastar los usos reales.
    """
    sin_tildes = (
        unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    )
    return " ".join(sin_tildes.split()).lower()


def palabras(texto: str) -> set[str]:
    """Descompone un texto en el conjunto de sus palabras comparables."""
    return {
        limpia
        for palabra in normalizar(texto).split()
        if (limpia := "".join(c for c in palabra if c.isalnum()))
    }


def limpiar_texto(texto: str | None) -> str:
    """Normaliza un texto extraído de la web."""
    if not texto:
        return ""
    texto = texto.replace(_ESPACIO_DURO, " ").replace(_ANCHO_CERO, "")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def reparar_url(url: str | None) -> str | None:
    """Repara una URL de guía docente con el sufijo ".html" duplicado."""
    if not url:
        return url
    indice = url.find(".html")
    if indice == -1:
        return url
    return url[: indice + len(".html")]


def quitar_nota_al_pie(nombre: str | None) -> str | None:
    """Elimina el marcador de nota al pie del nombre de una asignatura."""
    if not nombre:
        return nombre
    return re.sub(r"\s*\*+\s*$", "", nombre).strip()


# Reconoce la nota de no ofertada sin fijar el curso ni confundir otros paréntesis.
_NO_OFERTADA: Final[re.Pattern[str]] = re.compile(
    r"\s*\(\s*no\s+ofertad[ao][^)]*\)\s*$", re.IGNORECASE
)


def separar_oferta(nombre: str | None) -> tuple[str | None, bool]:
    """Separa del nombre la marca de asignatura no ofertada."""
    if not nombre:
        return nombre, True
    if _NO_OFERTADA.search(nombre):
        return _NO_OFERTADA.sub("", nombre).strip(), False
    return nombre, True

"""Extracción de guías docentes servidas en PDF (IT-67)."""

from __future__ import annotations

import io
import logging
import re
from functools import lru_cache
from typing import Final

from pypdf import PdfReader

from tfg_uja.text_cleaner import limpiar_texto

# pypdf avisa por su cuenta ("invalid pdf header", "EOF marker not found")
# antes de lanzar la excepción que sí se captura más abajo; se silencia su
# logger para que un PDF corrupto no ensucie la salida del rastreo.
logging.getLogger("pypdf").setLevel(logging.ERROR)

#: Rótulos que la plantilla de la UJA trae en TODAS las guías: medidos sobre
#: 293 guías rastreadas, estos trece aparecen en las 293.
_ROTULOS_ESPERADOS: Final[frozenset[str]] = frozenset(
    {
        "FICHA IDENTIFICATIVA",
        "PROFESORADO",
        "RESUMEN",
        "COMPETENCIAS / RESULTADOS DEL PROCESO DE FORMACIÓN Y APRENDIZAJE",
        "DESCRIPCIÓN DE CONTENIDOS",
        "METODOLOGÍAS DOCENTES Y ACTIVIDADES FORMATIVAS",
        "SISTEMAS DE EVALUACIÓN",
        "BIBLIOGRAFÍA",
        "OBJETIVOS DE DESARROLLO SOSTENIBLE",
        "ESTUDIANTADO CON NECESIDADES ESPECÍFICAS DE APOYO EDUCATIVO",
        "PLAN DE CONTINGENCIA",
        "CLÁUSULAS",
        "COMPROMISO CON LA IGUALDAD Y LA PERSPECTIVA DE GÉNERO",
    }
)

# Los rótulos de sección delimitan el contenido; los títulos de temas se conservan.

# Todo rótulo obligatorio también delimita una sección.

# Las variantes opcionales sirven de frontera, pero no se exigen a cada guía.
_ROTULOS_SECCION: Final[frozenset[str]] = _ROTULOS_ESPERADOS | frozenset(
    {
        "COMPETENCIAS",
        "RESULTADOS DE APRENDIZAJE",
        "METODOLOGÍA DOCENTE",
        "SISTEMA DE EVALUACIÓN",
    }
)

#: Los dos únicos rótulos cuyo contenido pasa al corpus (lista de permitidos).
_RESUMEN: Final[str] = "RESUMEN"
_CONTENIDOS: Final[str] = "DESCRIPCIÓN DE CONTENIDOS"

#: Cabecera y pie que la plantilla repite en cada página del PDF y que, al caer
#: dentro de una sección por el salto de página, contaminarían su contenido.
_RUIDO_PAGINA: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^Página\s+\d+\s+de\s+\d+$"),  # pie: "Página 1 de 7"
    re.compile(r"^Guía Docente$"),  # cabecera, línea 1
    re.compile(r"^\d{8}\s+-\s+"),  # cabecera, línea 2: "15411005 - Cartografía..."
    re.compile(r"^Curso Académico"),  # cabecera, línea 3
)

#: Datos personales que nunca pueden salir de un PDF hacia el corpus. Se usan
#: como red de seguridad final sobre lo ya filtrado por la lista de permitidos.
_CORREO: Final[re.Pattern[str]] = re.compile(r"[\w.\-]+@[\w.\-]+\.\w+")
_TELEFONO: Final[re.Pattern[str]] = re.compile(r"\b\d{9}\b")


def rotulos_presentes(datos: bytes) -> list[str]:
    """Rótulos de sección conocidos que aparecen en el PDF, en orden de lectura."""
    return [
        linea
        for linea in _lineas_utiles(_texto_del_pdf(datos))
        if linea in _ROTULOS_SECCION
    ]


def rotulos_ausentes(datos: bytes) -> list[str]:
    """Rótulos que la plantilla debería traer y este PDF no trae."""
    return sorted(_ROTULOS_ESPERADOS - set(rotulos_presentes(datos)))


def es_pdf(cabecera_tipo: bytes | str | None, cuerpo: bytes) -> bool:
    """Indica si una respuesta es un PDF y no el HTML esperado."""
    if cabecera_tipo is not None:
        tipo = (
            cabecera_tipo.decode("latin-1")
            if isinstance(cabecera_tipo, bytes)
            else cabecera_tipo
        )
        if "application/pdf" in tipo.lower():
            return True
    return cuerpo[:5] == b"%PDF-"


@lru_cache(maxsize=1)
def _texto_del_pdf(datos: bytes) -> str:
    """Extrae el texto de un PDF en orden de lectura, o vacío si no se puede."""
    try:
        lector = PdfReader(io.BytesIO(datos))
        return "\n".join(pagina.extract_text() for pagina in lector.pages)
    except Exception:
        # Un PDF corrupto, cifrado o vacío no debe romper el rastreo: se
        # trata como guía ilegible y la asignatura queda como «sin guía».
        return ""


def _lineas_utiles(texto: str) -> list[str]:
    """Devuelve las líneas del PDF ya recortadas y sin la cabecera/pie repetida."""
    utiles = []
    for linea in texto.split("\n"):
        linea = linea.strip()
        if not linea:
            continue
        if any(patron.match(linea) for patron in _RUIDO_PAGINA):
            continue
        utiles.append(linea)
    return utiles


def _seccion(lineas: list[str], rotulo: str) -> str:
    """Recoge el contenido de una sección, hasta el siguiente rótulo conocido."""
    try:
        inicio = lineas.index(rotulo)
    except ValueError:
        return ""
    recogidas: list[str] = []
    for linea in lineas[inicio + 1 :]:
        if linea in _ROTULOS_SECCION:
            break
        limpia = limpiar_texto(linea)
        if limpia:
            recogidas.append(limpia)
    return "\n".join(recogidas).strip()


def _redactar_datos_personales(texto: str) -> str:
    """Elimina correos y teléfonos que hubieran escapado a la lista de permitidos."""
    texto = _CORREO.sub("", texto)
    texto = _TELEFONO.sub("", texto)
    return texto


def extraer_guia(datos: bytes) -> dict[str, str] | None:
    """Extrae resumen y temario de una guía docente en PDF."""
    lineas = _lineas_utiles(_texto_del_pdf(datos))
    resumen = _redactar_datos_personales(_seccion(lineas, _RESUMEN))
    temario = _redactar_datos_personales(_seccion(lineas, _CONTENIDOS))
    if not resumen and not temario:
        return None
    return {"resumen": resumen, "temario": temario}


def reparto_por_seccion(datos: bytes) -> dict[str, int]:
    """Caracteres que aporta cada sección del PDF, esté permitida o no."""
    # Extrae el PDF una sola vez para obtener rótulos y contenido.
    lineas = _lineas_utiles(_texto_del_pdf(datos))
    rotulos = [linea for linea in lineas if linea in _ROTULOS_SECCION]
    return {rotulo: len(_seccion(lineas, rotulo)) for rotulo in rotulos}


#: Los dos rótulos cuyo contenido sí pasa al corpus, para que quien audite el
#: reparto no tenga que volver a escribirlos.
PERMITIDOS: Final[tuple[str, str]] = (_RESUMEN, _CONTENIDOS)


# Distingue un PDF ilegible de una guía publicada con secciones vacías (IT-95).
ILEGIBLE: Final[str] = "ilegible"
SIN_TEXTO: Final[str] = "sin_texto"
ROTULOS_DESCONOCIDOS: Final[str] = "rotulos_desconocidos"
SECCIONES_VACIAS: Final[str] = "secciones_vacias"


def motivo_sin_guia(datos: bytes) -> str:
    """Explica por qué un PDF no ha dado ni resumen ni temario."""
    try:
        PdfReader(io.BytesIO(datos))
    except Exception:
        return ILEGIBLE
    texto = _texto_del_pdf(datos)
    if not texto.strip():
        return SIN_TEXTO
    lineas = _lineas_utiles(texto)
    if _RESUMEN not in lineas and _CONTENIDOS not in lineas:
        return ROTULOS_DESCONOCIDOS
    return SECCIONES_VACIAS

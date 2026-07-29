"""Extracción de guías docentes servidas en PDF (IT-67).

Desde el curso 2026-27, la EPSJ publica algunas guías docentes como PDF en
lugar de HTML, pero detrás de una URL que sigue acabando en ``.html``. El
spider las trata como HTML, no encuentra la estructura esperada y acaba
guardando el binario del PDF en la colección. Este módulo extrae de esos PDF
lo mismo que ``parse_guia`` saca del HTML —el resumen y el temario— y, sobre
todo, deja fuera el bloque de profesorado, que en el PDF trae nombres, correos
y teléfonos que la colección excluye a propósito (privacidad, RGPD).

El criterio es una **lista de permitidos**, no de prohibidos: solo pasan al
corpus las secciones «Resumen» y «Descripción de contenidos». Si la UJA añade
mañana una sección nueva con datos personales, con una lista de prohibidos se
colaría sola; con una de permitidos, se queda fuera por defecto. Como red de
seguridad final, el texto extraído se redacta de cualquier correo o teléfono
que se hubiera colado pese a todo.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Final

from pypdf import PdfReader

from tfg_uja.text_cleaner import limpiar_texto

# pypdf avisa por su cuenta ("invalid pdf header", "EOF marker not found")
# antes de lanzar la excepción que sí se captura más abajo; se silencia su
# logger para que un PDF corrupto no ensucie la salida del rastreo.
logging.getLogger("pypdf").setLevel(logging.ERROR)

#: Rótulos de sección de la plantilla de guía docente de la UJA. Sirven como
#: FRONTERAS: una sección abarca desde su rótulo hasta el siguiente rótulo
#: conocido. No confundir con los títulos de tema del temario, que también van
#: en mayúsculas ("INTRODUCCIÓN A LA CARTOGRAFÍA Y SIG") pero NO están en este
#: conjunto y, por tanto, se conservan como contenido en lugar de cortar la
#: sección. Se recogen las variantes observadas (singular/plural) porque la UJA
#: no es consistente entre planes.
_ROTULOS_SECCION: Final[frozenset[str]] = frozenset(
    {
        "FICHA IDENTIFICATIVA",
        "PROFESORADO",
        "RESUMEN",
        "COMPETENCIAS",
        "COMPETENCIAS / RESULTADOS DEL PROCESO DE FORMACIÓN Y APRENDIZAJE",
        "RESULTADOS DE APRENDIZAJE",
        "DESCRIPCIÓN DE CONTENIDOS",
        "METODOLOGÍA DOCENTE",
        "METODOLOGÍAS DOCENTES Y ACTIVIDADES FORMATIVAS",
        "SISTEMA DE EVALUACIÓN",
        "SISTEMAS DE EVALUACIÓN",
        "BIBLIOGRAFÍA",
        "OBJETIVOS DE DESARROLLO SOSTENIBLE",
        "ESTUDIANTADO CON NECESIDADES ESPECÍFICAS DE APOYO EDUCATIVO",
        "PLAN DE CONTINGENCIA",
        "CLÁUSULAS",
        "COMPROMISO CON LA IGUALDAD Y LA PERSPECTIVA DE GÉNERO",
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

#: Encabezados de segundo nivel dentro de PROFESORADO. No delimitan sección,
#: pero la plantilla los compone con la misma tipografía que los rótulos, así
#: que hay que conocerlos para no confundirlos con un rótulo desconocido.
_SUBROTULOS: Final[frozenset[str]] = frozenset({"Coordinación", "Cuadro docente"})

#: Tipografía con la que la plantilla de la UJA compone los rótulos de sección:
#: negrita a 12 puntos. Medido sobre los PDF reales (IT-95); ningún otro texto
#: del documento usa esa combinación salvo la cabecera de página, que ya filtra
#: `_RUIDO_PAGINA`.
#:
#: Se mira la tipografía y NO que el texto vaya en mayúsculas, que es la idea
#: evidente y la que no funciona: el bloque de profesorado trae en mayúsculas
#: los nombres, los departamentos y las ubicaciones, y produce entre 17 y 25
#: falsos avisos por guía. Un verificador que avisa siempre se acaba ignorando.
_TAM_ROTULO: Final[float] = 12.0


def rotulos_del_pdf(datos: bytes) -> list[str]:
    """Enumera los rótulos de sección que la plantilla compone en el PDF.

    Los localiza por su tipografía (negrita a :data:`_TAM_ROTULO` puntos), no
    por su texto, y descarta la cabecera y el pie que se repiten en cada
    página. Sirve para comprobar que la plantilla de la UJA sigue siendo la
    esperada: un rótulo que no se conozca significa que una sección puede no
    terminar donde debe, y eso se traduce en contenido perdido o, peor, en
    contenido de profesorado arrastrado hasta el corpus.

    Args:
        datos: Bytes del PDF descargado.

    Returns:
        Los rótulos hallados, en orden de lectura y sin repetir los de la
        cabecera de página. Lista vacía si el PDF no se puede leer.
    """
    hallados: list[str] = []

    # La firma la impone pypdf: `cm` y `tm` son las matrices de
    # transformación de la página, que aquí no hacen falta.
    def visitar(
        texto: str, cm: object, tm: object, fuente: dict | None, tamano: float
    ) -> None:
        limpio = texto.strip()
        if not limpio or round(float(tamano), 1) != _TAM_ROTULO:
            return
        if "Bold" not in str((fuente or {}).get("/BaseFont", "")):
            return
        if any(patron.match(limpio) for patron in _RUIDO_PAGINA):
            return
        hallados.append(limpio)

    try:
        lector = PdfReader(io.BytesIO(datos))
        for pagina in lector.pages:
            pagina.extract_text(visitor_text=visitar)
    except Exception:
        return []
    return hallados


def rotulos_desconocidos(datos: bytes) -> list[str]:
    """Rótulos del PDF que no están en la plantilla conocida, sin repetir.

    Es la comprobación que sostiene toda la extracción: mientras salga vacía,
    la plantilla es la esperada y las fronteras de sección caen donde el código
    cree. En cuanto devuelva algo, hay que mirarlo antes de fiarse del corpus.

    Args:
        datos: Bytes del PDF descargado.

    Returns:
        Los rótulos desconocidos, ordenados y sin duplicados.
    """
    conocidos = _ROTULOS_SECCION | _SUBROTULOS
    return sorted({r for r in rotulos_del_pdf(datos) if r not in conocidos})


def es_pdf(cabecera_tipo: bytes | str | None, cuerpo: bytes) -> bool:
    """Indica si una respuesta es un PDF y no el HTML esperado.

    Comprueba tanto la cabecera ``Content-Type`` como los primeros bytes del
    cuerpo: el servidor de la UJA sirve estos PDF con la cabecera correcta,
    pero mirar también la firma ``%PDF`` protege frente a cabeceras engañosas.

    Args:
        cabecera_tipo: Valor de la cabecera ``Content-Type`` de la respuesta.
        cuerpo: Bytes del cuerpo de la respuesta.

    Returns:
        ``True`` si la respuesta es un PDF.
    """
    if cabecera_tipo is not None:
        tipo = (
            cabecera_tipo.decode("latin-1")
            if isinstance(cabecera_tipo, bytes)
            else cabecera_tipo
        )
        if "application/pdf" in tipo.lower():
            return True
    return cuerpo[:5] == b"%PDF-"


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
    """Recoge el contenido de una sección, hasta el siguiente rótulo conocido.

    Args:
        lineas: Líneas útiles del PDF (sin cabecera/pie de página).
        rotulo: Rótulo de la sección buscada (uno de los permitidos).

    Returns:
        El texto de la sección, una línea por renglón; vacío si no aparece.
    """
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
    """Elimina correos y teléfonos que hubieran escapado a la lista de permitidos.

    Es la red de seguridad final: la lista de permitidos ya deja fuera el
    bloque de profesorado, pero al tratarse de un requisito legal se comprueba
    también el texto ya extraído, para que ni un descuido en los rótulos
    pueda filtrar un dato personal.
    """
    texto = _CORREO.sub("", texto)
    texto = _TELEFONO.sub("", texto)
    return texto


def extraer_guia(datos: bytes) -> dict[str, str] | None:
    """Extrae resumen y temario de una guía docente en PDF.

    Solo se conservan las secciones «Resumen» y «Descripción de contenidos»
    (lista de permitidos); el resto del PDF, incluido el bloque de profesorado
    con sus datos personales, se descarta.

    Args:
        datos: Bytes del PDF descargado.

    Returns:
        Diccionario con ``resumen`` y ``temario``, o ``None`` si el PDF no se
        puede leer o no contiene ninguna de las dos secciones. Devolver
        ``None`` permite al spider tratar la asignatura como «sin guía» en
        lugar de recurrir al mecanismo de respaldo.
    """
    lineas = _lineas_utiles(_texto_del_pdf(datos))
    resumen = _redactar_datos_personales(_seccion(lineas, _RESUMEN))
    temario = _redactar_datos_personales(_seccion(lineas, _CONTENIDOS))
    if not resumen and not temario:
        return None
    return {"resumen": resumen, "temario": temario}


def reparto_por_seccion(datos: bytes) -> dict[str, int]:
    """Caracteres que aporta cada sección del PDF, esté permitida o no.

    Sirve para que «se descarta la mayor parte del documento» deje de ser una
    alarma suelta y pase a ser una lista de secciones con nombre, cada una
    descartada a propósito. Sin esto no hay forma de distinguir una pérdida
    deliberada —profesorado, bibliografía, cláusulas— de una accidental.

    Args:
        datos: Bytes del PDF descargado.

    Returns:
        Caracteres por rótulo, en orden de aparición en el documento. Vacío si
        el PDF no se puede leer.
    """
    lineas = _lineas_utiles(_texto_del_pdf(datos))
    return {rotulo: len(_seccion(lineas, rotulo)) for rotulo in rotulos_del_pdf(datos)}


#: Los dos rótulos cuyo contenido sí pasa al corpus, para que quien audite el
#: reparto no tenga que volver a escribirlos.
PERMITIDOS: Final[tuple[str, str]] = (_RESUMEN, _CONTENIDOS)


#: Motivos por los que una guía en PDF no aporta contenido. Se distinguen
#: porque NO son lo mismo y el sistema no puede afirmar el que no es: decirle
#: a un estudiante que la guía «no se ha podido obtener» cuando la Universidad
#: la publica vacía es meter una afirmación falsa en la colección (IT-95).
ILEGIBLE: Final[str] = "ilegible"
SIN_TEXTO: Final[str] = "sin_texto"
ROTULOS_DESCONOCIDOS: Final[str] = "rotulos_desconocidos"
SECCIONES_VACIAS: Final[str] = "secciones_vacias"


def motivo_sin_guia(datos: bytes) -> str:
    """Explica por qué un PDF no ha dado ni resumen ni temario.

    Se llama solo cuando :func:`extraer_guia` ha devuelto ``None``, para poder
    registrar qué ha pasado en vez de un aviso genérico. Hasta IT-95 los cuatro
    casos eran indistinguibles y el rastreo los llamaba a todos «PDF ilegible»,
    que resultó ser falso: los seis casos reales observados el 29/07/2026 se
    leían perfectamente y lo que estaba vacío eran las secciones en el origen.

    Args:
        datos: Bytes del PDF descargado.

    Returns:
        Uno de :data:`ILEGIBLE` (el PDF está corrupto, cifrado o truncado),
        :data:`SIN_TEXTO` (se abre pero no tiene capa de texto, típico de un
        escaneo), :data:`ROTULOS_DESCONOCIDOS` (la plantilla ha cambiado y las
        secciones permitidas no se localizan) o :data:`SECCIONES_VACIAS` (la
        guía está publicada y sus secciones de contenido no traen nada).
    """
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

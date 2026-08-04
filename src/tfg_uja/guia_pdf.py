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
from functools import lru_cache
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

#: Rótulos que la plantilla de la UJA trae en TODAS las guías. Medido sobre
#: las 293 guías del rastreo del 29/07/2026: estos trece aparecen en las 293.
#: El resto de `_ROTULOS_SECCION` son variantes que unas veces salen y otras no
#: («COMPETENCIAS» en 33, «SISTEMA DE EVALUACIÓN» en 5) o que ya no aparecen
#: nunca («RESULTADOS DE APRENDIZAJE», «METODOLOGÍA DOCENTE»); siguen en el
#: conjunto porque como frontera no estorban, pero exigirlas sería inventarse
#: un invariante que la fuente no cumple.
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


def rotulos_presentes(datos: bytes) -> list[str]:
    """Rótulos de sección conocidos que aparecen en el PDF, en orden de lectura.

    Se localizan como línea completa, que es como los compone la plantilla y
    como los usa :func:`_seccion` para delimitar. No se usa la tipografía: se
    intentó (negrita a doce puntos) y **no funciona sobre el corpus real**,
    porque la plantilla usa esa misma tipografía para resaltar contenido dentro
    de las secciones —criterios de evaluación, títulos de capítulo del
    temario— y para la segunda línea del nombre de la asignatura cuando no cabe
    en la cabecera.

    Args:
        datos: Bytes del PDF descargado.

    Returns:
        Los rótulos hallados, en el orden en que aparecen. Vacío si el PDF no
        se puede leer.
    """
    return [
        linea
        for linea in _lineas_utiles(_texto_del_pdf(datos))
        if linea in _ROTULOS_SECCION
    ]


def rotulos_ausentes(datos: bytes) -> list[str]:
    """Rótulos que la plantilla debería traer y este PDF no trae.

    Es la comprobación que sostiene toda la extracción, y va por ausencia y no
    por presencia de rótulos desconocidos. El motivo es que buscar rótulos
    desconocidos no se puede hacer sin falsos positivos: sobre las 293 guías
    reales produce 68 avisos distintos, todos legítimos (``'tecnológica'`` es
    la continuación del nombre de la asignatura en la cabecera; ``'Capítulo
    I.- ...'`` es un título del temario). Un verificador que avisa siempre se
    acaba ignorando.

    Preguntar por ausencia sí es exacto, y cubre el caso que de verdad hace
    daño: si la Universidad renombra o retira un rótulo, la sección que
    delimitaba deja de terminar donde debe. Da igual que el rótulo perdido sea
    uno de los dos permitidos —entonces se pierde su contenido— o el que venía
    justo después —entonces la sección permitida se traga la siguiente—: en
    ambos casos el rótulo desaparece de la lista esperada y se detecta.

    Lo que **no** cubre, y conviene declararlo: una sección enteramente nueva
    intercalada entre dos conocidas, con un rótulo que nunca se ha visto. Esa
    sí se colaría dentro de la sección anterior. El daño queda acotado por la
    lista de permitidos —solo dos secciones pasan al corpus— y por la redacción
    final de correos y teléfonos, que se aplica sobre lo ya extraído.

    Args:
        datos: Bytes del PDF descargado.

    Returns:
        Los rótulos esperados que faltan, ordenados. Vacío si están todos.
    """
    return sorted(_ROTULOS_ESPERADOS - set(rotulos_presentes(datos)))


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


@lru_cache(maxsize=1)
def _texto_del_pdf(datos: bytes) -> str:
    """Extrae el texto de un PDF en orden de lectura, o vacío si no se puede.

    Se memoriza el último resultado porque al auditar se pregunta varias cosas
    seguidas por el mismo PDF (rótulos, contenido y reparto por sección), y
    volver a parsearlo cada vez multiplicaba por tres el trabajo: sobre las 288
    guías del corpus, la diferencia entre medio minuto y un minuto y medio.
    Basta con recordar uno, que es el patrón real de uso, y así no se acumulan
    en memoria los megabytes de todo el corpus.
    """
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
    # Se extrae el texto UNA vez y de ahí salen tanto los rótulos como sus
    # contenidos: llamar a `rotulos_presentes` aquí volvería a parsear el PDF
    # entero, y sobre las 288 guías del corpus eso se nota (el verificador
    # pasaba de segundos a minutos).
    lineas = _lineas_utiles(_texto_del_pdf(datos))
    rotulos = [linea for linea in lineas if linea in _ROTULOS_SECCION]
    return {rotulo: len(_seccion(lineas, rotulo)) for rotulo in rotulos}


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

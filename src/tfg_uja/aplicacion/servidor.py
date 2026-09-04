"""Punto de entrada HTTP de la aplicación web (IT-44).

Sirve la interfaz de ``web/`` y atiende ``POST /api/chat``, que devuelve la
respuesta **por partes** según la decisión del ADR-0006: una línea JSON por
unidad ya verificada.

**Por qué la biblioteca estándar y no un marco de trabajo.** Medido con
``pip install --dry-run`` contra lo que el sistema necesita para funcionar:
``http.server`` añade 0 paquetes, Starlette 2, FastAPI 3 y Flask 4.
Lo que hay que atender es un endpoint y unos ficheros estáticos, y el cuello de
botella es el modelo, que responde con una mediana de 62,7 s: ninguna capa HTTP
cambia eso.

⚠️ **No es apto para producción**, y así está declarado: no da HTTPS ni limita
la tasa de peticiones, y el despliegue queda fuera del alcance de este trabajo
(reparto MoSCoW del Capítulo 4). Llevarlo allí exigiría un servidor WSGI/ASGI
tras un proxy inverso, HTTPS, límites de tasa, conversación por sesión y, sobre
todo, resolver que el modelo atiende de uno en uno.

**El alcance es una demostración local para un solo visitante, y el servidor
está construido para eso.** Atiende de una petición en una ---:class:`HTTPServer`
y no ``ThreadingHTTPServer``---, y de ahí se siguen tres cosas:

* El estado de la conversación, único para todo el proceso, es correcto en vez
  de una carrera. Con hilos, dos peticiones solapadas ---una persona sola llega
  a eso cancelando y volviendo a preguntar--- compartían sujeto y contador de
  turno sin ninguna sincronización.
* No hay hilos que agotar, y una llamada al modelo puede ocupar hasta
  :data:`tfg_uja.generador.ESPERA_MAXIMA` segundos.
* El precio, que conviene decir: **mientras se redacta una respuesta no se
  atiende nada más**. Para un visitante que pregunta y lee es invisible; para
  dos no lo sería, y por eso el alcance dice uno.

Lo que el navegador manda se comprueba (:data:`ORIGENES_PERMITIDOS`): no es CORS
abierto, es lo contrario. Y el cuerpo va acotado en :data:`MAXIMO_CUERPO`.

**La lógica no vive en el manejador.** :func:`partes_de_la_respuesta` no sabe
nada de HTTP y se prueba entera sin red y sin modelo; el manejador solo la
enchufa con el socket.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Iterator
from functools import cache, partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Final

from tfg_uja import RAIZ
from tfg_uja.dialogo.ambito import decisor_con_modelo
from tfg_uja.dialogo.conversacion import Consulta, Conversacion
from tfg_uja.dialogo.generador import (
    RESPUESTA_SALUDO,
    ErrorDelModelo,
    respuesta_fija,
    responder_por_partes,
)
from tfg_uja.indexacion.incrustaciones import MODELO as MODELO_INCRUSTACIONES
from tfg_uja.indexacion.incrustaciones import incrustador_de_consultas
from tfg_uja.aplicacion.registro_chat import anotar_turno, linea_de_turno
from tfg_uja.aplicacion.sugerencias import sugerencias_para
from tfg_uja.dialogo.recuperador import (
    K_MAXIMO,
    abrir_indice,
    catalogo_del_indice,
    contexto_para,
    distancia_del_indice,
)

#: Canal diagnóstico del servidor. Sirve para lo que no puede ir al chat ni
#: al registro de turnos: que un adorno de la interfaz se haya caído o que se
#: haya perdido la anotación de un turno. No lleva nunca la pregunta íntegra.
_registro: Final[logging.Logger] = logging.getLogger(__name__)

#: Interfaz estática. Se sirve desde el mismo proceso que el endpoint, que es
#: lo que decide el ADR de arquitectura de la Fase 3.
WEB: Final[Path] = RAIZ / "web"

#: Índice vectorial. No se versiona: se construye con
#: ``py -m tfg_uja.indexacion.indexer``.
INDICE: Final[Path] = RAIZ / "data" / "indice_lance"

#: Dataset del que salen las direcciones oficiales de cada unidad. Es el
#: mismo fichero del que se construye la colección, así que si hay índice
#: lo hay a él.
DATASET: Final[Path] = RAIZ / "data" / "grados.json"

MODELO_GENERATIVO: Final[str] = "gemma3:12b"

PUERTO: Final[int] = 8000

#: Cabeceras que acompañan a toda respuesta. Ninguna hace falta para que la
#: aplicación funcione en local; están porque el día que este servidor deje de
#: escuchar solo en ``127.0.0.1`` ya no habría que acordarse de ponerlas.
#:
#: La política de contenido es estricta a propósito: la página no tiene nada en
#: línea y no carga nada de fuera, así que ``'self'` a secas basta y no hace
#: falta ``'unsafe-inline'``. Modificar ``element.style`` desde el guion no la
#: infringe: lo que la política gobierna es el atributo ``style`` del marcado,
#: no el modelo de objetos.
CABECERAS_DEFENSIVAS: Final[dict[str, str]] = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    # Impide que el navegador adivine el tipo de un fichero y lo trate como
    # algo distinto de lo que se declara.
    "X-Content-Type-Options": "nosniff",
    # `frame-ancestors` ya lo cubre en los navegadores actuales; esto vale para
    # los que no entienden esa directiva.
    "X-Frame-Options": "DENY",
    # Que la dirección de esta página no viaje a ningún sitio al salir de ella.
    "Referrer-Policy": "no-referrer",
    # La aplicación no usa cámara, ni micrófono, ni ubicación. Decirlo evita
    # que un guion inyectado pueda pedirlas.
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}

#: Tope del cuerpo de la petición. Una pregunta no ocupa esto ni de lejos; está
#: para que un cuerpo enorme no se lea entero en memoria.
MAXIMO_CUERPO: Final[int] = 8 * 1024

#: De dónde se acepta una consulta. Es una lista de PERMITIDOS y deliberadamente
#: corta: solo la propia interfaz, servida por este mismo proceso.
#:
#: Sin ella, ``POST /api/chat`` atendía a cualquiera. Comprobado: una petición
#: con ``Origin`` y ``Host`` ajenos y ``Content-Type: text/plain`` se respondía
#: con un 200. Una página abierta en otra pestaña del mismo navegador podía
#: entonces lanzar consultas, mover el estado de la conversación y ensuciar el
#: registro; y un ataque de reenlace de DNS se apoya justo en que el proceso
#: local se fíe de cualquier ``Host``.
#:
#: Esto **no es CORS**: CORS sirve para abrir el acceso a terceros y aquí lo que
#: se quiere es lo contrario. Por eso no se emite ninguna cabecera
#: ``Access-Control-Allow-*``.
ORIGENES_PERMITIDOS: Final[frozenset[str]] = frozenset(
    {
        f"http://127.0.0.1:{PUERTO}",
        f"http://localhost:{PUERTO}",
    }
)

#: Anfitriones que se admiten en la cabecera ``Host``.
ANFITRIONES_PERMITIDOS: Final[frozenset[str]] = frozenset(
    {
        f"127.0.0.1:{PUERTO}",
        f"localhost:{PUERTO}",
    }
)

#: Tipo de contenido que exige ``/api/chat``. El cuerpo se interpreta como JSON,
#: así que pedir que lo declare no es formalismo: un ``text/plain`` es
#: exactamente lo que un formulario ajeno puede enviar sin disparar la
#: comprobación previa del navegador.
TIPO_ESPERADO: Final[str] = "application/json"


#: Cómo se nombra en pantalla cada tipo de fragmento. La colección los marca
#: con una etiqueta corta que no significa nada para quien pregunta.
#:
#: Las siete claves son las que trae el corpus, contadas sobre ``chunks.json``
#: y no supuestas: escribirlas de memoria ya dejó tres sin traducir, y el fallo
#: no se ve en las pruebas porque un origen desconocido sale tal cual y la
#: pantalla sigue funcionando.
ROTULOS_DE_ORIGEN: Final[dict[str, str]] = {
    "guia": "Guía docente",
    "asignatura_sin_guia": "Asignatura sin guía publicada",
    "plan_de_estudios": "Plan de estudios",
    "mencion": "Menciones",
    "salidas": "Salidas profesionales",
    "ficha_titulacion": "Ficha de la titulación",
    "catalogo": "Catálogo de titulaciones",
}


#: De donde sale el enlace de cada tipo de unidad. Las de asignatura apuntan a
#: su guia docente; las que describen la titulacion entera, a la pagina del
#: plan; las salidas, a la suya. El catalogo no tiene pagina propia.
_ENLACE_DE_LA_TITULACION: Final[dict[str, str]] = {
    "plan_de_estudios": "url_asignaturas",
    "mencion": "url_asignaturas",
    "ficha_titulacion": "url_asignaturas",
    "salidas": "url_salidas",
}


@cache
def enlaces_oficiales(datos: Path = DATASET) -> dict[tuple[str, str], str]:
    """Direccion oficial de la EPSJ para cada unidad de la coleccion.

    El cuadro de fuentes dice de donde sale cada cosa, y sin enlace habria que
    buscar el documento a mano en la web de la Escuela para comprobar un dato.
    La direccion la extrae el spider por su ``href`` real, nunca por patron.

    Se resuelve aqui y no en el indice a proposito: es un dato de presentacion,
    y meterlo en la coleccion obligaria a reconstruirla entera por una columna
    que el recuperador no usa.

    La clave es ``(titulacion, nombre de la unidad)``. La regla del proyecto es
    identificar una asignatura por ``(grado, codigo or nombre)``, y aqui solo
    se dispone del nombre; se ha comprobado que en las 528 asignaturas no hay
    dos con el mismo nombre dentro de una titulacion, pero por si algun dia las
    hubiera, una colision **retira** el enlace en vez de elegir uno: es mejor
    quedarse sin enlace que mandar a alguien a la guia equivocada.

    Args:
        datos: Fichero del dataset, ``data/grados.json``.

    Returns:
        ``(titulacion, unidad) -> URL``. Solo las unidades que tienen una; las
        235 asignaturas sin guia publicada no aparecen, y eso es correcto: no
        hay documento al que enlazar y fabricar uno seria mentir.
    """
    if not datos.exists():
        return {}
    items = json.loads(datos.read_text(encoding="utf-8"))

    enlaces: dict[tuple[str, str], str] = {}
    chocadas: set[tuple[str, str]] = set()
    for item in items:
        if item.get("tipo") != "asignatura" or not item.get("url_guia"):
            continue
        clave = (item["grado"], item["nombre"])
        if clave in enlaces and enlaces[clave] != item["url_guia"]:
            chocadas.add(clave)
        enlaces[clave] = item["url_guia"]
    for clave in chocadas:
        del enlaces[clave]

    return enlaces


@cache
def paginas_de_titulacion(datos: Path = DATASET) -> dict[tuple[str, str], str]:
    """Pagina del plan y de las salidas de cada titulacion.

    Las unidades que no son de asignatura ---el plan, las menciones, la ficha,
    las salidas--- no tienen guia docente, pero si tienen la pagina de la
    Escuela de la que se extrajeron.

    Args:
        datos: Fichero del dataset, ``data/grados.json``.

    Returns:
        ``(titulacion, campo) -> URL``, con ``campo`` uno de
        ``url_asignaturas`` o ``url_salidas``. La titulacion internacional con
        Schmalkalden no publica ninguna de las dos y no aparece.
    """
    if not datos.exists():
        return {}
    items = json.loads(datos.read_text(encoding="utf-8"))

    return {
        (item["nombre"], campo): item[campo]
        for item in items
        if item.get("tipo") == "grado"
        for campo in ("url_asignaturas", "url_salidas")
        if item.get(campo)
    }


def _enlace_de(fragmento: Any) -> str:
    """Direccion oficial de la unidad de un fragmento, o cadena vacia.

    Una unidad compartida por varias titulaciones tiene una guia por cada una,
    y son la misma: se toma la de la primera que la imparta. Si no hay ninguna
    se devuelve cadena vacia, que la interfaz muestra como texto sin enlace en
    lugar de fabricar uno.

    Args:
        fragmento: Uno de los que trajo el recuperador.

    Returns:
        La URL, o ``""`` si esa unidad no tiene documento publicado.
    """
    campo = _ENLACE_DE_LA_TITULACION.get(fragmento.origen)
    if campo:
        paginas = paginas_de_titulacion()
        for grado in fragmento.grados:
            if (grado, campo) in paginas:
                return paginas[(grado, campo)]
        return ""

    guias = enlaces_oficiales()
    for grado in fragmento.grados:
        if (grado, fragmento.nombre) in guias:
            return guias[(grado, fragmento.nombre)]
    return ""


def fuentes_de(fragmentos: list[Any]) -> list[dict[str, str]]:
    """Unidades de la colección que se le entregaron al modelo para responder.

    Un fragmento no es una fuente. Una guía docente larga se trocea en varios y
    los tres apuntan al mismo sitio, así que listarlos uno a uno repetiría la
    misma línea. Se agrupa por unidad, con la misma identidad que usa el resto
    del sistema: el nombre de la unidad junto a las titulaciones en las que se
    imparte.

    ⚠️ Lo que devuelve es **lo que se le entregó al modelo**, no lo que el
    modelo usó al redactar. El sistema no sabe lo segundo, y presentarlo como
    si lo supiera sería afirmar de más.

    Args:
        fragmentos: Lo que devolvió el recuperador para esta consulta.

    Returns:
        Una entrada por unidad, en el orden en que las trajo el recuperador,
        que es el de proximidad a la pregunta.
    """
    vistas: dict[tuple[str, str], dict[str, str]] = {}
    for fragmento in fragmentos:
        titulacion = " · ".join(fragmento.grados)
        clave = (fragmento.nombre, titulacion)
        if clave not in vistas:
            vistas[clave] = {
                "nombre": fragmento.nombre,
                "titulacion": titulacion,
                "origen": ROTULOS_DE_ORIGEN.get(fragmento.origen, fragmento.origen),
                "url": _enlace_de(fragmento),
            }
    return list(vistas.values())


def partes_de_la_respuesta(
    pregunta: str,
    sistema: tuple[Any, Any, list[str], str],
    conversacion: Conversacion,
    turno: int = 0,
) -> Iterator[dict[str, object]]:
    """Recorre el sistema y va soltando lo que hay que mandar al navegador.

    No toca HTTP: devuelve los objetos tal cual, y quien los serialice decide
    cómo. Así se prueba el recorrido entero sin levantar un socket.

    Lo primero es mirar si la pregunta se contesta con texto fijo, y se mira
    **antes de recuperar**: un saludo no llega al modelo, así que buscarle
    contexto es trabajo tirado y anunciar lo encontrado como fuentes presenta
    como respaldo algo que nadie usó para redactar. La respuesta fija la produce
    igualmente :func:`tfg_uja.generador.responder_por_partes`, para que siga
    habiendo una única forma de redactar cada respuesta.

    Al terminar el turno ---responda el modelo o falle--- se deja una línea en
    ``data/registro_chat.jsonl``. Se registra aquí y no en el manejador porque
    aquí está lo que hay que registrar: la consulta con la que se buscó de
    verdad y las distancias de los fragmentos, que el manejador ya no ve.

    Args:
        pregunta: Lo que ha escrito el estudiante.
        sistema: ``(tabla, incrustar, catalogo, distancia)``, ya abierto.
        conversacion: Estado del diálogo, que se actualiza aquí.
        turno: Cuántas preguntas lleva la conversación. Solo sirve para
            desplazar las sugerencias, para que dos turnos seguidos no
            propongan lo mismo.

    Yields:
        ``{"fuentes": [...]}`` con las unidades recuperadas, ``{"parte": ...}``
        por cada unidad verificada, ``{"borrar": True}`` cuando la respuesta se
        retira a media emisión, ``{"sugerencias": [...]}`` con lo que se puede
        preguntar a continuación, y ``{"error": ...}`` si el modelo no
        responde.
    """
    tabla, incrustar, catalogo, distancia = sistema
    arranque = time.monotonic()
    # El ámbito se copia ANTES de preparar la consulta: preparar no lo cambia,
    # pero anotar sí, y lo que interesa del registro es precisamente en qué
    # turno cambió de titulación.
    ambito_antes = list(conversacion.ambito)
    # Reproducido contra el sistema real: «Hola» anunciaba **16 fuentes**,
    # las dieciséis de la misma titulación, porque se recuperaba primero y se
    # decidía después. Preguntarlo aquí es lo que lo corta.
    fija = respuesta_fija(pregunta)
    # Y ahora la respuesta fija se resuelve **antes** de preparar la consulta,
    # no después, porque preparar le pregunta al modelo de qué titulación se
    # habla. A un «hola» ese modelo contesta, con razón, que de ninguna: el
    # ámbito se soltaría y la pregunta de seguimiento que viniera detrás se
    # quedaría sin sujeto. Un saludo en mitad de una conversación no cambia de
    # tema, y además así no cuesta los dos segundos y medio de la decisión.
    consulta = (
        conversacion.preparar(pregunta)
        if fija is None
        else Consulta(texto=pregunta, ambito=list(conversacion.ambito))
    )
    fragmentos: list[Any] = []
    if fija is None:
        fragmentos = contexto_para(
            consulta.texto,
            tabla,
            incrustar,
            respaldo=consulta.respaldo,
            abierta=consulta.abierta,
            distancia=distancia,
            k=K_MAXIMO,
            catalogo=catalogo,
            ambito=consulta.ambito,
        )
    # Las fuentes salen antes que el texto y no después: se conocen en cuanto
    # termina la recuperación, y el modelo tarda un minuto en dar la primera
    # frase. Esperar al final sería tener el dato guardado sin motivo.
    if fragmentos:
        yield {"fuentes": fuentes_de(fragmentos)}
    entero = ""
    retirada = False

    def registrar(fallo: str = "") -> None:
        """Deja el turno en el registro con el estado tal como esté ahora.

        Que el registro no pueda escribirse no tumba el chat, que es lo
        correcto: es un artefacto auxiliar. Pero tampoco puede perderse en
        silencio, porque estas sesiones se analizan después y un hueco sin
        aviso se lee como un turno que nunca ocurrió. El aviso lleva el
        motivo, nunca la pregunta.
        """
        if anotar_turno(
            linea_de_turno(
                pregunta=pregunta,
                consulta=consulta,
                ambito_antes=ambito_antes,
                ambito_despues=list(conversacion.ambito),
                fragmentos=fragmentos,
                se_busco=fija is None,
                respuesta=entero,
                retirada=retirada,
                segundos=time.monotonic() - arranque,
                modelo=MODELO_GENERATIVO,
                error=fallo,
            )
        ):
            return
        _registro.warning(
            "No se ha podido anotar el turno en el registro: se pierde la "
            "observación de esta consulta."
        )

    try:
        partes = responder_por_partes(
            pregunta,
            fragmentos,
            MODELO_GENERATIVO,
            historial=[(p, "") for p in conversacion.preguntas()],
            ambito=(
                consulta.ambito[0]
                if len(consulta.ambito) == 1
                else consulta.ambito or None
            ),
            catalogo=catalogo,
        )
        for parte in partes:
            if parte is None:
                entero = ""
                retirada = True
                yield {"borrar": True}
                continue
            entero += parte
            yield {"parte": parte}
    except ErrorDelModelo as fallo:
        # Un turno que falla es justo el que hay que poder analizar después,
        # así que se registra igual, con el mensaje del fallo dentro.
        registrar(str(fallo))
        yield {"error": str(fallo)}
        return
    # Se anota lo que de verdad se ha entregado: si hubo retirada, lo que queda
    # anotado es la respuesta fija y no el texto retirado.
    #
    # Y con respuesta fija el ámbito no se toca. Aquí no se ha llamado a
    # `preparar`, así que el decisor no ha opinado y `anotar` caería a la
    # deducción por reglas: una pregunta por otro centro, que la barrera
    # rechaza, dejaba la conversación apuntando a la titulación que nombraba
    # de pasada.
    conversacion.anotar(pregunta, entero, cambia_ambito=fija is None)
    # Se registra DESPUÉS de anotar, que es donde la conversación fija de qué
    # titulación se está hablando: registrarlo antes guardaría siempre el
    # ámbito del turno anterior.
    registrar()
    # Las sugerencias se calculan DESPUÉS de anotar, porque es ahí donde la
    # conversación fija de qué titulación se está hablando, y eso es lo que
    # decide qué se puede proponer.
    #
    # Y se calculan dentro de una captura porque son un adorno: consultan el
    # índice por su cuenta y un fallo suyo escapaba hasta aquí, dejaba el
    # turno sin `fin` y se llevaba por delante una respuesta que ya estaba
    # entregada. La captura es estrecha a propósito: envuelve solo esta
    # llamada, no el turno entero, para no convertir un fallo real del
    # generador en un silencio.
    try:
        propuestas = sugerencias_para(tabla, conversacion.ambito, catalogo, turno)
    except Exception as fallo:  # noqa: BLE001
        _registro.warning("No se han podido calcular las sugerencias: %s", fallo)
        propuestas = []
    yield {"sugerencias": propuestas}
    yield {"fin": True}


def abrir_sistema() -> tuple[Any, Any, list[str], str]:
    """Abre el índice y el incrustador una sola vez, al arrancar.

    Returns:
        ``(tabla, incrustar, catalogo, distancia)``.
    """
    return (
        abrir_indice(INDICE, MODELO_INCRUSTACIONES),
        incrustador_de_consultas(MODELO_INCRUSTACIONES),
        catalogo_del_indice(INDICE),
        distancia_del_indice(INDICE),
    )


def manejador(sistema: tuple[Any, Any, list[str], str]) -> type:
    """Construye el manejador con el sistema ya abierto dentro.

    Se hace así, y no con variables de módulo, para que las pruebas puedan
    inyectar un sistema falso sin tocar estado global.

    Args:
        sistema: Lo que devuelve :func:`abrir_sistema`.

    Returns:
        La clase de manejador lista para ``HTTPServer``.
    """

    class Manejador(SimpleHTTPRequestHandler):
        """Sirve ``web/`` y atiende ``POST /api/chat``."""

        def version_string(self) -> str:
            """Cabecera ``Server`` sin número de versión.

            Se anunciaba ``SimpleHTTP/0.6 Python/3.13.5``, que le dice a quien
            pregunte qué biblioteca y qué intérprete hay detrás. No es una
            vulnerabilidad por sí sola, pero es información que solo sirve a
            quien busca por dónde entrar. El servicio se sigue identificando:
            lo que se calla es la versión.

            Returns:
                Nombre del servicio, sin versión.
            """
            return "asistente-epsj"

        def end_headers(self) -> None:
            """Añade las cabeceras defensivas a **todas** las respuestas.

            Se hace aquí y no en cada punto de salida porque hay cinco, y una
            que se olvide no falla: simplemente sirve una respuesta sin
            protección, y eso no se nota mirando la aplicación.

            La política de contenido puede ser estricta porque la página no
            tiene nada en línea ---ni ``<script>`` ni ``style=``--- y desde
            IT-118 tampoco pide tipografías fuera: todo lo que carga es suyo.
            """
            for nombre, valor in CABECERAS_DEFENSIVAS.items():
                self.send_header(nombre, valor)
            super().end_headers()

        def send_error(  # type: ignore[override]
            self,
            code: int,
            message: str | None = None,
            explain: str | None = None,
        ) -> None:
            """Responde en JSON cuando el fallo es de la API.

            El endpoint operaba en JSON y fallaba en HTML, y además en inglés,
            mientras la interfaz y el atributo ``lang`` están en español. Un
            cliente que consuma la API tenía que saber distinguir dos formatos
            según le fuera bien o mal.

            Fuera de ``/api/`` se mantiene el HTML de la biblioteca: ahí quien
            se equivoca de dirección es un navegador, y una página de error se
            lee mejor que un objeto JSON.

            Args:
                code: Código HTTP.
                message: Motivo breve, el que se le devuelve al cliente.
                explain: Explicación larga de la clase base; no se usa en JSON.
            """
            if not self.path.startswith("/api/"):
                super().send_error(code, message, explain)
                return
            cuerpo = json.dumps(
                {"error": message or self.responses[code][0], "codigo": code},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(code, message)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(cuerpo)

        #: La conversación vive en el proceso, no en el cliente: es lo que
        #: desbloquea IT-106. Con un solo visitante ---que es el alcance
        #: declarado--- una sola instancia basta.
        #:
        #: Que baste **lo garantiza el servidor serial, no la buena voluntad**.
        #: Estos dos atributos son de la clase, así que los comparten todas las
        #: conexiones; mientras el servidor tuvo hilos, dos peticiones
        #: solapadas mezclaban historial, ámbito y contador de turno sin
        #: ninguna sincronización, y una persona sola llega a eso cancelando
        #: una respuesta y volviendo a preguntar. Atendiendo de una en una no
        #: hay dos peticiones a la vez que puedan pisarse (IT-129).
        #:
        #: De qué titulación se habla lo decide el modelo en cada turno
        #: (:mod:`tfg_uja.ambito`). Las reglas deterministas sabían fijar el
        #: sujeto pero no soltarlo, y eso apagaba además el rechazo de
        #: preguntas ajenas: medido sobre las diez del conjunto de validación,
        #: el recuperador rechaza 5 en el primer turno y **0 en el noveno**.
        conversacion = Conversacion(
            sistema[2], decisor=decisor_con_modelo(sistema[2], MODELO_GENERATIVO)
        )

        #: Preguntas atendidas. Solo desplaza las sugerencias, y por eso no
        #: vale ``len(conversacion.preguntas())``: esa lista es una ventana de
        #: tres y deja de crecer, de modo que del cuarto turno en adelante se
        #: volvería a proponer siempre lo mismo.
        turno = 0

        def responder_json(self, dato: object) -> None:
            """Manda ``dato`` como JSON, sin guardar copia en la caché."""
            cuerpo = json.dumps(dato, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_GET(self) -> None:  # noqa: N802 (el nombre lo impone la base)
            """Sirve la interfaz, el saludo y las sugerencias del arranque."""
            if self.path == "/api/saludo":
                # El saludo NO pasa por ``/api/chat``, y esa es toda la razón
                # de que esta ruta exista. Cuando el navegador lo pedía como
                # una consulta cualquiera, el servidor anotaba un turno en el
                # registro por cada apertura de la página: una pregunta que
                # nadie había escrito. Cualquier recuento sobre el registro
                # salía inflado, y esconderlo solo en la interfaz habría
                # dejado el dato igual de sucio.
                #
                # El texto sigue viniendo del servidor, que era el motivo de
                # pedírselo: si el cliente lo escribiera, habría dos copias
                # que pueden separarse.
                self.responder_json({"respuesta": RESPUESTA_SALUDO})
                return
            if self.path != "/api/sugerencias":
                super().do_GET()
                return
            self.responder_json(sugerencias_para(sistema[0], [], sistema[2]))

        def peticion_es_de_la_interfaz(self) -> bool:
            """Comprueba que la consulta venga de la interfaz de este proceso.

            Las tres comprobaciones son deliberadamente estrictas y por lista de
            permitidos. Cada una detiene algo distinto:

            * ``Host`` acota a qué nombre se ha llegado, que es lo que rompe el
              reenlace de DNS: ese ataque consiste precisamente en que un
              dominio ajeno resuelva a ``127.0.0.1`` y el proceso local no mire
              a nombre de quién le hablan.
            * ``Origin`` distingue una consulta de la propia página de una
              lanzada desde otra pestaña. El navegador lo pone solo y no deja
              que una página lo falsifique.
            * ``Content-Type`` cierra el hueco que dejan las dos anteriores: un
              formulario ajeno puede enviar ``text/plain`` sin comprobación
              previa, y en algunos casos sin ``Origin``.

            ``Origin`` ausente se admite a propósito: no lo mandan ni ``curl``
            ni las herramientas con las que se prueba el sistema a mano, y
            exigirlo dejaría fuera al propio autor sin cerrar nada ---lo que hay
            que rechazar es un ``Origin`` **ajeno**, no su ausencia.

            Returns:
                ``True`` si las tres cabeceras encajan con la interfaz local.
            """
            if self.headers.get("Host") not in ANFITRIONES_PERMITIDOS:
                return False
            origen = self.headers.get("Origin")
            if origen is not None and origen not in ORIGENES_PERMITIDOS:
                return False
            # El tipo puede traer parámetros: «application/json; charset=utf-8».
            tipo = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            return tipo == TIPO_ESPERADO

        def do_POST(self) -> None:  # noqa: N802 (el nombre lo impone la base)
            """Atiende la consulta y emite la respuesta por partes."""
            if self.path != "/api/chat":
                self.send_error(404)
                return
            if not self.peticion_es_de_la_interfaz():
                # 403 y no 400: la petición está bien formada, lo que pasa es
                # que no viene de donde tiene que venir.
                self.send_error(403, "esta consulta no viene de la interfaz")
                return
            try:
                largo = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self.send_error(400, "Content-Length no es válido")
                return
            if largo < 0:
                self.send_error(400, "Content-Length no puede ser negativo")
                return
            if largo > MAXIMO_CUERPO:
                self.send_error(413)
                return
            try:
                cuerpo = json.loads(self.rfile.read(largo) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                # UnicodeDecodeError no es hija de JSONDecodeError: un cuerpo
                # que no venga en UTF-8 se colaba y reventaba el manejador con
                # una traza, dejando al cliente sin respuesta ninguna.
                self.send_error(400, "el cuerpo no es JSON válido")
                return
            if not isinstance(cuerpo, dict):
                # Una lista, una cadena y ``null`` son JSON válido, pero no el
                # objeto que define el contrato del endpoint. Llamar a ``get``
                # sin comprobarlo soltaba AttributeError y cerraba la conexión.
                self.send_error(400, "el cuerpo JSON debe ser un objeto")
                return
            pregunta = cuerpo.get("pregunta")
            if not isinstance(pregunta, str) or not pregunta.strip():
                self.send_error(400, "falta la pregunta")
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            type(self).turno += 1
            for suceso in partes_de_la_respuesta(
                pregunta, sistema, type(self).conversacion, type(self).turno
            ):
                self.wfile.write(json.dumps(suceso, ensure_ascii=False).encode("utf-8"))
                self.wfile.write(b"\n")
                # Sin esto el texto se queda en el buffer y llega todo junto al
                # final, que es exactamente lo que la emision por partes evita.
                self.wfile.flush()

    return Manejador


def main() -> None:
    """Levanta el servidor.

    Punto de entrada de ``py -m tfg_uja.aplicacion.servidor``.
    """
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if not INDICE.exists():
        print(
            f"No hay índice en {INDICE}. Se construye con "
            "«py -m tfg_uja.indexacion.indexer data/chunks.json data/indice_lance»."
        )
        raise SystemExit(1)
    print(f"Abriendo el índice de {INDICE}…")
    atender = partial(manejador(abrir_sistema()), directory=str(WEB))
    # Serial a proposito: ver el docstring del modulo. El alcance es un solo
    # visitante, y atender de uno en uno es lo que hace correcto compartir una
    # sola conversacion en vez de ser una carrera.
    servidor = HTTPServer(("127.0.0.1", PUERTO), atender)
    print(f"Asistente en http://127.0.0.1:{PUERTO}  (Ctrl+C para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nParando.")


if __name__ == "__main__":
    main()

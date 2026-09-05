"""Punto de entrada HTTP de la aplicación web (IT-44)."""

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

# La interfaz sirve todos sus recursos desde el mismo origen y no usa código en línea.
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

# Host y Origin restringen las consultas a la interfaz local y evitan peticiones de
# otras páginas.

#: Esto no es CORS: CORS sirve para abrir el acceso a terceros y aquí lo que
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

# Exige JSON para impedir el envío desde formularios ajenos con text/plain.
TIPO_ESPERADO: Final[str] = "application/json"


#: Cómo se nombra en pantalla cada tipo de fragmento. La colección los marca
#: con una etiqueta corta que no significa nada para quien pregunta.

# Traducciones de los siete valores de origen presentes en el corpus.
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
    """Direccion oficial de la EPSJ para cada unidad de la coleccion."""
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
    """Pagina del plan y de las salidas de cada titulacion."""
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
    """Direccion oficial de la unidad de un fragmento, o cadena vacia."""
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
    """Unidades de la colección que se le entregaron al modelo para responder."""
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
    """Recorre el sistema y va soltando lo que hay que mandar al navegador."""
    tabla, incrustar, catalogo, distancia = sistema
    arranque = time.monotonic()
    # El ámbito se copia ANTES de preparar la consulta: preparar no lo cambia,
    # pero anotar sí, y lo que interesa del registro es precisamente en qué
    # turno cambió de titulación.
    ambito_antes = list(conversacion.ambito)
    # Reproducido contra el sistema real: «Hola» anunciaba 16 fuentes,
    # las dieciséis de la misma titulación, porque se recuperaba primero y se
    # decidía después. Preguntarlo aquí es lo que lo corta.
    fija = respuesta_fija(pregunta)
    # Resuelve la respuesta fija antes de consultar al decisor de ámbito.
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
        """Deja el turno en el registro con el estado tal como esté ahora."""
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
    # Anota el texto entregado; una respuesta fija no modifica el ámbito.
    conversacion.anotar(pregunta, entero, cambia_ambito=fija is None)
    # Se registra DESPUÉS de anotar, que es donde la conversación fija de qué
    # titulación se está hablando: registrarlo antes guardaría siempre el
    # ámbito del turno anterior.
    registrar()
    # Calcula las sugerencias después de actualizar el ámbito de la conversación.
    try:
        propuestas = sugerencias_para(tabla, conversacion.ambito, catalogo, turno)
    except Exception as fallo:  # noqa: BLE001
        _registro.warning("No se han podido calcular las sugerencias: %s", fallo)
        propuestas = []
    yield {"sugerencias": propuestas}
    yield {"fin": True}


def abrir_sistema() -> tuple[Any, Any, list[str], str]:
    """Abre el índice y el incrustador una sola vez, al arrancar."""
    return (
        abrir_indice(INDICE, MODELO_INCRUSTACIONES),
        incrustador_de_consultas(MODELO_INCRUSTACIONES),
        catalogo_del_indice(INDICE),
        distancia_del_indice(INDICE),
    )


def manejador(sistema: tuple[Any, Any, list[str], str]) -> type:
    """Construye el manejador con el sistema ya abierto dentro."""

    class Manejador(SimpleHTTPRequestHandler):
        """Sirve ``web/`` y atiende ``POST /api/chat``."""

        def version_string(self) -> str:
            """Cabecera ``Server`` sin número de versión."""
            return "asistente-epsj"

        def end_headers(self) -> None:
            """Añade las cabeceras defensivas a todas las respuestas."""
            for nombre, valor in CABECERAS_DEFENSIVAS.items():
                self.send_header(nombre, valor)
            super().end_headers()

        def send_error(  # type: ignore[override]
            self,
            code: int,
            message: str | None = None,
            explain: str | None = None,
        ) -> None:
            """Responde en JSON cuando el fallo es de la API."""
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

        # El servidor serial evita que conexiones simultáneas modifiquen estos atributos
        # compartidos.

        # El decisor puede cambiar o soltar el ámbito en cada turno.
        conversacion = Conversacion(
            sistema[2], decisor=decisor_con_modelo(sistema[2], MODELO_GENERATIVO)
        )

        # Contador independiente de la ventana de preguntas para seguir rotando las
        # sugerencias.
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
                # El saludo tiene ruta propia para no registrar una pregunta que el
                # visitante no escribió.
                self.responder_json({"respuesta": RESPUESTA_SALUDO})
                return
            if self.path != "/api/sugerencias":
                super().do_GET()
                return
            self.responder_json(sugerencias_para(sistema[0], [], sistema[2]))

        def peticion_es_de_la_interfaz(self) -> bool:
            """Comprueba que la consulta venga de la interfaz de este proceso."""
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
    """Levanta el servidor."""
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if not INDICE.exists():
        print(
            f"No hay índice en {INDICE}. Se construye con "
            "«py -m tfg_uja.indexacion.indexer data/chunks.json data/indice_lance»."
        )
        raise SystemExit(1)
    print(f"Abriendo el índice de {INDICE}…")
    atender = partial(manejador(abrir_sistema()), directory=str(WEB))
    # El servidor serial permite compartir una conversación sin carreras.
    servidor = HTTPServer(("127.0.0.1", PUERTO), atender)
    print(f"Asistente en http://127.0.0.1:{PUERTO}  (Ctrl+C para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nParando.")


if __name__ == "__main__":
    main()

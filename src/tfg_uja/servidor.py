"""Punto de entrada HTTP de la aplicación web (IT-44).

Sirve la interfaz de ``web/`` y atiende ``POST /api/chat``, que devuelve la
respuesta **por partes** según la decisión del ADR-0006: una línea JSON por
unidad ya verificada.

**Por qué la biblioteca estándar y no un marco de trabajo.** Medido el
24/08/2026 con ``pip install --dry-run`` contra lo que el sistema necesita para
funcionar: ``http.server`` añade 0 paquetes, Starlette 2, FastAPI 3 y Flask 4.
Lo que hay que atender es un endpoint y unos ficheros estáticos, y el cuello de
botella es el modelo, que responde con una mediana de 62,7 s: ninguna capa HTTP
cambia eso.

⚠️ **No es apto para producción**, y así está declarado: atiende en serie, no
limita el tamaño de la petición y no da HTTPS. El despliegue en producción está
fuera del alcance de este trabajo (reparto MoSCoW del Capítulo 4). Para llevarlo
allí harían falta un servidor WSGI/ASGI real tras un proxy inverso, HTTPS,
límites de tasa y de tamaño, y sobre todo resolver que el modelo atiende de uno
en uno.

**La lógica no vive en el manejador.** :func:`partes_de_la_respuesta` no sabe
nada de HTTP y se prueba entera sin red y sin modelo; el manejador solo la
enchufa con el socket.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final

from tfg_uja.conversacion import Conversacion
from tfg_uja.generador import ErrorDelModelo, responder_por_partes
from tfg_uja.incrustaciones import MODELO as MODELO_INCRUSTACIONES
from tfg_uja.incrustaciones import incrustador_de_consultas
from tfg_uja.recuperador import (
    K_MAXIMO,
    abrir_indice,
    catalogo_del_indice,
    contexto_para,
    distancia_del_indice,
)

RAIZ: Final[Path] = Path(__file__).resolve().parent.parent.parent

#: Interfaz estática. Se sirve desde el mismo proceso que el endpoint, que es
#: lo que decide el ADR de arquitectura de la Fase 3.
WEB: Final[Path] = RAIZ / "web"

#: Índice vectorial. No se versiona: se construye con ``py -m tfg_uja.indexer``.
INDICE: Final[Path] = RAIZ / "data" / "indice_lance"

MODELO_GENERATIVO: Final[str] = "gemma3:12b"

PUERTO: Final[int] = 8000

#: Tope del cuerpo de la petición. Una pregunta no ocupa esto ni de lejos; está
#: para que un cuerpo enorme no se lea entero en memoria.
MAXIMO_CUERPO: Final[int] = 8 * 1024


#: Como se nombra en pantalla cada tipo de fragmento. La colección los marca
#: con una etiqueta corta que no significa nada para quien pregunta.
ROTULOS_DE_ORIGEN: Final[dict[str, str]] = {
    "guia": "Guía docente",
    "sin_guia": "Asignatura sin guía publicada",
    "plan": "Plan de estudios",
    "mencion": "Menciones",
    "salidas": "Salidas profesionales",
    "ficha": "Ficha de la titulación",
    "catalogo": "Catálogo de titulaciones",
}


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
            }
    return list(vistas.values())


def partes_de_la_respuesta(
    pregunta: str,
    sistema: tuple[Any, Any, list[str], str],
    conversacion: Conversacion,
) -> Iterator[dict[str, object]]:
    """Recorre el sistema y va soltando lo que hay que mandar al navegador.

    No toca HTTP: devuelve los objetos tal cual, y quien los serialice decide
    cómo. Así se prueba el recorrido entero sin levantar un socket.

    Args:
        pregunta: Lo que ha escrito el estudiante.
        sistema: ``(tabla, incrustar, catalogo, distancia)``, ya abierto.
        conversacion: Estado del diálogo, que se actualiza aquí.

    Yields:
        ``{"fuentes": [...]}`` con las unidades recuperadas, ``{"parte": ...}``
        por cada unidad verificada, ``{"borrar": True}`` cuando la respuesta se
        retira a media emisión, y ``{"error": ...}`` si el modelo no responde.
    """
    tabla, incrustar, catalogo, distancia = sistema
    consulta = conversacion.preparar(pregunta)
    fragmentos = contexto_para(
        consulta.texto,
        tabla,
        incrustar,
        respaldo=consulta.respaldo,
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
    try:
        partes = responder_por_partes(
            pregunta,
            fragmentos,
            MODELO_GENERATIVO,
            historial=[(p, "") for p in conversacion.preguntas()],
            ambito=consulta.ambito[0] if len(consulta.ambito) == 1 else None,
            catalogo=catalogo,
        )
        for parte in partes:
            if parte is None:
                entero = ""
                yield {"borrar": True}
                continue
            entero += parte
            yield {"parte": parte}
    except ErrorDelModelo as fallo:
        yield {"error": str(fallo)}
        return
    # Se anota lo que de verdad se ha entregado: si hubo retirada, lo que queda
    # anotado es la respuesta fija y no el texto retirado.
    conversacion.anotar(pregunta, entero)
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
        La clase de manejador lista para ``ThreadingHTTPServer``.
    """

    class Manejador(SimpleHTTPRequestHandler):
        """Sirve ``web/`` y atiende ``POST /api/chat``."""

        #: La conversación vive en el proceso, no en el cliente: es lo que
        #: desbloquea IT-106. Con un solo visitante ---que es el alcance
        #: declarado--- una sola instancia basta.
        conversacion = Conversacion(sistema[2])

        def do_POST(self) -> None:  # noqa: N802 (el nombre lo impone la base)
            """Atiende la consulta y emite la respuesta por partes."""
            if self.path != "/api/chat":
                self.send_error(404)
                return
            largo = int(self.headers.get("Content-Length") or 0)
            if largo > MAXIMO_CUERPO:
                self.send_error(413)
                return
            try:
                pregunta = json.loads(self.rfile.read(largo) or b"{}").get("pregunta")
            except json.JSONDecodeError:
                self.send_error(400, "el cuerpo no es JSON válido")
                return
            if not isinstance(pregunta, str) or not pregunta.strip():
                self.send_error(400, "falta la pregunta")
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            for suceso in partes_de_la_respuesta(
                pregunta, sistema, type(self).conversacion
            ):
                self.wfile.write(json.dumps(suceso, ensure_ascii=False).encode("utf-8"))
                self.wfile.write(b"\n")
                # Sin esto el texto se queda en el buffer y llega todo junto al
                # final, que es exactamente lo que la emision por partes evita.
                self.wfile.flush()

    return Manejador


def main() -> None:
    """Levanta el servidor. Punto de entrada de ``py -m tfg_uja.servidor``."""
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if not INDICE.exists():
        print(
            f"No hay índice en {INDICE}. Se construye con "
            "«py -m tfg_uja.indexer data/chunks.json data/indice_lance»."
        )
        raise SystemExit(1)
    print(f"Abriendo el índice de {INDICE}…")
    atender = partial(manejador(abrir_sistema()), directory=str(WEB))
    servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), atender)
    print(f"Asistente en http://127.0.0.1:{PUERTO}  (Ctrl+C para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nParando.")


if __name__ == "__main__":
    main()

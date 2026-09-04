"""Pruebas del punto de entrada HTTP (IT-44).

**Ninguna abre un socket.** El manejador se ejercita con ``rfile`` y ``wfile``
falsos, que es lo que permite el diseño: la lógica vive en
:func:`partes_de_la_respuesta`, que no sabe nada de HTTP, y el manejador solo la
enchufa. Si hubiera que levantar un servidor de verdad para probar esto, sería
señal de que la lógica está en el sitio equivocado.
"""

from __future__ import annotations

import io
from http.server import SimpleHTTPRequestHandler
import json
import logging
import socketserver
from pathlib import Path
from typing import Any

import pytest

from tfg_uja.aplicacion import registro_chat, servidor

# Se enlazan al importar, ANTES de que la fixture de aislamiento sustituya
# los atributos del modulo: las cuatro pruebas de enlaces necesitan la
# implementacion de verdad y no el sustituto vacio.
from tfg_uja.aplicacion.servidor import enlaces_oficiales as _ENLACES_REALES
from tfg_uja.aplicacion.servidor import paginas_de_titulacion as _PAGINAS_REALES
from tfg_uja.dialogo.conversacion import Consulta, Conversacion
from tfg_uja.dialogo.recuperador import Fragmento
from tfg_uja.dialogo.generador import (
    ErrorDelModelo,
    RESPUESTA_SALUDO,
    RESPUESTA_TITULACION_INVENTADA,
)


class ConversacionFalsa:
    """Recuerda lo anotado y devuelve una consulta sin ámbito."""

    def __init__(self) -> None:
        self.anotado: list[tuple[str, str]] = []
        self.ambito: list[str] = []
        self.cambios_de_ambito: list[bool] = []

    def preparar(self, texto: str) -> Consulta:
        # Se devuelve la `Consulta` de verdad y no un objeto inventado al
        # vuelo: el falso no tenía el campo `abierta`, así que al añadirlo al
        # tipo real estas pruebas seguían en verde midiendo una forma de
        # consulta que ya no existía.
        return Consulta(texto=texto, ambito=[])

    def preguntas(self) -> list[str]:
        return [p for p, _ in self.anotado]

    def anotar(self, pregunta: str, respuesta: str, cambia_ambito: bool = True) -> None:
        self.anotado.append((pregunta, respuesta))
        # Se guarda para poder comprobar que una respuesta fija no reapunta el
        # ámbito: es lo único que distingue ese turno de uno normal.
        self.cambios_de_ambito.append(cambia_ambito)


SISTEMA_FALSO: tuple[Any, Any, list[str], str] = (
    "tabla",
    "incrustar",
    ["Grado en Ingeniería Informática"],
    "cosine",
)


def frag(
    nombre: str, origen: str = "guia", grado: str = "Grado en Ingeniería Informática"
) -> Fragmento:
    """Un fragmento con lo justo para las pruebas de este módulo."""
    return Fragmento(
        texto="x",
        nombre=nombre,
        grados=[grado],
        origen=origen,
        distancia=0.1,
        chunk_index=0,
        total_chunks=1,
    )


@pytest.fixture(autouse=True)
def sin_sugerencias(monkeypatch: pytest.MonkeyPatch) -> None:
    """Las sugerencias consultan el índice; aquí no hay índice que consultar.

    Se anulan en todas las pruebas de este módulo a propósito: lo que se está
    midiendo es el recorrido de la respuesta, y el módulo de sugerencias tiene
    sus propias pruebas contra un índice de verdad.
    """
    monkeypatch.setattr(servidor, "sugerencias_para", lambda *a, **k: [])


@pytest.fixture(autouse=True)
def registro(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Cada prueba escribe en su propio registro, nunca en el de ``data/``.

    Va con ``autouse`` a propósito: cualquier prueba que recorra el sistema
    deja una línea, y sin esto la tanda entera iría ensuciando el registro de
    las conversaciones de verdad.
    """
    destino = tmp_path / "registro_chat.jsonl"
    monkeypatch.setattr(registro_chat, "REGISTRO", destino)
    return destino


def turnos_de(registro: Path) -> list[dict[str, Any]]:
    """Lee el registro línea a línea, que es como está pensado para leerse."""
    if not registro.exists():
        return []
    crudo = registro.read_text(encoding="utf-8").splitlines()
    return [json.loads(linea) for linea in crudo if linea]


@pytest.fixture
def sin_recuperador(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evita tocar el índice: el recuperador devuelve siempre un fragmento."""
    monkeypatch.setattr(
        servidor,
        "contexto_para",
        lambda *a, **k: [frag("Fundamentos de la programación")],
    )


def test_cada_unidad_verificada_sale_como_una_linea(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None
) -> None:
    """El recorrido normal emite una parte por unidad y cierra con «fin»."""
    monkeypatch.setattr(
        servidor, "responder_por_partes", lambda *a, **k: iter(["Uno. ", "Dos."])
    )
    conversacion = ConversacionFalsa()

    sucesos = list(servidor.partes_de_la_respuesta("¿Y?", SISTEMA_FALSO, conversacion))

    assert sucesos[0]["fuentes"] == [
        {
            "nombre": "Fundamentos de la programación",
            "titulacion": "Grado en Ingeniería Informática",
            "origen": "Guía docente",
            # Vacía porque esta prueba corre sin dataset: lo que se comprueba
            # aquí es la forma del suceso, no de dónde sale la dirección.
            "url": "",
        }
    ]
    assert sucesos[1:] == [
        {"parte": "Uno. "},
        {"parte": "Dos."},
        {"sugerencias": []},
        {"fin": True},
    ]
    assert conversacion.anotado == [("¿Y?", "Uno. Dos.")]


def test_una_retirada_manda_borrar_y_no_anota_el_texto_retirado(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None
) -> None:
    """Lo que se anota es lo entregado, nunca lo que se retiró.

    Si se anotara el texto retirado, el turno siguiente heredaría como ámbito
    una titulación que el sistema acaba de declarar inexistente.
    """
    monkeypatch.setattr(
        servidor,
        "responder_por_partes",
        lambda *a, **k: iter(["Te recomiendo el Grado en Magia. ", None, "No existe."]),
    )
    conversacion = ConversacionFalsa()

    sucesos = list(servidor.partes_de_la_respuesta("¿Y?", SISTEMA_FALSO, conversacion))

    assert {"borrar": True} in sucesos
    assert conversacion.anotado == [("¿Y?", "No existe.")]


def test_si_el_modelo_no_responde_sale_un_error_y_no_un_cuelgue(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None
) -> None:
    """Un servidor de inferencia caído tiene que llegar al navegador como tal."""

    def revienta(*a: Any, **k: Any) -> Any:
        raise ErrorDelModelo("Ollama no responde")
        yield  # pragma: no cover

    monkeypatch.setattr(servidor, "responder_por_partes", revienta)

    sucesos = list(
        servidor.partes_de_la_respuesta("¿Y?", SISTEMA_FALSO, ConversacionFalsa())
    )

    assert sucesos[-1] == {"error": "Ollama no responde"}


# --------------------------------------------------------------- el manejador


def manejador_falso(
    cuerpo: bytes,
    ruta: str = "/api/chat",
    largo: int | str | None = None,
    Clase: type | None = None,
    cabeceras: dict[str, str] | None = None,
):
    """Crea un manejador sin socket, con la petición ya puesta dentro.

    ``Clase`` se pasa cuando la prueba necesita **dos peticiones seguidas del
    mismo servidor**: la conversación y la cuenta de turnos viven en la clase,
    así que construir una nueva por cada petición es empezar de cero.

    Las cabeceras por omisión son las de una petición legítima de la interfaz
    (IT-129). ``cabeceras`` las sustituye o añade, y un valor ``None`` borra la
    cabecera, que es como se prueba que falte.
    """
    Clase = Clase or servidor.manejador(SISTEMA_FALSO)
    m = Clase.__new__(Clase)
    m.path = ruta
    m.rfile = io.BytesIO(cuerpo)
    m.wfile = io.BytesIO()
    m.headers = {
        "Content-Length": str(len(cuerpo) if largo is None else largo),
        "Host": f"127.0.0.1:{servidor.PUERTO}",
        "Origin": f"http://127.0.0.1:{servidor.PUERTO}",
        "Content-Type": "application/json",
    }
    for nombre, valor in (cabeceras or {}).items():
        if valor is None:
            m.headers.pop(nombre, None)
        else:
            m.headers[nombre] = valor
    m.errores: list[tuple[int, str | None]] = []
    m.send_error = lambda codigo, mensaje=None: m.errores.append((codigo, mensaje))
    m.send_response = lambda *a, **k: None
    m.send_header = lambda *a, **k: None
    m.end_headers = lambda: None
    return m


@pytest.mark.parametrize(
    "cabeceras, porque",
    [
        ({"Host": "ejemplo.com"}, "un Host ajeno es el vector del reenlace de DNS"),
        ({"Host": None}, "sin Host no se sabe a nombre de quién se ha llegado"),
        ({"Origin": "http://ejemplo.com"}, "la consulta viene de otra página"),
        ({"Content-Type": "text/plain"}, "lo que manda un formulario ajeno"),
        ({"Content-Type": None}, "sin declarar el tipo tampoco se acepta"),
    ],
)
def test_una_consulta_que_no_viene_de_la_interfaz_se_rechaza(
    cabeceras: dict[str, str], porque: str
) -> None:
    """Regresión de IT-129: ``/api/chat`` atendía a cualquiera.

    Comprobado antes del arreglo: una petición con ``Origin`` y ``Host`` ajenos
    y ``Content-Type: text/plain`` se contestaba con un 200. Una página abierta
    en otra pestaña podía lanzar consultas, mover el estado de la conversación
    y ensuciar el registro.

    Se responde 403 y no 400 a propósito: la petición está bien formada, lo que
    falla es de dónde viene.
    """
    cuerpo = json.dumps({"pregunta": "¿qué asignaturas tiene?"}).encode("utf-8")
    m = manejador_falso(cuerpo, cabeceras=cabeceras)

    m.do_POST()

    assert m.errores and m.errores[0][0] == 403, porque
    assert sucesos_de(m) == [], "no puede haberse respondido nada"


@pytest.mark.parametrize(
    "cabeceras",
    [
        {},
        {"Host": f"localhost:{servidor.PUERTO}"},
        {"Origin": f"http://localhost:{servidor.PUERTO}"},
        # El tipo puede traer parámetros y sigue siendo el mismo tipo.
        {"Content-Type": "application/json; charset=utf-8"},
        # `curl` y las herramientas con las que se prueba a mano no mandan
        # Origin. Lo que hay que rechazar es un Origin ajeno, no su ausencia.
        {"Origin": None},
    ],
)
def test_la_interfaz_local_sigue_pudiendo_preguntar(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None, cabeceras: dict[str, str]
) -> None:
    """La barrera no puede dejar fuera a quien tiene que entrar."""
    monkeypatch.setattr(
        servidor, "responder_por_partes", lambda *a, **k: iter(["Hola."])
    )
    cuerpo = json.dumps({"pregunta": "¿qué asignaturas tiene?"}).encode("utf-8")
    m = manejador_falso(cuerpo, cabeceras=cabeceras)

    m.do_POST()

    assert m.errores == []
    assert sucesos_de(m)


def test_el_servidor_atiende_de_una_peticion_en_una() -> None:
    """IT-129: es lo que hace correcto compartir una sola conversación.

    ``conversacion`` y ``turno`` son atributos de la clase de manejador, o sea
    compartidos por todas las conexiones. Con ``ThreadingHTTPServer`` dos
    peticiones solapadas mezclaban historial, ámbito y contador sin ninguna
    sincronización, y a eso llega una persona sola cancelando una respuesta y
    volviendo a preguntar.

    Se comprueba la clase que se instancia, no un comportamiento con hilos:
    montar dos peticiones concurrentes de verdad para demostrar que no hay
    concurrencia sería una prueba lenta y con carreras propias.
    """
    from http.server import ThreadingHTTPServer

    assert servidor.HTTPServer is not ThreadingHTTPServer
    assert not issubclass(servidor.HTTPServer, socketserver.ThreadingMixIn)


def sucesos_de(m: Any) -> list[dict[str, object]]:
    """Lee lo que el manejador ha escrito, línea a línea."""
    crudo = m.wfile.getvalue().decode("utf-8")
    return [json.loads(linea) for linea in crudo.splitlines() if linea]


def test_el_manejador_emite_una_linea_json_por_parte(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None
) -> None:
    """Que es el contrato que espera el navegador.

    La pregunta tiene que ser una de verdad y no un «hola»: un saludo se
    contesta con texto fijo, no se recupera nada y no sale la línea de
    fuentes, que es la que aquí se salta con el ``[1:]``.
    """
    monkeypatch.setattr(
        servidor, "responder_por_partes", lambda *a, **k: iter(["Hola."])
    )
    cuerpo = json.dumps({"pregunta": "¿qué asignaturas tiene?"}).encode("utf-8")
    m = manejador_falso(cuerpo)

    m.do_POST()

    assert sucesos_de(m)[1:] == [
        {"parte": "Hola."},
        {"sugerencias": []},
        {"fin": True},
    ]


@pytest.mark.parametrize(
    ("cuerpo", "ruta", "largo", "codigo"),
    [
        (b'{"pregunta":"x"}', "/otra", None, 404),
        (b"no soy json", "/api/chat", None, 400),
        # JSON válido no significa contrato válido: las tres formas siguientes
        # no tienen ``.get`` y antes derribaban el manejador con AttributeError.
        (b"[]", "/api/chat", None, 400),
        (b'"pregunta"', "/api/chat", None, 400),
        (b"null", "/api/chat", None, 400),
        (b'{"pregunta":"   "}', "/api/chat", None, 400),
        (b'{"otra":"cosa"}', "/api/chat", None, 400),
        # El encabezado lo controla el cliente. Convertirlo sin comprobarlo
        # soltaba ValueError; admitir uno negativo pediría leer hasta EOF.
        (b"{}", "/api/chat", "no-es-un-entero", 400),
        (b"{}", "/api/chat", -1, 400),
        (b"{}", "/api/chat", servidor.MAXIMO_CUERPO + 1, 413),
        # Regresion: un cuerpo que no viene en UTF-8 reventaba el manejador con
        # una traza en vez de contestar 400, y el cliente se quedaba sin nada.
        ('{"pregunta":"¿y?"}'.encode("cp1252"), "/api/chat", None, 400),
    ],
)
def test_las_peticiones_mal_formadas_no_llegan_al_modelo(
    cuerpo: bytes, ruta: str, largo: int | str | None, codigo: int
) -> None:
    """Se rechazan antes de gastar un minuto de modelo en ellas."""
    m = manejador_falso(cuerpo, ruta, largo)

    m.do_POST()

    assert m.errores[0][0] == codigo
    assert m.wfile.getvalue() == b""


def test_el_ambito_multiple_llega_entero_al_generador(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None
) -> None:
    """RU-04 perdería una titulación si el servidor redujera la lista a una."""
    informatica = "Grado en Ingeniería Informática"
    mecanica = "Grado en Ingeniería Mecánica"
    recibidos: list[list[str]] = []

    class ConversacionComparativa(ConversacionFalsa):
        """Devuelve la consulta múltiple que produce la conversación real."""

        def preparar(self, texto: str) -> Consulta:
            return Consulta(texto=texto, ambito=[informatica, mecanica])

    def responder_falso(*args: Any, **opciones: Any):
        recibidos.append(opciones["ambito"])
        yield "Comparación."

    monkeypatch.setattr(servidor, "responder_por_partes", responder_falso)

    list(
        servidor.partes_de_la_respuesta(
            "Compara Informática y Mecánica",
            SISTEMA_FALSO,
            ConversacionComparativa(),
        )
    )

    assert recibidos == [[informatica, mecanica]]


def test_la_cabecera_server_no_dice_la_version() -> None:
    """Anunciaba «SimpleHTTP/0.6 Python/3.13.5».

    Eso le dice a quien pregunte qué biblioteca y qué intérprete hay detrás, y
    solo le sirve a quien busca por dónde entrar. El servicio se sigue
    identificando: lo que desaparece es la versión.
    """
    m = manejador_falso(b"{}")

    firma = m.version_string()

    assert firma == "asistente-epsj"
    assert not any(c.isdigit() for c in firma), firma


def test_toda_respuesta_lleva_las_cabeceras_defensivas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Se ponen en ``end_headers`` y no en cada punto de salida.

    Hay cinco sitios distintos donde el manejador termina una respuesta. Una
    cabecera que se olvide en uno de ellos no falla: sirve la respuesta sin
    protección, y eso no se ve mirando la aplicación.
    """
    puestas: list[tuple[str, str]] = []
    Clase = servidor.manejador(SISTEMA_FALSO)
    m = Clase.__new__(Clase)
    m.send_header = lambda nombre, valor: puestas.append((nombre, valor))
    # La de la clase base escribe en un socket que aquí no existe.
    monkeypatch.setattr(SimpleHTTPRequestHandler, "end_headers", lambda self: None)

    m.end_headers()

    assert dict(puestas) == servidor.CABECERAS_DEFENSIVAS


def test_la_politica_de_contenido_no_admite_nada_en_linea() -> None:
    """Si admitiera ``'unsafe-inline'`` no protegería de una inyección.

    Puede ser estricta porque la página no tiene ``<script>`` ni ``style=`` en
    el marcado y no carga nada de fuera: todo lo que pide es suyo.
    """
    politica = servidor.CABECERAS_DEFENSIVAS["Content-Security-Policy"]

    assert "unsafe-inline" not in politica
    assert "unsafe-eval" not in politica
    assert "frame-ancestors 'none'" in politica
    assert "default-src 'self'" in politica


def test_un_error_de_la_api_se_responde_en_json() -> None:
    """El endpoint operaba en JSON y fallaba en HTML, y además en inglés.

    Un cliente tenía que saber distinguir dos formatos según le fuera bien o
    mal, cuando la interfaz y el atributo ``lang`` están en español.
    """
    Clase = servidor.manejador(SISTEMA_FALSO)
    m = Clase.__new__(Clase)
    m.path = "/api/chat"
    m.command = "POST"
    m.wfile = io.BytesIO()
    m.send_response = lambda *a, **k: None
    m.send_header = lambda *a, **k: None
    m.end_headers = lambda: None

    m.send_error(400, "falta la pregunta")

    assert json.loads(m.wfile.getvalue()) == {
        "error": "falta la pregunta",
        "codigo": 400,
    }


def test_un_error_fuera_de_la_api_sigue_siendo_una_pagina(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quien se equivoca de dirección es un navegador, no un cliente de la API.

    Una página de error se lee; un objeto JSON en pantalla, no.
    """
    recibidos: list[int] = []
    monkeypatch.setattr(
        SimpleHTTPRequestHandler,
        "send_error",
        lambda self, code, message=None, explain=None: recibidos.append(code),
    )
    Clase = servidor.manejador(SISTEMA_FALSO)
    m = Clase.__new__(Clase)
    m.path = "/pagina-que-no-existe"

    m.send_error(404)

    assert recibidos == [404]


def test_un_error_de_la_api_sin_mensaje_usa_el_de_la_biblioteca() -> None:
    """``send_error(413)`` se llama sin motivo cuando el cuerpo es enorme."""
    Clase = servidor.manejador(SISTEMA_FALSO)
    m = Clase.__new__(Clase)
    m.path = "/api/chat"
    m.command = "POST"
    m.wfile = io.BytesIO()
    m.send_response = lambda *a, **k: None
    m.send_header = lambda *a, **k: None
    m.end_headers = lambda: None

    m.send_error(413)

    devuelto = json.loads(m.wfile.getvalue())
    assert devuelto["codigo"] == 413
    assert devuelto["error"]


def test_una_peticion_head_a_la_api_no_lleva_cuerpo() -> None:
    """Lo exige HTTP: una respuesta a HEAD no tiene cuerpo, tenga el código
    que tenga."""
    Clase = servidor.manejador(SISTEMA_FALSO)
    m = Clase.__new__(Clase)
    m.path = "/api/chat"
    m.command = "HEAD"
    m.wfile = io.BytesIO()
    m.send_response = lambda *a, **k: None
    m.send_header = lambda *a, **k: None
    m.end_headers = lambda: None

    m.send_error(404)

    assert m.wfile.getvalue() == b""


def test_sin_indice_el_arranque_avisa_en_vez_de_reventar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un clon limpio no tiene índice: hay que decir cómo se construye."""
    monkeypatch.setattr(servidor, "INDICE", tmp_path / "no-existe")

    with pytest.raises(SystemExit):
        servidor.main()

    assert "py -m tfg_uja.indexacion.indexer" in capsys.readouterr().out


def test_el_arranque_levanta_el_servidor_y_se_para_con_ctrl_c(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ctrl+C tiene que parar limpio, no soltar una traza por pantalla."""
    (tmp_path / "indice").mkdir()
    monkeypatch.setattr(servidor, "INDICE", tmp_path / "indice")
    monkeypatch.setattr(servidor, "abrir_sistema", lambda: SISTEMA_FALSO)

    class ServidorFalso:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

    monkeypatch.setattr(servidor, "HTTPServer", ServidorFalso)

    servidor.main()

    assert "Parando." in capsys.readouterr().out


def test_abrir_sistema_devuelve_las_cuatro_piezas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El índice se abre una vez al arrancar, no en cada pregunta."""
    monkeypatch.setattr(servidor, "abrir_indice", lambda *a: "tabla")
    monkeypatch.setattr(servidor, "incrustador_de_consultas", lambda *a: "incrustar")
    monkeypatch.setattr(servidor, "catalogo_del_indice", lambda *a: ["Grado"])
    monkeypatch.setattr(servidor, "distancia_del_indice", lambda *a: "cosine")

    assert servidor.abrir_sistema() == ("tabla", "incrustar", ["Grado"], "cosine")


def test_la_respuesta_fija_de_retirada_es_la_del_modulo() -> None:
    """Regresión: la retirada no puede inventarse un texto propio."""
    assert "no" in RESPUESTA_TITULACION_INVENTADA.lower()


# ----------------------------------------------------------------- las fuentes


def test_los_fragmentos_de_una_misma_unidad_son_una_sola_fuente() -> None:
    """Una guía larga se trocea en varios fragmentos y sigue siendo una fuente.

    Listarlos uno a uno repetiría tres veces la misma línea y daría a entender
    que la respuesta se apoya en tres sitios distintos.
    """
    trozos = [frag("Estadística"), frag("Estadística"), frag("Álgebra")]

    assert [f["nombre"] for f in servidor.fuentes_de(trozos)] == [
        "Estadística",
        "Álgebra",
    ]


def test_la_misma_asignatura_en_dos_grados_no_se_funde() -> None:
    """Regresión de la identidad de una asignatura.

    Una guía compartida se imparte en varias titulaciones y el nombre a solas
    no la identifica: la clave lleva también las titulaciones.
    """
    trozos = [
        frag("Física", grado="Grado en Ingeniería Eléctrica"),
        frag("Física", grado="Grado en Ingeniería Mecánica"),
    ]

    assert len(servidor.fuentes_de(trozos)) == 2


def test_el_origen_se_dice_en_castellano_y_lo_desconocido_pasa_tal_cual() -> None:
    """La etiqueta de la colección no significa nada para quien pregunta."""
    fuentes = servidor.fuentes_de(
        [frag("Salidas", origen="salidas"), frag("X", origen="raro")]
    )

    assert [f["origen"] for f in fuentes] == ["Salidas profesionales", "raro"]


def test_los_siete_origenes_del_corpus_tienen_rotulo() -> None:
    """Regresión: tres de los siete se escribieron de memoria y estaban mal.

    Un origen sin rótulo no rompe nada ---sale tal cual---, así que el fallo
    solo se ve mirando la pantalla. Aquí quedan fijados los nombres reales,
    contados sobre la colección.
    """
    del_corpus = {
        "guia",
        "asignatura_sin_guia",
        "plan_de_estudios",
        "mencion",
        "salidas",
        "ficha_titulacion",
        "catalogo",
    }

    assert del_corpus == set(servidor.ROTULOS_DE_ORIGEN)


def test_sin_fragmentos_recuperados_no_se_anuncian_fuentes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un botón de fuentes vacío diría que hay respaldo donde no lo hay."""
    monkeypatch.setattr(servidor, "contexto_para", lambda *a, **k: [])
    monkeypatch.setattr(
        servidor, "responder_por_partes", lambda *a, **k: iter(["Nada."])
    )

    sucesos = list(
        servidor.partes_de_la_respuesta("¿Y?", SISTEMA_FALSO, ConversacionFalsa())
    )

    assert not any("fuentes" in s for s in sucesos)


# ------------------------------------------------------------ las sugerencias


@pytest.fixture(autouse=True)
def sin_enlaces_del_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Desconecta las fuentes del ``grados.json`` real.

    Las direcciones oficiales se resuelven leyendo el dataset, que no se
    versiona y cuyo contenido cambia cada vez que se rastrea la web. Una prueba
    que dependiera de él afirmaría cosas distintas segun el dia. Las pruebas
    que sí miran los enlaces se traen su propio fichero.
    """
    monkeypatch.setattr(servidor, "enlaces_oficiales", lambda *a, **k: {})
    monkeypatch.setattr(servidor, "paginas_de_titulacion", lambda *a, **k: {})


def manejador_get(ruta: str):
    """Un manejador preparado para una petición GET, también sin socket."""
    Clase = servidor.manejador(SISTEMA_FALSO)
    m = Clase.__new__(Clase)
    m.path = ruta
    m.wfile = io.BytesIO()
    m.cabeceras: list[tuple[str, str]] = []
    m.send_response = lambda *a, **k: None
    m.send_header = lambda clave, valor: m.cabeceras.append((clave, valor))
    m.end_headers = lambda: None
    return m


def test_las_sugerencias_de_arranque_salen_por_su_propia_ruta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La interfaz no las trae escritas: se las pide al servidor al cargar."""
    monkeypatch.setattr(servidor, "sugerencias_para", lambda *a, **k: ["¿Y bien?"])
    m = manejador_get("/api/sugerencias")

    m.do_GET()

    assert json.loads(m.wfile.getvalue().decode("utf-8")) == ["¿Y bien?"]
    assert ("Cache-Control", "no-store") in m.cabeceras


def test_el_saludo_sale_por_una_ruta_que_no_anota_nada(registro: Path) -> None:
    """Regresión del defecto que destapó la auditoría.

    El saludo se pedía a ``/api/chat`` con la palabra «Hola», y el servidor
    anota en el registro todo lo que entra por ahí: cada apertura de la página
    dejaba un turno que nadie había escrito, así que cualquier recuento sobre
    el registro salía inflado. Lo que hay que proteger no es que el saludo se
    devuelva ---eso ya pasaba--- sino que devolverlo no escriba nada.
    """
    m = manejador_get("/api/saludo")

    m.do_GET()

    assert json.loads(m.wfile.getvalue().decode("utf-8")) == {
        "respuesta": RESPUESTA_SALUDO
    }
    assert not registro.exists(), registro.read_text(encoding="utf-8")


def test_el_texto_del_saludo_es_el_del_generador() -> None:
    # Deliberadamente rígida. La ruta existe para que el texto viva en un solo
    # sitio: si alguien lo copia aquí «para no importar el generador», vuelve a
    # haber dos versiones que pueden separarse sin que nada avise.
    m = manejador_get("/api/saludo")

    m.do_GET()

    devuelto = json.loads(m.wfile.getvalue().decode("utf-8"))["respuesta"]
    assert devuelto == RESPUESTA_SALUDO


def test_cualquier_otra_ruta_la_sirve_el_manejador_de_ficheros(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regresión: el atajo de las sugerencias no puede tapar los estáticos."""
    servido: list[bool] = []
    monkeypatch.setattr(
        servidor.SimpleHTTPRequestHandler,
        "do_GET",
        lambda self: servido.append(True),
    )
    m = manejador_get("/index.html")

    m.do_GET()

    assert servido == [True]
    assert m.wfile.getvalue() == b""


# ------------------------------------------------------------- el registro


def test_cada_turno_deja_una_linea_con_lo_que_hace_falta_para_analizarlo(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None, registro: Path
) -> None:
    """Un turno tiene que poder leerse entero sin volver a ejecutar nada.

    Se usa la conversación de verdad y no un doble: el ámbito de después lo
    fija ``anotar``, y con un doble que no lo mueve la prueba no distinguiría
    registrar antes de anotar de registrar después.
    """
    monkeypatch.setattr(
        servidor,
        "responder_por_partes",
        lambda *a, **k: iter(["En el Grado en Ingeniería Informática se programa."]),
    )
    conversacion = Conversacion(SISTEMA_FALSO[2])

    list(
        servidor.partes_de_la_respuesta("¿qué se estudia?", SISTEMA_FALSO, conversacion)
    )

    (turno,) = turnos_de(registro)
    assert turno["pregunta"] == "¿qué se estudia?"
    assert turno["consulta"]["texto"] == "¿qué se estudia?"
    assert turno["respuesta"] == "En el Grado en Ingeniería Informática se programa."
    assert turno["ambito_antes"] == []
    assert turno["ambito_despues"] == SISTEMA_FALSO[2]
    assert turno["se_busco"] is True
    assert turno["fragmentos"] == [
        {
            "nombre": "Fundamentos de la programación",
            "origen": "guia",
            "grados": SISTEMA_FALSO[2],
            "distancia": 0.1,
        }
    ]
    assert turno["modelo"] == servidor.MODELO_GENERATIVO
    assert turno["retirada"] is False
    assert turno["error"] == ""


def test_una_respuesta_retirada_se_registra_como_tal(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None, registro: Path
) -> None:
    """Sin la marca, un turno retirado se lee como una respuesta corta normal."""
    monkeypatch.setattr(
        servidor,
        "responder_por_partes",
        lambda *a, **k: iter(
            ["Te recomiendo el Grado en Magia. ", None, RESPUESTA_TITULACION_INVENTADA]
        ),
    )

    list(servidor.partes_de_la_respuesta("¿Y?", SISTEMA_FALSO, ConversacionFalsa()))

    (turno,) = turnos_de(registro)
    assert turno["retirada"] is True
    assert turno["respuesta"] == RESPUESTA_TITULACION_INVENTADA
    assert turno["respuesta_del_generador"] is True


def test_un_turno_que_falla_tambien_se_registra(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None, registro: Path
) -> None:
    """Es justo el que hay que poder analizar: si no se registra, no existió."""

    def revienta(*a: Any, **k: Any) -> Any:
        raise ErrorDelModelo("Ollama no responde")
        yield  # pragma: no cover

    monkeypatch.setattr(servidor, "responder_por_partes", revienta)

    list(servidor.partes_de_la_respuesta("¿Y?", SISTEMA_FALSO, ConversacionFalsa()))

    (turno,) = turnos_de(registro)
    assert turno["error"] == "Ollama no responde"
    assert turno["respuesta"] == ""


def test_que_falle_el_registro_no_deja_al_estudiante_sin_respuesta(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None, tmp_path: Path
) -> None:
    """Registrar es auxiliar y se comporta como tal.

    El registro se apunta a una carpeta que ya existe: escribir ahí falla de
    verdad, igual que con el disco lleno o el fichero bloqueado, y no hace
    falta simularlo con un doble. La respuesta tiene que salir entera igual.
    """
    monkeypatch.setattr(registro_chat, "REGISTRO", tmp_path)
    monkeypatch.setattr(
        servidor, "responder_por_partes", lambda *a, **k: iter(["Hola."])
    )

    sucesos = list(
        servidor.partes_de_la_respuesta("¿Y?", SISTEMA_FALSO, ConversacionFalsa())
    )

    assert {"parte": "Hola."} in sucesos
    assert sucesos[-1] == {"fin": True}


def test_que_falle_el_registro_deja_aviso_en_el_canal_diagnostico(
    monkeypatch: pytest.MonkeyPatch,
    sin_recuperador: None,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Perder la anotación de un turno no puede pasar en silencio.

    Que el registro no tumbe el chat es correcto: es auxiliar. Pero estas
    sesiones se analizan después, y un hueco sin aviso se lee como un turno
    que nunca ocurrió. El aviso no lleva la pregunta.
    """
    monkeypatch.setattr(registro_chat, "REGISTRO", tmp_path)
    monkeypatch.setattr(
        servidor, "responder_por_partes", lambda *a, **k: iter(["Hola."])
    )

    with caplog.at_level(logging.WARNING):
        list(
            servidor.partes_de_la_respuesta(
                "¿Cuántos créditos tiene Álgebra?", SISTEMA_FALSO, ConversacionFalsa()
            )
        )

    assert any("no se ha podido anotar" in m.lower() for m in caplog.messages)
    assert not any("Álgebra" in m for m in caplog.messages)


def test_que_fallen_las_sugerencias_no_se_lleva_por_delante_la_respuesta(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None, registro: Path
) -> None:
    """Un adorno de la interfaz no puede dejar el turno sin cerrar.

    Las sugerencias consultan el índice por su cuenta, y ``sugerencias_para``
    no captura nada: ``_hay`` llama directo a ``count_rows``. Ese fallo
    escapaba hasta el generador de sucesos, así que el turno terminaba sin
    ``fin`` y el cliente daba por completa una respuesta que no lo estaba.
    Regresión de la auditoría.
    """
    monkeypatch.setattr(
        servidor, "responder_por_partes", lambda *a, **k: iter(["Hola."])
    )

    def sugerencias_rotas(*a: Any, **k: Any) -> list[str]:
        raise RuntimeError("el índice no responde")

    monkeypatch.setattr(servidor, "sugerencias_para", sugerencias_rotas)

    sucesos = list(
        servidor.partes_de_la_respuesta("¿Y?", SISTEMA_FALSO, ConversacionFalsa())
    )

    assert {"parte": "Hola."} in sucesos
    assert {"sugerencias": []} in sucesos
    # Exactamente un terminal, y de éxito.
    assert sucesos[-1] == {"fin": True}
    assert sum(1 for s in sucesos if "fin" in s) == 1
    assert not any("error" in s for s in sucesos)


# ------------------------------------------------- las respuestas fijas


def test_un_saludo_ni_llega_al_indice_ni_anuncia_fuentes(
    monkeypatch: pytest.MonkeyPatch, registro: Path
) -> None:
    """Regresión del saludo con fuentes.

    Medido contra el sistema real: «Hola» devolvía **16 fuentes**, las
    dieciséis de la misma titulación. Un saludo se contesta con texto fijo y
    no llega al modelo, así que esas dieciséis unidades no respaldan nada: lo
    que se estaba enseñando como fuentes de la respuesta era lo que había
    quedado más cerca de la palabra «hola».

    Aquí no se dobla el generador: la respuesta fija la produce el de verdad,
    que para esto no necesita ni red ni modelo. Lo que se dobla es el
    recuperador, y para que reviente si alguien lo llama.
    """

    def no_deberia_buscarse(*a: Any, **k: Any) -> Any:
        raise AssertionError("un saludo no puede llegar al índice")

    monkeypatch.setattr(servidor, "contexto_para", no_deberia_buscarse)
    conversacion = Conversacion(SISTEMA_FALSO[2])

    sucesos = list(servidor.partes_de_la_respuesta("Hola", SISTEMA_FALSO, conversacion))

    assert not any("fuentes" in suceso for suceso in sucesos)
    assert sucesos[0] == {"parte": RESPUESTA_SALUDO}
    assert sucesos[-1] == {"fin": True}
    # Un saludo no habla de ninguna titulación: el turno siguiente tiene que
    # seguir sin sujeto, no heredar uno que nadie ha nombrado.
    assert conversacion.ambito == []

    (turno,) = turnos_de(registro)
    assert turno["se_busco"] is False
    assert turno["recuperados"] == 0
    assert turno["respuesta_del_generador"] is False


# ------------------------------------------------------ las sugerencias que rotan


def test_dos_turnos_seguidos_no_proponen_lo_mismo(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None
) -> None:
    """El desplazamiento avanza con la conversación, o no rotan.

    Se comprueba con dos peticiones del **mismo** servidor, que es donde vive
    la cuenta: pidiendo dos veces con manejadores recién construidos las dos
    empezarían por cero y la prueba pasaría sin que rotase nada.
    """
    pedidos: list[int] = []

    def anotar_desplazamiento(
        tabla: Any, ambito: list[str], catalogo: list[str], desplazamiento: int = 0
    ) -> list[str]:
        pedidos.append(desplazamiento)
        return []

    monkeypatch.setattr(servidor, "sugerencias_para", anotar_desplazamiento)
    monkeypatch.setattr(
        servidor, "responder_por_partes", lambda *a, **k: iter(["Hola."])
    )
    Clase = servidor.manejador(SISTEMA_FALSO)
    cuerpo = json.dumps({"pregunta": "¿qué asignaturas tiene?"}).encode("utf-8")

    manejador_falso(cuerpo, Clase=Clase).do_POST()
    manejador_falso(cuerpo, Clase=Clase).do_POST()

    assert pedidos == [1, 2]


# ------------------------------------------- los enlaces oficiales (IT-118)


def test_cada_fuente_lleva_la_direccion_oficial_de_su_unidad(
    tmp_path: Path,
) -> None:
    """El cuadro decía de dónde salía cada cosa pero no dejaba llegar hasta ella.

    Para comprobar un dato había que buscarlo a mano en la web de la Escuela,
    lo que convertía la trazabilidad en una promesa y no en algo que el lector
    pudiera ejercer.
    """
    datos = tmp_path / "grados.json"
    datos.write_text(
        json.dumps(
            [
                {
                    "tipo": "asignatura",
                    "grado": "Grado en Ingeniería Informática",
                    "nombre": "Álgebra",
                    "codigo": "13011009",
                    "url_guia": "https://uvirtual.ujaen.es/ficha/13011009",
                },
                {
                    "tipo": "asignatura",
                    "grado": "Grado en Ingeniería Informática",
                    "nombre": "Estadística",
                    "codigo": "",
                    "url_guia": None,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    enlaces = _ENLACES_REALES.__wrapped__(datos)

    assert enlaces == {
        ("Grado en Ingeniería Informática", "Álgebra"): (
            "https://uvirtual.ujaen.es/ficha/13011009"
        )
    }
    # La que no tiene guía publicada no aparece, y eso es lo correcto: no hay
    # documento al que enlazar y fabricar uno sería mentir.
    assert ("Grado en Ingeniería Informática", "Estadística") not in enlaces


def test_dos_asignaturas_homonimas_se_quedan_sin_enlace(tmp_path: Path) -> None:
    """Es mejor sin enlace que mandando a alguien a la guía equivocada.

    Hoy no hay dos asignaturas con el mismo nombre dentro de una titulación
    ---comprobado sobre las 528---, pero la clave canónica del proyecto es
    ``(grado, codigo or nombre)`` y aquí solo se dispone del nombre. Si la
    fuente cambiara, la ambigüedad no puede resolverse eligiendo una.
    """
    datos = tmp_path / "grados.json"
    datos.write_text(
        json.dumps(
            [
                {
                    "tipo": "asignatura",
                    "grado": "G",
                    "nombre": "Prácticas externas",
                    "url_guia": "https://ejemplo/1",
                },
                {
                    "tipo": "asignatura",
                    "grado": "G",
                    "nombre": "Prácticas externas",
                    "url_guia": "https://ejemplo/2",
                },
            ]
        ),
        encoding="utf-8",
    )
    assert _ENLACES_REALES.__wrapped__(datos) == {}


def test_sin_dataset_las_fuentes_se_quedan_sin_enlace(tmp_path: Path) -> None:
    # El dataset no se versiona: en un clon recién hecho no existe todavía. La
    # aplicación tiene que seguir dando las fuentes, solo que sin enlazarlas.
    assert _ENLACES_REALES.__wrapped__(tmp_path / "no_esta.json") == {}
    assert _PAGINAS_REALES.__wrapped__(tmp_path / "no_esta.json") == {}


def test_las_unidades_que_no_son_asignatura_enlazan_a_la_titulacion(
    tmp_path: Path,
) -> None:
    # El plan, las menciones y la ficha no tienen guía docente, pero sí tienen
    # la página de la Escuela de la que se extrajeron.
    datos = tmp_path / "grados.json"
    datos.write_text(
        json.dumps(
            [
                {
                    "tipo": "grado",
                    "nombre": "Grado en Ingeniería Informática",
                    "url_asignaturas": "https://eps.ujaen.es/informatica/plan",
                    "url_salidas": "https://eps.ujaen.es/informatica/salidas",
                },
                {
                    "tipo": "grado",
                    "nombre": "Doble Grado Internacional",
                    "url_asignaturas": None,
                    "url_salidas": None,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    paginas = _PAGINAS_REALES.__wrapped__(datos)

    assert paginas[("Grado en Ingeniería Informática", "url_salidas")] == (
        "https://eps.ujaen.es/informatica/salidas"
    )
    # La titulación internacional con Schmalkalden no publica ninguna de las
    # dos: no aparece en vez de aparecer con una dirección vacía.
    assert not any(t == "Doble Grado Internacional" for t, _ in paginas)


def test_la_fuente_de_una_unidad_compartida_toma_el_enlace_que_encuentra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una guía compartida por varias titulaciones tiene una URL por cada una.

    Son el mismo documento ---81 de las 398 unidades del corpus se comparten---
    así que vale la primera que se encuentre. Lo que no vale es quedarse sin
    enlace porque la primera titulación de la lista no sea la que lo publica.
    """
    monkeypatch.setattr(
        servidor,
        "enlaces_oficiales",
        lambda *a, **k: {("G. Mecánica", "Física"): "https://ejemplo/fisica"},
    )
    monkeypatch.setattr(
        servidor,
        "paginas_de_titulacion",
        lambda *a, **k: {("G. Mecánica", "url_salidas"): "https://ejemplo/salidas"},
    )
    compartida = Fragmento(
        texto="x",
        nombre="Física",
        grados=["G. Eléctrica", "G. Mecánica"],
        origen="guia",
        distancia=0.1,
        chunk_index=0,
        total_chunks=1,
    )
    salidas = Fragmento(
        texto="x",
        nombre="G. Mecánica",
        grados=["G. Eléctrica", "G. Mecánica"],
        origen="salidas",
        distancia=0.1,
        chunk_index=0,
        total_chunks=1,
    )

    fuentes = servidor.fuentes_de([compartida, salidas])

    assert fuentes[0]["url"] == "https://ejemplo/fisica"
    assert fuentes[1]["url"] == "https://ejemplo/salidas"


# --- IT-121: la respuesta fija no reapunta el ambito ---


def test_una_respuesta_fija_no_deja_cambiar_el_ambito() -> None:
    """El turno rechazado por ser de otro centro no cambia de que se habla.

    Aqui no se llama a `preparar`, asi que el decisor no opina y `anotar`
    caeria a la deduccion por reglas: la pregunta nombra una titulacion de la
    EPSJ de pasada y el ambito se iba detras de ella.
    """
    conversacion = ConversacionFalsa()

    list(
        servidor.partes_de_la_respuesta(
            "¿La Universidad de Granada tiene el Grado en Ingeniería Mecánica?",
            SISTEMA_FALSO,
            conversacion,
        )
    )

    assert conversacion.cambios_de_ambito == [False]


def test_un_turno_normal_si_deja_cambiar_el_ambito(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None
) -> None:
    """La otra mitad: sin respuesta fija, el ambito se sigue actualizando."""
    monkeypatch.setattr(
        servidor, "responder_por_partes", lambda *a, **k: iter(["Pues mira."])
    )
    conversacion = ConversacionFalsa()

    list(
        servidor.partes_de_la_respuesta(
            "¿Qué asignaturas tiene?", SISTEMA_FALSO, conversacion
        )
    )

    assert conversacion.cambios_de_ambito == [True]

"""Pruebas del punto de entrada HTTP (IT-44).

**Ninguna abre un socket.** El manejador se ejercita con ``rfile`` y ``wfile``
falsos, que es lo que permite el diseño: la lógica vive en
:func:`partes_de_la_respuesta`, que no sabe nada de HTTP, y el manejador solo la
enchufa. Si hubiera que levantar un servidor de verdad para probar esto, sería
señal de que la lógica está en el sitio equivocado.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from tfg_uja import servidor
from tfg_uja.recuperador import Fragmento
from tfg_uja.generador import ErrorDelModelo, RESPUESTA_TITULACION_INVENTADA


class ConversacionFalsa:
    """Recuerda lo anotado y devuelve una consulta sin ámbito."""

    def __init__(self) -> None:
        self.anotado: list[tuple[str, str]] = []

    def preparar(self, texto: str) -> Any:
        return type("Consulta", (), {"texto": texto, "respaldo": None, "ambito": []})()

    def preguntas(self) -> list[str]:
        return [p for p, _ in self.anotado]

    def anotar(self, pregunta: str, respuesta: str) -> None:
        self.anotado.append((pregunta, respuesta))


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
        }
    ]
    assert sucesos[1:] == [{"parte": "Uno. "}, {"parte": "Dos."}, {"fin": True}]
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


def manejador_falso(cuerpo: bytes, ruta: str = "/api/chat", largo: int | None = None):
    """Crea un manejador sin socket, con la petición ya puesta dentro."""
    Clase = servidor.manejador(SISTEMA_FALSO)
    m = Clase.__new__(Clase)
    m.path = ruta
    m.rfile = io.BytesIO(cuerpo)
    m.wfile = io.BytesIO()
    m.headers = {"Content-Length": str(len(cuerpo) if largo is None else largo)}
    m.errores: list[tuple[int, str | None]] = []
    m.send_error = lambda codigo, mensaje=None: m.errores.append((codigo, mensaje))
    m.send_response = lambda *a, **k: None
    m.send_header = lambda *a, **k: None
    m.end_headers = lambda: None
    return m


def sucesos_de(m: Any) -> list[dict[str, object]]:
    """Lee lo que el manejador ha escrito, línea a línea."""
    crudo = m.wfile.getvalue().decode("utf-8")
    return [json.loads(linea) for linea in crudo.splitlines() if linea]


def test_el_manejador_emite_una_linea_json_por_parte(
    monkeypatch: pytest.MonkeyPatch, sin_recuperador: None
) -> None:
    """Que es el contrato que espera el navegador."""
    monkeypatch.setattr(
        servidor, "responder_por_partes", lambda *a, **k: iter(["Hola."])
    )
    m = manejador_falso(json.dumps({"pregunta": "hola"}).encode("utf-8"))

    m.do_POST()

    assert sucesos_de(m)[1:] == [{"parte": "Hola."}, {"fin": True}]


@pytest.mark.parametrize(
    ("cuerpo", "ruta", "largo", "codigo"),
    [
        (b'{"pregunta":"x"}', "/otra", None, 404),
        (b"no soy json", "/api/chat", None, 400),
        (b'{"pregunta":"   "}', "/api/chat", None, 400),
        (b'{"otra":"cosa"}', "/api/chat", None, 400),
        (b"{}", "/api/chat", servidor.MAXIMO_CUERPO + 1, 413),
        # Regresion: un cuerpo que no viene en UTF-8 reventaba el manejador con
        # una traza en vez de contestar 400, y el cliente se quedaba sin nada.
        ('{"pregunta":"¿y?"}'.encode("cp1252"), "/api/chat", None, 400),
    ],
)
def test_las_peticiones_mal_formadas_no_llegan_al_modelo(
    cuerpo: bytes, ruta: str, largo: int | None, codigo: int
) -> None:
    """Se rechazan antes de gastar un minuto de modelo en ellas."""
    m = manejador_falso(cuerpo, ruta, largo)

    m.do_POST()

    assert m.errores[0][0] == codigo
    assert m.wfile.getvalue() == b""


def test_sin_indice_el_arranque_avisa_en_vez_de_reventar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un clon limpio no tiene índice: hay que decir cómo se construye."""
    monkeypatch.setattr(servidor, "INDICE", tmp_path / "no-existe")

    with pytest.raises(SystemExit):
        servidor.main()

    assert "py -m tfg_uja.indexer" in capsys.readouterr().out


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

    monkeypatch.setattr(servidor, "ThreadingHTTPServer", ServidorFalso)

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

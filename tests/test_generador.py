"""Pruebas de la generación de la respuesta (IT-37).

Sin red y sin modelo: la llamada al servidor se sustituye por un doble que
anota lo que se le envía. Lo que se comprueba aquí no es lo que responde un
modelo ---eso lo mide IT-38 con métricas, no una prueba booleana--- sino que
el prompt lleva lo que tiene que llevar y que los parámetros que hacen la
ejecución reproducible viajan de verdad en la petición.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tfg_uja import generador
from tfg_uja.generador import (
    INSTRUCCIONES,
    TOPE_RESPUESTA,
    VENTANA,
    construir_prompt,
    generar,
)
from tfg_uja.recuperador import Fragmento


def fragmento(nombre: str, texto: str, grados: list[str] | None = None) -> Fragmento:
    return Fragmento(
        texto=texto,
        nombre=nombre,
        grados=grados or ["Grado en Ingeniería Informática"],
        origen="guia",
        distancia=0.1,
    )


# --- El prompt ---


def test_el_contexto_identifica_cada_fragmento():
    """Sin la etiqueta, el modelo recibe textos seguidos sin saber de quién son.

    Atribuir el temario de una asignatura a otra es el defecto que la
    fragmentación evita desde la Fase 1; el prompt no puede reintroducirlo.
    """
    prompt = construir_prompt(
        "¿qué se ve en Álgebra?",
        [fragmento("Álgebra", "Matrices y determinantes.")],
    )
    assert "Álgebra" in prompt
    assert "Grado en Ingeniería Informática" in prompt
    assert "Matrices y determinantes." in prompt


def test_los_fragmentos_van_numerados_y_en_orden():
    prompt = construir_prompt(
        "una pregunta",
        [fragmento("Primera", "texto uno"), fragmento("Segunda", "texto dos")],
    )
    assert prompt.index("[1] Primera") < prompt.index("[2] Segunda")


def test_una_guia_compartida_declara_sus_titulaciones():
    """Las listas paralelas del corpus llegan hasta el prompt, no se pierden."""
    prompt = construir_prompt(
        "una pregunta",
        [fragmento("Compartida", "texto", ["Grado A", "Doble Grado A y B"])],
    )
    assert "Grado A, Doble Grado A y B" in prompt


def test_sin_fragmentos_el_prompt_lo_dice_explicitamente():
    """El caso que más importa: recuperación vacía.

    Es donde un sistema RAG alucina peor, porque responde con la seguridad de
    siempre sobre algo que no ha leído.
    """
    prompt = construir_prompt("¿qué se ve en Álgebra?", [])
    assert "no se ha recuperado ningún fragmento" in prompt


def test_las_instrucciones_prohiben_salirse_del_contexto():
    assert "ÚNICAMENTE" in INSTRUCCIONES
    assert "no está publicada" in INSTRUCCIONES or "no esté" in INSTRUCCIONES


def test_las_instrucciones_distinguen_sin_guia_de_inexistente():
    """Son 86 asignaturas del corpus: el usuario tiene que poder distinguirlo."""
    assert "guía no está publicada" in INSTRUCCIONES
    assert "no exista la asignatura" in INSTRUCCIONES


# --- La llamada al modelo ---


class RespuestaFalsa:
    def __init__(self, datos: dict[str, Any]) -> None:
        self._datos = datos

    def read(self) -> bytes:
        return json.dumps(self._datos).encode("utf-8")

    def __enter__(self) -> "RespuestaFalsa":
        return self

    def __exit__(self, *_: object) -> None:
        return None


@pytest.fixture()
def espia(monkeypatch) -> dict[str, Any]:
    """Sustituye la llamada de red y anota el cuerpo enviado."""
    registro: dict[str, Any] = {}

    def urlopen_falso(peticion: Any, timeout: int = 0) -> RespuestaFalsa:
        registro["url"] = peticion.full_url
        registro["cuerpo"] = json.loads(peticion.data.decode("utf-8"))
        return RespuestaFalsa({"response": "  una respuesta  "})

    monkeypatch.setattr(generador.urllib.request, "urlopen", urlopen_falso)
    return registro


def test_la_respuesta_llega_limpia(espia):
    assert generar("un prompt", "un-modelo") == "una respuesta"


def test_el_muestreo_va_fijado(espia):
    """Sin esto, dos ejecuciones de la misma pregunta dan cosas distintas.

    Y entonces ninguna medición sobre las respuestas sería reproducible.
    """
    generar("un prompt", "un-modelo")
    opciones = espia["cuerpo"]["options"]
    assert opciones["temperature"] == 0
    assert opciones["seed"] == 42


def test_la_ventana_se_declara_en_la_peticion(espia):
    """Regresión: con la ventana por defecto el modelo no cabe en la tarjeta.

    Medido: con la de por defecto se reparte 30 % CPU / 70 % GPU y rinde a un
    tercio; declarándola, entra entero.
    """
    generar("un prompt", "un-modelo")
    assert espia["cuerpo"]["options"]["num_ctx"] == VENTANA


def test_el_tope_de_respuesta_se_declara(espia):
    generar("un prompt", "un-modelo")
    assert espia["cuerpo"]["options"]["num_predict"] == TOPE_RESPUESTA


def test_el_razonamiento_va_desactivado(espia):
    """Regresión: con él activo, un candidato gastó 6.682 tokens y 280 s.

    Desactivado, la misma pregunta se respondió en 148 tokens y 8,74 s.
    """
    generar("un prompt", "un-modelo")
    assert espia["cuerpo"]["think"] is False


def test_no_se_llama_a_ningun_servicio_externo(espia):
    """El sistema se ejecuta entero en local: es requisito del trabajo."""
    generar("un prompt", "un-modelo")
    assert espia["url"].startswith("http://127.0.0.1")

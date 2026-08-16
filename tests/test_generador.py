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
    RESUMEN_TURNO,
    TOPE_RESPUESTA,
    VENTANA,
    construir_prompt,
    generar,
)
from tfg_uja.recuperador import Fragmento


def fragmento(
    nombre: str,
    texto: str,
    grados: list[str] | None = None,
    distancia: float = 0.1,
    parte: int = 0,
    total: int = 1,
    origen: str = "guia",
) -> Fragmento:
    return Fragmento(
        texto=texto,
        nombre=nombre,
        grados=grados or ["Grado en Ingeniería Informática"],
        origen=origen,
        distancia=distancia,
        chunk_index=parte,
        total_chunks=total,
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


# --- La conversación previa ---


def test_los_turnos_anteriores_entran_en_el_prompt():
    """Sin ellos, «¿y en primer año?» no sabe de qué titulación se hablaba."""
    prompt = construir_prompt(
        "¿y en primer año?",
        [fragmento("Álgebra", "temario")],
        [("háblame de Informática", "es una carrera de cuatro años")],
    )
    assert "háblame de Informática" in prompt
    assert "es una carrera de cuatro años" in prompt


def test_la_conversacion_va_separada_del_contexto():
    """Regresión de diseño: una respuesta inventada no puede volverse fuente.

    Si el turno anterior entrara mezclado con los fragmentos del corpus, lo que
    el modelo se inventó en una respuesta sería contexto para la siguiente, y
    el error se consolidaría en vez de corregirse.
    """
    prompt = construir_prompt(
        "otra pregunta",
        [fragmento("Álgebra", "temario real")],
        [("antes", "algo que dijo el modelo")],
    )
    assert prompt.index("CONVERSACIÓN PREVIA") < prompt.index("CONTEXTO:")
    assert "nunca de tus respuestas anteriores" in prompt


def test_una_respuesta_larga_se_recorta_al_recordarla():
    """Tres respuestas de listado enteras ocuparían más que el propio contexto."""
    larga = "x" * (RESUMEN_TURNO + 500)
    prompt = construir_prompt("otra", [fragmento("A", "t")], [("antes", larga)])
    assert larga not in prompt
    assert "[...]" in prompt


def test_sin_historial_el_prompt_no_cambia():
    """Lo habitual sigue siendo una pregunta suelta: no puede llevar peaje.

    Se busca el rótulo con sus dos puntos, que solo aparece encabezando el
    bloque; sin ellos casaría también con la regla de las instrucciones que
    habla de la conversación previa, y la prueba pasaría por el motivo malo.
    """
    sin = construir_prompt("una pregunta", [fragmento("A", "t")])
    vacio = construir_prompt("una pregunta", [fragmento("A", "t")], [])
    assert sin == vacio
    assert "CONVERSACIÓN PREVIA:" not in sin


# --- El orden y la integridad del contexto ---


def test_las_partes_de_una_unidad_viajan_juntas_y_en_orden():
    """Regresión del caso real: el listado del plan llegaba 3, optativas, 2, 1.

    La respuesta reproducía ese orden ---empezaba por la mitad de la lista y
    volvía al principio más abajo--- porque el modelo redacta siguiendo el
    orden en que recibe el contexto.
    """
    recuperados = [
        fragmento("Obligatorias", "TEXTO-C", distancia=0.105, parte=2, total=3),
        fragmento("Optativas", "TEXTO-D", distancia=0.107),
        fragmento("Obligatorias", "TEXTO-B", distancia=0.109, parte=1, total=3),
        fragmento("Obligatorias", "TEXTO-A", distancia=0.111, parte=0, total=3),
    ]
    # Marcas que no puedan aparecer en las instrucciones: comprobar el orden
    # buscando palabras del dominio casaba con el texto de las reglas y daba
    # por malo un contexto que estaba bien colocado.
    prompt = construir_prompt("qué asignaturas hay", recuperados)
    posiciones = [prompt.index(t) for t in ("TEXTO-A", "TEXTO-B", "TEXTO-C", "TEXTO-D")]
    assert posiciones == sorted(posiciones)


def test_la_unidad_mas_proxima_sigue_yendo_primero():
    """Agrupar no puede tirar por tierra la relevancia: solo reordena dentro."""
    recuperados = [
        fragmento("Lejana", "texto lejano", distancia=0.5),
        fragmento("Cercana", "texto cercano", distancia=0.1),
    ]
    prompt = construir_prompt("una pregunta", recuperados)
    assert prompt.index("texto cercano") < prompt.index("texto lejano")


def test_la_marca_de_parte_no_aparece_en_el_contexto():
    """Regresión de dos fallos reales, y de un arreglo que no funcionó.

    Con la marca en el encabezado, el sistema contestó a un estudiante que
    «Desarrollo de aplicaciones web (Parte 1, 2, 3, 4, 5 y 6)». Se añadió una
    regla prohibiéndolo y **volvió a colarse**: la segunda vez se inventó una
    asignatura llamada «Sistemas inteligentes de información (parte 3 de 4)» y
    afirmó que su guía no estaba publicada. Lo que no está en el prompt no se
    puede filtrar.
    """
    prompt = construir_prompt(
        "una pregunta", [fragmento("Obligatorias", "once nombres", parte=2, total=3)]
    )
    assert "parte 3 de 3" not in prompt
    assert "de 3)" not in prompt


def test_las_instrucciones_fijan_el_orden_de_la_enumeracion():
    """Lo pidió el autor: agrupado por curso y las optativas al final."""
    assert "agrúpalas por curso" in INSTRUCCIONES
    assert "optativas" in INSTRUCCIONES


def test_los_listados_del_plan_se_leen_en_el_orden_en_que_se_cursan():
    """Medido: por distancia, las optativas caían entre segundo y primero.

    El modelo enumeró los cuatro cursos y dejó fuera las diecisiete optativas
    aunque las tenía delante, en la segunda posición del contexto.
    """
    plan = "plan_de_estudios"
    recuperados = [
        fragmento(
            "Asignaturas obligatorias de segundo curso del X",
            "SEGUNDO",
            distancia=0.080,
            origen=plan,
        ),
        fragmento(
            "Asignaturas optativas del X", "OPTATIVAS", distancia=0.081, origen=plan
        ),
        fragmento(
            "Asignaturas obligatorias de primer curso del X",
            "PRIMERO",
            distancia=0.082,
            origen=plan,
        ),
    ]
    prompt = construir_prompt("qué asignaturas hay", recuperados)
    posiciones = [prompt.index(t) for t in ("PRIMERO", "SEGUNDO", "OPTATIVAS")]
    assert posiciones == sorted(posiciones)


def test_un_listado_no_desplaza_a_lo_que_estaba_mas_cerca():
    """Reordenar los listados entre sí no puede colarlos por delante de todo."""
    guia = fragmento("Álgebra", "GUIA-CERCANA", distancia=0.01)
    listado = fragmento(
        "Asignaturas obligatorias de primer curso del X",
        "LISTADO",
        distancia=0.5,
        origen="plan_de_estudios",
    )
    prompt = construir_prompt("una pregunta", [guia, listado])
    assert prompt.index("GUIA-CERCANA") < prompt.index("LISTADO")


def test_el_tope_da_para_la_respuesta_mas_larga_del_corpus():
    """Las 67 asignaturas de Informática son ~783 tokens; con 400 se cortaban.

    El número no es redondo por gusto: sale de medir el listado completo con
    sus créditos sobre el corpus real.
    """
    assert TOPE_RESPUESTA >= 800


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


# --- El ámbito de la consulta ---


def test_el_ambito_se_declara_como_dato_en_el_prompt():
    """78 guías se imparten en varias titulaciones y el encabezado las nombra.

    Medido: con la búsqueda acotada a Informática, el sistema respondió con un
    apartado entero sobre Inteligencia Artificial y Ciberseguridad. Acotar la
    búsqueda no le dice al modelo de qué tiene que hablar.
    """
    prompt = construir_prompt(
        "qué asignaturas hay",
        [fragmento("Álgebra", "temario")],
        ambito="Grado en Ingeniería Informática",
    )
    assert "ÁMBITO: la consulta es sobre el Grado en Ingeniería Informática" in prompt
    assert prompt.index("ÁMBITO") < prompt.index("CONTEXTO:")


def test_sin_ambito_el_prompt_no_lo_menciona():
    prompt = construir_prompt("una pregunta", [fragmento("A", "t")])
    assert "ÁMBITO:" not in prompt

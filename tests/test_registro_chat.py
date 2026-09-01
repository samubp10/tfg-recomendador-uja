"""Pruebas del registro de conversaciones (IT-45).

**Ninguna llama al modelo ni levanta un servidor.** Es lo que permite haber
separado la tarea en dos: :func:`linea_de_turno` decide qué se guarda y se
prueba con datos en memoria, y :func:`anotar_turno` solo escribe, contra un
fichero temporal. Si para comprobar qué campos lleva el registro hiciera falta
un minuto de modelo, sería señal de que la composición está en el sitio
equivocado.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tfg_uja.aplicacion import registro_chat
from tfg_uja.dialogo.conversacion import Consulta
from tfg_uja.dialogo.generador import (
    RESPUESTA_SALUDO,
    RESPUESTA_SIN_CONTEXTO,
    RESPUESTA_TITULACION_INVENTADA,
)
from tfg_uja.dialogo.recuperador import Fragmento
from tfg_uja.aplicacion.registro_chat import anotar_turno, linea_de_turno

INFORMATICA = "Grado en Ingeniería Informática"


def frag(
    nombre: str = "Fundamentos de la programación",
    distancia: float = 0.1234,
    origen: str = "guia",
    grados: list[str] | None = None,
) -> Fragmento:
    """Un fragmento con lo justo para estas pruebas."""
    return Fragmento(
        texto="x",
        nombre=nombre,
        grados=grados or [INFORMATICA],
        origen=origen,
        distancia=distancia,
        chunk_index=0,
        total_chunks=1,
    )


def linea(**cambios: Any) -> dict[str, Any]:
    """Una línea de registro con valores por omisión que las pruebas retocan."""
    datos: dict[str, Any] = {
        "pregunta": "¿y en segundo?",
        "consulta": Consulta(texto="asignaturas en segundo", ambito=[INFORMATICA]),
        "ambito_antes": [INFORMATICA],
        "ambito_despues": [INFORMATICA],
        "fragmentos": [frag()],
        "se_busco": True,
        "respuesta": "En segundo se cursan…",
        "retirada": False,
        "segundos": 61.234,
        "modelo": "gemma3:12b",
    }
    datos.update(cambios)
    return linea_de_turno(**datos)


# -------------------------------------------------------------- qué se guarda


def test_la_pregunta_y_la_consulta_se_guardan_por_separado() -> None:
    """No son lo mismo, y confundirlas haría inútil el registro.

    La conversación reescribe la pregunta antes de buscar: «¿y en segundo?» se
    convierte en otra cosa. Guardando solo una de las dos no hay forma de saber
    si un fallo vino de lo que se escribió o de lo que se buscó.
    """
    registro = linea()

    assert registro["pregunta"] == "¿y en segundo?"
    assert registro["consulta"] == {
        "texto": "asignaturas en segundo",
        "ambito": [INFORMATICA],
        "respaldo": "",
        "decision": "",
        "abierta": False,
    }


def test_cada_fragmento_lleva_su_distancia() -> None:
    """Es lo único que permite comprobar después si actuó el suelo.

    Sin la distancia, un turno en el que el suelo de pertinencia lo descartó
    todo y otro en el que el índice no tenía nada se leen exactamente igual.
    """
    registro = linea(fragmentos=[frag(distancia=0.0918), frag(distancia=0.1512)])

    assert registro["recuperados"] == 2
    assert [f["distancia"] for f in registro["fragmentos"]] == [0.0918, 0.1512]
    assert registro["fragmentos"][0] == {
        "nombre": "Fundamentos de la programación",
        "origen": "guia",
        "grados": [INFORMATICA],
        "distancia": 0.0918,
    }


def test_no_haber_buscado_se_distingue_de_no_haber_encontrado() -> None:
    """Dos turnos con cero fragmentos que no son el mismo turno.

    Uno ni siquiera llegó al índice ---la respuesta era fija--- y el otro
    buscó y el suelo de pertinencia lo descartó todo. Sin este campo los dos
    se leen igual, y son la señal de dos cosas distintas: en el primero no hay
    nada que ajustar, en el segundo puede que el suelo esté demasiado alto.
    Tampoco se deduce de la respuesta: «hola» y «hei» acaban las dos en la
    bienvenida y solo la segunda pasó por el índice.
    """
    saludo = linea(fragmentos=[], se_busco=False, respuesta=RESPUESTA_SALUDO)
    descartado = linea(fragmentos=[], se_busco=True, respuesta=RESPUESTA_SIN_CONTEXTO)

    assert saludo["recuperados"] == descartado["recuperados"] == 0
    assert saludo["se_busco"] is False
    assert descartado["se_busco"] is True


def test_el_ambito_queda_registrado_antes_y_despues_del_turno() -> None:
    """Un turno cambia de titulación, y el registro tiene que decir en cuál."""
    registro = linea(ambito_antes=[], ambito_despues=[INFORMATICA])

    assert registro["ambito_antes"] == []
    assert registro["ambito_despues"] == [INFORMATICA]


def test_el_momento_es_una_marca_de_tiempo_que_se_puede_leer() -> None:
    """Un registro sin fecha no se puede ordenar ni cruzar con nada."""
    assert datetime.fromisoformat(linea()["momento"])


def test_los_segundos_se_redondean_a_centesimas() -> None:
    """La coma flotante en crudo llena el registro de dígitos sin sentido."""
    assert linea(segundos=61.234)["segundos"] == 61.23


def test_el_registro_no_guarda_ningun_dato_personal() -> None:
    """RNF-03. Este es el sitio exacto por donde se colarían.

    La prueba fija la lista entera de campos, no comprueba la ausencia de unos
    cuantos: un registro de conversaciones crece con el tiempo, y lo que hay
    que impedir es que un campo **nuevo** ---la dirección IP, el agente de
    usuario, un identificador de sesión--- entre sin que nadie lo note.
    """
    assert set(linea()) == {
        "momento",
        "modelo",
        "pregunta",
        "consulta",
        "ambito_antes",
        "ambito_despues",
        "se_busco",
        "recuperados",
        "fragmentos",
        "respuesta",
        "retirada",
        "segundos",
        "modelo_llamado",
        "error",
    }


# ------------------------------------------------ si se llamó o no al modelo


@pytest.mark.parametrize("fija", [RESPUESTA_SALUDO, RESPUESTA_SIN_CONTEXTO])
def test_una_respuesta_fija_queda_marcada_como_turno_sin_modelo(fija: str) -> None:
    """Un saludo o un contexto vacío no gastan modelo, y se ve en el registro."""
    assert linea(respuesta=fija)["modelo_llamado"] is False


def test_la_retirada_cuenta_como_turno_con_modelo() -> None:
    """Regresión: la respuesta de retirada también es fija, pero llega tarde.

    Cuando se entrega, el modelo ya se había llamado y había redactado una
    respuesta entera que luego se retiró. Contarla entre las fijas diría que
    ese turno salió gratis, y es de los más caros que hay.
    """
    registro = linea(respuesta=RESPUESTA_TITULACION_INVENTADA, retirada=True)

    assert registro["modelo_llamado"] is True
    assert registro["retirada"] is True


def test_un_fallo_del_modelo_se_guarda_con_su_mensaje() -> None:
    """Un turno que falla es justo el que hay que poder analizar después."""
    registro = linea(respuesta="", error="Ollama no responde")

    assert registro["error"] == "Ollama no responde"
    assert registro["respuesta"] == ""


# ------------------------------------------------------------ cómo se escribe


def test_el_registro_por_omision_vive_en_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No es un detalle: en ``data/`` es donde el registro sobrevive.

    La carpeta no se versiona pero persiste entre ramas y árboles de trabajo.
    Escribirlo en cualquier otro sitio es exactamente como se perdió el
    registro en bruto de las 320 respuestas del cribado de IT-35.
    """
    assert registro_chat.REGISTRO.name == "registro_chat.jsonl"
    assert registro_chat.REGISTRO.parent.name == "data"

    destino = tmp_path / "registro_chat.jsonl"
    monkeypatch.setattr(registro_chat, "REGISTRO", destino)

    assert anotar_turno(linea()) is True
    assert destino.exists()


def test_las_lineas_se_acumulan_y_el_fichero_se_crea_solo(tmp_path: Path) -> None:
    """Se abre en modo añadir: reescribirlo borraría la tanda anterior."""
    destino = tmp_path / "sin" / "crear" / "registro_chat.jsonl"

    anotar_turno(linea(pregunta="primera"), destino)
    anotar_turno(linea(pregunta="segunda"), destino)

    lineas = destino.read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["pregunta"] for x in lineas] == ["primera", "segunda"]


def test_el_texto_se_guarda_legible_y_no_escapado(tmp_path: Path) -> None:
    """Escapando a ASCII el fichero se llena de barras y no hay quien lo lea."""
    destino = tmp_path / "registro_chat.jsonl"

    anotar_turno(linea(pregunta="¿qué se estudia en Informática?"), destino)

    assert "¿qué se estudia en Informática?" in destino.read_text(encoding="utf-8")


def test_si_no_se_puede_escribir_se_pierde_la_linea_y_no_se_lanza_nada(
    tmp_path: Path,
) -> None:
    """Registrar es auxiliar: un fallo aquí no puede salir de aquí.

    Se apunta el registro a una carpeta que ya existe, que es un fallo de
    escritura de verdad ---el mismo que da un fichero bloqueado o un disco
    lleno--- y no uno simulado con un doble.
    """
    assert anotar_turno(linea(), tmp_path) is False


def test_una_linea_que_no_se_puede_serializar_tampoco_lanza(tmp_path: Path) -> None:
    """Se atrapa cualquier cosa, no solo los fallos de disco."""
    destino = tmp_path / "registro_chat.jsonl"

    assert anotar_turno({"raro": object()}, destino) is False

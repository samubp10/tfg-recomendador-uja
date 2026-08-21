"""Pruebas de integración del recorrido RAG completo (IT-37).

Son las únicas del proyecto que **no** usan dobles: recorren el tubo entero
---incrustar la pregunta, consultar el índice, armar el *prompt*, llamar al
modelo y comprobar lo que responde--- porque lo que esta tarjeta promete es
justo eso, que el recorrido funcione de extremo a extremo. Con un generador
falso se comprobaría el pegamento, que ya está cubierto en las demás pruebas.

**Por qué se saltan en vez de fallar.** Necesitan dos cosas que no existen en
un clon limpio: el índice vectorial, que vive en ``data/`` y no se versiona, y
el servidor de inferencia levantado. Exigirlas rompería la integración continua
sin que nada estuviera roto.

**El salto siempre dice por qué.** Un test que se salta en silencio pasa por
verde, y este proyecto lleva ya cinco verificadores que decían «OK» midiendo
otra cosa. El motivo viaja en la llamada a :func:`pytest.skip` y ``-ra``, que
está en la configuración, lo imprime en cada ejecución.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from tfg_uja.generador import SERVIDOR, responder
from tfg_uja.incrustaciones import MODELO as MODELO_INCRUSTACIONES
from tfg_uja.incrustaciones import incrustador_de_consultas
from tfg_uja.recuperador import (
    K_MAXIMO,
    abrir_indice,
    catalogo_del_indice,
    contexto_para,
    distancia_del_indice,
)
from tfg_uja.verificacion import titulaciones_inventadas

RAIZ = Path(__file__).resolve().parent.parent

#: Índice vectorial construido con ``py -m tfg_uja.indexer``. No se versiona.
INDICE = RAIZ / "data" / "indice_lance"

#: Conjunto etiquetado de IT-27. Este sí está versionado.
BANCO = RAIZ / "eval" / "preguntas_evaluacion.json"

#: Modelo con el que se prueba. Es el del sistema; se puede cambiar por
#: variable de entorno para probar un candidato sin tocar el fichero.
MODELO_GENERATIVO = os.environ.get("TFG_MODELO", "gemma3:12b")

#: Cuánto se espera a que el servidor diga que está vivo. Es una comprobación
#: de disponibilidad, no una petición de trabajo: si tarda más de esto, a
#: efectos de la prueba no está.
ESPERA_SONDEO = 3


def motivo_para_saltar() -> str | None:
    """Comprueba si están las dos condiciones para ejecutar de verdad.

    Returns:
        El motivo por el que no se puede ejecutar, redactado para que quien lea
        la salida sepa qué le falta, o ``None`` si se puede.
    """
    if not INDICE.exists():
        return (
            f"no hay índice vectorial en {INDICE.relative_to(RAIZ)}; "
            "se construye con «py -m tfg_uja.indexer data/chunks.json "
            "data/indice_lance»"
        )
    try:
        urllib.request.urlopen(SERVIDOR, timeout=ESPERA_SONDEO).read()
    except (urllib.error.URLError, OSError) as fallo:
        return (
            f"el servidor de inferencia no responde en {SERVIDOR} ({fallo}); "
            "se levanta con «ollama serve»"
        )
    return None


@pytest.fixture(scope="module")
def sistema() -> Any:
    """Abre el índice y el incrustador una sola vez para todo el módulo.

    Cargar el modelo de incrustaciones tarda varios segundos y no depende de la
    pregunta, así que repetirlo por caso solo alargaría la prueba.

    Returns:
        ``(tabla, incrustar, distancia, catalogo)``.

    Raises:
        pytest.skip.Exception: Si falta el índice o el servidor, con el motivo.
    """
    motivo = motivo_para_saltar()
    if motivo:
        pytest.skip(motivo)
    return (
        abrir_indice(INDICE, MODELO_INCRUSTACIONES),
        incrustador_de_consultas(MODELO_INCRUSTACIONES),
        distancia_del_indice(INDICE),
        catalogo_del_indice(INDICE),
    )


def preguntas_de_dominio() -> list[dict[str, Any]]:
    """Las preguntas del conjunto de IT-27 que sí tienen respuesta en el corpus.

    Las de fuera de dominio se excluyen a propósito: su criterio es el
    contrario ---rechazar es acertar--- y aquí se comprueba que el recorrido
    traiga contexto, que es exactamente lo que ellas no deben provocar.

    Returns:
        Las entradas de dominio, en el orden del fichero.
    """
    banco = json.loads(BANCO.read_text(encoding="utf-8"))
    return [p for p in banco["preguntas"] if p["tipo"] != "fuera_de_dominio"]


def recorrer(pregunta: str, sistema: Any) -> tuple[list[Any], str]:
    """Pasa una pregunta por el recorrido completo.

    Args:
        pregunta: La pregunta, tal cual la escribiría un estudiante.
        sistema: Lo que devuelve la fixture del mismo nombre.

    Returns:
        ``(fragmentos recuperados, respuesta)``.
    """
    tabla, incrustar, distancia, catalogo = sistema
    fragmentos = contexto_para(
        pregunta,
        tabla,
        incrustar,
        distancia=distancia,
        k=K_MAXIMO,
        catalogo=catalogo,
    )
    respuesta = responder(pregunta, fragmentos, MODELO_GENERATIVO, catalogo=catalogo)
    return fragmentos, respuesta


@pytest.mark.parametrize("entrada", preguntas_de_dominio()[:3], ids=lambda p: p["id"])
def test_el_recorrido_completo_responde(entrada: dict[str, Any], sistema: Any) -> None:
    """Tres preguntas reales entran por un extremo y sale una respuesta.

    Se comprueban las tres cosas que pueden romperse sin que ninguna prueba
    unitaria se entere: que el índice devuelve algo, que el modelo contesta y
    que lo que contesta no nombra una titulación inexistente.
    """
    fragmentos, respuesta = recorrer(entrada["pregunta"], sistema)
    catalogo = sistema[3]
    assert fragmentos, f"{entrada['id']}: el recuperador no trajo nada"
    assert respuesta.strip(), f"{entrada['id']}: el modelo devolvió una respuesta vacía"
    inventadas = titulaciones_inventadas(respuesta, catalogo)
    assert not inventadas, f"{entrada['id']}: nombra {sorted(inventadas)}"


@pytest.mark.lento
def test_ninguna_pregunta_del_conjunto_se_queda_sin_respuesta(sistema: Any) -> None:
    """El conjunto entero de dominio, que son 56 llamadas al modelo.

    Fuera de la ejecución por defecto porque tarda cerca de una hora: es la
    comprobación que se lanza antes de dar por buena una versión, no la de cada
    ``pytest``. Lo que verifica es el umbral eliminatorio del proyecto sobre
    todo el conjunto, no sobre una muestra.
    """
    catalogo = sistema[3]
    sin_contexto: list[str] = []
    con_invencion: list[str] = []
    for entrada in preguntas_de_dominio():
        fragmentos, respuesta = recorrer(entrada["pregunta"], sistema)
        if not fragmentos:
            sin_contexto.append(entrada["id"])
            continue
        if titulaciones_inventadas(respuesta, catalogo):
            con_invencion.append(entrada["id"])
    assert not sin_contexto, f"sin contexto recuperado: {sin_contexto}"
    assert not con_invencion, f"nombran titulaciones inexistentes: {con_invencion}"

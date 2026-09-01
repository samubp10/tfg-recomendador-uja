"""Pruebas de la convención de prefijos del modelo de incrustaciones (IT-98).

El modelo del ADR-0003 distingue el papel del texto por un prefijo:
``"passage: "`` para los fragmentos que se indexan y ``"query: "`` para las
preguntas. Olvidarlo no produce ningún error —ni excepción, ni aviso, ni
vector de forma distinta—, solo peor recuperación, así que la única forma de
protegerlo es comprobarlo.

Estas pruebas no descargan nada: sustituyen la carga del modelo por un
incrustador espía que anota los textos que le llegan, que es justo lo que hay
que mirar.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from tfg_uja.indexacion import incrustaciones
from tfg_uja.indexacion.incrustaciones import (
    MODELO,
    PREFIJO_CONSULTA,
    PREFIJO_DOCUMENTO,
    VARIABLE_DESCARGA,
    cargar_modelo,
    con_prefijo,
    incrustador_de_consultas,
    incrustador_de_documentos,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _texto_real() -> str:
    """Un fragmento real del corpus, no una cadena inventada."""
    chunks = json.loads(
        (FIXTURES / "chunks_muestra_real.json").read_text(encoding="utf-8")
    )
    return chunks[0]["texto"]


class _Espia:
    """Incrustador falso que guarda los textos exactos que ha recibido."""

    def __init__(self) -> None:
        self.recibidos: list[str] = []

    def __call__(self, textos: list[str]) -> list[list[float]]:
        self.recibidos.extend(textos)
        return [[0.0] for _ in textos]


def test_con_prefijo_antepone_el_prefijo_a_cada_texto() -> None:
    espia = _Espia()
    texto = _texto_real()
    con_prefijo(PREFIJO_DOCUMENTO, espia)([texto, "otra cosa"])
    assert espia.recibidos == [
        PREFIJO_DOCUMENTO + texto,
        PREFIJO_DOCUMENTO + "otra cosa",
    ]


def test_lo_que_se_indexa_lleva_el_prefijo_de_documento(monkeypatch) -> None:
    # Este es el camino real del indexador. Si alguien quita el prefijo de
    # `incrustador_de_documentos`, esta prueba falla; sin ella, el cambio
    # pasaría con todo en verde y el índice quedaría peor en silencio.
    espia = _Espia()
    monkeypatch.setattr(incrustaciones, "cargar_modelo", lambda nombre=MODELO: espia)
    incrustador_de_documentos()([_texto_real()])
    assert espia.recibidos[0].startswith(PREFIJO_DOCUMENTO)


def test_lo_que_se_consulta_lleva_el_prefijo_de_consulta(monkeypatch) -> None:
    espia = _Espia()
    monkeypatch.setattr(incrustaciones, "cargar_modelo", lambda nombre=MODELO: espia)
    incrustador_de_consultas()(["¿Qué se estudia en Criptografía?"])
    assert espia.recibidos[0].startswith(PREFIJO_CONSULTA)


def test_los_dos_prefijos_son_distintos() -> None:
    # La asimetría es la razón de ser del módulo: si algún día alguien los
    # iguala «para simplificar», el modelo deja de poder distinguir el papel
    # del texto y esta prueba lo dice.
    assert PREFIJO_DOCUMENTO != PREFIJO_CONSULTA


def test_el_prefijo_termina_en_espacio() -> None:
    # La ficha del modelo escribe "query: " y "passage: " con el espacio
    # incluido. Sin él se pega al primer término ("query:Criptografía") y se
    # tokeniza distinto de como se entrenó.
    assert PREFIJO_DOCUMENTO.endswith(" ")
    assert PREFIJO_CONSULTA.endswith(" ")


def test_el_modelo_es_el_que_decidio_el_adr_0003() -> None:
    # Deliberadamente rígida. El modelo dejó de ser un valor de trabajo: lo
    # respalda un ADR con dos ejecuciones del experimento detrás. Si alguien
    # lo cambia, que sea a sabiendas y tocando también el ADR, no de pasada.
    assert MODELO == "intfloat/multilingual-e5-small"


class _ModeloFalso:
    """Sustituto de ``SentenceTransformer`` que anota cómo lo han llamado.

    No descarga nada ni carga pesos: solo guarda los argumentos de la llamada
    para poder comprobar que se pide la carga desde la caché.
    """

    def __init__(self, nombre: str, local_files_only: bool = False) -> None:
        self.nombre = nombre
        self.local_files_only = local_files_only

    def encode(self, textos: list[str], show_progress_bar: bool = True) -> _Vector:
        return _Vector([[float(len(t))] for t in textos])


class _Vector(list):  # type: ignore[type-arg]
    """Remeda lo justo de un ``ndarray``: que ``tolist()`` devuelva la lista."""

    def tolist(self) -> list[list[float]]:
        return list(self)


def _finge_sentence_transformers(monkeypatch, constructor) -> None:
    """Instala un ``sentence_transformers`` de mentira en ``sys.modules``.

    La importación de :func:`cargar_modelo` es perezosa y ocurre dentro de la
    función, así que basta con que el módulo esté puesto antes de llamarla.
    """
    falso = types.ModuleType("sentence_transformers")
    falso.SentenceTransformer = constructor  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", falso)


def test_por_defecto_el_modelo_se_carga_solo_de_la_cache(monkeypatch) -> None:
    # El sistema promete funcionar sin conexión. Sin esta restricción no lo
    # cumplía: en un equipo con la red cortada el servidor no llegaba a
    # levantar porque la carga consultaba el Hub aunque el modelo ya
    # estuviera descargado.
    monkeypatch.delenv(VARIABLE_DESCARGA, raising=False)
    creados: list[_ModeloFalso] = []

    def constructor(nombre: str, local_files_only: bool = False) -> _ModeloFalso:
        modelo = _ModeloFalso(nombre, local_files_only)
        creados.append(modelo)
        return modelo

    _finge_sentence_transformers(monkeypatch, constructor)

    incrustar = cargar_modelo("un-modelo")

    assert creados[0].local_files_only is True
    assert incrustar(["abc"]) == [[3.0]]


def test_la_variable_de_entorno_autoriza_la_descarga(monkeypatch) -> None:
    # La primera instalación tiene que poder traerse el modelo. Se pide a
    # propósito y no ocurre a espaldas de quien solo ejecuta el sistema.
    monkeypatch.setenv(VARIABLE_DESCARGA, "1")
    creados: list[_ModeloFalso] = []

    def constructor(nombre: str, local_files_only: bool = False) -> _ModeloFalso:
        modelo = _ModeloFalso(nombre, local_files_only)
        creados.append(modelo)
        return modelo

    _finge_sentence_transformers(monkeypatch, constructor)
    cargar_modelo("un-modelo")

    assert creados[0].local_files_only is False


def test_sin_modelo_en_cache_el_error_dice_como_traerlo(monkeypatch) -> None:
    # Un modelo que falta no es una avería del sistema, y el mensaje tiene que
    # distinguir las dos cosas: si no, «funciona sin conexión» se convierte en
    # «misteriosamente no arranca».
    monkeypatch.delenv(VARIABLE_DESCARGA, raising=False)

    def constructor(nombre: str, local_files_only: bool = False) -> _ModeloFalso:
        raise OSError("no está en la caché")

    _finge_sentence_transformers(monkeypatch, constructor)

    with pytest.raises(RuntimeError) as fallo:
        cargar_modelo("un-modelo")

    assert VARIABLE_DESCARGA in str(fallo.value)
    assert isinstance(fallo.value.__cause__, OSError)


def test_con_la_descarga_autorizada_el_error_original_se_respeta(monkeypatch) -> None:
    # Si se pidió descargar y aun así falla, el problema es otro (sin red, el
    # nombre mal escrito, el Hub caído). Envolverlo en el mensaje de la caché
    # mandaría a quien lo lea a buscar donde no es.
    monkeypatch.setenv(VARIABLE_DESCARGA, "1")

    def constructor(nombre: str, local_files_only: bool = False) -> _ModeloFalso:
        raise OSError("la red no responde")

    _finge_sentence_transformers(monkeypatch, constructor)

    with pytest.raises(OSError, match="la red no responde"):
        cargar_modelo("un-modelo")

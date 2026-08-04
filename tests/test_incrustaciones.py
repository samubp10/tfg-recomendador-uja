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
from pathlib import Path

from tfg_uja import incrustaciones
from tfg_uja.incrustaciones import (
    MODELO,
    PREFIJO_CONSULTA,
    PREFIJO_DOCUMENTO,
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

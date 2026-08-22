"""Pruebas del experimento de recuperación (IT-38).

Ninguna incrusta ni consulta el índice: lo que se comprueba aquí es la
aritmética que sostiene las cifras del informe, que es justo donde este
proyecto ha ido acumulando defectos ---verificadores que decían «OK» midiendo
otra cosa---. Las tres métricas en sí ya están probadas en
``test_evaluacion.py``; lo que faltaba por cubrir es el techo, que se calcula
aquí y en ningún otro sitio.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

import experimento_recuperacion as recuperacion  # noqa: E402


def chunk(origen: str, nombre: str) -> dict[str, object]:
    """Fragmento mínimo con lo que necesita el selector de relevantes.

    Args:
        origen: Tipo de fragmento.
        nombre: Nombre de su unidad.

    Returns:
        El fragmento.
    """
    return {"tipo": "chunk", "origen": origen, "nombre": nombre, "grados": ["G"]}


def pregunta(*unidades: tuple[str, str]) -> dict[str, object]:
    """Pregunta con los selectores de relevancia indicados.

    Args:
        unidades: Pares ``(origen, nombre)``.

    Returns:
        La entrada del conjunto de evaluación.
    """
    return {
        "id": "P-000",
        "tipo": "listado",
        "pregunta": "da igual",
        "relevantes": [{"origen": o, "nombre": n} for o, n in unidades],
    }


# --- El techo ---


def test_con_menos_relevantes_que_k_el_techo_es_uno():
    """Si la pregunta se resuelve con dos fragmentos, K=3 puede traerlos todos."""
    chunks = [chunk("guia", "A"), chunk("guia", "B"), chunk("guia", "Z")]
    preguntas = [pregunta(("guia", "A"), ("guia", "B"))]
    assert recuperacion.techo_de_recall(preguntas, chunks, 3) == 1.0


def test_con_mas_relevantes_que_k_el_techo_baja():
    """Seis fragmentos relevantes y K=3: el máximo alcanzable es 0,5.

    Es la razón de existir de esta función. Sin ella, una pregunta así
    parecería medio fallada cuando el recuperador ha hecho todo lo que podía.
    """
    chunks = [chunk("guia", nombre) for nombre in "ABCDEF"]
    preguntas = [pregunta(*(("guia", nombre) for nombre in "ABCDEF"))]
    assert recuperacion.techo_de_recall(preguntas, chunks, 3) == 0.5


def test_el_techo_promedia_sobre_las_preguntas():
    """Una alcanzable y otra que no: el techo del conjunto queda en medio."""
    chunks = [chunk("guia", nombre) for nombre in "ABCDEF"]
    preguntas = [
        pregunta(("guia", "A")),
        pregunta(*(("guia", nombre) for nombre in "ABCDEF")),
    ]
    assert recuperacion.techo_de_recall(preguntas, chunks, 3) == 0.75


def test_una_pregunta_sin_relevantes_no_rompe_el_techo():
    """Las de fuera de dominio se filtran antes, pero el cálculo no puede caer.

    Dividir por cero aquí abortaría el experimento entero por una entrada mal
    etiquetada, y el conjunto lo mantiene una persona a mano.
    """
    chunks = [chunk("guia", "A")]
    assert recuperacion.techo_de_recall([pregunta()], chunks, 3) == 0.0


def test_sin_preguntas_el_techo_es_cero():
    assert recuperacion.techo_de_recall([], [chunk("guia", "A")], 3) == 0.0


# --- La carga del corpus ---


def test_la_procedencia_no_cuenta_como_fragmento(tmp_path):
    """Se separa por tipo, nunca por posición.

    ``chunks.json`` encabeza la lista con un registro de procedencia. Contarlo
    como fragmento mete en el corpus un texto que no lo es y desplaza todos los
    índices del ranking.
    """
    fichero = tmp_path / "chunks.json"
    fichero.write_text(
        json.dumps(
            [
                chunk("guia", "A"),
                {"tipo": "procedencia", "fecha_extraccion": "2026-08-16"},
                chunk("guia", "B"),
            ]
        ),
        encoding="utf-8",
    )
    chunks, procedencia = recuperacion.cargar_chunks(fichero)
    assert len(chunks) == 2
    assert procedencia["fecha_extraccion"] == "2026-08-16"


def test_sin_registro_de_procedencia_se_devuelve_vacio(tmp_path):
    """Un corpus antiguo no lo trae, y eso no debe abortar la medición."""
    fichero = tmp_path / "chunks.json"
    fichero.write_text(json.dumps([chunk("guia", "A")]), encoding="utf-8")
    chunks, procedencia = recuperacion.cargar_chunks(fichero)
    assert len(chunks) == 1
    assert procedencia == {}


# --- El informe ---


AGREGADOS = {
    "recall@3": 0.65,
    "recall@5": 0.79,
    "recall@10": 0.88,
    "recall_unidad@3": 0.91,
    "recall_unidad@5": 0.97,
    "recall_unidad@10": 0.99,
    "mrr": 0.93,
}

TECHOS = {3: 0.754, 5: 0.906, 10: 0.966}

PROCEDENCIA = {"fecha_extraccion": "2026-08-16", "origen": "https://eps.ujaen.es"}


def test_el_informe_distingue_las_peticiones_de_consejo(tmp_path):
    """Que una petición de consejo reciba contexto no es un fallo del filtro.

    El sistema le entrega la banda completa a propósito: quien pregunta qué
    carrera le pega no debe recibir silencio. Si el informe no lo distingue, la
    cifra se lee como si el suelo fallara cuatro veces.
    """
    destino = tmp_path / "informe.md"
    recuperacion.informe(
        AGREGADOS,
        TECHOS,
        [("P-051", 3, False), ("P-053", 20, True), ("P-055", 0, False)],
        [],
        1499,
        56,
        PROCEDENCIA,
        destino,
    )
    escrito = destino.read_text(encoding="utf-8")
    assert "Rechazadas por el recuperador: 1 de 3" in escrito
    assert "**1 son peticiones" in escrito
    assert "0.754" in escrito


def test_el_conjunto_de_validacion_se_informa_aparte(tmp_path):
    """Las dos cifras de rechazo no dicen lo mismo y no pueden mezclarse.

    La del conjunto de IT-27 mide lo bien que se ajustó el suelo, porque es el
    conjunto sobre el que se ajustó. La del otro mide lo bien que el sistema
    rechaza. Sumarlas en una sola cifra las estropearía las dos.
    """
    destino = tmp_path / "informe.md"
    recuperacion.informe(
        AGREGADOS,
        TECHOS,
        [("P-051", 3, False), ("P-055", 0, False)],
        [("V-001", 0, False), ("V-006", 12, False)],
        1499,
        56,
        PROCEDENCIA,
        destino,
    )
    escrito = destino.read_text(encoding="utf-8")
    assert "Rechazadas por el recuperador: 1 de 2" in escrito
    assert "**Rechazadas: 1 de 2.**" in escrito
    assert "V-006" in escrito


def test_sin_conjunto_de_validacion_no_se_inventa_la_seccion(tmp_path):
    """Si el fichero no existe, el informe no debe fingir que sí."""
    destino = tmp_path / "informe.md"
    recuperacion.informe(
        AGREGADOS, TECHOS, [("P-055", 0, False)], [], 1499, 56, PROCEDENCIA, destino
    )
    assert "no intervinieron en el ajuste" not in destino.read_text(encoding="utf-8")

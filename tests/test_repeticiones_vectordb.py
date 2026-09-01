"""Pruebas de las repeticiones de la comparativa de bases vectoriales (IT-113).

Este guion es el que sostiene el umbral U6 del ADR-0004: son las veinte
reconstrucciones que descubrieron que ChromaDB pierde un vecino en cuatro de
cada veinte. Estuvo roto y sin una sola prueba desde que IT-114 agrupó los
guiones en carpetas, así que la evidencia que sostiene una decisión de
arquitectura no se podía regenerar.

**Ninguna prueba construye un índice de verdad.** Lo caro ---incrustar el
corpus y levantar las tres bases--- se sustituye; lo que se mide aquí es el
recorrido, el resumen y el informe, que es lo que el guion aporta por encima
del experimento del que se cuelga.
"""

from __future__ import annotations

import contextlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_RUTA = RAIZ / "scripts" / "experimentos" / "repeticiones_vectordb.py"
_spec = importlib.util.spec_from_file_location("repeticiones_vectordb", _RUTA)
assert _spec is not None and _spec.loader is not None
repeticiones = importlib.util.module_from_spec(_spec)
sys.modules["repeticiones_vectordb"] = repeticiones
_spec.loader.exec_module(repeticiones)


@dataclass
class MedidaFalsa:
    """Lo único que el guion le pide a una medida."""

    fidelidad: float
    latencia_mediana_ms: float


def _preparar(monkeypatch, tmp_path, fidelidades):
    """Sustituye todo lo caro y deja el guion listo para recorrerse.

    Args:
        monkeypatch: Parcheador de pytest.
        tmp_path: Carpeta temporal donde se escribirá el informe.
        fidelidades: Fidelidad que devuelve cada base, por nombre.

    Returns:
        La ruta del informe que el guion escribirá.
    """
    exp = repeticiones.exp
    monkeypatch.setattr(exp, "cargar_corpus", lambda: [{"texto": "uno"}])
    monkeypatch.setattr(exp, "cargar_preguntas", lambda: ["¿qué?"])
    monkeypatch.setattr(exp, "medir_numpy", lambda v, c: (None, [[0]]))

    @contextlib.contextmanager
    def carpeta():
        yield tmp_path

    monkeypatch.setattr(exp, "carpeta_temporal", carpeta)
    monkeypatch.setattr(
        exp,
        "medir_chroma",
        lambda *a: MedidaFalsa(fidelidades["chroma"].pop(0), 1.43),
    )
    monkeypatch.setattr(
        exp, "medir_lancedb", lambda *a: MedidaFalsa(fidelidades["lance"].pop(0), 7.35)
    )
    monkeypatch.setattr(
        exp, "medir_qdrant", lambda *a: MedidaFalsa(fidelidades["qdrant"].pop(0), 5.62)
    )

    from tfg_uja.indexacion import incrustaciones

    monkeypatch.setattr(
        incrustaciones, "incrustador_de_documentos", lambda: (lambda textos: [[1.0]])
    )
    monkeypatch.setattr(
        incrustaciones, "incrustador_de_consultas", lambda: (lambda textos: [[1.0]])
    )

    salida = tmp_path / "docs" / "it31.md"
    monkeypatch.setattr(repeticiones, "SALIDA", salida)
    monkeypatch.setattr(repeticiones, "RAIZ", tmp_path)
    return salida


# --- El resumen por pantalla ------------------------------------------------


def test_el_resumen_dice_en_cuantos_ciclos_falla_el_umbral(capsys):
    """U1 se fijó en 1,000 exacto ANTES de medir: un 0,998 lo incumple."""
    repeticiones.resumir("ChromaDB", [1.0, 0.998, 1.0, 0.998], [1.0, 2.0, 3.0, 4.0])

    salida = capsys.readouterr().out
    assert "U1 FALLA en  : 2 de 4 ciclos (50 %)" in salida
    assert "0.9980" in salida


def test_el_resumen_de_una_candidata_fiel_no_denuncia_nada(capsys):
    repeticiones.resumir("LanceDB", [1.0, 1.0], [7.0, 8.0])

    salida = capsys.readouterr().out
    assert "0 de 2 ciclos (0 %)" in salida
    assert "mediana=7.50" in salida


# --- El informe -------------------------------------------------------------


def _registro(chroma=(1.0, 0.998), lance=(1.0, 1.0), qdrant=(1.0, 1.0)):
    """El registro con la forma que `main` va acumulando."""
    return {
        "ChromaDB": {"fidelidad": list(chroma), "latencia": [1.43, 1.50]},
        "LanceDB": {"fidelidad": list(lance), "latencia": [7.35, 7.40]},
        "Qdrant": {"fidelidad": list(qdrant), "latencia": [5.62, 5.70]},
    }


def test_el_informe_marca_como_incumplidora_a_la_que_pierde_un_vecino():
    texto = repeticiones.informe(_registro(), ciclos=2)

    fila_chroma = [ln for ln in texto.split("\n") if ln.startswith("| ChromaDB")][0]
    fila_lance = [ln for ln in texto.split("\n") if ln.startswith("| LanceDB")][0]
    assert "1 de 2" in fila_chroma and fila_chroma.rstrip().endswith("no |")
    assert "0 de 2" in fila_lance and fila_lance.rstrip().endswith("sí |")


def test_el_informe_dice_donde_esta_la_variabilidad():
    """En la construcción del índice, no en la consulta: consultar es estable."""
    texto = repeticiones.informe(_registro(), ciclos=20)

    assert "**20 reconstrucciones completas**" in texto
    assert "no en la consulta" in texto


def test_el_informe_nombra_su_propia_ruta():
    """Si el guion se mueve y la ruta no, el informe dice quién no lo escribió."""
    texto = repeticiones.informe(_registro(), ciclos=2)

    assert "`scripts/experimentos/repeticiones_vectordb.py`" in texto


# --- El recorrido entero ----------------------------------------------------


def test_main_recorre_los_ciclos_pedidos(tmp_path, monkeypatch, capsys):
    fidelidades = {
        "chroma": [1.0, 0.998],
        "lance": [1.0, 1.0],
        "qdrant": [1.0, 1.0],
    }
    salida = _preparar(monkeypatch, tmp_path, fidelidades)

    repeticiones.main(["2"])

    texto = capsys.readouterr().out
    assert "2 ciclos" in texto
    assert "ciclo  1/2" in texto and "ciclo  2/2" in texto
    assert "RESUMEN DE 2 CICLOS" in texto
    assert salida.exists()


def test_main_sin_argumentos_usa_los_veinte_ciclos_por_defecto(
    tmp_path, monkeypatch, capsys
):
    """Con 20, un fallo de uno de cada cinco aparece varias veces y no es azar."""
    n = repeticiones.CICLOS
    fidelidades = {
        "chroma": [1.0] * n,
        "lance": [1.0] * n,
        "qdrant": [1.0] * n,
    }
    _preparar(monkeypatch, tmp_path, fidelidades)

    repeticiones.main([])

    assert f"RESUMEN DE {n} CICLOS" in capsys.readouterr().out


def test_main_escribe_el_informe_creando_su_carpeta(tmp_path, monkeypatch):
    """El informe se versiona: la tabla de U6 no depende de una transcripción."""
    fidelidades: dict[str, list[Any]] = {
        "chroma": [0.998],
        "lance": [1.0],
        "qdrant": [1.0],
    }
    salida = _preparar(monkeypatch, tmp_path, fidelidades)
    assert not salida.parent.exists()

    repeticiones.main(["1"])

    assert "| ChromaDB |" in salida.read_text(encoding="utf-8")


def test_el_guion_carga_el_experimento_del_que_se_cuelga():
    """Regresión de IT-111: la ruta apuntaba a la carpeta anterior al agrupado."""
    assert repeticiones.exp.__name__ == "experimento_vectordb"
    assert hasattr(repeticiones.exp, "medir_lancedb")


@pytest.mark.parametrize("base", ["ChromaDB", "LanceDB", "Qdrant"])
def test_el_registro_lleva_las_tres_candidatas(tmp_path, monkeypatch, base):
    fidelidades = {"chroma": [1.0], "lance": [1.0], "qdrant": [1.0]}
    salida = _preparar(monkeypatch, tmp_path, fidelidades)

    repeticiones.main(["1"])

    assert f"| {base} |" in salida.read_text(encoding="utf-8")

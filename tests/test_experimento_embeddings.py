"""Pruebas del experimento comparativo de incrustaciones (IT-28).

El experimento necesita red y PyTorch, así que no se ejecuta aquí. Lo que sí
se puede comprobar sin nada de eso es lo que decide qué dice la tabla: el
techo de Recall@K, el formato de las filas y qué ocurre cuando una de las
medidas falta.

Esa última parte es la importante. La comparativa de IT-28 solo es válida
porque la tabla dice cuánto corpus ha leído cada modelo ---sin esa columna, el
margen entre el primero y el último no distingue «mejor modelo» de «modelo que
sí lee el fragmento entero», que es el hallazgo de IT-29---, y una medida
ausente no puede acabar pareciendo un cero.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_RUTA = RAIZ / "scripts" / "experimentos" / "experimento_embeddings.py"
_spec = importlib.util.spec_from_file_location("experimento_embeddings", _RUTA)
assert _spec is not None and _spec.loader is not None
experimento = importlib.util.module_from_spec(_spec)
sys.modules["experimento_embeddings"] = experimento
_spec.loader.exec_module(experimento)


class _TokenizadorFalso:
    """Tokenizador que parte por espacios, para no cargar ningún modelo."""

    def encode(self, texto: str, add_special_tokens: bool = True) -> list[int]:
        return list(range(len(texto.split())))


class _ModeloFalso:
    """Lo mínimo que ``medir_truncado`` mira de un ``SentenceTransformer``."""

    def __init__(self, max_seq_length: int) -> None:
        self.max_seq_length = max_seq_length
        self.tokenizer = _TokenizadorFalso()


def _fila(nombre: str, **contexto) -> dict:
    """Fila de resultados con las métricas ya calculadas."""
    base = {
        "nombre": nombre,
        "mrr": 0.9,
        "tiempo_s": 12.3,
        "ventana": 510,
        "truncados": 0,
        "fraccion_leida": 1.0,
        "por_tipo": {"temario": {"n": 20, "recall@5": 0.8}},
    }
    for k in experimento.KS:
        base[f"recall@{k}"] = 0.5
        base[f"recall_unidad@{k}"] = 0.9
    return {**base, **contexto}


# --- El techo de Recall@K --------------------------------------------------


def test_el_techo_por_fragmento_no_es_uno() -> None:
    """Una unidad repartida en más de K fragmentos no cabe en el top-K.

    Con dos preguntas, una de 1 fragmento relevante y otra de 4, el techo de
    R@3 es la media de 1/1 y 3/4, o sea 0,875. Escribir 1 en su lugar haría
    leer como un fallo del recuperador lo que es una propiedad de la métrica.
    """
    chunks = [
        {"origen": "guia", "nombre": "Sola", "grados": ["G"], "codigos": ["1"]},
    ] + [
        {"origen": "guia", "nombre": "Partida", "grados": ["G"], "codigos": ["2"]}
        for _ in range(4)
    ]
    preguntas = [
        {"id": "P-1", "relevantes": [{"origen": "guia", "nombre": "Sola"}]},
        {"id": "P-2", "relevantes": [{"origen": "guia", "nombre": "Partida"}]},
    ]

    techos = experimento.techos_de_recall(preguntas, chunks)

    assert techos[3] == (1.0 + 3 / 4) / 2
    assert techos[10] == 1.0


# --- La medida de la ventana -----------------------------------------------


def test_un_corpus_que_cabe_entero_no_trunca_nada() -> None:
    modelo = _ModeloFalso(max_seq_length=12)

    ventana, truncados, fraccion = medir = experimento.medir_truncado(
        modelo, ["una dos tres", "cuatro cinco"], ""
    )

    assert medir is not None
    assert ventana == 10
    assert truncados == 0
    assert fraccion == 1.0


def test_el_prefijo_cuenta_como_tokens() -> None:
    """El prefijo de los modelos E5 ocupa sitio en la ventana.

    Medir sin él diría que un fragmento cabe cuando en realidad se recorta.
    """
    modelo = _ModeloFalso(max_seq_length=5)
    texto = "uno dos tres"

    _, sin_prefijo, _ = experimento.medir_truncado(modelo, [texto], "")
    _, con_prefijo, _ = experimento.medir_truncado(modelo, [texto], "passage: uno ")

    assert sin_prefijo == 0
    assert con_prefijo == 1


def test_un_corpus_vacio_no_revienta_la_medida() -> None:
    """Sin tokens que contar, la fracción leída no se puede dividir.

    La división por cero ocurría dentro del bloque que captura excepciones, así
    que un corpus vacío se contabilizaba como «este modelo ha fallado».
    """
    ventana, truncados, fraccion = experimento.medir_truncado(_ModeloFalso(12), [], "")

    assert (ventana, truncados, fraccion) == (10, 0, 0.0)


# --- Qué dice la tabla cuando falta una medida -----------------------------


def test_la_tabla_escribe_las_medidas_que_hay() -> None:
    tabla = experimento.formatear_tabla([_fila("modelo/a")])

    assert "| 510 | 0 | 100% |" in tabla


def test_una_medida_ausente_no_se_escribe_como_cero() -> None:
    """Regresión: «sin medir» y «0 truncados» son afirmaciones distintas.

    Un 0 en la columna de truncados dice que el modelo lee el corpus entero,
    que es precisamente lo que no se sabe cuando la medida ha fallado. Con la
    tabla mintiendo ahí, la comparativa volvería al defecto que IT-29 destapó:
    atribuir a la calidad del modelo una diferencia que era de cuánto texto
    llegó a leer.
    """
    fila = _fila("modelo/b", ventana=None, truncados=None, fraccion_leida=None)

    tabla = experimento.formatear_tabla([fila])

    assert "sin medir | sin medir | sin medir |" in tabla
    assert "| 0 |" not in tabla
    assert "0%" not in tabla


def test_las_metricas_siguen_saliendo_aunque_falte_la_ventana() -> None:
    """La fila no se pierde: lo que se ha medido bien se publica igual."""
    fila = _fila("modelo/b", ventana=None, truncados=None, fraccion_leida=None)

    tabla = experimento.formatear_tabla([fila])

    assert "modelo/b" in tabla
    assert "0.900" in tabla

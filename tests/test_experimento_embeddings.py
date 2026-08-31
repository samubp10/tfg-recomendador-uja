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


# --- Carga, incrustadores, dispositivo y recorrido entero (IT-113) ----------

import json  # noqa: E402
import types  # noqa: E402

import pytest  # noqa: E402


def test_la_procedencia_no_se_incrusta_como_si_fuera_corpus(tmp_path, monkeypatch):
    """Incrustarla falsearía las métricas: describe el corpus, no es corpus."""
    corpus = tmp_path / "chunks.json"
    corpus.write_text(
        json.dumps(
            [
                {"tipo": "procedencia", "fecha_extraccion": "2026-08-16"},
                {"tipo": "chunk", "texto": "uno"},
                {"tipo": "chunk", "texto": "dos"},
            ]
        ),
        encoding="utf-8",
    )
    evalset = tmp_path / "evalset.json"
    evalset.write_text(json.dumps({"preguntas": [{"id": "p1"}]}), encoding="utf-8")
    monkeypatch.setattr(experimento, "RUTA_EVAL", evalset)

    chunks, preguntas = experimento.cargar_datos(corpus)

    assert len(chunks) == 2
    assert len(preguntas) == 1


class _SentenceTransformerFalso:
    """Sustituto de la clase real, que arrastraría PyTorch."""

    def __init__(self, nombre, trust_remote_code=False):
        self.nombre = nombre
        self.trust_remote_code = trust_remote_code
        self.max_seq_length = 512
        self.tokenizer = _TokenizadorFalso()
        self.recibidos: list[list[str]] = []

    def encode(self, textos, batch_size=None, show_progress_bar=False):
        self.recibidos.append(list(textos))
        return _Vectores([[float(len(t))] for t in textos])


class _Vectores(list):
    """Lo que devuelve `encode`: hace falta que sepa convertirse a lista."""

    def tolist(self):
        return list(self)


@pytest.fixture
def sin_sentence_transformers(monkeypatch):
    """Inyecta un `sentence_transformers` de mentira en el camino de imports."""
    modulo = types.ModuleType("sentence_transformers")
    modulo.SentenceTransformer = _SentenceTransformerFalso  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", modulo)
    return modulo


def test_cada_incrustador_antepone_el_prefijo_de_su_papel(
    sin_sentence_transformers,
):
    """La convención de e5 distingue consulta de documento (ADR-0003)."""
    candidato = experimento.ModeloCandidato(
        nombre="m",
        descripcion="d",
        prefijo_consulta="query: ",
        prefijo_documento="passage: ",
    )

    doc, consulta, modelo = experimento.crear_incrustadores(candidato)
    doc(["texto"])
    consulta(["texto"])

    assert modelo.recibidos[0] == ["passage: texto"]
    assert modelo.recibidos[1] == ["query: texto"]


def test_el_codigo_remoto_se_declara_explicitamente(sin_sentence_transformers):
    """Es una decisión de confianza, no un detalle de configuración."""
    candidato = experimento.ModeloCandidato(
        nombre="m", descripcion="d", codigo_remoto=True
    )

    _doc, _consulta, modelo = experimento.crear_incrustadores(candidato)

    assert modelo.trust_remote_code is True


def _con_torch(monkeypatch, hay_gpu, nombre="RTX 4060"):
    """Inyecta un `torch` de mentira."""
    modulo = types.ModuleType("torch")
    modulo.cuda = types.SimpleNamespace(  # type: ignore[attr-defined]
        is_available=lambda: hay_gpu, get_device_name=lambda i: nombre
    )
    monkeypatch.setitem(sys.modules, "torch", modulo)


def test_el_informe_dice_si_se_midio_en_gpu(monkeypatch):
    """Los tiempos no se pueden comparar entre ejecuciones si cambia el aparato."""
    _con_torch(monkeypatch, hay_gpu=True)

    assert experimento._dispositivo() == "GPU (RTX 4060)"


def test_el_informe_dice_cpu_cuando_no_hay_gpu(monkeypatch):
    _con_torch(monkeypatch, hay_gpu=False)

    assert experimento._dispositivo() == "CPU"


# --- La evaluación de un candidato ------------------------------------------


def _resultado_de_evaluar():
    agregados = {"mrr": 0.970}
    for k in experimento.KS:
        agregados[f"recall@{k}"] = 0.7
        agregados[f"recall_unidad@{k}"] = 0.9
    return {"agregados": agregados, "por_tipo": {}}


def test_un_candidato_evaluado_trae_sus_medidas_de_contexto(monkeypatch):
    monkeypatch.setattr(
        experimento,
        "crear_incrustadores",
        lambda c: (None, None, _ModeloFalso(10)),
    )
    candidato = experimento.ModeloCandidato(nombre="m", descripcion="d")

    fila, aviso = experimento._evaluar_candidato(
        candidato,
        [{"texto": "una dos"}],
        [{"id": "p"}],
        lambda *a, **kw: _resultado_de_evaluar(),
    )

    assert aviso is None
    assert fila["nombre"] == "m"
    assert fila["ventana"] == 8


def test_si_falla_la_ventana_las_metricas_se_conservan(monkeypatch):
    """Son dos cosas distintas: no poder evaluar, y evaluar sin saber cuánto lee.

    Antes el fallo al tokenizar tiraba unas métricas ya calculadas bien.
    """
    monkeypatch.setattr(
        experimento, "crear_incrustadores", lambda c: (None, None, _ModeloFalso(10))
    )

    def revienta(*a, **kw):
        raise RuntimeError("tokenizador raro")

    monkeypatch.setattr(experimento, "medir_truncado", revienta)
    candidato = experimento.ModeloCandidato(nombre="m", descripcion="d")

    fila, aviso = experimento._evaluar_candidato(
        candidato,
        [{"texto": "una"}],
        [{"id": "p"}],
        lambda *a, **kw: _resultado_de_evaluar(),
    )

    assert aviso is not None and "m" in aviso
    assert fila["ventana"] is None
    assert fila["mrr"] == 0.970


# --- Lo que se imprime ------------------------------------------------------


def test_se_avisa_por_pantalla_de_los_fragmentos_truncados(capsys):
    """`encode` recorta en silencio: si no se dice, la tabla engaña."""
    fila = _fila("m", ventana=128, truncados=40, fraccion_leida=0.62)

    experimento._imprimir_resultado(fila, total_chunks=1334)

    salida = capsys.readouterr().out
    assert "40 de 1334 fragmentos se truncan" in salida
    assert "62.00%" in salida


def test_sin_truncado_no_se_avisa(capsys):
    fila = _fila("m", ventana=512, truncados=0, fraccion_leida=1.0)

    experimento._imprimir_resultado(fila, total_chunks=1334)

    assert "AVISO" not in capsys.readouterr().out


def test_los_techos_se_redactan_una_sola_vez():
    """La misma frase va por consola y al informe: separadas, una envejece."""
    texto = experimento._texto_de_techos({3: 0.789, 5: 0.906})

    assert "**0.789** para R@3" in texto
    assert "**0.906** para R@5" in texto


def test_la_cabecera_lleva_la_ruta_relativa_del_corpus(tmp_path, monkeypatch):
    """La absoluta lleva el nombre de usuario y no significa nada fuera.

    La raiz se sustituye por una carpeta real: en un arbol de trabajo, `data/`
    es un enlace al del repositorio principal y `resolve()` lo sigue fuera del
    arbol, con lo que la ruta relativa no se puede calcular.
    """
    _con_torch(monkeypatch, hay_gpu=False)
    monkeypatch.setattr(experimento, "RAIZ", tmp_path)
    corpus = tmp_path / "data" / "chunks.json"
    corpus.parent.mkdir()
    corpus.write_text("{}", encoding="utf-8")

    cabecera = experimento._cabecera_del_informe(corpus, 1499, 66)

    assert "`data/chunks.json`" in cabecera
    assert "1499 fragmentos, 66 preguntas" in cabecera
    assert "**CPU**" in cabecera


def test_un_corpus_de_fuera_del_repositorio_se_nombra_por_su_fichero(
    tmp_path, monkeypatch
):
    _con_torch(monkeypatch, hay_gpu=False)

    cabecera = experimento._cabecera_del_informe(tmp_path / "otro.json", 10, 2)

    assert "`otro.json`" in cabecera


# --- El recorrido entero ----------------------------------------------------


def _preparar_main(tmp_path, monkeypatch, resultado_por_candidato):
    corpus = tmp_path / "chunks.json"
    corpus.write_text(
        json.dumps(
            [{"tipo": "chunk", "texto": "uno", "nombre": "U", "origen": "guia"}]
        ),
        encoding="utf-8",
    )
    evalset = tmp_path / "evalset.json"
    evalset.write_text(
        json.dumps(
            {
                "preguntas": [
                    {
                        "id": "p1",
                        "tipo": "temario",
                        "pregunta": "¿?",
                        "relevantes": [{"origen": "guia", "nombre": "U"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(experimento, "RUTA_EVAL", evalset)
    monkeypatch.setattr(experimento, "_evaluar_candidato", resultado_por_candidato)
    monkeypatch.setattr(
        experimento, "CANDIDATOS", [experimento.ModeloCandidato("m", "d")]
    )
    _con_torch(monkeypatch, hay_gpu=False)

    salida = tmp_path / "sub" / "adr.md"
    salida.parent.mkdir(parents=True)
    salida.write_text(
        f"# ADR\n\n{experimento.MARCA_INICIO}\nviejo\n\n{experimento.MARCA_FIN}\n",
        encoding="utf-8",
    )
    return corpus, salida


def test_main_sale_con_cero_cuando_todo_se_midio(tmp_path, monkeypatch, capsys):
    corpus, salida = _preparar_main(
        tmp_path,
        monkeypatch,
        lambda c, ch, p, e: (
            _fila("m", ventana=512, truncados=0, fraccion_leida=1.0),
            None,
        ),
    )

    codigo = experimento.main(["--chunks", str(corpus), "--salida", str(salida)])

    assert codigo == 0
    assert "Anexo de adr.md reescrito." in capsys.readouterr().out


def test_main_sale_con_uno_si_un_modelo_no_pudo_caracterizarse(
    tmp_path, monkeypatch, capsys
):
    """Sin la columna de truncado no se separa «mejor» de «lee el fragmento entero»."""
    corpus, salida = _preparar_main(
        tmp_path,
        monkeypatch,
        lambda c, ch, p, e: (_fila("m"), "m: no se pudo medir la ventana"),
    )

    codigo = experimento.main(["--chunks", str(corpus), "--salida", str(salida)])

    assert codigo == 1
    assert "AVISO: m: no se pudo medir la ventana" in capsys.readouterr().out


def test_main_sigue_con_el_resto_si_un_candidato_revienta(
    tmp_path, monkeypatch, capsys
):
    def cae(c, ch, p, e):
        raise RuntimeError("no se pudo descargar")

    corpus, salida = _preparar_main(tmp_path, monkeypatch, cae)

    codigo = experimento.main(["--chunks", str(corpus), "--salida", str(salida)])

    assert codigo == 1
    assert "Ningún modelo pudo evaluarse." in capsys.readouterr().out


def test_el_pie_declara_los_modelos_que_no_pudieron_descargarse():
    """Una comparativa a la que le falta un candidato tiene que decirlo."""
    pie = experimento._pie_del_informe(
        "| tabla |", "techos.", ["bge-m3: sin memoria"], []
    )

    assert "### Fallos" in pie
    assert "bge-m3: sin memoria" in pie

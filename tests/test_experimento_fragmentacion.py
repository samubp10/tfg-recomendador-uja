"""Pruebas de la rejilla de fragmentación (IT-113).

Es el experimento del ADR-0001: las 45 configuraciones que fijaron el tamaño de
fragmento en 900/900. Tarda alrededor de una hora y no tenía ninguna prueba, de
modo que un defecto en la rejilla solo se habría visto repitiéndola.

**Ninguna prueba carga el modelo ni incrusta de verdad.** El incrustador se
sustituye por uno determinista, que basta porque lo que se comprueba es dónde
corta cada estrategia, no qué vectores salen. La colección es la muestra real
de ``tests/fixtures/dataset_muestra.json``.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "experimentos"))

import experimento_fragmentacion as rejilla  # noqa: E402

from tfg_uja import chunker  # noqa: E402

MUESTRA = json.loads(
    (RAIZ / "tests" / "fixtures" / "dataset_muestra.json").read_text(encoding="utf-8")
)


@pytest.fixture(autouse=True)
def _cache_limpia():
    """La caché de incrustaciones es del módulo: se vacía entre pruebas.

    Sin esto, una prueba se encuentra los vectores que dejó otra y pasa por el
    trabajo de su vecina, que es el modo de fallo que este proyecto persigue.
    """
    rejilla._CACHE.clear()
    yield
    rejilla._CACHE.clear()


def incrustador_determinista(textos):
    """Vector de dos dimensiones que solo depende del texto.

    No se parece a un modelo real y no hace falta: lo que se prueba es la
    política de corte, que solo mira si la distancia supera el umbral.
    """
    return [[float(len(t) % 7), float(len(t) % 3)] for t in textos]


# --- La caché de incrustaciones ---------------------------------------------


def test_una_pieza_ya_incrustada_no_se_vuelve_a_pedir():
    pedidos = []

    def espia(textos):
        pedidos.append(list(textos))
        return incrustador_determinista(textos)

    rejilla._incrustar_piezas(["uno", "dos"], espia)
    rejilla._incrustar_piezas(["dos", "tres"], espia)

    assert pedidos == [["uno", "dos"], ["tres"]]


def test_las_piezas_salen_en_su_orden():
    vectores = rejilla._incrustar_piezas(["a", "bb"], incrustador_determinista)

    assert vectores.shape == (2, 2)
    assert list(vectores[0]) == [1.0, 1.0]


def test_un_incrustador_que_devuelve_de_menos_revienta():
    """Un zip normal truncaría en silencio y las piezas sobrantes se perderían."""
    with pytest.raises(ValueError):
        rejilla._incrustar_piezas(["uno", "dos"], lambda t: [[1.0, 0.0]])


# --- Las distancias ---------------------------------------------------------


def test_dos_vectores_iguales_estan_a_distancia_cero():
    vectores = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)

    assert rejilla._distancias_consecutivas(vectores) == pytest.approx([0.0])


def test_dos_vectores_perpendiculares_estan_a_distancia_uno():
    vectores = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

    assert rejilla._distancias_consecutivas(vectores) == pytest.approx([1.0])


def test_un_vector_nulo_no_divide_entre_cero():
    """Una pieza que se incrusta a cero no puede reventar la rejilla entera."""
    vectores = np.array([[0.0, 0.0], [1.0, 0.0]], dtype=np.float32)

    assert rejilla._distancias_consecutivas(vectores) == pytest.approx([1.0])


def test_un_solo_vector_no_tiene_distancias():
    assert rejilla._distancias_consecutivas(np.array([[1.0, 0.0]])) == []


# --- La forma de los fragmentos ---------------------------------------------


def test_cada_fragmento_lleva_su_encabezado_y_su_numeracion():
    chunks = rejilla._construir_chunks(
        "«Cálculo»", ["uno", "dos"], {"nombre": "Cálculo"}, "guia"
    )

    assert [c["texto"] for c in chunks] == ["«Cálculo»\nuno", "«Cálculo»\ndos"]
    assert [c["chunk_index"] for c in chunks] == [0, 1]
    assert all(c["total_chunks"] == 2 for c in chunks)
    assert all(c["origen"] == "guia" for c in chunks)


# --- La sustitución del troceador -------------------------------------------


def test_el_troceador_original_se_devuelve_aunque_falle():
    """Una configuración que reviente a medias contaminaría las siguientes."""
    original = chunker._chunks_de_unidad

    def revienta(*a, **kw):
        raise RuntimeError("configuración mala")

    with pytest.raises(RuntimeError):
        rejilla._trocear_con(revienta, MUESTRA, (900, 900, 200))

    assert chunker._chunks_de_unidad is original


def test_trocear_con_el_original_da_el_corpus_de_siempre():
    chunks = rejilla._trocear_con(chunker._chunks_de_unidad, MUESTRA, (900, 900, 200))

    assert chunks
    assert all(len(c["texto"]) <= 900 for c in chunks)


# --- El agrupado semántico --------------------------------------------------


def test_se_abre_grupo_donde_el_salto_supera_el_umbral():
    grupos = rejilla._agrupar_por_salto(["a", "b", "c"], [0.1, 0.9], umbral=0.5)

    assert grupos == [["a", "b"], ["c"]]


def test_sin_saltos_grandes_todo_queda_en_un_grupo():
    grupos = rejilla._agrupar_por_salto(["a", "b", "c"], [0.1, 0.2], umbral=0.5)

    assert grupos == [["a", "b", "c"]]


def test_un_grupo_que_no_cabe_se_reparte():
    """Ningun cuerpo puede pasarse del maximo: es la restriccion dura.

    Las piezas se pasan ya por debajo del maximo, que es como llegan de
    `_dividir_en_piezas`: el reparto agrupa piezas, no las parte.
    """
    cuerpos = rejilla._unir_grupos([["x" * 30, "y" * 30]], maximo=50)

    assert len(cuerpos) > 1
    assert all(len(c) <= 50 for c in cuerpos)


def test_un_grupo_que_cabe_se_une_entero():
    assert rejilla._unir_grupos([["uno", "dos"]], maximo=100) == ["uno\ndos"]


# --- Las dos estrategias alternativas ---------------------------------------


BASE = {"grados": ["G"], "codigos": ["1"], "nombre": "Cálculo"}


def test_la_estrategia_semantica_respeta_el_maximo():
    trocear = rejilla.hacer_semantico(0.5, incrustador_determinista)
    texto = "\n\n".join(f"Parrafo {i}. " * 12 for i in range(8))

    chunks = trocear("«Cálculo»", texto, dict(BASE), "guia", (900, 900, 200))

    assert chunks
    assert all(len(c["texto"]) <= 900 for c in chunks)


def test_la_semantica_con_una_sola_pieza_no_incrusta_nada():
    """Sin dos piezas no hay salto que medir: llamar al modelo sería gasto."""
    llamadas = []

    def espia(textos):
        llamadas.append(textos)
        return incrustador_determinista(textos)

    trocear = rejilla.hacer_semantico(0.5, espia)
    chunks = trocear(
        "«Cálculo»", "Un texto corto.", dict(BASE), "guia", (900, 900, 200)
    )

    assert len(chunks) == 1
    assert llamadas == []


def test_la_semantica_sobre_un_texto_vacio_no_produce_nada():
    trocear = rejilla.hacer_semantico(0.5, incrustador_determinista)

    assert trocear("«Cálculo»", "", dict(BASE), "guia", (900, 900, 200)) == []


def test_la_estrategia_fija_avanza_contando_caracteres():
    trocear = rejilla.hacer_fijo(0.0)
    texto = "x" * 2000

    chunks = trocear("«Cálculo»", texto, dict(BASE), "guia", (900, 900, 200))

    assert len(chunks) > 1
    assert all(len(c["texto"]) <= 900 for c in chunks)


def test_la_fija_con_solape_produce_mas_fragmentos_que_sin_el():
    texto = "x" * 3000

    sin_solape = rejilla.hacer_fijo(0.0)(
        "«C»", texto, dict(BASE), "guia", (900, 900, 200)
    )
    con_solape = rejilla.hacer_fijo(0.2)(
        "«C»", texto, dict(BASE), "guia", (900, 900, 200)
    )

    assert len(con_solape) >= len(sin_solape)


def test_la_fija_sobre_un_texto_vacio_devuelve_el_texto_tal_cual():
    chunks = rejilla.hacer_fijo(0.0)("«C»", "", dict(BASE), "guia", (900, 900, 200))

    assert len(chunks) == 1


# --- El techo por fragmento -------------------------------------------------


def _chunk(nombre, origen="guia"):
    return {"tipo": "chunk", "origen": origen, "nombre": nombre, "grados": ["G"]}


def _pregunta(*unidades):
    return {
        "id": "p",
        "tipo": "temario",
        "pregunta": "¿?",
        "relevantes": [{"origen": o, "nombre": n} for o, n in unidades],
    }


def test_una_unidad_repartida_en_mas_de_k_no_cabe_entera():
    """Por eso el techo se recalcula para cada fragmentación."""
    chunks = [_chunk("U") for _ in range(5)]

    assert rejilla.techo_por_fragmento(chunks, [_pregunta(("guia", "U"))], 2) == 0.4


def test_si_la_unidad_cabe_entera_el_techo_es_uno():
    chunks = [_chunk("U")]

    assert rejilla.techo_por_fragmento(chunks, [_pregunta(("guia", "U"))], 5) == 1.0


def test_una_pregunta_sin_relevantes_aporta_cero():
    assert rejilla.techo_por_fragmento([_chunk("U")], [_pregunta()], 5) == 0.0


def test_sin_preguntas_el_techo_es_cero():
    assert rejilla.techo_por_fragmento([_chunk("U")], [], 5) == 0.0


# --- Las distancias del corpus y la rejilla ---------------------------------


def test_las_distancias_se_miden_por_unidad():
    """La frontera entre dos unidades no es un salto interno y contaminaría."""
    distancias = rejilla._distancias_del_corpus(
        MUESTRA, incrustador_determinista, chunker._chunks_de_unidad, 900
    )

    assert distancias
    # El coseno cae en [0, 2]; el epsilon es el error de punto flotante de
    # normalizar y multiplicar, no un margen elegido para que pase.
    assert all(math.isfinite(d) for d in distancias)
    assert min(distancias) >= -1e-6
    assert max(distancias) <= 2.0 + 1e-6


def test_las_tres_estrategias_aportan_el_mismo_numero_de_variantes():
    """Ninguna puede competir con más intentos que otra."""
    umbrales = {p: 0.5 for p in rejilla.PERCENTILES}

    configuraciones = rejilla._configuraciones(
        900, umbrales, chunker._chunks_de_unidad, incrustador_determinista
    )

    por_estrategia = {}
    for estrategia, _ajuste, _funcion, _tamanos in configuraciones:
        por_estrategia[estrategia] = por_estrategia.get(estrategia, 0) + 1
    assert len(set(por_estrategia.values())) == 1
    assert set(por_estrategia) == {"estructural", "semantica", "fijo"}


# --- La evaluación de una configuración -------------------------------------


def test_la_columna_de_tiempo_no_incluye_el_troceo(monkeypatch):
    """Se llama `segundos_evaluacion` a propósito: no es el coste de la estrategia."""
    agregados = {"mrr": 0.9}
    for k in rejilla.KS:
        agregados[f"recall@{k}"] = 0.5
        agregados[f"recall_unidad@{k}"] = 0.8
    monkeypatch.setattr(
        rejilla, "evaluar_modelo", lambda *a, **kw: {"agregados": agregados}
    )
    chunks = [dict(_chunk("U"), texto="x" * 100)]

    fila = rejilla._evaluar(
        chunks, [_pregunta(("guia", "U"))], None, None, lambda ts: [10], 512
    )

    assert fila["fragmentos"] == 1
    assert fila["mediana"] == 100
    assert fila["truncados"] == 0
    assert "segundos_evaluacion" in fila


def test_un_fragmento_que_no_cabe_en_la_ventana_se_cuenta(monkeypatch):
    agregados = {"mrr": 0.9}
    for k in rejilla.KS:
        agregados[f"recall@{k}"] = 0.5
        agregados[f"recall_unidad@{k}"] = 0.8
    monkeypatch.setattr(
        rejilla, "evaluar_modelo", lambda *a, **kw: {"agregados": agregados}
    )
    chunks = [dict(_chunk("U"), texto="x")]

    fila = rejilla._evaluar(chunks, [], None, None, lambda ts: [999], 512)

    assert fila["truncados"] == 1


# --- Las entradas y el modelo -----------------------------------------------


def test_las_preguntas_se_leen_tanto_de_una_lista_como_de_un_documento(
    tmp_path, monkeypatch
):
    """El fichero ha tenido las dos formas a lo largo del proyecto."""
    dataset = tmp_path / "grados.json"
    dataset.write_text(json.dumps(MUESTRA), encoding="utf-8")
    preguntas = tmp_path / "preguntas.json"
    monkeypatch.setattr(rejilla, "RUTA_DATASET", dataset)
    monkeypatch.setattr(rejilla, "RUTA_PREGUNTAS", preguntas)

    preguntas.write_text(json.dumps({"preguntas": [{"id": "p"}]}), encoding="utf-8")
    _datos, como_documento = rejilla._cargar_entradas()

    preguntas.write_text(json.dumps([{"id": "p"}]), encoding="utf-8")
    _datos, como_lista = rejilla._cargar_entradas()

    assert como_documento == como_lista == [{"id": "p"}]


class _ModeloFalso:
    """Lo que la rejilla le pide a un SentenceTransformer."""

    max_seq_length = 512

    def encode(self, textos, show_progress_bar=False):
        class _V(list):
            def tolist(self):
                return list(self)

        return _V(incrustador_determinista(textos))

    def tokenizer(self, textos):
        return {"input_ids": [list(range(len(t.split()))) for t in textos]}


def test_el_modelo_se_carga_una_sola_vez_para_los_dos_papeles(monkeypatch):
    """Cargarlo por cada papel son 2,5 GB innecesarios en esta máquina."""
    import types

    creados = []

    def crear(nombre):
        creados.append(nombre)
        return _ModeloFalso()

    modulo = types.ModuleType("sentence_transformers")
    modulo.SentenceTransformer = crear  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", modulo)

    doc, consulta, tokenizar, ventana = rejilla._cargar_modelo()

    assert len(creados) == 1
    assert ventana == 512
    assert tokenizar(["una dos tres"]) == [3]
    assert doc(["texto"]) and consulta(["texto"])


# --- El informe -------------------------------------------------------------


def _fila(estrategia="estructural", maximo=900, ajuste="objetivo 100%"):
    fila = {
        "estrategia": estrategia,
        "maximo": maximo,
        "ajuste": ajuste,
        "fragmentos": 1334,
        "mediana": 836,
        "maximo_real": 900,
        "truncados": 0,
        "segundos_evaluacion": 12.3,
        "mrr": 0.949,
    }
    for k in rejilla.KS:
        fila[f"ru@{k}"] = 0.9
        fila[f"r@{k}"] = 0.7
        fila[f"techo@{k}"] = 0.95
    return fila


def test_el_avance_se_imprime_por_configuracion(capsys):
    """Son 45 configuraciones y una hora: sin avance parece que se ha colgado."""
    rejilla._imprimir_avance(7, 45, _fila())

    salida = capsys.readouterr().out
    assert "[ 7/45]" in salida
    assert "estructural" in salida


def test_la_cabecera_dice_contra_que_se_midio():
    lineas = rejilla._cabecera_del_informe(45, 50, 512)

    texto = "\n".join(lineas)
    assert "45" in texto
    assert "50" in texto


def test_la_tabla_lleva_una_fila_por_configuracion():
    lineas = rejilla._tabla_del_informe([_fila(), _fila("fijo", ajuste="solape 10%")])

    texto = "\n".join(lineas)
    assert "estructural" in texto
    assert "fijo" in texto


def test_el_informe_se_escribe_entre_las_marcas_del_adr(tmp_path, monkeypatch):
    """El resto del ADR lo escribe el autor y el guion no lo toca."""
    adr = tmp_path / "adr-0001.md"
    adr.write_text(
        f"# ADR\n\nProsa del autor.\n\n{rejilla.MARCA_INICIO}\nviejo\n\n"
        f"{rejilla.MARCA_FIN}\n\n## Decisión\n\nMás prosa.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rejilla, "RUTA_SALIDA", adr)

    rejilla._escribir_informe([_fila()], 50, 512)

    texto = adr.read_text(encoding="utf-8")
    assert "Prosa del autor." in texto
    assert "Más prosa." in texto
    assert "viejo" not in texto


def test_sin_las_marcas_el_guion_no_escribe_nada(tmp_path, monkeypatch):
    adr = tmp_path / "adr-0001.md"
    adr.write_text("# ADR\n\nSin marcas.\n", encoding="utf-8")
    monkeypatch.setattr(rejilla, "RUTA_SALIDA", adr)

    with pytest.raises(SystemExit, match="marcas"):
        rejilla.escribir_en_el_adr("bloque")

    assert adr.read_text(encoding="utf-8") == "# ADR\n\nSin marcas.\n"


# --- El recorrido entero ----------------------------------------------------


def test_main_recorre_la_rejilla_y_escribe_el_anexo(tmp_path, monkeypatch, capsys):
    """La rejilla se reduce a una casilla: lo que se mide aquí es el recorrido."""
    monkeypatch.setattr(rejilla, "MAXIMOS", (900,))
    monkeypatch.setattr(rejilla, "RATIOS_OBJETIVO", (1.0,))
    monkeypatch.setattr(rejilla, "RATIOS_SOLAPE", (0.0,))
    monkeypatch.setattr(rejilla, "PERCENTILES", (50,))
    monkeypatch.setattr(
        rejilla, "_cargar_entradas", lambda: (MUESTRA, [_pregunta(("guia", "U"))])
    )
    monkeypatch.setattr(
        rejilla,
        "_cargar_modelo",
        lambda: (
            incrustador_determinista,
            incrustador_determinista,
            lambda ts: [1] * len(ts),
            512,
        ),
    )
    agregados = {"mrr": 0.9}
    for k in rejilla.KS:
        agregados[f"recall@{k}"] = 0.5
        agregados[f"recall_unidad@{k}"] = 0.8
    monkeypatch.setattr(
        rejilla, "evaluar_modelo", lambda *a, **kw: {"agregados": agregados}
    )
    escritos = []
    monkeypatch.setattr(
        rejilla, "_escribir_informe", lambda filas, n, v: escritos.append(len(filas))
    )

    assert rejilla.main() == 0

    salida = capsys.readouterr().out
    assert "Rejilla: 3 configuraciones" in salida
    assert escritos == [3]

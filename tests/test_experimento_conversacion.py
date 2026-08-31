"""Pruebas del experimento que compara los mecanismos de ámbito (IT-113).

Es el experimento de IT-106: compara tres formas de convertir una pregunta de
seguimiento en algo que se pueda buscar, y es la evidencia de que el arrastre
de IT-37 no basta. No tenía ninguna prueba.

**Ninguna abre el índice ni incrusta nada.** Lo que se comprueba es que las
conversaciones se derivan bien del dataset ---no están escritas a mano, y esa
es la mitad del argumento del experimento--- y que las tres estrategias hacen
lo que dicen hacer.

El catálogo de las fixtures es el real, de doce titulaciones: con uno corto
``palabras_distintivas`` no devuelve nada, ninguna estrategia deduce sujeto y
las pruebas pasarían midiendo un sistema que no existe.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "experimentos"))

import experimento_conversacion as conversacion  # noqa: E402

CATALOGO = [
    "Doble Grado en Ingeniería Electrónica Industrial y Mecánica",
    "Doble Grado en Ingeniería Eléctrica y Electrónica Industrial",
    "Doble Grado en Ingeniería Eléctrica y Mecánica",
    "Doble Grado en Ingeniería Mecánica y Organización Industrial",
    "Grado en Ingeniería Electrónica Industrial",
    "Grado en Ingeniería Eléctrica",
    "Grado en Ingeniería Geomática y Topográfica (plan 2025)",
    "Grado en Ingeniería Informática",
    "Grado en Ingeniería Mecánica",
    "Grado en Ingeniería de Organización Industrial",
    "Grado en Inteligencia Artificial y Ciberseguridad",
]
INFORMATICA = "Grado en Ingeniería Informática"
MECANICA = "Grado en Ingeniería Mecánica"


def _asignatura(grado=INFORMATICA, curso="Primer curso", tipo="OB", nombre="Cálculo"):
    """Un item ``asignatura`` con lo que el experimento le mira."""
    return {
        "tipo": "asignatura",
        "grado": grado,
        "curso": curso,
        "tipo_asignatura": tipo,
        "nombre": nombre,
    }


def _datos_con_cursos(grados, cursos):
    """Dataset con una asignatura obligatoria por cada par (grado, curso)."""
    return [
        _asignatura(grado=g, curso=c, nombre=f"{g} {c}") for g in grados for c in cursos
    ]


class _Fragmento:
    """Lo único que el experimento le pide a un fragmento recuperado."""

    def __init__(self, nombre):
        self.nombre = nombre


# --- Cómo se nombra cada cosa -----------------------------------------------


def test_la_unidad_esperada_es_el_encabezado_del_plan():
    """Si no coincide con el del corpus, el experimento mide siempre cero."""
    assert conversacion._unidad(INFORMATICA, "Primer curso") == (
        f"Asignaturas obligatorias de primer curso del {INFORMATICA}"
    )


def test_el_nombre_corto_identifica_a_una_sola_titulacion():
    assert conversacion._nombre_corto(INFORMATICA, CATALOGO) == "informatica"


def test_una_titulacion_sin_palabra_propia_no_tiene_nombre_corto():
    """«electrónica» sitúa en tres: la conversación derivada sería ambigua."""
    assert conversacion._nombre_corto(CATALOGO[0], CATALOGO) is None


# --- Los pares (titulación, curso) que existen ------------------------------


def test_solo_se_cuentan_las_no_optativas():
    """La EPSJ publica su bloque de optativas sin curso: no forman un par."""
    datos = [_asignatura(), _asignatura(tipo="OP", nombre="Otra")]

    por_curso = conversacion._asignaturas_por_curso(datos)

    assert por_curso == {(INFORMATICA, "Primer curso"): 1}


def test_una_asignatura_sin_curso_no_forma_par():
    por_curso = conversacion._asignaturas_por_curso([_asignatura(curso="")])

    assert por_curso == {}


def test_lo_que_no_es_una_asignatura_se_ignora():
    datos = [{"tipo": "grado", "nombre": INFORMATICA}, _asignatura()]

    assert len(conversacion._asignaturas_por_curso(datos)) == 1


# --- Las tres familias de conversaciones ------------------------------------


def test_el_sujeto_puede_venir_solo_de_la_respuesta():
    """Es el caso que ninguna heurística sobre la pregunta puede resolver."""
    datos = _datos_con_cursos([INFORMATICA], ["Primer curso"])

    casos = conversacion.construir_conversaciones(datos, CATALOGO)

    familia = [c for c in casos if c["familia"] == "sujeto_en_la_respuesta"]
    assert len(familia) == 1
    assert INFORMATICA in familia[0]["turnos"][0][1]
    assert INFORMATICA not in familia[0]["pregunta"]


def test_el_cambio_de_curso_solo_se_deriva_si_los_dos_existen():
    """Una conversación sobre un curso que la fuente no publica no mide nada."""
    datos = _datos_con_cursos([INFORMATICA], ["Primer curso", "Segundo curso"])

    casos = conversacion.construir_conversaciones(datos, CATALOGO)

    familia = [c for c in casos if c["familia"] == "cambia_el_curso"]
    assert len(familia) == 1
    assert familia[0]["pregunta"] == "¿Y en segundo?"
    assert familia[0]["esperado"].endswith(f"segundo curso del {INFORMATICA}")


def test_sin_el_curso_de_destino_no_hay_conversacion_de_cambio():
    datos = _datos_con_cursos([INFORMATICA], ["Primer curso"])

    casos = conversacion.construir_conversaciones(datos, CATALOGO)

    assert not [c for c in casos if c["familia"] == "cambia_el_curso"]


def test_el_cambio_de_titulacion_encadena_una_con_la_siguiente():
    datos = _datos_con_cursos([INFORMATICA, MECANICA], ["Primer curso"])

    casos = conversacion.construir_conversaciones(datos, CATALOGO)

    familia = [c for c in casos if c["familia"] == "cambia_la_titulacion"]
    assert familia
    for caso in familia:
        assert caso["pregunta"].startswith("¿Y en ")


def test_una_titulacion_sin_nombre_corto_no_genera_conversacion():
    """Sin palabra propia, la pregunta de seguimiento sería ambigua."""
    datos = _datos_con_cursos([CATALOGO[0], CATALOGO[1]], ["Primer curso"])

    casos = conversacion.construir_conversaciones(datos, CATALOGO)

    assert not [c for c in casos if c["familia"] == "cambia_la_titulacion"]


def test_una_titulacion_que_no_esta_en_el_indice_no_entra():
    datos = _datos_con_cursos(["Grado en Medicina"], ["Primer curso"])

    assert conversacion.construir_conversaciones(datos, CATALOGO) == []


# --- Las tres estrategias ---------------------------------------------------


TURNOS = [(f"¿Qué se estudia en el {INFORMATICA}?", "Pues esto.")]


def test_la_estrategia_sola_no_mira_la_conversacion():
    """Es el estado en que nació el chat."""
    texto, ambito = conversacion._sola("¿Y en segundo?", TURNOS, CATALOGO)

    assert texto == "¿Y en segundo?"
    assert ambito == []


def test_la_concatenada_pega_delante_la_ultima_titulacion_nombrada():
    """Es el mecanismo de IT-37, la línea base a batir."""
    texto, ambito = conversacion._concatenada("¿Y en segundo?", TURNOS, CATALOGO)

    assert texto.startswith(TURNOS[0][0])
    assert texto.endswith("¿Y en segundo?")
    assert ambito == []


def test_la_concatenada_no_toca_una_pregunta_que_ya_nombra_su_titulacion():
    pregunta = f"¿Qué se estudia en el {MECANICA}?"

    texto, _ = conversacion._concatenada(pregunta, TURNOS, CATALOGO)

    assert texto == pregunta


def test_la_concatenada_sin_sujeto_anterior_deja_la_pregunta_igual():
    texto, _ = conversacion._concatenada("¿Y en segundo?", [], CATALOGO)

    assert texto == "¿Y en segundo?"


def test_la_conversacion_deduce_el_sujeto_de_la_respuesta():
    """Es el defecto 1 de IT-106: la titulación aparece solo en la respuesta."""
    turnos = [("Estoy en bachillerato", f"Podrías mirar el {INFORMATICA}.")]

    _texto, ambito = conversacion._conversacion("¿Y en primero?", turnos, CATALOGO)

    assert ambito == [INFORMATICA]


def test_las_tres_estrategias_estan_declaradas():
    assert set(conversacion.ESTRATEGIAS) == {"sola", "concatenada", "conversacion"}


# --- La medida --------------------------------------------------------------


def test_la_posicion_se_cuenta_desde_uno():
    """Contar desde cero es de dentro; el MRR se calcula sobre el puesto."""
    assert conversacion._posicion(["a", "b", "c"], "b") == 2


def test_si_la_unidad_no_aparece_no_hay_posicion():
    assert conversacion._posicion(["a"], "z") is None


def _medir(monkeypatch, nombres_traidos, casos):
    """Mide una estrategia con una recuperación de mentira."""
    monkeypatch.setattr(
        conversacion,
        "recuperar",
        lambda *a, **kw: [_Fragmento(n) for n in nombres_traidos],
    )
    coste: list[float] = []
    aciertos = conversacion._medir_estrategia(
        conversacion._sola, casos, None, None, "cosine", CATALOGO, 10, coste
    )
    return aciertos, coste


def test_medir_apunta_acierto_y_mrr_cuando_la_unidad_aparece(monkeypatch):
    casos = [{"familia": "f", "turnos": [], "pregunta": "p", "esperado": "U"}]

    aciertos, coste = _medir(monkeypatch, ["otra", "U"], casos)

    assert aciertos["f"] == [1.0]
    assert aciertos["f:mrr"] == [0.5]
    assert len(coste) == 1


def test_medir_apunta_cero_cuando_no_aparece(monkeypatch):
    casos = [{"familia": "f", "turnos": [], "pregunta": "p", "esperado": "U"}]

    aciertos, _ = _medir(monkeypatch, ["otra"], casos)

    assert aciertos["f"] == [0.0]
    assert aciertos["f:mrr"] == [0.0]


# --- Lo que se imprime ------------------------------------------------------


def test_el_reparto_dice_cuantas_salieron_de_cada_familia(capsys):
    casos = [{"familia": "a"}, {"familia": "a"}, {"familia": "b"}]

    reparto = conversacion._imprimir_reparto(casos)

    salida = capsys.readouterr().out
    assert reparto == {"a": 2, "b": 1}
    assert "Conversaciones derivadas del dataset: 3" in salida


def test_las_filas_llevan_la_media_de_cada_familia_y_el_total(capsys):
    resultados = {
        nombre: {"a": [1.0, 0.0], "a:mrr": [1.0, 0.0]}
        for nombre in conversacion.ESTRATEGIAS
    }

    conversacion._imprimir_filas(resultados, ["a"])

    salida = capsys.readouterr().out
    assert salida.count("0.500") == 6  # media de familia y total, por estrategia


# --- El recorrido entero ----------------------------------------------------


def test_main_compara_las_tres_estrategias(tmp_path, monkeypatch, capsys):
    dataset = tmp_path / "grados.json"
    dataset.write_text(
        json.dumps(_datos_con_cursos([INFORMATICA], ["Primer curso", "Segundo curso"])),
        encoding="utf-8",
    )
    monkeypatch.setattr(conversacion, "catalogo_del_indice", lambda ruta: CATALOGO)
    monkeypatch.setattr(conversacion, "incrustador_de_consultas", lambda modelo: None)
    monkeypatch.setattr(conversacion, "abrir_indice", lambda ruta, modelo: None)
    monkeypatch.setattr(conversacion, "distancia_del_indice", lambda ruta: "cosine")
    monkeypatch.setattr(
        conversacion, "recuperar", lambda *a, **kw: [_Fragmento("nada")]
    )

    conversacion.main(
        ["--indice", str(tmp_path), "--dataset", str(dataset), "--k", "5"]
    )

    salida = capsys.readouterr().out
    for nombre in conversacion.ESTRATEGIAS:
        assert nombre in salida
    assert "MRR de la unidad esperada" in salida
    assert "Coste de preparar la consulta" in salida


@pytest.mark.parametrize("familia", ["sujeto_en_la_respuesta", "cambia_el_curso"])
def test_main_informa_de_cada_familia_derivada(tmp_path, monkeypatch, capsys, familia):
    dataset = tmp_path / "grados.json"
    dataset.write_text(
        json.dumps(_datos_con_cursos([INFORMATICA], ["Primer curso", "Segundo curso"])),
        encoding="utf-8",
    )
    monkeypatch.setattr(conversacion, "catalogo_del_indice", lambda ruta: CATALOGO)
    monkeypatch.setattr(conversacion, "incrustador_de_consultas", lambda modelo: None)
    monkeypatch.setattr(conversacion, "abrir_indice", lambda ruta, modelo: None)
    monkeypatch.setattr(conversacion, "distancia_del_indice", lambda ruta: "cosine")
    monkeypatch.setattr(conversacion, "recuperar", lambda *a, **kw: [])

    conversacion.main(["--indice", str(tmp_path), "--dataset", str(dataset)])

    assert familia[:18] in capsys.readouterr().out


def test_si_la_titulacion_anterior_no_tiene_primero_no_hay_encadenado():
    """La conversación necesita las dos: la de la que se viene y la de la que se va.

    Pasa con el doble grado internacional, que está en el catálogo y no aporta
    asignaturas: encadenar desde él dejaría un primer turno sin unidad.
    """
    datos = _datos_con_cursos([INFORMATICA], ["Primer curso"])
    datos += [_asignatura(grado=MECANICA, curso="Segundo curso", nombre="Otra")]

    casos = conversacion.construir_conversaciones(datos, CATALOGO)

    encadenados = [c for c in casos if c["familia"] == "cambia_la_titulacion"]
    assert not [c for c in encadenados if MECANICA in c["turnos"][0][0]]

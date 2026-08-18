"""Pruebas del guion que criba modelos generativos (IT-35).

Ninguna llama a un modelo: se comprueba el **instrumento**, que es lo que ha
fallado dos veces en dos días y las dos con cifras verosímiles. Un cribado que
mide mal no avisa de nada, simplemente elige el candidato equivocado.

Los registros son copias literales de ``data/grados.json`` y de las respuestas
que dieron los candidatos el 18/08/2026.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "experimento_generacion", RAIZ / "scripts" / "experimento_generacion.py"
)
assert _spec is not None and _spec.loader is not None
experimento = importlib.util.module_from_spec(_spec)
sys.modules["experimento_generacion"] = experimento
_spec.loader.exec_module(experimento)


# --- Registros reales de data/grados.json ---

_CON_MENCION = {
    "tipo": "asignatura",
    "grado": "Grado en Ingeniería Electrónica Industrial",
    "codigo": "13113013",
    "nombre": "Sistemas Digitales",
    "tipo_asignatura": "OP",
    "menciones": ["Sistemas electrónicos"],
    "ects": "6",
}

_COMUN = {
    "tipo": "asignatura",
    "grado": "Grado en Ingeniería Mecánica",
    "codigo": "13413012",
    "nombre": "Prácticas externas",
    "tipo_asignatura": "OP",
    "menciones": ["Común a todas las menciones"],
    "ects": "6",
}

_SIN_MENCION = {
    "tipo": "asignatura",
    "grado": "Grado en Ingeniería Informática",
    "codigo": "13312001",
    "nombre": "Fundamentos de la programación",
    "tipo_asignatura": "FB",
    "menciones": [],
    "ects": "6",
}

_DATOS = [{"tipo": "grado", "nombre": "Grado en Ingeniería Informática"}] + [
    _CON_MENCION,
    _COMUN,
    _SIN_MENCION,
]

CATALOGO = ["Grado en Ingeniería Informática", "Grado en Ingeniería Mecánica"]


# --- De dónde salen los nombres válidos ---


def test_los_nombres_de_asignatura_salen_del_dataset():
    assert experimento.asignaturas_del_corpus(_DATOS) == {
        "Sistemas Digitales",
        "Prácticas externas",
        "Fundamentos de la programación",
    }


def test_comun_a_todas_las_menciones_no_es_una_mencion():
    """Es un rótulo de la fuente, no un itinerario."""
    assert experimento.menciones_del_corpus(_DATOS) == {"Sistemas electrónicos"}


# --- Contra qué se comprueba cada familia (regresión del 18/08/2026) ---

_PREGUNTA_MENCIONES = {
    "familia": "menciones",
    "respuesta": "conjunto",
    "esperado": ["Automática", "Sistemas electrónicos"],
    "ambito": {"grado": "Grado en Ingeniería Electrónica Industrial"},
}

_PREGUNTA_ASIGNATURAS_DE_MENCION = {
    "familia": "menciones",
    "respuesta": "conjunto",
    "esperado": ["Robótica industrial"],
    "ambito": {
        "grado": "Grado en Ingeniería Electrónica Industrial",
        "mencion": "Automática",
    },
}

_PREGUNTA_CATALOGO = {
    "familia": "catalogo",
    "respuesta": "conjunto",
    "esperado": CATALOGO,
    "ambito": {},
}


def test_el_catalogo_se_comprueba_contra_las_titulaciones():
    assert experimento.universo(_PREGUNTA_CATALOGO, CATALOGO, set(), set()) == set(
        CATALOGO
    )


def test_preguntar_por_las_menciones_se_comprueba_contra_las_menciones():
    """Regresión.

    Comprobándolas contra los nombres de asignatura, los tres candidatos daban
    precisión 0,59-0,62 por enumerar bien lo que se les pedía. Que los tres
    coincidieran era la señal de que fallaba el instrumento.
    """
    assert experimento.universo(
        _PREGUNTA_MENCIONES, CATALOGO, {"Álgebra"}, {"Automática"}
    ) == {"Automática"}


def test_preguntar_por_las_asignaturas_de_una_mencion_no():
    """La misma familia, pero el ámbito trae la mención: se piden asignaturas."""
    assert experimento.universo(
        _PREGUNTA_ASIGNATURAS_DE_MENCION, CATALOGO, {"Álgebra"}, {"Automática"}
    ) == {"Álgebra"}


# --- Las respuestas de valor único ---


def test_los_creditos_solo_cuentan_con_su_unidad_detras():
    """Sin la unidad, cualquier «6» suelto del texto contaría como acierto."""
    acierta, dicho = experimento.acierto_escalar(
        "La asignatura tiene 6 ECTS.", "6", "creditos"
    )
    assert acierta
    assert dicho == "6"


def test_un_seis_suelto_no_es_una_respuesta_de_creditos():
    acierta, dicho = experimento.acierto_escalar(
        "Se imparte en el grupo 6 del segundo cuatrimestre.", "6", "creditos"
    )
    assert not acierta
    assert dicho == ""


def test_decir_otra_cifra_de_creditos_es_fallar():
    acierta, dicho = experimento.acierto_escalar("Tiene 9 créditos.", "6", "creditos")
    assert not acierta
    assert dicho == "9"


def test_el_curso_se_busca_sin_la_palabra_curso():
    """El rótulo de la fuente es «Tercer o cuarto curso» y el modelo la omite."""
    acierta, _ = experimento.acierto_escalar(
        "Se imparte en tercer o cuarto, según el itinerario.",
        "Tercer o cuarto curso",
        "curso_de_asignatura",
    )
    assert acierta


def test_decir_otro_curso_es_fallar():
    acierta, _ = experimento.acierto_escalar(
        "Se imparte en primero.", "Tercer o cuarto curso", "curso_de_asignatura"
    )
    assert not acierta


# --- La medición completa de una respuesta ---


def test_una_respuesta_escalar_no_calcula_precision():
    medido = experimento.medir(
        "Tiene 6 ECTS.",
        {
            "familia": "creditos",
            "respuesta": "escalar",
            "esperado": ["6"],
            "ambito": {},
        },
        CATALOGO,
        set(),
        set(),
    )
    assert medido["acierto"]
    assert "precision" not in medido


def test_una_titulacion_inventada_se_registra_en_cualquier_familia():
    medido = experimento.medir(
        "Te recomiendo el Grado en Ingeniería Biomédica.",
        {
            "familia": "creditos",
            "respuesta": "escalar",
            "esperado": ["6"],
            "ambito": {},
        },
        CATALOGO,
        set(),
        set(),
    )
    assert medido["titulaciones_inventadas"] == ["Grado en Ingeniería Biomédica"]


# --- Repuntuar sin volver a pagar la inferencia ---


def test_recalcular_no_necesita_ningun_modelo_y_corrige_las_cifras():
    """El caso exacto que motivó el modo: la familia de menciones.

    La fila guardada trae la precisión que salía con el universo equivocado;
    repuntuada con el bueno, la respuesta ---que es correcta--- sube a 1,0.
    """
    fila = {
        "modelo": "gemma3:12b",
        "id": "G-MEN-001",
        "familia": "menciones",
        "pregunta": "¿En qué menciones se puede especializar?",
        "respuesta": "- Automática\n- Sistemas electrónicos\n",
        "fragmentos": 4,
        "segundos_recuperar": 0.04,
        "segundos_generar": 12.0,
        "precision": 0.0,
        "cobertura": 1.0,
        "inventadas": ["automatica", "sistemas electronicos"],
        "omitidas": 0,
        "esperadas": 2,
        "titulaciones_inventadas": [],
    }
    nuevas = experimento.recalcular(
        [fila],
        {"G-MEN-001": _PREGUNTA_MENCIONES},
        CATALOGO,
        {"Álgebra"},
        {"Automática", "Sistemas electrónicos"},
    )
    assert nuevas[0]["precision"] == 1.0
    assert nuevas[0]["inventadas"] == []
    # Lo que no es una cifra se conserva tal cual: la respuesta es el dato caro.
    assert nuevas[0]["respuesta"] == fila["respuesta"]
    assert nuevas[0]["segundos_generar"] == 12.0


# --- El registro y el informe ---


def test_no_se_vuelve_a_pagar_una_respuesta_ya_medida(tmp_path):
    registro = tmp_path / "r.jsonl"
    registro.write_text(
        json.dumps({"modelo": "m", "id": "G-1"}) + "\n", encoding="utf-8"
    )
    assert experimento.ya_medido(registro) == {("m", "G-1")}


def test_un_registro_que_no_existe_no_tiene_nada_medido(tmp_path):
    assert experimento.ya_medido(tmp_path / "no-esta.jsonl") == set()


_FILAS = [
    {
        "modelo": "m",
        "id": "G-1",
        "familia": "menciones",
        "respuesta": "- Automática",
        "fragmentos": 3,
        "segundos_generar": 10.0,
        "segundos_recuperar": 0.0,
        "precision": 1.0,
        "cobertura": 1.0,
        "inventadas": [],
        "omitidas": 0,
        "esperadas": 1,
        "titulaciones_inventadas": [],
    },
    {
        "modelo": "m",
        "id": "G-2",
        "familia": "creditos",
        "respuesta": "6 ECTS",
        "fragmentos": 0,
        "segundos_generar": 0.0,
        "segundos_recuperar": 0.0,
        "acierto": True,
        "dicho": "6",
        "titulaciones_inventadas": ["Grado en Ingeniería Biomédica"],
    },
]


def test_el_resumen_separa_listados_de_escalares():
    resumen = experimento.resumir(_FILAS)["m"]
    assert resumen["listados"] == 1
    assert resumen["escalares"] == 1
    assert resumen["titulaciones_inventadas"] == 1
    assert resumen["nombres_inventados"] == ["Grado en Ingeniería Biomédica"]


def test_una_pregunta_sin_contexto_no_entra_en_los_tiempos():
    """Cero segundos no es una respuesta rápida: es una respuesta que no hubo."""
    resumen = experimento.resumir(_FILAS)["m"]
    assert resumen["sin_contexto"] == 1
    assert resumen["mediana_s"] == 10.0


def test_el_desglose_marca_que_familia_es_de_listado():
    familias = experimento.por_familia(_FILAS)["m"]
    assert familias["menciones"]["es_listado"]
    assert not familias["creditos"]["es_listado"]


def test_el_informe_se_escribe_entero(tmp_path):
    destino = tmp_path / "informe.md"
    experimento.informe(
        _FILAS, {"procedencia_del_dataset": {"fecha": "2026-08-16"}}, destino
    )
    texto = destino.read_text(encoding="utf-8")
    assert "Cribado de modelos generativos" in texto
    assert "Grado en Ingeniería Biomédica" in texto
    assert "fecha: 2026-08-16" in texto


# --- La versión del servidor de inferencia ---


def test_el_informe_avisa_si_se_mezclaron_dos_servidores(tmp_path):
    """Regresión del 19/08/2026.

    El servidor de inferencia se actualizó solo de la 0.23.2 a la 0.32.14 en
    mitad del cribado. Una diferencia entre candidatos medidos con versiones
    distintas puede venir del tiempo de ejecución y no del modelo, así que la
    tabla no compara nada y el informe tiene que decirlo.
    """
    mezcladas = [
        {**_FILAS[0], "modelo": "a", "servidor": "0.23.2"},
        {**_FILAS[0], "modelo": "b", "servidor": "0.32.14"},
    ]
    destino = tmp_path / "informe.md"
    experimento.informe(mezcladas, {}, destino)
    texto = destino.read_text(encoding="utf-8")
    assert "0.23.2 · 0.32.14" in texto
    assert "NO se midieron todas con el mismo servidor" in texto


def test_un_solo_servidor_no_dispara_el_aviso(tmp_path):
    iguales = [{**f, "servidor": "0.32.14"} for f in _FILAS]
    destino = tmp_path / "informe.md"
    experimento.informe(iguales, {}, destino)
    texto = destino.read_text(encoding="utf-8")
    assert "Servidor de inferencia: 0.32.14" in texto
    assert "NO se midieron todas" not in texto


def test_las_respuestas_viejas_sin_version_se_marcan_como_tales(tmp_path):
    """Las 240 primeras se midieron antes de anotar la versión."""
    destino = tmp_path / "informe.md"
    experimento.informe(_FILAS, {}, destino)
    assert "sin anotar" in destino.read_text(encoding="utf-8")

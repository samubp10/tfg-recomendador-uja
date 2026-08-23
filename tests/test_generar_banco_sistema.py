"""Pruebas del generador del banco de evaluación del sistema (IT-37, IT-39).

El fichero no tenía ninguna prueba y las preguntas ajenas dejaron de estar
escritas a mano en IT-39: ahora la mitad larga se lee del conjunto de validación
versionado. Eso convierte al guion en algo que puede romperse en silencio ---si
el fichero cambia de forma, el banco se queda corto y nadie se entera hasta leer
un informe con menos entradas---, así que se cubre entero.

Las preguntas factuales de las que se muestrea están **copiadas de
``eval/preguntas_generacion.json``**, con su forma real: la familia va en el
mismo campo y el identificador conserva su prefijo.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "generar_banco_sistema", RAIZ / "scripts" / "generar_banco_sistema.py"
)
assert _spec is not None and _spec.loader is not None
generar_banco_sistema = importlib.util.module_from_spec(_spec)
sys.modules["generar_banco_sistema"] = generar_banco_sistema
_spec.loader.exec_module(generar_banco_sistema)


# --- Dobles de los ficheros de entrada ---


def _banco_factual() -> dict[str, Any]:
    """Banco derivado del dataset, con tres familias de tamaños distintos.

    La familia ``catalogo`` va con una sola pregunta a propósito: es el caso que
    obliga al sorteo a pedir menos de las que se le piden por familia.
    """
    preguntas = [
        {
            "id": f"G-CRE-{i:03d}",
            "familia": "creditos",
            "pregunta": f"¿Cuántos créditos tiene la asignatura {i}?",
            "respuesta": "escalar",
            "esperado": [6],
        }
        for i in range(1, 7)
    ]
    preguntas += [
        {
            "id": f"G-OPT-{i:03d}",
            "familia": "optativas",
            "pregunta": f"¿Qué optativas tiene la titulación {i}?",
            "respuesta": "conjunto",
            "esperado": ["Una optativa"],
        }
        for i in range(1, 4)
    ]
    preguntas.append(
        {
            "id": "G-CAT-001",
            "familia": "catalogo",
            "pregunta": "¿Qué titulaciones se pueden estudiar en la Escuela?",
            "respuesta": "conjunto",
            "esperado": ["Grado en Ingeniería Informática"],
        }
    )
    return {"descripcion": "doble del banco derivado", "preguntas": preguntas}


def _validacion_ajenas() -> dict[str, Any]:
    """Conjunto de validación del rechazo, con la forma real del versionado."""
    return {
        "descripcion": "doble del conjunto de validación",
        "preguntas": [
            {
                "id": "V-001",
                "tipo": "fuera_de_dominio",
                "clase": "otra_rama_de_la_uja",
                "pregunta": "¿Se puede estudiar Enfermería aquí?",
                "relevantes": [],
            },
            {
                "id": "V-002",
                "tipo": "fuera_de_dominio",
                "clase": "otro_centro",
                "pregunta": "¿Qué se estudia en la Escuela Politécnica Superior "
                "de Linares?",
                "relevantes": [],
            },
        ],
    }


@pytest.fixture
def ruta_factual(tmp_path: Path) -> Path:
    """Escribe el doble del banco derivado y devuelve su ruta."""
    ruta = tmp_path / "preguntas_generacion.json"
    ruta.write_text(json.dumps(_banco_factual(), ensure_ascii=False), encoding="utf-8")
    return ruta


@pytest.fixture
def ruta_validacion(tmp_path: Path) -> Path:
    """Escribe el doble del conjunto de validación y devuelve su ruta."""
    ruta = tmp_path / "validacion.json"
    ruta.write_text(
        json.dumps(_validacion_ajenas(), ensure_ascii=False), encoding="utf-8"
    )
    return ruta


# --- El sorteo de las factuales ---


def test_factuales_toma_las_pedidas_de_cada_familia(ruta_factual: Path) -> None:
    """De cada familia salen las que se piden, y de la corta salen las que hay."""
    elegidas = generar_banco_sistema.factuales(ruta_factual, 2, 20)

    por_familia: dict[str, int] = {}
    for pregunta in elegidas:
        por_familia[pregunta["familia"]] = por_familia.get(pregunta["familia"], 0) + 1

    assert por_familia == {"catalogo": 1, "creditos": 2, "optativas": 2}


def test_factuales_es_reproducible_con_la_misma_semilla(ruta_factual: Path) -> None:
    """La misma semilla da el mismo sorteo, que es lo que exige el RNF-05."""
    primera = generar_banco_sistema.factuales(ruta_factual, 3, 20)
    segunda = generar_banco_sistema.factuales(ruta_factual, 3, 20)

    assert [p["id"] for p in primera] == [p["id"] for p in segunda]


def test_factuales_cambia_de_muestra_al_cambiar_la_semilla(ruta_factual: Path) -> None:
    """Semillas distintas sortean cosas distintas; si no, la semilla no sortea."""
    con_veinte = [p["id"] for p in generar_banco_sistema.factuales(ruta_factual, 3, 20)]
    con_uno = [p["id"] for p in generar_banco_sistema.factuales(ruta_factual, 3, 1)]

    assert con_veinte != con_uno


# --- Las familias escritas a mano ---


@pytest.mark.parametrize(
    ("funcion", "familia", "cuantas"),
    [
        ("conversaciones", "conversacion", 8),
        ("consejos", "consejo", 6),
        ("cortesias", "cortesia", 4),
        ("ambiguas", "ambigua", 3),
    ],
)
def test_las_familias_a_mano_declaran_su_familia(
    funcion: str, familia: str, cuantas: int
) -> None:
    """Cada entrada escrita a mano lleva la familia que le toca y su tamaño."""
    entradas = getattr(generar_banco_sistema, funcion)()

    assert len(entradas) == cuantas
    assert {e["familia"] for e in entradas} == {familia}


def test_las_conversaciones_llevan_turnos_y_las_demas_pregunta() -> None:
    """El corrector distingue una conversación por que trae ``turnos``."""
    assert all("turnos" in c for c in generar_banco_sistema.conversaciones())
    assert all("pregunta" in c for c in generar_banco_sistema.consejos())


# --- Las ajenas, que es lo que cambia en IT-39 ---


def test_ajenas_suma_las_del_guion_y_las_del_conjunto_de_validacion(
    ruta_validacion: Path,
) -> None:
    """Las cinco evidentes siguen estando y detrás van las del fichero."""
    entradas = generar_banco_sistema.ajenas(ruta_validacion)

    assert len(entradas) == 7
    assert [e["origen"] for e in entradas] == [
        "escrita_en_el_guion",
        "escrita_en_el_guion",
        "escrita_en_el_guion",
        "escrita_en_el_guion",
        "escrita_en_el_guion",
        "conjunto_de_validacion:V-001",
        "conjunto_de_validacion:V-002",
    ]


def test_ajenas_no_reescribe_el_texto_de_la_pregunta(ruta_validacion: Path) -> None:
    """La pregunta viaja literal: si se retocara, dejaría de ser la validada."""
    entradas = generar_banco_sistema.ajenas(ruta_validacion)

    assert entradas[5]["pregunta"] == "¿Se puede estudiar Enfermería aquí?"


def test_ajenas_numera_sin_repetir_identificador(ruta_validacion: Path) -> None:
    """Dos entradas con el mismo identificador se pisarían al recorregir."""
    entradas = generar_banco_sistema.ajenas(ruta_validacion)

    assert [e["id"] for e in entradas] == [
        f"S-AJE-{i:03d}" for i in range(1, len(entradas) + 1)
    ]


def test_ajenas_espera_rechazo_y_nada_mas(ruta_validacion: Path) -> None:
    """Todas se corrigen igual: el acierto es no nombrar ninguna titulación."""
    entradas = generar_banco_sistema.ajenas(ruta_validacion)

    assert {e["respuesta"] for e in entradas} == {"rechazo"}
    assert all(e["esperado"] == [] for e in entradas)


def test_ajenas_lee_el_conjunto_versionado_cuando_no_se_le_da_ruta() -> None:
    """Sin argumento tira del fichero de ``eval/``, que es el caso real.

    Es la prueba que se rompe si alguien mueve o renombra el conjunto de
    validación, que es justo el fallo que dejaría el banco corto en silencio.
    """
    entradas = generar_banco_sistema.ajenas()

    versionado = json.loads(
        (RAIZ / "eval" / generar_banco_sistema.VALIDACION_AJENAS).read_text(
            encoding="utf-8"
        )
    )["preguntas"]

    assert len(entradas) == 5 + len(versionado)
    assert [e["pregunta"] for e in entradas[5:]] == [p["pregunta"] for p in versionado]


# --- El banco entero ---


def test_construir_junta_todas_las_familias(ruta_factual: Path) -> None:
    """El banco trae las factuales sorteadas y las cinco familias a mano."""
    banco = generar_banco_sistema.construir(ruta_factual, 2, 20)

    assert {p["familia"] for p in banco} == {
        "catalogo",
        "creditos",
        "optativas",
        "conversacion",
        "consejo",
        "cortesia",
        "fuera_de_dominio",
        "ambigua",
    }


def test_construir_no_repite_ningun_identificador(ruta_factual: Path) -> None:
    """Un identificador repetido rompe el recorregido, que indexa por él."""
    banco = generar_banco_sistema.construir(ruta_factual, 2, 20)

    identificadores = [p["id"] for p in banco]
    assert len(set(identificadores)) == len(identificadores)


def test_llamadas_cuenta_un_turno_por_mensaje(ruta_factual: Path) -> None:
    """Una conversación de tres turnos cuesta tres llamadas, no una."""
    banco = generar_banco_sistema.construir(ruta_factual, 2, 20)

    sueltas = sum(1 for p in banco if "turnos" not in p)
    de_conversacion = sum(len(p["turnos"]) for p in banco if "turnos" in p)
    assert generar_banco_sistema.llamadas(banco) == sueltas + de_conversacion


# --- El punto de entrada ---


def test_main_escribe_el_banco_y_lo_deja_legible(
    ruta_factual: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Escribe el fichero, y el resumen que imprime cuadra con lo escrito."""
    salida = tmp_path / "preguntas_sistema.json"
    generar_banco_sistema.main(
        [
            "--banco",
            str(ruta_factual),
            "--salida",
            str(salida),
            "--por-familia",
            "2",
            "--semilla",
            "20",
        ]
    )

    documento = json.loads(salida.read_text(encoding="utf-8"))
    assert documento["descripcion"]
    assert len(documento["preguntas"]) == int(
        capsys.readouterr().out.split("entradas:")[1].split()[0]
    )

"""Pruebas de la comparación pareada de dos modelos (IT-133).

Ninguna llama a un modelo: el guion no lo hace tampoco, solo lee el registro
que dejó la tanda. Eso es lo que permite probar la estadística con casos
construidos, que es donde se puede comprobar que da el número correcto.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_RUTA = RAIZ / "scripts" / "experimentos" / "comparar_dos_modelos.py"
_spec = importlib.util.spec_from_file_location("comparar_dos_modelos", _RUTA)
assert _spec is not None and _spec.loader is not None
comparar_dos_modelos = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(comparar_dos_modelos)

A = "qwen3.5:9b"
B = "gemma3:12b"


def _fila(
    identificador: str,
    modelo: str,
    precision: float | None = 1.0,
    cobertura: float | None = 1.0,
    segundos: float = 10.0,
) -> dict[str, Any]:
    return {
        "id": identificador,
        "modelo": modelo,
        "familia": "creditos",
        "precision": precision,
        "cobertura": cobertura,
        "segundos_generar": segundos,
    }


# --- Intervalo de Wilson ----------------------------------------------------


def test_wilson_no_se_sale_del_intervalo_unidad_con_una_tasa_de_uno() -> None:
    """Es la razón de usar Wilson y no el intervalo normal.

    Este banco produce tasas pegadas a 1, y ahí el normal da cotas por encima
    de 1 o de anchura cero: sugiere una certeza que no hay.
    """
    bajo, alto = comparar_dos_modelos.wilson(34, 34)

    # `approx` y no `== 1.0` por la coma flotante: la cota exacta con p = 1 es
    # 1, y el cálculo la deja en 0,9999999999999999. No se fuerza a 1 en la
    # función para no tapar con un redondeo un caso en que de verdad se pasara.
    assert alto == pytest.approx(1.0)
    assert 0.8 < bajo < 1.0


def test_wilson_se_estrecha_al_crecer_la_muestra() -> None:
    """Lo que estrecha el intervalo son más preguntas, no más tiradas."""
    estrecho = comparar_dos_modelos.wilson(250, 250)
    ancho = comparar_dos_modelos.wilson(34, 34)

    assert estrecho[0] > ancho[0]


def test_wilson_sin_datos_no_acota_nada() -> None:
    """Sin observaciones, decir cualquier cosa sería inventarla."""
    assert comparar_dos_modelos.wilson(0, 0) == (0.0, 1.0)


# --- McNemar ----------------------------------------------------------------


def test_mcnemar_sin_discordantes_no_distingue_nada() -> None:
    """Dos modelos que aciertan y fallan exactamente lo mismo no se separan."""
    assert comparar_dos_modelos.mcnemar(0, 0) == 1.0


def test_mcnemar_con_desacuerdo_equilibrado_no_distingue() -> None:
    """Cinco a cinco es lo que se espera de una moneda: no dice nada."""
    assert comparar_dos_modelos.mcnemar(5, 5) == 1.0


def test_mcnemar_con_desacuerdo_fuerte_si_distingue() -> None:
    """Diez a cero sobre diez discordantes es p = 2/1024."""
    p = comparar_dos_modelos.mcnemar(10, 0)

    assert p == pytest.approx(2 / 1024)
    assert p < comparar_dos_modelos.ALFA


def test_mcnemar_no_pasa_de_uno() -> None:
    """La cola doblada de un caso casi equilibrado se recorta en 1."""
    assert comparar_dos_modelos.mcnemar(3, 2) <= 1.0


# --- Emparejado -------------------------------------------------------------


def test_solo_se_comparan_las_preguntas_que_vieron_los_dos() -> None:
    """Comparar sobre conjuntos distintos mide además qué le tocó a cada uno."""
    filas = [
        _fila("P1", A, precision=1.0),
        _fila("P1", B, precision=0.0),
        _fila("P2", A, precision=1.0),
    ]

    resultado = comparar_dos_modelos.comparar(filas, A, B, "precision")

    assert resultado["n"] == 1
    assert (resultado["solo_a"], resultado["solo_b"]) == (1, 0)


def test_las_preguntas_sin_medir_quedan_fuera_de_la_metrica() -> None:
    """Un `None` es «no se pudo medir», no un cero (IT-110)."""
    filas = [
        _fila("P1", A, precision=None),
        _fila("P1", B, precision=1.0),
        _fila("P2", A, precision=1.0),
        _fila("P2", B, precision=1.0),
    ]

    resultado = comparar_dos_modelos.comparar(filas, A, B, "precision")

    assert resultado["n"] == 1


def test_una_ventaja_clara_se_declara_distinguible() -> None:
    """Doce preguntas que acierta uno y falla el otro, y ninguna al revés."""
    filas: list[dict[str, Any]] = []
    for i in range(12):
        filas.append(_fila(f"P{i}", A, precision=1.0))
        filas.append(_fila(f"P{i}", B, precision=0.0))

    resultado = comparar_dos_modelos.comparar(filas, A, B, "precision")

    assert resultado["solo_a"] == 12
    assert resultado["p"] < comparar_dos_modelos.ALFA


# --- Mediana ----------------------------------------------------------------


def test_la_mediana_con_un_numero_par_de_medidas_promedia_las_centrales() -> None:
    filas = [_fila(f"P{i}", A, segundos=s) for i, s in enumerate([10, 20, 30, 40])]

    assert comparar_dos_modelos.medianas(filas, A) == 25.0


def test_la_mediana_de_un_modelo_ausente_es_cero() -> None:
    assert comparar_dos_modelos.medianas([], A) == 0.0


# --- Punto de entrada -------------------------------------------------------


def _registro(tmp_path: Path, filas: list[dict[str, Any]]) -> Path:
    ruta = tmp_path / "registro.jsonl"
    ruta.write_text(
        "\n".join(json.dumps(f, ensure_ascii=False) for f in filas) + "\n",
        encoding="utf-8",
    )
    return ruta


def test_el_informe_dice_si_los_modelos_se_distinguen(tmp_path, capsys) -> None:
    filas = [_fila("P1", A), _fila("P1", B), _fila("P2", A), _fila("P2", B)]
    salida = tmp_path / "informe.md"

    codigo = comparar_dos_modelos.main(
        [
            "--registro",
            str(_registro(tmp_path, filas)),
            "--modelos",
            A,
            B,
            "--salida",
            str(salida),
        ]
    )

    assert codigo == 0
    texto = salida.read_text(encoding="utf-8")
    assert "McNemar" in texto
    assert "no se distinguen" in capsys.readouterr().out


def test_un_registro_que_no_existe_se_denuncia(tmp_path) -> None:
    from tfg_uja.invariantes import InvarianteRoto

    with pytest.raises(InvarianteRoto, match="no existe el registro"):
        comparar_dos_modelos.main(
            [
                "--registro",
                str(tmp_path / "no_esta.jsonl"),
                "--modelos",
                A,
                B,
                "--salida",
                str(tmp_path / "x.md"),
            ]
        )


def test_pedir_un_modelo_que_no_esta_en_el_registro_se_denuncia(tmp_path) -> None:
    from tfg_uja.invariantes import InvarianteRoto

    ruta = _registro(tmp_path, [_fila("P1", A)])

    with pytest.raises(InvarianteRoto, match="se piden"):
        comparar_dos_modelos.main(
            [
                "--registro",
                str(ruta),
                "--modelos",
                A,
                B,
                "--salida",
                str(tmp_path / "x.md"),
            ]
        )


def test_si_los_modelos_no_vieron_lo_mismo_se_aborta(tmp_path) -> None:
    """Comparar sobre bancos distintos da un número que no significa nada.

    Y no se puede detectar mirando las medias: salen las dos, y una es más
    alta. Por eso se comprueba antes de calcular.
    """
    from tfg_uja.invariantes import InvarianteRoto

    filas = [_fila("P1", A), _fila("P1", B), _fila("P2", A)]

    with pytest.raises(InvarianteRoto, match="no vieron las mismas preguntas"):
        comparar_dos_modelos.main(
            [
                "--registro",
                str(_registro(tmp_path, filas)),
                "--modelos",
                A,
                B,
                "--salida",
                str(tmp_path / "x.md"),
            ]
        )


def test_una_metrica_sin_ninguna_medida_no_aparece_en_la_tabla(tmp_path) -> None:
    """Sin datos no se escribe una fila vacía que parezca un resultado."""
    filas = [
        _fila("P1", A, precision=None, cobertura=None),
        _fila("P1", B, precision=None, cobertura=None),
    ]
    salida = tmp_path / "informe.md"

    comparar_dos_modelos.main(
        [
            "--registro",
            str(_registro(tmp_path, filas)),
            "--modelos",
            A,
            B,
            "--salida",
            str(salida),
        ]
    )

    texto = salida.read_text(encoding="utf-8")
    assert "| precision |" not in texto
    assert "| cobertura |" not in texto

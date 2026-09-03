"""Pruebas del verificador de accesibilidad.

Cada comprobación se prueba por sus dos lados: con la interfaz real, que tiene
que pasar, y con una versión estropeada a propósito, que tiene que fallar. Un
verificador que solo se prueba con el caso bueno no demuestra que sirva para
nada: ya ha pasado tres veces en este proyecto que uno diera verde midiendo
otra cosa.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parent.parent
RUTA = RAIZ / "scripts" / "verificadores" / "check_accesibilidad.py"

_spec = importlib.util.spec_from_file_location("check_accesibilidad", RUTA)
assert _spec and _spec.loader
acc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(acc)


CSS_REAL = (RAIZ / "web" / "estilos.css").read_text(encoding="utf-8")
HTML_REAL = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")


# ------------------------------------------------------- la fórmula de contraste


def test_el_blanco_sobre_negro_da_el_maximo():
    """21:1 es el contraste mayor que existe; sirve de calibración."""
    assert acc.contraste("#ffffff", "#000000") == pytest.approx(21.0, abs=0.01)


def test_un_color_consigo_mismo_no_contrasta():
    assert acc.contraste("#006d38", "#006d38") == pytest.approx(1.0)


def test_el_orden_de_los_colores_da_igual():
    """La razón se define con el más claro arriba, se pase como se pase."""
    assert acc.contraste("#ffffff", "#006d38") == acc.contraste("#006d38", "#ffffff")


def test_la_forma_corta_de_tres_cifras_se_expande():
    assert acc.contraste("#fff", "#000") == pytest.approx(21.0, abs=0.01)


def test_la_luminancia_usa_el_tramo_lineal_de_los_valores_bajos():
    """La fórmula tiene dos tramos y el de abajo solo entra con canales muy
    oscuros. Sin este caso, esa rama no la ejecuta ninguna prueba."""
    assert acc.luminancia("#010101") == pytest.approx(0.000303, abs=1e-6)


# --------------------------------------------------------------- el contraste


def test_la_interfaz_real_pasa_el_contraste():
    assert acc.revisar_contraste(CSS_REAL) == []


def test_se_mide_la_paleta_por_defecto_y_no_la_de_alto_contraste():
    """Regresión del defecto con el que nació este verificador.

    La hoja redefine algunas variables dentro de
    ``@media (prefers-contrast: more)``. Leyendo el fichero entero con un
    diccionario ganaba la última declaración, la del medio, así que se medía
    la paleta reforzada: el borde daba 6,00:1 en vez de los 3,02:1 reales, y
    un verde aquí no habría dicho nada de la interfaz que ve casi todo el
    mundo.
    """
    var = acc.variables(CSS_REAL)

    assert var["--borde-fuerte"] == "#8c8d8f"
    assert acc.contraste(var["--borde-fuerte"], var["--superficie"]) == pytest.approx(
        3.02, abs=0.01
    )


def test_una_hoja_sin_bloque_raiz_no_declara_ninguna_variable():
    assert acc.variables(".mensaje { color: #000; }") == {}


def test_un_texto_sin_contraste_se_detecta():
    """Se aclara el color del texto hasta que deja de leerse sobre el fondo."""
    roto = CSS_REAL.replace("--texto: #231f20;", "--texto: #d0d0d0;")
    fallos = acc.revisar_contraste(roto)
    assert fallos and "texto sobre la superficie" in fallos[0]


def test_un_color_escrito_en_la_regla_tambien_se_comprueba():
    """Las parejas literales no salen de una variable y podrían olvidarse."""
    roto = CSS_REAL.replace("--uja-verde: #006d38;", "--uja-verde: #cfe8da;")
    assert any("título de la cabecera" in f for f in acc.revisar_contraste(roto))


# --------------------------------------------------------- tamaño del objetivo


def test_los_controles_reales_llegan_al_minimo():
    assert acc.revisar_objetivos() == []


def test_un_control_pequeno_se_detecta(monkeypatch: pytest.MonkeyPatch):
    """Es el defecto que se encontró: el aspa de cerrar medía 22,6 px."""
    monkeypatch.setattr(acc, "CONTROLES", [("el aspa de cerrar", 22.6, 25.6)])
    fallos = acc.revisar_objetivos()
    assert fallos and "22.6x25.6" in fallos[0]


def test_un_control_bajo_pero_ancho_tambien_falla(monkeypatch: pytest.MonkeyPatch):
    """El criterio pide las dos medidas, no una."""
    monkeypatch.setattr(acc, "CONTROLES", [("una barra", 200.0, 12.0)])
    assert acc.revisar_objetivos() != []


# ----------------------------------------------------------------- foco visible


def test_la_hoja_real_da_foco_a_todos_los_controles():
    assert acc.revisar_foco(CSS_REAL) == []


def test_un_control_sin_regla_de_foco_se_detecta():
    roto = CSS_REAL.replace(".fuentes__cerrar:focus-visible", ".nada:focus-visible")
    assert acc.revisar_foco(roto) == [
        "fuentes__cerrar no tiene regla propia de foco visible"
    ]


# --------------------------------------------------------------------- marcado


def test_el_marcado_real_pasa():
    assert acc.revisar_marcado(HTML_REAL) == []


def test_una_etiqueta_escrita_dentro_de_un_comentario_no_cuenta():
    """Regresión: el HTML explica en un comentario por qué usa `<dialog>`, y
    contarlo como marcado daba un control sin nombre que no existe."""
    assert acc.revisar_marcado("<!-- usa un <button> del navegador -->") == [
        "el documento no declara idioma",
        "el documento no tiene título",
    ]


def test_una_imagen_sin_alt_se_detecta():
    roto = HTML_REAL.replace('alt="Universidad de Jaén"', "")
    assert any("imagen sin alt" in f for f in acc.revisar_marcado(roto))


def test_un_tabindex_positivo_se_detecta():
    roto = HTML_REAL.replace('rows="1"', 'rows="1" tabindex="3"')
    assert any("tabindex positivo (3)" in f for f in acc.revisar_marcado(roto))


def test_un_control_sin_nombre_accesible_se_detecta():
    roto = HTML_REAL.replace('aria-label="Enviar consulta"', "")
    assert any("sin nombre accesible" in f for f in acc.revisar_marcado(roto))


def test_el_area_de_escritura_la_nombra_su_etiqueta():
    """No lleva `aria-label`: la nombra el `<label for=...>`. Si ese label
    desapareciera, el área se quedaría sin nombre y hay que verlo."""
    roto = HTML_REAL.replace('for="entrada"', 'for="otro"')
    assert any('id="entrada"' in f for f in acc.revisar_marcado(roto))


def test_sin_idioma_ni_titulo_se_detectan_los_dos():
    fallos = acc.revisar_marcado("<html><body></body></html>")
    assert "el documento no declara idioma" in fallos
    assert "el documento no tiene título" in fallos


# ------------------------------------------------------------------ el programa


def test_el_programa_pasa_sobre_la_interfaz_real(capsys: Any):
    assert acc.main() == 0
    assert "Accesibilidad OK" in capsys.readouterr().out


def test_el_programa_falla_y_enumera_los_problemas(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
):
    monkeypatch.setattr(acc, "CONTROLES", [("un control diminuto", 8.0, 8.0)])
    assert acc.main() == 1
    salida = capsys.readouterr().out
    assert "FALLA" in salida
    assert "un control diminuto" in salida
    assert "1 problemas" in salida

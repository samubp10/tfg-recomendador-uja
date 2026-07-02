"""Pruebas del spider de grados (IT-03, IT-04 e IT-05)."""

from pathlib import Path

import scrapy
from scrapy.http import HtmlResponse, Request

from tfg_uja.grados_spider import GradosSpider

FIXTURES = Path(__file__).parent / "fixtures"


def _respuesta(fixture, url="https://eps.ujaen.es/grados", meta=None):
    return HtmlResponse(
        url=url,
        body=(FIXTURES / fixture).read_bytes(),
        encoding="utf-8",
        request=Request(url, meta=meta or {}),
    )


# --- IT-03: listado de grados (parse) ---

def test_sigue_cada_grado_del_menu():
    peticiones = list(GradosSpider().parse(_respuesta("grados.html")))
    nombres = [p.meta["nombre"] for p in peticiones]
    assert "Grado en Ingeniería Informática" in nombres
    assert "Grado en Inteligencia Artificial y Ciberseguridad" in nombres


def test_incluye_los_dobles_grados():
    peticiones = list(GradosSpider().parse(_respuesta("grados.html")))
    nombres = [p.meta["nombre"] for p in peticiones]
    assert any(n.startswith("Doble Grado") for n in nombres)


def test_ignora_enlaces_que_no_son_grados():
    peticiones = list(GradosSpider().parse(_respuesta("grados.html")))
    nombres = [p.meta["nombre"] for p in peticiones]
    assert all("PARS" not in n for n in nombres)


def test_las_peticiones_van_a_urls_absolutas():
    peticiones = list(GradosSpider().parse(_respuesta("grados.html")))
    assert peticiones
    assert all(p.url.startswith("https://eps.ujaen.es/") for p in peticiones)


# --- IT-04: portada del grado (parse_portada) ---

def test_encuentra_enlace_a_asignaturas():
    meta = {"nombre": "Grado en Ingeniería Informática"}
    item = next(GradosSpider().parse_portada(_respuesta("portada_grado.html", meta=meta)))
    assert "asignaturas-y-profesorado" in item["url_asignaturas"]


def test_encuentra_enlace_a_salidas():
    meta = {"nombre": "Grado en Ingeniería Informática"}
    item = next(GradosSpider().parse_portada(_respuesta("portada_grado.html", meta=meta)))
    assert "salidas-profesionales" in item["url_salidas"]


def test_detecta_grado_simple():
    meta = {"nombre": "Grado en Ingeniería Informática"}
    item = next(GradosSpider().parse_portada(_respuesta("portada_grado.html", meta=meta)))
    assert item["es_doble_grado"] is False


def test_detecta_doble_grado():
    meta = {"nombre": "Doble Grado en Ingeniería Eléctrica y Mecánica"}
    item = next(GradosSpider().parse_portada(_respuesta("portada_grado.html", meta=meta)))
    assert item["es_doble_grado"] is True


def test_sin_enlace_de_salidas_no_rompe():
    meta = {"nombre": "Grado en Ingeniería Eléctrica"}
    item = next(GradosSpider().parse_portada(_respuesta("portada_sin_salidas.html", meta=meta)))
    assert item["url_salidas"] is None
    assert "asignaturas-y-profesorado" in item["url_asignaturas"]


# --- IT-05: tabla de asignaturas (parse_asignaturas) ---
#
# Se prueba contra la página REAL del Grado en Ingeniería Informática
# (fixtures/tabla_asignaturas.html), que reúne tablas troncales y dos tablas
# de optativas por mención. La fixture derivada tabla_sin_guia.html cubre el
# caso "asignatura sin guía publicada", ausente en Informática.

_URL_ASIG = (
    "https://eps.ujaen.es/grados/"
    "grado-en-ingenieria-informatica/asignaturas-y-profesorado"
)
_META_ASIG = {"nombre": "Grado en Ingeniería Informática"}


def _asignaturas(fixture="tabla_asignaturas.html"):
    resp = _respuesta(fixture, url=_URL_ASIG, meta=_META_ASIG)
    return list(GradosSpider().parse_asignaturas(resp))


def _por_nombre(items, nombre):
    return next((i for i in items if i["nombre"] == nombre), None)


def test_extrae_todas_las_asignaturas_de_la_pagina_real():
    # 67 asignaturas únicas tras validar, limpiar y fusionar el duplicado real.
    assert len(_asignaturas()) == 67


def test_no_pierde_las_optativas_de_mencion():
    items = _asignaturas()
    de_mencion = [i for i in items if i["menciones"]]
    assert len(de_mencion) >= 17
    assert _por_nombre(items, "Procesamiento del lenguaje natural") is not None


def test_asignatura_troncal_con_su_tipo():
    mate = _por_nombre(_asignaturas(), "Matemática discreta")
    assert mate is not None
    assert mate["codigo"] == "13311008"
    assert mate["tipo_asignatura"] == "FB"
    assert mate["ects"] == "6"
    assert mate["tiene_guia"] is True
    assert mate["menciones"] == []


def test_limpia_el_espacio_duro_del_nombre():
    mate = _por_nombre(_asignaturas(), "Matemática discreta")
    assert "\xa0" not in mate["nombre"]


def test_descarta_los_placeholders_de_optativas():
    nombres = [i["nombre"] for i in _asignaturas()]
    assert "Optativa 3" not in nombres
    assert "Optativa 5" not in nombres


def test_extrae_el_trabajo_fin_de_grado():
    tfg = _por_nombre(_asignaturas(), "Trabajo fin de Grado")
    assert tfg is not None
    assert tfg["tipo_asignatura"] == "OB"
    assert tfg["ects"] == "12"


def test_repara_la_url_de_guia_rota():
    asig = next(i for i in _asignaturas() if i["codigo"] == "13312032")
    assert asig["url_guia"].endswith("2025-26-13312032_es.html")


def test_fusiona_una_asignatura_de_varias_menciones():
    minweb = _por_nombre(_asignaturas(), "Minería web")
    assert minweb is not None
    assert set(minweb["menciones"]) == {
        "Informática empresarial",
        "Tratamiento inteligente de la información",
    }


def test_no_duplica_una_optativa_comun_a_varias_menciones():
    # "Prácticas externas" (13313009) aparece en las dos tablas de menciones.
    practicas = [i for i in _asignaturas() if i["codigo"] == "13313009"]
    assert len(practicas) == 1


def test_quita_el_asterisco_de_las_practicas_externas():
    items = _asignaturas()
    assert _por_nombre(items, "Prácticas externas") is not None
    assert _por_nombre(items, "Prácticas externas *") is None


def test_los_ects_reales_son_6_o_12():
    assert {i["ects"] for i in _asignaturas()} == {"6", "12"}


def test_una_asignatura_sin_guia_se_emite_igualmente():
    items = _asignaturas("tabla_sin_guia.html")
    sin_guia = _por_nombre(items, "Auditoría informática")
    assert sin_guia is not None
    assert sin_guia["tiene_guia"] is False
    assert sin_guia["url_guia"] is None


def test_portada_encola_el_rastreo_de_asignaturas():
    meta = {"nombre": "Grado en Ingeniería Informática"}
    resultados = list(
        GradosSpider().parse_portada(_respuesta("portada_grado.html", meta=meta))
    )
    requests = [r for r in resultados if isinstance(r, scrapy.Request)]
    assert len(requests) == 1
    assert "asignaturas-y-profesorado" in requests[0].url

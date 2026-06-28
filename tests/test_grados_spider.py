"""Pruebas del spider de grados (IT-03 e IT-04)."""

from pathlib import Path

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

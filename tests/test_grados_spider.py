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

_URL_ASIG = (
    "https://eps.ujaen.es/grados/"
    "grado-en-ingenieria-informatica/asignaturas-y-profesorado"
)
_META_ASIG = {"nombre": "Grado en Ingeniería Informática"}


def _items_asignaturas():
    """Devuelve la lista de items emitidos por parse_asignaturas."""
    resp = _respuesta("tabla_asignaturas.html", url=_URL_ASIG, meta=_META_ASIG)
    return list(GradosSpider().parse_asignaturas(resp))


def test_extrae_asignaturas_con_enlace():
    items = _items_asignaturas()
    con_guia = [i for i in items if i["tiene_guia"]]
    assert len(con_guia) == 2
    assert all(i["url_guia"] is not None for i in con_guia)


def test_extrae_asignatura_sin_enlace():
    items = _items_asignaturas()
    sin_guia = [i for i in items if not i["tiene_guia"]]
    assert len(sin_guia) == 2
    nombres_sin_guia = [i["nombre"] for i in sin_guia]
    assert "Arquitectura de computadores" in nombres_sin_guia
    assert all(i["url_guia"] is None for i in sin_guia)


def test_descarta_placeholder_optativa():
    items = _items_asignaturas()
    nombres = [i["nombre"] for i in items]
    assert "Optativa 1" not in nombres


def test_descarta_nombre_vacio():
    items = _items_asignaturas()
    assert all(i["nombre"] for i in items)


def test_limpia_nombre_con_espacios_duros():
    items = _items_asignaturas()
    mate = [i for i in items if "discreta" in i["nombre"]][0]
    assert "\xa0" not in mate["nombre"]
    assert mate["nombre"] == "Matemática discreta"


def test_repara_url_guia_rota():
    items = _items_asignaturas()
    fbd = [i for i in items if "bases de datos" in i["nombre"]][0]
    assert fbd["url_guia"].endswith("_es.html")
    assert "htmles" not in fbd["url_guia"]


def test_portada_sigue_a_asignaturas():
    meta = {"nombre": "Grado en Ingeniería Informática"}
    resultados = list(GradosSpider().parse_portada(
        _respuesta("portada_grado.html", meta=meta)
    ))
    requests = [r for r in resultados if isinstance(r, scrapy.Request)]
    assert len(requests) == 1
    assert "asignaturas-y-profesorado" in requests[0].url


def test_extrae_ects():
    items = _items_asignaturas()
    assert all(i["ects"] == "6" for i in items)


def test_normaliza_tipos_textuales():
    items = _items_asignaturas()
    prog = [i for i in items if i["nombre"] == "Programación"][0]
    assert prog["tipo_asignatura"] == "FB"



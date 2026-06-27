"""Pruebas del spider de grados (IT-03)."""

from pathlib import Path

from scrapy.http import HtmlResponse

from tfg_uja.grados_spider import GradosSpider

FIXTURE = Path(__file__).parent / "fixtures" / "grados.html"


def _respuesta():
    return HtmlResponse(
        url="https://eps.ujaen.es/grados",
        body=FIXTURE.read_bytes(),
        encoding="utf-8",
    )


def test_extrae_los_grados_del_menu():
    nombres = [i["nombre"] for i in GradosSpider().parse(_respuesta())]
    assert "Grado en Ingeniería Informática" in nombres
    assert "Grado en Inteligencia Artificial y Ciberseguridad" in nombres


def test_incluye_los_dobles_grados():
    nombres = [i["nombre"] for i in GradosSpider().parse(_respuesta())]
    assert any(n.startswith("Doble Grado") for n in nombres)


def test_ignora_enlaces_que_no_son_grados():
    nombres = [i["nombre"] for i in GradosSpider().parse(_respuesta())]
    assert all("PARS" not in n for n in nombres)


def test_las_urls_son_absolutas():
    items = list(GradosSpider().parse(_respuesta()))
    assert items
    assert all(i["url"].startswith("https://eps.ujaen.es/") for i in items)

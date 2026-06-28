"""Spider de Scrapy para la oferta de grados de la EPSJ.

Define el spider que recorre la web de la Escuela Politécnica Superior de Jaén.
Por ahora extrae el listado de titulaciones desde el menú lateral de
https://eps.ujaen.es/grados; en iteraciones posteriores seguirá cada grado
hasta sus asignaturas y guías docentes.
"""

import scrapy


class GradosSpider(scrapy.Spider):
    """Spider que extrae el listado de grados de la EPSJ.

    Parte de la página de grados de la EPSJ y recoge, del menú lateral de
    navegación, el nombre y la URL de cada titulación oficial.

    Attributes:
        name (str): Nombre con el que se invoca el spider en Scrapy.
        allowed_domains (list[str]): Dominios que el spider puede visitar.
        start_urls (list[str]): URL de partida del rastreo.
    """

    name = "grados"
    allowed_domains = ["ujaen.es", "uvirtual.ujaen.es"]
    start_urls = ["https://eps.ujaen.es/grados"]

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 1.0,
        "USER_AGENT": "TFG-UJA/0.1 (+https://github.com/samubp10/tfg-recomendador-uja)",
        "FEED_EXPORT_ENCODING": "utf-8",
    }

    def parse(self, response):
        """Extrae el listado de grados desde el menú lateral de la página.

        Recorre los enlaces del menú de sección y conserva únicamente los que
        corresponden a una titulación (los que contienen la palabra «Grado»),
        descartando el resto de entradas del menú.

        Args:
            response (scrapy.http.Response): Respuesta de la página de grados
                de la EPSJ.

        Yields:
            dict: Diccionario con las claves ``nombre`` y ``url`` de cada grado
                encontrado.
        """
        enlaces = response.css("aside.layout-sidebar-first nav ul.menu li a")
        for enlace in enlaces:
            nombre = (enlace.css("::text").get() or "").strip()
            url = enlace.attrib.get("href")
            if url and "Grado" in nombre:
                yield {"nombre": nombre, "url": response.urljoin(url)}
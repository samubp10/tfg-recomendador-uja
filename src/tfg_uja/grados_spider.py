"""Spider de Scrapy para la oferta de grados de la EPSJ.

Define el spider que recorre la web de la Escuela Politécnica Superior de Jaén.
Parte del listado de titulaciones de https://eps.ujaen.es/grados y, por cada
grado, sigue hasta su portada para localizar sus asignaturas y sus salidas
profesionales.
"""

import scrapy

from tfg_uja.text_cleaner import limpiar_texto, reparar_url
from tfg_uja.validators import es_asignatura_valida, normalizar_tipo


class GradosSpider(scrapy.Spider):
    """Spider que recorre los grados de la EPSJ y su información.

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
        """Sigue cada grado del listado hacia su portada.

        Recorre los enlaces del menú lateral y, por cada titulación (las que
        contienen la palabra «Grado»), emite una petición a su portada,
        llevando el nombre del grado en los metadatos.

        Args:
            response (scrapy.http.Response): Respuesta de la página de grados.

        Yields:
            scrapy.Request: Petición a la portada de cada grado.
        """
        enlaces = response.css("aside.layout-sidebar-first nav ul.menu li a")
        for enlace in enlaces:
            nombre = (enlace.css("::text").get() or "").strip()
            url = enlace.attrib.get("href")
            if url and "Grado" in nombre:
                yield response.follow(
                    url, callback=self.parse_portada, meta={"nombre": nombre}
                )

    def parse_portada(self, response):
        """Extrae de la portada de un grado sus enlaces clave.

        Determina si el grado es un doble grado (a partir de su nombre) y
        localiza los enlaces a «asignaturas y profesorado» y a «salidas
        profesionales». Si alguno no existe, su valor queda a ``None``.

        Cuando existe el enlace a asignaturas, emite además una petición
        para descargar la tabla de asignaturas del grado.

        Args:
            response (scrapy.http.Response): Respuesta de la portada del grado.

        Yields:
            dict: Datos del grado: nombre, tipo y los enlaces hallados.
            scrapy.Request: Petición a la página de asignaturas, si existe.
        """
        nombre = response.meta["nombre"]
        url_asignaturas = response.css(
            'a[href*="asignaturas-y-profesorado"]::attr(href)'
        ).get()
        url_salidas = response.css(
            'a[href*="salidas-profesionales"]::attr(href)'
        ).get()
        yield {
            "tipo": "grado",
            "nombre": nombre,
            "es_doble_grado": "Doble Grado" in nombre,
            "url_asignaturas": response.urljoin(url_asignaturas) if url_asignaturas else None,
            "url_salidas": response.urljoin(url_salidas) if url_salidas else None,
        }
        if url_asignaturas:
            yield response.follow(
                url_asignaturas,
                callback=self.parse_asignaturas,
                meta={"nombre": nombre},
            )

    def parse_asignaturas(self, response):
        """Recorre la tabla de asignaturas de un grado.

        Por cada fila de la tabla, limpia el nombre con
        :func:`~tfg_uja.text_cleaner.limpiar_texto` y valida con
        :func:`~tfg_uja.validators.es_asignatura_valida`. Las filas válidas
        se emiten como items de tipo ``"asignatura"``, distinguiendo las que
        enlazan a la guía docente de las que no.

        Args:
            response (scrapy.http.Response): Respuesta de la página de
                asignaturas y profesorado.

        Yields:
            dict: Datos de cada asignatura válida encontrada.
        """
        grado = response.meta["nombre"]
        for fila in response.css("table tbody tr"):
            celdas = fila.css("td")
            if len(celdas) < 4:
                continue

            codigo = limpiar_texto(celdas[0].css("::text").get())
            nombre = limpiar_texto(celdas[1].css("::text").get())
            tipo_crudo = limpiar_texto(celdas[2].css("::text").get())
            tipo_asig = normalizar_tipo(tipo_crudo)

            if not es_asignatura_valida(codigo, nombre, tipo_asig):
                continue

            ects = limpiar_texto(celdas[3].css("::text").get())

            enlace = celdas[1].css("a::attr(href)").get()
            if enlace:
                url_guia = reparar_url(response.urljoin(enlace))
                tiene_guia = True
            else:
                url_guia = None
                tiene_guia = False

            yield {
                "tipo": "asignatura",
                "grado": grado,
                "codigo": codigo,
                "nombre": nombre,
                "tipo_asignatura": tipo_asig,
                "ects": ects,
                "url_guia": url_guia,
                "tiene_guia": tiene_guia,
            }

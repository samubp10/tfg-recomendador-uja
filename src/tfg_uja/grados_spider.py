"""Spider de Scrapy para la oferta de grados de la EPSJ.

Define el spider que recorre la web de la Escuela Politécnica Superior de Jaén.
Parte del listado de titulaciones de https://eps.ujaen.es/grados y, por cada
grado, sigue hasta su portada para localizar sus asignaturas y sus salidas
profesionales.
"""

import scrapy

from tfg_uja.text_cleaner import (
    limpiar_texto,
    quitar_nota_al_pie,
    reparar_url,
    separar_oferta,
)
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
        """Recorre las tablas de asignaturas de un grado.

        La página reúne varias tablas. Unas son troncales (su tercera columna
        es el tipo de asignatura: FB, OB, OP, ...) y otras son de optativas por
        mención (su tercera columna es la mención). Se distinguen por la
        cabecera de esa columna. Por cada fila se limpia el nombre con
        :func:`~tfg_uja.text_cleaner.limpiar_texto`, se le retira la nota al
        pie con :func:`~tfg_uja.text_cleaner.quitar_nota_al_pie` y se valida
        con :func:`~tfg_uja.validators.es_asignatura_valida`. Las de mención se
        registran con tipo ``"OP"`` y sus menciones como lista; una misma
        optativa puede figurar en varias menciones y en varias tablas, por lo
        que se fusiona por código para no duplicarla. Seguir el enlace a la
        guía docente es tarea de IT-06.

        Args:
            response (scrapy.http.Response): Respuesta de la página de
                asignaturas y profesorado.

        Yields:
            dict: Datos de cada asignatura válida, sin duplicados.
        """
        grado = response.meta["nombre"]
        # Se acumulan las asignaturas por código para poder fusionar las
        # menciones de las que aparecen repetidas.
        por_codigo = {}
        orden = []
        sin_codigo = []
        for tabla in response.css("table"):
            filas = tabla.css("tr")
            if not filas:
                continue
            cabeceras = [
                limpiar_texto(" ".join(th.css("::text").getall()))
                for th in filas[0].css("th")
            ]
            if len(cabeceras) < 3:
                continue
            etiqueta_columna = cabeceras[2].lower()
            if etiqueta_columna.startswith("menci"):
                es_tabla_de_menciones = True
            elif etiqueta_columna == "tipo":
                es_tabla_de_menciones = False
            else:
                self.logger.warning(
                    "Tabla con una tercera columna inesperada %r; se omite.",
                    cabeceras,
                )
                continue
            for fila in filas:
                celdas = fila.css("td")
                if len(celdas) < 4:
                    continue
                codigo = limpiar_texto(" ".join(celdas[0].css("::text").getall()))
                nombre = limpiar_texto(" ".join(celdas[1].css("::text").getall()))
                nombre, ofertada = separar_oferta(nombre)
                nombre = quitar_nota_al_pie(nombre)
                if es_tabla_de_menciones:
                    tipo_asig = "OP"
                    menciones = self._menciones(celdas[2])
                else:
                    tipo_asig = normalizar_tipo(
                        limpiar_texto(" ".join(celdas[2].css("::text").getall()))
                    )
                    menciones = []
                if not es_asignatura_valida(codigo, nombre, tipo_asig):
                    continue
                ects = limpiar_texto(" ".join(celdas[3].css("::text").getall()))
                enlace = celdas[1].css("a::attr(href)").get()
                if enlace:
                    url_guia = reparar_url(response.urljoin(enlace))
                    tiene_guia = True
                else:
                    url_guia = None
                    tiene_guia = False
                item = {
                    "tipo": "asignatura",
                    "grado": grado,
                    "codigo": codigo,
                    "nombre": nombre,
                    "tipo_asignatura": tipo_asig,
                    "menciones": menciones,
                    "ects": ects,
                    "ofertada": ofertada,
                    "url_guia": url_guia,
                    "tiene_guia": tiene_guia,
                }
                if codigo and codigo in por_codigo:
                    existentes = por_codigo[codigo]["menciones"]
                    for nueva in menciones:
                        if nueva not in existentes:
                            existentes.append(nueva)
                elif codigo:
                    por_codigo[codigo] = item
                    orden.append(codigo)
                else:
                    sin_codigo.append(item)
        for codigo in orden:
            yield por_codigo[codigo]
        for item in sin_codigo:
            yield item

    @staticmethod
    def _menciones(celda):
        """Extrae de una celda las menciones de una asignatura optativa.

        Una asignatura puede pertenecer a varias menciones, que la web
        presenta de dos formas: en párrafos ``<p>`` separados o dentro de un
        mismo texto separadas por una barra ("A / B"). Ambas se normalizan a
        una lista plana de menciones, sin duplicados ni entradas vacías.

        Args:
            celda (scrapy.selector.Selector): Celda de la columna «Mención».

        Returns:
            list[str]: Menciones de la asignatura.
        """
        parrafos = [limpiar_texto(p) for p in celda.css("p::text").getall()]
        parrafos = [p for p in parrafos if p]
        if not parrafos:
            texto = limpiar_texto(" ".join(celda.css("::text").getall()))
            parrafos = [texto] if texto else []
        menciones = []
        for parrafo in parrafos:
            for parte in parrafo.split("/"):
                parte = parte.strip()
                if parte and parte not in menciones:
                    menciones.append(parte)
        return menciones

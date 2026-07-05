"""Spider de Scrapy para la oferta de grados de la EPSJ.

Define el spider que recorre la web de la Escuela Politécnica Superior de Jaén.
Parte del listado de titulaciones de https://eps.ujaen.es/grados y, por cada
grado, sigue hasta su portada para localizar sus asignaturas y sus salidas
profesionales.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final, NotRequired, TypedDict

import scrapy
from scrapy.http import Request, Response

from tfg_uja.text_cleaner import (
    limpiar_texto,
    quitar_nota_al_pie,
    reparar_url,
    separar_oferta,
)
from tfg_uja.validators import es_asignatura_valida, normalizar_tipo

UMBRAL_CONTENIDO_GUIA: Final[int] = 200


class GradoItem(TypedDict):
    """Item de un grado de la EPSJ."""
    nombre: str
    url: str
    salidas: NotRequired[str]


class AsignaturaItem(TypedDict):
    """Item de una asignatura de un plan de estudios."""
    grado: str
    nombre: str
    tipo: str
    curso: int
    ects: NotRequired[float]
    ofertada: bool
    mencion: NotRequired[str]


class GuiaItem(TypedDict):
    """Item del contenido extraído de una guía docente."""
    asignatura: str
    contenido: str


class SalidasItem(TypedDict):
    """Item de las salidas profesionales de un grado."""
    grado: str
    texto: str


class GradosSpider(scrapy.Spider):
    """Spider que recorre los grados de la EPSJ y su información.

    Attributes:
        name (str): Nombre con el que se invoca el spider en Scrapy.
        allowed_domains (list[str]): Dominios que el spider puede visitar.
        start_urls (list[str]): URL de partida del rastreo.
    """
    name: str = "grados"
    allowed_domains = ["ujaen.es", "uvirtual.ujaen.es"]
    start_urls = ["https://eps.ujaen.es/grados"]

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 1.0,
        "USER_AGENT": "TFG-UJA/0.1 (+https://github.com/samubp10/tfg-recomendador-uja)",
        "FEED_EXPORT_ENCODING": "utf-8",
    }

    _SECCIONES_EXCLUIDAS_FALLBACK: Final[set[str]] = {
        "coordinador",
        "equipodocente",
        "clausulas",
        "objetivosdesarrollosostenible",
    }

    def parse(self, response: Response, **kwargs: Any) -> Iterator[Request]:
        """Punto de entrada: recorre el listado de grados."""
        enlaces = response.css("aside.layout-sidebar-first nav ul.menu li a")
        for enlace in enlaces:
            nombre = (enlace.css("::text").get() or "").strip()
            url = enlace.attrib.get("href")
            if url and "Grado" in nombre:
                yield response.follow(
                    url, callback=self.parse_portada, meta={"nombre": nombre}
                )

    def parse_portada(
        self, response: Response, **kwargs: Any
    ) -> Iterator[Request | GradoItem]:
        """Procesa la portada de un grado y encola asignaturas/salidas."""
        nombre = response.meta["nombre"]
        url_asignaturas = response.css(
            'a[href*="asignaturas-y-profesorado"]::attr(href)'
        ).get()
        url_salidas = response.css(
            'a[href*="salidas-profesionales"]::attr(href)'
        ).get()
        
        yield GradoItem(nombre=nombre, url=response.url)
        
        if url_asignaturas:
            yield response.follow(
                url_asignaturas,
                callback=self.parse_asignaturas,
                meta={"nombre": nombre},
            )
        if url_salidas:
            yield response.follow(
                url_salidas,
                callback=self.parse_salidas,
                meta={"nombre": nombre},
            )

    def parse_asignaturas(
        self, response: Response, **kwargs: Any
    ) -> Iterator[Request | AsignaturaItem]:
        """Extrae la tabla de asignaturas de un plan de estudios."""
        grado = response.meta["nombre"]
        menciones_map = self._menciones(response)
        
        # Para evitar enviar la misma asignatura de mención múltiples veces
        asignaturas_emitidas: set[str] = set()

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
            es_tabla_de_menciones = etiqueta_columna.startswith("menci")
            if not es_tabla_de_menciones and etiqueta_columna != "tipo":
                self.logger.warning("Tabla omitida por columnas: %r", cabeceras)
                continue

            for fila in filas:
                celdas = fila.css("td")
                if len(celdas) < 4:
                    continue
                
                nombre_raw = limpiar_texto(" ".join(celdas[1].css("::text").getall()))
                nombre, ofertada = separar_oferta(nombre_raw)
                nombre = quitar_nota_al_pie(nombre)

                # Controlar duplicados (una asignatura puede aparecer en varias tablas)
                if nombre in asignaturas_emitidas:
                    continue

                if es_tabla_de_menciones:
                    tipo_asig = "OP"
                else:
                    tipo_str = limpiar_texto(" ".join(celdas[2].css("::text").getall()))
                    tipo_asig = normalizar_tipo(tipo_str) or tipo_str

                if not es_asignatura_valida(nombre, tipo_asig):
                    continue

                ects_str = limpiar_texto(" ".join(celdas[3].css("::text").getall()))
                ects: float | None = None
                try:
                    ects = float(ects_str.replace(",", "."))
                except ValueError:
                    pass

                enlace = celdas[1].css("a::attr(href)").get()
                if enlace:
                    url_guia = reparar_url(response.urljoin(enlace))
                    tiene_guia = True
                else:
                    url_guia = None
                    tiene_guia = False
                    
                mencion = menciones_map.get(nombre)

                item: AsignaturaItem = {
                    "grado": grado,
                    "nombre": nombre,
                    "tipo": tipo_asig,
                    "curso": 0,  # Fallback: no disponible en estas tablas
                    "ofertada": ofertada,
                }
                
                if ects is not None:
                    item["ects"] = ects
                if mencion:
                    item["mencion"] = mencion

                yield item
                asignaturas_emitidas.add(nombre)

                if url_guia:
                    yield response.follow(
                        url_guia,
                        callback=self.parse_guia,
                        meta={"nombre": nombre, "grado": grado},
                    )

    def parse_guia(
        self, response: Response, **kwargs: Any
    ) -> Iterator[GuiaItem]:
        """Extrae el contenido de una guía docente concreta."""
        resumen = self._contenido_seccion(response, "resumen")
        temario = self._contenido_seccion(response, "descripcioncontenidos")
        
        total_caracteres = len(resumen) + len(temario)
        if total_caracteres < UMBRAL_CONTENIDO_GUIA:
            self.logger.warning(
                "Guía de %s usa fallback de limpieza general.",
                response.meta["nombre"],
            )
            ficha = response.css("#fichadocenteasignatura")
            if not ficha:
                ficha = response
            exclusion = " ".join(
                f'[not(ancestor-or-self::*[@id="{sid}"])]'
                for sid in self._SECCIONES_EXCLUIDAS_FALLBACK
            )
            nodos_texto = ficha.xpath(f".//text(){exclusion}")
            texto_raw = " ".join(nodos_texto.getall())
            contenido = self._limpieza_general(texto_raw)
        else:
            contenido = f"{resumen}\n\n{temario}".strip()

        yield GuiaItem(
            asignatura=response.meta["nombre"],
            contenido=contenido,
        )

    def parse_salidas(
        self, response: Response, **kwargs: Any
    ) -> Iterator[SalidasItem]:
        """Extrae las salidas profesionales de un grado."""
        elementos = response.css(".field--name-body ul li")
        salidas = []
        for elemento in elementos:
            texto = limpiar_texto(" ".join(elemento.css("::text").getall()))
            if texto:
                salidas.append(texto)
                
        if not salidas:
            self.logger.warning("Sin salidas profesionales en %s", response.url)
            return
            
        texto_unido = "\n".join(f"- {salida}" for salida in salidas)
        yield SalidasItem(
            grado=response.meta["nombre"],
            texto=texto_unido,
        )

    def _menciones(self, response: Response) -> dict[str, str]:
        """Devuelve el mapa asignatura -> mención de un grado."""
        mapa: dict[str, str] = {}
        for tabla in response.css("table"):
            filas = tabla.css("tr")
            if not filas:
                continue
            
            cabeceras = [
                limpiar_texto(" ".join(th.css("::text").getall())).lower()
                for th in filas[0].css("th")
            ]
            if len(cabeceras) < 3 or not cabeceras[2].startswith("menci"):
                continue
            
            for fila in filas[1:]:
                celdas = fila.css("td")
                if len(celdas) < 4:
                    continue
                
                nombre_raw = limpiar_texto(" ".join(celdas[1].css("::text").getall()))
                nombre = quitar_nota_al_pie(separar_oferta(nombre_raw)[0])
                mencion = limpiar_texto(" ".join(celdas[2].css("::text").getall()))
                
                if nombre and mencion:
                    mapa[nombre] = mencion
                    
        return mapa

    def _contenido_seccion(self, response: Response, titulo: str) -> str:
        """Extrae el texto de una sección de guía por su título."""
        bloques = response.css(f"#{titulo} .fdoca_valor_cuadro_ambito")
        partes = []
        for bloque in bloques:
            texto = limpiar_texto(" ".join(bloque.css("::text").getall()))
            if texto and texto != "-":
                partes.append(texto)
        return "\n\n".join(partes)

    def _limpieza_general(self, texto: str) -> str:
        """Aplica la limpieza común a un bloque de texto de guía."""
        return limpiar_texto(texto)

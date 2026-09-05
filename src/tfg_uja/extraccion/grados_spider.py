"""Spider de Scrapy para la oferta de grados de la EPSJ."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any, Final, cast

import scrapy
from scrapy.http import Request, Response
from scrapy.selector import Selector, SelectorList

from tfg_uja import RAIZ as _RAIZ
from tfg_uja.extraccion.guia_pdf import es_pdf, extraer_guia, motivo_sin_guia
from tfg_uja.invariantes import exigir
from tfg_uja.text_cleaner import (
    limpiar_texto,
    normalizar_rotulo,
    quitar_nota_al_pie,
    reparar_url,
    separar_oferta,
)
from tfg_uja.extraccion.validators import es_asignatura_valida, normalizar_tipo

# La raíz del paquete evita que el destino dependa del directorio de ejecución.


#: Tamaño máximo que se acepta descargar, en bytes. Ver el comentario de
#: ``custom_settings``: sale de medir los PDF reales, no de un número redondo.
TOPE_DESCARGA: Final[int] = 2 * 1024 * 1024

# Solo estos caracteres pueden formar parte del nombre local de un PDF.
_PERMITIDO_EN_NOMBRE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_-]")

#: Nombre del fichero cuando la asignatura no trae código, o cuando el que trae
#: no deja ningún carácter admisible.
_SIN_CODIGO: Final[str] = "sin_codigo"


def nombre_seguro(codigo: str | None) -> str:
    """Sanea el código para usarlo como nombre de PDF; sin código usa sin_codigo."""
    limpio = _PERMITIDO_EN_NOMBRE.sub("", codigo or "")
    return limpio or _SIN_CODIGO


# IT-137 unificó los rótulos. El antiguo _normalizar solo recortaba extremos; el del
# fragmentador colapsaba espacios interiores. No eran intercambiables.


# El curso se lee de la URL de la guía, sin fijarlo en la configuración.
_CURSO_EN_URL: Final[re.Pattern[str]] = re.compile(r"/(\d{4}-\d{2})/")

#: Ordinales con los que la EPSJ rotula los cursos. Se admiten las dos formas
#: («primer» y «primero») porque la fuente usa las dos.
_ORDINALES: Final[str] = "primer[o]?|segundo|tercer[o]?|cuarto|quinto|sexto"

# Conserva cursos disyuntivos como «Tercer o Cuarto Curso» sin elegir uno.
_CURSO_EN_ROTULO: Final[re.Pattern[str]] = re.compile(
    rf"\b((?:{_ORDINALES})(?:\s+o\s+(?:{_ORDINALES}))?)\s+curso\b"
)

#: Cuatrimestre dentro del rótulo de una sección.
_CUATRIMESTRE_EN_ROTULO: Final[re.Pattern[str]] = re.compile(
    r"\b(primer|segundo)\s+cuatrimestre\b"
)


def curso_de_url(url: str | None) -> str | None:
    """Deduce el curso académico al que pertenece una guía a partir de su URL."""
    if not url:
        return None
    encontrado = _CURSO_EN_URL.search(url)
    return encontrado.group(1) if encontrado else None


class GradosSpider(scrapy.Spider):
    """Spider que recorre los grados de la EPSJ y su información."""

    name = "grados"
    allowed_domains = ["ujaen.es", "uvirtual.ujaen.es"]
    start_urls = ["https://eps.ujaen.es/grados"]

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 1.0,
        "USER_AGENT": "TFG-UJA/0.1 (+https://github.com/samubp10/tfg-recomendador-uja)",
        "FEED_EXPORT_ENCODING": "utf-8",
        # Los 2 MiB limitan cada descarga y dejan margen sobre el mayor PDF medido
        # (106.683 bytes).
        "DOWNLOAD_MAXSIZE": TOPE_DESCARGA,
        # Avisa mucho antes de rechazar, para enterarse de que la fuente está
        # creciendo sin esperar a que un rastreo falle.
        "DOWNLOAD_WARNSIZE": TOPE_DESCARGA // 4,
    }

    #: Marca con la que la EPSJ señala en el nombre una titulación que ya no
    #: admite nuevas matrículas. Se compara sin tildes y en minúsculas, porque
    #: la fuente no es consistente al escribirla.
    MARCA_EXTINCION: Final[str] = "en extincion"

    # Copia local de auditoría; los tests redirigen este atributo a su temporal.
    DIR_PDF: Path = _RAIZ / "data" / "guias_pdf"

    def parse(self, response: Response) -> Iterator[dict[str, Any] | Request]:
        """Sigue cada grado del listado hacia su portada."""
        yield {
            "tipo": "procedencia",
            "fecha_extraccion": date.today().isoformat(),
            "origen": response.url,
        }
        enlaces = response.css("aside.layout-sidebar-first nav ul.menu li a")
        for enlace in enlaces:
            nombre = (enlace.css("::text").get() or "").strip()
            url = enlace.attrib.get("href")
            if not url or "Grado" not in nombre:
                continue
            if self.esta_en_extincion(nombre):
                self.logger.info(
                    "Titulación en extinción, se excluye del corpus: %r", nombre
                )
                continue
            yield response.follow(
                url, callback=self.parse_portada, meta={"nombre": nombre}
            )

    @classmethod
    def esta_en_extincion(cls, nombre: str) -> bool:
        """Indica si el nombre de una titulación la marca como en extinción."""
        return cls.MARCA_EXTINCION in normalizar_rotulo(nombre)

    def parse_portada(self, response: Response) -> Iterator[dict[str, Any] | Request]:
        """Extrae de la portada de un grado sus enlaces clave."""
        nombre = response.meta["nombre"]
        url_asignaturas = response.css(
            'a[href*="asignaturas-y-profesorado"]::attr(href)'
        ).get()
        if not url_asignaturas:
            # Los dobles usan «plan-de-estudios»; se busca después para conservar la
            # página habitual de los grados simples.
            url_asignaturas = response.css(
                'a[href*="plan-de-estudios"]::attr(href)'
            ).get()
        url_salidas = response.css('a[href*="salidas-profesionales"]::attr(href)').get()
        yield {
            "tipo": "grado",
            "nombre": nombre,
            "es_doble_grado": "Doble Grado" in nombre,
            "url_asignaturas": (
                response.urljoin(url_asignaturas) if url_asignaturas else None
            ),
            "url_salidas": response.urljoin(url_salidas) if url_salidas else None,
        }
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
        self, response: Response
    ) -> Iterator[dict[str, Any] | Request]:
        """Emite asignaturas sin duplicados y las peticiones a sus guías."""
        por_clave: dict[str, dict[str, Any]] = {}
        for tabla in cast(list[Selector], response.css("table")):
            for item in self._asignaturas_de_tabla(tabla, response):
                # El grado es común a toda la página; sin código manda el nombre.
                clave = item["codigo"] or item["nombre"]
                if clave in por_clave:
                    self._fusionar_asignatura(por_clave[clave], item)
                else:
                    por_clave[clave] = item
        for item in por_clave.values():
            yield item
            if item["tiene_guia"]:
                yield response.follow(
                    item["url_guia"],
                    callback=self.parse_guia,
                    meta={
                        campo: item[campo] for campo in ("codigo", "nombre", "grado")
                    },
                )

    def _asignaturas_de_tabla(
        self, tabla: Selector, response: Response
    ) -> Iterator[dict[str, Any]]:
        """Localiza las columnas por rótulo y extrae las filas válidas."""
        filas = cast(list[Selector], tabla.css("tr"))
        if not filas:
            return
        cabeceras = [
            limpiar_texto(" ".join(th.css("::text").getall()))
            for th in filas[0].css("th")
        ]
        columnas = self._columnas_de_cabecera(cabeceras)
        if "mencion" not in columnas and "tipo" not in columnas:
            self.logger.warning(
                "Tabla sin columna de tipo ni de mención %r; se omite.", cabeceras
            )
            return
        if "nombre" not in columnas or "ects" not in columnas:
            self.logger.warning(
                "Tabla sin columna de asignatura o de ECTS %r; se omite.", cabeceras
            )
            return
        curso, cuatrimestre = self._curso_y_cuatrimestre(tabla)
        for fila in filas:
            celdas = cast(list[Selector], fila.css("td"))
            if len(celdas) <= max(columnas.values()):
                continue
            item = self._asignatura_de_fila(celdas, columnas, response)
            if item is not None:
                yield {**item, "curso": curso, "cuatrimestre": cuatrimestre}

    def _asignatura_de_fila(
        self, celdas: list[Selector], columnas: dict[str, int], response: Response
    ) -> dict[str, Any] | None:
        """Extrae una asignatura; devuelve ``None`` si la fila no es válida."""
        codigo = self._texto_celda(celdas, columnas.get("codigo"))
        celda_nombre = celdas[columnas["nombre"]]
        nombre_bruto = self._texto_celda(celdas, columnas["nombre"])
        # La nota de oferta puede estar fuera del enlace que contiene el nombre.
        _, ofertada = separar_oferta(nombre_bruto)
        enlaces = cast(SelectorList, celda_nombre.css("a"))
        if enlaces:
            enlace = cast(Selector, enlaces[0])
            nombre_bruto = (
                self._texto_de(cast(SelectorList, enlace.css("::text"))) or nombre_bruto
            )
        nombre, _ = separar_oferta(nombre_bruto)
        nombre = quitar_nota_al_pie(nombre) or ""
        if "mencion" in columnas:
            tipo_asig = "OP"
            menciones = self._menciones(celdas[columnas["mencion"]])
        else:
            tipo_asig = normalizar_tipo(self._texto_celda(celdas, columnas["tipo"]))
            menciones = []
        if not es_asignatura_valida(codigo, nombre, tipo_asig):
            return None
        href = enlaces.attrib.get("href") if enlaces else None
        return {
            "tipo": "asignatura",
            "grado": response.meta["nombre"],
            "codigo": codigo,
            "nombre": nombre,
            "tipo_asignatura": tipo_asig,
            "menciones": menciones,
            "ects": self._texto_celda(celdas, columnas["ects"]),
            "ofertada": ofertada,
            "url_guia": reparar_url(response.urljoin(href)) if href else None,
            "tiene_guia": bool(href),
        }

    @staticmethod
    def _fusionar_asignatura(existente: dict[str, Any], nueva: dict[str, Any]) -> None:
        """Añade menciones y datos ausentes; conserva la primera aparición."""
        for mencion in nueva["menciones"]:
            if mencion not in existente["menciones"]:
                existente["menciones"].append(mencion)
        for campo in ("curso", "cuatrimestre"):
            if not existente[campo] and nueva[campo]:
                existente[campo] = nueva[campo]

    @staticmethod
    def _curso_y_cuatrimestre(tabla: Selector) -> tuple[str, str]:
        """Lee los rótulos anteriores; las optativas cortan la búsqueda de curso."""
        curso = ""
        cuatrimestre = ""
        previos = tabla.xpath(
            "preceding::*[self::h2 or self::h3 or self::h4 or self::strong"
            " or self::caption]"
        )
        for nodo in reversed(list(previos)):
            rotulo = normalizar_rotulo(
                limpiar_texto(" ".join(nodo.css("::text").getall()))
            )
            if not cuatrimestre:
                encontrado = _CUATRIMESTRE_EN_ROTULO.search(rotulo)
                if encontrado:
                    cuatrimestre = encontrado.group(0).capitalize()
                    continue
            if "optativ" in rotulo:
                break
            encontrado = _CURSO_EN_ROTULO.search(rotulo)
            if encontrado:
                curso = f"{encontrado.group(1)} curso".capitalize()
                break
        return curso, cuatrimestre

    @staticmethod
    def _columnas_de_cabecera(cabeceras: list[str]) -> dict[str, int]:
        """Localiza columnas por rótulo y conserva su primera aparición."""
        columnas: dict[str, int] = {}
        for posicion, rotulo in enumerate(cabeceras):
            campo = GradosSpider._campo_de_rotulo(normalizar_rotulo(rotulo))
            if campo is not None:
                columnas.setdefault(campo, posicion)
        return columnas

    @staticmethod
    def _campo_de_rotulo(etiqueta: str) -> str | None:
        """Reconoce el campo de una cabecera normalizada, o ninguno."""
        if etiqueta.startswith("codigo"):
            return "codigo"
        if etiqueta.startswith("asignatura"):
            return "nombre"
        if etiqueta.startswith(("tipo", "caracter")):
            return "tipo"
        if etiqueta.startswith("mencion"):
            return "mencion"
        if "ects" in etiqueta or etiqueta.startswith("credito"):
            return "ects"
        return None

    @staticmethod
    def _texto_celda(celdas: list[Selector], posicion: int | None) -> str:
        """Devuelve el texto limpio de una celda, o vacío si la columna no existe."""
        if posicion is None:
            return ""
        nodos = cast(SelectorList, celdas[posicion].css("::text"))
        return GradosSpider._texto_de(nodos)

    @staticmethod
    def _texto_de(nodos: SelectorList) -> str:
        """Une los nodos de texto de una selección y los deja limpios."""
        return limpiar_texto(" ".join(nodos.getall()))

    @staticmethod
    def _menciones(celda: Selector) -> list[str]:
        """Extrae de una celda las menciones de una asignatura optativa."""
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

    # Umbral del respaldo HTML; las guías observadas superaban 1.480 caracteres.

    # El PDF no usa este respaldo; se conserva para las guías HTML.
    UMBRAL_CONTENIDO_GUIA: Final[int] = 200

    #: IDs de las secciones que se excluyen del fallback de limpieza general
    #: por no aportar valor a un futuro estudiante o por ser datos personales
    #: del profesorado (privacidad) o texto legal (RGPD).
    _SECCIONES_EXCLUIDAS_FALLBACK: Final[frozenset[str]] = frozenset(
        {
            "coordinador",
            "equipodocente",
            "clausulas",
            "objetivosdesarrollosostenible",
        }
    )

    def parse_salidas(self, response: Response) -> Iterator[dict[str, Any]]:
        """Extrae las salidas profesionales de un grado."""
        introduccion = []
        for parrafo in response.css(".field--name-body p"):
            texto = limpiar_texto(" ".join(parrafo.css("::text").getall()))
            if texto:
                introduccion.append(texto)
        elementos = response.css(".field--name-body ul li")
        salidas = []
        for elemento in elementos:
            texto = limpiar_texto(" ".join(elemento.css("::text").getall()))
            # Conserva la primera aparición de cada salida, también en dobles grados.
            if texto and texto not in salidas:
                salidas.append(texto)
        if not salidas:
            self.logger.warning(
                "Sin salidas profesionales en %s; no se emite item.",
                response.url,
            )
            return
        vinetas = "\n".join(f"- {salida}" for salida in salidas)
        yield {
            "tipo": "salidas",
            "grado": response.meta["nombre"],
            "texto": "\n".join([*introduccion, vinetas]) if introduccion else vinetas,
        }

    def parse_guia(self, response: Response) -> Iterator[dict[str, Any]]:
        """Extrae PDF o HTML; solo el HTML admite limpieza de respaldo."""
        if es_pdf(response.headers.get("Content-Type"), response.body):
            yield from self._guia_desde_pdf(response)
            return
        secciones = {
            "resumen": self._contenido_seccion(response, "resumen"),
            "temario": self._contenido_seccion(response, "descripcioncontenidos"),
        }
        total_caracteres = sum(len(v) for v in secciones.values())
        fallback = total_caracteres < self.UMBRAL_CONTENIDO_GUIA
        if fallback:
            self.logger.warning(
                "Guía %s con contenido estructurado insuficiente (%d "
                "caracteres); se usa el fallback de limpieza general.",
                response.meta["codigo"],
                total_caracteres,
            )
            secciones = {
                "resumen": "",
                "temario": "",
                "cuerpo_general": self._limpieza_general(response),
            }
        yield {
            "tipo": "guia",
            "codigo": response.meta["codigo"],
            "nombre": response.meta["nombre"],
            "grado": response.meta["grado"],
            "curso": curso_de_url(response.url),
            # Registra el formato de origen para poder auditar la extracción (IT-95).
            "formato": "html",
            "fallback": fallback,
            **secciones,
        }

    def _guia_desde_pdf(self, response: Response) -> Iterator[dict[str, Any]]:
        """Emite la guía docente cuando el servidor la sirve como PDF."""
        codigo = response.meta["codigo"]
        self._guardar_pdf(codigo, response.body)
        datos = extraer_guia(response.body)
        if datos is None:
            # Distingue PDF ilegible de secciones vacías en la fuente (IT-95).
            self.logger.warning(
                "Guía %s sin contenido extraíble (motivo: %s); se omite y la "
                "asignatura queda como «sin guía».",
                codigo,
                motivo_sin_guia(response.body),
            )
            return
        yield {
            "tipo": "guia",
            "codigo": codigo,
            "nombre": response.meta["nombre"],
            "grado": response.meta["grado"],
            "curso": curso_de_url(response.url),
            "formato": "pdf",
            "fallback": False,
            "resumen": datos["resumen"],
            "temario": datos["temario"],
        }

    def _guardar_pdf(self, codigo: str, cuerpo: bytes) -> None:
        """Guarda el PDF local; avisa de fallos de disco sin parar el rastreo."""
        try:
            self.DIR_PDF.mkdir(parents=True, exist_ok=True)
            destino = self.DIR_PDF / f"{nombre_seguro(codigo)}.pdf"
            # Comprueba el destino resuelto, además de sanear el nombre remoto.
            exigir(
                destino.resolve().parent == self.DIR_PDF.resolve(),
                lambda: f"el código «{codigo}» apunta fuera de {self.DIR_PDF}",
            )
            destino.write_bytes(cuerpo)
        except OSError as error:
            self.logger.warning(
                "No se ha podido guardar el PDF de la guía %s (%s); el rastreo "
                "sigue, pero esa guía no se podrá auditar.",
                codigo,
                error,
            )

    @staticmethod
    def _contenido_seccion(response: Response, id_seccion: str) -> str:
        """Extrae el texto de una sección de la guía docente por su id."""
        bloques = response.css(f"#{id_seccion} .fdoca_valor_cuadro_ambito")
        partes = []
        for bloque in bloques:
            texto = limpiar_texto(" ".join(bloque.css("::text").getall()))
            if texto and texto != "-":
                partes.append(texto)
        return "\n\n".join(partes)

    @classmethod
    def _limpieza_general(cls, response: Response) -> str:
        """Extrae texto general de la ficha cuando falla la estructura."""
        ficha: SelectorList | Response = response.css("#fichadocenteasignatura")
        if not ficha:
            ficha = response
        exclusion = " ".join(
            f'[not(ancestor-or-self::*[@id="{sid}"])]'
            for sid in cls._SECCIONES_EXCLUIDAS_FALLBACK
        )
        nodos_texto = ficha.xpath(f".//text(){exclusion}")
        texto = limpiar_texto(" ".join(nodos_texto.getall()))
        return texto

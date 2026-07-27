"""Spider de Scrapy para la oferta de grados de la EPSJ.

Define el spider que recorre la web de la Escuela Politécnica Superior de Jaén.
Parte del listado de titulaciones de https://eps.ujaen.es/grados y, por cada
grado, sigue hasta su portada para localizar sus asignaturas y sus salidas
profesionales.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from typing import Any, Final

import scrapy
from scrapy.http import Request, Response
from parsel import Selector, SelectorList

from tfg_uja.guia_pdf import es_pdf, extraer_guia
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

    def parse(self, response: Response) -> Iterator[Request]:
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

    def parse_portada(self, response: Response) -> Iterator[dict[str, Any] | Request]:
        """Extrae de la portada de un grado sus enlaces clave.

        Determina si el grado es un doble grado (a partir de su nombre) y
        localiza los enlaces a «asignaturas y profesorado» y a «salidas
        profesionales». Si alguno no existe, su valor queda a ``None``.

        Cuando existe el enlace a asignaturas, emite además una petición
        para descargar la tabla de asignaturas del grado. Si existe el enlace
        a salidas y el grado no es un doble grado, emite también una petición
        para sus salidas profesionales: las salidas de un doble grado son la
        unión de las de sus dos grados base (que ya se rastrean por separado),
        por lo que no se duplican.

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
        if url_salidas and "Doble Grado" not in nombre:
            yield response.follow(
                url_salidas,
                callback=self.parse_salidas,
                meta={"nombre": nombre},
            )

    def parse_asignaturas(
        self, response: Response
    ) -> Iterator[dict[str, Any] | Request]:
        """Recorre las tablas de asignaturas de un grado.

        La página reúne varias tablas. Unas son troncales (traen columna de
        tipo de asignatura: FB, OB, OP, ...) y otras son de optativas por
        mención (traen columna de mención). Se distinguen por eso, y cada
        columna se localiza por el rótulo de su cabecera mediante
        :meth:`_columnas_de_cabecera`, nunca por su posición: la EPSJ ha
        intercalado columnas nuevas y una posición fija descartaba la tabla
        entera en silencio.

        Por cada fila se limpia el nombre con
        :func:`~tfg_uja.text_cleaner.limpiar_texto`, se le retira la nota al
        pie con :func:`~tfg_uja.text_cleaner.quitar_nota_al_pie` y se valida
        con :func:`~tfg_uja.validators.es_asignatura_valida`. Las de mención se
        registran con tipo ``"OP"`` y sus menciones como lista; una misma
        optativa puede figurar en varias menciones y en varias tablas, por lo
        que se fusiona para no duplicarla. Seguir el enlace a la guía docente
        es tarea de IT-06.

        Args:
            response (scrapy.http.Response): Respuesta de la página de
                asignaturas y profesorado.

        Yields:
            dict: Datos de cada asignatura válida, sin duplicados.
        """
        grado = response.meta["nombre"]
        # Se acumulan las asignaturas para poder fusionar las menciones de las
        # que aparecen en varias tablas. La clave es el código y, cuando falta,
        # el nombre: hay planes de implantación reciente cuyas asignaturas no
        # traen código, y agruparlas solo por código dejaría duplicada la misma
        # asignatura una vez por cada mención en la que figura.
        por_clave: dict[str, dict[str, Any]] = {}
        orden: list[str] = []
        for tabla in response.css("table"):
            filas = tabla.css("tr")
            if not filas:
                continue
            cabeceras = [
                limpiar_texto(" ".join(th.css("::text").getall()))
                for th in filas[0].css("th")
            ]
            columnas = self._columnas_de_cabecera(cabeceras)
            # Una tabla es de menciones si trae columna de mención, y troncal si
            # trae columna de tipo. Sin ninguna de las dos no se puede saber qué
            # es cada asignatura, así que se omite avisando.
            es_tabla_de_menciones = "mencion" in columnas
            if not es_tabla_de_menciones and "tipo" not in columnas:
                self.logger.warning(
                    "Tabla sin columna de tipo ni de mención %r; se omite.",
                    cabeceras,
                )
                continue
            if "nombre" not in columnas or "ects" not in columnas:
                self.logger.warning(
                    "Tabla sin columna de asignatura o de ECTS %r; se omite.",
                    cabeceras,
                )
                continue
            for fila in filas:
                celdas = fila.css("td")
                # La fila debe llegar hasta la última columna que interesa; las
                # de cabecera (sin <td>) y las incompletas se descartan.
                if len(celdas) <= max(columnas.values()):
                    continue
                codigo = self._texto_celda(celdas, columnas.get("codigo"))
                nombre_bruto = self._texto_celda(celdas, columnas["nombre"])
                nombre, ofertada = separar_oferta(nombre_bruto)
                # Un nombre ausente equivale a uno vacío: en ambos casos la
                # fila la descarta es_asignatura_valida unas líneas más abajo.
                nombre = quitar_nota_al_pie(nombre) or ""
                if es_tabla_de_menciones:
                    tipo_asig = "OP"
                    menciones = self._menciones(celdas[columnas["mencion"]])
                else:
                    tipo_asig = normalizar_tipo(
                        self._texto_celda(celdas, columnas["tipo"])
                    )
                    menciones = []
                if not es_asignatura_valida(codigo, nombre, tipo_asig):
                    continue
                ects = self._texto_celda(celdas, columnas["ects"])
                enlace = celdas[columnas["nombre"]].css("a::attr(href)").get()
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
                clave = codigo or nombre
                if clave in por_clave:
                    existentes = por_clave[clave]["menciones"]
                    for nueva in menciones:
                        if nueva not in existentes:
                            existentes.append(nueva)
                else:
                    por_clave[clave] = item
                    orden.append(clave)
        for clave in orden:
            item = por_clave[clave]
            yield item
            if item["tiene_guia"]:
                yield response.follow(
                    item["url_guia"],
                    callback=self.parse_guia,
                    meta={
                        "codigo": item["codigo"],
                        "nombre": item["nombre"],
                        "grado": item["grado"],
                    },
                )

    @staticmethod
    def _columnas_de_cabecera(cabeceras: list[str]) -> dict[str, int]:
        """Sitúa cada columna que interesa a partir del rótulo de su cabecera.

        Las columnas se localizan por su rótulo y no por su posición porque la
        EPSJ las reordena: el plan 2025 de Geomática intercaló una columna
        «Curso recomendado» que desplazó la mención de la tercera a la cuarta
        posición. Con posiciones fijas, la tabla entera se descartaba sin que
        nada fallara. Las columnas que no se reconocen (esa misma «Curso
        recomendado») se ignoran: no forman parte del modelo de datos.

        Args:
            cabeceras (list[str]): Rótulos de la fila de cabecera, ya limpios.

        Returns:
            dict[str, int]: Posición de cada columna reconocida, con las claves
                ``codigo``, ``nombre``, ``tipo``, ``mencion`` y ``ects``. Solo
                aparecen las que existan en la tabla.
        """
        columnas: dict[str, int] = {}
        for posicion, rotulo in enumerate(cabeceras):
            # Se comparan los rótulos sin tildes: la fuente escribe unas veces
            # "Mención" y otras "Mencion", y "Créditos ECTS" o "Creditos ECTS".
            sin_tildes = (
                unicodedata.normalize("NFKD", rotulo)
                .encode("ascii", "ignore")
                .decode("ascii")
            )
            etiqueta = sin_tildes.strip().lower()
            if etiqueta.startswith("codigo"):
                campo = "codigo"
            elif etiqueta.startswith("asignatura"):
                campo = "nombre"
            elif etiqueta.startswith("tipo"):
                campo = "tipo"
            elif etiqueta.startswith("mencion"):
                campo = "mencion"
            elif "ects" in etiqueta or etiqueta.startswith("credito"):
                campo = "ects"
            else:
                continue
            # La primera aparición manda: si un rótulo se repitiera, quedarse
            # con la última movería las celdas de sitio en silencio.
            columnas.setdefault(campo, posicion)
        return columnas

    @staticmethod
    def _texto_celda(celdas: SelectorList[Selector], posicion: int | None) -> str:
        """Devuelve el texto limpio de una celda, o vacío si la columna no existe.

        Args:
            celdas (SelectorList): Celdas de la fila.
            posicion (int): Índice de la columna, o ``None`` si la tabla no la
                trae (el código falta en varios planes de implantación
                reciente).

        Returns:
            str: Texto de la celda, ya limpio.
        """
        if posicion is None:
            return ""
        return limpiar_texto(" ".join(celdas[posicion].css("::text").getall()))

    @staticmethod
    def _menciones(celda: Selector) -> list[str]:
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

    #: Umbral mínimo de caracteres (suma de Resumen + Temario) por debajo del
    #: cual se considera que la extracción estructurada no ha dado contenido
    #: suficiente y se recurre al fallback de limpieza general. Las guías
    #: reales observadas combinan mínimo ~1480 caracteres entre ambas
    #: secciones; 200 deja margen amplio para no activarse en guías
    #: legítimas y sí detectar una estructura rota.
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
        """Extrae las salidas profesionales de un grado.

        Las salidas se publican como una lista dentro del cuerpo del
        contenido de la página (``.field--name-body``). Se extrae cada
        elemento de la lista, se limpia con
        :func:`~tfg_uja.text_cleaner.limpiar_texto` y se compone un texto con
        una viñeta por salida. Si la página no contiene ese bloque (por
        ejemplo, un grado sin salidas publicadas o una URL sin contenido), no
        se emite ningún item, para no introducir registros vacíos.

        Args:
            response (scrapy.http.Response): Respuesta de la página de
                salidas profesionales del grado.

        Yields:
            dict: Salidas del grado, con el texto en viñetas. Solo se emite
                si hay al menos una salida.
        """
        elementos = response.css(".field--name-body ul li")
        salidas = []
        for elemento in elementos:
            texto = limpiar_texto(" ".join(elemento.css("::text").getall()))
            if texto:
                salidas.append(texto)
        if not salidas:
            self.logger.warning(
                "Sin salidas profesionales en %s; no se emite item.",
                response.url,
            )
            return
        yield {
            "tipo": "salidas",
            "grado": response.meta["nombre"],
            "texto": "\n".join(f"- {salida}" for salida in salidas),
        }

    def parse_guia(self, response: Response) -> Iterator[dict[str, Any]]:
        """Extrae el resumen y el temario de una guía docente.

        Recorre las secciones «Resumen» (conocimientos previos y
        prerrequisitos) y «Descripción de contenidos» (temario), localizadas
        por su ``id`` estable en la página (verificado igual en varios
        grados). Cada sección puede tener varios bloques de valor; se
        descartan los marcadores de "sin contenido" (un guion suelto, "-") y
        se unen el resto con un salto de línea.

        Si la suma de caracteres de ambas secciones no alcanza
        :data:`UMBRAL_CONTENIDO_GUIA`, se considera que la estructura
        esperada no ha aparecido (formato de guía distinto al habitual) y se
        recurre a un fallback: todo el texto de la ficha salvo profesorado,
        cláusulas legales y objetivos de desarrollo sostenible.

        Nota sobre codificación: la web declara "UTF-8" en su ``<meta>`` pero
        el servidor envía la cabecera HTTP real como ISO-8859-1/cp1252; en
        una petición real, Scrapy prioriza la cabecera HTTP y decodifica
        bien sin intervención (verificado). Esto solo afecta a fixtures
        locales sin cabecera HTTP, donde el test debe declarar el encoding
        explícitamente.

        Args:
            response (scrapy.http.Response): Respuesta de la guía docente.

        Yields:
            dict: Resumen y temario de la guía, con ``fallback`` indicando
                si se usó la limpieza general en vez de la extracción
                estructurada.
        """
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
            "fallback": fallback,
            **secciones,
        }

    def _guia_desde_pdf(self, response: Response) -> Iterator[dict[str, Any]]:
        """Emite la guía docente cuando el servidor la sirve como PDF.

        Desde el curso 2026-27 la EPSJ publica algunas guías como PDF detrás
        de una URL que sigue acabando en ``.html``. La extracción y el
        filtrado de datos personales viven en
        :mod:`~tfg_uja.guia_pdf`; aquí solo se decide qué hacer con el
        resultado. Si el PDF no se puede leer o no contiene resumen ni
        temario, no se emite ningún item: la asignatura queda como «sin guía»
        (un chunk informativo, IT-09), en lugar de activar el mecanismo de
        respaldo, que volcaría el binario del PDF en la colección.

        Args:
            response (scrapy.http.Response): Respuesta con el PDF de la guía.

        Yields:
            dict: Resumen y temario de la guía, con ``fallback`` siempre
                ``False``. No se emite nada si el PDF es ilegible.
        """
        datos = extraer_guia(response.body)
        if datos is None:
            self.logger.warning(
                "Guía %s servida como PDF ilegible o sin secciones útiles; "
                "se omite y la asignatura queda como «sin guía».",
                response.meta["codigo"],
            )
            return
        yield {
            "tipo": "guia",
            "codigo": response.meta["codigo"],
            "nombre": response.meta["nombre"],
            "grado": response.meta["grado"],
            "fallback": False,
            "resumen": datos["resumen"],
            "temario": datos["temario"],
        }

    @staticmethod
    def _contenido_seccion(response: Response, id_seccion: str) -> str:
        """Extrae el texto de una sección de la guía docente por su id.

        Une los bloques de valor de la sección, descartando los que son
        únicamente el marcador "sin contenido" (un guion suelto) que usa la
        web cuando un campo no se ha rellenado.

        Args:
            response (scrapy.http.Response): Respuesta de la guía docente.
            id_seccion (str): Id del contenedor de la sección (por ejemplo,
                ``"sistemasevaluacion"``).

        Returns:
            str: Texto de la sección, o cadena vacía si no hay contenido.
        """
        bloques = response.css(f"#{id_seccion} .fdoca_valor_cuadro_ambito")
        partes = []
        for bloque in bloques:
            texto = limpiar_texto(" ".join(bloque.css("::text").getall()))
            if texto and texto != "-":
                partes.append(texto)
        return "\n\n".join(partes)

    @classmethod
    def _limpieza_general(cls, response: Response) -> str:
        """Extrae texto general de la ficha cuando falla la estructura.

        Recorre todo el contenido de la ficha docente salvo las secciones de
        profesorado (datos personales), cláusulas legales y objetivos de
        desarrollo sostenible, que no aportan valor a un futuro estudiante.

        Args:
            response (scrapy.http.Response): Respuesta de la guía docente.

        Returns:
            str: Texto limpio de toda la ficha, salvo las secciones excluidas.
        """
        ficha: SelectorList[Selector] | Response = response.css(
            "#fichadocenteasignatura"
        )
        if not ficha:
            ficha = response
        exclusion = " ".join(
            f'[not(ancestor-or-self::*[@id="{sid}"])]'
            for sid in cls._SECCIONES_EXCLUIDAS_FALLBACK
        )
        nodos_texto = ficha.xpath(f".//text(){exclusion}")
        texto = limpiar_texto(" ".join(nodos_texto.getall()))
        return texto

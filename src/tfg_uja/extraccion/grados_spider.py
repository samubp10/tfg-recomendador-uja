"""Spider de Scrapy para la oferta de grados de la EPSJ.

Define el spider que recorre la web de la Escuela Politécnica Superior de Jaén.
Parte del listado de titulaciones de https://eps.ujaen.es/grados y, por cada
grado, sigue hasta su portada para localizar sus asignaturas y sus salidas
profesionales.

Dos caminos para extraer una guía docente, y solo uno está vivo
---------------------------------------------------------------

La guía se puede servir como HTML o como PDF, y :meth:`GradosSpider.parse_guia`
elige por el tipo real de la respuesta. Al empezar el proyecto todas eran HTML;
durante el curso 2026-27 la EPSJ migró al PDF, y en el rastreo del 28/07/2026
**las 288 guías del corpus vienen de PDF y ninguna de HTML** (DQA-0002).

El camino HTML se conserva a propósito, como **retrocompatibilidad**, no por
descuido: la fuente ha cambiado de formato dos veces en un año y servir un PDF
detrás de una URL acabada en ``.html`` parece más un artefacto de migración que
una decisión firme. Conservarlo no cuesta nada apreciable; retirarlo costaría
reescribirlo si la Escuela revierte.

Lo que hoy **no se ejecuta ni una vez** y hay que leer sabiéndolo:
:meth:`GradosSpider._contenido_seccion`, :data:`GradosSpider.UMBRAL_CONTENIDO_GUIA`,
:meth:`GradosSpider._limpieza_general` y el campo ``cuerpo_general`` que produce.
Sus pruebas seguirán pasando, porque usan fixtures HTML de 2025-26 que ya no se
corresponden con lo que sirve la web: comprueban bien un escenario que hoy no
ocurre. Todo el esfuerzo de mejora va al camino PDF (:mod:`tfg_uja.guia_pdf`).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any, Final

import scrapy
from scrapy.http import Request, Response
from parsel import Selector, SelectorList

from tfg_uja import RAIZ as _RAIZ
from tfg_uja.extraccion.guia_pdf import es_pdf, extraer_guia, motivo_sin_guia
from tfg_uja.text_cleaner import (
    limpiar_texto,
    quitar_nota_al_pie,
    reparar_url,
    separar_oferta,
)
from tfg_uja.extraccion.validators import es_asignatura_valida, normalizar_tipo

# La raíz llega de :mod:`tfg_uja` y no se calcula aquí: se resuelve desde la
# ubicación del paquete y no como ruta relativa al directorio de trabajo, para
# que el rastreo deje los ficheros en el mismo sitio se lance desde donde se
# lance.


def _normalizar(texto: str) -> str:
    """Pasa un texto a minúsculas y sin tildes, para compararlo con seguridad.

    La web de la EPSJ no es consistente al acentuar: escribe unas veces
    «Mención» y otras «Mencion», «Créditos ECTS» o «Creditos ECTS». Comparar
    sobre la forma normalizada evita depender de esa inconsistencia.

    Args:
        texto (str): Texto tal como llega de la web.

    Returns:
        str: El texto en minúsculas, sin tildes y sin espacios alrededor.
    """
    sin_tildes = (
        unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    )
    return sin_tildes.strip().lower()


#: Curso académico dentro de la URL de una guía docente. La UJA lo incluye en
#: la ruta del catálogo de fichas (".../p/2025-26/4/130A/13011009/..."), así
#: que se puede leer de ahí en vez de escribirlo a mano en la configuración:
#: un dato deducido de la fuente no se queda obsoleto sin que nadie se entere.
_CURSO_EN_URL: Final[re.Pattern[str]] = re.compile(r"/(\d{4}-\d{2})/")

#: Ordinales con los que la EPSJ rotula los cursos. Se admiten las dos formas
#: («primer» y «primero») porque la fuente usa las dos.
_ORDINALES: Final[str] = "primer[o]?|segundo|tercer[o]?|cuarto|quinto|sexto"

#: Curso dentro del rótulo de una sección. Admite la forma disyuntiva «Tercer o
#: Cuarto Curso» que usan los dobles grados: a partir de tercero el estudiante
#: elige por qué especialidad empieza, así que la fuente no fija uno solo y
#: nosotros tampoco lo fijamos (decisión 9: no se imputa lo que no consta).
_CURSO_EN_ROTULO: Final[re.Pattern[str]] = re.compile(
    rf"\b((?:{_ORDINALES})(?:\s+o\s+(?:{_ORDINALES}))?)\s+curso\b"
)

#: Cuatrimestre dentro del rótulo de una sección.
_CUATRIMESTRE_EN_ROTULO: Final[re.Pattern[str]] = re.compile(
    r"\b(primer|segundo)\s+cuatrimestre\b"
)


def curso_de_url(url: str | None) -> str | None:
    """Deduce el curso académico al que pertenece una guía a partir de su URL.

    Args:
        url (str): URL de la guía docente.

    Returns:
        str: Curso en formato ``"2025-26"``, o ``None`` si la URL no lo lleva
            (el formato de la fuente habría cambiado y conviene que se note,
            en vez de suponer un curso que no consta).
    """
    if not url:
        return None
    encontrado = _CURSO_EN_URL.search(url)
    return encontrado.group(1) if encontrado else None


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

    #: Marca con la que la EPSJ señala en el nombre una titulación que ya no
    #: admite nuevas matrículas. Se compara sin tildes y en minúsculas, porque
    #: la fuente no es consistente al escribirla.
    MARCA_EXTINCION: Final[str] = "en extincion"

    #: Dónde se deja copia de los PDF de las guías para poder auditarlos
    #: después (IT-95). Es atributo de clase y no una constante del módulo
    #: para que las pruebas puedan redirigirlo a un directorio temporal: si no,
    #: ejecutar la batería escribiría dentro del `data/` real del proyecto.
    DIR_PDF: Path = _RAIZ / "data" / "guias_pdf"

    def parse(self, response: Response) -> Iterator[dict[str, Any] | Request]:
        """Sigue cada grado del listado hacia su portada.

        Recorre los enlaces del menú lateral y, por cada titulación (las que
        contienen la palabra «Grado»), emite una petición a su portada,
        llevando el nombre del grado en los metadatos.

        Antes de nada emite el item ``procedencia`` con la fecha del rastreo
        (IT-90). Se emite aquí, en el primer callback, y no al terminar,
        porque Scrapy no permite emitir items una vez cerrado el spider; el
        curso no hace falta en este item, porque cada guía trae el suyo
        deducido de su URL y el conjunto se calcula después.

        Las titulaciones en extinción se descartan aquí, antes de rastrearlas
        (IT-77): el sistema orienta a estudiantes preuniversitarios y un grado
        en extinción no admite nuevas matrículas, así que recomendárselo sería
        un error. Se descarta en el origen y no más adelante para no gastar
        peticiones en la web de la UJA sobre datos que no van a usarse.

        Args:
            response (scrapy.http.Response): Respuesta de la página de grados.

        Yields:
            dict: El item ``procedencia`` del rastreo.
            scrapy.Request: Petición a la portada de cada grado vigente.
        """
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
        """Indica si el nombre de una titulación la marca como en extinción.

        Args:
            nombre (str): Nombre de la titulación tal como aparece en la web.

        Returns:
            bool: ``True`` si la titulación ya no admite nuevas matrículas.
        """
        return cls.MARCA_EXTINCION in _normalizar(nombre)

    def parse_portada(self, response: Response) -> Iterator[dict[str, Any] | Request]:
        """Extrae de la portada de un grado sus enlaces clave.

        Determina si el grado es un doble grado (a partir de su nombre) y
        localiza los enlaces a «asignaturas y profesorado» y a «salidas
        profesionales». Si alguno no existe, su valor queda a ``None``.

        Cuando existe el enlace a asignaturas, emite además una petición
        para descargar la tabla de asignaturas del grado, y otra para sus
        salidas profesionales si están publicadas.

        Las salidas de los dobles grados se excluían a propósito, dando por
        supuesto que eran la unión exacta de las de sus dos grados base.
        **IT-101 comprobó que no lo son**: la página del Doble Grado en
        Ingeniería Eléctrica y Mecánica enuncia además a qué profesiones
        reguladas da acceso la doble titulación, que es justo lo que un
        estudiante preuniversitario quiere saber, y no repite las salidas
        comunes a los dos grados. Reproducir eso uniendo dos textos exigiría
        deduplicar y redactar la frase de cabecera; leer la página que ya lo
        dice es más simple y más fiel.

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
        if not url_asignaturas:
            # Los dobles grados publican su plan bajo otra ruta (IT-101):
            # «plan-de-estudios» en lugar de «asignaturas-y-profesorado». No es
            # que la fuente no lo publique, es que el patrón del enlace es
            # otro, y buscando solo el primero las cinco titulaciones dobles se
            # quedaban sin una sola asignatura. Se busca en segundo lugar para
            # no cambiar de página en los grados simples, que traen las dos.
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
            # IT-105: el curso es de la tabla entera, no de cada fila, porque
            # la fuente lo publica en el rótulo de la sección que la agrupa.
            curso, cuatrimestre = self._curso_y_cuatrimestre(tabla)
            for fila in filas:
                celdas = fila.css("td")
                # La fila debe llegar hasta la última columna que interesa; las
                # de cabecera (sin <td>) y las incompletas se descartan.
                if len(celdas) <= max(columnas.values()):
                    continue
                codigo = self._texto_celda(celdas, columnas.get("codigo"))
                celda_nombre = celdas[columnas["nombre"]]
                nombre_bruto = self._texto_celda(celdas, columnas["nombre"])
                # La oferta se decide con la celda ENTERA: la fuente escribe
                # "(No ofertada en 2025/26)" fuera del enlace, en un <em>, así
                # que mirar solo el enlace la perdería.
                _, ofertada = separar_oferta(nombre_bruto)
                # El nombre, en cambio, es el texto del enlace que lleva a su
                # guía (ver enlace_guia): la celda puede traer además otros
                # enlaces que no forman parte del nombre, y juntar todo su
                # texto los pegaba al final (IT-93, «... ( Syllabus )»).
                enlace_guia = celda_nombre.css("a")
                if enlace_guia:
                    nombre_bruto = (
                        self._texto_de(enlace_guia[0].css("::text")) or nombre_bruto
                    )
                nombre, _ = separar_oferta(nombre_bruto)
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
                # El mismo <a> del que ha salido el nombre: así el nombre y la
                # URL no pueden hablar de cosas distintas, que es lo que pasaba
                # cuando uno salía de la celda entera y la otra de un elemento.
                enlace = enlace_guia.attrib.get("href") if enlace_guia else None
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
                    "curso": curso,
                    "cuatrimestre": cuatrimestre,
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
                    # Una optativa figura en varias tablas de mención, y solo
                    # algunas de esas tablas están bajo un rótulo con curso.
                    # Se rellena si la primera aparición vino sin él, pero no
                    # se pisa: la primera manda, igual que en las menciones.
                    for campo in ("curso", "cuatrimestre"):
                        if not por_clave[clave][campo] and item[campo]:
                            por_clave[clave][campo] = item[campo]
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
    def _curso_y_cuatrimestre(tabla: Selector) -> tuple[str, str]:
        """Sitúa una tabla en su curso y cuatrimestre a partir de los rótulos.

        La EPSJ **no publica el curso como columna** salvo en el plan 2025 de
        Geomática: lo publica agrupando las tablas bajo encabezados de sección.
        Y no vale el ``<caption>``, que sería el sitio natural, porque está
        vacío en Informática, Eléctrica y Mecánica.

        Se recorren los rótulos hacia atrás desde la tabla y se para en el
        primero que la sitúa. El bloque de optativas ---rotulado «Optativas»,
        «Optatividad» o «Listado de Optativas» según la titulación--- corta la
        búsqueda: sus asignaturas no tienen curso publicado, y seguir hacia
        atrás les asignaría el del último curso, que es el que quedó justo
        encima.

        Se miran encabezados **y negritas** porque los planes de los dobles
        grados no rotulan igual: el curso va en un ``<h3>`` pero el
        cuatrimestre en un ``<li><strong>`` suelto entre el encabezado y la
        tabla. Que un rótulo cuente o no lo decide la expresión regular, no la
        etiqueta que lo envuelve.

        Args:
            tabla (Selector): Tabla de asignaturas dentro de la página.

        Returns:
            tuple[str, str]: Curso y cuatrimestre tal como los rotula la
                fuente, o cadena vacía cuando no consta.
        """
        curso = ""
        cuatrimestre = ""
        previos = tabla.xpath(
            "preceding::*[self::h2 or self::h3 or self::h4 or self::strong"
            " or self::caption]"
        )
        for nodo in reversed(list(previos)):
            rotulo = _normalizar(limpiar_texto(" ".join(nodo.css("::text").getall())))
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
            etiqueta = _normalizar(rotulo)
            if etiqueta.startswith("codigo"):
                campo = "codigo"
            elif etiqueta.startswith("asignatura"):
                campo = "nombre"
            elif etiqueta.startswith("tipo") or etiqueta.startswith("caracter"):
                # «Carácter» es como rotulan esa misma columna los planes de
                # los dobles grados (IT-101). El rótulo cambia, el dato no.
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
        return GradosSpider._texto_de(celdas[posicion].css("::text"))

    @staticmethod
    def _texto_de(nodos: SelectorList[Selector]) -> str:
        """Une los nodos de texto de una selección y los deja limpios.

        Args:
            nodos (SelectorList): Nodos de texto, tal como los devuelve
                ``::text``.

        Returns:
            str: Texto unido y normalizado, vacío si no hay ninguno.
        """
        return limpiar_texto(" ".join(nodos.getall()))

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
    #:
    #: SOLO CAMINO HTML (retrocompatibilidad, ver el docstring del módulo): el
    #: rastreo del 28/07/2026 no lo activa ni una vez, porque las 288 guías
    #: llegan como PDF y la extracción de PDF no pasa por este umbral.
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

        Las salidas se publican dentro del cuerpo del contenido de la página
        (``.field--name-body``): uno o dos párrafos de presentación y, debajo,
        una lista de ámbitos profesionales. Se extrae cada elemento, se limpia
        con :func:`~tfg_uja.text_cleaner.limpiar_texto` y se compone un texto
        con los párrafos primero y una viñeta por salida después. Si la página
        no contiene la lista (por ejemplo, un grado sin salidas publicadas o
        una URL sin contenido), no se emite ningún item, para no introducir
        registros vacíos.

        Los párrafos de presentación **no se recogían hasta IT-101** y se
        perdían en silencio, en las siete titulaciones. Son los que dicen a qué
        profesiones reguladas da acceso el título, que es información que la
        lista de viñetas no contiene y que un estudiante preuniversitario sí
        pregunta.

        Args:
            response (scrapy.http.Response): Respuesta de la página de
                salidas profesionales del grado.

        Yields:
            dict: Salidas del grado, con el texto en viñetas. Solo se emite
                si hay al menos una salida.
        """
        introduccion = []
        for parrafo in response.css(".field--name-body p"):
            texto = limpiar_texto(" ".join(parrafo.css("::text").getall()))
            if texto:
                introduccion.append(texto)
        elementos = response.css(".field--name-body ul li")
        salidas = []
        for elemento in elementos:
            texto = limpiar_texto(" ".join(elemento.css("::text").getall()))
            # La fuente repite viñetas: la página de un doble grado encadena
            # las listas de sus dos grados base sin fusionarlas, de modo que
            # las salidas comunes a ambos aparecen dos veces (4 de 16 en el
            # Doble Grado en Ingeniería Eléctrica y Mecánica). Se conserva la
            # primera aparición y se descartan las repetidas: repetir una
            # salida no añade información y sí desplaza a otras del fragmento.
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
            "curso": curso_de_url(response.url),
            # De qué camino ha salido esta guía (IT-95). Hasta ahora solo se
            # podía deducir a posteriori mirando los saltos de línea del texto,
            # que es una pista y no un dato: sirvió para descubrir que el
            # corpus ya era 100 % PDF, pero deja de ser concluyente en cuanto
            # la fuente vuelva a servir las dos cosas a la vez.
            "formato": "html",
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
                ``False``. No se emite nada si el PDF no aporta contenido.
        """
        codigo = response.meta["codigo"]
        self._guardar_pdf(codigo, response.body)
        datos = extraer_guia(response.body)
        if datos is None:
            # El motivo importa: hasta IT-95 los cuatro casos posibles se
            # anunciaban como «PDF ilegible», y resultó ser falso. Los seis
            # casos reales del rastreo del 28/07/2026 se leían perfectamente
            # y lo vacío eran las secciones en el origen.
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
        """Guarda el PDF de una guía para poder auditar después su extracción.

        Sin esto no hay nada contra lo que comparar: el rastreo lee el PDF,
        se queda con dos secciones y tira el resto, así que comprobar que no
        se ha perdido contenido exigiría volver a rastrear la web entera
        (IT-95). Guardarlos durante el rastreo cuesta cero peticiones.

        Los ficheros van a ``data/``, que no se versiona. **Contienen datos
        personales del profesorado**, así que son una copia local de trabajo y
        no salen de la máquina; el corpus sigue sin ellos.

        Cualquier fallo al escribir se registra y se ignora: perder la copia de
        auditoría es un contratiempo, pero tumbar un rastreo de 300 peticiones
        por no poder crear un fichero sería mucho peor.

        Args:
            codigo (str): Código de la asignatura, que da nombre al fichero.
            cuerpo (bytes): Bytes del PDF tal como los sirvió el servidor.
        """
        try:
            self.DIR_PDF.mkdir(parents=True, exist_ok=True)
            (self.DIR_PDF / f"{codigo or 'sin_codigo'}.pdf").write_bytes(cuerpo)
        except OSError as error:
            self.logger.warning(
                "No se ha podido guardar el PDF de la guía %s (%s); el rastreo "
                "sigue, pero esa guía no se podrá auditar.",
                codigo,
                error,
            )

    @staticmethod
    def _contenido_seccion(response: Response, id_seccion: str) -> str:
        """Extrae el texto de una sección de la guía docente por su id.

        SOLO CAMINO HTML (retrocompatibilidad, ver el docstring del módulo).
        Hoy no se ejecuta: las 288 guías del corpus llegan como PDF y las
        extrae :mod:`tfg_uja.guia_pdf`.

        Une los bloques de valor de la sección, descartando los que son
        únicamente el marcador "sin contenido" (un guion suelto) que usa la
        web cuando un campo no se ha rellenado.

        Los bloques se unen con un salto de línea DOBLE, y cada uno pasa antes
        por ``limpiar_texto``, que colapsa todo espacio en blanco en espacios
        simples. Eso hace que el texto salido de aquí no pueda contener nunca
        un salto suelto, y es lo que permite distinguir a posteriori una guía
        extraída del HTML de una extraída del PDF (DQA-0002).

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

        SOLO CAMINO HTML (retrocompatibilidad, ver el docstring del módulo).
        Es el mecanismo de respaldo, y hoy no se activa ninguna vez: 0 de 288
        guías en el rastreo del 28/07/2026. Una guía en PDF que no se pueda
        extraer NO llega aquí a propósito, porque volcaría el binario en la
        colección; queda como «sin guía» (DQA-0002).

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

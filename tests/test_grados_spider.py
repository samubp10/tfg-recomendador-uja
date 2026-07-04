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
#
# Se prueba contra la página REAL del Grado en Ingeniería Informática
# (fixtures/tabla_asignaturas.html), que reúne tablas troncales y dos tablas
# de optativas por mención. Todos los tests usan HTML real de la EPSJ.

_URL_ASIG = (
    "https://eps.ujaen.es/grados/"
    "grado-en-ingenieria-informatica/asignaturas-y-profesorado"
)
_META_ASIG = {"nombre": "Grado en Ingeniería Informática"}


def _asignaturas(fixture="tabla_asignaturas.html"):
    resp = _respuesta(fixture, url=_URL_ASIG, meta=_META_ASIG)
    return [i for i in GradosSpider().parse_asignaturas(resp) if isinstance(i, dict)]


def _por_nombre(items, nombre):
    return next((i for i in items if i["nombre"] == nombre), None)


def test_extrae_todas_las_asignaturas_de_la_pagina_real():
    # 67 asignaturas únicas tras validar, limpiar y fusionar el duplicado real.
    assert len(_asignaturas()) == 67


def test_no_pierde_las_optativas_de_mencion():
    items = _asignaturas()
    de_mencion = [i for i in items if i["menciones"]]
    assert len(de_mencion) >= 17
    assert _por_nombre(items, "Procesamiento del lenguaje natural") is not None


def test_asignatura_troncal_con_su_tipo():
    mate = _por_nombre(_asignaturas(), "Matemática discreta")
    assert mate is not None
    assert mate["codigo"] == "13311008"
    assert mate["tipo_asignatura"] == "FB"
    assert mate["ects"] == "6"
    assert mate["tiene_guia"] is True
    assert mate["menciones"] == []


def test_limpia_el_espacio_duro_del_nombre():
    mate = _por_nombre(_asignaturas(), "Matemática discreta")
    assert "\xa0" not in mate["nombre"]


def test_descarta_los_placeholders_de_optativas():
    nombres = [i["nombre"] for i in _asignaturas()]
    assert "Optativa 3" not in nombres
    assert "Optativa 5" not in nombres


def test_extrae_el_trabajo_fin_de_grado():
    tfg = _por_nombre(_asignaturas(), "Trabajo fin de Grado")
    assert tfg is not None
    assert tfg["tipo_asignatura"] == "OB"
    assert tfg["ects"] == "12"


def test_repara_la_url_de_guia_rota():
    asig = next(i for i in _asignaturas() if i["codigo"] == "13312032")
    assert asig["url_guia"].endswith("2025-26-13312032_es.html")


def test_fusiona_una_asignatura_de_varias_menciones():
    minweb = _por_nombre(_asignaturas(), "Minería web")
    assert minweb is not None
    assert set(minweb["menciones"]) == {
        "Informática empresarial",
        "Tratamiento inteligente de la información",
    }


def test_no_duplica_una_optativa_comun_a_varias_menciones():
    # "Prácticas externas" (13313009) aparece en las dos tablas de menciones.
    practicas = [i for i in _asignaturas() if i["codigo"] == "13313009"]
    assert len(practicas) == 1


def test_quita_el_asterisco_de_las_practicas_externas():
    items = _asignaturas()
    assert _por_nombre(items, "Prácticas externas") is not None
    assert _por_nombre(items, "Prácticas externas *") is None


def test_los_ects_reales_son_6_o_12():
    assert {i["ects"] for i in _asignaturas()} == {"6", "12"}


def test_una_asignatura_sin_guia_se_emite_igualmente():
    # Caso real: en IA y Ciberseguridad (grado en implantación) hay asignaturas
    # que existen pero cuya guía aún no se ha publicado. Deben emitirse igual.
    items = _asignaturas_iayc()
    sin_guia = _por_nombre(items, "Sistemas operativos")
    assert sin_guia is not None
    assert sin_guia["tiene_guia"] is False
    assert sin_guia["url_guia"] is None


def test_portada_encola_el_rastreo_de_asignaturas():
    meta = {"nombre": "Grado en Ingeniería Informática"}
    resultados = list(
        GradosSpider().parse_portada(_respuesta("portada_grado.html", meta=meta))
    )
    requests = [r for r in resultados if isinstance(r, scrapy.Request)]
    asignaturas = [r for r in requests if "asignaturas-y-profesorado" in r.url]
    assert len(asignaturas) == 1


# --- IT-05 (validez externa): Grado en IA y Ciberseguridad ---
#
# Grado en implantación con estructura distinta a Informática: tipos escritos
# con nombre largo (Formación básica/Obligatoria/Optativa), asignaturas de
# 2.º-4.º sin código ni guía publicada, y el TFG con carácter propio "TFG".

_META_IAYC = {"nombre": "Grado en Inteligencia Artificial y Ciberseguridad"}


def _asignaturas_iayc():
    resp = _respuesta(
        "tabla_asignaturas_iayc.html",
        url="https://eps.ujaen.es/grados/grado-en-inteligencia-artificial-y-ciberseguridad/asignaturas-y-profesorado",
        meta=_META_IAYC,
    )
    return [i for i in GradosSpider().parse_asignaturas(resp) if isinstance(i, dict)]


def test_iayc_normaliza_los_tipos_de_nombre_largo():
    fb = _por_nombre(_asignaturas_iayc(), "Matemática discreta")
    assert fb is not None
    assert fb["tipo_asignatura"] == "FB"


def test_iayc_extrae_el_tfg_con_su_caracter_propio():
    tfg = _por_nombre(_asignaturas_iayc(), "Trabajo fin de grado")
    assert tfg is not None
    assert tfg["tipo_asignatura"] == "TFG"


def test_iayc_conserva_asignaturas_sin_codigo_ni_guia():
    # Caso real: 2.º-4.º del grado nuevo aún sin guía publicada.
    so = _por_nombre(_asignaturas_iayc(), "Sistemas operativos")
    assert so is not None
    assert so["codigo"] == ""
    assert so["tiene_guia"] is False


def test_iayc_descarta_los_placeholders_de_optativas():
    nombres = [i["nombre"] for i in _asignaturas_iayc()]
    assert "Optativa 1" not in nombres
    assert "Optativa 2" not in nombres


# --- IT-05 (validez externa): cabeceras <th> envueltas en <strong> ---
#
# Los grados de la rama industrial (Mecánica, Eléctrica, Electrónica,
# Organización Industrial) escriben la cabecera como <th><strong>Tipo</strong>
# </th> en vez de <th>Tipo</th>. El texto directo del <th> es vacío, por lo que
# la cabecera debe leerse incluyendo el texto descendiente.

def test_extrae_grado_con_cabeceras_envueltas_en_strong():
    resp = _respuesta(
        "tabla_mecanica.html",
        url="https://eps.ujaen.es/grados/grado-en-ingenieria-mecanica/asignaturas-y-profesorado",
        meta={"nombre": "Grado en Ingeniería Mecánica"},
    )
    items = [i for i in GradosSpider().parse_asignaturas(resp) if isinstance(i, dict)]
    assert len(items) > 0
    # También sus tablas de mención se detectan pese a la cabecera envuelta.
    assert any(i["menciones"] for i in items)


# --- IT-05 (campo ofertada): caso real del Grado en Ingeniería Eléctrica ---
#
# Eléctrica incluye 4 optativas marcadas "(No ofertada en 2025/26)". El nombre
# debe quedar limpio y el campo ofertada a False, conservando la asignatura.

def _asignaturas_electrica():
    resp = _respuesta(
        "tabla_electrica.html",
        url="https://eps.ujaen.es/grados/grado-en-ingenieria-electrica/asignaturas-y-profesorado",
        meta={"nombre": "Grado en Ingeniería Eléctrica"},
    )
    return [i for i in GradosSpider().parse_asignaturas(resp) if isinstance(i, dict)]


def test_electrica_marca_las_no_ofertadas_y_limpia_el_nombre():
    items = _asignaturas_electrica()
    no_ofertadas = [i for i in items if not i["ofertada"]]
    assert len(no_ofertadas) == 4
    # El estado no debe quedar pegado al nombre.
    assert all("ofertada" not in i["nombre"].lower() for i in no_ofertadas)
    topo = _por_nombre(items, "Topografía y construcción")
    assert topo is not None
    assert topo["ofertada"] is False


def test_electrica_las_demas_se_ofertan():
    items = _asignaturas_electrica()
    ofertadas = [i for i in items if i["ofertada"]]
    assert len(ofertadas) == len(items) - 4


# --- IT-05 (menciones multivalor con barra): caso real de Mecánica ---
#
# En Mecánica y Eléctrica, una asignatura de dos menciones viene en un solo
# párrafo separado por "/", frente a los <p> separados de Informática. Ambas
# formas deben normalizarse a una lista plana.

def test_mecanica_divide_menciones_separadas_por_barra():
    resp = _respuesta(
        "tabla_mecanica.html",
        url="https://eps.ujaen.es/grados/grado-en-ingenieria-mecanica/asignaturas-y-profesorado",
        meta={"nombre": "Grado en Ingeniería Mecánica"},
    )
    items = [i for i in GradosSpider().parse_asignaturas(resp) if isinstance(i, dict)]
    integridad = next(i for i in items if i["codigo"] == "13413009")
    assert integridad["menciones"] == [
        "Ingeniería y fabricación mecánica",
        "Construcción industrial",
    ]


def test_electrica_separa_las_menciones_combinadas_con_barra():
    # Algunas optativas pertenecen a dos menciones escritas como "A / B".
    items = _asignaturas_electrica()
    protecciones = _por_nombre(items, "Protecciones eléctricas")
    assert protecciones is not None
    assert set(protecciones["menciones"]) == {
        "Sistemas Eléctricos",
        "Instalaciones Eléctricas",
    }


# --- IT-06: contenido de la guía docente (parse_guia) ---
#
# La web declara charset=UTF-8 en el <meta>, pero el servidor real envía la
# cabecera HTTP como ISO-8859-1/cp1252 (verificado contra una petición real
# a una guía en producción). Scrapy prioriza la cabecera HTTP y decodifica
# bien sin intervención; el problema es solo de las fixtures locales, que no
# traen cabecera HTTP, así que aquí se declara encoding="cp1252" explícito
# para reproducir lo que ocurre en una petición real.

_URL_GUIA = "https://uvirtual.ujaen.es/pub/.../guia_es.html"


def _guia(fixture, codigo, nombre, grado):
    resp = HtmlResponse(
        url=_URL_GUIA,
        body=(FIXTURES / fixture).read_bytes(),
        encoding="cp1252",
        request=Request(_URL_GUIA, meta={
            "codigo": codigo, "nombre": nombre, "grado": grado,
        }),
    )
    return next(GradosSpider().parse_guia(resp))


def test_extrae_resumen_y_temario_de_una_guia_real():
    # Matemáticas I de Organización Industrial (13011009).
    item = _guia(
        "guia_matematicas_oi.html", "13011009", "Matemáticas I",
        "Grado en Ingeniería de Organización Industrial",
    )
    assert item["fallback"] is False
    assert "sistemas de ecuaciones lineales" in item["temario"].lower()
    assert len(item["resumen"]) > 100
    assert "evaluacion" not in item
    assert "bibliografia" not in item


def test_decodifica_los_acentos_correctamente():
    # Regresión directa del hallazgo de codificación: la web dice UTF-8 en
    # el <meta> pero el servidor envía ISO-8859-1/cp1252 por HTTP. Sin el
    # encoding explícito, este texto saldría con mojibake ("Naci�n").
    item = _guia(
        "guia_matematicas_oi.html", "13011009", "Matemáticas I",
        "Grado en Ingeniería de Organización Industrial",
    )
    texto_completo = item["resumen"] + item["temario"]
    assert "�" not in texto_completo
    assert "diagonalización" in texto_completo.lower()


def test_misma_asignatura_en_otro_grado_extrae_igual():
    # Matemáticas I de Eléctrica (13511009): FB compartida con Organización
    # Industrial, misma guía, mismo contenido real.
    oi = _guia(
        "guia_matematicas_oi.html", "13011009", "x", "x",
    )
    electrica = _guia(
        "guia_matematicas_electrica.html", "13511009", "x", "x",
    )
    assert oi["temario"] == electrica["temario"]


def test_extrae_guia_real_de_iayc():
    item = _guia(
        "guia_metodos_numericos_iayc.html", "15711001",
        "Análisis y métodos numéricos",
        "Grado en Inteligencia Artificial y Ciberseguridad",
    )
    assert item["fallback"] is False
    assert len(item["temario"]) > 100


def test_descarta_el_marcador_de_campo_sin_contenido():
    # Caso real documentado: la guía del TFG de Informática (13316001,
    # https://uvirtual.ujaen.es/pub/es/informacionacademica/
    # catalogofichasdocentesasignaturas/p/2025-26/4/133A/13316001/es/
    # 2025-26-13316001_es.html) tiene "Breve resumen: -" y
    # "Competencias: -": un guion suelto marca "sin contenido". Se aísla el
    # patrón exacto observado en un fragmento mínimo, en vez de una fixture
    # completa inventada.
    from tfg_uja.grados_spider import GradosSpider
    html = (
        '<div id="resumen">'
        '<div class="fdoca_valor_cuadro_ambito">Contenido real</div>'
        '<div class="fdoca_valor_cuadro_ambito">-</div>'
        "</div>"
    )
    resp = HtmlResponse(url=_URL_GUIA, body=html.encode("utf-8"), encoding="utf-8")
    texto = GradosSpider._contenido_seccion(resp, "resumen")
    assert texto == "Contenido real"
    assert "-" not in texto


def test_usa_el_fallback_cuando_la_estructura_no_aparece():
    # Fixture CONSTRUIDA (no real, ver comentario en el propio HTML): ninguna
    # de las guías reales disponibles dispara el fallback, así que se ejercita
    # esta rama con una estructura de ids válida pero sin contenido, para no
    # dejar el camino de código sin probar. Documentado explícitamente como
    # caso de prueba, no como dato real de la EPSJ.
    item = _guia(
        "guia_estructura_rota.html", "X000", "Asignatura de prueba", "Grado de prueba",
    )
    assert item["fallback"] is True
    assert item["resumen"] == ""
    assert item["temario"] == ""
    assert "cuerpo_general" in item
    assert len(item["cuerpo_general"]) > 0


def test_el_fallback_excluye_profesorado_y_clausulas():
    item = _guia(
        "guia_estructura_rota.html", "X000", "Asignatura de prueba", "Grado de prueba",
    )
    cuerpo = item["cuerpo_general"].lower()
    assert "profesor" not in cuerpo
    assert "rgpd" not in cuerpo


def test_encola_una_peticion_a_la_guia_por_cada_asignatura_con_guia():
    resp = _respuesta("tabla_asignaturas.html", url=_URL_ASIG, meta=_META_ASIG)
    salida = list(GradosSpider().parse_asignaturas(resp))
    items = [i for i in salida if isinstance(i, dict)]
    requests = [i for i in salida if isinstance(i, scrapy.Request)]
    con_guia = [i for i in items if i["tiene_guia"]]
    assert len(requests) == len(con_guia)
    assert all(r.callback.__name__ == "parse_guia" for r in requests)
    peticion = next(r for r in requests if r.meta["codigo"] == "13311008")
    assert peticion.meta["nombre"] == "Matemática discreta"


# --- IT-07: salidas profesionales (parse_salidas) ---
#
# Las salidas viven en una lista dentro de .field--name-body. La fixture
# salidas_no_encontrada.html es una página 404 REAL de la EPSJ (resultado de
# una URL de salidas inexistente), útil para verificar el comportamiento
# robusto cuando no hay bloque de salidas.

def _salidas(fixture, nombre):
    resp = HtmlResponse(
        url="https://eps.ujaen.es/grados/x/salidas-profesionales",
        body=(FIXTURES / fixture).read_bytes(),
        encoding="utf-8",
        request=Request("https://eps.ujaen.es/grados/x/salidas-profesionales",
                        meta={"nombre": nombre}),
    )
    return list(GradosSpider().parse_salidas(resp))


def test_extrae_las_salidas_profesionales_de_un_grado():
    items = _salidas("salidas_informatica.html", "Grado en Ingeniería Informática")
    assert len(items) == 1
    item = items[0]
    assert item["tipo"] == "salidas"
    assert item["grado"] == "Grado en Ingeniería Informática"
    lineas = item["texto"].split("\n")
    assert len(lineas) == 16
    assert lineas[0] == "- Programador de aplicaciones."
    assert all(linea.startswith("- ") for linea in lineas)


def test_no_emite_item_si_no_hay_bloque_de_salidas():
    # Página 404 real: no hay .field--name-body, no se emite item.
    items = _salidas("salidas_no_encontrada.html", "Grado en Ingeniería Eléctrica")
    assert items == []


def test_portada_encola_el_rastreo_de_salidas():
    meta = {"nombre": "Grado en Ingeniería Informática"}
    salida = list(GradosSpider().parse_portada(
        _respuesta("portada_grado.html", meta=meta)))
    requests = [r for r in salida if isinstance(r, scrapy.Request)]
    urls_salidas = [r for r in requests if "salidas-profesionales" in r.url]
    assert len(urls_salidas) == 1
    assert urls_salidas[0].callback.__name__ == "parse_salidas"

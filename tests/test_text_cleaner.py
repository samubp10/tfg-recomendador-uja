"""Pruebas del limpiador de texto (IT-02)."""

from tfg_uja.text_cleaner import limpiar_texto, reparar_url


# --- limpiar_texto ---

def test_sustituye_espacios_duros():
    assert limpiar_texto("Matem\xa0tica discreta") == "Matem tica discreta"


def test_elimina_caracteres_de_ancho_cero():
    assert limpiar_texto("Álgebra\u200b") == "Álgebra"


def test_colapsa_espacios_multiples():
    assert limpiar_texto("Bases   de    datos") == "Bases de datos"


def test_quita_espacios_al_principio_y_al_final():
    assert limpiar_texto("  Estadística  ") == "Estadística"


def test_colapsa_saltos_de_linea():
    assert limpiar_texto("Sistemas\noperativos") == "Sistemas operativos"


def test_cadena_vacia_o_none_devuelve_cadena_vacia():
    assert limpiar_texto("") == ""
    assert limpiar_texto(None) == ""


# --- reparar_url: casos reales encontrados en la tabla de asignaturas ---

def test_repara_url_con_sufijo_html_repetido():
    rota = "https://uvirtual.ujaen.es/.../2025-26-13312013_es.htmles.html"
    reparada = "https://uvirtual.ujaen.es/.../2025-26-13312013_es.html"
    assert reparar_url(rota) == reparada


def test_repara_url_con_codigo_duplicado():
    rota = "https://uvirtual.ujaen.es/.../2025-26-13312025_es.html13312025_es.html"
    reparada = "https://uvirtual.ujaen.es/.../2025-26-13312025_es.html"
    assert reparar_url(rota) == reparada


def test_repara_url_con_fragmento_suelto():
    rota = "https://uvirtual.ujaen.es/.../2025-26-13312032_es.html4-13312032_es.html"
    reparada = "https://uvirtual.ujaen.es/.../2025-26-13312032_es.html"
    assert reparar_url(rota) == reparada


def test_no_toca_una_url_ya_correcta():
    correcta = "https://uvirtual.ujaen.es/.../2025-26-13311001_es.html"
    assert reparar_url(correcta) == correcta


def test_url_vacia_o_none_no_rompe():
    assert reparar_url("") == ""
    assert reparar_url(None) is None


# --- quitar_nota_al_pie: caso real "Prácticas externas *" ---

def test_quita_el_asterisco_de_nota_al_pie():
    from tfg_uja.text_cleaner import quitar_nota_al_pie
    assert quitar_nota_al_pie("Prácticas externas *") == "Prácticas externas"


def test_no_toca_un_nombre_sin_asterisco():
    from tfg_uja.text_cleaner import quitar_nota_al_pie
    assert quitar_nota_al_pie("Cálculo") == "Cálculo"


def test_nota_al_pie_con_vacio_o_none_no_rompe():
    from tfg_uja.text_cleaner import quitar_nota_al_pie
    assert quitar_nota_al_pie("") == ""
    assert quitar_nota_al_pie(None) is None


# --- separar_oferta: caso real "(No ofertada en 2025/26)" ---

def test_separa_la_marca_de_no_ofertada():
    from tfg_uja.text_cleaner import separar_oferta
    nombre, ofertada = separar_oferta("Métodos cuantitativos avanzados (No ofertada en 2025/26)")
    assert nombre == "Métodos cuantitativos avanzados"
    assert ofertada is False


def test_una_asignatura_normal_se_oferta():
    from tfg_uja.text_cleaner import separar_oferta
    nombre, ofertada = separar_oferta("Cálculo")
    assert nombre == "Cálculo"
    assert ofertada is True


def test_no_toca_un_parentesis_legitimo():
    from tfg_uja.text_cleaner import separar_oferta
    # Un paréntesis que no sea la marca de no ofertada no debe alterarse.
    nombre, ofertada = separar_oferta("Química (plan antiguo)")
    assert nombre == "Química (plan antiguo)"
    assert ofertada is True


def test_separar_oferta_con_vacio_o_none():
    from tfg_uja.text_cleaner import separar_oferta
    assert separar_oferta("") == ("", True)
    assert separar_oferta(None) == (None, True)

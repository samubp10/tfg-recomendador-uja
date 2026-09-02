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


def test_reparar_url_deja_intacta_la_que_no_termina_en_html():
    """Lo que no lleva ".html" no se toca: no hay nada duplicado que cortar.

    La reparación existe porque la fuente concatena la URL consigo misma
    después del ".html". Una URL sin esa extensión --- las de las guías en PDF,
    por ejemplo --- no puede tener ese defecto, y recortarla por si acaso la
    rompería.
    """
    from tfg_uja.text_cleaner import reparar_url

    pdf = "https://eps.ujaen.es/guia/13312001"
    assert reparar_url(pdf) == pdf


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

    nombre, ofertada = separar_oferta(
        "Métodos cuantitativos avanzados (No ofertada en 2025/26)"
    )
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


# El «Syllabus» que la fuente añadió en 2026-27 se trataba aquí, con un patrón
# que borraba ese rótulo del final del nombre (IT-93). Desde IT-96 el nombre se
# toma del enlace a la guía, así que ya no hay nada que borrar: cualquier enlace
# añadido a la celda queda fuera por construcción, se llame como se llame. Las
# pruebas de esa regresión viven ahora en test_grados_spider.py, que es donde
# está la decisión.


# --- normalizar y palabras (IT-37) ---


def test_normalizar_quita_tildes_y_mayusculas():
    from tfg_uja.text_cleaner import normalizar

    assert normalizar("Ingeniería Informática") == "ingenieria informatica"


def test_normalizar_colapsa_los_espacios():
    from tfg_uja.text_cleaner import normalizar

    assert normalizar("  Grado   en\nMecánica ") == "grado en mecanica"


def test_palabras_descarta_los_signos():
    """Lo que escribe un usuario lleva interrogaciones y comas, no solo letras."""
    from tfg_uja.text_cleaner import palabras

    assert palabras("¿Informática?, ¡sí!") == {"informatica", "si"}


def test_palabras_no_repite():
    from tfg_uja.text_cleaner import palabras

    assert palabras("grado grado GRADO") == {"grado"}


def test_palabras_de_un_texto_vacio():
    from tfg_uja.text_cleaner import palabras

    assert palabras("") == set()


def test_palabras_descarta_lo_que_es_solo_signos():
    """«—» y «...» no son palabras y colarían como cadenas vacías."""
    from tfg_uja.text_cleaner import palabras

    assert palabras("hola — ...") == {"hola"}


# ------------------------------------------- IT-137: una sola normalizacion


def test_normalizar_rotulo_colapsa_los_espacios_interiores():
    """Es la diferencia que separaba las dos copias que había.

    La del rastreador solo recortaba los extremos y la del fragmentador
    colapsaba. Se conserva la que colapsa.
    """
    from tfg_uja.text_cleaner import normalizar_rotulo

    assert normalizar_rotulo("  Prácticas   externas  ") == "practicas externas"


def test_normalizar_rotulo_y_normalizar_no_son_la_misma_funcion():
    """Regresión del riesgo de fusionarlas por parecerse.

    La de rótulos pasa por ASCII, así que borra lo que no tiene equivalente;
    la de texto libre solo descarta las marcas diacríticas y lo conserva. Esa
    diferencia no importa en los nombres de la fuente y sí en lo que escribe
    una persona, así que las dos tienen que seguir existiendo.
    """
    from tfg_uja.text_cleaner import normalizar, normalizar_rotulo

    assert normalizar_rotulo("Ingeniería — 60 €") == "ingenieria 60"
    assert normalizar("Ingeniería — 60 €") == "ingenieria — 60 €"


def test_las_dos_copias_retiradas_daban_lo_mismo_sobre_los_nombres_reales():
    """Caracterización que hizo segura la unificación (IT-137).

    Se comprueba contra las dos implementaciones que había, escritas aquí tal
    como estaban, sobre los nombres que de verdad maneja el sistema. Si algún
    día divergieran, esta prueba lo dice antes de que cambie el corpus.
    """
    import unicodedata

    from tfg_uja.text_cleaner import normalizar_rotulo

    def como_el_rastreador(texto: str) -> str:
        sin = unicodedata.normalize("NFKD", texto)
        return sin.encode("ascii", "ignore").decode("ascii").strip().lower()

    reales = [
        "Grado en Ingeniería Informática",
        "Doble Grado en Ingeniería Eléctrica y Electrónica Industrial",
        "Grado en Ingeniería Geomática y Topográfica (en extinción)",
        "Grado en Ingeniería Geomática y Topográfica (plan 2025)",
        "MATEMÁTICAS I",
        "Créditos ECTS",
        "Carácter",
        "Mención",
        "Común a todas las menciones",
        "TRABAJO FIN DE GRADO",
    ]

    for nombre in reales:
        assert normalizar_rotulo(nombre) == como_el_rastreador(nombre), nombre

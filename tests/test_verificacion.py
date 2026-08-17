"""Pruebas de las comprobaciones deterministas de la respuesta (IT-35).

Los casos no son inventados: salen de las respuestas reales que dieron gemma3
y mistral-7b los días 16 y 17/08/2026, que están recogidas en las sesiones de
prueba. Una comprobación calibrada con texto inventado no reconocería la forma
en que fallan de verdad los modelos.
"""

from __future__ import annotations

from tfg_uja.verificacion import (
    cotejar_listado,
    elementos_de_lista,
    titulaciones_inventadas,
    titulaciones_nombradas,
)

CATALOGO = [
    "Grado en Ingeniería Informática",
    "Grado en Ingeniería Eléctrica",
    "Grado en Ingeniería Geomática y Topográfica (plan 2025)",
    "Doble Grado en Ingeniería Eléctrica y Mecánica",
]


# --- Titulaciones ---


def test_reconoce_las_titulaciones_que_nombra_una_respuesta():
    texto = (
        "Te encajarían el Grado en Ingeniería Eléctrica y también el "
        "Doble Grado en Ingeniería Eléctrica y Mecánica."
    )
    assert titulaciones_nombradas(texto) == {
        "Grado en Ingeniería Eléctrica",
        "Doble Grado en Ingeniería Eléctrica y Mecánica",
    }


def test_caza_las_dos_titulaciones_inventadas_del_caso_real():
    """El caso del 16/08/2026, literal.

    A un estudiante interesado en electricidad le recomendó seis titulaciones.
    «Grado en Ingeniería de Energía» y «Grado en Ingeniería Ambiental» no
    existen en la EPSJ, y ninguna estaba en el contexto recuperado.
    """
    texto = (
        "Podrías estudiar el Grado en Ingeniería Eléctrica, el "
        "Grado en Ingeniería de Energía o el Grado en Ingeniería Ambiental."
    )
    assert titulaciones_inventadas(texto, CATALOGO) == {
        "Grado en Ingeniería de Energía",
        "Grado en Ingeniería Ambiental",
    }


def test_recortar_el_nombre_oficial_no_es_inventarselo():
    """La fuente llama a una «Geomática y Topográfica (plan 2025)».

    Ningún modelo escribe eso entero, y contarlo como invención convertiría la
    métrica en un detector de verbosidad.
    """
    texto = "El Grado en Ingeniería Geomática es de la rama industrial."
    assert titulaciones_inventadas(texto, CATALOGO) == set()


def test_una_respuesta_sin_titulaciones_no_inventa_ninguna():
    assert titulaciones_inventadas("Tiene 6 créditos.", CATALOGO) == set()


# --- Listados ---


def test_extrae_los_elementos_con_las_tres_vinetas():
    texto = "- Álgebra\n* Cálculo\n1. Física\n2) Química"
    assert elementos_de_lista(texto) == ["Álgebra", "Cálculo", "Física", "Química"]


def test_los_creditos_no_forman_parte_del_nombre():
    """Los modelos los escriben de varias formas y todas sobran para cotejar."""
    texto = "- Álgebra (6 ECTS)\n- Cálculo - 6 créditos\n- Física: 6 ECTS"
    assert elementos_de_lista(texto) == ["Álgebra", "Cálculo", "Física"]


def test_el_texto_de_alrededor_no_entra_en_la_lista():
    texto = "Estas son las asignaturas:\n\n- Álgebra\n\nEspero que te sirva."
    assert elementos_de_lista(texto) == ["Álgebra"]


def test_un_listado_perfecto_puntua_uno_y_uno():
    texto = "- Álgebra\n- Cálculo\n- Física"
    esperadas = {"Álgebra", "Cálculo", "Física"}
    precision, cobertura, inventadas, omitidas = cotejar_listado(
        texto, esperadas, esperadas
    )
    assert (precision, cobertura) == (1.0, 1.0)
    assert not inventadas and not omitidas


def test_dejarse_asignaturas_baja_la_cobertura_y_no_la_precision():
    """El fallo real del 16/08: enumeró once de las cincuenta obligatorias.

    Ninguna era falsa, así que una métrica de solo precisión lo habría dado por
    bueno.
    """
    texto = "- Álgebra\n- Cálculo"
    esperadas = {"Álgebra", "Cálculo", "Física", "Química"}
    precision, cobertura, inventadas, omitidas = cotejar_listado(
        texto, esperadas, esperadas
    )
    assert precision == 1.0
    assert cobertura == 0.5
    assert omitidas == {"fisica", "quimica"}


def test_inventarse_una_asignatura_baja_la_precision():
    texto = "- Álgebra\n- Programación cuántica avanzada"
    esperadas = {"Álgebra", "Cálculo"}
    precision, _, inventadas, _ = cotejar_listado(
        texto, esperadas, {"Álgebra", "Cálculo"}
    )
    assert precision == 0.5
    assert inventadas == {"programacion cuantica avanzada"}


def test_una_asignatura_de_otra_titulacion_no_cuenta_como_inventada():
    """Existe en la EPSJ, así que el fallo es de atribución y no de invención.

    Son dos defectos distintos y mezclarlos haría ilegible la comparación: uno
    se corrige con el filtro y el otro no se corrige con nada.
    """
    texto = "- Álgebra\n- Topografía"
    precision, cobertura, inventadas, _ = cotejar_listado(
        texto, {"Álgebra"}, {"Álgebra", "Topografía"}
    )
    assert inventadas == set()
    assert precision == 1.0
    assert cobertura == 1.0


def test_no_enumerar_nada_no_es_acertar():
    """Un modelo que contesta en prosa «son cincuenta» no ha listado ninguna."""
    precision, cobertura, _, omitidas = cotejar_listado(
        "El grado tiene cincuenta asignaturas obligatorias.", {"Álgebra"}, {"Álgebra"}
    )
    assert precision == 0.0
    assert cobertura == 0.0
    assert omitidas == {"algebra"}


# --- Enumeración en prosa (calibrado contra la sesión del 17/08/2026) ---

#: Fragmento literal de la respuesta de mistral-7b a «¿qué asignaturas
#: optativas ofrece Ingeniería Informática?». Las enumeró las diecisiete en
#: prosa, sin una sola viñeta: un extractor que solo mirase viñetas habría
#: contado cero y puntuado 0,0 una respuesta correcta.
_EN_PROSA = (
    "Las asignaturas optativas del Grado en Ingeniería Informática son 17, "
    "incluyendo Algoritmos geométricos (6 ECTS), Desarrollo de videojuegos "
    "(6 ECTS), Minería web (6 ECTS) y Web semántica y social (6 ECTS)."
)


def test_una_enumeracion_en_prosa_tambien_se_reconoce():
    elementos = elementos_de_lista(_EN_PROSA)
    assert len(elementos) == 4
    assert elementos[-1] == "Web semántica y social"


def test_lo_que_introduce_el_nombre_no_lo_convierte_en_inventado():
    """«incluyendo Algoritmos geométricos» es el modelo redactando."""
    corpus = {
        "Algoritmos geométricos",
        "Desarrollo de videojuegos",
        "Minería web",
        "Web semántica y social",
    }
    precision, cobertura, inventadas, _ = cotejar_listado(_EN_PROSA, corpus, corpus)
    assert inventadas == set()
    assert (precision, cobertura) == (1.0, 1.0)


def test_la_cobertura_no_premia_un_formato_sobre_otro():
    """En prosa y en viñetas, la misma respuesta tiene que puntuar igual."""
    corpus = {"Minería web", "Desarrollo de videojuegos"}
    prosa = "Son Minería web y Desarrollo de videojuegos."
    vinetas = "- Minería web\n- Desarrollo de videojuegos"
    assert cotejar_listado(prosa, corpus, corpus)[1] == 1.0
    assert cotejar_listado(vinetas, corpus, corpus)[1] == 1.0

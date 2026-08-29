"""Pruebas de las comprobaciones deterministas de la respuesta (IT-35).

Los casos no son inventados: salen de las respuestas reales que dieron gemma3
y mistral-7b los días 16 y 17/08/2026, que están recogidas en las sesiones de
prueba. Una comprobación calibrada con texto inventado no reconocería la forma
en que fallan de verdad los modelos.
"""

from __future__ import annotations

import json
from pathlib import Path

from tfg_uja.verificacion import (
    Atributos,
    atributos_del_contexto,
    corregir_atributos,
    cotejar_listado,
    elementos_de_lista,
    nucleo,
    sin_tipo_de_estudios,
    titulaciones_inventadas,
    titulaciones_nombradas,
)

FIXTURES = Path(__file__).parent / "fixtures"

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


def test_no_enumerar_nada_deja_la_precision_sin_medir_y_lo_caza_la_cobertura():
    """Contestar «son cincuenta» sin listarlas sigue siendo un fallo.

    Lo que cambia es quién lo caza. La precisión no vale cero, no existe: no se
    ha encontrado nada falso porque no se ha enumerado nada. Quien suspende la
    respuesta es la cobertura, que se mide sobre el texto entero y no depende
    de que se usen viñetas.
    """
    precision, cobertura, _, omitidas = cotejar_listado(
        "El grado tiene cincuenta asignaturas obligatorias.", {"Álgebra"}, {"Álgebra"}
    )
    assert precision is None
    assert cobertura == 0.0
    assert omitidas == {"algebra"}


def test_una_respuesta_correcta_en_prosa_no_puntua_cero():
    """Regresión de G-MEN-001, del cribado del 22/08/2026.

    `gemma3:12b` nombró las tres menciones correctas en prosa y la métrica le
    puso precisión 0,000 con cero invenciones y cero omisiones. Puntuar así
    ordenaba a los modelos por su estilo de redacción y no por su veracidad.
    """
    texto = (
        "El Grado en Ingeniería Electrónica Industrial tiene tres menciones: "
        "Automática, Sistemas electrónicos y Sistemas fotovoltaicos."
    )
    esperadas = {"Automática", "Sistemas electrónicos", "Sistemas fotovoltaicos"}
    precision, cobertura, inventadas, omitidas = cotejar_listado(
        texto, esperadas, esperadas
    )
    assert precision is None
    assert cobertura == 1.0
    assert not inventadas and not omitidas


def test_un_nombre_partido_por_un_punto_se_cuenta_inventado():
    """Límite conocido del cotejo, declarado a propósito (G-MEN-011).

    «Smart Grids. Redes Eléctricas Inteligentes» citada por su segunda mitad se
    cuenta como inventada aunque exista. Es el único nombre así de todo el
    corpus, de modo que una regla de alias se escribiría para un caso único.
    Esta prueba no celebra el comportamiento: lo fija, para que quien lo cambie
    sepa que era una decisión y no un descuido.
    """
    corpus = {"Smart Grids. Redes Eléctricas Inteligentes"}
    precision, _, inventadas, _ = cotejar_listado(
        "- Redes Eléctricas Inteligentes", corpus, corpus
    )
    assert precision == 0.0
    assert inventadas == {"redes electricas inteligentes"}


def test_el_nombre_partido_entero_si_se_reconoce():
    """Contrapartida de la anterior: citado entero, casa.

    Sin ella, la limitación podría confundirse con que el cotejo no reconoce
    ese nombre de ninguna forma.
    """
    corpus = {"Smart Grids. Redes Eléctricas Inteligentes"}
    precision, cobertura, inventadas, _ = cotejar_listado(
        "- Smart Grids. Redes Eléctricas Inteligentes", corpus, corpus
    )
    assert precision == 1.0
    assert cobertura == 1.0
    assert not inventadas


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


# --- El formato del modelo no puede cambiar la nota (18/08/2026) ---

#: Respuesta literal de ministral-3:3b, correcta y en negrita. Es el caso que
#: destapó el fallo: la negrita se colaba dentro del nombre.
_EN_NEGRITA = (
    "En el **primer curso del Grado en Ingeniería Informática**, "
    "las asignaturas obligatorias son:\n\n"
    "- **Matemática discreta** (6 ECTS).\n"
    "- **Álgebra** (6 ECTS).\n"
    "- **Programación orientada a objetos** (6 ECTS).\n"
)

#: Respuesta literal de gemma3, correcta, con un rótulo encabezando la sublista.
_CON_ROTULO = (
    "Las asignaturas del Grado en Ingeniería Informática en primer curso son:\n\n"
    "*   Primer curso:\n"
    "    *   Matemática discreta (6 ECTS)\n"
    "    *   Álgebra (6 ECTS)\n"
    "    *   Programación orientada a objetos (6 ECTS)\n"
)

_TRES = {"Matemática discreta", "Álgebra", "Programación orientada a objetos"}


def test_la_negrita_no_forma_parte_del_nombre():
    """Regresión: «**Álgebra**» no casaba con ninguna asignatura del corpus."""
    assert elementos_de_lista(_EN_NEGRITA) == [
        "Matemática discreta",
        "Álgebra",
        "Programación orientada a objetos",
    ]


def test_una_respuesta_perfecta_en_negrita_no_puntua_cero():
    """Antes puntuaba 0,000 de precisión con las tres asignaturas acertadas."""
    precision, cobertura, inventadas, omitidas = cotejar_listado(
        _EN_NEGRITA, _TRES, _TRES
    )
    assert (inventadas, omitidas) == (set(), set())
    assert (precision, cobertura) == (1.0, 1.0)


def test_un_rotulo_de_sublista_no_es_un_elemento():
    """«Primer curso:» encabeza la lista; contarlo inventaba una asignatura."""
    assert "Primer curso" not in elementos_de_lista(_CON_ROTULO)
    assert len(elementos_de_lista(_CON_ROTULO)) == 3


def test_el_rotulo_no_baja_la_precision_de_una_respuesta_correcta():
    precision, _, inventadas, _ = cotejar_listado(_CON_ROTULO, _TRES, _TRES)
    assert inventadas == set()
    assert precision == 1.0


def test_los_dos_puntos_dentro_del_elemento_siguen_recortando_la_cola():
    """Un elemento que **no** termina en dos puntos conserva su nombre."""
    assert elementos_de_lista("- Álgebra: 6 ECTS") == ["Álgebra"]


def test_la_negrita_tambien_se_quita_en_la_enumeracion_en_prosa():
    """En prosa la negrita también estorba, aunque el nombre llegue con lo que
    lo introducía delante: eso lo absorbe después la comparación por sufijo."""
    texto = "Son **Minería web** (6 ECTS) y **Álgebra** (6 ECTS)."
    assert elementos_de_lista(texto) == ["Son Minería web", "Álgebra"]
    corpus = {"Minería web", "Álgebra"}
    precision, cobertura, inventadas, _ = cotejar_listado(texto, corpus, corpus)
    assert inventadas == set()
    assert (precision, cobertura) == (1.0, 1.0)


# --- El calificador de doble grado (caso real del 18/08/2026) ---

#: Las diez obligatorias de tercer o cuarto curso del Doble Grado en Ingeniería
#: Electrónica Industrial y Mecánica, tal como las publica la fuente: con la
#: sigla de la titulación de la que vienen.
_CON_SIGLA = {
    "AUTOMÁTICA AVANZADA (GIEI)",
    "ELECTROTECNIA AVANZADA (GIEI)",
    "ELECTRÓNICA ANALÓGICA (GIEI)",
}

#: Cómo las enumeró ministral-8b: correctas, completas y sin la sigla.
_SIN_SIGLA = """En el Doble Grado se cursan:
   - Automática Avanzada (6 ECTS).
   - Electrotecnia Avanzada (6 ECTS).
   - Electrónica Analógica (6 ECTS).
"""


def test_la_sigla_del_doble_grado_no_forma_parte_del_nombre():
    assert nucleo("AUTOMÁTICA AVANZADA (GIEI)") == "automatica avanzada"


def test_el_plan_entre_parentesis_tampoco():
    assert (
        nucleo("Grado en Ingeniería Geomática y Topográfica (plan 2025)")
        == "grado en ingenieria geomatica y topografica"
    )


def test_la_abreviatura_de_la_fuente_se_resuelve():
    """La fuente escribe «ING.» en los seis TFG y ningún modelo la copia."""
    assert nucleo("TFG ING. MECÁNICA (GIM)") == "tfg ingenieria mecanica"


def test_un_listado_correcto_sin_la_sigla_no_puntua_cero():
    """Regresión del 18/08/2026.

    Con el calificador puesto en la comparación, esta respuesta ---que enumera
    las tres esperadas, ninguna de más y ninguna de menos--- daba cobertura
    0,000 y las tres contadas como omitidas.
    """
    precision, cobertura, inventadas, omitidas = cotejar_listado(
        _SIN_SIGLA, _CON_SIGLA, _CON_SIGLA
    )
    assert (precision, cobertura) == (1.0, 1.0)
    assert inventadas == set()
    assert omitidas == set()


def test_expandir_la_abreviatura_no_convierte_el_tfg_en_inventado():
    texto = "- TFG Ingeniería Mecánica (12 ECTS)."
    corpus = {"TFG ING. MECÁNICA (GIM)"}
    precision, cobertura, inventadas, _ = cotejar_listado(texto, corpus, corpus)
    assert inventadas == set()
    assert (precision, cobertura) == (1.0, 1.0)


# --- El nombre de la titulación sin la fórmula «Grado en» (G-CAT-001) ---

_CATALOGO_EPSJ = {
    "Grado en Ingeniería Eléctrica",
    "Grado en Ingeniería Mecánica",
    "Doble Grado en Ingeniería Mecánica (Internacional - Schmalkalden)",
}


def test_nombrar_la_titulacion_sin_la_formula_grado_en():
    """Regresión de G-CAT-001.

    El 19/08/2026 «command-r7b» enumeró las doce titulaciones de la EPSJ, las
    doce correctas y ninguna de más, agrupadas bajo dos rótulos que decían
    cuáles eran grados y cuáles dobles. Como escribía «Ingeniería Eléctrica» y
    no «Grado en Ingeniería Eléctrica», la respuesta puntuaba precisión 0,083 y
    cobertura 0,000, con las doce contadas como omitidas. La misma respuesta de
    «granite4.1:8b», con la fórmula puesta, puntuaba 1,000 y 1,000: lo único
    que separaba a las dos eran esas dos palabras.
    """
    respuesta = (
        "Grados:\n"
        "- Ingeniería Eléctrica\n"
        "- Ingeniería Mecánica\n"
        "Dobles grados:\n"
        "- Ingeniería Mecánica (Internacional - Schmalkalden)\n"
    )
    precision, cobertura, inventadas, omitidas = cotejar_listado(
        respuesta, _CATALOGO_EPSJ, _CATALOGO_EPSJ
    )
    assert (precision, cobertura) == (1.0, 1.0)
    assert not inventadas and not omitidas


def test_con_la_formula_puesta_se_compara_con_ella():
    """La corrección no relaja la comparación cuando la respuesta sí la usa."""
    respuesta = (
        "- Grado en Ingeniería Eléctrica\n"
        "- Grado en Ingeniería Mecánica\n"
        "- Doble Grado en Ingeniería Mecánica (Internacional - Schmalkalden)\n"
    )
    precision, cobertura, _, omitidas = cotejar_listado(
        respuesta, _CATALOGO_EPSJ, _CATALOGO_EPSJ
    )
    assert (precision, cobertura) == (1.0, 1.0)
    assert not omitidas


def test_sin_tipo_de_estudios_deja_intacto_lo_que_no_lo_lleva():
    assert sin_tipo_de_estudios("algebra") == "algebra"
    assert sin_tipo_de_estudios("grado en ingenieria electrica") == (
        "ingenieria electrica"
    )
    assert sin_tipo_de_estudios("doble grado en ingenieria mecanica") == (
        "ingenieria mecanica"
    )


def test_abreviar_el_nombre_por_dentro_no_es_inventarlo():
    """Regresión: la barrera retiró una respuesta correcta el 19/08/2026.

    `ministral-8b` recomendó cuatro titulaciones reales y escribió una de
    ellas «Grado en Mecánica». Ningún prefijo casa con «Grado en Ingeniería
    Mecánica», así que contaba como inventada y la respuesta entera se retiró.
    """
    catalogo = [
        "Grado en Ingeniería Mecánica",
        "Grado en Ingeniería Informática",
        "Doble Grado en Ingeniería Mecánica y Organización Industrial",
    ]
    dicho = "Te encaja el Grado en Mecánica, que tiene mucho dibujo técnico."
    assert titulaciones_inventadas(dicho, catalogo) == set()


def test_una_titulacion_que_no_existe_sigue_detectandose():
    """Admitir la abreviatura no puede abrir la mano con lo inventado."""
    catalogo = ["Grado en Ingeniería Mecánica", "Grado en Ingeniería Informática"]
    dicho = "Te recomiendo el Grado en Ingeniería Biomédica y el Grado en Medicina."
    assert titulaciones_inventadas(dicho, catalogo) == {
        "Grado en Ingeniería Biomédica",
        "Grado en Medicina",
    }


def test_el_guion_dentro_del_nombre_no_lo_corta():
    """Regresión: las dos asignaturas del corpus que llevan guion.

    «Interacción persona-ordenador» quedaba en «Interacción persona» y
    «Técnicas de animación 3D y post-procesamiento» en «...y post». Ninguna
    casaba con el corpus, y dos respuestas correctas perdían precisión.
    """
    assert elementos_de_lista("- **Interacción persona-ordenador** (6 ECTS)") == [
        "Interacción persona-ordenador"
    ]
    assert elementos_de_lista(
        "- Técnicas de animación 3D y post-procesamiento (6 ECTS)"
    ) == ["Técnicas de animación 3D y post-procesamiento"]


def test_el_guion_con_espacio_delante_sigue_separando_la_cola():
    """Es la forma en que los modelos escriben los créditos detrás."""
    assert elementos_de_lista("- **Álgebra** - 6 ECTS") == ["Álgebra"]


def test_la_lista_que_factoriza_el_tipo_de_estudios_se_recompone():
    """Regresión: `ministral-8b` enumeró las doce titulaciones correctas así.

    El cotejo devolvió «12 omitidas, 10 de más» sobre una respuesta perfecta,
    porque comparaba «Ingeniería Informática» contra «Grado en Ingeniería
    Informática». Sacar la fórmula fuera de la lista es mejor prosa que
    repetirla doce veces, no un error del modelo.
    """
    respuesta = (
        "En la Escuela puedes estudiar estas titulaciones:\n\n"
        "**Grado en:**\n"
        "- Ingeniería Informática.\n"
        "- Ingeniería Mecánica.\n\n"
        "**Doble Grado en:**\n"
        "- Ingeniería Eléctrica y Mecánica.\n"
    )
    assert elementos_de_lista(respuesta) == [
        "Grado en Ingeniería Informática",
        "Grado en Ingeniería Mecánica",
        "Doble Grado en Ingeniería Eléctrica y Mecánica",
    ]


def test_un_encabezado_de_curso_no_se_antepone_al_nombre():
    """Ahí lo factorizado es el curso, no el principio del nombre."""
    respuesta = "**Primer curso:**\n- Álgebra (6 ECTS)\n- Física I (6 ECTS)"
    assert elementos_de_lista(respuesta) == ["Álgebra", "Física I"]


def test_la_cobertura_cuenta_la_lista_factorizada():
    """La respuesta perfecta al catálogo daba cobertura 0,000.

    Al sacar «Grado en:» a un encabezado, la cadena «Grado en Ingeniería
    Informática» no aparece en ninguna parte del texto, y la cobertura la
    buscaba ahí. Los nombres sí están, recompuestos, entre los elementos.
    """
    respuesta = (
        "En la Escuela puedes estudiar:\n\n"
        "**Grado en:**\n- Ingeniería Informática.\n- Ingeniería Mecánica.\n"
    )
    esperadas = ["Grado en Ingeniería Informática", "Grado en Ingeniería Mecánica"]
    precision, cobertura, inventadas, omitidas = cotejar_listado(
        respuesta, esperadas, set(esperadas)
    )
    assert precision == 1.0
    assert cobertura == 1.0
    assert not inventadas and not omitidas


def test_elementos_en_prosa_sin_ninguna_mayuscula_se_dejan_enteros():
    """Si nada empieza por mayúscula, no hay dónde recortar y se deja tal cual.

    El recorte existe porque el modelo arrastra lo que introducía el nombre
    («incluyendo Algoritmos geométricos»), y se apoya en que en la fuente todo
    nombre de asignatura empieza por mayúscula. Cuando el modelo escribe la
    enumeración entera en minúscula esa pista no está, y adivinar dónde empieza
    el nombre sería inventarse el corte: es preferible devolver de más y que el
    cotejo lo cuente como no encontrado, a devolver un trozo equivocado.
    """
    respuesta = "se cursan álgebra (6 ECTS) y física aplicada (6 créditos)."

    assert elementos_de_lista(respuesta) == [
        "se cursan álgebra",
        "y física aplicada",
    ]


# ------------------------------------------- los atributos de plan (IT-118)
#
# El defecto que da origen a todo esto es real y esta fechado. Preguntado por
# Topografia el 29/08/2026, el sistema contesto:
#
#     **Fotogrametria y teledeteccion III (6 ECTS):** Se imparte en el segundo
#     cuatrimestre.
#
# y el fragmento que se le habia entregado decia, con esas palabras, «Se
# imparte en el primer cuatrimestre de tercer curso». La asignatura existia,
# los creditos eran correctos y las tres barreras de dominio la dejaron pasar,
# porque comprueban identidades y no afirmaciones.
#
# El porque no es que el modelo se inventara un dato de la nada: Fotogrametria
# III tiene UN fragmento (no hay guia publicada) frente a los siete de I y los
# seis de II, y el de II dice literalmente «segundo cuatrimestre». Se lo presto
# el hermano.


def _contexto_real(nombre_parcial: str) -> list[str]:
    """Textos reales del corpus, no cadenas escritas para la ocasion."""
    chunks = json.loads(
        (FIXTURES / "chunks_atributos_real.json").read_text(encoding="utf-8")
    )
    return [c["texto"] for c in chunks if nombre_parcial in c["nombre"]]


def test_el_contexto_se_lee_con_la_plantilla_del_troceador() -> None:
    # El encabezado lo redacta `chunker`, no la fuente, asi que se puede leer
    # sin ambiguedad. Si alguien cambia esa plantilla, esta prueba lo dice
    # antes de que la correccion deje de encontrar nada y falle en silencio.
    atributos = atributos_del_contexto(_contexto_real("Fotogrametría"))

    assert atributos["fotogrametria y teledeteccion iii"] == Atributos(
        cuatrimestre=1, curso=3, ects="6"
    )
    assert atributos["fotogrametria y teledeteccion ii"] == Atributos(
        cuatrimestre=2, curso=2, ects="6"
    )


def test_regresion_el_cuatrimestre_prestado_por_la_asignatura_hermana() -> None:
    # La respuesta literal del 29/08/2026, contra el contexto literal que se le
    # dio. Es el caso que justifica el modulo entero.
    atributos = atributos_del_contexto(_contexto_real("Fotogrametría"))

    corregida, avisos = corregir_atributos(
        "**Fotogrametría y teledetección III (6 ECTS):** Se imparte en el "
        "segundo cuatrimestre.",
        atributos,
    )

    assert "primer cuatrimestre" in corregida
    assert "segundo cuatrimestre" not in corregida
    assert len(avisos) == 1
    assert "primer cuatrimestre" in avisos[0]


def test_una_respuesta_correcta_no_se_toca() -> None:
    # Lo que mas caro sale de un corrector es que corrija de mas: reescribir
    # una respuesta buena es peor que dejar pasar una mala, porque destruye
    # informacion que era cierta.
    atributos = atributos_del_contexto(_contexto_real("Fotogrametría"))
    buena = (
        "**Fotogrametría y teledetección II** se imparte en el segundo "
        "cuatrimestre de segundo curso y son 6 ECTS."
    )

    corregida, avisos = corregir_atributos(buena, atributos)

    assert corregida == buena
    assert avisos == []


def test_un_segmento_con_dos_asignaturas_se_deja_intacto() -> None:
    # El defecto nace de confundir asignaturas de nombre casi igual. Atribuir a
    # ciegas un atributo cuando la frase nombra dos seria cometerlo del reves,
    # asi que ante la duda no se corrige nada.
    atributos = atributos_del_contexto(_contexto_real("Fotogrametría"))
    ambigua = (
        "Tanto **Fotogrametría y teledetección II** como **Fotogrametría y "
        "teledetección III** se imparten en el primer cuatrimestre."
    )

    corregida, avisos = corregir_atributos(ambigua, atributos)

    assert corregida == ambigua
    assert avisos == []


def test_se_corrigen_los_tres_atributos_a_la_vez() -> None:
    atributos = atributos_del_contexto(_contexto_real("Fotogrametría"))

    corregida, avisos = corregir_atributos(
        'La asignatura "Fotogrametría y teledetección III" es obligatoria, de '
        "9 ECTS y se imparte en el primer cuatrimestre de segundo curso.",
        atributos,
    )

    assert "6 ECTS" in corregida
    assert "tercer curso" in corregida
    assert "primer cuatrimestre" in corregida  # este ya estaba bien
    assert len(avisos) == 2


def test_lo_que_el_contexto_no_dice_no_se_corrige() -> None:
    # Fotogrametria de objeto cercano es optativa y la fuente no le publica
    # curso. Decision 9 del proyecto: lo que falta se refleja, no se imputa.
    # Un corrector que rellenara el hueco estaria inventando.
    atributos = atributos_del_contexto(_contexto_real("Fotogrametría"))
    assert atributos["fotogrametria de objeto cercano"].curso is None

    dicho = "**Fotogrametría de objeto cercano** se imparte en el cuarto curso."
    corregida, avisos = corregir_atributos(dicho, atributos)

    assert corregida == dicho
    assert avisos == []


def test_un_contexto_que_se_contradice_no_corrige_a_nadie() -> None:
    # Si dos fragmentos de la misma unidad dijeran cosas distintas, no hay
    # nada con lo que corregir: el contexto no seria una autoridad. Se
    # descarta esa asignatura en vez de elegir uno de los dos al azar.
    atributos = atributos_del_contexto(
        [
            "«Una asignatura», asignatura obligatoria de 6 ECTS del Grado. "
            "Se imparte en el primer cuatrimestre de primer curso.",
            "«Una asignatura», asignatura obligatoria de 6 ECTS del Grado. "
            "Se imparte en el segundo cuatrimestre de primer curso.",
        ]
    )

    assert "una asignatura" not in atributos


def test_sin_contexto_util_el_texto_sale_como_entro() -> None:
    texto = "Se imparte en el segundo cuatrimestre."
    assert corregir_atributos(texto, {}) == (texto, [])


def test_las_asignaturas_sin_curso_publicado_conservan_su_cuatrimestre() -> None:
    # El troceador escribe «el segundo cuatrimestre, sin curso asignado en el
    # plan» cuando la fuente publica uno y no el otro. Hay que leer el
    # cuatrimestre igual, o media coleccion se quedaria sin comprobar.
    atributos = atributos_del_contexto(
        [
            "«Optativa suelta», asignatura optativa de 6 ECTS del Grado. "
            "Se imparte en el segundo cuatrimestre, sin curso asignado en "
            "el plan."
        ]
    )

    assert atributos["optativa suelta"] == Atributos(
        cuatrimestre=2, curso=None, ects="6"
    )


def test_lo_que_no_es_un_encabezado_de_asignatura_se_ignora() -> None:
    # El contexto de un turno trae de todo: salidas profesionales, planes de
    # estudios, catálogo. Solo los encabezados de asignatura enuncian el plan,
    # y son los únicos que empiezan por el nombre entre comillas angulares.
    salidas = (
        "Salidas profesionales del Doble Grado en Ingeniería Eléctrica y "
        "Mecánica: la doble titulación se imparte en el primer cuatrimestre "
        "de primer curso, dice esta frase tramposa a propósito."
    )

    assert atributos_del_contexto([salidas]) == {}


def test_una_asignatura_con_curso_y_sin_cuatrimestre() -> None:
    # No hay ninguna hoy en el corpus, pero `chunker._situacion_en_el_plan`
    # escribe esta forma cuando la fuente publica el curso y no el otro dato.
    # Si algún día la EPSJ publica así ---y ya ha cambiado tres veces este
    # verano--- el curso tiene que seguir comprobándose.
    atributos = atributos_del_contexto(
        [
            "«Trabajo fin de grado», asignatura de TFG de 12 ECTS del Grado. "
            "Se imparte en el cuarto curso."
        ]
    )

    assert atributos["trabajo fin de grado"] == Atributos(
        cuatrimestre=None, curso=4, ects="12"
    )

    corregida, avisos = corregir_atributos(
        "**Trabajo fin de grado** se hace en el tercer curso.", atributos
    )
    assert "cuarto curso" in corregida
    assert len(avisos) == 1


def test_la_asignatura_escrita_como_vineta_pelada_tambien_cuenta() -> None:
    """Es la forma más común, y al principio no se reconocía.

    Medido sobre las 29 respuestas del registro que afirman curso, cuatrimestre
    o ECTS: reconociendo solo la negrita y las comillas, 4 tenían una
    afirmación comprobable; añadiendo la viñeta, 25.
    """
    atributos = atributos_del_contexto(_contexto_real("Fotogrametría"))

    corregida, avisos = corregir_atributos(
        "*   Fotogrametría y teledetección III (6 ECTS) — segundo cuatrimestre",
        atributos,
    )

    assert "primer cuatrimestre" in corregida
    assert len(avisos) == 1


def test_una_vineta_que_encabeza_una_sublista_no_es_una_asignatura() -> None:
    # «* Primer curso:» introduce las asignaturas de debajo. Tomarlo por una
    # asignatura ya produjo una invención en la comprobación de listados, y
    # aquí haría que un rótulo arrastrase los atributos de otra cosa.
    atributos = atributos_del_contexto(_contexto_real("Fotogrametría"))

    encabezado = "*   **Segundo curso:**"
    corregida, avisos = corregir_atributos(encabezado, atributos)

    assert corregida == encabezado
    assert avisos == []

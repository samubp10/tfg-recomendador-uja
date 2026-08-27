"""Pruebas de la decisión de ámbito turno a turno (IT-111).

Lo que se prueba aquí no es que el modelo acierte —eso no depende de este
módulo— sino las dos piezas deterministas que lo rodean: el prompt con el que
se le pregunta y la comprobación contra el catálogo de todo lo que contesta.
Esa comprobación es la que convierte una etiqueta escrita por un modelo en algo
defendible, así que es la que tiene que estar cubierta caso por caso.

El catálogo es el de las doce titulaciones del corpus, el mismo que usan las
pruebas de la conversación. Con un catálogo de juguete no se vería lo que de
verdad complica el módulo: que «Ingeniería Mecánica» está dentro de tres
títulos distintos y que un nombre parcial casa con varios a la vez.

Nada de aquí toca el servidor: el decisor recibe un generador falso por
parámetro, igual que el indexador recibe un incrustador falso.
"""

from __future__ import annotations

import pytest

from tfg_uja.ambito import (
    CAMBIA,
    INTENTOS,
    Decision,
    LARGO_RESPUESTA_ANTERIOR,
    NINGUNA,
    SIGUE,
    TODAS,
    TOPE_DECISION,
    construir_peticion,
    decisor_con_modelo,
    interpretar,
)
from tfg_uja.generador import ErrorDelModelo

CATALOGO = [
    "Doble Grado en Ingeniería Electrónica Industrial y Mecánica",
    "Doble Grado en Ingeniería Eléctrica y Electrónica Industrial",
    "Doble Grado en Ingeniería Eléctrica y Mecánica",
    (
        "Doble Grado en Ingeniería Mecánica (Internacional - University of "
        "Applied Sciences Schmalkalden, Alemania)"
    ),
    "Doble Grado en Ingeniería Mecánica y Organización Industrial",
    "Grado en Ingeniería Electrónica Industrial",
    "Grado en Ingeniería Eléctrica",
    "Grado en Ingeniería Geomática y Topográfica (plan 2025)",
    "Grado en Ingeniería Informática",
    "Grado en Ingeniería Mecánica",
    "Grado en Ingeniería de Organización Industrial",
    "Grado en Inteligencia Artificial y Ciberseguridad",
]

INFORMATICA = "Grado en Ingeniería Informática"
GEOMATICA = "Grado en Ingeniería Geomática y Topográfica (plan 2025)"


# --- Las tres etiquetas fijas ---


@pytest.mark.parametrize(
    "salida",
    ["SIGUE", "sigue", "- SIGUE", "**SIGUE**", "  Sigue.  ", ": SIGUE"],
)
def test_la_etiqueta_sigue_se_reconoce_venga_como_venga(salida):
    """El modelo adorna la etiqueta: la escribe en viñeta, en negrita o suelta.

    Ninguno de esos adornos cambia lo que quiso decir, así que ninguno puede
    tirar la decisión al camino de «no lo entiendo».
    """
    assert interpretar(salida, CATALOGO).clase == SIGUE


@pytest.mark.parametrize(
    "salida",
    ["TODAS", "todas", "- TODAS", "**TODAS**", "Todas.", "— TODAS"],
)
def test_la_etiqueta_todas_se_reconoce_venga_como_venga(salida):
    assert interpretar(salida, CATALOGO).clase == TODAS


@pytest.mark.parametrize(
    "salida",
    ["NINGUNA", "ninguna", "- NINGUNA", "**NINGUNA**", "Ninguna.", ": NINGUNA"],
)
def test_la_etiqueta_ninguna_se_reconoce_venga_como_venga(salida):
    assert interpretar(salida, CATALOGO).clase == NINGUNA


def test_una_etiqueta_fija_no_arrastra_titulaciones():
    """`TODAS` no acota a nada, así que la lista tiene que salir vacía."""
    assert interpretar("TODAS", CATALOGO).titulaciones == []


# --- Resolver nombres contra el catálogo ---


def test_el_nombre_exacto_de_una_titulacion_cambia_el_ambito():
    assert interpretar(INFORMATICA, CATALOGO) == Decision(CAMBIA, [INFORMATICA])


def test_un_nombre_parcial_resuelve_al_del_catalogo():
    """El modelo escribe el nombre corto; el catálogo lo lleva con el plan."""
    decision = interpretar("Ingeniería Geomática y Topográfica", CATALOGO)
    assert decision.titulaciones == [GEOMATICA]


def test_un_nombre_parcial_sin_tildes_tambien_resuelve():
    decision = interpretar("ingenieria geomatica y topografica", CATALOGO)
    assert decision.titulaciones == [GEOMATICA]


def test_un_nombre_parcial_ambiguo_devuelve_todas_las_que_encajan():
    """«Ingeniería Mecánica» está dentro de tres títulos del catálogo.

    Quedarse con uno sería elegir por el modelo cuando el modelo no eligió.
    """
    decision = interpretar("Ingeniería Mecánica", CATALOGO)
    assert decision.titulaciones == [
        CATALOGO[3],
        CATALOGO[4],
        CATALOGO[9],
    ]


def test_las_ambiguas_salen_en_el_orden_del_catalogo():
    """No en el orden en que se encontraron: el catálogo manda."""
    decision = interpretar("Ingeniería Eléctrica", CATALOGO)
    assert decision.titulaciones == [CATALOGO[1], CATALOGO[2], CATALOGO[6]]


def test_dos_titulaciones_separadas_por_punto_y_coma_valen_las_dos():
    linea = f"{INFORMATICA}; {GEOMATICA}"
    assert interpretar(linea, CATALOGO).titulaciones == [GEOMATICA, INFORMATICA]


def test_el_nombre_exacto_no_arrastra_a_los_dobles_que_lo_contienen():
    """Regresión: «Grado en Ingeniería Mecánica» es subcadena de dos dobles.

    Antes se buscaba por igualdad y por subcadena a la vez, así que nombrar dos
    titulaciones enteras acotaba la búsqueda a cuatro. Es el mismo defecto de
    subcadena que `nombrada_por_si_misma` resuelve para las respuestas.
    """
    linea = f"{INFORMATICA}; Grado en Ingeniería Mecánica"
    assert interpretar(linea, CATALOGO).titulaciones == [
        CATALOGO[8],
        CATALOGO[9],
    ]


def test_una_titulacion_repetida_no_sale_dos_veces():
    linea = f"{INFORMATICA}; Ingeniería Informática"
    assert interpretar(linea, CATALOGO).titulaciones == [INFORMATICA]


def test_un_trozo_vacio_entre_puntos_y_comas_no_estorba():
    assert interpretar(f"; {INFORMATICA}", CATALOGO).titulaciones == [INFORMATICA]


def test_una_titulacion_que_no_existe_se_trata_como_ninguna():
    """El caso real: contestó esto a una pregunta ajena.

    Nombrar una titulación que la Escuela no imparte es señal de que el mensaje
    va de otra cosa, no de que siga con la titulación anterior. Por eso no puede
    salir SIGUE de aquí.
    """
    salida = "Grado en Administración y Dirección de Empresas"
    assert interpretar(salida, CATALOGO).clase == NINGUNA


def test_una_palabra_demasiado_corta_no_casa_por_subcadena():
    """«grado» está dentro de las doce: admitirlo no acotaría nada."""
    assert interpretar("grado", CATALOGO).clase == NINGUNA


# --- Lo que no se entiende ---


def test_una_salida_vacia_es_ninguna():
    assert interpretar("", CATALOGO).clase == NINGUNA


def test_una_salida_de_solo_espacios_es_ninguna():
    assert interpretar("   \n \t \n", CATALOGO).clase == NINGUNA


def test_solo_cuenta_la_primera_linea_con_contenido():
    """El modelo se explica después de contestar; esa explicación no decide."""
    salida = "TODAS\nporque no cita ninguna titulación concreta."
    assert interpretar(salida, CATALOGO).clase == TODAS


def test_la_titulacion_se_lee_de_la_primera_linea_y_el_resto_se_ignora():
    salida = f"{INFORMATICA}\nEs la que encaja con lo que pregunta."
    assert interpretar(salida, CATALOGO).titulaciones == [INFORMATICA]


# --- El prompt ---


def test_con_ambito_se_ofrece_la_opcion_de_seguir():
    peticion = construir_peticion("¿y en segundo?", [INFORMATICA], None, CATALOGO)
    assert "- SIGUE" in peticion


def test_con_ambito_la_opcion_de_seguir_nombra_la_titulacion():
    peticion = construir_peticion("¿y en segundo?", [INFORMATICA], None, CATALOGO)
    assert f"se sigue refiriendo al {INFORMATICA}" in peticion


def test_sin_ambito_no_se_ofrece_la_opcion_de_seguir():
    """Sin titulación anterior no hay nada a lo que seguir.

    Ofrecerla invitaba a contestar que sí a un mensaje que no continuaba nada.
    """
    peticion = construir_peticion("hola", [], None, CATALOGO)
    assert "SIGUE" not in peticion


def test_el_catalogo_entero_entra_en_el_prompt():
    """Es lo que hace comprobable la respuesta: solo puede elegir de la lista."""
    peticion = construir_peticion("hola", [], None, CATALOGO)
    assert all(f"- {t}" in peticion for t in CATALOGO)


def test_sin_turno_anterior_no_aparece_el_bloque_del_ultimo_turno():
    peticion = construir_peticion("hola", [], None, CATALOGO)
    assert "ESTUDIANTE:" not in peticion


def test_con_turno_anterior_aparece_lo_que_dijo_el_asistente():
    """Sostener el sujeto cuando lo nombró el asistente y no la pregunta."""
    anterior = ("¿qué grados hay?", f"Uno de ellos es el {INFORMATICA}.")
    peticion = construir_peticion("cuéntame más", [], anterior, CATALOGO)
    assert f"ASISTENTE: «Uno de ellos es el {INFORMATICA}.»" in peticion


def test_la_respuesta_anterior_se_recorta():
    """Entera costaría más fichas que el resto del prompt junto."""
    larga = "a" * (LARGO_RESPUESTA_ANTERIOR + 100)
    peticion = construir_peticion("y más", [], ("¿y?", larga), CATALOGO)
    assert "a" * LARGO_RESPUESTA_ANTERIOR + "»" in peticion


def test_la_pregunta_del_turno_actual_entra_tal_cual():
    peticion = construir_peticion("¿y en segundo?", [], None, CATALOGO)
    assert "el estudiante escribe: «¿y en segundo?»" in peticion


# --- El decisor completo ---


def test_el_decisor_devuelve_la_decision_ya_interpretada():
    decidir = decisor_con_modelo(CATALOGO, "gemma3:12b", lambda *a, **k: "TODAS")
    decision = decidir("¿qué grados hay?", [], None)
    assert decision is not None and decision.clase == TODAS


def test_el_decisor_resuelve_contra_el_catalogo_lo_que_conteste_el_modelo():
    decidir = decisor_con_modelo(
        CATALOGO, "gemma3:12b", lambda *a, **k: "Ingeniería Informática"
    )
    decision = decidir("háblame de programación", [], None)
    assert decision is not None and decision.titulaciones == [INFORMATICA]


def test_un_fallo_del_servidor_no_tumba_el_turno():
    """Devolver None deja a la conversación con su mecanismo determinista.

    Una decisión de ámbito no merece tumbar una consulta que aún se puede
    responder.
    """

    def rompe(*a, **k):
        raise ErrorDelModelo("el servidor respondió 500")

    decidir = decisor_con_modelo(CATALOGO, "gemma3:12b", rompe)
    assert decidir("¿y en segundo?", [INFORMATICA], None) is None


def test_un_tropiezo_del_servidor_se_reintenta_una_vez():
    """Es el caso real del 27/08/2026, y no se ve venir.

    Con dos clientes hablando a la vez con el mismo servidor de inferencia, la
    llamada de decisión se llevó un 500. El sistema cayó al mecanismo
    determinista, la conversación se quedó pegada a la titulación anterior, y
    desde fuera eso es indistinguible del defecto que el decisor viene a
    corregir: un tropiezo pasajero se lee como una regresión.
    """
    llamadas: list[str] = []

    def falla_una_vez(peticion: str, modelo: str, **extra: object) -> str:
        llamadas.append(peticion)
        if len(llamadas) == 1:
            raise ErrorDelModelo("el servidor respondió 500")
        return GEOMATICA

    decidir = decisor_con_modelo(CATALOGO, "gemma3:12b", falla_una_vez)
    decision = decidir("cuéntame de topografía", [INFORMATICA], None)
    assert decision == Decision(CAMBIA, [GEOMATICA])
    assert len(llamadas) == 2


def test_no_se_reintenta_indefinidamente():
    """Si el servidor está caído de verdad, la generación va a fallar detrás.

    Insistir más solo alarga la espera antes de un fallo que va a ocurrir de
    todos modos.
    """
    llamadas: list[str] = []

    def rompe_siempre(peticion: str, modelo: str, **extra: object) -> str:
        llamadas.append(peticion)
        raise ErrorDelModelo("el servidor respondió 500")

    decidir = decisor_con_modelo(CATALOGO, "gemma3:12b", rompe_siempre)
    assert decidir("¿y en segundo?", [INFORMATICA], None) is None
    assert len(llamadas) == INTENTOS


def test_el_decisor_llama_al_modelo_que_se_le_dio_y_con_el_tope_de_decision():
    """El tope va apretado a propósito: la respuesta válida es una línea."""
    recibido: dict[str, object] = {}

    def falso(peticion: str, modelo: str, **extra: object) -> str:
        recibido["modelo"] = modelo
        recibido["tope"] = extra.get("tope")
        return "NINGUNA"

    decidir = decisor_con_modelo(CATALOGO, "gemma3:12b", falso)
    decidir("¿cuál es la capital de Francia?", [], None)
    assert recibido == {"modelo": "gemma3:12b", "tope": TOPE_DECISION}


def test_el_decisor_le_pasa_al_modelo_la_peticion_construida():
    """Lo que se envía tiene que ser el prompt del módulo, no otra cosa."""
    recibido: dict[str, str] = {}

    def falso(peticion: str, modelo: str, **extra: object) -> str:
        recibido["peticion"] = peticion
        return "SIGUE"

    decidir = decisor_con_modelo(CATALOGO, "gemma3:12b", falso)
    decidir("¿y en segundo?", [INFORMATICA], None)
    esperada = construir_peticion("¿y en segundo?", [INFORMATICA], None, CATALOGO)
    assert recibido["peticion"] == esperada

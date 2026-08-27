"""Pruebas de la gestión de la conversación (IT-106).

Las conversaciones de este fichero no son inventadas: son las que fallaron de
verdad al probar el sistema a mano los días 17 y 18/08/2026, con los turnos en
el mismo orden. Una prueba escrita con diálogos imaginarios no reproduce la
forma en que se rompe una conversación real.

El catálogo es el de las doce titulaciones del corpus, tal como lo declara el
índice: las reglas se calculan de él y con un catálogo de juguete no se vería
que «electrónica» sitúa en tres titulaciones a la vez.
"""

from __future__ import annotations

import pytest

from tfg_uja.ambito import CAMBIA, FALLO, NINGUNA, SIGUE, TODAS, Decision, Decisor
from tfg_uja.conversacion import (
    Conversacion,
    contenido,
    recorta_lo_anterior,
    titulaciones_de_la_pregunta,
    titulaciones_de_la_respuesta,
)

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


# --- Reconocer de qué se habla ---


def test_una_pregunta_situa_por_su_nombre_corto():
    assert titulaciones_de_la_pregunta("¿y en informática?", CATALOGO) == [INFORMATICA]


def test_un_nombre_ambiguo_devuelve_todas_las_que_encajan():
    """«electrónica» está en tres titulaciones; elegir una sería inventar.

    El 18/08/2026 el sistema contestó sobre el Grado en Ingeniería Eléctrica a
    «¿y en el grado de electrónica?». Devolver las tres y dejar que el filtro
    las admita todas es lo honesto: la pregunta es ambigua de verdad.
    """
    situadas = titulaciones_de_la_pregunta("Y en el grado de electrónica?", CATALOGO)
    assert len(situadas) == 3
    assert "Grado en Ingeniería Electrónica Industrial" in situadas
    assert "Grado en Ingeniería Eléctrica" not in situadas


@pytest.mark.parametrize(
    "pregunta",
    [
        "¿y en primer año?",
        "¿cuáles son las obligatorias?",
        "¿qué se ve en esa asignatura?",
        "¿y las optativas?",
    ],
)
def test_las_preguntas_de_seguimiento_no_situan_en_ninguna(pregunta):
    assert titulaciones_de_la_pregunta(pregunta, CATALOGO) == []


def test_la_respuesta_situa_solo_con_el_nombre_entero():
    """En la respuesta no valen las palabras sueltas.

    Una respuesta larga menciona de pasada muchos términos; bastaría con que
    dijese «informática» dentro de una frase para cambiar de sujeto.
    """
    suelta = "Esa asignatura es de informática aplicada a la industria."
    entera = "Te encaja el Grado en Ingeniería Informática, que ofrece esa optativa."
    assert titulaciones_de_la_respuesta(suelta, CATALOGO) == []
    assert titulaciones_de_la_respuesta(entera, CATALOGO) == [INFORMATICA]


def test_una_pregunta_elipsis_no_aporta_contenido():
    """«grado» no dice qué se pregunta: está en los doce nombres."""
    assert contenido("Y en el grado de electrónica?", CATALOGO) == set()
    assert contenido("¿Y las optativas?", CATALOGO) == {"optativas"}


# --- Los tres fallos reales ---


def test_el_sujeto_puede_venir_de_la_respuesta_del_asistente():
    """Conversación real del 18/08/2026, turnos 13 y 14 de gemma3:12b.

    El estudiante nunca nombró la titulación: la nombró el asistente al
    recomendársela. Mirando solo las preguntas, el sistema no sabía de qué se
    hablaba y contestó sobre **cinco titulaciones distintas**.
    """
    c = Conversacion(CATALOGO)
    c.anotar(
        "Soy de bachillerato y me gustan los videojuegos",
        "Si te gustan los videojuegos, podrías considerar el Grado en "
        "Ingeniería Informática, que ofrece Desarrollo de videojuegos.",
    )
    consulta = c.preparar("Y qué asignaturas tiene cuarto de esta titulación")
    assert consulta.ambito == [INFORMATICA]
    assert INFORMATICA in consulta.texto


def test_una_pregunta_que_solo_cambia_el_sujeto_recupera_el_predicado():
    """Turno 10 del 18/08/2026: «Y en el grado de electrónica?».

    Nombra una titulación, así que el mecanismo de IT-37 la daba por
    autosuficiente y la incrustaba sola. Pero «electrónica» suelta es un
    **tema**: recuperó guías de asignaturas de electrónica en vez del plan de
    estudios, y el sistema contestó sobre otra titulación.
    """
    c = Conversacion(CATALOGO)
    c.anotar(
        "¿Qué asignaturas se cursan en primer curso del Grado en " "Informática?", "..."
    )
    consulta = c.preparar("Y en el grado de electrónica?")
    assert "asignaturas" in consulta.texto
    assert "primer curso" in consulta.texto
    assert len(consulta.ambito) == 3


def test_al_cambiar_de_sujeto_no_se_arrastra_el_anterior():
    """El predicado se hereda; el sujeto, no. Si no, se mezclarían dos."""
    c = Conversacion(CATALOGO)
    c.anotar("¿Qué asignaturas se cursan en primer curso de Informática?", "...")
    consulta = c.preparar("Y en el grado de electrónica?")
    assert "nformática" not in consulta.texto
    assert INFORMATICA not in consulta.ambito


def test_no_se_arrastra_el_texto_de_una_pregunta_sin_predicado():
    """Regresión del 17/08/2026: seis asignaturas inventadas.

    A «¿Y en el segundo?» se le antepusieron las dos preguntas anteriores
    literalmente, y una era «¿y cuántas de esas son optativas?». La consulta
    quedó dominada por «optativas», el listado de segundo curso no entró en el
    contexto y el modelo rellenó el hueco con seis asignaturas inexistentes.
    """
    c = Conversacion(CATALOGO)
    c.anotar("¿Qué asignaturas se dan en primer curso de Informática?", "...")
    c.anotar("¿Y cuántas de esas son optativas?", "...")
    consulta = c.preparar("¿Y en el segundo?")
    assert "optativas" not in consulta.texto.lower()
    assert consulta.ambito == [INFORMATICA]


def test_una_pregunta_que_se_sostiene_sola_no_se_toca():
    """Arrastrar lo que no hace falta estropea la consulta.

    Medido el 17/08/2026: a «¿cuántas asignaturas tiene el Grado en Ingeniería
    Informática?» se le antepuso una pregunta sobre una asignatura suelta, el
    vector quedó dominado por ella y el sistema respondió que la titulación
    entera «cuenta con una sola asignatura».
    """
    c = Conversacion(CATALOGO)
    c.anotar("¿Qué se ve en Álgebra?", "Matrices y determinantes.")
    consulta = c.preparar(
        "¿Cuántas asignaturas tiene el Grado en Ingeniería Informática?"
    )
    assert consulta.texto == (
        "¿Cuántas asignaturas tiene el Grado en Ingeniería Informática?"
    )


def test_un_ordinal_solo_no_dice_que_se_pregunta():
    """«¿Y en segundo?» dice **cuál**, no **qué**: sigue siendo seguimiento.

    Medido sobre las 39 conversaciones derivadas del dataset: tratándola como
    pregunta que se sostiene sola, la unidad buscada aparecía en el 48 % de los
    casos; heredando el predicado, en el 100 %.
    """
    c = Conversacion(CATALOGO)
    c.anotar(
        "¿Qué asignaturas se cursan en primer curso del Grado en "
        "Ingeniería Informática?",
        "...",
    )
    consulta = c.preparar("¿Y en segundo?")
    assert "asignaturas" in consulta.texto
    assert consulta.ambito == [INFORMATICA]


def test_solo_recorta_la_que_se_refiere_a_lo_anterior():
    """Empezar por «y» no basta para descartarla como predicado.

    Medido el 18/08/2026 sobre la conversación real: «¿Y qué asignaturas tiene
    en primero?» empieza por «y» pero sí plantea tema, y descartarla dejaba a
    la siguiente heredando de «soy de bachillerato y me gustan los
    videojuegos», que no dice nada del plan de estudios.
    """
    assert recorta_lo_anterior("¿Y cuántas de esas son optativas?")
    assert not recorta_lo_anterior("¿Y qué asignaturas tiene en primero?")
    assert not recorta_lo_anterior("Y en el grado de electrónica?")


def test_una_pregunta_que_solo_lleva_ordinal_hereda_el_predicado_original():
    """El predicado que se hereda es el de la última pregunta que abrió tema."""
    c = Conversacion(CATALOGO)
    c.anotar("¿Qué asignaturas se dan en primer curso de Informática?", "...")
    c.anotar("¿Y cuántas de esas son optativas?", "...")
    c.anotar("¿Y en el segundo?", "...")
    consulta = c.preparar("¿Y en el tercero?")
    assert "optativas" not in consulta.texto.lower()
    assert "asignaturas" in consulta.texto


def test_el_ordinal_heredado_lo_sustituye_el_de_la_pregunta():
    """Si la pregunta trae su curso, el del predicado heredado sobra.

    Medido el 18/08/2026 con la conversación real: heredando «¿y qué
    asignaturas tiene en primero?» entera, a «¿y en segundo?» le seguían
    llegando los listados de *primer* curso.
    """
    c = Conversacion(CATALOGO)
    c.anotar("¿Y qué asignaturas tiene en primero del Grado en Informática?", "...")
    consulta = c.preparar("¿Y en segundo?")
    assert "primero" not in consulta.texto.lower()
    assert "asignaturas" in consulta.texto


def test_si_la_pregunta_no_trae_curso_se_conserva_el_heredado():
    """El caso contrario: quitarlo siempre perdía el curso del que se hablaba.

    «¿Y en el grado de electrónica?» no dice curso, así que sigue preguntando
    por el mismo del que se venía hablando.
    """
    c = Conversacion(CATALOGO)
    c.anotar("¿Y qué asignaturas tiene en primero del Grado en Informática?", "...")
    consulta = c.preparar("¿Y en el grado de electrónica?")
    assert "primero" in consulta.texto.lower()


# --- El ámbito ---


def test_sin_conversacion_no_se_acota_nada():
    c = Conversacion(CATALOGO)
    assert c.preparar("¿qué titulaciones hay?").ambito == []


def test_la_titulacion_de_la_pregunta_manda_sobre_la_recordada():
    """Nombrar otra cambia el sujeto, aunque el nombre corto sitúe en varias.

    «Mecánica» está en cinco titulaciones ---la simple y sus cuatro dobles---,
    igual que «electrónica» está en tres. Se devuelven todas y decide el
    filtro; lo que no puede pasar es que se siga hablando de la anterior.
    """
    c = Conversacion(CATALOGO)
    c.anotar("háblame de Informática", "...")
    ambito = c.preparar("¿y en Mecánica?").ambito
    assert INFORMATICA not in ambito
    assert "Grado en Ingeniería Mecánica" in ambito


def test_el_ambito_se_mantiene_mientras_no_se_nombre_otro():
    c = Conversacion(CATALOGO)
    c.anotar("háblame del Grado en Ingeniería Informática", "...")
    c.anotar("¿y las optativas?", "...")
    assert c.preparar("¿y cuántas son?").ambito == [INFORMATICA]


# --- La ventana y el olvido ---


def test_solo_se_conservan_los_ultimos_turnos():
    c = Conversacion(CATALOGO, turnos_recordados=2)
    for i in range(5):
        c.anotar(f"pregunta {i}", "respuesta")
    assert c.preguntas() == ["pregunta 3", "pregunta 4"]


def test_al_recortar_la_ventana_no_se_pierde_el_sujeto():
    """Es la política: lo primero que se descarta son las preguntas viejas.

    El sujeto ocupa unas palabras y es lo único que la pregunta de seguimiento
    necesita de verdad, así que sobrevive a la poda.
    """
    c = Conversacion(CATALOGO, turnos_recordados=1)
    c.anotar("háblame del Grado en Ingeniería Informática", "...")
    c.anotar("¿y las optativas?", "...")
    c.anotar("¿y cuántas son?", "...")
    assert c.preguntas() == ["¿y cuántas son?"]
    assert c.ambito == [INFORMATICA]


def test_las_respuestas_no_se_devuelven_nunca():
    """Una respuesta equivocada no puede ser fuente del turno siguiente.

    Lo que no está en el prompt no se puede copiar. Es la única forma de
    impedirlo que no depende de que el modelo obedezca una instrucción.
    """
    c = Conversacion(CATALOGO)
    c.anotar("una pregunta", "RESPUESTA-EQUIVOCADA-DEL-MODELO")
    assert all("RESPUESTA-EQUIVOCADA" not in p for p in c.preguntas())


def test_una_respuesta_equivocada_no_contamina_la_consulta_siguiente():
    c = Conversacion(CATALOGO)
    c.anotar("¿qué se ve en Álgebra?", "Álgebra tiene 300 ECTS y dura nueve años.")
    consulta = c.preparar("¿y cuántos créditos tiene?")
    assert "300" not in consulta.texto
    assert "nueve" not in consulta.texto


def test_olvidar_deja_la_conversacion_como_recien_creada():
    c = Conversacion(CATALOGO)
    c.anotar("háblame del Grado en Ingeniería Informática", "...")
    c.olvidar()
    assert c.preguntas() == []
    assert c.ambito == []
    assert c.preparar("¿y las optativas?").ambito == []


def test_el_ambito_que_se_devuelve_es_una_copia():
    """Quien lo reciba no puede alterar el estado de la conversación."""
    c = Conversacion(CATALOGO)
    c.anotar("háblame de Informática", "...")
    c.ambito.clear()
    assert c.ambito == [INFORMATICA]


# --- El nombre de un grado simple vive dentro del de los dobles ---


def test_el_doble_grado_no_arrastra_al_simple_que_contiene():
    """Regresión: turno 6 de la sesión del 19/08/2026 con `ministral-8b`.

    La respuesta nombró el Doble Grado en Ingeniería Mecánica y Organización
    Industrial, y el ámbito se quedó también con el Grado en Ingeniería
    Mecánica, que nadie había mencionado. El turno siguiente pidió las
    optativas «de esta carrera» y contestó con las de Mecánica.
    """
    dicho = (
        "Es una asignatura clave en los grados de Ingeniería de Organización "
        "Industrial y Doble Grado en Ingeniería Mecánica y Organización "
        "Industrial."
    )
    assert titulaciones_de_la_respuesta(dicho, CATALOGO) == [
        "Doble Grado en Ingeniería Mecánica y Organización Industrial"
    ]


def test_si_se_nombran_las_dos_se_reconocen_las_dos():
    """El filtro no puede tapar al simple cuando sí se ha escrito aparte."""
    dicho = (
        "Puedes cursar el Grado en Ingeniería Mecánica o, si prefieres las dos "
        "cosas, el Doble Grado en Ingeniería Mecánica y Organización Industrial."
    )
    assert titulaciones_de_la_respuesta(dicho, CATALOGO) == [
        "Doble Grado en Ingeniería Mecánica y Organización Industrial",
        "Grado en Ingeniería Mecánica",
    ]


def test_el_simple_repetido_dentro_del_doble_sigue_sin_contar():
    """Dos menciones del doble arrastran dos del simple, y ninguna es suya."""
    dicho = (
        "El Doble Grado en Ingeniería Mecánica y Organización Industrial dura "
        "cinco cursos. El Doble Grado en Ingeniería Mecánica y Organización "
        "Industrial comparte primero con los dos grados de origen."
    )
    assert titulaciones_de_la_respuesta(dicho, CATALOGO) == [
        "Doble Grado en Ingeniería Mecánica y Organización Industrial"
    ]


# --- El respaldo para la pregunta de seguimiento ---


def test_la_pregunta_de_seguimiento_lleva_respaldo():
    """Regresión medida el 20/08/2026 sobre el índice completo.

    «¿Y cuántas son en total?» tiene palabras de contenido ---«total», «son»---
    así que no se la trata como elíptica y se incrusta tal cual. Su mejor
    fragmento se queda a 0,1722, por encima del suelo, y el sistema respondía
    que no había encontrado información sobre lo que él mismo acababa de
    contestar. El respaldo permite reintentar con el predicado delante.
    """
    c = Conversacion(CATALOGO)
    primera = "¿Qué asignaturas optativas tiene el Grado en Ingeniería Informática?"
    c.anotar(primera, "Tiene diecisiete.")
    consulta = c.preparar("¿Y cuántas son en total?")
    assert consulta.respaldo.startswith(primera)
    assert consulta.respaldo.endswith("¿Y cuántas son en total?")


def test_el_primer_mensaje_no_tiene_respaldo():
    """Sin conversación previa no hay nada con lo que reintentar."""
    c = Conversacion(CATALOGO)
    assert c.preparar("¿Qué titulaciones hay?").respaldo == ""


def test_el_respaldo_no_repite_la_misma_pregunta():
    """Reintentar con lo mismo daría el mismo resultado vacío."""
    c = Conversacion(CATALOGO)
    c.anotar("¿Qué optativas tiene Informática?", "Diecisiete.")
    assert c.preparar("¿Qué optativas tiene Informática?").respaldo == ""


# --- Cuando el ámbito lo decide el modelo ---

MECANICA = "Grado en Ingeniería Mecánica"

#: Con qué se llama al decisor en cada turno: pregunta, ámbito de partida y
#: turno anterior completo.
Llamada = tuple[str, list[str], "tuple[str, str] | None"]


def decisor_de_guion(*decisiones: Decision | None) -> Decisor:
    """Decisor falso que devuelve decisiones escritas de antemano.

    Ninguna prueba de este fichero habla con un modelo: lo que se comprueba
    aquí es qué hace la conversación **con** la decisión, no cómo se toma.

    Args:
        *decisiones: Lo que devuelve, una por turno y en orden. Agotadas, se
            devuelve ``None``, que es lo que significa no haber podido decidir.

    Returns:
        La función que espera :class:`Conversacion`.
    """
    guion = list(decisiones)

    def decidir(
        pregunta: str, ambito: list[str], ultimo_turno: tuple[str, str] | None
    ) -> Decision | None:
        return guion.pop(0) if guion else None

    return decidir


def decisor_espia(llamadas: list[Llamada]) -> Decisor:
    """Decisor falso que anota con qué se le llama y no cambia el ámbito.

    Args:
        llamadas: Lista donde se dejan los argumentos de cada llamada.

    Returns:
        La función que espera :class:`Conversacion`.
    """

    def decidir(
        pregunta: str, ambito: list[str], ultimo_turno: tuple[str, str] | None
    ) -> Decision | None:
        llamadas.append((pregunta, list(ambito), ultimo_turno))
        return Decision(SIGUE, [])

    return decidir


def test_al_cambiar_de_titulacion_se_acota_a_la_nueva():
    """Es lo que el mecanismo determinista no sabe hacer: soltar el sujeto.

    La pregunta del segundo turno no nombra ninguna titulación, así que sin
    decisor se seguiría hablando de la primera para siempre.
    """
    c = Conversacion(
        CATALOGO,
        decisor=decisor_de_guion(
            Decision(CAMBIA, [INFORMATICA]), Decision(CAMBIA, [MECANICA])
        ),
    )
    c.preparar("háblame del Grado en Ingeniería Informática")
    c.anotar("háblame del Grado en Ingeniería Informática", "...")
    consulta = c.preparar("¿y qué optativas tiene?")
    assert consulta.ambito == [MECANICA]


def test_al_cambiar_de_titulacion_se_pega_el_nombre_nuevo():
    """El nombre que se le pega detrás a la consulta es el de ahora.

    Pegar el anterior sería peor que no pegar ninguno: acercaría la consulta a
    los fragmentos de una titulación de la que ya no se está hablando.
    """
    c = Conversacion(
        CATALOGO,
        decisor=decisor_de_guion(
            Decision(CAMBIA, [INFORMATICA]), Decision(CAMBIA, [MECANICA])
        ),
    )
    c.preparar("háblame del Grado en Ingeniería Informática")
    c.anotar("háblame del Grado en Ingeniería Informática", "...")
    consulta = c.preparar("¿y qué optativas tiene?")
    assert MECANICA in consulta.texto
    assert INFORMATICA not in consulta.texto


def test_una_pregunta_por_la_oferta_entera_no_se_acota_y_va_abierta():
    """«Enséñame todas» no habla de ninguna titulación, sino de las doce.

    Se responde con el catálogo, así que ni se filtra por la titulación
    anterior ni se busca como una pregunta por una unidad concreta.
    """
    c = Conversacion(
        CATALOGO,
        decisor=decisor_de_guion(Decision(CAMBIA, [INFORMATICA]), Decision(TODAS, [])),
    )
    c.preparar("háblame del Grado en Ingeniería Informática")
    c.anotar("háblame del Grado en Ingeniería Informática", "...")
    consulta = c.preparar("¿qué titulaciones ofrece la escuela?")
    assert consulta.ambito == []
    assert consulta.abierta is True


def test_un_mensaje_ajeno_suelta_el_ambito_pero_no_abre_la_consulta():
    """`NINGUNA` deja la consulta desnuda y sin filtro: es el estado neutro."""
    c = Conversacion(
        CATALOGO,
        decisor=decisor_de_guion(
            Decision(CAMBIA, [INFORMATICA]), Decision(NINGUNA, [])
        ),
    )
    c.preparar("háblame del Grado en Ingeniería Informática")
    c.anotar("háblame del Grado en Ingeniería Informática", "...")
    consulta = c.preparar("¿cuál es la capital de Francia?")
    assert consulta.ambito == []
    assert consulta.abierta is False


def test_un_mensaje_ajeno_no_arrastra_ningun_nombre_de_titulacion():
    """La otra mitad del arreglo, y la que se midió.

    Al ámbito se le pega su nombre detrás de la consulta antes de incrustarla,
    y ese texto añadido acerca al corpus **todo** lo que se pregunte. Sin él la
    pregunta vuelve a medirse desnuda, que es la única condición en la que el
    suelo de pertinencia rechaza lo ajeno.
    """
    c = Conversacion(
        CATALOGO,
        decisor=decisor_de_guion(
            Decision(CAMBIA, [INFORMATICA]), Decision(NINGUNA, [])
        ),
    )
    c.preparar("háblame del Grado en Ingeniería Informática")
    c.anotar("háblame del Grado en Ingeniería Informática", "...")
    consulta = c.preparar("¿cuál es la capital de Francia?")
    assert all(titulacion not in consulta.texto for titulacion in CATALOGO)


def test_seguir_hablando_de_lo_mismo_conserva_el_ambito():
    """`SIGUE` no toca nada: la pregunta de seguimiento es el caso normal."""
    c = Conversacion(
        CATALOGO,
        decisor=decisor_de_guion(Decision(CAMBIA, [INFORMATICA]), Decision(SIGUE, [])),
    )
    c.preparar("háblame del Grado en Ingeniería Informática")
    c.anotar("háblame del Grado en Ingeniería Informática", "...")
    assert c.preparar("¿y las optativas?").ambito == [INFORMATICA]


def test_si_el_decisor_falla_se_responde_igual_que_sin_el():
    """Un fallo del servidor no puede perder el turno.

    Una decisión de ámbito no merece tumbar una consulta que aún se puede
    responder: lo que promete `decisor_con_modelo` cuando devuelve ``None`` es
    que la conversación se queda con su mecanismo determinista.

    Es una prueba de regresión. La primera versión se saltaba la deducción por
    reglas mirando **si hay decisor** en vez de si ha decidido, y con el
    servidor caído nadie fijaba el sujeto: la pregunta de seguimiento se buscaba
    en las doce titulaciones, que es el defecto 1 de IT-106 de vuelta y encima
    en el momento en que nada podía avisar.
    """
    turnos = [
        (
            "Soy de bachillerato y me gustan los videojuegos",
            "Te encaja el Grado en Ingeniería Informática.",
        ),
        ("¿Y qué asignaturas tiene en primero?", "Álgebra, Cálculo y Programación."),
    ]
    con_decisor = Conversacion(CATALOGO, decisor=decisor_de_guion(None))
    sin_decisor = Conversacion(CATALOGO)
    for pregunta, respuesta in turnos:
        con_decisor.anotar(pregunta, respuesta)
        sin_decisor.anotar(pregunta, respuesta)
    fallada = con_decisor.preparar("¿Y en segundo?")
    normal = sin_decisor.preparar("¿Y en segundo?")
    # Se comparan los tres campos que deciden dónde se busca. El cuarto, la
    # decisión, tiene que ser justamente distinto: es lo único que deja
    # constancia de que hubo un decisor y no pudo.
    assert (fallada.texto, fallada.ambito, fallada.respaldo) == (
        normal.texto,
        normal.ambito,
        normal.respaldo,
    )
    assert (fallada.decision, normal.decision) == (FALLO, "")


def test_sin_decisor_la_consulta_nunca_es_abierta():
    """Que lo de antes siga funcionando igual: si nadie decide, nada se abre."""
    c = Conversacion(CATALOGO)
    c.anotar("háblame del Grado en Ingeniería Informática", "...")
    assert c.preparar("¿qué titulaciones hay?").abierta is False
    assert c.preparar("¿y las optativas?").abierta is False


def test_sin_decisor_la_respuesta_sigue_fijando_el_ambito():
    """El caso de IT-106: la titulación la nombró el asistente, no el alumno."""
    c = Conversacion(CATALOGO)
    c.anotar("¿me lo recomiendas?", f"Te encaja el {MECANICA}.")
    assert c.ambito == [MECANICA]


def test_con_decisor_la_respuesta_ya_no_fija_el_ambito():
    """Dos mecanismos apuntando al mismo dato se acaban contradiciendo.

    Con decisor puesto manda él, que ve el último turno entero y por tanto la
    titulación que nombró el asistente. Es la diferencia con la prueba
    anterior, y es deliberada.

    El turno se monta entero ---`preparar` y luego `anotar`--- porque es lo que
    manda: la regla no es «hay decisor» sino «ha decidido alguien en este
    turno», y así un fallo del servidor sigue cayendo en la deducción por
    reglas en vez de dejar la conversación sin ningún mecanismo.
    """
    c = Conversacion(CATALOGO, decisor=decisor_de_guion(Decision(SIGUE, [])))
    c.preparar("¿me lo recomiendas?")
    c.anotar("¿me lo recomiendas?", f"Te encaja el {MECANICA}.")
    assert c.ambito == []


def test_en_el_primer_mensaje_el_decisor_no_recibe_turno_anterior():
    """No hay nada que enseñarle: la conversación acaba de empezar."""
    llamadas: list[Llamada] = []
    c = Conversacion(CATALOGO, decisor=decisor_espia(llamadas))
    c.preparar("hola, buenas tardes")
    assert llamadas == [("hola, buenas tardes", [], None)]


def test_al_decisor_le_llega_el_ultimo_turno_completo():
    """Con la respuesta dentro, que es lo que sostiene el sujeto heredado.

    Si solo se le enseñaran las preguntas, no podría saber de qué se habla
    cuando la titulación la nombró el asistente.
    """
    llamadas: list[Llamada] = []
    c = Conversacion(CATALOGO, decisor=decisor_espia(llamadas))
    c.preparar("¿me lo recomiendas?")
    c.anotar("¿me lo recomiendas?", f"Te encaja el {MECANICA}.")
    c.preparar("¿y las optativas?")
    assert llamadas[-1] == (
        "¿y las optativas?",
        [],
        ("¿me lo recomiendas?", f"Te encaja el {MECANICA}."),
    )


def test_al_olvidar_el_decisor_vuelve_a_empezar_de_cero():
    """`olvidar` deja el objeto como recién creado, también para el decisor."""
    llamadas: list[Llamada] = []
    c = Conversacion(CATALOGO, decisor=decisor_espia(llamadas))
    c.anotar("¿me lo recomiendas?", f"Te encaja el {MECANICA}.")
    c.olvidar()
    c.preparar("¿y las optativas?")
    assert llamadas[-1] == ("¿y las optativas?", [], None)

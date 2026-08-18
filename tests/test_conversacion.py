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

from tfg_uja.conversacion import (
    Conversacion,
    contenido,
    es_continuacion,
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


def test_una_continuacion_no_se_convierte_en_el_predicado():
    """Heredar de una continuación arrastra el recorte que ella misma hacía."""
    assert es_continuacion("¿Y cuántas de esas son optativas?")
    assert es_continuacion("Y en el grado de electrónica?")
    assert not es_continuacion("¿Qué asignaturas tiene primero?")


def test_una_pregunta_que_solo_lleva_ordinal_hereda_el_predicado_original():
    """El predicado que se hereda es el de la última pregunta que abrió tema."""
    c = Conversacion(CATALOGO)
    c.anotar("¿Qué asignaturas se dan en primer curso de Informática?", "...")
    c.anotar("¿Y cuántas de esas son optativas?", "...")
    c.anotar("¿Y en el segundo?", "...")
    consulta = c.preparar("¿Y en el tercero?")
    assert "optativas" not in consulta.texto.lower()
    assert "asignaturas" in consulta.texto


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

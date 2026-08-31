"""Pruebas de los correctores del banco del sistema (IT-37).

Ninguna llama al servidor de inferencia: lo que se comprueba aquí es que cada
criterio da por buena la respuesta correcta y por mala la equivocada, que es lo
único que sostiene las cifras del experimento. Los criterios nuevos son los que
no existían en el banco de IT-35 y, por tanto, los que nunca se habían probado.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "experimentos"))

import experimento_sistema as sistema  # noqa: E402

from tfg_uja import generador  # noqa: E402

CATALOGO = [
    "Doble Grado en Ingeniería Mecánica y Organización Industrial",
    "Grado en Ingeniería Informática",
    "Grado en Ingeniería Mecánica",
    "Grado en Ingeniería de Organización Industrial",
]


# --- Respuestas fijas ---


def test_la_respuesta_fija_se_compara_entera():
    acierta, _ = sistema.corregir_fija(generador.RESPUESTA_SALUDO, ["RESPUESTA_SALUDO"])
    assert acierta


def test_una_respuesta_parecida_no_es_la_fija():
    """Se compara literal a propósito: es la comprobación más dura que hay."""
    acierta, detalle = sistema.corregir_fija("¡Hola!", ["RESPUESTA_SALUDO"])
    assert not acierta
    assert "RESPUESTA_SALUDO" in detalle


def test_la_despedida_no_vale_por_el_saludo():
    acierta, _ = sistema.corregir_fija(
        generador.RESPUESTA_DESPEDIDA, ["RESPUESTA_SALUDO"]
    )
    assert not acierta


# --- Recomendaciones ---


def test_recomendar_una_titulacion_real_es_acertar():
    acierta, _ = sistema.corregir_sin_invencion(
        "Te encaja el Grado en Ingeniería Informática.", CATALOGO
    )
    assert acierta


def test_inventarse_una_titulacion_es_fallar():
    acierta, detalle = sistema.corregir_sin_invencion(
        "Te recomiendo el Grado en Ingeniería Biomédica.", CATALOGO
    )
    assert not acierta
    assert "Biomédica" in detalle


def test_no_recomendar_ninguna_tambien_es_fallar():
    """A quien pide consejo hay que darle alguno: escurrir el bulto no vale."""
    acierta, detalle = sistema.corregir_sin_invencion(
        "Depende de lo que te guste.", CATALOGO
    )
    assert not acierta
    assert "ninguna" in detalle


def test_la_retirada_de_la_barrera_se_distingue_del_silencio():
    """Son fallos distintos y el informe los daba por el mismo.

    Cuando la barrera actúa, la respuesta que queda no nombra ninguna
    titulación ---es una frase fija--- y el criterio la suspendía por «no
    recomienda ninguna», que se lee como si el modelo se hubiese callado.
    Lo que pasó es lo contrario: nombró de más y se le retiró todo.
    """
    acierta, detalle = sistema.corregir_sin_invencion(
        generador.RESPUESTA_TITULACION_INVENTADA, CATALOGO
    )
    assert not acierta
    assert "barrera" in detalle


# --- Preguntas ajenas al dominio ---


def test_negar_y_ademas_ofrecer_lo_que_si_hay_es_rechazar_bien():
    """Regresión: el criterio anterior daba por fallada la mejor respuesta.

    `granite4.1:8b` y `gemma3:12b` contestaron «No, no puedes estudiar Medicina
    en la Escuela Politécnica Superior de Jaén. Las titulaciones que ofrece
    son...» con la lista correcta, y el criterio las suspendía por nombrar
    titulaciones. Enumerar lo que sí hay después de negar lo que no hay es
    mejor servicio, no un error.
    """
    acierta, detalle = sistema.corregir_rechazo(
        "No, no puedes estudiar Medicina en la Escuela. Las titulaciones que "
        "ofrece son el Grado en Ingeniería Informática y el Grado en "
        "Ingeniería Mecánica.",
        CATALOGO,
    )
    assert acierta, detalle


def test_afirmar_lo_que_no_existe_es_fallar():
    """Es el fallo que este criterio busca de verdad."""
    acierta, detalle = sistema.corregir_rechazo(
        "Sí, en la Escuela puedes estudiar el Grado en Ingeniería Informática.",
        CATALOGO,
    )
    assert not acierta
    assert "niega" in detalle


def test_una_titulacion_inventada_falla_aunque_niegue():
    acierta, detalle = sistema.corregir_rechazo(
        "No, aquí no hay Medicina, pero tienes el Grado en Ingeniería Biomédica.",
        CATALOGO,
    )
    assert not acierta
    assert "Biomédica" in detalle


def test_la_respuesta_fija_de_contexto_vacio_es_un_rechazo_valido():
    acierta, _ = sistema.corregir_rechazo(generador.RESPUESTA_SIN_CONTEXTO, CATALOGO)
    assert acierta


def test_negar_con_ninguna_cuenta_igual_que_negar_con_no():
    """Caso real del 23/08/2026, que el criterio anterior suspendía.

    A «me gusta el derecho penal, ¿qué carrera me pega?» el sistema contestó
    que ninguna de sus titulaciones encaja y que todas son de ingeniería. Es un
    rechazo impecable, y fallaba porque la primera frase decía «ninguna» y no
    «no». Un criterio que exige una palabra concreta mide la redacción del
    rechazo, no el rechazo, que es el mismo defecto que tuvo la precisión del
    cribado antes de IT-110.
    """
    acierta, detalle = sistema.corregir_rechazo(
        "Dado que te gusta el derecho penal, ninguna de las titulaciones que "
        "ofrece la Escuela encaja directamente con tus intereses. Todas las "
        "opciones son de ingeniería, informática o ciberseguridad, y no tienen "
        "relación con el ámbito legal.",
        CATALOGO,
    )
    assert acierta, detalle


def test_la_negacion_puede_llegar_en_la_segunda_frase():
    """El modelo introduce y niega después; partir por el primer punto lo perdía."""
    acierta, detalle = sistema.corregir_rechazo(
        "Vamos a ver lo que ofrece la Escuela. Aquí no se imparte esa carrera.",
        CATALOGO,
    )
    assert acierta, detalle


def test_una_respuesta_que_ni_niega_ni_introduce_sigue_fallando():
    """La regresión del arreglo: ampliar la negación no puede aprobarlo todo."""
    acierta, detalle = sistema.corregir_rechazo(
        "La Escuela imparte titulaciones de ingeniería. Te cuento cuáles son.",
        CATALOGO,
    )
    assert not acierta
    assert "niega" in detalle


# --- Ámbito de la conversación ---


def test_hablar_de_la_titulacion_correcta_es_acertar():
    pregunta = {
        "esperado": ["Grado en Ingeniería de Organización Industrial"],
        "prohibido": ["Grado en Ingeniería Mecánica"],
    }
    acierta, _ = sistema.corregir_ambito(
        "El Grado en Ingeniería de Organización Industrial tiene 15 optativas.",
        pregunta,
        CATALOGO,
    )
    assert acierta


def test_responder_de_otra_titulacion_es_fallar():
    """Regresión del turno 7 del 19/08/2026, que ninguna métrica detectaba.

    Quince asignaturas reales, cero invenciones y la titulación equivocada: la
    precisión y la cobertura salían perfectas.
    """
    pregunta = {
        "esperado": ["Grado en Ingeniería de Organización Industrial"],
        "prohibido": ["Grado en Ingeniería Mecánica"],
    }
    acierta, detalle = sistema.corregir_ambito(
        "El Grado en Ingeniería Mecánica tiene 15 asignaturas optativas.",
        pregunta,
        CATALOGO,
    )
    assert not acierta
    assert "Mecánica" in detalle


def test_el_doble_grado_no_dispara_la_prohibicion_del_simple():
    """El nombre del simple está dentro del doble, y eso no es nombrarlo."""
    pregunta = {
        "esperado": ["Doble Grado en Ingeniería Mecánica y Organización Industrial"],
        "prohibido": ["Grado en Ingeniería Mecánica"],
    }
    acierta, detalle = sistema.corregir_ambito(
        "El Doble Grado en Ingeniería Mecánica y Organización Industrial dura "
        "cinco cursos.",
        pregunta,
        CATALOGO,
    )
    assert acierta, detalle


# --- El despachador ---


def test_un_criterio_desconocido_no_pasa_en_silencio():
    """Un banco con una errata daría cifras sin que nadie se enterase."""
    with pytest.raises(ValueError, match="criterio desconocido"):
        sistema.corregir("lo que sea", {"respuesta": "inventado"}, CATALOGO, set())


def test_el_criterio_de_conjunto_exige_precision_y_cobertura_perfectas():
    pregunta = {
        "respuesta": "conjunto",
        "familia": "optativas",
        "esperado": ["Álgebra", "Cálculo"],
    }
    nombres = {"Álgebra", "Cálculo", "Física I"}
    entero = sistema.corregir(
        "- Álgebra (6 ECTS)\n- Cálculo (6 ECTS)", pregunta, CATALOGO, nombres
    )
    assert entero["acierta"]
    falta = sistema.corregir("- Álgebra (6 ECTS)", pregunta, CATALOGO, nombres)
    assert not falta["acierta"]
    assert falta["omitidas"] == 1


# --- Ámbito, recorrido de una entrada, informe y main (IT-113) --------------

import json  # noqa: E402
from pathlib import Path  # noqa: E402


def _entrada(
    identificador="E-001",
    familia="temario",
    criterio="fija",
    esperado=None,
    turnos=None,
    prohibido=None,
):
    """Una entrada del banco del sistema."""
    entrada = {
        "id": identificador,
        "familia": familia,
        # El banco llama `respuesta` al criterio con el que se corrige.
        "respuesta": criterio,
        "pregunta": "¿y el temario?",
        "esperado": esperado if esperado is not None else [],
    }
    if turnos is not None:
        entrada["turnos"] = turnos
    if prohibido is not None:
        entrada["prohibido"] = prohibido
    return entrada


# --- El corrector de ámbito -------------------------------------------------


def test_el_ambito_falla_si_habla_de_una_titulacion_prohibida():
    """Es el defecto que IT-106 persigue: responder de otra titulación con aplomo."""
    entrada = _entrada(
        criterio="ambito", esperado=[CATALOGO[0]], prohibido=[CATALOGO[1]]
    )

    acierta, detalle = sistema.corregir_ambito(
        f"Te hablo del {CATALOGO[1]}.", entrada, CATALOGO
    )

    assert not acierta
    assert "que no es" in detalle


def test_el_ambito_falla_si_no_nombra_la_que_toca():
    entrada = _entrada(criterio="ambito", esperado=[CATALOGO[0]])

    acierta, detalle = sistema.corregir_ambito("No te digo cuál.", entrada, CATALOGO)

    assert not acierta
    assert "no nombra" in detalle


def test_el_ambito_acierta_cuando_nombra_la_suya_y_ninguna_prohibida():
    entrada = _entrada(
        criterio="ambito", esperado=[CATALOGO[0]], prohibido=[CATALOGO[1]]
    )

    acierta, detalle = sistema.corregir_ambito(
        f"Te hablo del {CATALOGO[0]}.", entrada, CATALOGO
    )

    assert acierta
    assert detalle == ""


def test_un_criterio_que_no_existe_revienta():
    """Callar un criterio desconocido daría por buena una entrada sin corregir."""
    with pytest.raises(ValueError, match="criterio desconocido"):
        sistema.corregir("da igual", _entrada(criterio="inventado"), CATALOGO, set())


# --- El recorrido de una entrada --------------------------------------------


def _sin_modelo(monkeypatch, respuestas, fragmentos=3):
    """Sustituye la recuperación y la generación."""
    pendientes = list(respuestas)
    monkeypatch.setattr(sistema, "contexto_para", lambda *a, **kw: ["f"] * fragmentos)

    def responder(texto, frags, modelo, historial, ambito, catalogo, traza):
        traza["retirada"] = "no"
        return pendientes.pop(0)

    monkeypatch.setattr(sistema, "responder", responder)


def test_una_entrada_de_un_turno_se_responde_una_vez(monkeypatch):
    _sin_modelo(monkeypatch, ["Pues esto."])

    respuesta, segundos, cuantos, turnos, traza = sistema.responder_entrada(
        _entrada(), "gemma3:12b", None, None, "cosine", CATALOGO
    )

    assert (respuesta, cuantos, turnos) == ("Pues esto.", 3, 1)
    assert segundos >= 0.0
    assert traza["retirada"] == "no"


def test_de_una_conversacion_se_corrige_el_ultimo_turno(monkeypatch):
    """Una retirada de un turno intermedio contaría contra una respuesta ajena."""
    _sin_modelo(monkeypatch, ["Primera.", "Segunda.", "Tercera."])

    respuesta, _s, _c, turnos, _t = sistema.responder_entrada(
        _entrada(turnos=["uno", "dos", "tres"]),
        "gemma3:12b",
        None,
        None,
        "cosine",
        CATALOGO,
    )

    assert (respuesta, turnos) == ("Tercera.", 3)


# --- La tanda ---------------------------------------------------------------


def test_ejecutar_escribe_el_registro_y_dice_lo_que_falla(
    tmp_path, monkeypatch, capsys
):
    """El registro se vacía en cada llamada y se vuelca turno a turno."""
    monkeypatch.setattr(sistema, "version_del_servidor", lambda: "0.32.14")
    monkeypatch.setattr(
        sistema,
        "responder_entrada",
        lambda *a: ("Pues esto.", 1.5, 3, 1, {}),
    )
    monkeypatch.setattr(
        sistema,
        "corregir",
        lambda *a: {"acierta": False, "detalle": "no nombra nada", "criterio": "fija"},
    )
    registro = tmp_path / "registro.jsonl"

    filas = sistema.ejecutar(
        ["gemma3:12b"], [_entrada()], None, None, "cosine", CATALOGO, set(), registro
    )

    texto = capsys.readouterr().out
    assert len(filas) == 1
    assert "FALLA" in texto
    assert "no nombra nada" in texto
    assert json.loads(registro.read_text(encoding="utf-8").strip())["id"] == "E-001"


# --- El informe -------------------------------------------------------------


def _fila(identificador="E-001", modelo="gemma3:12b", acierta=True, familia="temario"):
    return {
        "modelo": modelo,
        "servidor": "0.32.14",
        "id": identificador,
        "familia": familia,
        "turnos": 1,
        "segundos": 21.6,
        "fragmentos": 3,
        "respuesta": "Pues esto.",
        "acierta": acierta,
        "detalle": "" if acierta else "no nombra nada",
    }


def test_el_informe_reparte_los_aciertos_por_modelo_y_familia(tmp_path, capsys):
    destino = tmp_path / "it38.md"

    sistema.informe(
        [_fila(), _fila("E-002", acierta=False, familia="fuera_de_dominio")], destino
    )

    texto = destino.read_text(encoding="utf-8")
    assert "| `gemma3:12b` | 1 de 2 | 0.500 |" in texto
    assert "| fuera_de_dominio | 1 |" in texto
    assert "Informe escrito en" in capsys.readouterr().out


def test_el_informe_lista_lo_que_falla_con_su_motivo(tmp_path):
    destino = tmp_path / "it38.md"

    sistema.informe([_fila("E-002", acierta=False)], destino)

    texto = destino.read_text(encoding="utf-8")
    assert "## Lo que falla" in texto
    assert "E-002 (temario): no nombra nada" in texto


def test_si_no_falla_nada_el_informe_lo_dice(tmp_path):
    destino = tmp_path / "it38.md"

    sistema.informe([_fila()], destino)

    assert "Nada." in destino.read_text(encoding="utf-8")


def test_un_informe_sin_filas_no_revienta(tmp_path):
    """Puede pasar si la tanda se corta antes de la primera respuesta."""
    destino = tmp_path / "it38.md"

    sistema.informe([], destino)

    assert "Servidor de inferencia: ?" in destino.read_text(encoding="utf-8")


# --- El recorrido entero ----------------------------------------------------


def _preparar_main(tmp_path, monkeypatch):
    banco = tmp_path / "banco.json"
    banco.write_text(json.dumps({"preguntas": [_entrada()]}), encoding="utf-8")
    datos = tmp_path / "grados.json"
    datos.write_text(json.dumps([]), encoding="utf-8")
    monkeypatch.setattr(sistema, "catalogo_del_indice", lambda ruta: CATALOGO)
    return banco, datos


def test_main_ejecuta_la_tanda_y_escribe_el_informe(tmp_path, monkeypatch):
    banco, datos = _preparar_main(tmp_path, monkeypatch)
    monkeypatch.setattr(sistema, "abrir_indice", lambda ruta, modelo: None)
    monkeypatch.setattr(sistema, "incrustador_de_consultas", lambda modelo: None)
    monkeypatch.setattr(sistema, "distancia_del_indice", lambda ruta: "cosine")
    monkeypatch.setattr(sistema, "ejecutar", lambda *a: [_fila()])
    salida = tmp_path / "it38.md"

    sistema.main(
        [
            "--banco",
            str(banco),
            "--datos",
            str(datos),
            "--indice",
            str(tmp_path),
            "--registro",
            str(tmp_path / "r.jsonl"),
            "--salida",
            str(salida),
            "--modelos",
            "gemma3:12b",
        ]
    )

    assert "gemma3:12b" in salida.read_text(encoding="utf-8")


def test_main_recorrige_lo_guardado_sin_llamar_a_ningun_modelo(
    tmp_path, monkeypatch, capsys
):
    """Los criterios han cambiado nueve veces; repetir la tanda cuesta horas.

    Recorregir lo guardado deja además todas las tandas comparables con la
    misma vara.
    """
    banco, datos = _preparar_main(tmp_path, monkeypatch)
    registro = tmp_path / "r.jsonl"
    registro.write_text(json.dumps(_fila(acierta=False)) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        sistema,
        "corregir",
        lambda *a: {"acierta": True, "detalle": "", "criterio": "fija"},
    )
    salida = tmp_path / "it38.md"

    sistema.main(
        [
            "--banco",
            str(banco),
            "--datos",
            str(datos),
            "--indice",
            str(tmp_path),
            "--registro",
            str(registro),
            "--salida",
            str(salida),
            "--recorregir",
        ]
    )

    assert "Recorregidas 1 respuestas" in capsys.readouterr().out
    assert json.loads(registro.read_text(encoding="utf-8").strip())["acierta"] is True


# --- El despachador de criterios --------------------------------------------
#
# Cada criterio tenía su prueba, pero nadie comprobaba que `corregir` los
# reparta bien. Un despachador que se equivoque de rama corrige una respuesta
# con la vara de otra familia y las cifras siguen pareciendo razonables.


def test_corregir_reparte_el_criterio_de_conjunto():
    entrada = _entrada(
        criterio="conjunto", familia="menciones", esperado=["Automática"]
    )

    salida = sistema.corregir("- Automática.", entrada, CATALOGO, {"Automática"})

    assert salida["criterio"] == "conjunto"
    assert salida["acierta"]
    assert salida["cobertura"] == 1.0


def test_corregir_reparte_el_criterio_escalar():
    entrada = _entrada(criterio="escalar", familia="creditos", esperado=["6"])

    salida = sistema.corregir("Son 6 ECTS.", entrada, CATALOGO, set())

    assert salida["criterio"] == "escalar"
    assert salida["acierta"]


def test_corregir_reparte_el_criterio_de_respuesta_fija():
    entrada = _entrada(criterio="fija", esperado=["RESPUESTA_SALUDO"])

    salida = sistema.corregir(generador.RESPUESTA_SALUDO, entrada, CATALOGO, set())

    assert salida["criterio"] == "fija"
    assert salida["acierta"]


def test_corregir_reparte_el_criterio_de_no_inventar():
    entrada = _entrada(criterio="sin_invencion")

    salida = sistema.corregir(f"Te hablo del {CATALOGO[0]}.", entrada, CATALOGO, set())

    assert salida["criterio"] == "sin_invencion"
    assert salida["acierta"]


def test_corregir_reparte_el_criterio_de_rechazo():
    entrada = _entrada(criterio="rechazo", familia="fuera_de_dominio")

    salida = sistema.corregir(
        generador.RESPUESTA_SIN_CONTEXTO, entrada, CATALOGO, set()
    )

    assert salida["criterio"] == "rechazo"
    assert salida["acierta"]


def test_corregir_reparte_el_criterio_de_ambito():
    entrada = _entrada(
        criterio="ambito", esperado=[CATALOGO[0]], prohibido=[CATALOGO[1]]
    )

    salida = sistema.corregir(f"Te hablo del {CATALOGO[0]}.", entrada, CATALOGO, set())

    assert salida["criterio"] == "ambito"
    assert salida["acierta"]


def test_una_respuesta_de_listado_en_prosa_no_se_suspende_por_el_formato():
    """IT-110: exigir precisión 1,0 medía el formato, no la verdad.

    En prosa no se enumera nada, la precisión es None y decide la cobertura,
    que se mide sobre el texto entero.
    """
    entrada = _entrada(
        criterio="conjunto", familia="menciones", esperado=["Automática"]
    )

    salida = sistema.corregir(
        "La titulación ofrece la mención de Automática.",
        entrada,
        CATALOGO,
        {"Automática"},
    )

    assert salida["precision"] is None
    assert salida["acierta"]

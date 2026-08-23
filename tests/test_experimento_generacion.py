"""Pruebas del guion que criba modelos generativos (IT-35).

Ninguna llama a un modelo: se comprueba el **instrumento**, que es lo que ha
fallado dos veces en dos días y las dos con cifras verosímiles. Un cribado que
mide mal no avisa de nada, simplemente elige el candidato equivocado.

Los registros son copias literales de ``data/grados.json`` y de las respuestas
que dieron los candidatos el 18/08/2026.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "experimento_generacion", RAIZ / "scripts" / "experimento_generacion.py"
)
assert _spec is not None and _spec.loader is not None
experimento = importlib.util.module_from_spec(_spec)
sys.modules["experimento_generacion"] = experimento
_spec.loader.exec_module(experimento)


# --- Registros reales de data/grados.json ---

_CON_MENCION = {
    "tipo": "asignatura",
    "grado": "Grado en Ingeniería Electrónica Industrial",
    "codigo": "13113013",
    "nombre": "Sistemas Digitales",
    "tipo_asignatura": "OP",
    "menciones": ["Sistemas electrónicos"],
    "ects": "6",
}

_COMUN = {
    "tipo": "asignatura",
    "grado": "Grado en Ingeniería Mecánica",
    "codigo": "13413012",
    "nombre": "Prácticas externas",
    "tipo_asignatura": "OP",
    "menciones": ["Común a todas las menciones"],
    "ects": "6",
}

_SIN_MENCION = {
    "tipo": "asignatura",
    "grado": "Grado en Ingeniería Informática",
    "codigo": "13312001",
    "nombre": "Fundamentos de la programación",
    "tipo_asignatura": "FB",
    "menciones": [],
    "ects": "6",
}

_DATOS = [{"tipo": "grado", "nombre": "Grado en Ingeniería Informática"}] + [
    _CON_MENCION,
    _COMUN,
    _SIN_MENCION,
]

CATALOGO = ["Grado en Ingeniería Informática", "Grado en Ingeniería Mecánica"]


# --- De dónde salen los nombres válidos ---


def test_los_nombres_de_asignatura_salen_del_dataset():
    assert experimento.asignaturas_del_corpus(_DATOS) == {
        "Sistemas Digitales",
        "Prácticas externas",
        "Fundamentos de la programación",
    }


def test_comun_a_todas_las_menciones_no_es_una_mencion():
    """Es un rótulo de la fuente, no un itinerario."""
    assert experimento.menciones_del_corpus(_DATOS) == {"Sistemas electrónicos"}


# --- Contra qué se comprueba cada familia (regresión del 18/08/2026) ---

_PREGUNTA_MENCIONES = {
    "familia": "menciones",
    "respuesta": "conjunto",
    "esperado": ["Automática", "Sistemas electrónicos"],
    "ambito": {"grado": "Grado en Ingeniería Electrónica Industrial"},
}

_PREGUNTA_ASIGNATURAS_DE_MENCION = {
    "familia": "menciones",
    "respuesta": "conjunto",
    "esperado": ["Robótica industrial"],
    "ambito": {
        "grado": "Grado en Ingeniería Electrónica Industrial",
        "mencion": "Automática",
    },
}

_PREGUNTA_CATALOGO = {
    "familia": "catalogo",
    "respuesta": "conjunto",
    "esperado": CATALOGO,
    "ambito": {},
}


def test_el_universo_es_todo_lo_que_el_corpus_nombra():
    assert experimento.universo(CATALOGO, {"Álgebra"}, {"Automática"}) == set(
        CATALOGO
    ) | {"Álgebra", "Automática"}


def test_enumerar_menciones_no_cuenta_como_invencion():
    """Regresión.

    Comprobando las preguntas de mención contra los nombres de asignatura, los
    tres candidatos daban precisión 0,59-0,62 por enumerar bien lo que se les
    pedía. Que los tres coincidieran era la señal de que fallaba el
    instrumento.
    """
    assert "Automática" in experimento.universo(CATALOGO, {"Álgebra"}, {"Automática"})


def test_enumerar_asignaturas_reales_tampoco():
    """Regresión de G-MEN-003.

    Con el conjunto restringido a las menciones, ``command-r7b`` sacaba
    precisión 0,136 en esa pregunta por enumerar además las asignaturas de
    cada mención: diecinueve nombres reales del corpus contados como
    inventados.
    """
    assert "Álgebra" in experimento.universo(CATALOGO, {"Álgebra"}, {"Automática"})


# --- Las respuestas de valor único ---


def test_los_creditos_solo_cuentan_con_su_unidad_detras():
    """Sin la unidad, cualquier «6» suelto del texto contaría como acierto."""
    acierta, dicho = experimento.acierto_escalar(
        "La asignatura tiene 6 ECTS.", "6", "creditos"
    )
    assert acierta
    assert dicho == "6"


def test_un_seis_suelto_no_es_una_respuesta_de_creditos():
    acierta, dicho = experimento.acierto_escalar(
        "Se imparte en el grupo 6 del segundo cuatrimestre.", "6", "creditos"
    )
    assert not acierta
    assert dicho == ""


def test_decir_otra_cifra_de_creditos_es_fallar():
    acierta, dicho = experimento.acierto_escalar("Tiene 9 créditos.", "6", "creditos")
    assert not acierta
    assert dicho == "9"


def test_el_curso_se_busca_sin_la_palabra_curso():
    """El rótulo de la fuente es «Tercer o cuarto curso» y el modelo la omite."""
    acierta, _ = experimento.acierto_escalar(
        "Se imparte en tercer o cuarto, según el itinerario.",
        "Tercer o cuarto curso",
        "curso_de_asignatura",
    )
    assert acierta


def test_decir_otro_curso_es_fallar():
    acierta, _ = experimento.acierto_escalar(
        "Se imparte en primero.", "Tercer o cuarto curso", "curso_de_asignatura"
    )
    assert not acierta


def test_nombrar_uno_solo_de_los_dos_cursos_del_rotulo_es_acertar():
    """Regresión: respuesta real de `granite4.1:8b` a G-ASI-0226.

    El rótulo de la fuente enumera dos cursos admisibles y el modelo nombró
    uno. Buscar la cadena entera lo contaba como fallo, y con él a las dos
    preguntas de rótulo doble de la muestra por cada uno de los tres
    candidatos.
    """
    acierta, dicho = experimento.acierto_escalar(
        "Ingeniería térmica II (GIM) se imparte en el segundo cuatrimestre de "
        "tercer curso del Doble Grado en Ingeniería Eléctrica y Mecánica.",
        "Tercer o cuarto curso",
        "curso_de_asignatura",
    )
    assert acierta
    assert dicho == "tercer"


def test_el_rotulo_doble_admite_tambien_el_segundo_de_sus_cursos():
    """La fuente publica los dos órdenes: «Tercer o cuarto» y «Cuarto o tercer»."""
    acierta, dicho = experimento.acierto_escalar(
        "Se imparte en cuarto.", "Cuarto o tercer curso", "curso_de_asignatura"
    )
    assert acierta
    assert dicho == "cuarto"


def test_un_rotulo_de_un_solo_curso_admite_ese_curso():
    assert experimento.cursos_admisibles("Quinto curso") == ["quinto"]


# --- La medición completa de una respuesta ---


def test_una_respuesta_escalar_no_calcula_precision():
    medido = experimento.medir(
        "Tiene 6 ECTS.",
        {
            "familia": "creditos",
            "respuesta": "escalar",
            "esperado": ["6"],
            "ambito": {},
        },
        CATALOGO,
        set(),
        set(),
    )
    assert medido["acierto"]
    assert "precision" not in medido


def test_una_titulacion_inventada_se_registra_en_cualquier_familia():
    medido = experimento.medir(
        "Te recomiendo el Grado en Ingeniería Biomédica.",
        {
            "familia": "creditos",
            "respuesta": "escalar",
            "esperado": ["6"],
            "ambito": {},
        },
        CATALOGO,
        set(),
        set(),
    )
    assert medido["titulaciones_inventadas"] == ["Grado en Ingeniería Biomédica"]


# --- Repuntuar sin volver a pagar la inferencia ---


def test_recalcular_no_necesita_ningun_modelo_y_corrige_las_cifras():
    """El caso exacto que motivó el modo: la familia de menciones.

    La fila guardada trae la precisión que salía con el universo equivocado;
    repuntuada con el bueno, la respuesta ---que es correcta--- sube a 1,0.
    """
    fila = {
        "modelo": "gemma3:12b",
        "id": "G-MEN-001",
        "familia": "menciones",
        "pregunta": "¿En qué menciones se puede especializar?",
        "respuesta": "- Automática\n- Sistemas electrónicos\n",
        "fragmentos": 4,
        "segundos_recuperar": 0.04,
        "segundos_generar": 12.0,
        "precision": 0.0,
        "cobertura": 1.0,
        "inventadas": ["automatica", "sistemas electronicos"],
        "omitidas": 0,
        "esperadas": 2,
        "titulaciones_inventadas": [],
    }
    nuevas = experimento.recalcular(
        [fila],
        {"G-MEN-001": _PREGUNTA_MENCIONES},
        CATALOGO,
        {"Álgebra"},
        {"Automática", "Sistemas electrónicos"},
    )
    assert nuevas[0]["precision"] == 1.0
    assert nuevas[0]["inventadas"] == []
    # Lo que no es una cifra se conserva tal cual: la respuesta es el dato caro.
    assert nuevas[0]["respuesta"] == fila["respuesta"]
    assert nuevas[0]["segundos_generar"] == 12.0


# --- El registro y el informe ---


def test_no_se_vuelve_a_pagar_una_respuesta_ya_medida(tmp_path):
    registro = tmp_path / "r.jsonl"
    registro.write_text(
        json.dumps({"modelo": "m", "id": "G-1"}) + "\n", encoding="utf-8"
    )
    assert experimento.ya_medido(registro) == {("m", "G-1")}


def test_un_registro_que_no_existe_no_tiene_nada_medido(tmp_path):
    assert experimento.ya_medido(tmp_path / "no-esta.jsonl") == set()


_FILAS = [
    {
        "modelo": "m",
        "id": "G-1",
        "familia": "menciones",
        "respuesta": "- Automática",
        "fragmentos": 3,
        "segundos_generar": 10.0,
        "segundos_recuperar": 0.0,
        "precision": 1.0,
        "cobertura": 1.0,
        "inventadas": [],
        "omitidas": 0,
        "esperadas": 1,
        "titulaciones_inventadas": [],
    },
    {
        "modelo": "m",
        "id": "G-2",
        "familia": "creditos",
        "respuesta": "6 ECTS",
        "fragmentos": 0,
        "segundos_generar": 0.0,
        "segundos_recuperar": 0.0,
        "acierto": True,
        "dicho": "6",
        "titulaciones_inventadas": ["Grado en Ingeniería Biomédica"],
    },
]


def test_el_resumen_separa_listados_de_escalares():
    resumen = experimento.resumir(_FILAS)["m"]
    assert resumen["listados"] == 1
    assert resumen["escalares"] == 1
    assert resumen["titulaciones_inventadas"] == 1
    assert resumen["nombres_inventados"] == ["Grado en Ingeniería Biomédica"]


def test_una_pregunta_sin_contexto_no_entra_en_los_tiempos():
    """Cero segundos no es una respuesta rápida: es una respuesta que no hubo."""
    resumen = experimento.resumir(_FILAS)["m"]
    assert resumen["sin_contexto"] == 1
    assert resumen["mediana_s"] == 10.0


def test_el_desglose_marca_que_familia_es_de_listado():
    familias = experimento.por_familia(_FILAS)["m"]
    assert familias["menciones"]["es_listado"]
    assert not familias["creditos"]["es_listado"]


def test_el_informe_se_escribe_entero(tmp_path):
    destino = tmp_path / "informe.md"
    experimento.informe(
        _FILAS, {"procedencia_del_dataset": {"fecha": "2026-08-16"}}, destino
    )
    texto = destino.read_text(encoding="utf-8")
    assert "Cribado de modelos generativos" in texto
    assert "Grado en Ingeniería Biomédica" in texto
    assert "fecha: 2026-08-16" in texto


# --- La versión del servidor de inferencia ---


def test_el_informe_avisa_si_se_mezclaron_dos_servidores(tmp_path):
    """Regresión del 19/08/2026.

    El servidor de inferencia se actualizó solo de la 0.23.2 a la 0.32.14 en
    mitad del cribado. Una diferencia entre candidatos medidos con versiones
    distintas puede venir del tiempo de ejecución y no del modelo, así que la
    tabla no compara nada y el informe tiene que decirlo.
    """
    mezcladas = [
        {**_FILAS[0], "modelo": "a", "servidor": "0.23.2"},
        {**_FILAS[0], "modelo": "b", "servidor": "0.32.14"},
    ]
    destino = tmp_path / "informe.md"
    experimento.informe(mezcladas, {}, destino)
    texto = destino.read_text(encoding="utf-8")
    assert "0.23.2 · 0.32.14" in texto
    assert "NO se midieron todas con el mismo servidor" in texto


def test_un_solo_servidor_no_dispara_el_aviso(tmp_path):
    iguales = [{**f, "servidor": "0.32.14"} for f in _FILAS]
    destino = tmp_path / "informe.md"
    experimento.informe(iguales, {}, destino)
    texto = destino.read_text(encoding="utf-8")
    assert "Servidor de inferencia: 0.32.14" in texto
    assert "NO se midieron todas" not in texto


def test_las_respuestas_viejas_sin_version_se_marcan_como_tales(tmp_path):
    """Las 240 primeras se midieron antes de anotar la versión."""
    destino = tmp_path / "informe.md"
    experimento.informe(_FILAS, {}, destino)
    assert "sin anotar" in destino.read_text(encoding="utf-8")


# --- El tiempo informa, pero no descarta ---


def test_sin_presupuesto_no_hay_columna_de_descarte(tmp_path):
    """Eliminar por tiempo exige una máquina en condiciones controladas.

    El 18/08/2026 una respuesta de 581 caracteres marcó 16.677 s porque el
    equipo estaba paginando a disco. Con esa varianza el tiempo describe la
    máquina y no al candidato.
    """
    destino = tmp_path / "informe.md"
    experimento.informe(_FILAS, {}, destino, presupuesto=0)
    texto = destino.read_text(encoding="utf-8")
    assert "Fuera de presupuesto" not in texto
    assert "no descarta a ningún candidato" in texto
    # Los tiempos se siguen informando: son un dato, no un veredicto.
    assert "Mediana (s)" in texto


def test_con_presupuesto_vuelve_la_columna(tmp_path):
    destino = tmp_path / "informe.md"
    experimento.informe(_FILAS, {}, destino, presupuesto=5.0)
    texto = destino.read_text(encoding="utf-8")
    assert "Fuera de presupuesto" in texto
    assert "**5 s**" in texto


def test_el_presupuesto_cero_no_cuenta_a_nadie_fuera():
    lento = [{**_FILAS[0], "segundos_generar": 9999.0}]
    sin_tope = experimento.resumir(lento, presupuesto=0)
    assert sin_tope["m"]["fuera_de_presupuesto"] == 0
    con = experimento.resumir(lento, presupuesto=60.0)
    assert con["m"]["fuera_de_presupuesto"] == 1


# --- La precisión que no se puede medir (IT-110) ---
#
# Una respuesta de listado redactada en prosa no enumera nada, así que su
# precisión es None y no cero. Lo que se comprueba aquí es que ese None no se
# cuele en las medias como un cero, que es lo que hundía la cifra de los
# modelos que redactan en prosa.


def _fila_listado(id_: str, precision, cobertura, familia="menciones"):
    """Fila de listado mínima, para no repetir el diccionario entero.

    Args:
        id_: Identificador de la pregunta.
        precision: Precisión medida, o ``None`` si la respuesta fue en prosa.
        cobertura: Cobertura medida.
        familia: Familia de la pregunta.

    Returns:
        La fila tal como la escribe el registro.
    """
    return {
        "modelo": "m",
        "id": id_,
        "familia": familia,
        "respuesta": "…",
        "fragmentos": 3,
        "segundos_generar": 10.0,
        "segundos_recuperar": 0.0,
        "precision": precision,
        "cobertura": cobertura,
        "inventadas": [],
        "omitidas": 0,
        "esperadas": 1,
        "titulaciones_inventadas": [],
    }


def test_la_prosa_no_entra_en_la_media_de_precision():
    """Regresión del cribado del 22/08/2026.

    Con la respuesta en prosa contando como 0,0 la media salía 0,500 y decía
    que la mitad de lo enumerado era falso. No se enumeró nada falso: no se
    enumeró nada.
    """
    filas = [_fila_listado("G-1", 1.0, 1.0), _fila_listado("G-2", None, 1.0)]
    resumen = experimento.resumir(filas)["m"]
    assert resumen["precision"] == 1.0
    assert resumen["listados"] == 2
    assert resumen["precision_no_medible"] == 1


def test_si_ninguna_se_puede_medir_la_precision_no_es_cero_sino_nada():
    """El caso extremo: un modelo que contesta siempre en prosa.

    Devolver 0,0 aquí sería afirmar que todo lo que dijo es falso, cuando lo
    cierto es que no hay nada medido sobre lo que afirmar.
    """
    filas = [_fila_listado("G-1", None, 1.0), _fila_listado("G-2", None, 0.0)]
    resumen = experimento.resumir(filas)["m"]
    assert resumen["precision"] is None
    assert resumen["precision_no_medible"] == 2


def test_la_cobertura_si_recoge_a_quien_no_contesto():
    """Quedarse sin medir no exime: el que no dijo nada suspende igual.

    Es el caso de las tres respuestas de optativas del cribado, que daban el
    recuento («ofrece un total de 16») en lugar de la lista. Su precisión no se
    puede medir, pero su cobertura es 0.
    """
    filas = [_fila_listado("G-1", None, 0.0), _fila_listado("G-2", None, 0.0)]
    resumen = experimento.resumir(filas)["m"]
    assert resumen["precision"] is None
    assert resumen["cobertura"] == 0.0


def test_el_desglose_por_familia_tambien_aparta_la_prosa():
    filas = [
        _fila_listado("G-1", 1.0, 1.0, "menciones"),
        _fila_listado("G-2", None, 1.0, "menciones"),
        _fila_listado("G-3", None, 1.0, "optativas"),
    ]
    familias = experimento.por_familia(filas)["m"]
    assert familias["menciones"]["precision"] == 1.0
    assert familias["menciones"]["precision_no_medible"] == 1
    assert familias["optativas"]["precision"] is None
    assert familias["optativas"]["precision_no_medible"] == 1


def test_una_media_que_no_existe_se_escribe_con_un_guion():
    """`0.000` y «no se ha podido medir» no se pueden leer igual."""
    assert experimento._cifra(1.0) == "1.000"
    assert experimento._cifra(0.5) == "0.500"
    # Cero sí es una cifra: significa que todo lo enumerado era falso, y eso
    # tiene que poder distinguirse del guion de «no se ha podido medir».
    assert experimento._cifra(0.0) == "0.000"
    assert experimento._cifra(None) == "—"


def test_el_informe_declara_cuantas_quedaron_sin_medir(tmp_path):
    """Si el informe no lo dice, la media engaña sin que se note."""
    destino = tmp_path / "informe.md"
    filas = [_fila_listado("G-1", 1.0, 1.0), _fila_listado("G-2", None, 1.0)]
    experimento.informe(filas, {"procedencia_del_dataset": {}}, destino)
    texto = destino.read_text(encoding="utf-8")
    assert "Sin medir" in texto
    assert "1/2" in texto
    assert "su precisión no es cero, no existe" in texto


def test_el_informe_no_revienta_cuando_no_hay_nada_que_promediar(tmp_path):
    """Todas en prosa: la tabla tiene que escribirse igual, con guiones."""
    destino = tmp_path / "informe.md"
    filas = [_fila_listado("G-1", None, 1.0), _fila_listado("G-2", None, 0.0)]
    experimento.informe(filas, {"procedencia_del_dataset": {}}, destino)
    texto = destino.read_text(encoding="utf-8")
    assert "| — |" in texto
    assert "2/2" in texto


# --- El bloque de datos brutos del ADR-0005 (IT-36) ---


def test_el_bloque_del_adr_lleva_sus_marcas_y_las_cifras():
    """Sin las marcas, volver a ejecutar el guion pisaría el ADR entero."""
    filas = [_fila_listado("G-1", 1.0, 1.0), _fila_listado("G-2", None, 1.0)]
    bloque = experimento.bloque_adr(filas, {"procedencia_del_dataset": {}})
    assert bloque.startswith(experimento.MARCA_INICIO)
    assert bloque.rstrip().endswith(experimento.MARCA_FIN)
    assert "Comparativa de los candidatos" in bloque
    assert "1/2" in bloque


def test_el_bloque_declara_la_procedencia_del_corpus():
    """Una tabla sin decir de qué extracción sale no es reproducible."""
    filas = [_fila_listado("G-1", 1.0, 1.0)]
    bloque = experimento.bloque_adr(
        filas,
        {
            "procedencia_del_dataset": {
                "fecha_extraccion": "2026-08-16",
                "origen": "https://eps.ujaen.es/grados",
            }
        },
    )
    assert "2026-08-16" in bloque
    assert "https://eps.ujaen.es/grados" in bloque


def test_el_bloque_avisa_si_las_respuestas_son_de_dos_servidores():
    """Ya pasó con la criba amplia: la tabla comparaba también los servidores."""
    una = _fila_listado("G-1", 1.0, 1.0)
    otra = _fila_listado("G-2", 1.0, 1.0)
    una["servidor"] = "0.23.2"
    otra["servidor"] = "0.32.14"
    bloque = experimento.bloque_adr([una, otra], {"procedencia_del_dataset": {}})
    assert "MEZCLADAS" in bloque
    assert "0.23.2" in bloque and "0.32.14" in bloque


def test_con_un_solo_servidor_no_hay_aviso():
    fila = _fila_listado("G-1", 1.0, 1.0)
    fila["servidor"] = "0.32.14"
    bloque = experimento.bloque_adr([fila], {"procedencia_del_dataset": {}})
    assert "MEZCLADAS" not in bloque
    assert "0.32.14" in bloque


def test_escribir_el_adr_solo_toca_lo_que_hay_entre_las_marcas(tmp_path, monkeypatch):
    """Lo escrito a mano alrededor del bloque tiene que sobrevivir intacto."""
    adr = tmp_path / "adr-0005.md"
    adr.write_text(
        "# ADR-0005\n\n## Decisión\n\nLa escribe el autor.\n\n"
        f"{experimento.MARCA_INICIO}\nviejo\n{experimento.MARCA_FIN}\n\n"
        "## Referencias\n\nY esto también es suyo.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(experimento, "RUTA_ADR", adr)
    experimento.escribir_adr(
        f"{experimento.MARCA_INICIO}\nnuevo\n{experimento.MARCA_FIN}"
    )
    texto = adr.read_text(encoding="utf-8")
    assert "nuevo" in texto and "viejo" not in texto
    assert "La escribe el autor." in texto
    assert "Y esto también es suyo." in texto


def test_escribir_el_adr_falla_si_no_existe(tmp_path, monkeypatch):
    """El ADR lo abre la tarjeta, no el guion: si falta, es que algo va mal."""
    monkeypatch.setattr(experimento, "RUTA_ADR", tmp_path / "no-existe.md")
    with pytest.raises(SystemExit, match="No existe"):
        experimento.escribir_adr("da igual")


def test_escribir_el_adr_falla_si_faltan_las_marcas(tmp_path, monkeypatch):
    """Escribir al final de un fichero que no lo esperaba lo desordena en silencio."""
    adr = tmp_path / "adr-0005.md"
    adr.write_text("# ADR-0005\n\nSin marcas.\n", encoding="utf-8")
    monkeypatch.setattr(experimento, "RUTA_ADR", adr)
    with pytest.raises(SystemExit, match="marcas"):
        experimento.escribir_adr("da igual")
    assert adr.read_text(encoding="utf-8") == "# ADR-0005\n\nSin marcas.\n"

"""Pruebas de las sugerencias de preguntas (Fase 3).

Sin red y sin modelo: el incrustador es falso e inyectado, y el índice se
construye con el propio ``indexer`` en la carpeta temporal de la prueba, igual
que en ``test_recuperador.py``. Se usa un índice de verdad, y no un doble que
finja contar filas, porque lo que hay que comprobar es que la expresión de
filtrado la entiende LanceDB: una expresión mal escrita no da error, devuelve
cero filas, y el resultado sería no ofrecer nunca esa pregunta.

Los nombres de titulación y el reparto de orígenes son los del corpus real
---curso 2026-27---:
Informática con menciones y sin TFG indexado, Organización Industrial al
revés, y el doble grado internacional con Schmalkalden, que no tiene ni una
asignatura.

Hay además una prueba que se ejecuta contra el índice real, si está
construido, para comprobar que ninguna plantilla del banco se ha quedado sin
respaldo. Se salta sola, con su motivo, cuando el índice no está: no se
versiona.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tfg_uja.indexacion.incrustaciones import MODELO
from tfg_uja.indexacion.indexer import reconstruir_indice
from tfg_uja.dialogo.recuperador import abrir_indice, catalogo_del_indice
from tfg_uja.aplicacion.sugerencias import (
    ARRANQUE_CATALOGO,
    DEL_AMBITO,
    MAXIMO,
    PETICION_DE_CONSEJO,
    PLANTILLAS,
    _preguntas,
    sugerencias_para,
)

DIMENSION = 8

RAIZ = Path(__file__).resolve().parent.parent

#: Índice del corpus completo. No se versiona: se construye con
#: ``py -m tfg_uja.indexacion.indexer data/chunks.json data/indice_lance``.
INDICE_REAL = RAIZ / "data" / "indice_lance"

ELECTRICA = "Grado en Ingeniería Eléctrica"
ELECTRONICA = "Grado en Ingeniería Electrónica Industrial"
INFORMATICA = "Grado en Ingeniería Informática"
MECANICA = "Grado en Ingeniería Mecánica"
ORGANIZACION = "Grado en Ingeniería de Organización Industrial"
SCHMALKALDEN = (
    "Doble Grado en Ingeniería Mecánica (Internacional - University of "
    "Applied Sciences Schmalkalden, Alemania)"
)

#: Catálogo que el índice graba de sí mismo, tal como lo devuelve
#: ``catalogo_del_indice``.
CATALOGO = [
    ELECTRICA,
    ELECTRONICA,
    INFORMATICA,
    MECANICA,
    ORGANIZACION,
    SCHMALKALDEN,
]


def incrustador_falso(textos: list[str]) -> list[list[float]]:
    """Incrustador determinista.

    Aquí no se busca por similitud ---las sugerencias se cuentan, no se
    buscan---, pero el indexador necesita vectores para crear la tabla.
    """
    return [[float(len(t) % 97)] + [0.0] * (DIMENSION - 1) for t in textos]


def chunk(
    origen: str,
    nombre: str,
    grados: list[str],
    tipo_asignatura: str = "",
    curso: str = "",
) -> dict[str, Any]:
    """Fragmento con la forma exacta que emite el fragmentador.

    El tipo y el curso van como argumentos, y no siempre vacíos, porque cuatro
    plantillas del banco filtran por ellos: sin fragmentos que los lleven, esas
    cuatro no se probarían y podrían estar mal escritas sin que nada fallara.
    """
    return {
        "tipo": "chunk",
        "origen": origen,
        "grados": grados,
        "codigos": [None] * len(grados),
        "nombre": nombre,
        "texto": f"{nombre}. Contenido de prueba.",
        "tipo_asignatura": tipo_asignatura,
        "curso": curso,
        "chunk_index": 0,
        "total_chunks": 1,
    }


#: Reparto copiado del índice real, en pequeño. Lo que importa es que ninguna
#: titulación lo tenga todo: Informática tiene menciones y no tiene TFG,
#: Organización Industrial tiene TFG y no tiene menciones, y el doble grado
#: internacional solo tiene ficha, porque la EPSJ no le publica asignaturas.
CHUNKS = [
    chunk("catalogo", "Titulaciones que se imparten en la EPSJ", CATALOGO),
    # Informática
    chunk("ficha_titulacion", f"Datos generales del {INFORMATICA}", [INFORMATICA]),
    chunk(
        "plan_de_estudios",
        f"Obligatorias de primer curso del {INFORMATICA}",
        [INFORMATICA],
        curso="Primer curso",
    ),
    chunk(
        "plan_de_estudios",
        f"Obligatorias de cuarto curso del {INFORMATICA}",
        [INFORMATICA],
        curso="Cuarto curso",
    ),
    chunk("mencion", f"Menciones del {INFORMATICA}", [INFORMATICA]),
    chunk("salidas", INFORMATICA, [INFORMATICA]),
    chunk(
        "guia",
        "Fundamentos de la programación",
        [INFORMATICA],
        tipo_asignatura="FB",
        curso="Primer curso",
    ),
    chunk(
        "guia",
        "Desarrollo de videojuegos",
        [INFORMATICA],
        tipo_asignatura="OP",
    ),
    chunk(
        "guia",
        "Sistemas de información",
        [INFORMATICA],
        tipo_asignatura="OB",
        curso="Cuarto curso",
    ),
    # Organización Industrial: sin menciones, con TFG
    chunk("ficha_titulacion", f"Datos generales del {ORGANIZACION}", [ORGANIZACION]),
    chunk(
        "plan_de_estudios",
        f"Obligatorias de primer curso del {ORGANIZACION}",
        [ORGANIZACION],
        curso="Primer curso",
    ),
    chunk("salidas", ORGANIZACION, [ORGANIZACION]),
    chunk(
        "guia",
        "Trabajo fin de grado",
        [ORGANIZACION],
        tipo_asignatura="TFG",
    ),
    chunk(
        "guia",
        "Física aplicada",
        [ORGANIZACION],
        tipo_asignatura="FB",
        curso="Primer curso",
    ),
    # El doble grado internacional: solo ficha
    chunk("ficha_titulacion", f"Datos generales del {SCHMALKALDEN}", [SCHMALKALDEN]),
    # Las tres restantes, con lo justo para que haya de dónde sacar «otras»
    chunk("ficha_titulacion", f"Datos generales del {ELECTRICA}", [ELECTRICA]),
    chunk(
        "plan_de_estudios",
        f"Obligatorias de primer curso del {ELECTRICA}",
        [ELECTRICA],
        curso="Primer curso",
    ),
    chunk("ficha_titulacion", f"Datos generales del {ELECTRONICA}", [ELECTRONICA]),
    chunk("salidas", ELECTRONICA, [ELECTRONICA]),
    chunk("ficha_titulacion", f"Datos generales del {MECANICA}", [MECANICA]),
    chunk(
        "plan_de_estudios",
        f"Obligatorias de primer curso del {MECANICA}",
        [MECANICA],
        curso="Primer curso",
    ),
    chunk(
        "guia",
        "Mecánica de fluidos",
        [MECANICA],
        tipo_asignatura="OB",
        curso="Cuarto curso",
    ),
]


def construir(ruta: Path, chunks: list[dict[str, Any]]) -> Any:
    """Construye un índice con esos fragmentos y devuelve la tabla abierta.

    Args:
        ruta: Carpeta temporal de la prueba.
        chunks: Fragmentos a indexar.

    Returns:
        La tabla, ya abierta.
    """
    ruta_chunks = ruta / "chunks.json"
    ruta_chunks.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    ruta_indice = ruta / "indice"
    reconstruir_indice(ruta_chunks, ruta_indice, incrustador_falso, MODELO)
    return abrir_indice(ruta_indice, MODELO)


@pytest.fixture()
def tabla(tmp_path) -> Any:
    """Índice pequeño con el reparto de orígenes del corpus real."""
    return construir(tmp_path, CHUNKS)


def preguntas_de(titulacion: str) -> set[str]:
    """Todas las preguntas que el banco puede formular sobre una titulación.

    Sirve para saber de quién habla una sugerencia **sin buscar el nombre
    dentro del texto**, que es la trampa de siempre en este corpus: «Grado en
    Ingeniería Mecánica» es subcadena del doble grado internacional, así que
    con una comprobación por subcadena las preguntas del doble contarían
    también como del simple. Aquí se compara la pregunta entera.

    Args:
        titulacion: Nombre del catálogo.

    Returns:
        Las preguntas del banco ya rellenas con ese nombre.
    """
    return {pregunta.format(titulacion=titulacion) for _, pregunta in PLANTILLAS}


def nombradas(preguntas: list[str]) -> set[str]:
    """Titulaciones del catálogo de las que habla alguna de las preguntas.

    Args:
        preguntas: Lo que devuelve ``sugerencias_para``.

    Returns:
        Los nombres del catálogo a los que se refiere alguna.
    """
    return {t for t in CATALOGO if preguntas_de(t) & set(preguntas)}


# --- El fallo que reportó el autor ---


def test_no_parece_que_solo_se_haya_preparado_una_titulacion(tabla):
    """Regresión del fallo que encontró el autor probando la interfaz.

    Sus palabras: «solo hablan del grado de ingeniería informática, parece que
    solo hemos preparado ese». Pasaba porque los cuatro huecos se llenaban con
    preguntas de la titulación del ámbito. Ahora la mitad se reserva a otras,
    así que hablando de Informática tienen que salir nombradas varias.
    """
    preguntas = sugerencias_para(tabla, [INFORMATICA], CATALOGO)
    assert len(nombradas(preguntas)) > 1
    assert not set(preguntas) <= preguntas_de(INFORMATICA)


def test_del_ambito_salen_como_mucho_los_huecos_reservados(tabla):
    """Ni uno más: el resto es de otras titulaciones, siempre."""
    preguntas = sugerencias_para(tabla, [INFORMATICA], CATALOGO)
    assert len(set(preguntas) & preguntas_de(INFORMATICA)) == DEL_AMBITO


# --- Determinismo y variedad ---


def test_el_mismo_desplazamiento_da_siempre_lo_mismo(tabla):
    """Es determinista, y por eso se puede comprobar qué ofrece.

    Un sorteo sin semilla daría variedad y ninguna forma de escribir esta
    prueba.
    """
    for desplazamiento in range(4):
        primera = sugerencias_para(tabla, [INFORMATICA], CATALOGO, desplazamiento)
        segunda = sugerencias_para(tabla, [INFORMATICA], CATALOGO, desplazamiento)
        assert primera == segunda


def test_el_desplazamiento_cambia_lo_que_se_ofrece(tabla):
    """Dos turnos seguidos no repiten la misma lista de botones."""
    tandas = [sugerencias_para(tabla, [INFORMATICA], CATALOGO, d) for d in range(4)]
    assert len({tuple(t) for t in tandas}) > 1


def test_el_desplazamiento_tambien_varia_el_arranque(tabla):
    """De las dos preguntas de catálogo se enseña una, y va alternando."""
    primera = sugerencias_para(tabla, [], CATALOGO, 0)
    segunda = sugerencias_para(tabla, [], CATALOGO, 1)
    assert primera[0] == ARRANQUE_CATALOGO[0]
    assert segunda[0] == ARRANQUE_CATALOGO[1]


# --- La regresión que motiva el módulo entero ---


def test_no_se_pregunta_por_menciones_a_quien_no_las_tiene(tabla):
    """Organización Industrial no tiene ni una mención indexada.

    Con una lista fija de sugerencias se le ofrecería igual, y lo que llegaría
    al modelo serían fragmentos de otra cosa: sobre el índice real esa
    pregunta trae cinco fragmentos de plan de estudios, salidas y ficha, y
    ninguno de mención.
    """
    for desplazamiento in range(len(PLANTILLAS)):
        preguntas = sugerencias_para(tabla, [ORGANIZACION], CATALOGO, desplazamiento)
        propias = set(preguntas) & preguntas_de(ORGANIZACION)
        assert not any("menciones" in p for p in propias)


def test_de_la_titulacion_sin_asignaturas_solo_se_ofrece_la_ficha(tabla):
    """Al doble grado internacional la EPSJ no le publica ni una asignatura."""
    preguntas = sugerencias_para(tabla, [SCHMALKALDEN], CATALOGO)
    suyas = set(preguntas) & preguntas_de(SCHMALKALDEN)
    assert suyas == {
        f"¿Cuántas asignaturas tiene el {SCHMALKALDEN} y cómo se reparten por curso?",
    }


def test_solo_se_ofrece_lo_que_el_indice_respalda(tabla):
    """Ninguna pregunta habla de algo que su titulación no tenga indexado.

    Se comprueba plantilla a plantilla y titulación a titulación: lo que sale
    de ``sugerencias_para`` tiene que estar entre lo que ``_preguntas``
    respalda para esa misma titulación.
    """
    for titulacion in CATALOGO:
        respaldadas = set(_preguntas(tabla, titulacion, 0))
        for desplazamiento in range(len(PLANTILLAS)):
            for pregunta in sugerencias_para(
                tabla, [titulacion], CATALOGO, desplazamiento
            ):
                if pregunta in preguntas_de(titulacion):
                    assert pregunta in respaldadas


# --- Tope y repeticiones ---


def test_nunca_se_pasa_del_maximo_ni_se_repiten(tabla):
    """Cuatro botones como mucho, y los cuatro distintos."""
    ambitos = [[], [INFORMATICA], [INFORMATICA, ORGANIZACION], CATALOGO]
    for ambito in ambitos:
        for desplazamiento in range(len(PLANTILLAS)):
            preguntas = sugerencias_para(tabla, ambito, CATALOGO, desplazamiento)
            assert len(preguntas) <= MAXIMO
            assert len(set(preguntas)) == len(preguntas)


# --- Arranque ---


def test_al_arrancar_se_ofrece_el_catalogo_el_consejo_y_otras(tabla):
    """Sin ámbito: por dónde empezar y titulaciones concretas que mirar."""
    preguntas = sugerencias_para(tabla, [], CATALOGO)
    assert preguntas[0] in ARRANQUE_CATALOGO
    assert preguntas[1] == PETICION_DE_CONSEJO
    assert len(preguntas) == MAXIMO
    assert len(nombradas(preguntas[2:])) == MAXIMO - DEL_AMBITO


def test_sin_fragmentos_de_catalogo_no_se_ofrece_esa_pregunta(tmp_path):
    """Un índice de un corpus sin fragmentos de catálogo no la ofrece.

    No es un caso inventado: los fragmentos de catálogo los empezó a emitir el
    fragmentador más tarde que el resto, y reindexar un ``chunks.json`` viejo
    no falla ---el indexador lo admite a propósito---, así que la tabla existe
    y responde, pero sin esas filas.
    """
    sin_catalogo = [c for c in CHUNKS if c["origen"] != "catalogo"]
    preguntas = sugerencias_para(construir(tmp_path, sin_catalogo), [], CATALOGO)
    assert not any(p in ARRANQUE_CATALOGO for p in preguntas)
    assert preguntas[0] == PETICION_DE_CONSEJO


def test_un_nombre_fuera_del_catalogo_no_llega_al_filtro(tabla):
    """Lo que no declara el índice no se filtra: se cae al arranque.

    Filtrar por una titulación que el índice no tiene devuelve cero fragmentos
    y todas sus preguntas serían un rechazo garantizado, que es justo lo que
    este módulo existe para evitar.
    """
    ajena = ["Grado en Medicina"]
    assert sugerencias_para(tabla, ajena, CATALOGO) == sugerencias_para(
        tabla, [], CATALOGO
    )


# --- Varias titulaciones en el ámbito ---


def test_con_varias_en_el_ambito_va_una_de_cada(tabla):
    """El ámbito ambiguo reparte sus huecos, no se los queda la primera.

    Es lo que pasa al escribir «eléctrica», que resuelve al grado simple y a
    sus dobles: al pulsar una sugerencia el ámbito se queda en esa sola.
    """
    preguntas = sugerencias_para(tabla, [INFORMATICA, ORGANIZACION], CATALOGO)
    assert len(set(preguntas) & preguntas_de(INFORMATICA)) == 1
    assert len(set(preguntas) & preguntas_de(ORGANIZACION)) == 1


def test_si_el_ambito_es_todo_el_catalogo_no_hay_otras(tabla):
    """Con las doce dentro no queda ninguna de fuera que ofrecer.

    No sobra: la rotación de una lista vacía es lo único que separa este caso
    de una división por cero.
    """
    preguntas = sugerencias_para(tabla, CATALOGO, CATALOGO)
    assert len(preguntas) == DEL_AMBITO


# --- Contra el índice real ---


def test_ninguna_plantilla_se_ha_quedado_sin_respaldo():
    """Toda plantilla del banco la respalda alguna titulación del corpus.

    Una plantilla que no case con ningún fragmento no se ofrecería nunca, y no
    fallaría nada: se quedaría ahí, en silencio, aparentando un banco más
    grande del que hay. Se comprueba contra el corpus completo porque el
    índice pequeño de estas pruebas no lo contiene todo.
    """
    if not INDICE_REAL.exists():
        pytest.skip(
            f"no hay índice vectorial en {INDICE_REAL.relative_to(RAIZ)}; "
            "se construye con «py -m tfg_uja.indexacion.indexer data/chunks.json "
            "data/indice_lance»"
        )
    tabla_real = abrir_indice(INDICE_REAL, MODELO)
    catalogo = catalogo_del_indice(INDICE_REAL)
    respaldadas = {
        pregunta
        for titulacion in catalogo
        for pregunta in _preguntas(tabla_real, titulacion, 0)
    }
    huerfanas = [
        pregunta
        for _, pregunta in PLANTILLAS
        if not any(pregunta.format(titulacion=t) in respaldadas for t in catalogo)
    ]
    assert huerfanas == []

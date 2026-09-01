"""Tests del troceado del dataset (IT-08 e IT-09).

La fixture ``dataset_muestra.json`` contiene items REALES extraídos del
dataset generado por el spider: la guía más corta del dataset ("Sistemas de
información para el negocio electrónico", 395 caracteres), una guía larga
("Aprovechamiento y ahorro energético", ~6.000), una guía que activó el
fallback en producción ("Cartografía"), una asignatura sin guía con mención
("Microelectrónica") y las salidas profesionales de Informática, junto a
sus items de asignatura para los metadatos de encabezado.
"""

import json
import threading
from pathlib import Path

import pytest

from tfg_uja.indexacion import chunker
from tfg_uja.indexacion.chunker import (
    TAMANO_MAXIMO,
    TAMANO_MINIMO,
    _fusionar_pequenos,
    procedencia_de,
    trocear_dataset,
)


def _de_origen(chunks, origen):
    """Chunks de un origen concreto.

    Desde IT-100 cualquier dataset con asignaturas genera ademas sus
    fragmentos de `plan_de_estudios`, asi que asertar sobre el total acopla
    cada prueba a tipos de fragmento que no esta comprobando. Filtrar por
    origen deja cada prueba mirando lo suyo y la hace inmune a que se anadan
    tipos nuevos.
    """
    return [c for c in chunks if c["origen"] == origen]


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def muestra():
    return json.loads((FIXTURES / "dataset_muestra.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def chunks(muestra):
    return trocear_dataset(muestra)


def _de(chunks, codigo):
    return [c for c in chunks if codigo in c["codigos"]]


# --- IT-08: troceo semántico base ---


def test_una_guia_corta_produce_un_solo_chunk(chunks):
    # "Sistemas de información para el negocio electrónico": 395 caracteres.
    resultado = _de(chunks, "13312032")
    assert len(resultado) == 1
    assert resultado[0]["chunk_index"] == 0
    assert resultado[0]["total_chunks"] == 1


def test_una_guia_larga_se_divide_en_varios_chunks(chunks):
    # "Aprovechamiento y ahorro energético": ~6.000 caracteres reales.
    resultado = _de(chunks, "13013001")
    assert len(resultado) > 1
    assert [c["chunk_index"] for c in resultado] == list(range(len(resultado)))
    assert all(c["total_chunks"] == len(resultado) for c in resultado)


def test_ningun_chunk_supera_el_maximo(chunks):
    # Invariante estricto: el chunk COMPLETO (encabezado incluido) respeta
    # el máximo. La fixture incluye la guía real 13013009 («Manutención y
    # almacenaje»), que violaba este invariante antes de descontar el
    # encabezado del presupuesto de tamaño.
    assert all(len(c["texto"]) <= TAMANO_MAXIMO for c in chunks)


def test_ningun_chunk_mezcla_asignaturas(chunks):
    # Cada chunk lleva el código de UNA asignatura y su texto no contiene
    # el nombre de las demás asignaturas de la muestra.
    nombres = {
        "13312032": "Sistemas de información para el negocio electrónico",
        "13013001": "Aprovechamiento y ahorro energético",
    }
    for codigo, nombre_ajeno in nombres.items():
        for chunk in chunks:
            if codigo not in chunk["codigos"] and chunk["origen"] == "guia":
                assert nombre_ajeno not in chunk["texto"]


def test_cada_chunk_es_autocontenido(chunks):
    # Todo chunk de guía empieza por el encabezado con nombre y grado.
    for chunk in chunks:
        if chunk["origen"] == "guia":
            assert chunk["texto"].startswith("«")
            assert any(g in chunk["texto"].split("\n")[0] for g in chunk["grados"])


def test_una_guia_con_fallback_tambien_se_trocea(chunks):
    # "Cartografía" (13212001) activó el fallback en producción: su
    # cuerpo_general (~6.400 chars) debe trocearse igualmente.
    resultado = _de(chunks, "13212001")
    assert len(resultado) > 1


def test_el_troceo_es_determinista(muestra):
    assert trocear_dataset(muestra) == trocear_dataset(muestra)


# --- IT-09: fusión de pequeños y asignaturas sin guía ---


def test_ningun_chunk_queda_por_debajo_del_minimo(chunks):
    # La fusión debe absorber los fragmentos residuales del troceo.
    #
    # El invariante real no es «ningún chunk baja del mínimo» sino «ninguno
    # baja del mínimo pudiendo evitarlo»: una unidad cuyo texto completo es
    # más corto que el umbral no tiene con qué fusionarse, y el ADR-0001 deja
    # claro que el mínimo es una preferencia y solo el máximo es restricción
    # dura. Antes de IT-100 ninguna unidad del corpus era tan corta y la
    # distinción no se notaba; los listados de plan de estudios de una
    # titulación con pocas optativas sí lo son.
    cortos = [
        c for c in chunks if len(c["texto"]) < TAMANO_MINIMO and c["total_chunks"] > 1
    ]
    assert not cortos, (
        f"{len(cortos)} chunks por debajo del mínimo teniendo vecinos con los "
        f"que fusionarse (p. ej. {cortos[0]['nombre']!r})"
    )


def test_asignatura_sin_guia_genera_chunk_informativo(chunks):
    # "Microelectrónica" (13113006) no tiene guía publicada.
    resultado = [c for c in chunks if c["origen"] == "asignatura_sin_guia"]
    assert len(resultado) == 1
    chunk = resultado[0]
    assert chunk["codigos"] == ["13113006"]
    assert "Microelectrónica" in chunk["texto"]
    assert "no está publicada" in chunk["texto"]
    # Sus metadatos básicos viajan en el encabezado (tipo y mención reales).
    assert "optativa" in chunk["texto"]
    assert "Sistemas electrónicos" in chunk["texto"]


def test_asignatura_no_ofertada_lo_indica_en_el_encabezado(chunks):
    # Microelectrónica está además marcada como no ofertada en el dataset.
    chunk = next(c for c in chunks if c["origen"] == "asignatura_sin_guia")
    assert "No ofertada" in chunk["texto"]


# --- Salidas profesionales ---


def test_las_salidas_de_un_grado_forman_su_propia_unidad(chunks):
    resultado = [c for c in chunks if c["origen"] == "salidas"]
    assert resultado
    for chunk in resultado:
        assert chunk["codigos"] == [None]
        assert chunk["texto"].startswith("Salidas profesionales del ")
        assert (
            "Programador de aplicaciones" in chunk["texto"] or chunk["chunk_index"] > 0
        )


# --- IT (deduplicación): guías compartidas entre titulaciones ---


def test_una_asignatura_compartida_se_deduplica_en_una_unidad(muestra):
    # Se construye una guía idéntica en dos titulaciones distintas (mismo
    # nombre y mismo contenido): deben fusionarse en una sola unidad cuyo
    # campo grados enumere ambas, en vez de duplicar el texto en el índice.
    guia_a = {
        "tipo": "guia",
        "grado": "Grado A",
        "codigo": "10000001",
        "nombre": "Álgebra",
        "fallback": False,
        "resumen": "Espacios vectoriales y aplicaciones lineales.",
        "temario": "Tema 1. Matrices. Tema 2. Determinantes. Tema 3. Diagonalización.",
    }
    guia_b = {**guia_a, "grado": "Grado B", "codigo": "20000001"}
    asig_a = {
        "tipo": "asignatura",
        "grado": "Grado A",
        "codigo": "10000001",
        "nombre": "Álgebra",
        "tipo_asignatura": "FB",
        "ects": "6",
        "menciones": [],
        "ofertada": True,
        "tiene_guia": True,
    }
    asig_b = {**asig_a, "grado": "Grado B", "codigo": "20000001"}
    chunks = trocear_dataset([asig_a, asig_b, guia_a, guia_b])
    algebra = [c for c in chunks if c["nombre"] == "Álgebra"]
    # Una sola unidad (no dos), con las dos titulaciones y sus dos códigos.
    assert {tuple(c["grados"]) for c in algebra} == {("Grado A", "Grado B")}
    assert algebra[0]["codigos"] == ["10000001", "20000001"]
    assert "2 titulaciones" in algebra[0]["texto"]


def test_no_fusiona_asignaturas_distintas_con_el_mismo_texto(muestra):
    # Dos asignaturas DISTINTAS (nombres distintos) con texto idéntico —el
    # caso real del fallback de Smart Grids y Técnicas gráfica— no deben
    # fusionarse: la clave de deduplicación incluye el nombre.
    base_guia = {
        "tipo": "guia",
        "grado": "Grado A",
        "fallback": True,
        "cuerpo_general": "Texto genérico idéntico de respaldo.",
    }
    g1 = {**base_guia, "codigo": "30000001", "nombre": "Asignatura Uno"}
    g2 = {**base_guia, "codigo": "30000002", "nombre": "Asignatura Dos"}
    chunks = trocear_dataset([g1, g2])
    nombres = {c["nombre"] for c in chunks}
    assert nombres == {"Asignatura Uno", "Asignatura Dos"}
    assert all(len(c["grados"]) == 1 for c in chunks)


# --- IT-91: asignaturas sin código publicado ---

# Las tres asignaturas de abajo son REALES del plan 2025 del Grado en Ingeniería
# Geomática y Topográfica, copiadas literalmente del dataset (nombre, tipo y
# ECTS). Esa titulación publica 18 asignaturas SIN código, y "Trabajo de Fin de
# Grado" es la última del listado: es la que, con la clave anterior
# `(grado, codigo)`, sobrescribía a todas las demás.
#
# Lo único que no procede de la fuente es que una de ellas tenga guía: hoy
# ninguna de las 57 asignaturas sin código del dataset la tiene publicada, y por
# eso el defecto nunca llegó a manifestarse. Se construye ese escenario a
# propósito, porque es justo la condición que debe quedar blindada antes de
# regenerar el corpus (IT-80).
_GRADO_GEOMATICA = "Grado en Ingeniería Geomática y Topográfica (plan 2025)"


def _asignatura_sin_codigo(nombre, tipo_asignatura, ects, tiene_guia=False):
    return {
        "tipo": "asignatura",
        "grado": _GRADO_GEOMATICA,
        "codigo": "",
        "nombre": nombre,
        "tipo_asignatura": tipo_asignatura,
        "ects": ects,
        "menciones": [],
        "ofertada": True,
        "tiene_guia": tiene_guia,
    }


def test_guia_de_asignatura_sin_codigo_lleva_su_propio_encabezado():
    # Regresión de IT-91: con la clave `(grado, codigo)`, las 18 asignaturas
    # sin código de esta titulación colapsaban en la clave `(grado, "")` y la
    # última ganaba. El chunk de "Cartografía y SIG II" salía encabezado como
    # «Trabajo de Fin de Grado» de 12 ECTS: una atribución falsa dentro del
    # único campo que se vectoriza.
    cartografia = _asignatura_sin_codigo("Cartografía y SIG II", "OB", "6", True)
    metodos = _asignatura_sin_codigo("Métodos topográficos", "OB", "6")
    tfg = _asignatura_sin_codigo("Trabajo de Fin de Grado", "TFG", "12")
    guia = {
        "tipo": "guia",
        "grado": _GRADO_GEOMATICA,
        "codigo": "",
        "nombre": "Cartografía y SIG II",
        "fallback": False,
        "resumen": "Sistemas de información geográfica y análisis espacial.",
        "temario": "Tema 1. Modelos de datos. Tema 2. Análisis raster y vectorial.",
    }
    chunks = trocear_dataset([cartografia, metodos, tfg, guia])

    unidad = [c for c in chunks if c["origen"] == "guia"]
    assert len(unidad) == 1
    encabezado = unidad[0]["texto"].split("\n")[0]
    assert encabezado.startswith("«Cartografía y SIG II»")
    # Los metadatos del encabezado son los suyos, no los de otra asignatura.
    assert "6 ECTS" in encabezado
    assert "Trabajo de Fin de Grado" not in encabezado
    assert "12 ECTS" not in encabezado


def test_asignaturas_sin_codigo_no_se_pisan_entre_ellas():
    # Las tres comparten `codigo` vacío: cada una debe conservar su propio
    # chunk informativo con sus metadatos, sin que ninguna absorba a las otras.
    #
    # Este invariante YA se cumplía antes de IT-91 (el chunk informativo de una
    # asignatura sin guía se genera recorriendo los items, sin pasar por la
    # clave que fallaba), así que no es un test de regresión: es la red que
    # avisaría si ese recorrido pasara algún día a agruparse por código.
    asignaturas = [
        _asignatura_sin_codigo("Cartografía y SIG II", "OB", "6"),
        _asignatura_sin_codigo("Métodos topográficos", "OB", "6"),
        _asignatura_sin_codigo("Trabajo de Fin de Grado", "TFG", "12"),
    ]
    chunks = _de_origen(trocear_dataset(asignaturas), "asignatura_sin_guia")

    assert len(chunks) == 3
    for chunk in chunks:
        assert chunk["texto"].startswith(f"«{chunk['nombre']}»")
    # Los 12 ECTS son solo del TFG: si otra asignatura los mostrara, sería que
    # ha heredado los metadatos equivocados.
    por_nombre = {c["nombre"]: c["texto"] for c in chunks}
    assert "12 ECTS" in por_nombre["Trabajo de Fin de Grado"]
    assert "6 ECTS" in por_nombre["Cartografía y SIG II"]
    assert "6 ECTS" in por_nombre["Métodos topográficos"]


# --- IT-90: procedencia del corpus ---


def _guia_de(nombre, curso, grado="Grado A"):
    return {
        "tipo": "guia",
        "grado": grado,
        "codigo": "",
        "nombre": nombre,
        "curso": curso,
        "fallback": False,
        "resumen": "Resumen de la asignatura.",
        "temario": "Tema 1. Contenido.",
    }


def test_la_procedencia_arrastra_la_fecha_de_extraccion_del_dataset():
    items = [
        {"tipo": "procedencia", "fecha_extraccion": "2026-07-09"},
        _guia_de("Álgebra", "2025-26"),
    ]
    procedencia = procedencia_de(items)
    assert procedencia["tipo"] == "procedencia"
    assert procedencia["fecha_extraccion"] == "2026-07-09"
    assert procedencia["cursos"] == ["2025-26"]


def test_un_corpus_de_dos_cursos_los_enumera_los_dos():
    # Es el escenario que produce IT-80: la EPSJ publica las guías del curso
    # nuevo según las va teniendo, así que el corpus queda mezclado. Resumirlo
    # a un solo curso ocultaría de qué año es cada parte.
    items = [
        {"tipo": "procedencia", "fecha_extraccion": "2026-07-28"},
        _guia_de("Álgebra", "2025-26"),
        _guia_de("Estadística", "2026-27"),
    ]
    assert procedencia_de(items)["cursos"] == ["2025-26", "2026-27"]


def test_las_guias_sin_curso_se_cuentan_en_vez_de_suponerles_uno():
    # Si la fuente cambia el formato de sus URL, el curso deja de deducirse.
    # Debe constar cuántas guías están así, no rellenarse con el curso de al lado.
    items = [
        {"tipo": "procedencia", "fecha_extraccion": "2026-07-28"},
        _guia_de("Álgebra", "2025-26"),
        _guia_de("Física", None),
    ]
    procedencia = procedencia_de(items)
    assert procedencia["cursos"] == ["2025-26"]
    assert procedencia["guias_sin_curso"] == 1


def test_un_dataset_anterior_a_it90_no_inventa_fecha():
    # El grados.json del snapshot de julio no lleva procedencia: debe quedar
    # a None y notarse, en vez de rellenarse con la fecha del troceo.
    procedencia = procedencia_de([_guia_de("Álgebra", None)])
    assert procedencia["fecha_extraccion"] is None
    assert procedencia["cursos"] == []


def test_la_procedencia_no_se_convierte_en_un_fragmento():
    # Va en el fichero, pero no es contenido recuperable: si acabara indexada,
    # el sistema podría devolverla como respuesta a una consulta.
    items = [
        {"tipo": "procedencia", "fecha_extraccion": "2026-07-28"},
        _guia_de("Álgebra", "2025-26"),
    ]
    chunks = trocear_dataset(items)
    assert all(c["tipo"] == "chunk" for c in chunks)
    assert all("Álgebra" in c["nombre"] for c in chunks)


# --- IT-92: la fusión de fragmentos siempre termina ---

# Geometría tomada del caso real que colgó al fragmentador: la guía de
# «Minería web» (13313008) del Grado en Ingeniería Informática, en el corpus
# de 2026-27. Su encabezado ocupa 159 caracteres, así que el cuerpo dispone de
# 1340 (1500 − 159 − 1), y el troceo dejaba tres piezas de 185, 1155 y 1172.
#
# El par de las dos primeras suma 1341: excede el máximo por UN carácter, así
# que no se puede fusionar. Y al reequilibrarlo, sus únicas fronteras de frase
# son las que ya lo separaban, con lo que el reparto devuelto era idéntico al
# de partida. La función volvía a empezar y repetía lo mismo indefinidamente.
_MAXIMO_MINERIA_WEB = 1340
_MINIMO_MINERIA_WEB = 200


def _texto_de(longitud):
    """Texto de una longitud exacta terminado en punto (frontera de frase)."""
    relleno = "palabra " * ((longitud // 8) + 1)
    return relleno[: longitud - 1] + "."


def _piezas_del_caso_real():
    # 185 + 1 (salto) + 1155 = 1341 > 1340: el par no cabe junto.
    return [_texto_de(185), _texto_de(1155), _texto_de(1172)]


def _con_limite_de_tiempo(funcion, segundos=10):
    """Ejecuta una función en un hilo y falla si no termina a tiempo.

    Un bucle infinito no se puede probar con un assert normal: la prueba se
    colgaría con él y el CI se quedaría esperando hasta agotar su propio
    tiempo. Ejecutarla aparte permite que la regresión se manifieste como un
    fallo con nombre en vez de como una ejecución que no acaba nunca.
    """
    resultado = {}

    def ejecutar():
        resultado["valor"] = funcion()

    hilo = threading.Thread(target=ejecutar, daemon=True)
    hilo.start()
    hilo.join(segundos)
    assert not hilo.is_alive(), (
        "la fusión de fragmentos no terminó: un par que no cabe junto y que "
        "no se puede repartir de otra forma hacía que el bucle se repitiera "
        "indefinidamente (IT-92)"
    )
    return resultado["valor"]


def test_la_fusion_termina_con_un_par_que_no_se_puede_repartir():
    # Un único test ejecuta el caso que podría no terminar, y comprueba sobre
    # su resultado todo lo que hay que comprobar. Repartirlo en varios tests
    # parecía más limpio, pero un hilo colgado no se puede matar en Python: si
    # la regresión vuelve, cada test dejaría el suyo girando y unos
    # interferirían con otros, con lo que el resultado dejaría de ser
    # determinista. Comprobado: repartido en tres, uno de ellos pasaba.
    piezas = _piezas_del_caso_real()
    resultado = _con_limite_de_tiempo(
        lambda: _fusionar_pequenos(piezas, _MINIMO_MINERIA_WEB, _MAXIMO_MINERIA_WEB)
    )

    # La jerarquía del proyecto: el máximo es restricción dura y el mínimo una
    # preferencia. Cuando no hay manera de cumplir ambos, se conserva el
    # fragmento corto antes que producir uno que se truncaría en silencio.
    assert all(len(c) <= _MAXIMO_MINERIA_WEB for c in resultado)
    assert any(len(c) < _MINIMO_MINERIA_WEB for c in resultado)
    # Y aceptar ese fragmento corto no puede costar contenido.
    assert sum(len(c) for c in resultado) >= sum(len(p) for p in piezas)


def test_un_par_que_si_cabe_junto_se_sigue_fusionando():
    # El arreglo no debe volver conservadora la fusión normal: si el par cabe
    # bajo el máximo, se funde igual que antes. Este caso no puede colgarse,
    # así que no necesita ejecutarse aparte.
    resultado = _fusionar_pequenos(["a" * 50, "b" * 500], 200, 1340)
    assert len(resultado) == 1


# --- La fusión tampoco termina si el reparto AUMENTA el número de fragmentos ---

# El arreglo de IT-92 dejó fuera un segundo camino por el que el bucle no
# termina, y solo quedó a la vista al hacer parametrizables los tamaños de
# fragmento: con un máximo de 380 caracteres, el fragmentador se colgaba sobre
# el dataset completo.
#
# Aquel arreglo razonaba que el número de fragmentos solo podía disminuir, y
# que por eso reiniciar el recorrido tras cada fusión estaba acotado. Pero el
# reparto de un par que no cabe junto puede devolver TRES fragmentos donde
# había dos, y entonces el recuento sube. Alternando fusiones que bajan el
# recuento y repartos que lo suben, oscilaba (7, 8, 7, 8...) sin converger.
#
# Este es el caso real más pequeño que lo reproduce, reducido automáticamente
# desde el corpus de 2026-27: dos fragmentos del temario de una asignatura de
# empresa, ambos por debajo del mínimo. Juntos suman 191 caracteres y no caben
# bajo el máximo de 188; al repartirlos, sus fronteras de frase producen tres.
_TEMARIO_A = (
    "Decisiones de inversión y financiación\n"
    "- Tipos de interés: TAE, TIN, efectivo por periodos."
)
_TEMARIO_B = (
    "- Interés con inflación.\n"
    "- Capitalización simple y compuesta.\n"
    "Movimiento de capitales en el tiempo."
)
_MINIMO_TEMARIO = 100
_MAXIMO_TEMARIO = 188


def test_la_fusion_termina_cuando_el_reparto_devuelve_mas_fragmentos():
    piezas = [_TEMARIO_A, _TEMARIO_B]
    # La geometría del caso es lo que lo hace válido: si alguien "arregla" los
    # textos y dejan de cumplirla, la prueba pasaría sin ejercitar nada.
    assert all(len(p) < _MINIMO_TEMARIO for p in piezas)
    assert len(f"{_TEMARIO_A}\n{_TEMARIO_B}") > _MAXIMO_TEMARIO

    resultado = _con_limite_de_tiempo(
        lambda: _fusionar_pequenos(piezas, _MINIMO_TEMARIO, _MAXIMO_TEMARIO)
    )

    # Nunca más fragmentos de los que entraron: es justo la propiedad que
    # garantiza la terminación, porque hace que el recuento sea monótono no
    # creciente y acote los reinicios del recorrido.
    assert len(resultado) <= len(piezas)
    assert all(len(c) <= _MAXIMO_TEMARIO for c in resultado)
    # Y renunciar al reparto no puede costar contenido.
    assert sum(len(c) for c in resultado) >= sum(len(p) for p in piezas)


# --- IT-94: la guía anunciada que no llegó a extraerse ---

# Caso real del rastreo del 28/07/2026: cinco asignaturas cuya guía se sirve
# como PDF que `guia_pdf` no pudo leer. El rastreador ya había emitido la
# asignatura con `tiene_guia=True`, porque en la tabla sí había enlace, y el
# ítem de guía nunca llegó a emitirse. Se quedaban sin fragmento de guía y sin
# fragmento informativo: desaparecían del corpus enteras.
_CRIPTOGRAFIA = {
    "tipo": "asignatura",
    "grado": "Grado en Inteligencia Artificial y Ciberseguridad",
    "codigo": "15712013",
    "nombre": "Criptografía",
    "tipo_asignatura": "OB",
    "ects": "6",
    "menciones": [],
    "ofertada": True,
    "tiene_guia": True,  # la tabla enlazaba su guía...
}
# ...pero no hay ningún item `guia` para ella en el dataset.


def test_una_guia_anunciada_que_no_se_extrajo_no_borra_la_asignatura():
    chunks = _de_origen(trocear_dataset([_CRIPTOGRAFIA]), "asignatura_sin_guia")
    assert len(chunks) == 1
    assert chunks[0]["origen"] == "asignatura_sin_guia"
    assert chunks[0]["nombre"] == "Criptografía"
    assert chunks[0]["codigos"] == ["15712013"]


def test_ese_fragmento_no_afirma_que_la_guia_no_este_publicada():
    # La guía SÍ está publicada. Decir lo contrario metería una afirmación
    # falsa en el propio corpus, y el sistema se la daría por buena al
    # estudiante que preguntase por la asignatura.
    chunks = _de_origen(trocear_dataset([_CRIPTOGRAFIA]), "asignatura_sin_guia")
    texto = chunks[0]["texto"]
    assert "está publicada" in texto
    assert "no está publicada" not in texto


def test_ese_fragmento_tampoco_se_atribuye_un_fallo_propio():
    # IT-95. El texto decía «no ha podido obtenerse», que insinúa que el fallo
    # es del sistema. Se comprobó descargando las seis guías implicadas: las
    # seis se leen perfectamente y lo vacío son sus secciones en el origen.
    # Atribuirse un fallo inexistente es tan poco honesto como el error que
    # IT-94 evitó, solo que en la otra dirección.
    chunks = _de_origen(trocear_dataset([_CRIPTOGRAFIA]), "asignatura_sin_guia")
    texto = chunks[0]["texto"]
    assert "no ha podido obtenerse" not in texto
    assert "no recoge ni resumen ni temario" in texto


def test_la_asignatura_sin_guia_publicada_conserva_su_mensaje():
    # El otro caso no cambia: si la fuente no publica la guía, se dice así.
    sin_publicar = {**_CRIPTOGRAFIA, "tiene_guia": False}
    texto = _de_origen(trocear_dataset([sin_publicar]), "asignatura_sin_guia")[0][
        "texto"
    ]
    assert "no está publicada" in texto


def test_si_la_guia_si_llega_no_se_duplica_la_asignatura():
    # Comprobación de que el arreglo no genera fragmentos de más: con su guía
    # presente, la asignatura produce solo los fragmentos de guía.
    guia = {
        "tipo": "guia",
        "grado": _CRIPTOGRAFIA["grado"],
        "codigo": "15712013",
        "nombre": "Criptografía",
        "fallback": False,
        "resumen": "Fundamentos de criptografía simétrica y asimétrica.",
        "temario": "Tema 1. Cifrado clásico. Tema 2. Clave pública.",
    }
    chunks = trocear_dataset([_CRIPTOGRAFIA, guia])
    assert "asignatura_sin_guia" not in {c["origen"] for c in chunks}


# --- IT-105: el curso llega al fragmento ---


def _asignatura(nombre, tipo="OB", curso="", cuatrimestre=""):
    """Asignatura mínima con la forma que emite el spider desde IT-105."""
    return {
        "tipo": "asignatura",
        "grado": "Grado en Ingeniería Informática",
        "codigo": None,
        "nombre": nombre,
        "tipo_asignatura": tipo,
        "ects": "6",
        "menciones": [],
        "curso": curso,
        "cuatrimestre": cuatrimestre,
        "ofertada": True,
        "tiene_guia": False,
    }


def test_el_curso_se_escribe_dentro_del_texto_del_fragmento():
    # Un metadato que no aparece en el texto el modelo generativo no lo ve, y
    # sin verlo se lo inventa: preguntado por el primer año respondió con el
    # listado entero del grado, atribuyendo cursos que nadie le había dado.
    chunks = _de_origen(
        trocear_dataset(
            [
                _asignatura(
                    "Álgebra", curso="Primer curso", cuatrimestre="Segundo cuatrimestre"
                )
            ]
        ),
        "asignatura_sin_guia",
    )
    assert "el segundo cuatrimestre de primer curso" in chunks[0]["texto"]


def test_sin_curso_publicado_el_fragmento_no_se_lo_inventa():
    # Decisión 9: lo que no consta se refleja ausente, no se rellena.
    chunks = _de_origen(
        trocear_dataset([_asignatura("Minería web", tipo="OP")]),
        "asignatura_sin_guia",
    )
    assert "Se imparte en" not in chunks[0]["texto"]


def test_el_hueco_del_curso_se_dice_en_vez_de_callarse():
    # Medido el 16/08/2026: con el encabezado diciendo solo «Se imparte en el
    # segundo cuatrimestre», el modelo respondió que la asignatura era
    # «optativa en 2º curso», convirtiendo el cuatrimestre en un curso que la
    # fuente no publica. Un hueco callado se rellena solo.
    chunks = _de_origen(
        trocear_dataset(
            [
                _asignatura(
                    "Programación hardware",
                    tipo="OP",
                    cuatrimestre="Segundo cuatrimestre",
                )
            ]
        ),
        "asignatura_sin_guia",
    )
    assert "sin curso asignado en el plan" in chunks[0]["texto"]


def test_el_listado_del_plan_se_parte_por_curso_y_no_por_tamano():
    # Antes salían tercios alfabéticos: las tres partes repetían «En total son
    # 50» y ninguna decía cuál era. El modelo recibió las tres y aun así dejó
    # diez asignaturas sin nombrar.
    items = [_asignatura(f"Asignatura {i}", curso="Primer curso") for i in range(5)] + [
        _asignatura(f"Materia {i}", curso="Segundo curso") for i in range(5)
    ]
    listados = _de_origen(trocear_dataset(items), "plan_de_estudios")
    nombres = {c["nombre"] for c in listados}
    assert nombres == {
        "Asignaturas obligatorias de primer curso del Grado en Ingeniería Informática",
        "Asignaturas obligatorias de segundo curso del Grado en Ingeniería Informática",
    }
    # Y cada uno cabe entero: es la razón de agrupar así.
    assert all(c["total_chunks"] == 1 for c in listados)


def test_los_listados_salen_ordenados_por_curso():
    items = [_asignatura("Tardía", curso="Cuarto curso")] + [
        _asignatura("Temprana", curso="Primer curso")
    ]
    listados = _de_origen(trocear_dataset(items), "plan_de_estudios")
    assert "primer curso" in listados[0]["nombre"]
    assert "cuarto curso" in listados[1]["nombre"]


def test_el_curso_disyuntivo_del_doble_ordena_por_el_primero_que_nombra():
    # «Tercer o cuarto curso» va donde va tercero, que es lo antes que puede
    # cursarse. No se elige uno de los dos: el rótulo se conserva entero.
    items = [
        _asignatura("De quinto", curso="Quinto curso"),
        _asignatura("Ambigua", curso="Tercer o cuarto curso"),
    ]
    listados = _de_origen(trocear_dataset(items), "plan_de_estudios")
    assert "tercer o cuarto curso" in listados[0]["nombre"]
    assert "quinto curso" in listados[1]["nombre"]


def test_las_optativas_sin_curso_van_en_su_propio_listado_al_final():
    items = [
        _asignatura("Optativa", tipo="OP"),
        _asignatura("Obligatoria", curso="Primer curso"),
    ]
    listados = _de_origen(trocear_dataset(items), "plan_de_estudios")
    nombres = [c["nombre"] for c in listados]
    assert nombres == [
        "Asignaturas obligatorias de primer curso del Grado en Ingeniería Informática",
        "Asignaturas optativas del Grado en Ingeniería Informática",
    ]


# --- IT-107: fragmentos derivados que contestan las preguntas de agregación ---


def _titulacion(nombre, doble=False):
    return {"tipo": "grado", "nombre": nombre, "url": "", "es_doble_grado": doble}


def _asig_it107(grado, codigo, nombre, tipo, ects, curso="", menciones=None):
    return {
        "tipo": "asignatura",
        "grado": grado,
        "codigo": codigo,
        "nombre": nombre,
        "tipo_asignatura": tipo,
        "ects": ects,
        "curso": curso,
        "menciones": menciones or [],
        "ofertada": True,
        "tiene_guia": False,
    }


_SIMPLE = "Grado en Ingeniería Informática"
_DOBLE = "Doble Grado en Ingeniería Eléctrica y Mecánica"


@pytest.fixture(scope="module")
def derivados():
    """Dos titulaciones, una de ellas sin plan publicado."""
    items = [
        _titulacion(_SIMPLE),
        _titulacion(_DOBLE, doble=True),
        _titulacion("Grado sin plan publicado"),
        _asig_it107(_SIMPLE, "A1", "Álgebra", "FB", "6", "Primer curso"),
        _asig_it107(_SIMPLE, "A2", "Cálculo", "FB", "6", "Primer curso"),
        _asig_it107(_SIMPLE, "A3", "Redes", "OB", "6", "Segundo curso"),
        _asig_it107(
            _SIMPLE, "A4", "Metaheurísticas", "OP", "6", "", ["Sistemas gráficos"]
        ),
        _asig_it107(_SIMPLE, "A5", "Visión", "OP", "6", "", ["Sistemas gráficos"]),
        _asig_it107(_DOBLE, "B1", "CIRCUITOS", "OB", "6", "Primer curso"),
        _asig_it107(_DOBLE, "B2", "PROYECTOS", "OB", "6", "Quinto curso"),
    ]
    return trocear_dataset(items)


def test_el_catalogo_enumera_toda_la_oferta(derivados):
    """«¿Qué se puede estudiar en la EPSJ?» no la contestaba ningún fragmento."""
    general = [
        c
        for c in _de_origen(derivados, "catalogo")
        if c["nombre"].startswith("Titulaciones que")
    ]
    assert len(general) == 1
    texto = general[0]["texto"]
    assert "En total son 3: 2 grados y 1 dobles grados" in texto
    for nombre in (_SIMPLE, _DOBLE, "Grado sin plan publicado"):
        assert nombre in texto


def test_cada_familia_tiene_su_propio_fragmento(derivados):
    """Medido sobre el índice completo: «¿qué dobles grados hay?» no recuperaba
    el catálogo sino veinte fichas de titulaciones sueltas, porque un nombre
    propio se parece más a la pregunta que un encabezado que habla de las doce.
    """
    porfamilia = {
        c["nombre"]: c["texto"]
        for c in _de_origen(derivados, "catalogo")
        if not c["nombre"].startswith("Titulaciones que")
    }
    assert len(porfamilia) == 2
    dobles = next(t for n, t in porfamilia.items() if n.startswith("Dobles"))
    assert "En total son 1:" in dobles
    assert _DOBLE in dobles
    assert _SIMPLE not in dobles


def test_la_ficha_dice_cuantas_asignaturas_hay(derivados):
    """Regresión del peor fallo del 17/08/2026.

    Preguntado por cuántas asignaturas tiene Ingeniería Informática, el modelo
    contestó que **una**. La cifra no estaba en el corpus como texto: había que
    contar los fragmentos, y la recuperación devuelve los K mejores, no todos.
    """
    ficha = [
        c for c in _de_origen(derivados, "ficha_titulacion") if _SIMPLE in c["nombre"]
    ]
    assert len(ficha) == 1
    assert (
        "En total tiene 5 asignaturas: 3 obligatorias y 2 optativas"
        in ficha[0]["texto"]
    )


def test_la_ficha_deduce_la_duracion_de_los_rotulos(derivados):
    """Un doble dura cinco cursos y un grado cuatro: sale del dato, no de una regla."""
    fichas = {
        c["grados"][0]: c["texto"] for c in _de_origen(derivados, "ficha_titulacion")
    }
    assert "se organiza en 2 cursos" in fichas[_SIMPLE]
    assert "se organiza en 5 cursos" in fichas[_DOBLE]


def test_la_ficha_no_declara_creditos_totales(derivados):
    """Sumar lo que se oferta no son los créditos de la carrera.

    En Informática la suma da 408 y el grado son 240: la diferencia son las
    optativas, de las que solo se cursa una parte, y el corpus no publica
    cuántas. Un número que se lee como «los créditos de la carrera» y no lo es
    es peor que no darlo.
    """
    for ficha in _de_origen(derivados, "ficha_titulacion"):
        assert "ECTS" not in ficha["texto"]


def test_una_titulacion_sin_plan_publicado_lo_dice(derivados):
    """No se queda fuera: un hueco silencioso se lee como que no existe.

    Es el caso real del doble grado internacional con Schmalkalden, que el
    corpus lista como titulación pero del que la EPSJ no publica asignaturas.
    """
    ficha = [
        c
        for c in _de_origen(derivados, "ficha_titulacion")
        if c["grados"] == ["Grado sin plan publicado"]
    ]
    assert len(ficha) == 1
    assert "no publica el plan de estudios" in ficha[0]["texto"]
    assert "En total tiene" not in ficha[0]["texto"]


def test_el_doble_grado_declara_que_no_tiene_optativas(derivados):
    ficha = [
        c for c in _de_origen(derivados, "ficha_titulacion") if c["grados"] == [_DOBLE]
    ]
    assert "no publica optativas" in ficha[0]["texto"]


def test_la_mencion_reune_sus_asignaturas(derivados):
    """Estaban en el corpus, repartidas: ninguna unidad las juntaba."""
    suyo = [
        c
        for c in _de_origen(derivados, "mencion")
        if c["nombre"].startswith("Asignaturas de la mención")
    ]
    assert len(suyo) == 1
    texto = suyo[0]["texto"]
    assert texto.startswith("Asignaturas de la mención «Sistemas gráficos»")
    assert "En total son 2:" in texto
    assert "Metaheurísticas" in texto and "Visión" in texto


def test_hay_un_fragmento_que_dice_cuales_son_las_menciones(derivados):
    """Regresión del turno 12 del 17/08/2026: dijo «dos menciones» y son tres.

    La respuesta estaba repartida en una unidad por mención y ninguna decía
    cuántas hay. Se probó a meter la lista en la ficha de la titulación y la
    recuperación no la traía: su encabezado, «Datos generales del…», no se
    parece a la pregunta. Con encabezado propio entra la primera.
    """
    listado = [
        c
        for c in _de_origen(derivados, "mencion")
        if c["nombre"].startswith("Menciones")
    ]
    assert len(listado) == 1
    assert "En total son 1:" in listado[0]["texto"]
    assert "Sistemas gráficos" in listado[0]["texto"]


def test_los_derivados_no_inventan_titulaciones(derivados):
    """Todo lo que nombran sale del dataset: es reorganización, no información nueva."""
    reales = {_SIMPLE, _DOBLE, "Grado sin plan publicado"}
    for c in derivados:
        if c["origen"] in ("catalogo", "ficha_titulacion", "mencion"):
            assert set(c["grados"]) <= reales


def test_los_derivados_llevan_listas_paralelas_no_vacias(derivados):
    """El invariante que exige el verificador: sin esto, el índice los rechaza."""
    for c in derivados:
        if c["origen"] in ("catalogo", "ficha_titulacion", "mencion"):
            assert c["grados"] and len(c["grados"]) == len(c["codigos"])


def test_lo_comun_a_todas_las_menciones_no_se_presenta_como_una_mencion():
    """Regresión del 17/08/2026: «Mecánica tiene dos menciones» y una era esto.

    La fuente marca con ese rótulo las optativas que no pertenecen a ninguna
    mención concreta, y viaja en el mismo campo que ellas. Llamarlo mención en
    el encabezado hacía que el sistema lo contase como una más.
    """
    items = [
        _titulacion(_SIMPLE),
        _asig_it107(
            _SIMPLE, "A1", "Álgebra", "OP", "6", "", ["Común a todas las menciones"]
        ),
        _asig_it107(_SIMPLE, "A2", "Visión", "OP", "6", "", ["Sistemas gráficos"]),
    ]
    titulos = {c["nombre"] for c in _de_origen(trocear_dataset(items), "mencion")}
    assert (
        f"Asignaturas optativas comunes a todas las menciones del {_SIMPLE}" in titulos
    )
    assert not any("mención «Común" in t for t in titulos)


def test_el_encabezado_dice_que_los_creditos_no_estan_publicados():
    """Regresión: el dato ausente se refleja, no se omite.

    «Sistemas Digitales» es la única de las 528 asignaturas del corpus sin
    créditos en la fuente. El encabezado se los saltaba en silencio, así que el
    fragmento era indistinguible de uno al que simplemente no le cupo el dato.
    Medido el 18/08/2026, cuatro de cinco modelos generativos rellenaron el
    hueco con una cifra inventada.
    """
    asignatura = {
        "grado": "Grado en Ingeniería Electrónica Industrial",
        "codigo": "14012045",
        "nombre": "Sistemas Digitales",
        "tipo_asignatura": "OP",
        "ects": "",
        "ofertada": True,
        "menciones": [],
    }
    encabezado = chunker._encabezado_asignatura(
        asignatura, ["Grado en Ingeniería Electrónica Industrial"]
    )
    assert "La web de la EPSJ no publica sus créditos." in encabezado
    assert "ECTS" not in encabezado


def test_con_creditos_el_encabezado_no_dice_nada_de_eso():
    asignatura = {
        "grado": "Grado en Ingeniería Informática",
        "codigo": "13011001",
        "nombre": "Álgebra",
        "tipo_asignatura": "FB",
        "ects": "6",
        "ofertada": True,
        "menciones": [],
    }
    encabezado = chunker._encabezado_asignatura(
        asignatura, ["Grado en Ingeniería Informática"]
    )
    assert "de 6 ECTS" in encabezado
    assert "no publica sus créditos" not in encabezado


def test_los_listados_declaran_el_credito_ausente():
    """Regresión: un hueco en una lista donde todo lo demás lleva el dato.

    En el listado de la mención «Sistemas electrónicos» las otras tres
    asignaturas llevan «(6 ECTS)» y «Sistemas Digitales» no llevaba nada.
    Medido el 19/08/2026: granite4.1:8b razonó que «las otras dos tienen 6
    ECTS» y concluyó que esta también.
    """
    assert chunker._creditos({"ects": "6"}) == " (6 ECTS)"
    assert chunker._creditos({"ects": ""}) == " (créditos no publicados)"


# --- Bordes del troceado que ninguna guía real había ejercitado ---


def test_un_parrafo_vacio_entre_saltos_no_produce_una_pieza():
    """Tres saltos seguidos dejan un párrafo vacío que no es un fragmento.

    Sale de las guías en PDF: al pegar las líneas útiles quedan huecos dobles
    donde el original tenía un rótulo suprimido. Sin la guarda, cada hueco
    entraría como pieza vacía y acabaría contando como fragmento.
    """
    piezas = chunker._dividir_en_piezas("Primero.\n\n\n\nSegundo.", 900)

    assert piezas == ["Primero.", "Segundo."]


def test_una_palabra_mas_larga_que_el_maximo_se_corta_por_donde_sea():
    """Sin espacio donde cortar se corta en seco, porque el máximo es duro.

    El máximo de 900 es restricción dura y no una preferencia: una URL larga o
    un identificador sin espacios no puede saltárselo por no encontrar dónde
    partir. Se prefiere un corte feo a un fragmento que incumple.
    """
    larga = "A" * 50

    piezas = chunker._dividir_en_piezas(larga, 20)

    assert all(len(p) <= 20 for p in piezas)
    assert "".join(piezas) == larga


def test_un_encabezado_sin_metadatos_enumera_las_titulaciones_que_comparten():
    """Una guía compartida nombra todas sus titulaciones, no solo la primera.

    Es la consecuencia de que `grados` sea una lista: 81 de las 398 unidades se
    imparten en más de una titulación, y un encabezado que solo nombrase una
    haría que el modelo negase la asignatura al preguntarle por la otra.
    """
    uno = chunker._encabezado_sin_metadatos(
        "Álgebra", ["Grado en Ingeniería Eléctrica"]
    )
    varios = chunker._encabezado_sin_metadatos(
        "Álgebra",
        ["Grado en Ingeniería Eléctrica", "Grado en Ingeniería Mecánica"],
    )

    assert uno == "«Álgebra», asignatura del Grado en Ingeniería Eléctrica."
    assert varios == (
        "«Álgebra», asignatura impartida en: Grado en Ingeniería Eléctrica; "
        "Grado en Ingeniería Mecánica."
    )


def test_un_curso_con_rotulo_desconocido_va_al_final_sin_perderse():
    """Un rótulo de curso que no es ordinal se ordena al final, pero se conserva.

    La fuente ya cambió tres veces este verano y el rótulo de curso es de los
    que se han movido. Descartar lo que no se reconoce perdería asignaturas en
    silencio, que es exactamente el fallo que este proyecto ha pagado cuatro
    veces; mandarlo al final las conserva y hace visible la anomalía.
    """
    asignaturas = [
        {"nombre": "De primero", "curso": "Primer curso"},
        {"nombre": "De rótulo raro", "curso": "Curso de adaptación"},
        {"nombre": "Sin curso", "curso": ""},
    ]

    ordenadas = chunker._por_curso(asignaturas)

    cursos = [curso for curso, _ in ordenadas]
    assert cursos[0] == "Primer curso"
    assert "Curso de adaptación" in cursos
    assert cursos[-1] == ""


def test_main_escribe_la_procedencia_como_primer_registro(tmp_path, capsys):
    """El fichero de fragmentos lleva dentro de dónde y cuándo salió (IT-90).

    La procedencia va como PRIMER registro del fichero, no en uno aparte, para
    que no pueda separarse de los datos que describe. Es también la trampa que
    hace que ``len(chunks)`` cuente uno de más si no se filtra.
    """
    items = [
        {
            "tipo": "grado",
            "nombre": "Grado en Ingeniería Informática",
            "url": "https://eps.ujaen.es/grados/informatica",
            "es_doble_grado": False,
        },
        {
            "tipo": "salidas",
            "grado": "Grado en Ingeniería Informática",
            "texto": "Las salidas profesionales abarcan el desarrollo de software.",
        },
    ]
    entrada = tmp_path / "grados.json"
    entrada.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    salida = tmp_path / "chunks.json"

    chunker.main(str(entrada), str(salida))

    escrito = json.loads(salida.read_text(encoding="utf-8"))
    assert escrito[0]["tipo"] == "procedencia"
    assert escrito[0]["tamanos"] == [900, 900, 200]
    assert all(c["tipo"] == "chunk" for c in escrito[1:])
    assert f"chunks escritos en {salida}" in capsys.readouterr().out


def test_si_el_reparto_deja_menos_fragmentos_se_reevalua_desde_el_principio():
    """Cuando reequilibrar reduce el número de fragmentos, se vuelve a empezar.

    Ocurre porque las piezas se recortan al repartirlas: el texto que sale de
    una guía en PDF llega con líneas en blanco de sobra, y esos huecos cuentan
    para el máximo mientras están pegados pero desaparecen al trocear. Un par
    que no cabía junto acaba cabiendo, y entonces hay que reevaluar desde el
    principio porque el fragmento resultante puede volver a fusionarse con su
    vecino.

    La guarda contraria ---descartar el reparto que devuelve MÁS fragmentos---
    es la que hace que el bucle termine, y es la que a IT-92 se le escapó: el
    recuento oscilaba entre 7 y 8 y el troceado no acababa nunca.
    """
    corto = "A" * 40
    con_huecos = "B" * 40 + "\n" * 30

    resultado = chunker._fusionar_pequenos([corto, con_huecos], 50, 100)

    assert len(resultado) == 1
    assert len(resultado[0]) == 81


# --- IT-101: enganchar las asignaturas del doble grado a la guía que ya existe ---
#
# Un doble grado no publica guías propias. Sus asignaturas son casi todas las
# mismas que las de sus dos grados base, pero con códigos de otra serie, así que
# se cruzan por NOMBRE y no por código. El cruce añade la titulación doble a la
# unidad que ya existe en vez de duplicar unos 200 fragmentos de temario.


def _it101_grado(nombre: str, doble: bool = False) -> dict:
    return {
        "tipo": "grado",
        "nombre": nombre,
        "url": f"https://eps.ujaen.es/{nombre.lower().replace(' ', '-')}",
        "es_doble_grado": doble,
    }


def _it101_asignatura(grado: str, codigo: str, nombre: str) -> dict:
    return {
        "tipo": "asignatura",
        "grado": grado,
        "codigo": codigo,
        "nombre": nombre,
        "tipo_asignatura": "FB",
        "ects": "6",
        "menciones": [],
        "ofertada": True,
        "tiene_guia": True,
    }


def _it101_guia(grado: str, codigo: str, nombre: str, temario: str) -> dict:
    return {
        "tipo": "guia",
        "grado": grado,
        "codigo": codigo,
        "nombre": nombre,
        "resumen": f"Resumen de {nombre}.",
        "temario": temario,
        "fallback": False,
    }


def test_la_asignatura_del_doble_grado_se_engancha_a_la_guia_del_grado_base():
    """El doble grado entra en la lista de titulaciones, sin duplicar el temario.

    El plan del doble escribe los nombres en mayúsculas y el del simple en
    minúsculas, que es por lo que la comparación se hace normalizada: en crudo
    no casaba ni uno solo de los 178 nombres, y las asignaturas del doble
    acababan con un fragmento afirmando en falso que no tenían guía.
    """
    items = [
        _it101_grado("Grado A"),
        _it101_grado("Doble Grado A y B", doble=True),
        _it101_asignatura("Grado A", "10000001", "Álgebra lineal"),
        _it101_asignatura("Doble Grado A y B", "90000001", "ÁLGEBRA LINEAL"),
        _it101_guia("Grado A", "10000001", "Álgebra lineal", "Espacios vectoriales."),
    ]

    chunks = chunker.trocear_dataset(items)

    algebra = [c for c in chunks if c["nombre"] == "Álgebra lineal"]
    assert len(algebra) == 1
    assert algebra[0]["grados"] == ["Grado A", "Doble Grado A y B"]
    assert algebra[0]["codigos"] == ["10000001", "90000001"]


def test_un_nombre_ambiguo_entre_varias_guias_no_se_reparte_a_ojo(capsys):
    """Si el nombre casa con dos guías distintas, no se engancha a ninguna y se avisa.

    Adivinar de cuál cuelga sería inventarse el dato, y repartirlo entre las dos
    metería en la unidad una titulación que quizá no la imparte. Se avisa por
    salida de error porque este proyecto ya ha pagado cuatro veces el precio de
    un dato que se pierde sin decir nada.
    """
    items = [
        _it101_grado("Grado A"),
        _it101_grado("Grado B"),
        _it101_grado("Doble Grado A y B", doble=True),
        _it101_asignatura("Grado A", "10000001", "Física"),
        _it101_asignatura("Grado B", "20000001", "Física"),
        _it101_asignatura("Doble Grado A y B", "90000001", "FÍSICA"),
        _it101_guia("Grado A", "10000001", "Física", "Mecánica clásica y ondas."),
        _it101_guia("Grado B", "20000001", "Física", "Electromagnetismo y óptica."),
    ]

    chunks = chunker.trocear_dataset(items)

    for chunk in chunks:
        assert "Doble Grado A y B" not in chunk["grados"] or chunk["origen"] != "guia"
    aviso = capsys.readouterr().err
    assert "nombre ambiguo" in aviso
    assert "Doble Grado A y B - FÍSICA" in aviso

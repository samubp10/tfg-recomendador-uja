"""Pruebas de la recuperación de fragmentos (IT-37).

Tres de estas pruebas cubren invariantes que **no fallan solos**: la métrica de
distancia, el momento del filtrado y el modelo con el que se consulta. Ninguno
de los tres da error cuando se rompe, así que sin prueba solo se notarían como
respuestas peores, que es justo lo que este proyecto ya ha sufrido cuatro veces.

Sin red y sin modelo real: el incrustador es falso e inyectado, y el índice se
construye con el propio ``indexer`` en la carpeta temporal de cada prueba.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tfg_uja.incrustaciones import MODELO
from tfg_uja.indexer import reconstruir_indice
from tfg_uja.recuperador import (
    K_POR_DEFECTO,
    PREGUNTAS_DE_CONTEXTO,
    Fragmento,
    ModeloDiscrepante,
    TitulacionDesconocida,
    abrir_indice,
    acotar_por_distancia,
    catalogo_del_indice,
    consulta_con_historial,
    distancia_del_indice,
    nombra_titulacion,
    palabras_distintivas,
    recuperar,
    resolver_titulacion,
)

DIMENSION = 8

SIMPLE = "Grado en Ingeniería Eléctrica"
DOBLE = "Doble Grado en Ingeniería Eléctrica y Mecánica"
INFORMATICA = "Grado en Ingeniería Informática"

#: Catálogo que el índice graba de sí mismo. El filtro ya no interpola texto
#: del usuario: resuelve contra esto.
CATALOGO_PRUEBA = [SIMPLE, DOBLE, INFORMATICA]


def incrustador_falso(textos: list[str]) -> list[list[float]]:
    """Incrustador determinista: la primera componente es la longitud del texto.

    Con esto la proximidad depende de cuánto se parezcan las longitudes, que es
    arbitrario pero **predecible**, que es lo que necesita una prueba.
    """
    return [[float(len(t) % 97)] + [0.0] * (DIMENSION - 1) for t in textos]


def chunk(
    nombre: str, texto: str, grados: list[str], tipo: str = "OB"
) -> dict[str, Any]:
    """Fragmento con la forma exacta que emite el fragmentador."""
    return {
        "tipo": "chunk",
        "origen": "guia",
        "grados": grados,
        "codigos": ["13312001"] * len(grados),
        "nombre": nombre,
        "texto": texto,
        "tipo_asignatura": tipo,
        "chunk_index": 0,
        "total_chunks": 1,
    }


@pytest.fixture()
def indice(tmp_path) -> Path:
    """Índice pequeño pero con la anomalía real: dos titulaciones anidadas."""
    chunks = [
        chunk("Compartida", "Se imparte en el simple y en el doble.", [SIMPLE, DOBLE]),
        chunk("Solo del doble", "Solo en la titulación doble.", [DOBLE]),
        chunk("Optativa del doble", "Optativa de la doble.", [DOBLE], tipo="OP"),
        chunk(
            "De informática",
            "Asignatura de informática con texto mucho más largo "
            "que las demás para que quede lejos.",
            [INFORMATICA],
        ),
    ]
    ruta_chunks = tmp_path / "chunks.json"
    ruta_chunks.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    ruta_indice = tmp_path / "indice"
    reconstruir_indice(ruta_chunks, ruta_indice, incrustador_falso, MODELO)
    return ruta_indice


# --- Invariante 1: la métrica se declara en cada consulta ---


class ConsultaEspia:
    """Doble de la consulta de LanceDB que anota cómo se la construye."""

    def __init__(self, registro: dict[str, Any]) -> None:
        self.registro = registro

    def distance_type(self, metrica: str) -> "ConsultaEspia":
        self.registro["distancia"] = metrica
        return self

    def limit(self, k: int) -> "ConsultaEspia":
        self.registro["k"] = k
        return self

    def where(self, expresion: str, prefilter: bool = False) -> "ConsultaEspia":
        self.registro["where"] = expresion
        self.registro["prefilter"] = prefilter
        return self

    def to_list(self) -> list[dict[str, Any]]:
        return []


class TablaEspia:
    """Doble de la tabla que devuelve la consulta espía."""

    def __init__(self) -> None:
        self.registro: dict[str, Any] = {}

    def search(self, vector: list[float]) -> ConsultaEspia:
        self.registro["vector"] = vector
        return ConsultaEspia(self.registro)


def test_la_metrica_se_declara_en_cada_consulta():
    """Regresión: omitirla no falla, LanceDB ordena por `l2` y nadie se entera.

    Con el modelo del ADR-0003 el orden coincidiría, porque entrega vectores
    normalizados; pero eso es propiedad del modelo, no de la base, y se
    rompería al cambiarlo sin que fallara ninguna prueba.
    """
    tabla = TablaEspia()
    recuperar("una pregunta", tabla, incrustador_falso, distancia="cosine")
    assert tabla.registro["distancia"] == "cosine"


def test_la_metrica_recuperada_es_la_que_grabo_el_indice(indice):
    """El recuperador lee la métrica del índice en vez de suponerla."""
    assert distancia_del_indice(indice) == "cosine"


# --- Invariante 2: el filtro se aplica ANTES de buscar ---


def test_el_filtro_se_aplica_antes_de_buscar():
    """Regresión: filtrar después devuelve menos de k fragmentos, o ninguno.

    Y entonces el sistema responde «no tengo información» sobre algo que sí
    está indexado, que es un fallo invisible desde el código.
    """
    tabla = TablaEspia()
    recuperar(
        "una pregunta", tabla, incrustador_falso, grado=SIMPLE, catalogo=CATALOGO_PRUEBA
    )
    assert tabla.registro["prefilter"] is True
    assert "array_has_any" in tabla.registro["where"]


def test_filtrar_por_una_titulacion_no_arrastra_el_doble_grado(indice):
    """El caso real: «Grado en Ingeniería Eléctrica» es subcadena del doble.

    Una coincidencia por subcadena devolvería también los fragmentos que solo
    pertenecen al doble grado. Sobre el corpus completo eso son 167 falsos
    positivos.
    """
    tabla = abrir_indice(indice, MODELO)
    fragmentos = recuperar(
        "asignaturas",
        tabla,
        incrustador_falso,
        k=10,
        grado=SIMPLE,
        catalogo=CATALOGO_PRUEBA,
    )
    assert {f.nombre for f in fragmentos} == {"Compartida"}


def test_el_prefiltrado_rescata_lo_que_el_top_k_no_alcanza(indice):
    """Sin filtro, el fragmento de Informática no entra en el top-1.

    Con el filtro puesto **antes** de buscar, sí: es el mismo índice y la
    misma pregunta, y lo único que cambia es acotar la titulación.
    """
    tabla = abrir_indice(indice, MODELO)
    sin_filtro = recuperar("asignaturas", tabla, incrustador_falso, k=1)
    assert "De informática" not in {f.nombre for f in sin_filtro}

    con_filtro = recuperar(
        "asignaturas",
        tabla,
        incrustador_falso,
        k=1,
        grado=INFORMATICA,
        catalogo=CATALOGO_PRUEBA,
    )
    assert [f.nombre for f in con_filtro] == ["De informática"]


def test_filtrar_por_titulacion_y_tipo_a_la_vez(indice):
    """La consulta que motivó guardar el tipo: «optativas de este grado»."""
    tabla = abrir_indice(indice, MODELO)
    fragmentos = recuperar(
        "asignaturas",
        tabla,
        incrustador_falso,
        k=10,
        grado=DOBLE,
        tipo_asignatura="OP",
        catalogo=CATALOGO_PRUEBA,
    )
    assert [f.nombre for f in fragmentos] == ["Optativa del doble"]


# --- Invariante 3: el modelo de la consulta es el del índice ---


def test_consultar_con_otro_modelo_falla_de_forma_ruidosa(indice):
    """Regresión: dos modelos distintos pueden dar vectores de igual dimensión.

    Consultar con el equivocado no da error: solo devuelve peores resultados.
    Por eso el índice graba el suyo y aquí se comprueba.
    """
    with pytest.raises(ModeloDiscrepante) as excepcion:
        abrir_indice(indice, "otro/modelo-distinto")
    assert "otro/modelo-distinto" in str(excepcion.value)


def test_consultar_con_el_modelo_del_indice_no_falla(indice):
    assert abrir_indice(indice, MODELO) is not None


# --- Lo que devuelve ---


def test_recupera_como_mucho_k_fragmentos(indice):
    tabla = abrir_indice(indice, MODELO)
    assert len(recuperar("asignaturas", tabla, incrustador_falso, k=2)) == 2


def test_los_fragmentos_vienen_ordenados_por_proximidad(indice):
    tabla = abrir_indice(indice, MODELO)
    fragmentos = recuperar("asignaturas", tabla, incrustador_falso, k=4)
    distancias = [f.distancia for f in fragmentos]
    assert distancias == sorted(distancias)


@pytest.fixture()
def indice_partido(tmp_path) -> Path:
    """Índice aparte con una sola unidad partida en tres.

    Va separado del otro para que añadir esta unidad no altere qué fragmento
    queda más próximo en las pruebas de filtrado, que dependen de las
    longitudes del corpus de prueba.
    """
    chunks = [
        {
            **chunk("Listado", f"parte número {i}", [INFORMATICA]),
            "chunk_index": i,
            "total_chunks": 3,
        }
        for i in range(3)
    ]
    ruta_chunks = tmp_path / "chunks.json"
    ruta_chunks.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    ruta_indice = tmp_path / "indice_partido"
    reconstruir_indice(ruta_chunks, ruta_indice, incrustador_falso, MODELO)
    return ruta_indice


def test_el_fragmento_sabe_de_que_parte_de_su_unidad_viene(indice_partido):
    """Sin esto el generador no puede reagrupar un listado partido.

    Los tres campos están en el índice desde IT-30, pero el recuperador no los
    leía: el generador recibía las partes sueltas y sin forma de ordenarlas.
    """
    tabla = abrir_indice(indice_partido, MODELO)
    fragmentos = recuperar("listado", tabla, incrustador_falso, k=3)
    assert {f.chunk_index for f in fragmentos} == {0, 1, 2}
    assert {f.total_chunks for f in fragmentos} == {3}


def test_el_fragmento_trae_lo_necesario_para_citarlo(indice):
    """El generador tiene que poder decir de qué asignatura sale cada dato."""
    tabla = abrir_indice(indice, MODELO)
    fragmento = recuperar("asignaturas", tabla, incrustador_falso, k=1)[0]
    assert isinstance(fragmento, Fragmento)
    assert fragmento.nombre
    assert fragmento.grados
    assert fragmento.origen == "guia"
    assert fragmento.texto


# --- La consulta de seguimiento ---


def test_una_pregunta_suelta_se_incrusta_tal_cual():
    assert consulta_con_historial("¿qué es Álgebra?", []) == "¿qué es Álgebra?"


def test_una_pregunta_de_seguimiento_arrastra_las_anteriores():
    """El caso real: «¿y en primer año?» no nombra ninguna titulación.

    Incrustada sola recupera fragmentos de las doce titulaciones; con la
    pregunta anterior delante vuelve a caer sobre la que se estaba hablando.
    """
    consulta = consulta_con_historial(
        "¿y en primer año?", ["háblame del Grado en Ingeniería Informática"]
    )
    assert "Informática" in consulta
    assert consulta.endswith("¿y en primer año?")


def test_solo_se_arrastran_las_ultimas_preguntas():
    """Con toda la conversación dentro, el vector se diluye entre temas viejos."""
    anteriores = [f"pregunta {i}" for i in range(6)]
    consulta = consulta_con_historial("la actual", anteriores)
    assert "pregunta 0" not in consulta
    assert consulta.count("pregunta") == PREGUNTAS_DE_CONTEXTO


# --- Cuándo NO hay que arrastrar la conversación ---


def test_una_pregunta_que_nombra_su_titulacion_no_arrastra_nada():
    """Regresión del peor fallo de la sesión del 17/08/2026.

    A «¿cuántas asignaturas tiene el Grado en Ingeniería Informática?» se le
    antepuso la pregunta anterior, que era sobre una asignatura suelta. El
    vector quedó dominado por ella, la recuperación devolvió cuatro fragmentos
    ---los cuatro de esa asignatura--- y el sistema contestó que la titulación
    entera «cuenta con una sola asignatura llamada Metaheurísticas».
    """
    consulta = consulta_con_historial(
        "¿cuántas asignaturas tiene el Grado en Ingeniería Informática?",
        ["¿qué se estudia en Metaheurísticas?"],
        CATALOGO_PRUEBA,
    )
    assert "Metaheurísticas" not in consulta
    assert consulta == "¿cuántas asignaturas tiene el Grado en Ingeniería Informática?"


def test_el_nombre_corto_de_la_titulacion_tambien_la_sostiene():
    """Nadie escribe el nombre oficial completo: escribe «informática»."""
    consulta = consulta_con_historial(
        "¿qué salidas tiene informática?", ["háblame de eléctrica"], CATALOGO_PRUEBA
    )
    assert consulta == "¿qué salidas tiene informática?"


def test_una_pregunta_de_seguimiento_sigue_arrastrando_con_catalogo():
    """El arreglo no puede llevarse por delante lo que sí necesita la muleta."""
    consulta = consulta_con_historial(
        "¿y en primer año?", ["háblame de informática"], CATALOGO_PRUEBA
    )
    assert "informática" in consulta
    assert consulta.endswith("¿y en primer año?")


def test_las_palabras_comunes_del_catalogo_no_sirven_para_reconocer():
    """«Grado» e «ingeniería» están en casi todos los nombres."""
    distintivas = palabras_distintivas(CATALOGO_PRUEBA)
    assert "informatica" in distintivas
    for comun in ("grado", "en", "ingenieria"):
        assert comun not in distintivas


def test_una_pregunta_sin_titulacion_no_se_sostiene_sola():
    assert not nombra_titulacion("¿y en primer año?", CATALOGO_PRUEBA)
    assert nombra_titulacion("¿y en Mecánica?", CATALOGO_PRUEBA)


#: El catálogo real que graba el índice del proyecto, copiado del corpus del
#: 17/08/2026. Con tres nombres inventados la regla se comporta de otro modo:
#: «eléctrica» aparece en dos de tres y deja de ser distintiva, mientras que en
#: las doce reales está en tres y sí lo es. Un umbral relativo hay que probarlo
#: contra el reparto de verdad.
CATALOGO_REAL = [
    "Doble Grado en Ingeniería Electrónica Industrial y Mecánica",
    "Doble Grado en Ingeniería Eléctrica y Electrónica Industrial",
    "Doble Grado en Ingeniería Eléctrica y Mecánica",
    "Doble Grado en Ingeniería Mecánica (Internacional - University of Applied "
    "Sciences Schmalkalden, Alemania)",
    "Doble Grado en Ingeniería Mecánica y Organización Industrial",
    "Grado en Ingeniería Electrónica Industrial",
    "Grado en Ingeniería Eléctrica",
    "Grado en Ingeniería Geomática y Topográfica (plan 2025)",
    "Grado en Ingeniería Informática",
    "Grado en Ingeniería Mecánica",
    "Grado en Ingeniería de Organización Industrial",
    "Grado en Inteligencia Artificial y Ciberseguridad",
]


@pytest.mark.parametrize(
    "pregunta",
    [
        "¿qué asignaturas tiene informática?",
        "cuéntame de eléctrica",
        "¿y electrónica industrial?",
        "quiero saber de mecánica",
        "háblame de geomática",
        "¿qué es inteligencia artificial y ciberseguridad?",
        "organización industrial, ¿qué salidas tiene?",
    ],
)
def test_las_doce_titulaciones_reales_se_reconocen_por_su_nombre_corto(pregunta):
    assert nombra_titulacion(pregunta, CATALOGO_REAL)


@pytest.mark.parametrize(
    "pregunta",
    [
        "¿y en primer año?",
        "¿cuáles son las obligatorias?",
        "¿qué se ve en esa asignatura?",
        "¿y las optativas?",
    ],
)
def test_las_preguntas_de_seguimiento_reales_siguen_necesitando_la_muleta(pregunta):
    assert not nombra_titulacion(pregunta, CATALOGO_REAL)


def test_k_por_defecto_es_el_del_modulo():
    tabla = TablaEspia()
    recuperar("una pregunta", tabla, incrustador_falso)
    assert tabla.registro["k"] == K_POR_DEFECTO


# --- El filtro se resuelve contra el catálogo del índice ---


def test_el_indice_declara_las_titulaciones_que_contiene(indice):
    """Se leen del corpus, no de una lista escrita a mano que envejece sola."""
    assert set(catalogo_del_indice(indice)) == {SIMPLE, DOBLE, INFORMATICA}


def test_el_nombre_parcial_ya_no_devuelve_cero_fragmentos():
    """Antes exigía el nombre exacto y «informática» no casaba con nada.

    Y cuando el filtro no casa, devuelve cero fragmentos: el sistema responde
    que no tiene información sobre algo que sí está indexado, con toda la
    pinta de ser una respuesta legítima.
    """
    assert resolver_titulacion("informática", CATALOGO_PRUEBA) == [INFORMATICA]
    assert resolver_titulacion("INFORMATICA", CATALOGO_PRUEBA) == [INFORMATICA]


def test_el_nombre_exacto_no_arrastra_los_dobles():
    """«Grado en Ingeniería Eléctrica» es subcadena del doble grado.

    Escrito entero, gana la coincidencia exacta y devuelve solo esa.
    """
    assert resolver_titulacion(SIMPLE, CATALOGO_PRUEBA) == [SIMPLE]


def test_el_nombre_parcial_si_trae_la_familia():
    """A quien pregunta por eléctrica le interesan también sus dobles."""
    assert set(resolver_titulacion("eléctrica", CATALOGO_PRUEBA)) == {SIMPLE, DOBLE}


def test_una_titulacion_inventada_falla_de_forma_ruidosa():
    """Filtrar por algo inexistente devolvería cero fragmentos en silencio."""
    with pytest.raises(TitulacionDesconocida) as error:
        resolver_titulacion("Grado en Ingeniería de Energía", CATALOGO_PRUEBA)
    assert "Energía" in str(error.value)


def test_lo_que_se_interpola_sale_del_catalogo_y_no_del_usuario():
    """La comilla simple es lo único que separaba la consulta de una inyección.

    Ahora el valor no llega a componerse: no casa con ninguna titulación.
    """
    with pytest.raises(TitulacionDesconocida):
        resolver_titulacion("x'] OR 1=1 --", CATALOGO_PRUEBA)


# --- K deja de ser fijo ---


def _frag(distancia: float) -> Fragmento:
    return Fragmento(
        texto="t",
        nombre="n",
        grados=[INFORMATICA],
        origen="guia",
        distancia=distancia,
        chunk_index=0,
        total_chunks=1,
    )


def test_el_corte_deja_fuera_lo_que_esta_mucho_mas_lejos():
    """Caso real: 0,080 · 0,081 · 0,082 pertinentes, y luego 0,104 de ruido."""
    fragmentos = [_frag(d) for d in (0.080, 0.081, 0.082, 0.104, 0.109, 0.110)]
    assert len(acotar_por_distancia(fragmentos, minimo=1, maximo=20)) == 3


def test_el_corte_es_relativo_y_no_absoluto():
    """Medido: el mejor de una pregunta estaba a 0,076 y el de otra a 0,107.

    Un umbral fijo en 0,10 habría dejado la segunda pregunta sin contexto.
    """
    lejanos = [_frag(d) for d in (0.107, 0.108, 0.110, 0.180)]
    assert len(acotar_por_distancia(lejanos, minimo=1, maximo=20)) == 3


def test_el_minimo_protege_de_un_corte_demasiado_agresivo():
    fragmentos = [_frag(d) for d in (0.01, 0.90, 0.91, 0.92)]
    assert len(acotar_por_distancia(fragmentos, minimo=3, maximo=20)) == 3


def test_el_maximo_sigue_siendo_un_tope():
    fragmentos = [_frag(0.10) for _ in range(30)]
    assert len(acotar_por_distancia(fragmentos, minimo=3, maximo=20)) == 20


def test_sin_fragmentos_no_falla():
    assert acotar_por_distancia([]) == []


# --- IT-105: el curso también como columna del índice ---


@pytest.fixture()
def indice_con_curso(tmp_path) -> Path:
    chunks = [
        {
            **chunk("De primero", "Asignatura de primer curso.", [INFORMATICA]),
            "curso": "Primer curso",
        },
        {
            **chunk("De tercero", "Asignatura de tercer curso.", [INFORMATICA]),
            "curso": "Tercer curso",
        },
        {
            **chunk("Optativa", "Optativa sin curso.", [INFORMATICA], tipo="OP"),
            "curso": "",
        },
    ]
    ruta_chunks = tmp_path / "chunks.json"
    ruta_chunks.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    ruta_indice = tmp_path / "indice_curso"
    reconstruir_indice(ruta_chunks, ruta_indice, incrustador_falso, MODELO)
    return ruta_indice


def test_el_curso_llega_al_fragmento_recuperado(indice_con_curso):
    tabla = abrir_indice(indice_con_curso, MODELO)
    frs = recuperar("asignatura", tabla, incrustador_falso, k=10)
    assert {f.nombre: f.curso for f in frs}["De primero"] == "Primer curso"


def test_se_puede_acotar_la_busqueda_a_un_curso(indice_con_curso):
    """La consulta que la similitud vectorial no sabe hacer sola.

    «Qué se da en primer año» se contesta filtrando, no pareciéndose: sin
    filtro, el listado de segundo está tan cerca como el de primero.
    """
    tabla = abrir_indice(indice_con_curso, MODELO)
    frs = recuperar("asignatura", tabla, incrustador_falso, k=10, curso="primer")
    assert [f.nombre for f in frs] == ["De primero"]


def test_acotar_por_curso_no_arrastra_las_optativas(indice_con_curso):
    """No tienen curso publicado: no pueden salir en ningún curso concreto."""
    tabla = abrir_indice(indice_con_curso, MODELO)
    frs = recuperar("asignatura", tabla, incrustador_falso, k=10, curso="tercer")
    assert "Optativa" not in {f.nombre for f in frs}


def test_el_curso_y_la_titulacion_se_combinan(indice_con_curso):
    tabla = abrir_indice(indice_con_curso, MODELO)
    frs = recuperar(
        "asignatura",
        tabla,
        incrustador_falso,
        k=10,
        grado=INFORMATICA,
        catalogo=CATALOGO_PRUEBA,
        curso="primer",
    )
    assert [f.nombre for f in frs] == ["De primero"]


# --- Cuando NADA es pertinente ---


def test_un_saludo_no_arrastra_medio_plan_de_estudios():
    """Caso real: «hola buenas tardes» trajo diez fragmentos y un volcado.

    Las diez distancias iban de 0,170 a 0,182: lejísimos, pero tan juntas
    entre sí que el corte relativo no recortaba nada.
    """
    lejanos = [_frag(d) for d in (0.170, 0.172, 0.174, 0.176, 0.182)]
    assert acotar_por_distancia(lejanos) == []


def test_el_minimo_no_rescata_fragmentos_irrelevantes():
    """Forzar tres irrelevantes es peor que no dar ninguno.

    El modelo responde igual y con la misma seguridad; con la lista vacía, el
    prompt dice que no se recuperó nada y esa rama ya está cubierta.
    """
    assert acotar_por_distancia([_frag(0.30)], minimo=3) == []


def test_una_pregunta_real_sigue_pasando_el_suelo():
    """Las cinco medidas tenían su mejor entre 0,076 y 0,112."""
    reales = [_frag(d) for d in (0.112, 0.113, 0.115)]
    assert len(acotar_por_distancia(reales)) == 3


def test_solo_se_arrastra_la_pregunta_que_daba_el_sujeto():
    """Regresión del turno 8 del 17/08/2026, el peor de la sesión.

    A «¿Y en el segundo?» se le antepusieron las dos anteriores literalmente, y
    una de ellas era «¿y cuántas de esas son optativas?». La consulta acabó
    siendo «...optativas... primer curso... y en el segundo», el listado de
    segundo curso no entró en el contexto y el modelo rellenó con conocimiento
    propio **seis asignaturas que no existen** en la EPSJ.

    Lo que la pregunta de seguimiento necesita es el sujeto del que se hablaba,
    no el texto de lo que se preguntó antes.
    """
    consulta = consulta_con_historial(
        "¿Y en el segundo?",
        [
            "¿Y cuántas de esas son optativas?",
            "¿Qué asignaturas se dan en primer curso de Informática?",
        ],
        CATALOGO_PRUEBA,
    )
    assert "optativas" not in consulta
    assert "Informática" in consulta
    assert consulta.endswith("¿Y en el segundo?")


def test_si_ninguna_anterior_nombra_titulacion_no_se_arrastra_nada():
    """Arrastrar preguntas que tampoco tienen sujeto solo mete ruido."""
    consulta = consulta_con_historial(
        "¿y en el segundo?", ["¿y las optativas?", "¿cuántas son?"], CATALOGO_PRUEBA
    )
    assert consulta == "¿y en el segundo?"


def test_sin_catalogo_se_arrastra_como_antes():
    """El comportamiento previo se conserva cuando no hay con qué decidir."""
    consulta = consulta_con_historial("la actual", ["una", "dos", "tres"])
    assert consulta == "dos tres la actual"

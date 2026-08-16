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
    Fragmento,
    ModeloDiscrepante,
    abrir_indice,
    distancia_del_indice,
    recuperar,
)

DIMENSION = 8

SIMPLE = "Grado en Ingeniería Eléctrica"
DOBLE = "Doble Grado en Ingeniería Eléctrica y Mecánica"
INFORMATICA = "Grado en Ingeniería Informática"


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
    recuperar("una pregunta", tabla, incrustador_falso, grado=SIMPLE)
    assert tabla.registro["prefilter"] is True
    assert "array_has_any" in tabla.registro["where"]


def test_filtrar_por_una_titulacion_no_arrastra_el_doble_grado(indice):
    """El caso real: «Grado en Ingeniería Eléctrica» es subcadena del doble.

    Una coincidencia por subcadena devolvería también los fragmentos que solo
    pertenecen al doble grado. Sobre el corpus completo eso son 167 falsos
    positivos.
    """
    tabla = abrir_indice(indice, MODELO)
    fragmentos = recuperar("asignaturas", tabla, incrustador_falso, k=10, grado=SIMPLE)
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
        "asignaturas", tabla, incrustador_falso, k=1, grado=INFORMATICA
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


def test_k_por_defecto_es_el_del_modulo():
    tabla = TablaEspia()
    recuperar("una pregunta", tabla, incrustador_falso)
    assert tabla.registro["k"] == K_POR_DEFECTO

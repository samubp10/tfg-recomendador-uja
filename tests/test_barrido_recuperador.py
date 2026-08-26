"""Pruebas de la rejilla del recuperador (IT-49).

Lo que hay que asegurar aquí es que el corte simulado **es el mismo** que el que
aplica el sistema. Si se separan, la rejilla elegiría los parámetros de otro
recuperador y nadie se enteraría: las cifras seguirían pareciendo razonables.
Por eso la prueba central compara las dos implementaciones sobre las mismas
listas en vez de comprobar la simulada por su cuenta.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "experimentos"))

import barrido_recuperador as barrido  # noqa: E402

from tfg_uja.recuperador import Fragmento, acotar_por_distancia  # noqa: E402


def recuperados(distancias: list[float]) -> list[barrido.Recuperado]:
    """Lista simulada, ya ordenada, con una unidad distinta por fragmento."""
    return [
        barrido.Recuperado(f"unidad {i}", "guia", d) for i, d in enumerate(distancias)
    ]


def fragmentos(distancias: list[float]) -> list[Fragmento]:
    """La misma lista, en la estructura que usa el sistema."""
    return [
        Fragmento(
            texto="",
            nombre=f"unidad {i}",
            grados=[],
            origen="guia",
            distancia=d,
            chunk_index=0,
            total_chunks=1,
        )
        for i, d in enumerate(distancias)
    ]


LISTAS = [
    [0.10, 0.11, 0.115, 0.13, 0.20, 0.30],
    [0.05, 0.051, 0.052, 0.053, 0.054],
    [0.16, 0.17, 0.18],
    [0.142, 0.142, 0.9],
]


def test_el_corte_simulado_es_el_del_sistema():
    """La rejilla no puede optimizar un recuperador distinto del que se ejecuta."""
    for distancias in LISTAS:
        for config in barrido.rejilla()[::17]:
            simulado = barrido.acotar(recuperados(distancias), config)
            real = acotar_por_distancia(
                fragmentos(distancias),
                minimo=config.minimo,
                maximo=config.maximo,
                factor=config.factor,
                suelo=config.suelo,
            )
            assert [r.distancia for r in simulado] == [
                f.distancia for f in real
            ], f"discrepan con {config} sobre {distancias}"


def test_una_lista_vacia_no_devuelve_nada():
    config = barrido.Configuracion(3, 20, 1.20, 0.142)
    assert barrido.acotar([], config) == []


def test_por_encima_del_suelo_no_se_devuelve_nada():
    """Es la rama que rechaza lo ajeno al dominio, y el mínimo no la anula."""
    config = barrido.Configuracion(3, 20, 1.20, 0.142)
    assert barrido.acotar(recuperados([0.15, 0.16]), config) == []


def test_la_unidad_se_acierta_por_cualquiera_de_sus_fragmentos():
    """Para responder basta con alcanzar la asignatura, no todos sus trozos."""
    devueltos = recuperados([0.10, 0.11, 0.12])
    assert barrido.acierta_la_unidad(
        devueltos, [{"origen": "guia", "nombre": "unidad 2"}]
    )
    assert not barrido.acierta_la_unidad(
        devueltos, [{"origen": "guia", "nombre": "unidad 9"}]
    )


def test_el_origen_forma_parte_de_la_identidad_de_la_unidad():
    """Una guía y unas salidas pueden llamarse igual: son unidades distintas."""
    devueltos = recuperados([0.10])
    assert not barrido.acierta_la_unidad(
        devueltos, [{"origen": "salidas", "nombre": "unidad 0"}]
    )


def test_medir_cuenta_las_preguntas_sin_contexto():
    config = barrido.Configuracion(3, 20, 1.20, 0.142)
    dominio = [
        (recuperados([0.10, 0.11]), [{"origen": "guia", "nombre": "unidad 0"}]),
        (recuperados([0.90]), [{"origen": "guia", "nombre": "unidad 0"}]),
    ]
    medido = barrido.medir(config, dominio, [])
    assert medido["sin_contexto"] == 1
    assert medido["unidad"] == 0.5


def test_medir_cuenta_el_rechazo_de_lo_ajeno():
    config = barrido.Configuracion(3, 20, 1.20, 0.142)
    ajenas = [recuperados([0.90]), recuperados([0.10])]
    medido = barrido.medir(config, [], ajenas)
    assert medido["rechazo"] == 0.5


def test_la_rejilla_no_propone_un_minimo_mayor_que_el_maximo():
    for config in barrido.rejilla():
        assert config.minimo <= config.maximo

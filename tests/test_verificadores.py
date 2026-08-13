"""Pruebas comunes a los cuatro verificadores del corpus (IT-10).

Los guiones de ``scripts/check_*.py`` auditan el dataset, que no está
versionado y por tanto no existe en CI. Lo que sí se puede comprobar sin él es
que **puedan** comprobar: que sus invariantes no dependan de una construcción
del lenguaje que se desactiva desde la línea de órdenes, y que la sustituta se
comporte como se espera.

Van juntas y no repartidas por verificador porque la propiedad es de los
cuatro a la vez: en cuanto uno vuelva a usar ``assert``, este fichero lo dice.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tfg_uja.invariantes import InvarianteRoto, exigir

RAIZ = Path(__file__).resolve().parent.parent
VERIFICADORES = sorted((RAIZ / "scripts").glob("check_*.py"))


def test_hay_verificadores_que_revisar() -> None:
    """Sin esto, la prueba de abajo pasaría en verde sobre una lista vacía.

    Es el mismo error que persigue todo este fichero: una comprobación que no
    comprueba nada y lo celebra. Si algún día se renombran los guiones, esta
    falla y avisa de que la otra dejó de mirar donde debía.
    """
    assert len(VERIFICADORES) >= 4, [p.name for p in VERIFICADORES]


@pytest.mark.parametrize("ruta", VERIFICADORES, ids=lambda p: p.name)
def test_ningun_verificador_comprueba_con_assert(ruta: Path) -> None:
    """Ningún invariante puede depender de ``assert``.

    ``python -O`` elimina los ``assert`` del programa. Con ellos, los guiones
    recorrían el corpus entero sin comprobar nada y terminaban imprimiendo su
    «OK» de siempre, que es el modo de fallo que este proyecto ya ha sufrido
    cuatro veces por otras vías: el verificador que dice «OK» sin verificar.

    Se analiza el árbol sintáctico para que la comprobación no dependa de cómo
    esté escrita la línea.
    """
    asserts = [
        nodo
        for nodo in ast.walk(ast.parse(ruta.read_text(encoding="utf-8")))
        if isinstance(nodo, ast.Assert)
    ]

    assert not asserts, (
        f"{len(asserts)} `assert` en {ruta.name} (línea(s) "
        f"{[n.lineno for n in asserts]}): con `python -O` desaparecen y el "
        f"verificador diría «OK» sin comprobar nada. Usar `exigir()`."
    )


def test_exigir_deja_pasar_lo_que_se_cumple() -> None:
    """El caso bueno no debe abortar ni construir el mensaje."""
    exigir(True, "no debe saltar")
    exigir([1, 2], "no debe saltar")


def test_exigir_aborta_cuando_el_invariante_falla() -> None:
    """La sustituta de ``assert`` tiene que abortar de verdad."""
    with pytest.raises(InvarianteRoto, match="mensaje de prueba"):
        exigir(False, "mensaje de prueba")


def test_exigir_trata_las_colecciones_vacias_como_falsas() -> None:
    """Media comprobación pasa una lista que debe estar vacía.

    ``exigir(not sucios, ...)`` y ``exigir(sucios == [], ...)`` conviven en los
    guiones; el valor de verdad tiene que funcionar igual que en ``assert``.
    """
    with pytest.raises(InvarianteRoto):
        exigir([], "una lista vacía es falsa")
    exigir(["algo"], "una lista con elementos es verdadera")


def test_exigir_no_evalua_el_mensaje_si_no_hace_falta() -> None:
    """El mensaje perezoso solo se construye cuando el invariante falla.

    ``assert`` construía su mensaje solo al fallar; una llamada normal lo
    evalúa siempre. Varios mensajes de los verificadores miran el primer
    elemento de la colección que ha fallado, así que al pasar a función
    reventaban con ``IndexError`` justo en el caso bueno. La lambda restituye
    esa pereza, y esta prueba es el caso real que lo destapó.
    """
    vacia: list[int] = []

    # Si el mensaje se evaluara, `vacia[0]` lanzaría IndexError.
    exigir(not vacia, lambda: f"el primero es {vacia[0]}")


def test_exigir_si_falla_si_construye_el_mensaje_perezoso() -> None:
    """Y cuando falla, el mensaje tiene que llegar entero."""
    llena = [7]

    with pytest.raises(InvarianteRoto, match="el primero es 7"):
        exigir(not llena, lambda: f"el primero es {llena[0]}")

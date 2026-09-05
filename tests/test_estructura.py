"""Límites de tamaño y anidamiento de las funciones de producción (IT-111)."""

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1] / "src" / "tfg_uja"
AMBITOS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
BLOQUES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.TryStar,
    ast.Match,
    ast.ExceptHandler,
)


def _medir(nodo: ast.AST, nivel: int = 0) -> tuple[int, int]:
    """Cuenta sentencias sin docstrings ni cuerpos de ámbitos independientes.

    Cada bloque del AST suma un nivel, incluidos los ``elif`` y ``except``.
    Las funciones y métodos anidados se comprueban por separado.
    """
    if isinstance(nodo, AMBITOS):
        return 1, nivel
    es_docstring = (
        isinstance(nodo, ast.Expr)
        and isinstance(nodo.value, ast.Constant)
        and isinstance(nodo.value.value, str)
    )
    sentencias = int(isinstance(nodo, ast.stmt) and not es_docstring)
    nivel += int(isinstance(nodo, BLOQUES))
    profundidad = nivel
    for hijo in ast.iter_child_nodes(nodo):
        cantidad, fondo = _medir(hijo, nivel)
        sentencias += cantidad
        profundidad = max(profundidad, fondo)
    return sentencias, profundidad


@pytest.mark.parametrize("ruta", sorted(RAIZ.rglob("*.py")), ids=lambda p: p.name)
def test_funciones_con_hasta_40_sentencias_y_4_niveles(ruta):
    """Comprueba todas las funciones, incluidos los métodos y las anidadas."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    excesos = []
    for funcion in ast.walk(arbol):
        if not isinstance(funcion, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        medidas = [_medir(nodo) for nodo in funcion.body]
        cantidad = sum(m[0] for m in medidas)
        niveles = max(m[1] for m in medidas)
        if cantidad > 40 or niveles > 4:
            excesos.append(f"{funcion.name}: {cantidad} sentencias, {niveles} niveles")
    assert not excesos, "\n".join(excesos)

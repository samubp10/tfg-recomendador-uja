"""Validación de las filas extraídas de la tabla de asignaturas."""

from __future__ import annotations

import re
from typing import Final

# Tipos publicados: FB, OB, OP, obligatorias de especialidad y TFG.
TIPOS_VALIDOS: Final[frozenset[str]] = frozenset(
    {"FB", "OB", "OP", "OB-IS", "OB-SI", "OB-TI", "TFG"}
)

#: Patrón de los nombres de relleno de la tabla ("Optativa 1", "Optativa 2"...),
#: que no corresponden a asignaturas reales.
_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"^optativa\s+\d+$", re.IGNORECASE)

#: Mapeo de tipos textuales a las abreviaturas esperadas (para grados nuevos
#: como el de IA y Ciberseguridad que no usan las abreviaturas cortas).
_MAPA_TIPOS: Final[dict[str, str]] = {
    "formación básica": "FB",
    "obligatoria": "OB",
    "optativa": "OP",
    # Los planes de dobles grados escriben OBL donde los simples usan OB.
    "obl": "OB",
}


def normalizar_tipo(tipo: str | None) -> str:
    """Mapea tipos textuales a las abreviaturas esperadas."""
    tipo = (tipo or "").strip()
    return _MAPA_TIPOS.get(tipo.lower(), tipo)


def es_placeholder(nombre: str | None) -> bool:
    """Indica si un nombre es un marcador de posición, no una asignatura."""
    return bool(_PLACEHOLDER.match((nombre or "").strip()))


def es_asignatura_valida(
    codigo: str | None, nombre: str | None, tipo: str | None
) -> bool:
    """Decide si una fila de la tabla es una asignatura real."""
    nombre = (nombre or "").strip()
    if not nombre or es_placeholder(nombre):
        return False
    if (tipo or "").strip().upper() not in TIPOS_VALIDOS:
        return False
    return True

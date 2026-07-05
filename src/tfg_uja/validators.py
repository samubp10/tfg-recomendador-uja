"""Validación y normalización de tipos de asignatura."""
from __future__ import annotations

"""Validación de las filas extraídas de la tabla de asignaturas.

La tabla de asignaturas de un grado mezcla asignaturas reales con filas que
no lo son (marcadores de posición como "Optativa 1"). Este módulo decide qué
filas representan una asignatura válida y cuáles deben descartarse.
"""

import re
from typing import Final

#: Tipos de asignatura reconocidos en las tablas de la EPSJ.
#: FB (formación básica), OB (obligatoria), OP (optativa) y las variantes
#: de obligatoria de especialidad (OB-IS, OB-SI, OB-TI). TFG (trabajo fin de
#: grado) aparece como carácter propio en algunos planes (p. ej. IA y
#: Ciberseguridad), mientras que otros lo etiquetan como OB; se acepta tal
#: cual para no perder la asignatura ni imponer una uniformidad que la fuente
#: no tiene.
TIPOS_VALIDOS: Final[frozenset[str]] = frozenset(
    {"FB", "OB", "OP", "OB-IS", "OB-SI", "OB-TI", "TFG"}
)

#: Patrón de los nombres de relleno de la tabla ("Optativa 1", "Optativa 2"...),
#: que no corresponden a asignaturas reales.
_PLACEHOLDER: re.Pattern[str] = re.compile(r"^optativa\s+\d+$", re.IGNORECASE)

#: Mapeo de tipos textuales a las abreviaturas esperadas (para grados nuevos
#: como el de IA y Ciberseguridad que no usan las abreviaturas cortas).
_MAPEO_TIPOS: Final[dict[str, str]] = {
    "Formación básica": "FB",
    "Obligatoria": "OB",
    "Optativa": "OP",
}


def es_placeholder(nombre: str) -> bool:
    """Indica si un nombre es un marcador genérico ('optativa 1')."""
    return bool(_PLACEHOLDER.match(nombre.strip()))


def es_asignatura_valida(nombre: str | None, tipo: str | None) -> bool:
    """Valida que una asignatura tenga nombre real y tipo reconocido."""
    if not nombre or es_placeholder(nombre):
        return False
    
    if normalizar_tipo(tipo) is None:
        return False
        
    return True


def normalizar_tipo(tipo: str | None) -> str | None:
    """Normaliza el tipo textual a su código (FB/OB/OP...).

    Returns:
        El código normalizado, o None si no se reconoce el tipo.
    """
    if not tipo:
        return None
    
    tipo_limpio = tipo.strip()
    tipo_cap = tipo_limpio.capitalize()
    
    if tipo_cap in _MAPEO_TIPOS:
        return _MAPEO_TIPOS[tipo_cap]
        
    tipo_upper = tipo_limpio.upper()
    if tipo_upper in TIPOS_VALIDOS:
        return tipo_upper
        
    return None

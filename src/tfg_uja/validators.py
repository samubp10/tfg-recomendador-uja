"""Validación de las filas extraídas de la tabla de asignaturas.

La tabla de asignaturas de un grado mezcla asignaturas reales con filas que
no lo son (marcadores de posición como "Optativa 1"). Este módulo decide qué
filas representan una asignatura válida y cuáles deben descartarse.
"""

from __future__ import annotations

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
_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"^optativa\s+\d+$", re.IGNORECASE)

#: Mapeo de tipos textuales a las abreviaturas esperadas (para grados nuevos
#: como el de IA y Ciberseguridad que no usan las abreviaturas cortas).
_MAPA_TIPOS: Final[dict[str, str]] = {
    "formación básica": "FB",
    "obligatoria": "OB",
    "optativa": "OP",
}


def normalizar_tipo(tipo: str | None) -> str:
    """Mapea tipos textuales a las abreviaturas esperadas.

    Args:
        tipo (str): Tipo de asignatura extraído de la web.

    Returns:
        str: El tipo convertido a abreviatura, o el tipo original si no mapea.
    """
    tipo = (tipo or "").strip()
    return _MAPA_TIPOS.get(tipo.lower(), tipo)


def es_placeholder(nombre: str | None) -> bool:
    """Indica si un nombre es un marcador de posición, no una asignatura.

    Args:
        nombre (str): Nombre de la asignatura, ya limpio.

    Returns:
        bool: ``True`` si el nombre es del tipo "Optativa N".
    """
    return bool(_PLACEHOLDER.match((nombre or "").strip()))


def es_asignatura_valida(
    codigo: str | None, nombre: str | None, tipo: str | None
) -> bool:
    """Decide si una fila de la tabla es una asignatura real.

    Una fila se considera asignatura válida cuando tiene un nombre que no es
    un marcador de posición y un tipo reconocido. El código puede faltar en
    algunos casos legítimos, por lo que no se exige, pero si el nombre es un
    placeholder la fila se descarta aunque traiga otros datos.

    Args:
        codigo (str): Código de la asignatura, puede estar vacío.
        nombre (str): Nombre de la asignatura, ya limpio.
        tipo (str): Tipo de asignatura (FB, OB, OP, ...).

    Returns:
        bool: ``True`` si la fila representa una asignatura válida.
    """
    nombre = (nombre or "").strip()
    if not nombre or es_placeholder(nombre):
        return False
    if (tipo or "").strip().upper() not in TIPOS_VALIDOS:
        return False
    return True
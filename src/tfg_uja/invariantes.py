"""Comprobación de invariantes de los verificadores del dataset (IT-10)."""

from __future__ import annotations

from collections.abc import Callable


class InvarianteRoto(AssertionError):
    """Un invariante del dataset no se cumple."""


def exigir(condicion: object, mensaje: str | Callable[[], str]) -> None:
    """Comprueba un invariante incluso con python -O.

    Raises:
        InvarianteRoto: Si la condición es falsa.
    """
    if not condicion:
        raise InvarianteRoto(mensaje() if callable(mensaje) else mensaje)

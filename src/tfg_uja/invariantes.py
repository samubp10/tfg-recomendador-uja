"""Comprobación de invariantes de los verificadores del dataset (IT-10).

Los cuatro guiones de ``scripts/`` que auditan el corpus comprobaban sus
invariantes con ``assert``, y **el intérprete elimina los ``assert`` al
ejecutar con ``-O``**: con esa bandera recorrían el dataset entero sin
comprobar nada y terminaban imprimiendo su «OK» de siempre.

Ese es exactamente el modo de fallo que este proyecto ya ha sufrido cuatro
veces por otras vías —el verificador que dice «OK» sin verificar—, solo que
servido por el propio lenguaje. La sustituta vive aquí, y no copiada en cada
guion, para que no puedan discrepar entre sí: es la misma razón por la que
``incrustaciones.py`` centraliza los prefijos que comparten el indexador y el
recuperador.
"""

from __future__ import annotations

from collections.abc import Callable


class InvarianteRoto(AssertionError):
    """Un invariante del dataset no se cumple.

    Hereda de ``AssertionError`` para que el reemplazo de ``assert`` no
    cambie lo que ve quien capture la excepción por su tipo.
    """


def exigir(condicion: object, mensaje: str | Callable[[], str]) -> None:
    """Comprueba un invariante y aborta si no se cumple.

    El mensaje admite una función sin argumentos, y no es una comodidad:
    ``assert`` construye su mensaje **solo cuando la condición falla**, y una
    llamada normal lo evalúa siempre. Varios mensajes de los verificadores
    muestran el primer elemento del conjunto que ha fallado
    ---``descuadres[0]``, ``min(evitables)``---, así que reventarían con
    ``IndexError`` justo en el caso bueno, con la colección vacía. Con una
    lambda el mensaje vuelve a ser perezoso.

    Args:
        condicion: Lo que tiene que ser cierto. Se admite cualquier objeto y
            se evalúa su valor de verdad, como hacía ``assert``: media
            comprobación de los verificadores pasa una lista o un conjunto
            que debe estar vacío.
        mensaje: Qué se ha roto, con las cifras que lo demuestran. Si mirar
            esas cifras solo tiene sentido cuando el invariante falla, se pasa
            como función.

    Raises:
        InvarianteRoto: Si ``condicion`` es falsa.
    """
    if not condicion:
        raise InvarianteRoto(mensaje() if callable(mensaje) else mensaje)

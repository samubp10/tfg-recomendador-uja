"""Modelo de incrustaciones y su convención de llamada (IT-98, ADR-0003)."""

from __future__ import annotations

import os
from typing import Callable, Final

#: Variable de entorno que autoriza la descarga del modelo desde el Hub.
#: Puesta a ``"1"``, :func:`cargar_modelo` deja que ``sentence_transformers``
#: salga a la red; sin ella, el modelo se carga solo desde la caché local.

# La red queda desactivada salvo autorización mediante esta variable.
VARIABLE_DESCARGA: Final[str] = "TFG_DESCARGAR_MODELO"

# Modelo elegido en ADR-0003 mediante IT-28, sobre dos corpus.

# Su ventana de 512 tokens permite leer enteros los fragmentos del experimento.
MODELO: Final[str] = "intfloat/multilingual-e5-small"

#: Prefijo de los textos que se indexan (los fragmentos del corpus).
PREFIJO_DOCUMENTO: Final[str] = "passage: "

#: Prefijo de los textos que se consultan (las preguntas del usuario).
PREFIJO_CONSULTA: Final[str] = "query: "

#: Firma de la función de incrustación: recibe una lista de textos y
#: devuelve un vector de números reales por texto, en el mismo orden.
Incrustador = Callable[[list[str]], list[list[float]]]


def con_prefijo(prefijo: str, incrustar: Incrustador) -> Incrustador:
    """Antepone el prefijo de documento o consulta al incrustar."""

    def incrustar_con_papel(textos: list[str]) -> list[list[float]]:
        return incrustar([prefijo + texto for texto in textos])

    return incrustar_con_papel


def cargar_modelo(nombre: str = MODELO) -> Incrustador:
    """Carga el modelo sin prefijos; solo descarga con TFG_DESCARGAR_MODELO=1.

    Raises:
        RuntimeError: Si falta la copia local y no se autorizó la descarga.
    """
    from sentence_transformers import SentenceTransformer

    descargar = os.environ.get(VARIABLE_DESCARGA) == "1"
    try:
        modelo = SentenceTransformer(nombre, local_files_only=not descargar)
    except Exception as error:  # noqa: BLE001 - se reetiqueta y se relanza
        if descargar:
            raise
        raise RuntimeError(
            f"El modelo de incrustaciones «{nombre}» no está en la caché "
            f"local y no se ha autorizado descargarlo. Para traerlo una "
            f"sola vez: {VARIABLE_DESCARGA}=1 con conexión a internet. "
            f"Después el sistema vuelve a funcionar sin red."
        ) from error

    def incrustar(textos: list[str]) -> list[list[float]]:
        return modelo.encode(textos, show_progress_bar=False).tolist()

    return incrustar


def incrustador_de_documentos(nombre: str = MODELO) -> Incrustador:
    """Incrustador para los fragmentos que van al índice."""
    return con_prefijo(PREFIJO_DOCUMENTO, cargar_modelo(nombre))


def incrustador_de_consultas(nombre: str = MODELO) -> Incrustador:
    """Incrustador para las preguntas del usuario."""
    return con_prefijo(PREFIJO_CONSULTA, cargar_modelo(nombre))

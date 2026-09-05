"""Recomendador de titulaciones de la Universidad de Jaén basado en RAG."""

from pathlib import Path
from typing import Final

#: Raíz del repositorio, de donde cuelgan ``data/``, ``eval/`` y ``web/``.

# Raíz compartida, independiente de la profundidad de cada subpaquete.

#: Este fichero es el único que no se mueve nunca, porque es el que define el
#: paquete, así que la cuenta hecha desde aquí no puede quedarse obsoleta al
#: mover nada.
RAIZ: Final[Path] = Path(__file__).resolve().parent.parent.parent

"""Recomendador de titulaciones de la Universidad de Jaén basado en RAG.

El paquete está repartido en las cuatro fases del trabajo, que son las mismas
con las que están escritos los capítulos de la memoria:
:mod:`~tfg_uja.extraccion`, :mod:`~tfg_uja.indexacion`, :mod:`~tfg_uja.dialogo`
y :mod:`~tfg_uja.aplicacion`. Las dependencias van siempre hacia atrás
---la aplicación usa el diálogo, el diálogo usa la indexación--- y nunca al
revés, que es lo que hace que el reparto se sostenga.

Fuera de los cuatro quedan :mod:`~tfg_uja.text_cleaner` e
:mod:`~tfg_uja.invariantes`, que no pertenecen a ninguna fase porque los usan
todas.
"""

from pathlib import Path
from typing import Final

__version__ = "0.1.0"

#: Raíz del repositorio, de donde cuelgan ``data/``, ``eval/`` y ``web/``.
#:
#: **Vive aquí y no en cada módulo que la necesita.** La calculaban por su
#: cuenta tres módulos con ``Path(__file__).parent.parent.parent``, cuenta que
#: solo es correcta mientras el fichero esté exactamente a dos niveles de
#: ``src/``. Al repartir el paquete en subpaquetes se quedaría corta **sin dar
#: ningún error**: apuntaría a ``src/`` y ``data/`` dejaría de encontrarse.
#:
#: Este fichero es el único que no se mueve nunca, porque es el que define el
#: paquete, así que la cuenta hecha desde aquí no puede quedarse obsoleta al
#: mover nada.
RAIZ: Final[Path] = Path(__file__).resolve().parent.parent.parent

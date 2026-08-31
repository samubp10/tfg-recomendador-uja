"""Todo guion de ``scripts/`` tiene que poder cargarse (IT-111).

Es la comprobación que faltaba cuando IT-114 agrupó los guiones en carpetas. El
movimiento dejó ``repeticiones_vectordb.py`` cargando el experimento por una
ruta que desde entonces no existe, y el guion reventaba nada más importarse::

    FileNotFoundError: ...scripts/experimento_vectordb.py

La tanda entera seguía en verde, porque ninguna prueba lo cargaba. Cargar es lo
mínimo que se le puede pedir a un guion, y era justo lo que nadie comprobaba:
quinto caso de la serie de este proyecto, la comprobación que dice «OK» sobre
algo que no ha mirado.

Se carga el módulo y nada más: no se mide, no se llama al servidor de
inferencia y no se toca ``data/``. Los guiones dejan sus importaciones caras
---``sentence_transformers``, ``chromadb``, ``qdrant_client``--- dentro de las
funciones, así que esto se sostiene con lo que instala ``pip install -e
".[dev]"`` y no obliga al CI a bajarse PyTorch.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

#: Todos los guiones, en las tres carpetas y en la raíz de ``scripts/``. Se
#: buscan en vez de enumerarse para que un guion nuevo entre solo: una lista
#: escrita a mano se queda corta en silencio, que es el defecto que persigue
#: este fichero.
GUIONES = sorted((RAIZ / "scripts").rglob("*.py"))

#: Nombres que los guiones dejan en ``sys.modules`` al cargarse. Se retiran
#: después de cada caso para que uno no se encuentre cargado el módulo que
#: otro registró y la prueba pase por el trabajo de un vecino.
NOMBRES = {ruta.stem for ruta in GUIONES}


def test_hay_guiones_que_cargar() -> None:
    """Sin esto, la prueba de abajo pasaría en verde sobre una lista vacía.

    Es el mismo error que persigue el fichero entero. Si se vuelven a mover
    los guiones y el patrón deja de encontrarlos, falla esta y avisa de que la
    otra ya no mira donde debía.
    """
    assert len(GUIONES) >= 16, [ruta.name for ruta in GUIONES]


@pytest.mark.parametrize("ruta", GUIONES, ids=lambda ruta: ruta.name)
def test_el_guion_carga(ruta: Path) -> None:
    """El guion se importa sin reventar.

    Se carga por su ruta porque ``scripts/`` no es un paquete importable. Se
    añade su carpeta al camino de búsqueda durante la carga para reproducir lo
    que hace el intérprete al ejecutarlo de verdad: ``experimento_sistema``
    importa a ``experimento_generacion``, que es su vecino de carpeta.

    Args:
        ruta: Guion que se carga.
    """
    carpeta = str(ruta.parent)
    espec = importlib.util.spec_from_file_location(ruta.stem, ruta)
    assert espec is not None and espec.loader is not None, ruta

    modulo = importlib.util.module_from_spec(espec)
    sys.path.insert(0, carpeta)
    # Se registra antes de ejecutarlo porque algunos guiones definen
    # `@dataclass`, y `dataclasses` resuelve las anotaciones buscando el módulo
    # por su nombre.
    sys.modules[ruta.stem] = modulo
    try:
        espec.loader.exec_module(modulo)
    finally:
        sys.path.remove(carpeta)
        for nombre in NOMBRES:
            sys.modules.pop(nombre, None)

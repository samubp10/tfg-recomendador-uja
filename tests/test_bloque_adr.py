"""El bloque automático de cada ADR sigue siendo el mismo (IT-111).

Cuatro experimentos escriben sus cifras dentro de su ADR, entre dos marcas. El
proyecto comprueba ese bloque con ``diff``, así que un cambio de formato ---un
salto de línea de más al colocarlo--- produce una diferencia que nadie sabe
explicar y obliga a repetir tandas de horas para averiguar si es cosmética.

Aquí se coge el bloque que hoy tiene cada ADR, se vuelve a colocar con el guion
que lo escribe y se exige que el fichero quede **byte a byte** igual. Es lo que
permitió unificar las cuatro copias de la función que lo coloca sin tocar
ninguna cifra publicada, y lo que avisará si alguna se desvía.

De paso comprueba que la marca que compone el guion es exactamente la que
lleva el ADR: son dos ficheros distintos y mover el guion desincroniza una de
las dos sin que nada falle hasta la siguiente ejecución.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parent.parent
CARPETA = RAIZ / "scripts" / "experimentos"

#: Guion, ADR que escribe, atributo con la ruta, función que coloca el bloque y
#: si el guion entrega el bloque con las marcas dentro o sin ellas. Las dos
#: formas conviven a propósito: separan la marca de cierre con distinto número
#: de saltos, e igualarlas cambiaría los bytes de dos ADR ya publicados.
CASOS = [
    ("experimento_vectordb", "adr-0004-base-vectorial.md", "RUTA_ADR", True),
    ("experimento_generacion", "adr-0005-modelo-de-generacion.md", "RUTA_ADR", True),
    (
        "experimento_fragmentacion",
        "adr-0001-estrategia-chunking.md",
        "RUTA_SALIDA",
        False,
    ),
    (
        "experimento_embeddings",
        "adr-0003-modelo-de-embeddings.md",
        "RUTA_RESULTADOS",
        False,
    ),
]


def _cargar(nombre: str) -> Any:
    """Carga un guion por su ruta, que es como se cargan aquí.

    Args:
        nombre: Nombre del módulo, sin extensión.

    Returns:
        El módulo ya ejecutado.
    """
    if str(CARPETA) not in sys.path:
        sys.path.insert(0, str(CARPETA))
    espec = importlib.util.spec_from_file_location(nombre, CARPETA / f"{nombre}.py")
    assert espec is not None and espec.loader is not None, nombre
    modulo = importlib.util.module_from_spec(espec)
    sys.modules[nombre] = modulo
    espec.loader.exec_module(modulo)
    return modulo


@pytest.mark.parametrize(
    "nombre, adr, atributo, con_marcas", CASOS, ids=lambda v: str(v)
)
def test_la_marca_del_guion_esta_en_su_adr(
    nombre: str, adr: str, atributo: str, con_marcas: bool
) -> None:
    """La marca que compone el guion es la que lleva el documento.

    Si no coincide, la siguiente ejecución falla o ---peor--- escribe donde no
    debe. Es lo que pasó al agrupar los guiones en carpetas.
    """
    modulo = _cargar(nombre)
    texto = (RAIZ / "docs" / "adr" / adr).read_text(encoding="utf-8")

    assert modulo.MARCA_INICIO in texto, modulo.MARCA_INICIO
    assert modulo.MARCA_FIN in texto


@pytest.mark.parametrize(
    "nombre, adr, atributo, con_marcas", CASOS, ids=lambda v: str(v)
)
def test_recolocar_el_bloque_no_cambia_el_adr(
    nombre: str,
    adr: str,
    atributo: str,
    con_marcas: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Volver a colocar el bloque de hoy deja el ADR exactamente igual.

    Se trabaja sobre una copia: una prueba que reescriba el ADR de verdad
    convierte un fallo en una pérdida.
    """
    modulo = _cargar(nombre)
    copia = tmp_path / adr
    shutil.copyfile(RAIZ / "docs" / "adr" / adr, copia)
    antes = copia.read_bytes()

    texto = copia.read_text(encoding="utf-8")
    dentro = texto.split(modulo.MARCA_INICIO, 1)[1].split(modulo.MARCA_FIN, 1)[0]
    bloque = modulo.MARCA_INICIO + dentro + modulo.MARCA_FIN if con_marcas else dentro

    monkeypatch.setattr(modulo, atributo, copia)
    if nombre == "experimento_embeddings":
        modulo.escribir_en_el_adr(copia, bloque)
    elif nombre == "experimento_fragmentacion":
        modulo.escribir_en_el_adr(bloque)
    elif nombre == "experimento_generacion":
        modulo.escribir_adr(bloque)
    else:
        modulo.escribir_resultados(bloque)

    assert copia.read_bytes() == antes, f"{adr} cambia al recolocar su propio bloque"

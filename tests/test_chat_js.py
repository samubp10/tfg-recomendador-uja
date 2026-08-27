"""Puente para que las pruebas del cliente entren en la tanda de `pytest`.

`web/chat.js` es código de navegador y no se puede probar con `pytest`, pero
tampoco podía quedarse sin pruebas: son 475 líneas que deciden cómo se ve todo
lo que el modelo responde. Se prueban con `node --test`, que **viene con el
propio intérprete de Node** y no añade ninguna dependencia al proyecto: no hay
`package.json`, ni `node_modules`, ni nada que instalar.

Este fichero solo lanza esa tanda y traduce su resultado, para que
`pytest` siga siendo un único comando y para que un fallo del cliente
aparezca donde se miran los fallos.

Si Node no está instalado, la prueba **se salta y lo dice**. No se finge un
verde: un entorno sin Node no ha comprobado el cliente, y eso tiene que verse
en la salida en vez de quedar como si estuviera todo probado.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

#: Raíz del repositorio. Este fichero vive en `tests/`, así que sube uno.
RAIZ: Path = Path(__file__).resolve().parent.parent

#: La tanda de pruebas del cliente.
PRUEBAS_JS: Path = RAIZ / "tests" / "js" / "chat.test.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")
def test_las_pruebas_del_cliente_pasan() -> None:
    """Ejecuta `node --test` sobre las pruebas de `chat.js`.

    Se comprueba también que el fichero de pruebas exista antes de lanzarlo:
    `node --test` sobre una ruta que no existe falla con un mensaje sobre
    módulos que no se parece en nada a «faltan las pruebas», y ya costó un rato
    entenderlo.
    """
    assert PRUEBAS_JS.is_file(), f"No están las pruebas del cliente en {PRUEBAS_JS}"

    resultado = subprocess.run(
        ["node", "--test", str(PRUEBAS_JS)],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if resultado.returncode != 0:
        pytest.fail(
            "Las pruebas del cliente han fallado:\n\n"
            f"{resultado.stdout}\n{resultado.stderr}",
            pytrace=False,
        )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")
def test_se_prueba_el_fichero_que_se_sirve() -> None:
    """El doble de navegador tiene que cargar `web/chat.js`, no una copia.

    Es la comprobación que impide el fallo que este proyecto lleva repitiendo:
    una prueba en verde que mide algo distinto de lo que cree medir. Si alguien
    apuntara el doble a una copia recortada, las pruebas seguirían pasando y
    dejarían de decir nada sobre lo que se sirve al estudiante.
    """
    doble = RAIZ / "tests" / "js" / "dom_minimo.mjs"
    servido = RAIZ / "web" / "chat.js"

    assert servido.is_file()
    assert 'join(AQUI, "..", "..", "web", "chat.js")' in doble.read_text(
        encoding="utf-8"
    )

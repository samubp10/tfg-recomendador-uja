"""Sustitución del bloque de resultados dentro de un ADR (IT-111).

Cuatro experimentos ---incrustaciones, fragmentación, generación y base
vectorial--- dejan sus cifras dentro de su ADR, en el hueco delimitado
por dos marcas. Cada uno llevaba su propia copia de la misma función, con
cuatro nombres distintos y cuatro mensajes de error distintos para el mismo
fallo. Aquí vive lo que sí es idéntico en las cuatro: comprobar que el
documento existe y lleva sus marcas, y reemplazar lo que hay entre ellas.

**Lo que no se unifica es el texto que va dentro.** Dos de los guiones
componen el bloque con las marcas incluidas y separan la de cierre con un solo
salto de línea; los otros dos entregan solo el contenido y lo separan con dos.
Igualarlos cambiaría los bytes de dos ADR ya publicados, y el bloque se
comprueba con ``diff``, así que cada guion sigue componiendo el suyo y aquí
solo se coloca.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

#: Cierre del bloque. Es igual en los cuatro ADR y no lleva la ruta del guion:
#: con una sola marca de apertura por documento, basta con que sea la de
#: apertura la que diga quién escribe.
MARCA_FIN: Final[str] = "<!-- FIN RESULTADOS AUTOMÁTICOS -->"


def marca_inicio(guion: str) -> str:
    """Compone la marca de apertura de un guion.

    La ruta viaja dentro de la marca para que el ADR diga por sí solo quién
    escribe ese bloque. Se pasa escrita a mano y no deducida de ``__file__``
    a propósito: si se dedujera, mover el guion cambiaría la marca en silencio
    y dejaría de encontrar la del ADR, que es un fichero distinto y no se
    entera. Escrita, mover el guion obliga a tocar los dos sitios.

    Args:
        guion: Ruta del guion desde la raíz del repositorio, con barras
            normales, tal como aparece en el ADR.

    Returns:
        La marca completa, comentario de Markdown incluido.
    """
    return f"<!-- INICIO RESULTADOS AUTOMÁTICOS ({guion}) -->"


def sustituir(destino: Path, marca_ini: str, bloque: str) -> None:
    """Reemplaza por ``bloque`` todo lo que haya entre las dos marcas.

    No toca ni una línea del resto del documento: la Decisión y las
    Consecuencias las escribe el autor y ningún guion las redacta.

    Args:
        destino: Fichero del ADR.
        marca_ini: Marca de apertura de este guion, la que devuelve
            :func:`marca_inicio`.
        bloque: Texto que sustituye al anterior, **con las marcas incluidas**.

    Raises:
        SystemExit: Si el ADR no existe o le faltan las marcas. Se falla de
            forma ruidosa a propósito: escribir el bloque al final de un
            fichero que no lo esperaba deja el ADR desordenado sin avisar, y
            crear el documento desde aquí obliga a mantener una plantilla que
            envejece por su cuenta.
    """
    if not destino.exists():
        raise SystemExit(
            f"No existe {destino}: el ADR lo abre su tarjeta, no el guion."
        )
    contenido = destino.read_text(encoding="utf-8")
    if marca_ini not in contenido or MARCA_FIN not in contenido:
        raise SystemExit(
            f"{destino.name} no lleva las marcas de resultados automáticos. "
            "Añádelas donde deba ir el bloque."
        )
    antes, resto = contenido.split(marca_ini, 1)
    _, despues = resto.split(MARCA_FIN, 1)
    destino.write_text(antes + bloque + despues, encoding="utf-8")

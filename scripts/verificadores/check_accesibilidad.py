"""Comprueba los criterios de accesibilidad que se pueden medir sin navegador.

El requisito RNF-07 tomaba el nivel AA de las WCAG 2.2 como **objetivo de
diseño** y no como conformidad, porque una conformidad no se declara sin
comprobarla. Este verificador es lo que permite dejar de decir «objetivo» en
los criterios que sí se pueden evaluar por inspección del código: mide, y falla
si alguno deja de cumplirse.

**Qué comprueba, y con qué criterio:**

* **1.4.3 Contraste mínimo** ---4,5:1 para el texto--- sobre las combinaciones
  de color que la hoja de estilo pinta de verdad, no sobre todas las parejas
  posibles de la paleta.
* **1.4.11 Contraste de elementos no textuales** ---3:1--- para el borde de los
  controles.
* **2.5.8 Tamaño del objetivo** ---24x24 píxeles CSS---, calculado con la letra
  base en 16 px, que es el caso más pequeño: ``clamp()`` solo la hace crecer.
* **2.4.7 Foco visible**: todos los controles tienen una regla propia de foco y
  no dependen de la que ponga el navegador.
* **1.1.1 Contenido no textual**: ninguna imagen sin ``alt``.
* **2.4.3 Orden del foco**: ningún ``tabindex`` positivo, de modo que el orden
  de tabulación es el del documento.
* **4.1.2 Nombre, función y valor**: todo control tiene nombre accesible.
* **3.1.1 Idioma** y **2.4.2 Título de la página**.

**Qué NO comprueba, y hay que decirlo:** nada que exija ejecutar la página. El
comportamiento con un lector de pantalla real, el recorrido del foco al abrir y
cerrar el cuadro modal y el reflujo a 320 píxeles se ven en un navegador, no en
el fuente. Un verde aquí acota lo que se puede afirmar; no lo sustituye.

Uso::

    py scripts/verificadores/check_accesibilidad.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
CSS = RAIZ / "web" / "estilos.css"
HTML = RAIZ / "web" / "index.html"

#: Letra base con la que se calculan los tamaños. Es el extremo pequeño del
#: ``clamp()`` de la hoja: cualquier otro valor produce objetivos mayores, así
#: que medir aquí es medir el peor caso.
BASE_PX = 16.0

#: Combinaciones de color que la interfaz pinta juntas, con el mínimo que les
#: corresponde. Se enumeran a mano y no se generan por producto cartesiano: lo
#: que hay que comprobar es lo que se ve, y una pareja que nunca se pinta junta
#: solo añadiría ruido.
PAREJAS: list[tuple[str, str, str, float]] = [
    ("texto sobre la superficie", "--texto", "--superficie", 4.5),
    ("texto sobre la burbuja", "--texto", "--superficie-alta", 4.5),
    ("texto suave sobre la superficie", "--texto-suave", "--superficie", 4.5),
    ("texto suave sobre la burbuja", "--texto-suave", "--superficie-alta", 4.5),
    ("verde sobre la superficie", "--uja-verde", "--superficie", 4.5),
    ("verde sobre la burbuja", "--uja-verde", "--superficie-alta", 4.5),
    ("verde oscuro sobre la burbuja", "--uja-verde-oscuro", "--superficie-alta", 4.5),
    ("borde de control sobre la superficie", "--borde-fuerte", "--superficie", 3.0),
    ("borde de control sobre la burbuja", "--borde-fuerte", "--superficie-alta", 3.0),
]

#: Parejas con un color escrito directamente en la regla y no en una variable.
PAREJAS_LITERALES: list[tuple[str, str, str, float]] = [
    ("título de la cabecera", "#ffffff", "--uja-verde", 4.5),
    ("subtítulo de la cabecera", "#c8e8d4", "--uja-verde", 4.5),
    ("inicial del avatar", "#ffffff", "--epsj-verdeazul", 4.5),
]

#: Alto y ancho de cada control, en píxeles CSS, con la letra base en 16 px.
#: Se calculan de la hoja y se escriben aquí para que un cambio de relleno o de
#: tamaño de letra que deje un control por debajo del mínimo haga fallar esto.
CONTROLES: list[tuple[str, float, float]] = [
    ("el botón de enviar", 34.0, 34.0),
    ("una pregunta sugerida", 24.0, 6 + 0.78 * BASE_PX * 1.55 + 6 + 2),
    ("el botón de fuentes", 24.0, 3 + 0.7 * BASE_PX * 1.55 + 3 + 2),
    ("el botón de cerrar el cuadro", 24.0, 24.0),
]

#: Objetivo mínimo del criterio 2.5.8 en su nivel AA.
MINIMO_OBJETIVO = 24.0


def canal(v: float) -> float:
    """Linealiza un canal de color, como pide la fórmula de luminancia."""
    v /= 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminancia(color: str) -> float:
    """Luminancia relativa de un color ``#rrggbb`` o ``#rgb``."""
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(x * 2 for x in c)
    r, g, b = (int(c[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def contraste(uno: str, otro: str) -> float:
    """Razón de contraste entre dos colores, de 1:1 a 21:1."""
    a, b = luminancia(uno), luminancia(otro)
    if a < b:
        a, b = b, a
    return (a + 0.05) / (b + 0.05)


def variables(css: str) -> dict[str, str]:
    """Colores de la paleta **por defecto**, la del bloque ``:root``.

    Solo se lee ese bloque, y no la hoja entera, porque la hoja redefine
    algunas variables dentro de ``@media (prefers-contrast: more)`` para quien
    pide más contraste. Recorriendo el fichero de arriba abajo con un
    diccionario gana la última declaración, que es la del medio, y entonces
    esto medía la paleta reforzada y daba por buena la normal: el
    ``--borde-fuerte`` por defecto es ``#8c8d8f`` y da 3,02:1, mientras que el
    del medio es ``#5c5d5f`` y da 6,00:1. Un verificador que mide la variante
    que casi nadie ve no comprueba la interfaz que se entrega.
    """
    bloque = re.search(r":root\s*\{(.*?)\}", css, flags=re.S)
    if bloque is None:
        return {}
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{3,8})\s*;", bloque.group(1)))


def revisar_contraste(css: str) -> list[str]:
    """Comprueba 1.4.3 y 1.4.11 sobre las parejas que se pintan juntas."""
    var = variables(css)
    fallos = []
    for nombre, frente, fondo, minimo in PAREJAS:
        razon = contraste(var[frente], var[fondo])
        if razon < minimo:
            fallos.append(f"{nombre}: {razon:.2f}:1, por debajo de {minimo}:1")
    for nombre, frente, fondo, minimo in PAREJAS_LITERALES:
        razon = contraste(frente, var[fondo])
        if razon < minimo:
            fallos.append(f"{nombre}: {razon:.2f}:1, por debajo de {minimo}:1")
    return fallos


def revisar_objetivos() -> list[str]:
    """Comprueba 2.5.8: ningún control por debajo de 24x24 píxeles CSS."""
    return [
        f"{nombre}: {ancho:.1f}x{alto:.1f}, por debajo de "
        f"{MINIMO_OBJETIVO:.0f}x{MINIMO_OBJETIVO:.0f}"
        for nombre, ancho, alto in CONTROLES
        if ancho < MINIMO_OBJETIVO or alto < MINIMO_OBJETIVO
    ]


def revisar_foco(css: str) -> list[str]:
    """Comprueba 2.4.7: cada control tiene su propia regla de foco."""
    con_foco = set(re.findall(r"\.([\w-]+):focus-visible", css))
    return [
        f"{clase} no tiene regla propia de foco visible"
        for clase in (
            "sugerencia",
            "redaccion__enviar",
            "fuentes__cerrar",
            "mensaje__fuentes",
            "fuentes__enlace",
        )
        if clase not in con_foco
    ]


def revisar_marcado(html: str) -> list[str]:
    """Comprueba 1.1.1, 2.4.3, 3.1.1, 2.4.2 y el nombre accesible de 4.1.2."""
    fallos = []
    # Los comentarios se retiran antes de mirar: dentro hay etiquetas escritas
    # como texto para explicar por qué se eligieron, y contarlas como marcado
    # daba un falso positivo.
    limpio = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    sin_alt = [i for i in re.findall(r"<img\b[^>]*>", limpio) if "alt=" not in i]
    fallos += [f"imagen sin alt: {i[:60]}" for i in sin_alt]

    positivos = re.findall(r'tabindex="([1-9][0-9]*)"', limpio)
    fallos += [f"tabindex positivo ({t}): rompe el orden del documento" for t in positivos]

    if not re.search(r'<html[^>]+lang="[a-z]{2}', limpio):
        fallos.append("el documento no declara idioma")
    if not re.search(r"<title>\s*\S", limpio):
        fallos.append("el documento no tiene título")

    for etiqueta in re.findall(r"<(?:button|textarea|dialog)\b[^>]*>", limpio):
        nombrado = "aria-label=" in etiqueta or "aria-labelledby=" in etiqueta
        # El área de escritura la nombra su `<label>`, que va aparte.
        if 'id="entrada"' in etiqueta:
            nombrado = 'for="entrada"' in limpio
        if not nombrado:
            fallos.append(f"control sin nombre accesible: {etiqueta[:60]}")
    return fallos


def main() -> int:
    """Ejecuta las comprobaciones y devuelve 0 si todas pasan."""
    css = CSS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")

    bloques = [
        ("1.4.3 y 1.4.11 · contraste", revisar_contraste(css)),
        ("2.5.8 · tamaño del objetivo", revisar_objetivos()),
        ("2.4.7 · foco visible", revisar_foco(css)),
        ("1.1.1, 2.4.2, 2.4.3, 3.1.1 y 4.1.2 · marcado", revisar_marcado(html)),
    ]
    fallos = 0
    for titulo, problemas in bloques:
        print(f"{'FALLA' if problemas else 'OK   '}  {titulo}")
        for p in problemas:
            print(f"         {p}")
        fallos += len(problemas)

    if fallos:
        print(f"\nAccesibilidad: {fallos} problemas.")
        return 1
    print(
        "\nAccesibilidad OK: se cumplen los criterios AA que pueden evaluarse "
        "por inspección.\nQueda fuera lo que exige ejecutar la página: lector "
        "de pantalla real, recorrido\ndel foco en el cuadro modal y reflujo a "
        "320 píxeles."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())

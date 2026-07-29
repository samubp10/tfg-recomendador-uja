"""Auditoría de la extracción de las guías docentes en PDF (IT-95).

Desde el curso 2026-27 **todo** el contenido de la colección se obtiene de
guías servidas en PDF, y la extracción se apoya en una lista de rótulos de
sección escrita a mano contra la plantilla que la UJA usaba al observarla. Si
esa plantilla cambia, una sección deja de terminar donde debe: o se queda
corta, y se pierde contenido, o absorbe la siguiente, y puede arrastrar el
bloque de profesorado hasta el corpus. Ninguna de las dos cosas falla de forma
visible; de ahí este script.

Compara lo que hay en ``data/grados.json`` con los PDF originales que el
rastreo deja en ``data/guias_pdf/``::

    scrapy runspider src/tfg_uja/grados_spider.py -O data/grados.json
    py scripts/check_guias_pdf.py

Acepta rutas alternativas como argumentos::

    py scripts/check_guias_pdf.py otra/ruta/grados.json otra/carpeta_pdf

⚠️ Los PDF guardados contienen datos personales del profesorado. Viven en
``data/``, que no se versiona, y son copia local de trabajo: no salen de la
máquina y el corpus sigue sin ellos.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tfg_uja.guia_pdf import (  # noqa: E402
    PERMITIDOS,
    extraer_guia,
    reparto_por_seccion,
    rotulos_desconocidos,
)


def _pdf_de(carpeta: Path, guia: dict) -> Path:
    """Ruta del PDF guardado para una guía, por su código."""
    return carpeta / f"{guia.get('codigo') or 'sin_codigo'}.pdf"


def main(argv: list[str] | None = None) -> int:
    """Audita la extracción de todas las guías en PDF del dataset.

    Args:
        argv: Ruta del dataset y carpeta de los PDF; por defecto
            ``data/grados.json`` y ``data/guias_pdf``.

    Returns:
        Código de salida (0 si la extracción es fiel a los PDF originales).
    """
    # La consola de Windows fuerza cp1252 y los rótulos de la plantilla llevan
    # tildes y comillas angulares: sin esto la salida sale ilegible.
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    argumentos = argv if argv is not None else sys.argv[1:]
    datos_dir = Path(__file__).resolve().parent.parent / "data"
    ruta = Path(argumentos[0]) if len(argumentos) > 0 else datos_dir / "grados.json"
    carpeta = Path(argumentos[1]) if len(argumentos) > 1 else datos_dir / "guias_pdf"

    dataset = json.loads(ruta.read_text(encoding="utf-8"))
    guias = [d for d in dataset if d["tipo"] == "guia"]
    en_pdf = [g for g in guias if g.get("formato") == "pdf"]
    sin_formato = [g for g in guias if not g.get("formato")]

    reparto = Counter(g.get("formato") or "sin declarar" for g in guias)
    print(f"Guías: {len(guias)}  {dict(reparto)}")
    if sin_formato:
        print(
            f"AVISO: {len(sin_formato)} guías sin el campo `formato` (dataset "
            "anterior a IT-95). Regeneralo para poder auditarlas."
        )
    if not carpeta.is_dir():
        print(
            f"AVISO: no existe {carpeta}. El rastreo guarda ahí los PDF desde "
            "IT-95; sin ellos no hay contra qué comparar y esta auditoría no "
            "puede hacerse. Regenera el dataset."
        )
        return 0

    # --- Los rótulos del PDF siguen siendo los que el código conoce ---
    # Es la comprobación que sostiene todo lo demás: mientras salga vacía, las
    # fronteras de sección caen donde el código cree que caen.
    desconocidos: dict[str, list[str]] = {}
    ausentes: list[str] = []
    discrepancias: list[str] = []
    total_pdf = 0
    total_conservado = 0
    descartado_por_rotulo: Counter[str] = Counter()

    for guia in en_pdf:
        pdf = _pdf_de(carpeta, guia)
        if not pdf.is_file():
            ausentes.append(str(guia.get("codigo")))
            continue
        crudo = pdf.read_bytes()
        codigo = str(guia.get("codigo"))

        nuevos = rotulos_desconocidos(crudo)
        if nuevos:
            desconocidos[codigo] = nuevos

        # Lo que sale hoy del PDF debe ser lo que hay en el dataset: si no
        # coincide, uno de los dos está viejo y las cifras no son de fiar.
        extraido = extraer_guia(crudo) or {"resumen": "", "temario": ""}
        guardado = (guia.get("resumen", ""), guia.get("temario", ""))
        if (extraido["resumen"], extraido["temario"]) != guardado:
            discrepancias.append(codigo)

        for rotulo, largo in reparto_por_seccion(crudo).items():
            total_pdf += largo
            if rotulo in PERMITIDOS:
                total_conservado += largo
            else:
                descartado_por_rotulo[rotulo] += largo

    assert not desconocidos, (
        f"{len(desconocidos)} guía(s) con rótulos de sección que el código no "
        f"conoce, p. ej. {list(desconocidos)[0]}: "
        f"{desconocidos[list(desconocidos)[0]]}. La plantilla de la UJA ha "
        f"cambiado: una sección puede estar quedándose corta (se pierde "
        f"contenido) o tragándose la siguiente (puede arrastrar profesorado)."
    )
    assert not discrepancias, (
        f"{len(discrepancias)} guía(s) donde re-extraer el PDF no reproduce lo "
        f"que hay en el dataset (p. ej. {discrepancias[0]}). El dataset y el "
        f"código no están sincronizados: regenera el dataset."
    )

    if ausentes:
        print(
            f"AVISO: faltan {len(ausentes)} PDF de {len(en_pdf)} en {carpeta} "
            f"(p. ej. {ausentes[0]}); esas guías no se han podido auditar."
        )

    # --- Qué se descarta, con nombre y apellidos ---
    print(f"\nAuditadas {len(en_pdf) - len(ausentes)} guías en PDF.")
    if total_pdf:
        print(
            f"Texto de secciones: {total_pdf} caracteres, de los que se "
            f"conservan {total_conservado} ({100 * total_conservado // total_pdf} %)."
        )
    print("Descartado a propósito, por sección:")
    for rotulo, largo in descartado_por_rotulo.most_common():
        print(f"  {largo:9} {rotulo}")

    print("\nGuías PDF OK: la plantilla es la conocida y la extracción es fiel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
    py scripts/verificadores/check_guias_pdf.py

Acepta rutas alternativas como argumentos::

    py scripts/verificadores/check_guias_pdf.py otra/ruta/grados.json otra/carpeta_pdf

"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from tfg_uja.guia_pdf import (  # noqa: E402
    PERMITIDOS,
    extraer_guia,
    reparto_por_seccion,
    rotulos_ausentes,
)
from tfg_uja.invariantes import exigir  # noqa: E402


def _pdf_de(carpeta: Path, guia: dict) -> Path | None:
    """Ruta del PDF guardado para una guía, o ``None`` si no se puede saber.

    El nombre del fichero es el código de la asignatura, así que una guía sin
    código no tiene PDF identificable. Antes se le daba el nombre de reserva
    ``sin_codigo.pdf``, y con eso **todas** las guías sin código habrían
    apuntado al mismo fichero: cada una se habría auditado contra el PDF de
    otra, y las que no coincidieran habrían salido como discrepancias sin
    que el motivo real apareciera por ningún lado. Hoy las 288 guías del
    corpus traen código y ninguna entra por aquí; el caso se declara
    inauditable en vez de resolverse con un nombre inventado.

    Args:
        carpeta: Carpeta donde el rastreo guarda los PDF.
        guia: Item ``guia`` del dataset.

    Returns:
        Ruta del PDF, o ``None`` si la guía no declara código.
    """
    codigo = guia.get("codigo")
    return carpeta / f"{codigo}.pdf" if codigo else None


def _exigir_codigos_unicos(en_pdf: list[dict]) -> None:
    """Falla si dos guías comparten código.

    El nombre del PDF es el código, así que dos guías con el mismo código se
    auditarían contra el mismo fichero y una de las dos daría discrepancia
    sin motivo visible. Hoy los 288 códigos son distintos; se comprueba para
    que la identidad del fichero siga siendo una identidad.

    Args:
        en_pdf: Items ``guia`` que declaran formato PDF.
    """
    veces = Counter(g.get("codigo") for g in en_pdf)
    repetidos = [codigo for codigo, n in veces.items() if n > 1]
    exigir(
        not repetidos,
        lambda: (
            f"{len(repetidos)} código(s) de guía repetidos (p. ej. "
            f"{repetidos[0]!r}). El PDF se localiza por el código, así que "
            f"esas guías se auditarían contra el mismo fichero."
        ),
    )


def _localizar_pdfs(
    en_pdf: list[dict], carpeta: Path
) -> tuple[list[tuple[dict, Path]], list[str], list[str]]:
    """Empareja cada guía con su PDF y aparta las que no se pueden auditar.

    Args:
        en_pdf: Items ``guia`` que declaran formato PDF.
        carpeta: Carpeta donde el rastreo guarda los PDF.

    Returns:
        Las parejas ``(guia, pdf)`` auditables, los códigos cuyo PDF no está
        en la carpeta y los nombres de las guías que no declaran código.
    """
    auditables: list[tuple[dict, Path]] = []
    ausentes: list[str] = []
    sin_codigo: list[str] = []
    for guia in en_pdf:
        pdf = _pdf_de(carpeta, guia)
        if pdf is None:
            sin_codigo.append(str(guia.get("nombre")))
            continue
        if not pdf.is_file():
            ausentes.append(str(guia.get("codigo")))
            continue
        auditables.append((guia, pdf))
    return auditables, ausentes, sin_codigo


def _rotulos_perdidos(auditables: list[tuple[dict, Path]]) -> dict[str, list[str]]:
    """Rótulos de la plantilla que ya no aparecen en cada PDF.

    Es la comprobación que sostiene todo lo demás. Va por AUSENCIA y no por
    presencia de rótulos desconocidos: buscar desconocidos da 68 avisos sobre
    las 293 guías reales, todos legítimos (contenido en negrita dentro de las
    secciones y la segunda línea del nombre en la cabecera).

    Args:
        auditables: Parejas ``(guia, pdf)`` que sí se pueden comparar.

    Returns:
        Para cada código de guía afectado, los rótulos que le faltan.
    """
    faltantes: dict[str, list[str]] = {}
    for guia, pdf in auditables:
        perdidos = rotulos_ausentes(pdf.read_bytes())
        if perdidos:
            faltantes[str(guia.get("codigo"))] = perdidos
    return faltantes


def _guias_que_discrepan(auditables: list[tuple[dict, Path]]) -> list[str]:
    """Guías cuyo PDF ya no reproduce lo que hay guardado en el dataset.

    Lo que sale hoy del PDF debe ser lo que hay en el dataset: si no
    coincide, uno de los dos está viejo y las cifras no son de fiar.

    Args:
        auditables: Parejas ``(guia, pdf)`` que sí se pueden comparar.

    Returns:
        Códigos de las guías que discrepan.
    """
    discrepancias: list[str] = []
    for guia, pdf in auditables:
        extraido = extraer_guia(pdf.read_bytes()) or {"resumen": "", "temario": ""}
        guardado = (guia.get("resumen", ""), guia.get("temario", ""))
        if (extraido["resumen"], extraido["temario"]) != guardado:
            discrepancias.append(str(guia.get("codigo")))
    return discrepancias


def _reparto_de_texto(
    auditables: list[tuple[dict, Path]],
) -> tuple[int, int, Counter[str]]:
    """Cuánto texto trae la plantilla y cuánto se conserva, por sección.

    Args:
        auditables: Parejas ``(guia, pdf)`` que sí se pueden comparar.

    Returns:
        Caracteres totales de las secciones, caracteres conservados y cuántos
        se descartan bajo cada rótulo.
    """
    total_pdf = 0
    total_conservado = 0
    descartado_por_rotulo: Counter[str] = Counter()
    for _, pdf in auditables:
        for rotulo, largo in reparto_por_seccion(pdf.read_bytes()).items():
            total_pdf += largo
            if rotulo in PERMITIDOS:
                total_conservado += largo
            else:
                descartado_por_rotulo[rotulo] += largo
    return total_pdf, total_conservado, descartado_por_rotulo


def _exigir_plantilla_conocida(faltantes: dict[str, list[str]]) -> None:
    """Falla si a alguna guía le falta un rótulo de la plantilla.

    Args:
        faltantes: Rótulos perdidos por código de guía.
    """
    exigir(
        not faltantes,
        lambda: (
            f"{len(faltantes)} guía(s) a las que les falta algún rótulo de la "
            f"plantilla, p. ej. {list(faltantes)[0]}: "
            f"{faltantes[list(faltantes)[0]]}. La plantilla de la UJA ha "
            f"cambiado: la sección que ese rótulo delimitaba deja de terminar "
            f"donde debe, así que o se pierde su contenido o la anterior se "
            f"traga la siguiente."
        ),
    )


def _exigir_extraccion_fiel(discrepancias: list[str]) -> None:
    """Falla si re-extraer un PDF no reproduce lo guardado en el dataset.

    Args:
        discrepancias: Códigos de las guías que discrepan.
    """
    exigir(
        not discrepancias,
        lambda: (
            f"{len(discrepancias)} guía(s) donde re-extraer el PDF no "
            f"reproduce lo que hay en el dataset (p. ej. {discrepancias[0]}). "
            f"El dataset y el código no están sincronizados: regenera el "
            f"dataset."
        ),
    )


def _pdf_huerfanos(
    dataset: list[dict], guias: list[dict], en_pdf: list[dict], carpeta: Path
) -> tuple[set[str], set[str]]:
    """Separa los PDF sueltos de la carpeta en explicados e inesperados.

    Un PDF descargado que no ha llegado a ser una guía tiene una única
    explicación legítima, y es la anomalía DQA-0004: la asignatura enlaza su
    guía, el rastreo se la baja, y sus secciones de contenido están vacías en
    el origen, así que no se emite ningún item `guia`. Sobre el corpus del
    05/08/2026 los cinco huérfanos son exactamente esas cinco asignaturas.

    Uno que NO encaje ahí es otra cosa: o el PDF se descargó y su extracción
    se perdió por el camino, o es un resto de un rastreo anterior que ya no
    corresponde a este dataset. En ambos casos la carpeta y el dataset dicen
    cosas distintas, y esta auditoría compara justamente esas dos.

    Args:
        dataset: Items del dataset completo.
        guias: Items ``guia`` del dataset.
        en_pdf: Items ``guia`` que declaran formato PDF.
        carpeta: Carpeta donde el rastreo guarda los PDF.

    Returns:
        Los códigos huérfanos que la anomalía DQA-0004 explica y los que no.
    """
    asignaturas = [d for d in dataset if d["tipo"] == "asignatura"]
    claves_guia = {(g["grado"], g.get("codigo") or g["nombre"]) for g in guias}
    vacias_en_origen = {
        str(a["codigo"])
        for a in asignaturas
        if a["tiene_guia"]
        and (a["grado"], a["codigo"] or a["nombre"]) not in claves_guia
    }
    huerfanos = {p.stem for p in carpeta.glob("*.pdf")} - {
        str(g.get("codigo")) for g in en_pdf
    }
    return huerfanos & vacias_en_origen, huerfanos - vacias_en_origen


def _informar_descartes(
    total_pdf: int, total_conservado: int, descartado_por_rotulo: Counter[str]
) -> None:
    """Muestra qué se descarta de cada PDF, con nombre y apellidos.

    Args:
        total_pdf: Caracteres totales de las secciones de la plantilla.
        total_conservado: Caracteres que llegan a la colección.
        descartado_por_rotulo: Caracteres descartados bajo cada rótulo.
    """
    if total_pdf:
        print(
            f"Texto de secciones: {total_pdf} caracteres, de los que se "
            f"conservan {total_conservado} ({100 * total_conservado // total_pdf} %)."
        )
    print("Descartado a propósito, por sección:")
    for rotulo, largo in descartado_por_rotulo.most_common():
        print(f"  {largo:9} {rotulo}")


def main(argv: list[str] | None = None) -> int:
    """Audita la extracción de todas las guías en PDF del dataset.

    Args:
        argv: Ruta del dataset y carpeta de los PDF; por defecto
            ``data/grados.json`` y ``data/guias_pdf``.

    Returns:
        Código de salida: 0 solo si se ha auditado **toda** la colección y la
        extracción es fiel; 1 si algo ha fallado y también si la auditoría no
        ha podido hacerse o ha quedado incompleta. Una auditoría que no se
        ha hecho no es una auditoría superada, y confundir las dos cosas
        convierte este guion en el quinto verificador del proyecto que dice
        «OK» sin haber verificado nada.
    """
    # La consola de Windows fuerza cp1252 y los rótulos de la plantilla llevan
    # tildes y comillas angulares: sin esto la salida sale ilegible.
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    argumentos = argv if argv is not None else sys.argv[1:]
    datos_dir = Path(__file__).resolve().parent.parent.parent / "data"
    ruta = Path(argumentos[0]) if len(argumentos) > 0 else datos_dir / "grados.json"
    carpeta = Path(argumentos[1]) if len(argumentos) > 1 else datos_dir / "guias_pdf"

    dataset = json.loads(ruta.read_text(encoding="utf-8"))
    guias = [d for d in dataset if d["tipo"] == "guia"]
    en_pdf = [g for g in guias if g.get("formato") == "pdf"]
    sin_formato = [g for g in guias if not g.get("formato")]

    reparto = Counter(g.get("formato") or "sin declarar" for g in guias)
    print(f"Guías: {len(guias)}  {dict(reparto)}")

    # Motivos por los que una parte de la colección se queda sin auditar. La
    # lista decide el veredicto final: mientras tenga algo, este guion no
    # puede decir que la extracción es fiel, porque de una parte no lo sabe.
    sin_auditar: list[str] = []

    if sin_formato:
        sin_auditar.append(
            f"{len(sin_formato)} guías sin el campo `formato` (dataset "
            "anterior a IT-95): no entran en la auditoría. Regeneralo."
        )
    if not carpeta.is_dir():
        print(
            f"AUDITORÍA IMPOSIBLE: no existe {carpeta}. El rastreo guarda ahí "
            "los PDF desde IT-95; sin ellos no hay contra qué comparar. "
            "Regenera el dataset."
        )
        return 1

    _exigir_codigos_unicos(en_pdf)
    auditables, ausentes, sin_codigo = _localizar_pdfs(en_pdf, carpeta)

    faltantes = _rotulos_perdidos(auditables)
    discrepancias = _guias_que_discrepan(auditables)
    total_pdf, total_conservado, descartado_por_rotulo = _reparto_de_texto(auditables)

    _exigir_plantilla_conocida(faltantes)
    _exigir_extraccion_fiel(discrepancias)

    if ausentes:
        sin_auditar.append(
            f"faltan {len(ausentes)} PDF de {len(en_pdf)} en {carpeta} "
            f"(p. ej. {ausentes[0]}): esas guías no se han podido auditar."
        )
    if sin_codigo:
        sin_auditar.append(
            f"{len(sin_codigo)} guías sin código (p. ej. {sin_codigo[0]!r}): "
            f"su PDF no se puede localizar, porque el fichero se nombra por "
            f"el código."
        )
    if not auditables:
        sin_auditar.append(
            f"no se ha auditado ni una sola guía de las {len(guias)} del "
            f"dataset: no hay ninguna evidencia detrás de este informe."
        )

    # --- Qué se descarta, con nombre y apellidos ---
    print(
        f"\nAuditadas {len(auditables)} guías en PDF de las {len(guias)} del dataset."
    )

    explicados, inesperados = _pdf_huerfanos(dataset, guias, en_pdf, carpeta)
    if explicados:
        print(
            f"  {len(explicados)} PDF sin guía en el dataset, y con motivo: "
            f"son asignaturas que enlazan su guía y la publican sin contenido "
            f"(DQA-0004). El PDF existe; lo que no trae es qué contar."
        )
    if inesperados:
        sin_auditar.append(
            f"{len(inesperados)} PDF en la carpeta que este dataset no "
            f"referencia y que tampoco son guías vacías (p. ej. "
            f"{sorted(inesperados)[0]}): o su extracción se ha perdido, o son "
            f"restos de otro rastreo. La carpeta y el dataset no se "
            f"corresponden."
        )
    _informar_descartes(total_pdf, total_conservado, descartado_por_rotulo)

    if sin_auditar:
        print("\nAUDITORÍA INCOMPLETA. Lo comprobado sale bien, pero:")
        for motivo in sin_auditar:
            print(f"  - {motivo}")
        print(
            "  No se puede concluir que la extracción sea fiel: de esa parte "
            "no se sabe nada."
        )
        return 1

    print("\nGuías PDF OK: la plantilla es la conocida y la extracción es fiel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Verificación del dataset extraído por el spider (IT-10).

Comprueba los invariantes de ``data/grados.json`` tras cada regeneración::

    scrapy runspider src/tfg_uja/grados_spider.py -O data/grados.json
    py scripts/check_dataset.py

Acepta una ruta alternativa como argumento.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: Campos de texto libre que se vuelcan a la colección y, por tanto, jamás
#: deben contener binario. El bug que motivó esta comprobación (IT-67): una
#: guía servida como PDF pasaba por el mecanismo de respaldo y guardaba el
#: binario del PDF en ``cuerpo_general``, y el verificador respondía «OK».
_CAMPOS_TEXTO = ("resumen", "temario", "cuerpo_general", "texto")


def _parece_binario(texto: str) -> bool:
    """Indica si un texto parece binario y no lenguaje natural.

    Detecta dos señales: la firma ``%PDF`` de un PDF crudo y una densidad
    alta de caracteres de control (los que no aparecen en texto legible,
    salvo los saltos y tabuladores habituales).

    Args:
        texto: Contenido de un campo de texto del dataset.

    Returns:
        ``True`` si el texto parece binario.
    """
    if "%PDF" in texto:
        return True
    if not texto:
        return False
    control = sum(1 for c in texto if ord(c) < 32 and c not in "\n\r\t")
    return control / len(texto) > 0.02


def grados_sin_asignaturas(datos: list[dict]) -> list[str]:
    """Titulaciones que tienen página de asignaturas pero no aportan ninguna.

    Es la señal de que el rastreador no ha sabido leer sus tablas. Cuando
    ``parse_asignaturas`` no reconoce la estructura de una tabla la descarta
    con un ``logger.warning``, y ese aviso se pierde entre los cientos de
    líneas de un rastreo completo: lo único que se mira al terminar es el
    veredicto del verificador, que hasta ahora decía «OK» igualmente. Así
    pasó inadvertido que las dos titulaciones de Geomática cambiaran el
    formato de sus tablas (IT-76).

    Los dobles grados quedan fuera por construcción: no tienen página propia
    de asignaturas (``url_asignaturas`` a ``None``), porque son la unión de
    sus dos grados base, que sí se rastrean por separado.

    Aviso sobre su alcance: esto detecta la pérdida TOTAL de una titulación,
    no la parcial. Un grado que conserve sus tablas troncales y pierda solo
    las de mención sigue aportando asignaturas y no se detecta aquí; de eso
    responden las pruebas de regresión del spider con fixtures reales.

    Args:
        datos: Items del dataset tal como los emite el spider.

    Returns:
        Nombres de las titulaciones afectadas, vacío si no hay ninguna.
    """
    con_asignaturas = {d["grado"] for d in datos if d["tipo"] == "asignatura"}
    return [
        d["nombre"]
        for d in datos
        if d["tipo"] == "grado"
        and d.get("url_asignaturas")
        and d["nombre"] not in con_asignaturas
    ]


def main(argv: list[str] | None = None) -> int:
    """Ejecuta las comprobaciones del dataset del spider.

    Args:
        argv: Ruta del dataset; por defecto ``data/grados.json`` en la raíz
            del repositorio (el script vive en ``scripts/``).

    Returns:
        Código de salida (0 si todos los invariantes se cumplen).
    """
    argumentos = argv if argv is not None else sys.argv[1:]
    por_defecto = Path(__file__).resolve().parent.parent / "data" / "grados.json"
    ruta = Path(argumentos[0]) if argumentos else por_defecto

    datos = json.loads(ruta.read_text(encoding="utf-8"))
    asignaturas = [d for d in datos if d["tipo"] == "asignatura"]
    grados = [d for d in datos if d["tipo"] == "grado"]
    guias = [d for d in datos if d["tipo"] == "guia"]
    salidas = [d for d in datos if d["tipo"] == "salidas"]

    # Procedencia (IT-90): de cuándo y de qué curso es lo que se verifica.
    procedencia = next((d for d in datos if d["tipo"] == "procedencia"), {})
    cursos = sorted({g["curso"] for g in guias if g.get("curso")})
    if procedencia:
        print(
            f"Procedencia: extraccion {procedencia.get('fecha_extraccion')} | "
            f"curso(s) {', '.join(cursos) or 'sin determinar'}"
        )
    else:
        print(
            "AVISO: este grados.json no lleva procedencia (anterior a IT-90). "
            "Regeneralo para saber de cuando y de que curso es."
        )
    sin_curso = [g for g in guias if not g.get("curso")]
    if procedencia and sin_curso:
        print(
            f"  AVISO: {len(sin_curso)} de {len(guias)} guias sin curso en su "
            "URL; el formato de la fuente puede haber cambiado."
        )

    # Va antes que las cifras esperadas a propósito: si una titulación se ha
    # quedado sin asignaturas, el recuento total también falla, pero un
    # «asignaturas: 331 (esperado 361)» solo dice que falta algo. Comprobar
    # esto primero convierte ese número en el nombre de lo que hay que mirar.
    vacios = grados_sin_asignaturas(datos)
    assert not vacios, (
        f"{len(vacios)} titulación(es) con página de asignaturas pero sin "
        f"ninguna asignatura extraída: {vacios}. El rastreador no ha sabido "
        f"leer sus tablas; revisa los avisos del rastreo (IT-78)."
    )

    assert len(asignaturas) == 361, f"asignaturas: {len(asignaturas)} (esperado 361)"
    assert len(grados) == 13, f"grados: {len(grados)} (esperado 13)"
    assert len(guias) == 296, f"guias: {len(guias)} (esperado 296)"
    # Los dobles grados no emiten salidas (decisión de IT-07): 8, no 9.
    assert len(salidas) == 8, f"salidas: {len(salidas)} (esperado 8)"
    assert all("ofertada" in a for a in asignaturas), "falta el campo ofertada"
    no_ofertadas = sum(1 for a in asignaturas if not a["ofertada"])
    assert no_ofertadas == 9, f"no ofertadas: {no_ofertadas} (esperado 9)"
    assert not [a for a in asignaturas if "(" in a["nombre"]], "nombres sucios"
    assert not [
        a for a in asignaturas if any("/" in m for m in a["menciones"])
    ], "menciones con barra sin separar"
    sin_ects = [a for a in asignaturas if not a["ects"]]
    assert (
        len(sin_ects) == 1
    ), f"sin ECTS: {len(sin_ects)} (esperado 1, fiel a la fuente)"

    binarias = [
        d
        for d in datos
        for campo in _CAMPOS_TEXTO
        if isinstance(d.get(campo), str) and _parece_binario(d[campo])
    ]
    assert not binarias, (
        f"{len(binarias)} items con binario en un campo de texto "
        f"(p. ej. código {binarias[0].get('codigo')!r}): una guía servida "
        f"como PDF no se ha extraído bien (IT-67)."
    )

    print(
        f"Dataset OK: {len(asignaturas)} asignaturas, {len(guias)} guías, "
        f"{len(salidas)} salidas, {no_ofertadas} no ofertadas, "
        f"{len(sin_ects)} sin ECTS (fiel a la fuente)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

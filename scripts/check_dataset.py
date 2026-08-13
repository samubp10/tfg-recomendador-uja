"""Verificación del dataset extraído por el spider (IT-10).

Comprueba los invariantes de ``data/grados.json`` tras cada regeneración::

    scrapy runspider src/tfg_uja/grados_spider.py -O data/grados.json
    py scripts/check_dataset.py

Acepta una ruta alternativa como argumento.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

#: `assert` desaparece al ejecutar con `python -O`, y entonces este guion
#: recorrería el dataset entero sin comprobar nada y diría «Dataset OK». La
#: sustituta es común a los cuatro verificadores para que no puedan discrepar.
from tfg_uja.invariantes import exigir

ESPERADO = {
    "asignaturas": 528,
    "grados": 12,
    "guias": 288,
    "salidas": 8,
    "no_ofertadas": 10,
    "sin_ects": 1,
}

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
    procedencia: dict = next((d for d in datos if d["tipo"] == "procedencia"), {})
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

    # De que camino viene cada guia (IT-95). Se informa, no se comprueba: que
    # el reparto cambie no es un error, es la fuente migrando de formato. Lo
    # que no puede pasar es que migre sin que nadie se entere, que es lo que
    # ocurrio entre el 23 y el 28 de julio de 2026: el corpus paso de 62 de
    # 296 guias en PDF a las 288 de 288, y solo se supo mucho despues,
    # deduciendolo de los saltos de linea del texto extraido.
    formatos = Counter(g.get("formato") or "sin declarar" for g in guias)
    print(f"  Formato de las guias: {dict(formatos)}")
    if formatos.get("sin declarar"):
        print(
            "  AVISO: hay guias sin el campo `formato` (dataset anterior a "
            "IT-95). Regeneralo para poder auditar su extraccion."
        )

    # Va antes que las cifras esperadas a propósito: si una titulación se ha
    # quedado sin asignaturas, el recuento total también falla, pero un
    # «asignaturas: 331 (esperado 361)» solo dice que falta algo. Comprobar
    # esto primero convierte ese número en el nombre de lo que hay que mirar.
    vacios = grados_sin_asignaturas(datos)
    exigir(
        not vacios,
        lambda: (
            f"{len(vacios)} titulación(es) con página de asignaturas pero sin "
            f"ninguna asignatura extraída: {vacios}. El rastreador no ha sabido "
            f"leer sus tablas; revisa los avisos del rastreo (IT-78)."
        ),
    )

    # La comprobación de arriba solo ve la pérdida TOTAL de una titulación. La
    # parcial ---perder las tablas de mención y conservar las troncales--- deja
    # el recuento global descuadrado y nada más, y «asignaturas: 508 (esperado
    # 528)» no dice de quién faltan. No se comprueba con un umbral por
    # titulación porque cualquier cifra que se pusiera sería inventada: se
    # imprime el reparto para que la comparación con el rastreo anterior la
    # haga quien sí sabe cuántas asignaturas tiene cada plan.
    por_titulacion = Counter(a["grado"] for a in asignaturas)
    print("  Asignaturas por titulación:")
    for grado in grados:
        propias = por_titulacion.get(grado["nombre"], 0)
        sin_pagina = "" if grado.get("url_asignaturas") else "  (sin página propia)"
        print(f"    {propias:4}  {grado['nombre']}{sin_pagina}")

    for etiqueta, real in (
        ("asignaturas", len(asignaturas)),
        ("grados", len(grados)),
        ("guias", len(guias)),
        ("salidas", len(salidas)),
    ):
        esperado = ESPERADO[etiqueta]
        exigir(
            real == esperado,
            f"{etiqueta}: {real} (esperado {esperado}). Si el cambio es "
            f"legítimo porque se ha vuelto a rastrear, actualiza ESPERADO en "
            f"la cabecera de este script; si no lo es, el rastreo ha perdido "
            f"datos y hay que averiguar por qué antes de tocar nada.",
        )

    exigir(all("ofertada" in a for a in asignaturas), "falta el campo ofertada")
    no_ofertadas = sum(1 for a in asignaturas if not a["ofertada"])
    exigir(
        no_ofertadas == ESPERADO["no_ofertadas"],
        f"no ofertadas: {no_ofertadas} (esperado {ESPERADO['no_ofertadas']})",
    )

    # Un paréntesis en el nombre delata que se ha colado texto que no forma
    # parte de él. Este invariante lleva vigente desde IT-10 y saltó por
    # primera vez el 28/07/2026: la fuente había empezado a incrustar un
    # enlace «( Syllabus )» dentro de la celda del nombre (IT-93).
    #
    # IT-101 añade la única excepción legítima: los planes de los dobles grados
    # anotan entre paréntesis el acrónimo del grado del que procede cada
    # asignatura («GESTIÓN FINANCIERA (GIOI)»). Eso lo escribe la fuente y no es
    # basura arrastrada, así que se admite —y solo eso: cualquier otro
    # paréntesis, y cualquiera en una titulación simple, sigue fallando.
    dobles = {g["nombre"] for g in grados if g.get("es_doble_grado")}
    acronimo_de_grado = re.compile(r"^[^()]+ \([A-Z]{2,8}\)$")
    sucios = [
        a
        for a in asignaturas
        if "(" in a["nombre"]
        and not (a["grado"] in dobles and acronimo_de_grado.match(a["nombre"]))
    ]
    exigir(
        not sucios,
        lambda: (
            f"{len(sucios)} nombres con paréntesis, p. ej. "
            f"{sucios[0]['nombre']!r}. Se ha colado en el nombre algo que no "
            f"le pertenece."
        ),
    )
    # Solo la barra. Se descartó ampliarlo a otros separadores (« y », la coma)
    # porque sobre las 16 menciones reales del corpus daría 14 falsos
    # positivos: «Ingeniería y fabricación mecánica» o «Técnicas para la
    # información y la comunicación» son nombres, no dos menciones pegadas.
    exigir(
        not [a for a in asignaturas if any("/" in m for m in a["menciones"])],
        "menciones con barra sin separar",
    )
    sin_ects = [a for a in asignaturas if not a["ects"]]
    exigir(
        len(sin_ects) == ESPERADO["sin_ects"],
        f"sin ECTS: {len(sin_ects)} (esperado {ESPERADO['sin_ects']}, "
        f"fiel a la fuente)",
    )

    # IT-94: una asignatura que anuncia guía pero cuya guía no aparece en el
    # dataset se pierde del corpus si nadie lo mira. Es un hecho de la fuente y
    # no un error del rastreo, así que se avisa en vez de fallar; el
    # fragmentador ya les da su fragmento informativo.
    #
    # IT-97 corrige la redacción de este aviso. Decía «no se ha podido
    # extraer», que insinúa un fallo propio, y sobre las 293 guías del rastreo
    # del 29/07/2026 los cinco casos son la misma cosa y no es esa: la guía se
    # lee perfectamente y sus secciones de contenido están vacías en el origen.
    claves_guia = {(g["grado"], g.get("codigo") or g["nombre"]) for g in guias}
    sin_extraer = [
        a
        for a in asignaturas
        if a["tiene_guia"]
        and (a["grado"], a["codigo"] or a["nombre"]) not in claves_guia
    ]
    if sin_extraer:
        print(
            f"  AVISO: {len(sin_extraer)} asignaturas enlazan una guía que no "
            f"aporta ni resumen ni temario (p. ej. "
            f"{sin_extraer[0]['nombre']!r}); entran al corpus solo con sus "
            f"datos básicos. `check_guias_pdf.py` dice de cada una por qué."
        )

    binarias = [
        d
        for d in datos
        for campo in _CAMPOS_TEXTO
        if isinstance(d.get(campo), str) and _parece_binario(d[campo])
    ]
    exigir(
        not binarias,
        lambda: (
            f"{len(binarias)} items con binario en un campo de texto "
            f"(p. ej. código {binarias[0].get('codigo')!r}): una guía servida "
            f"como PDF no se ha extraído bien (IT-67)."
        ),
    )

    print(
        f"Dataset OK: {len(asignaturas)} asignaturas, {len(guias)} guías, "
        f"{len(salidas)} salidas, {no_ofertadas} no ofertadas, "
        f"{len(sin_ects)} sin ECTS (fiel a la fuente)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Verificación del dataset de chunks (IT-10).

Recorre ``data/chunks.json`` (salida de ``tfg_uja.chunker``) y comprueba los
invariantes del troceo, además de reportar las estadísticas que permiten
detectar regresiones cada vez que se regenera el dataset. Debe ejecutarse
tras cada regeneración::

    py -m tfg_uja.chunker data/grados.json data/chunks.json
    py scripts/check_chunks.py

Acepta rutas alternativas como argumentos::

    py scripts/check_chunks.py otra/ruta/chunks.json otra/ruta/grados.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

#: Deben coincidir con ``tfg_uja.chunker``; se duplican aquí para que el
#: script no dependa del paquete instalado (se ejecuta también en CI).
TAMANO_MAXIMO = 1500
TAMANO_MINIMO = 200


def _clave_item(item: dict) -> tuple:
    """Identifica la unidad de un item del dataset (grado y código singulares).

    El código no basta como identificador: las asignaturas de las
    titulaciones en implantación aún no tienen código publicado (cadena
    vacía) y agrupar solo por código las colapsaría. Cuando falta el código
    se usa el nombre.

    Args:
        item: Item del dataset (``asignatura``, ``guia`` o ``salidas``).

    Returns:
        Tupla ``(grado, codigo_o_nombre)`` que identifica la unidad.
    """
    return (item["grado"], item.get("codigo") or item.get("nombre"))


def _claves_chunk(chunk: dict) -> set[tuple]:
    """Expande un chunk a las unidades (grado, código) que representa.

    Tras la deduplicación, un chunk de guía puede pertenecer a varias
    titulaciones: su clave se expande a un par por cada titulación, para
    poder cotejarlo con los items individuales del dataset.

    Args:
        chunk: Chunk con ``grados`` y ``codigos`` como listas paralelas.

    Returns:
        Conjunto de pares ``(grado, codigo_o_nombre)``.
    """
    return {
        (grado, codigo or chunk["nombre"])
        for grado, codigo in zip(chunk["grados"], chunk["codigos"])
    }


def _imprimir_procedencia(procedencia: dict, total_guias: int) -> None:
    """Muestra de cuándo y de qué curso es el corpus que se está verificando.

    Se imprime lo primero, antes que cualquier estadística: leer «892
    fragmentos» sin saber a qué extracción corresponden fue justamente el
    problema que motivó IT-90.

    Args:
        procedencia: Item ``procedencia`` del ``chunks.json``, o vacío si el
            fichero se generó antes de IT-90.
        total_guias: Guías del dataset, para poder avisar en proporción.
    """
    if not procedencia:
        print(
            "AVISO: este chunks.json no lleva procedencia (anterior a IT-90). "
            "Regeneralo para saber de cuando y de que curso es."
        )
        return
    if not procedencia.get("fecha_extraccion"):
        # El fragmentador arrastra la fecha del dataset, y un grados.json
        # anterior a IT-90 no la trae. No es un fallo del rastreo: es un
        # dataset viejo, y conviene no confundirlo con un cambio de la fuente.
        print(
            "AVISO: el grados.json de origen es anterior a IT-90, asi que no "
            "consta ni la fecha de extraccion ni el curso. Se sabra al "
            "regenerar el dataset (IT-80)."
        )
        return
    cursos = ", ".join(procedencia.get("cursos") or []) or "sin determinar"
    print(
        f"Procedencia: extraccion {procedencia['fecha_extraccion']} | "
        f"troceado {procedencia.get('fecha_troceado')} | curso(s) {cursos}"
    )
    if len(procedencia.get("cursos") or []) > 1:
        print(
            "  NOTA: el corpus mezcla varios cursos. Es esperado mientras la "
            "EPSJ publica las guias nuevas, pero hay que declararlo al "
            "caracterizarlo, no dejarlo implicito."
        )
    sin_curso = procedencia.get("guias_sin_curso") or 0
    if sin_curso:
        print(
            f"  AVISO: {sin_curso} de {total_guias} guias sin curso en su URL; "
            "el formato de la fuente puede haber cambiado."
        )


def main(argv: list[str] | None = None) -> int:
    """Ejecuta las comprobaciones y reporta las estadísticas del troceo.

    Args:
        argv: Rutas del fichero de chunks y del dataset; por defecto,
            ``data/chunks.json`` y ``data/grados.json``.

    Returns:
        Código de salida (0 si todos los invariantes se cumplen).
    """
    argumentos = argv if argv is not None else sys.argv[1:]
    datos = Path(__file__).resolve().parent.parent / "data"
    ruta_chunks = Path(argumentos[0]) if len(argumentos) > 0 else datos / "chunks.json"
    ruta_dataset = Path(argumentos[1]) if len(argumentos) > 1 else datos / "grados.json"

    items = json.loads(ruta_chunks.read_text(encoding="utf-8"))
    # El item de procedencia (IT-90) encabeza el fichero pero no es contenido:
    # se separa por tipo, nunca por posición.
    chunks = [i for i in items if i.get("tipo") == "chunk"]
    procedencia = next((i for i in items if i.get("tipo") == "procedencia"), {})
    dataset = json.loads(ruta_dataset.read_text(encoding="utf-8"))
    asignaturas = [d for d in dataset if d["tipo"] == "asignatura"]
    guias = [d for d in dataset if d["tipo"] == "guia"]
    salidas = [d for d in dataset if d["tipo"] == "salidas"]

    _imprimir_procedencia(procedencia, len(guias))

    # --- Invariantes de forma ---
    assert chunks, "no hay chunks"
    assert all(c["texto"].strip() for c in chunks), "hay chunks vacíos"
    assert all(
        len(c["texto"]) <= TAMANO_MAXIMO for c in chunks
    ), "hay chunks por encima del máximo (encabezado incluido)"
    assert all(
        isinstance(c["grados"], list)
        and isinstance(c["codigos"], list)
        and len(c["grados"]) == len(c["codigos"])
        and c["grados"]
        for c in chunks
    ), "grados/codigos deben ser listas paralelas no vacías"

    # --- El encabezado de cada chunk es el de SU unidad (IT-91) ---
    # El encabezado va dentro de `texto`, que es el único campo que se
    # vectoriza: si nombra a otra asignatura, el índice afirma algo falso
    # aunque los metadatos del chunk sean correctos. Comprobarlo aquí es lo
    # que faltaba para que el defecto de IT-91 no pudiera pasar inadvertido:
    # el descuadre de cobertura de más abajo compara claves, no encabezados,
    # y por eso daba «OK» con los encabezados cruzados.
    descuadres = [
        c
        for c in chunks
        if c["origen"] in ("guia", "asignatura_sin_guia")
        and not c["texto"].startswith(f"«{c['nombre']}»")
    ]
    # IT-100: los fragmentos de plan de estudios llevan su nombre sin comillas
    # angulares, porque no nombran una asignatura sino un listado. Se comprueban
    # igual: dejarlos fuera habría metido 16 fragmentos que ningún verificador
    # mira, que es exactamente el patrón de fallo que este proyecto arrastra.
    descuadres += [
        c
        for c in chunks
        if c["origen"] == "plan_de_estudios" and not c["texto"].startswith(c["nombre"])
    ]
    assert not descuadres, (
        f"{len(descuadres)} chunks con el encabezado de otra unidad "
        f"(p. ej. {descuadres[0]['nombre']!r} encabezado como "
        f"{descuadres[0]['texto'].split(chr(10))[0][:60]!r})"
    )

    # IT-100: el listado debe decir cuántas asignaturas contiene, y esa cifra
    # tiene que cuadrar con el dataset. Es la única forma de detectar que el
    # listado se ha quedado corto: un fragmento con 40 asignaturas de las 50
    # que tiene la titulación se lee igual de bien y es igual de falso.
    planes = [c for c in chunks if c["origen"] == "plan_de_estudios"]
    for c in planes:
        if c["chunk_index"] != 0:
            continue
        declarado = re.search(r"En total son (\d+):", c["texto"])
        assert declarado, f"el plan {c['nombre']!r} no declara cuántas son"
        cuerpo = "\n".join(
            x["texto"].split("\n", 1)[1]
            for x in sorted(
                (p for p in planes if p["nombre"] == c["nombre"]),
                key=lambda p: p["chunk_index"],
            )
        )
        listadas = len([t for t in cuerpo.split("\n") if t.strip()])
        assert listadas == int(declarado.group(1)), (
            f"{c['nombre']!r} dice tener {declarado.group(1)} asignaturas "
            f"pero el listado trae {listadas}"
        )

    # --- Numeración consistente dentro de cada unidad ---
    por_unidad: dict[tuple, list] = {}
    for c in chunks:
        clave = (c["nombre"], tuple(c["grados"]), c["origen"])
        por_unidad.setdefault(clave, []).append(c)
    for unidad, lista in por_unidad.items():
        lista.sort(key=lambda c: c["chunk_index"])
        indices = [c["chunk_index"] for c in lista]
        assert indices == list(range(len(lista))), f"índices rotos en {unidad}"
        assert all(
            c["total_chunks"] == len(lista) for c in lista
        ), f"total_chunks inconsistente en {unidad}"
        if len(lista) > 1:
            assert all(
                len(c["texto"]) >= TAMANO_MINIMO for c in lista
            ), f"chunk bajo el mínimo tras la fusión en {unidad}"

    # --- Cobertura: cada item del dataset queda representado ---
    # Se expanden los chunks a pares (grado, código) por la deduplicación.
    con_guia = {_clave_item(g) for g in guias}
    unidades_guia = set()
    for c in chunks:
        if c["origen"] == "guia":
            unidades_guia |= _claves_chunk(c)
    assert con_guia == unidades_guia, (
        "descuadre guía<->chunk: "
        f"faltan {len(con_guia - unidades_guia)}, "
        f"sobran {len(unidades_guia - con_guia)}"
    )

    informativos = set()
    for c in chunks:
        if c["origen"] == "asignatura_sin_guia":
            informativos |= _claves_chunk(c)

    # IT-94: toda asignatura del dataset tiene que quedar representada en algún
    # fragmento, sea por su guía o por su chunk informativo. Antes se
    # comprobaba solo que las de `tiene_guia=False` tuvieran informativo y que
    # las guías tuvieran sus fragmentos, y entre ambas comprobaciones quedaba
    # un hueco: una asignatura con `tiene_guia=True` cuya guía no llegó a
    # emitirse (PDF ilegible, IT-67) no entraba en ninguna de las dos y
    # desaparecía del corpus mientras el verificador respondía «OK».
    todas = {_clave_item(a) for a in asignaturas}
    representadas = unidades_guia | informativos
    perdidas = todas - representadas
    assert not perdidas, (
        f"{len(perdidas)} asignaturas del dataset no aparecen en ningún "
        f"fragmento (p. ej. {sorted(perdidas)[0]}): ni con guía ni como "
        f"asignatura sin guía. Se han perdido del corpus (IT-94)."
    )

    grados_salidas = {s["grado"] for s in salidas}
    grados_chunk_salidas = {
        g for c in chunks if c["origen"] == "salidas" for g in c["grados"]
    }
    assert grados_salidas == grados_chunk_salidas, "salidas sin trocear"

    # --- Estadísticas ---
    origenes = Counter(c["origen"] for c in chunks)
    compartidas = sum(
        1 for c in chunks if len(c["grados"]) > 1 and c["chunk_index"] == 0
    )
    print(f"Chunks totales: {len(chunks)}  {dict(origenes)}")
    print(
        f"Unidades: {len(por_unidad)} (guías {len(con_guia)}, "
        f"sin guía {len(informativos)}, salidas {len(grados_salidas)})"
    )
    # IT-94: las que la fuente publica pero que no aportan contenido se
    # cuentan aparte, porque no son lo mismo que una guía inexistente y su
    # número mide directamente cuánto contenido se está perdiendo.
    #
    # IT-97 corrige la redacción, que decía «no se ha podido extraer». Eso
    # apunta a un fallo propio, y sobre el rastreo del 29/07/2026 los cinco
    # casos son la contraria: el PDF se lee entero y sus secciones de
    # contenido están vacías en el origen (DQA-0004). Tercer y último sitio
    # donde vivía la frase; los otros dos son check_dataset.py y chunker.py.
    no_extraidas = sum(1 for a in asignaturas if a["tiene_guia"]) - len(guias)
    if no_extraidas:
        print(
            f"  AVISO: {no_extraidas} asignaturas enlazan una guía que no "
            "aporta ni resumen ni temario; aparecen solo con sus datos "
            "básicos. `check_guias_pdf.py` dice de cada una por qué."
        )
    print(f"Unidades de guía compartidas entre titulaciones: {compartidas}")

    tamanos = sorted(len(c["texto"]) for c in chunks)
    n = len(tamanos)
    print(
        f"Tamaño (chars): min={tamanos[0]} mediana={tamanos[n // 2]} "
        f"p90={tamanos[int(n * 0.9)]} max={tamanos[-1]}"
    )

    print("Chunks OK: invariantes verificados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

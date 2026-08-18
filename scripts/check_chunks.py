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

#: Se importan del fragmentador en vez de copiarse. Antes estaban duplicados
#: aquí «para que el script no dependa del paquete instalado, que se ejecuta
#: también en CI», y esa razón ya no existe: el flujo de trabajo declara que
#: este verificador NO corre en CI, porque ``data/`` no está versionado y en
#: un checkout limpio los ficheros que verifica no existen.
#:
#: Lo que quedaba era el peor modo de fallo posible. Al bajar el máximo de
#: 1500 a 900 (IT-16), una copia sin actualizar habría seguido comprobando
#: ``len(texto) <= 1500`` sobre un corpus cuyo máximo real es 900: pasa en
#: verde y deja de verificar la restricción que el sistema declara. Sería el
#: cuarto caso de esta serie en el proyecto, después de los encabezados
#: cruzados de IT-91, y el patrón siempre es el mismo: el verificador mide
#: algo distinto de lo que cree medir, y nadie se entera porque dice «OK».
from tfg_uja.chunker import TAMANO_MAXIMO, TAMANO_MINIMO

#: Por el mismo motivo que los umbrales de arriba: los cuatro verificadores
#: comprueban invariantes y los cuatro tienen que hacerlo igual. Una copia por
#: guion es una copia que puede quedarse atrás sin que nadie lo note.
from tfg_uja.invariantes import InvarianteRoto, exigir  # noqa: F401

#: Orígenes cuyo encabezado nombra una asignatura y va entre comillas
#: angulares.
_ORIGENES_DE_ASIGNATURA = ("guia", "asignatura_sin_guia")

#: Orígenes cuyo encabezado es el nombre a secas, porque no nombran una
#: asignatura sino un listado o una ficha (IT-100, IT-107).
_ORIGENES_DERIVADOS = ("plan_de_estudios", "catalogo", "ficha_titulacion", "mencion")


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


def _claves_de_origen(chunks: list[dict], origen: str) -> set[tuple]:
    """Une las claves de unidad de todos los chunks de un origen dado.

    Args:
        chunks: Chunks del corpus completo.
        origen: Valor del campo ``origen`` que se quiere recoger.

    Returns:
        Conjunto de pares ``(grado, codigo_o_nombre)`` representados por ese
        origen.
    """
    claves: set[tuple] = set()
    for chunk in chunks:
        if chunk["origen"] == origen:
            claves |= _claves_chunk(chunk)
    return claves


def cortos_evitables(lista: list[dict]) -> list[int]:
    """Longitudes de los chunks cortos que sí se habrían podido fusionar.

    El mínimo no es una restricción dura, a diferencia del máximo: el
    fragmentador conserva un fragmento corto cuando unirlo a su vecino haría
    que el par superase el máximo y el texto no ofrece ninguna frontera por la
    que repartirlo mejor. Su propio ``_fusionar_pequenos`` lo documenta:
    «alguno puede quedar por debajo del mínimo si no había manera de
    evitarlo».

    Este verificador exigía ``len(texto) >= TAMANO_MINIMO`` sin más, es decir,
    trataba una preferencia como si fuera un invariante. Con el máximo en
    1.500 el caso no llegaba a darse sobre el corpus real y la comprobación
    pasaba; al bajarlo a 900 (IT-16) aparecieron seis colas de entre 171 y 196
    caracteres, todas legítimas, y el verificador las daba por defecto.

    Comprobar en su lugar «que no sea demasiado corto» con algún margen sería
    peor que no comprobar nada: en este proyecto un margen de 250 caracteres
    ya ocultó una vez que 40 fragmentos superaban el máximo. Así que no se
    afloja el umbral, se cambia por el invariante exacto: un fragmento corto
    solo es admisible si unirlo a su vecino desbordaría el máximo. Se
    reconstruye la unión tal como la haría el fragmentador ---mismo
    encabezado, mismo separador, mismo presupuesto descontado--- en lugar de
    estimarla.

    Args:
        lista: Chunks de una misma unidad semántica, ordenados por
            ``chunk_index``.

    Returns:
        Longitudes de los chunks cortos que se podían haber fusionado, vacío
        si no hay ninguno. Una unidad de un solo chunk nunca aporta: no tiene
        con quién fusionarse.
    """
    if len(lista) < 2:
        return []
    evitables = []
    for i, chunk in enumerate(lista):
        texto = chunk["texto"]
        if len(texto) >= TAMANO_MINIMO:
            continue
        # El encabezado se repite en cada chunk de la unidad y ocupa la
        # primera línea; el cuerpo es lo que queda. `_fusionar_pequenos`
        # trabaja sobre cuerpos, con el máximo ya descontado del encabezado.
        hueco = len(texto.split("\n", 1)[0]) + 1
        vecino = lista[i - 1] if i > 0 else lista[i + 1]
        primero, segundo = (vecino, chunk) if i > 0 else (chunk, vecino)
        combinado = f'{primero["texto"][hueco:]}\n{segundo["texto"][hueco:]}'
        if len(combinado) <= TAMANO_MAXIMO - hueco:
            evitables.append(len(texto))
    return evitables


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


def _exigir_forma(chunks: list[dict]) -> None:
    """Comprueba la forma mínima de todo chunk: no vacío, dentro del máximo
    y con ``grados``/``codigos`` como listas paralelas.

    El máximo es la única restricción dura de tamaño; el mínimo es una
    preferencia y se trata aparte, en ``cortos_evitables``.

    Args:
        chunks: Chunks del corpus completo.
    """
    exigir(chunks, "no hay chunks")
    exigir(all(c["texto"].strip() for c in chunks), "hay chunks vacíos")
    exigir(
        all(len(c["texto"]) <= TAMANO_MAXIMO for c in chunks),
        "hay chunks por encima del máximo (encabezado incluido)",
    )
    exigir(
        all(
            isinstance(c["grados"], list)
            and isinstance(c["codigos"], list)
            and len(c["grados"]) == len(c["codigos"])
            and c["grados"]
            for c in chunks
        ),
        "grados/codigos deben ser listas paralelas no vacías",
    )


def _exigir_encabezados(chunks: list[dict]) -> None:
    """El encabezado de cada chunk es el de SU unidad (IT-91).

    El encabezado va dentro de `texto`, que es el único campo que se
    vectoriza: si nombra a otra asignatura, el índice afirma algo falso
    aunque los metadatos del chunk sean correctos. Comprobarlo aquí es lo
    que faltaba para que el defecto de IT-91 no pudiera pasar inadvertido:
    el descuadre de cobertura de más abajo compara claves, no encabezados,
    y por eso daba «OK» con los encabezados cruzados.

    IT-100: los fragmentos de plan de estudios llevan su nombre sin comillas
    angulares, porque no nombran una asignatura sino un listado. Se comprueban
    igual: dejarlos fuera habría metido 16 fragmentos que ningún verificador
    mira, que es exactamente el patrón de fallo que este proyecto arrastra.
    IT-107: los derivados llevan su nombre igual, y por el mismo motivo. Si
    se dejaran fuera, 32 fragmentos de recuento quedarían sin verificar, que
    es cómo empezó siempre este defecto en las tres veces anteriores.

    Args:
        chunks: Chunks del corpus completo.
    """
    descuadres = [
        c
        for c in chunks
        if c["origen"] in _ORIGENES_DE_ASIGNATURA
        and not c["texto"].startswith(f"«{c['nombre']}»")
    ]
    descuadres += [
        c
        for c in chunks
        if c["origen"] in _ORIGENES_DERIVADOS and not c["texto"].startswith(c["nombre"])
    ]
    exigir(
        not descuadres,
        lambda: (
            f"{len(descuadres)} chunks con el encabezado de otra unidad "
            f"(p. ej. {descuadres[0]['nombre']!r} encabezado como "
            f"{descuadres[0]['texto'].split(chr(10))[0][:60]!r})"
        ),
    )


def _exigir_listados_completos(chunks: list[dict]) -> None:
    """La cifra que declara cada listado cuadra con lo que lista.

    IT-100: el listado debe decir cuántas asignaturas contiene, y esa cifra
    tiene que cuadrar con el dataset. Es la única forma de detectar que el
    listado se ha quedado corto: un fragmento con 40 asignaturas de las 50
    que tiene la titulación se lee igual de bien y es igual de falso.
    IT-107 los añade a la misma comprobación: los listados de mención tienen
    exactamente la misma forma y el mismo modo de fallar.

    Args:
        chunks: Chunks del corpus completo.
    """
    planes = [c for c in chunks if c["origen"] in ("plan_de_estudios", "mencion")]
    for c in planes:
        if c["chunk_index"] != 0:
            continue
        declarado = re.search(r"En total son (\d+):", c["texto"])
        # `if ... raise` explícito en vez de `exigir`: aquí hace falta que el
        # verificador de tipos sepa que a partir de esta línea `declarado` no
        # es None. `assert` lo estrechaba solo, una llamada a función no.
        if declarado is None:
            raise InvarianteRoto(f"el plan {c['nombre']!r} no declara cuántas son")
        cuerpo = "\n".join(
            x["texto"].split("\n", 1)[1]
            for x in sorted(
                (p for p in planes if p["nombre"] == c["nombre"]),
                key=lambda p: p["chunk_index"],
            )
        )
        listadas = len([t for t in cuerpo.split("\n") if t.strip()])
        exigir(
            listadas == int(declarado.group(1)),
            (
                f"{c['nombre']!r} dice tener {declarado.group(1)} asignaturas "
                f"pero el listado trae {listadas}"
            ),
        )


def _exigir_catalogo(chunks: list[dict], titulaciones: list[dict]) -> None:
    """Las cifras del catálogo se recalculan contra el dataset (IT-107).

    Un fragmento derivado no se puede leer contra la fuente como se lee una
    guía: su contenido es un número, y un número equivocado se lee igual de
    bien que el correcto. Por eso se recalcula aquí desde `grados.json` en vez
    de confiar en que el fragmentador contó bien.

    Args:
        chunks: Chunks del corpus completo.
        titulaciones: Items ``grado`` del dataset.
    """
    simples = sum(1 for g in titulaciones if not g.get("es_doble_grado"))
    catalogos = [c for c in chunks if c["origen"] == "catalogo"]
    generales = [c for c in catalogos if c["nombre"].startswith("Titulaciones que")]
    exigir(
        len(generales) == 1,
        lambda: f"hay {len(generales)} catálogos generales, debe haber 1",
    )
    declarado = re.search(
        r"En total son (\d+): (\d+) grados y (\d+) dobles grados", generales[0]["texto"]
    )
    if declarado is None:
        raise InvarianteRoto("el catálogo no declara cuántas titulaciones hay")
    exigir(
        (int(declarado.group(1)), int(declarado.group(2)), int(declarado.group(3)))
        == (len(titulaciones), simples, len(titulaciones) - simples),
        lambda: (
            f"el catálogo dice {declarado.group(1)} titulaciones "
            f"({declarado.group(2)}+{declarado.group(3)}) y el dataset tiene "
            f"{len(titulaciones)} ({simples}+{len(titulaciones) - simples})"
        ),
    )
    # Los fragmentos por familia declaran su propia cifra y tienen que cuadrar
    # con la del general: es donde se vería que uno de los dos se ha quedado
    # atrás tras un cambio en la fuente.
    for familia, esperadas in (
        ("Grados", simples),
        ("Dobles", len(titulaciones) - simples),
    ):
        suyo = [c for c in catalogos if c["nombre"].startswith(familia)]
        if not suyo:
            continue
        cifra = re.search(r"En total son (\d+):", suyo[0]["texto"])
        exigir(
            cifra is not None and int(cifra.group(1)) == esperadas,
            lambda: (
                f"el catálogo de {familia!r} no cuadra con las {esperadas} "
                "del dataset"
            ),
        )


def _exigir_fichas(
    chunks: list[dict], asignaturas: list[dict], titulaciones: list[dict]
) -> None:
    """Cada titulación tiene ficha y sus cifras cuadran con el dataset (IT-107).

    Args:
        chunks: Chunks del corpus completo.
        asignaturas: Items ``asignatura`` del dataset.
        titulaciones: Items ``grado`` del dataset.
    """
    fichas = [c for c in chunks if c["origen"] == "ficha_titulacion"]
    exigir(
        len({f["nombre"] for f in fichas}) == len(titulaciones),
        lambda: (
            f"hay {len({f['nombre'] for f in fichas})} fichas para "
            f"{len(titulaciones)} titulaciones: alguna se queda sin"
        ),
    )
    for ficha in fichas:
        cifras = re.search(
            r"En total tiene (\d+) asignaturas: (\d+) obligatorias y (\d+) optativas",
            ficha["texto"],
        )
        if cifras is None:
            continue  # la titulación cuyo plan la fuente no publica
        suyas = [a for a in asignaturas if a["grado"] == ficha["grados"][0]]
        optativas = sum(1 for a in suyas if a["tipo_asignatura"] == "OP")
        real = (len(suyas), len(suyas) - optativas, optativas)
        exigir(
            tuple(int(g) for g in cifras.groups()) == real,
            lambda: (
                f"la ficha de {ficha['grados'][0]!r} dice {cifras.groups()} "
                f"y el dataset dice {real}"
            ),
        )


def _agrupar_por_unidad(chunks: list[dict]) -> dict[tuple, list]:
    """Agrupa los chunks por la unidad semántica de la que salen.

    Args:
        chunks: Chunks del corpus completo.

    Returns:
        Para cada ``(nombre, grados, origen)``, sus chunks sin ordenar.
    """
    por_unidad: dict[tuple, list] = {}
    for c in chunks:
        clave = (c["nombre"], tuple(c["grados"]), c["origen"])
        por_unidad.setdefault(clave, []).append(c)
    return por_unidad


def _exigir_numeracion(por_unidad: dict[tuple, list]) -> int:
    """Numeración consistente dentro de cada unidad y fusión bien hecha.

    Ordena de paso cada lista por ``chunk_index``, que es como
    ``cortos_evitables`` espera recibirlas.

    Args:
        por_unidad: Chunks agrupados por unidad semántica.

    Returns:
        Cuántos fragmentos quedan por debajo del mínimo siendo legítimos, para
        poder informar de la cifra al final.
    """
    cortos = 0
    for unidad, lista in por_unidad.items():
        lista.sort(key=lambda c: c["chunk_index"])
        indices = [c["chunk_index"] for c in lista]
        exigir(indices == list(range(len(lista))), f"índices rotos en {unidad}")
        exigir(
            all(c["total_chunks"] == len(lista) for c in lista),
            f"total_chunks inconsistente en {unidad}",
        )
        evitables = cortos_evitables(lista)
        exigir(
            not evitables,
            lambda: (
                f"{len(evitables)} chunk(s) por debajo del mínimo en {unidad} que "
                f"sí se podían fusionar (el más corto, {min(evitables)} caracteres). "
                f"`_fusionar_pequenos` los tenía que haber unido con su vecino: si "
                f"aparecen aquí es que la fusión ha dejado de funcionar."
            ),
        )
        cortos += sum(
            1 for c in lista if len(lista) > 1 and len(c["texto"]) < TAMANO_MINIMO
        )
    return cortos


def _exigir_cobertura_de_guias(
    con_guia: set[tuple], unidades_guia: set[tuple], dataset: list[dict]
) -> None:
    """Ninguna guía del dataset se queda sin fragmentos, y no sobran pares.

    IT-101: un fragmento de guía puede citar además la titulación doble en la
    que esa misma asignatura se imparte, y esos pares NO tienen item `guia`
    propio porque el doble grado no publica guías. Son legítimos, pero solo
    ellos: la comprobación sigue exigiendo que no falte ninguna guía y que
    todo par sobrante pertenezca a un doble grado. Aflojarla sin esa segunda
    condición dejaría pasar justo lo que este verificador existe para pillar.

    Args:
        con_guia: Claves de los items ``guia`` del dataset.
        unidades_guia: Claves que representan los chunks de origen ``guia``.
        dataset: Items del dataset completo, para saber cuáles son dobles.
    """
    dobles = {
        g["nombre"] for g in dataset if g["tipo"] == "grado" and g.get("es_doble_grado")
    }
    faltan = con_guia - unidades_guia
    sobran = unidades_guia - con_guia
    ajenos = {par for par in sobran if par[0] not in dobles}
    exigir(
        (not faltan),
        f"descuadre guía<->chunk: faltan {len(faltan)}: {sorted(faltan)[:5]}",
    )
    exigir(
        not ajenos,
        (
            f"{len(ajenos)} pares de fragmento de guía sin item `guia` y sin ser de "
            f"un doble grado: {sorted(ajenos)[:5]}"
        ),
    )


def _exigir_toda_asignatura_representada(
    asignaturas: list[dict], unidades_guia: set[tuple], informativos: set[tuple]
) -> None:
    """Toda asignatura del dataset aparece en algún fragmento (IT-94).

    Antes se comprobaba solo que las de `tiene_guia=False` tuvieran
    informativo y que las guías tuvieran sus fragmentos, y entre ambas
    comprobaciones quedaba un hueco: una asignatura con `tiene_guia=True` cuya
    guía no llegó a emitirse (PDF ilegible, IT-67) no entraba en ninguna de
    las dos y desaparecía del corpus mientras el verificador respondía «OK».

    Args:
        asignaturas: Items ``asignatura`` del dataset.
        unidades_guia: Claves representadas por los chunks de guía.
        informativos: Claves representadas por los chunks sin guía.
    """
    todas = {_clave_item(a) for a in asignaturas}
    representadas = unidades_guia | informativos
    perdidas = todas - representadas
    exigir(
        not perdidas,
        lambda: (
            f"{len(perdidas)} asignaturas del dataset no aparecen en ningún "
            f"fragmento (p. ej. {sorted(perdidas)[0]}): ni con guía ni como "
            f"asignatura sin guía. Se han perdido del corpus (IT-94)."
        ),
    )


def _informar_guias_sin_contenido(asignaturas: list[dict], guias: list[dict]) -> None:
    """Lista las guías que la fuente publica vacías y exige que no haya huérfanas.

    IT-94: las que la fuente publica pero que no aportan contenido se
    cuentan aparte, porque no son lo mismo que una guía inexistente y su
    número mide directamente cuánto contenido se está perdiendo.

    IT-97 corrige la redacción, que decía «no se ha podido extraer». Eso
    apunta a un fallo propio, y sobre el rastreo del 29/07/2026 los cinco
    casos son la contraria: el PDF se lee entero y sus secciones de
    contenido están vacías en el origen (DQA-0004). Tercer y último sitio
    donde vivía la frase; los otros dos son check_dataset.py y chunker.py.

    Se calcula por correspondencia de claves y no restando dos totales. La
    resta da la cifra correcta solo mientras no haya nada más descuadrado: el
    día que aparezca a la vez una guía nueva sin asignatura que la declare,
    los dos errores se cancelan y el aviso dice «0». Además, restar no puede
    decir CUÁLES son, y son justamente los casos del DQA-0004.

    Args:
        asignaturas: Items ``asignatura`` del dataset.
        guias: Items ``guia`` del dataset.
    """
    declaran_guia = {_clave_item(a) for a in asignaturas if a["tiene_guia"]}
    guias_reales = {_clave_item(g) for g in guias}
    sin_contenido = declaran_guia - guias_reales
    huerfanas = guias_reales - declaran_guia
    if sin_contenido:
        print(
            f"  AVISO: {len(sin_contenido)} asignaturas enlazan una guía que no "
            "aporta ni resumen ni temario; aparecen solo con sus datos "
            "básicos. `check_guias_pdf.py` dice de cada una por qué."
        )
        for clave in sorted(sin_contenido):
            print(f"    - {clave[0]} / {clave[1]}")
    # Una guía sin asignatura que la declare es otra cosa, y hasta ahora la
    # resta la habría escondido: significa que el dataset trae una guía de una
    # asignatura que no existe o que dice no tenerla.
    exigir(
        not huerfanas,
        lambda: (
            f"{len(huerfanas)} guías sin asignatura que las declare "
            f"(p. ej. {sorted(huerfanas)[0]}). O sobra la guía o la "
            f"asignatura tiene `tiene_guia` a False."
        ),
    )


def _informar_tamanos(chunks: list[dict], cortos: int) -> None:
    """Imprime el reparto de tamaños y cuántas colas cortas quedan.

    Lo de las colas se informa, no se falla: son colas irreducibles y su
    número mide cuánto cuesta la preferencia incumplida. Que suba mucho sí es
    señal de que el máximo se ha quedado corto para este corpus, y eso solo se
    ve mirándolo.

    Args:
        chunks: Chunks del corpus completo.
        cortos: Fragmentos legítimos por debajo del mínimo.
    """
    tamanos = sorted(len(c["texto"]) for c in chunks)
    n = len(tamanos)
    print(
        f"Tamaño (chars): min={tamanos[0]} mediana={tamanos[n // 2]} "
        f"p90={tamanos[int(n * 0.9)]} max={tamanos[-1]}"
    )
    if cortos:
        print(
            f"  {cortos} fragmentos por debajo del mínimo ({TAMANO_MINIMO}), "
            f"todos colas que no cabían junto a su vecino sin pasarse del "
            f"máximo. El mínimo es una preferencia, no una restricción dura."
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
    procedencia: dict = next((i for i in items if i.get("tipo") == "procedencia"), {})
    dataset = json.loads(ruta_dataset.read_text(encoding="utf-8"))
    asignaturas = [d for d in dataset if d["tipo"] == "asignatura"]
    guias = [d for d in dataset if d["tipo"] == "guia"]
    salidas = [d for d in dataset if d["tipo"] == "salidas"]
    titulaciones = [d for d in dataset if d["tipo"] == "grado"]

    _imprimir_procedencia(procedencia, len(guias))

    _exigir_forma(chunks)
    _exigir_encabezados(chunks)
    _exigir_listados_completos(chunks)
    _exigir_catalogo(chunks, titulaciones)
    _exigir_fichas(chunks, asignaturas, titulaciones)

    por_unidad = _agrupar_por_unidad(chunks)
    cortos = _exigir_numeracion(por_unidad)

    # --- Cobertura: cada item del dataset queda representado ---
    # Se expanden los chunks a pares (grado, código) por la deduplicación.
    con_guia = {_clave_item(g) for g in guias}
    unidades_guia = _claves_de_origen(chunks, "guia")
    _exigir_cobertura_de_guias(con_guia, unidades_guia, dataset)

    informativos = _claves_de_origen(chunks, "asignatura_sin_guia")
    _exigir_toda_asignatura_representada(asignaturas, unidades_guia, informativos)

    grados_salidas = {s["grado"] for s in salidas}
    grados_chunk_salidas = {
        g for c in chunks if c["origen"] == "salidas" for g in c["grados"]
    }
    exigir(grados_salidas == grados_chunk_salidas, "salidas sin trocear")

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
    _informar_guias_sin_contenido(asignaturas, guias)
    print(f"Unidades de guía compartidas entre titulaciones: {compartidas}")
    _informar_tamanos(chunks, cortos)

    print("Chunks OK: invariantes verificados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

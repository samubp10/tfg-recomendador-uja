"""Comparativa de bases de datos vectoriales (IT-31, ADR-0004).

Mide tres candidatas (ChromaDB, LanceDB y Qdrant) contra una línea base de
búsqueda exacta por fuerza bruta con NumPy, sobre el corpus real y las 50
preguntas anotadas de IT-27. Escribe los resultados dentro de
``docs/adr/adr-0004-base-vectorial.md``

**Los umbrales U1--U8 están fijados en la tarjeta ANTES de la primera
ejecución** y este guion no los reinterpreta: los comprueba.

Las cuatro candidatas reciben **exactamente los mismos vectores**: el corpus se
incrusta una sola vez y se reparte. Sin eso, la comparación mezclaría la base
con el no determinismo del modelo, y no se estaría midiendo lo que se dice.

Qdrant necesita su contenedor levantado (solo en desarrollo)::

    docker run -d --name qdrant-tfg -p 6333:6333 -p 6334:6334 qdrant/qdrant:v1.19.0


    source .venv/Scripts/activate      # Git Bash
    .venv\\Scripts\\activate.bat         # cmd.exe
    python scripts/experimento_vectordb.py
"""

from __future__ import annotations

import gc
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import version as version_instalada
from pathlib import Path
from typing import Any, Final

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

#: Un fragmento de ``chunks.json``, tal como lo emite el troceador. Se nombra
#: el concepto en vez de repetir ``dict[str, Any]`` en quince firmas: el tipo
#: crudo no dice de qué se está hablando y el alias sí, sin añadir ninguna
#: capa de indirección en tiempo de ejecución.
type Chunk = dict[str, Any]

RUTA_CHUNKS = RAIZ / "data" / "chunks.json"
RUTA_EVAL = RAIZ / "eval" / "preguntas_evaluacion.json"

#: Dónde viven los resultados brutos: dentro del propio ADR, como anexo suyo,
#: y no en un fichero aparte.
RUTA_ADR: Final[Path] = RAIZ / "docs" / "adr" / "adr-0004-base-vectorial.md"

#: Marcas entre las que este guion escribe. Permiten volver a ejecutarlo sin
#: pisar lo que el autor haya escrito a mano en el resto del ADR.
MARCA_INICIO: Final[str] = (
    "<!-- INICIO RESULTADOS AUTOMÁTICOS (scripts/experimento_vectordb.py) -->"
)
MARCA_FIN: Final[str] = "<!-- FIN RESULTADOS AUTOMÁTICOS -->"

#: Esqueleto que se escribe la primera vez, si el ADR todavía no existe. El
#: resto de secciones (Contexto, Alternativas, Decisión) son una decisión del
#: autor y este guion no las redacta: solo deja el hueco marcado con su
#: tarjeta, para que quede claro qué falta y de dónde sale cada cosa.
ESQUELETO_ADR: Final[str] = """# ADR-0004: Base de datos vectorial

*Basado en https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions*

- **Estado:** propuesta
- **Fecha:** {fecha}
- **Decisores:** Samuel Blanco Palmero
- **Contexto técnico:** Fase 2 (pipeline RAG y base vectorial) del Recomendador UJA

## Contexto

_(IT-32, pendiente de redactar. Restricciones y candidatas verificadas en
`Notas_TFG/Teoría/Fase2_bases_vectoriales/`.)_

## Alternativas consideradas

_(IT-32, pendiente. Ver `02_los_3_candidatos.md` para ChromaDB, LanceDB y
Qdrant, con licencia, arquitectura e índice de cada una, y las descartadas con
su motivo.)_

## Resultados del experimento (IT-31)

{bloque}

## Decisión

_(IT-32, pendiente: a partir de los resultados de arriba.)_

## Consecuencias

_(IT-32, pendiente.)_

## Amenazas a la validez

_(IT-32, pendiente. Ver `04_como_se_mide_una_base_vectorial.md` §4.7 para la
lista ya identificada antes de ejecutar nada.)_

## Referencias

_(IT-32, pendiente.)_
"""

#: Vecinos que se piden en cada consulta. Es el K con el que se comprueba la
#: fidelidad frente a la búsqueda exacta (U1).
K: Final[int] = 10

#: Repeticiones de cada consulta al medir latencia. La mediana de tantas
#: medidas amortigua el ruido de una máquina que está haciendo otras cosas.
REPETICIONES: Final[int] = 5

#: Consultas que se lanzan y se DESCARTAN antes de empezar a cronometrar. La
#: primera consulta contra un índice recién abierto no mide lo mismo que la
#: enésima: paga la carga perezosa de bibliotecas, la apertura de ficheros y el
#: primer llenado de cachés. Con 250 medidas su efecto sobre la mediana es
#: pequeño, pero sobre el p90 no lo es, y el p90 es lo que se informa.
CALENTAMIENTO: Final[int] = 5

#: URL del contenedor de Qdrant. No hay descubrimiento automático a propósito:
#: si no está levantado, el experimento lo dice en vez de inventarse un modo
#: de funcionamiento distinto.
URL_QDRANT: Final[str] = "http://localhost:6333"

#: Nombre del contenedor de Qdrant, para medir su memoria con ``docker stats``.
CONTENEDOR_QDRANT: Final[str] = "qdrant-tfg"

#: Casos del umbral U2, fijados en la tarjeta antes de medir. El segundo es el
#: que ejerce la trampa: «Grado en Ingeniería Eléctrica» es subcadena de dos
#: nombres de titulación doble, así que un filtro que compare subcadenas en vez
#: de pertenencia a la lista devuelve fragmentos que no son.
CASOS_FILTRO: Final[tuple[tuple[str, str, str | None], ...]] = (
    (
        "obligatorias de Informática",
        "Grado en Ingeniería Informática",
        "OB",
    ),
    (
        "Eléctrica (caso trampa)",
        "Grado en Ingeniería Eléctrica",
        None,
    ),
)


@dataclass
class Medida:
    """Lo que se mide de una candidata."""

    nombre: str
    version: str
    modo: str
    """Cómo respondió: con índice aproximado o con recorrido completo. Sin este
    dato, una fidelidad de 1,000 no se puede interpretar."""
    segundos_construir: float
    latencia_mediana_ms: float
    latencia_p90_ms: float
    fidelidad: float
    """Proporción de los K vecinos exactos que devuelve, promediada sobre las
    preguntas. Es U1, y NO es el Recall@K del sistema: compara contra la fuerza
    bruta, no contra lo que anotó una persona."""
    memoria_mb: float
    """U5. En ChromaDB y LanceDB, delta de RSS del proceso al indexar (§4.4 de
    la teoría de bases vectoriales). En Qdrant, memoria del contenedor
    completo (``docker stats``), porque el proceso de Python solo ve al
    cliente. En NumPy, el tamaño calculado de la matriz: no hay almacén."""
    filtros: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    """Por caso: (recuperados, esperados, falsos positivos)."""
    prefiltrado: tuple[int, int, bool] | None = None
    """``(devueltos, pedidos, todos cumplen el filtro)`` en el caso que
    distingue prefiltrado de posfiltrado. Devolver menos de los pedidos
    habiendo candidatos de sobra significa posfiltrar, y posfiltrar es un fallo
    silencioso: el sistema respondería «no tengo información» sobre algo que sí
    está indexado."""
    esfuerzo: dict[str, str] = field(default_factory=dict)
    """U7. Coste de operar la candidata, en hechos verificables y no en
    opiniones: si necesita un servicio aparte, si hay que declarar el esquema,
    si hay que declarar la métrica y qué hay que preparar antes de insertar."""
    notas: list[str] = field(default_factory=list)


def cargar_corpus() -> list[Chunk]:
    """Carga los chunks reales, descartando el ítem de procedencia."""
    items = json.loads(RUTA_CHUNKS.read_text(encoding="utf-8"))
    return [i for i in items if i.get("tipo") == "chunk"]


def cargar_preguntas() -> list[str]:
    """Devuelve el texto de las 50 preguntas del conjunto de evaluación."""
    datos = json.loads(RUTA_EVAL.read_text(encoding="utf-8"))
    return [p["pregunta"] for p in datos["preguntas"]]


def esperados_del_filtro(chunks: list[Chunk], grado: str, tipo: str | None) -> set[int]:
    """Verdad de referencia de un caso de U2, calculada sobre ``chunks.json``.

    Se calcula aquí y no se le pregunta a ninguna base: si la referencia
    saliera de una de las candidatas, el umbral solo comprobaría que las demás
    se parecen a ella.

    Args:
        chunks: Fragmentos del corpus.
        grado: Titulación por la que se filtra.
        tipo: Tipo de asignatura, o ``None`` para no filtrar por él.

    Returns:
        Índices de los fragmentos que el filtro debe devolver.
    """
    return {
        i
        for i, c in enumerate(chunks)
        if grado in c.get("grados", [])
        and (tipo is None or c.get("tipo_asignatura") == tipo)
    }


def fidelidad_media(exactos: list[list[int]], obtenidos: list[list[int]]) -> float:
    """Cuánto se parece un ranking al de la búsqueda exacta (U1).

    Se compara el *conjunto* de los K primeros, no su orden: lo que decide U1
    es si el índice deja fuera vecinos que la fuerza bruta sí encuentra.

    Args:
        exactos: Índices que devuelve la fuerza bruta, por pregunta.
        obtenidos: Índices que devuelve la candidata, por pregunta.

    Returns:
        Media de la proporción recuperada, en ``[0, 1]``.
    """
    # strict=True: si una candidata devolviera resultados para menos consultas
    # de las pedidas, un zip normal truncaría en silencio y la fidelidad se
    # calcularía sobre las preguntas que sí contestó, que es justo la clase de
    # cifra engañosa que este experimento no puede permitirse.
    return float(
        np.mean(
            [
                len(set(e) & set(o)) / len(e) if e else 1.0
                for e, o in zip(exactos, obtenidos, strict=True)
            ]
        )
    )


def cronometrar(consultar: Callable[[int], object], n: int) -> tuple[float, float]:
    """Mide la latencia de ``n`` consultas repetidas, en milisegundos.

    Antes de cronometrar nada se lanzan :data:`CALENTAMIENTO` consultas que se
    descartan, para que la carga perezosa del índice no entre en la muestra
    (§4.3 de la teoría de bases vectoriales).

    Args:
        consultar: Función que ejecuta la consulta ``i``.
        n: Número de consultas distintas disponibles.

    Returns:
        Mediana y percentil 90 de todas las medidas.
    """
    for i in range(min(CALENTAMIENTO, n)):
        consultar(i)

    tiempos: list[float] = []
    for _ in range(REPETICIONES):
        for i in range(n):
            inicio = time.perf_counter()
            consultar(i)
            tiempos.append((time.perf_counter() - inicio) * 1000)
    # `np.percentile` y no un índice calculado a mano: `tiempos[int(n * 0.9)]`
    # cae un puesto por encima del percentil 90 y además no interpola, y U6
    # pide reproducibilidad a tres decimales, así que la definición del
    # estadístico tiene que ser la estándar y no una aproximación propia.
    return float(np.median(tiempos)), float(np.percentile(tiempos, 90))


@contextmanager
def carpeta_temporal() -> Iterator[Path]:
    """Carpeta que se borra al salir, para los índices en disco."""
    ruta = Path(tempfile.mkdtemp(prefix="it31_"))
    try:
        yield ruta
    finally:
        shutil.rmtree(ruta, ignore_errors=True)


@dataclass
class Consultador:
    """Cómo se consulta una candidata ya construida.

    Cada adaptador aporta el suyo: la única forma de medir tres bases con el
    mismo código de evaluación es que ese código no conozca la API de ninguna
    en concreto.
    """

    vecinos: Callable[[np.ndarray, int], list[int]]
    """Vector de consulta y K -> índices de los K vecinos, en orden."""
    filtro: Callable[[str, str | None], set[int]]
    """Grado y tipo (o ``None``) -> índices de TODOS los fragmentos que
    cumplen el filtro, sin límite de K. Es lo que mide U2: no es una búsqueda
    por similitud, es una consulta estructural."""
    vecinos_filtrados: Callable[[np.ndarray, int, str], list[int]]
    """Vector de consulta, K y titulación -> los K más parecidos DE ESA
    titulación. Es la operación que distingue prefiltrado de posfiltrado, y la
    que el recuperador de la Fase 2 va a necesitar de verdad: «lo más parecido
    a esta pregunta, pero solo de este grado»."""


def incrustador_fijo(vectores: np.ndarray) -> Callable[[list[str]], list[list[float]]]:
    """Envuelve el corpus ya incrustado como si fuera un incrustador.

    ``indexar_chunks`` pide una función de incrustación y la llama con un lote
    de textos cada vez; este incrustador ignora el texto y entrega la porción
    correspondiente de ``vectores``, en el mismo orden en que se generaron. Es
    lo único que garantiza que las tres candidatas reciben EXACTAMENTE los
    mismos números: si cada una recalculara su propia incrustación, la
    comparación mezclaría la base de datos con el no determinismo del modelo.

    Args:
        vectores: Corpus ya incrustado, en el mismo orden que los chunks que
            se van a indexar.

    Returns:
        Incrustador que consume ``vectores`` por lotes consecutivos.
    """
    cursor = 0

    def incrustar(textos: list[str]) -> list[list[float]]:
        nonlocal cursor
        n = len(textos)
        # Un corte de NumPy fuera de rango devuelve un array vacío SIN avisar, y
        # eso indexaría la base con menos vectores de los que tiene el corpus
        # sin que fallara nada: justo el tipo de fallo silencioso que este
        # experimento existe para no cometer. Mejor reventar aquí.
        if cursor + n > len(vectores):
            raise ValueError(
                f"El incrustador fijo se ha agotado: se piden {n} vectores "
                f"desde la posición {cursor}, y solo hay {len(vectores)}. "
                "Cada candidata necesita su propio incrustador_fijo()."
            )
        lote = vectores[cursor : cursor + n]
        cursor += n
        return lote.tolist()

    return incrustar


def id_a_indice(identificador: str) -> int:
    """Recupera la posición original de un chunk a partir de su id.

    Las tres candidatas indexan con los ids que genera ``indexar_chunks``
    (``"chunk-0000"``, ``"chunk-0001"``...), que son la posición del chunk en
    la lista de entrada (ver su docstring). Todas las comparaciones de este
    guion -contra los vecinos exactos, contra ``esperados_del_filtro``-
    trabajan con esa posición, así que hay que poder deshacer el id.
    """
    return int(identificador.split("-")[1])


def elegir_caso_prefiltrado(
    vectores: np.ndarray,
    consultas: np.ndarray,
    chunks: list[Chunk],
    k: int = K,
) -> tuple[int, str, int] | None:
    """Busca un caso real del corpus que distinga prefiltrado de posfiltrado.

    Un caso sirve si **ninguno** de los fragmentos de la titulación elegida
    entra en el top-K de la consulta sin filtrar. Entonces:

    - quien **prefiltra** devuelve K fragmentos, todos de esa titulación;
    - quien **posfiltra** devuelve **0**, porque de los K primeros del corpus
      entero ninguno pasa el filtro.

    Se busca sobre el corpus real en vez de fabricar vectores de juguete: así
    el caso es una situación que el sistema puede vivir de verdad ---«lo más
    parecido a esta pregunta, pero solo de este grado»--- y no un montaje
    diseñado para que salga bien.

    Args:
        vectores: Corpus incrustado.
        consultas: Preguntas incrustadas.
        chunks: Corpus, para leer las titulaciones de cada fragmento.
        k: Vecinos que se pedirán.

    Returns:
        ``(índice de la consulta, titulación, fragmentos que la cumplen)``, o
        ``None`` si no hay ningún caso así en el corpus.
    """
    normalizados = vectores / np.linalg.norm(vectores, axis=1, keepdims=True)
    titulaciones = sorted({g for c in chunks for g in c.get("grados", [])})
    for i in range(len(consultas)):
        q = consultas[i] / np.linalg.norm(consultas[i])
        orden = np.argsort(-(normalizados @ q))
        top = set(orden[:k].tolist())
        for grado in titulaciones:
            cumplen = esperados_del_filtro(chunks, grado, None)
            # Hacen falta al menos k candidatos para que pedir k tenga
            # sentido, y ninguno puede estar en el top-k sin filtrar.
            if len(cumplen) >= k and not (cumplen & top):
                return i, grado, len(cumplen)
    return None


def comprobar_prefiltrado(
    consultador: Consultador,
    consultas: np.ndarray,
    chunks: list[Chunk],
    caso: tuple[int, str, int],
    k: int = K,
) -> tuple[int, int, bool]:
    """Comprueba si una candidata prefiltra o posfiltra.

    Es la garantía que el recuperador de la Fase 2 necesita y que ni U1 ni U2
    detectan: U2 pide *todos* los fragmentos que cumplen el filtro, sin top-K
    que romper, así que prefiltrar y posfiltrar dan allí el mismo resultado.

    Args:
        consultador: Adaptador de la candidata.
        consultas: Preguntas incrustadas.
        chunks: Corpus, para comprobar que lo devuelto cumple el filtro.
        caso: El de :func:`elegir_caso_prefiltrado`.
        k: Vecinos pedidos.

    Returns:
        ``(devueltos, pedidos, todos cumplen el filtro)``. Si devuelve menos de
        los pedidos habiendo candidatos de sobra, está posfiltrando.
    """
    indice_consulta, grado, _ = caso
    obtenidos = consultador.vecinos_filtrados(consultas[indice_consulta], k, grado)
    correctos = all(grado in chunks[j].get("grados", []) for j in obtenidos)
    return len(obtenidos), k, correctos


def rss_actual_mb() -> float:
    """RSS del proceso actual, en MiB.

    ``psutil`` se importa aquí y no en la cabecera porque solo hace falta para
    medir, y está en el grupo opcional ``[comparativa-vectordb]``. Con el
    import arriba, cargar este módulo lo exigía, y las pruebas ---que no miden
    memoria, sino que comprueban la aritmética de la comparación--- dejaban de
    poder recogerse en un entorno que solo instala ``[dev]``, que es
    exactamente lo que pasa en la integración continua.
    """
    import psutil

    return psutil.Process().memory_info().rss / (1024**2)


def construir_con_metricas[T](construir: Callable[[], T]) -> tuple[T, float, float]:
    """Ejecuta ``construir`` y devuelve (lo construido, segundos, RSS en MiB).

    Sirve para ChromaDB y LanceDB, que corren en el mismo proceso que el
    guion: la diferencia de RSS antes/después de indexar es lo que cuesta la
    base, no el intérprete ni NumPy (§4.4 de la teoría de bases vectoriales).
    No sirve para Qdrant, que corre en un contenedor aparte.

    Devuelve también lo que ``construir`` haya creado, para que quien la llame
    no tenga que sacarlo del cierre por un diccionario intermedio.

    Args:
        construir: Bloque que crea el almacén e indexa el corpus, y devuelve
            el almacén ya construido.

    Returns:
        Lo construido, el tiempo de construcción en segundos y el delta de RSS
        en MiB (nunca negativo: una bajada solo indicaría que el recolector de
        basura liberó algo de otro sitio, no que la base ocupe menos que cero).
    """
    gc.collect()
    antes_mem = rss_actual_mb()
    inicio = time.perf_counter()
    construido = construir()
    segundos = time.perf_counter() - inicio
    gc.collect()
    delta_mem = max(rss_actual_mb() - antes_mem, 0.0)
    return construido, segundos, delta_mem


def memoria_contenedor_mb(nombre: str) -> float:
    """Memoria residente de un contenedor Docker, en MiB (``docker stats``).

    Es la forma correcta de medir Qdrant (§4.4 de la teoría): el proceso de
    Python solo ve al cliente, no al servidor. Comparar el RSS del cliente
    contra el RSS completo de ChromaDB o LanceDB le daría a Qdrant una ventaja
    de dos órdenes de magnitud que sería puro artefacto de medición. Esto
    tampoco es "la memoria del algoritmo": es la memoria de la solución
    completa, contenedor incluido, que es lo que aquí importa.

    Args:
        nombre: Nombre del contenedor.

    Returns:
        Memoria en uso, en MiB.
    """
    salida = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", nombre],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    usado = salida.split("/")[0].strip()
    # Se separa número y unidad con una expresión regular en vez de mirar el
    # sufijo: "TB" también acaba en "B", así que comprobar terminaciones haría
    # que un terabyte entrara por la rama de los bytes y fallara con un mensaje
    # que no es el suyo.
    encaje = re.fullmatch(r"([0-9.]+)\s*([A-Za-z]+)", usado)
    if encaje is None:
        raise ValueError(f"No se entiende la salida de 'docker stats': {usado!r}")
    cantidad, unidad = float(encaje.group(1)), encaje.group(2)
    # Docker informa en binarias (GiB/MiB/KiB), en decimales (GB/MB/kB) según
    # cómo esté configurado, y en bytes sueltos cuando el contenedor apenas
    # consume. Confundir una unidad por otra daría una memoria mil veces mayor
    # o menor sin que fallara nada, y U5 es el umbral que más aprieta.
    factores_a_mib: dict[str, float] = {
        "B": 1 / 1024**2,
        "KIB": 1 / 1024,
        "MIB": 1.0,
        "GIB": 1024.0,
        "KB": 1000.0 / 1024**2,
        "MB": 1000.0**2 / 1024**2,
        "GB": 1000.0**3 / 1024**2,
    }
    factor = factores_a_mib.get(unidad.upper())
    if factor is None:
        raise ValueError(
            f"Unidad no reconocida en la salida de 'docker stats': {unidad!r}"
        )
    return cantidad * factor


def medir_candidata(
    nombre: str,
    version: str,
    modo: str,
    segundos_construir: float,
    memoria_mb: float,
    consultador: Consultador,
    consultas: np.ndarray,
    exactos: list[list[int]],
    chunks: list[Chunk],
    notas: list[str],
    caso_prefiltrado: tuple[int, str, int] | None = None,
    esfuerzo: dict[str, str] | None = None,
) -> Medida:
    """Mide una candidata ya construida: fidelidad (U1), latencia y U2.

    Args:
        nombre: Nombre de la candidata para el informe.
        version: Versión instalada, para que la comparación sea reproducible.
        modo: Cómo respondió -índice aproximado o recorrido completo-, la
            declaración que exige U1 antes de interpretar la fidelidad.
        segundos_construir: Tiempo de indexación del corpus completo.
        memoria_mb: Memoria que cuesta la candidata, medida como corresponda a
            cómo se ejecuta.
        consultador: Adaptador de consulta de la candidata.
        consultas: Vectores de las 50 preguntas de evaluación.
        exactos: Vecinos exactos de cada consulta (referencia de U1).
        chunks: Corpus, para calcular la verdad de referencia de U2.
        notas: Observaciones libres sobre cómo se ha medido esta candidata.
        caso_prefiltrado: Caso con el que comprobar si prefiltra o posfiltra.
            Si es ``None``, no se comprueba (no había ninguno en el corpus).
        esfuerzo: Coste de operarla, para U7.

    Returns:
        La medida completa, lista para evaluarse contra U1-U8.
    """
    obtenidos = [
        list(consultador.vecinos(consultas[i], K)) for i in range(len(consultas))
    ]
    fidelidad = fidelidad_media(exactos, obtenidos)
    mediana, p90 = cronometrar(
        lambda i: consultador.vecinos(consultas[i], K), len(consultas)
    )
    filtros: dict[str, tuple[int, int, int]] = {}
    for etiqueta, grado, tipo in CASOS_FILTRO:
        esperado = esperados_del_filtro(chunks, grado, tipo)
        devuelto = consultador.filtro(grado, tipo)
        filtros[etiqueta] = (len(devuelto), len(esperado), len(devuelto - esperado))
    prefiltrado = (
        comprobar_prefiltrado(consultador, consultas, chunks, caso_prefiltrado)
        if caso_prefiltrado is not None
        else None
    )
    return Medida(
        nombre=nombre,
        version=version,
        modo=modo,
        segundos_construir=segundos_construir,
        latencia_mediana_ms=mediana,
        latencia_p90_ms=p90,
        fidelidad=fidelidad,
        memoria_mb=memoria_mb,
        filtros=filtros,
        prefiltrado=prefiltrado,
        esfuerzo=esfuerzo or {},
        notas=notas,
    )


def medir_numpy(
    vectores: np.ndarray, consultas: np.ndarray
) -> tuple[Medida, list[list[int]]]:
    """Mide la línea base de fuerza bruta y calcula los vecinos exactos.

    Es la única candidata que no pasa por ``indexar_chunks``: no hay almacén,
    solo la matriz. Devuelve además los vecinos exactos de cada pregunta,
    porque son la referencia contra la que se mide U1 en las otras tres.
    """
    inicio = time.perf_counter()
    normas = vectores / np.linalg.norm(vectores, axis=1, keepdims=True)
    segundos_construir = time.perf_counter() - inicio

    def vecinos_de(i: int) -> list[int]:
        q = consultas[i] / np.linalg.norm(consultas[i])
        return list(np.argsort(-(normas @ q))[:K])

    exactos = [vecinos_de(i) for i in range(len(consultas))]
    mediana, p90 = cronometrar(vecinos_de, len(consultas))
    medida = Medida(
        nombre="NumPy (fuerza bruta, línea base)",
        version=np.__version__,
        modo="exacto por construcción; no es candidata, es la referencia de U1",
        segundos_construir=segundos_construir,
        latencia_mediana_ms=mediana,
        latencia_p90_ms=p90,
        fidelidad=1.0,
        memoria_mb=vectores.nbytes / (1024**2),
        notas=[
            "No se mide U2: no filtra nada, es la propia esperados_del_filtro "
            "la que hace de verdad de referencia para las otras tres.",
            "Memoria calculada de la matriz (vectores.nbytes), no RSS: es la "
            "línea base, no un almacén con su propia sobrecarga.",
        ],
    )
    return medida, exactos


# --- ChromaDB --------------------------------------------------------------

#: Coste de operar ChromaDB (U7). Vive fuera de ``medir_chroma`` porque las
#: tres tablas de esfuerzo son las columnas de UNA tabla del informe: puestas
#: juntas se comparan de un vistazo, y enterradas cada una en su función había
#: que saltar trescientas líneas para ver qué contestaba cada candidata a la
#: misma pregunta. El orden de las claves es el orden de las filas de la tabla.
ESFUERZO_CHROMA: Final[dict[str, str]] = {
    "¿Servicio aparte?": "No: en proceso, `PersistentClient(path=...)`",
    "¿Docker?": "No",
    "¿Esquema declarado?": "No: los metadatos se infieren de cada `add`",
    "¿Métrica declarada?": "**Sí, obligatorio**: por defecto es `l2`",
    "Preparación antes de insertar": "Ninguna",
    "Índices de apoyo para filtrar": "Ninguno",
    "Sintaxis del filtro": "`$and` de `$contains` y `$eq` (dict)",
}

#: Observaciones sobre cómo se ha medido ChromaDB, que el informe imprime bajo
#: su veredicto.
NOTAS_CHROMA: Final[tuple[str, ...]] = (
    "Distancia coseno declarada explícitamente al crear la colección "
    "(la de ChromaDB por defecto es l2).",
    "Su fidelidad NO permite concluir «su índice es fiel» mientras el "
    "modo no esté determinado.",
)


class AlmacenChroma:
    """Adaptador de una colección de ChromaDB a ``AlmacenVectorial``.

    Vive aquí y no en ``indexer.py`` porque ChromaDB es la candidata que el
    ADR-0004 descarta: el sistema no la monta, pero este experimento tiene que
    poder seguir midiéndola, que es de donde sale la evidencia que la descarta.
    """

    def __init__(self, coleccion: Any) -> None:
        self.coleccion = coleccion

    def anadir(
        self,
        ids: list[str],
        vectores: list[Sequence[float]],
        textos: list[str],
        metadatos: list[dict[str, Any]],
    ) -> None:
        """Almacena un lote en la colección."""
        embeddings: list[Sequence[float] | Sequence[int]] = list(vectores)
        self.coleccion.add(
            ids=ids,
            embeddings=embeddings,
            documents=textos,
            metadatas=[dict(m) for m in metadatos],
        )


def crear_almacen_chroma(
    ruta_indice: Path, metadatos_coleccion: dict[str, str]
) -> AlmacenChroma:
    """Crea un índice persistente de ChromaDB vacío, borrando el anterior.

    Args:
        ruta_indice: Carpeta donde persiste el índice.
        metadatos_coleccion: Metadatos que describen el índice.

    Returns:
        Almacén listo para recibir vectores.
    """
    import chromadb

    from tfg_uja.indexer import COLECCION

    cliente = chromadb.PersistentClient(path=str(ruta_indice))
    try:
        cliente.delete_collection(COLECCION)
    except Exception:
        # La colección no existía todavía: primera ejecución.
        pass
    # Distancia coseno declarada explícitamente: la de ChromaDB por defecto es
    # `l2`. Se declara aquí al crear la colección porque es donde la recibe
    # esta base, a diferencia de LanceDB, que la toma en cada consulta.
    return AlmacenChroma(
        cliente.create_collection(
            COLECCION, metadata={"hnsw:space": "cosine", **metadatos_coleccion}
        )
    )


def _consultador_chroma(coleccion: Any) -> Consultador:
    """Adapta las tres operaciones que mide el experimento a la API de Chroma.

    Args:
        coleccion: Colección ya construida e indexada.

    Returns:
        El adaptador con el que ``medir_candidata`` la interroga.
    """

    def vecinos(consulta: np.ndarray, k: int) -> list[int]:
        resultado = coleccion.query(query_embeddings=[consulta.tolist()], n_results=k)
        return [id_a_indice(i) for i in resultado["ids"][0]]

    def filtro(grado: str, tipo: str | None) -> set[int]:
        where: dict[str, Any] = (
            {
                "$and": [
                    {"grados": {"$contains": grado}},
                    {"tipo_asignatura": {"$eq": tipo}},
                ]
            }
            if tipo is not None
            else {"grados": {"$contains": grado}}
        )
        resultado = coleccion.get(where=where)
        return {id_a_indice(i) for i in resultado["ids"]}

    def vecinos_filtrados(consulta: np.ndarray, k: int, grado: str) -> list[int]:
        resultado = coleccion.query(
            query_embeddings=[consulta.tolist()],
            n_results=k,
            where={"grados": {"$contains": grado}},
        )
        return [id_a_indice(i) for i in resultado["ids"][0]]

    return Consultador(
        vecinos=vecinos, filtro=filtro, vecinos_filtrados=vecinos_filtrados
    )


def _modo_chroma(coleccion: Any) -> str:
    """Describe cómo responde ChromaDB, que es lo que U1 exige declarar.

    Args:
        coleccion: Colección ya construida.

    Returns:
        La descripción del modo, tal como aparece en el informe.
    """
    # `configuration_json` no es API pública documentada de ChromaDB: hoy
    # existe en 1.5.9 y devuelve los parámetros efectivos de HNSW (comprobado),
    # pero una versión futura puede quitarlo o cambiarle la forma. Si
    # desapareciera, lo que NO puede pasar es que se caiga el experimento
    # entero por un dato que solo sirve para describir la configuración en el
    # informe: se degrada a los metadatos de la colección, que sí son API
    # pública, y se dice que el resto no se ha podido leer.
    try:
        hnsw = dict(coleccion.configuration_json.get("hnsw") or {})
    except (AttributeError, TypeError):
        metadatos_coleccion = coleccion.metadata or {}
        hnsw = {"space": metadatos_coleccion.get("hnsw:space", "no legible")}

    return (
        "NO VERIFICABLE desde el cliente — la colección se configura con "
        f"HNSW (space={hnsw.get('space')}, ef_search={hnsw.get('ef_search')}, "
        f"max_neighbors={hnsw.get('max_neighbors')}), pero ChromaDB **no "
        "expone un contador de vectores indexados** como Qdrant, así que "
        "no se puede comprobar por esta vía si a 1.334 vectores responde "
        "recorriendo el grafo o el conjunto completo"
    )


def medir_chroma(
    chunks: list[Chunk],
    vectores: np.ndarray,
    consultas: np.ndarray,
    exactos: list[list[int]],
    ruta_indice: Path,
    caso_prefiltrado: tuple[int, str, int] | None = None,
) -> Medida:
    """Construye y mide ChromaDB, reutilizando el pipeline de ``indexer.py``."""
    from tfg_uja.incrustaciones import MODELO, PREFIJO_DOCUMENTO
    from tfg_uja.indexer import indexar_chunks

    def construir() -> Any:
        almacen = crear_almacen_chroma(
            ruta_indice, {"modelo": MODELO, "prefijo_documento": PREFIJO_DOCUMENTO}
        )
        indexar_chunks(chunks, almacen, incrustador_fijo(vectores))
        return almacen.coleccion

    coleccion, segundos_construir, memoria_mb = construir_con_metricas(construir)

    return medir_candidata(
        nombre="ChromaDB",
        version=version_instalada("chromadb"),
        modo=_modo_chroma(coleccion),
        segundos_construir=segundos_construir,
        memoria_mb=memoria_mb,
        consultador=_consultador_chroma(coleccion),
        consultas=consultas,
        exactos=exactos,
        chunks=chunks,
        caso_prefiltrado=caso_prefiltrado,
        esfuerzo=ESFUERZO_CHROMA,
        notas=list(NOTAS_CHROMA),
    )


# --- LanceDB ---------------------------------------------------------------

#: Coste de operar LanceDB (U7). Mismas claves y mismo orden que
#: :data:`ESFUERZO_CHROMA`: son las filas de la tabla del informe.
ESFUERZO_LANCEDB: Final[dict[str, str]] = {
    "¿Servicio aparte?": "No: en proceso, `lancedb.connect(ruta)`",
    "¿Docker?": "No",
    "¿Esquema declarado?": (
        "**Sí**: esquema Arrow explícito, con el vector como "
        "`list_(float32, 384)` de tamaño fijo"
    ),
    "¿Métrica declarada?": "**Sí, obligatorio**: por defecto es `l2`",
    "Preparación antes de insertar": "Crear la tabla con su esquema",
    "Índices de apoyo para filtrar": (
        "Ninguno creado. Su documentación menciona un índice escalar "
        "`LABEL_LIST` para columnas lista; **el filtrado da 58/58 y "
        "417/417 sin él**, así que a esta escala es de rendimiento y "
        "no de corrección"
    ),
    "Sintaxis del filtro": "SQL de DataFusion: `array_has_any(...)`",
}

#: Observaciones sobre cómo se ha medido LanceDB.
NOTAS_LANCEDB: Final[tuple[str, ...]] = (
    "Prefiltrado por defecto (prefilter=True).",
    "Distancia coseno declarada en cada consulta: la de LanceDB por "
    "defecto es l2 (comprobado ejecutándolo).",
)


def _sql_literal(valor: str) -> str:
    """Escapa un valor para meterlo en una cadena SQL de LanceDB.

    LanceDB no expone consultas parametrizadas, así que el filtro se compone
    interpolando. Una comilla simple en un nombre de titulación rompería la
    expresión; hoy ninguno de los once nombres del corpus la lleva, pero eso es
    una propiedad de los datos de la EPSJ y no una garantía del código.

    Args:
        valor: Texto a insertar en la expresión SQL.

    Returns:
        El texto con las comillas simples duplicadas, según el estándar SQL.
    """
    return valor.replace("'", "''")


def _esquema_lance(dimension: int) -> Any:
    """Esquema Arrow explícito de la tabla, con el vector como lista de tamaño fijo."""
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dimension)),
            pa.field("texto", pa.string()),
            pa.field("origen", pa.string()),
            pa.field("nombre", pa.string()),
            pa.field("grados", pa.list_(pa.string())),
            pa.field("codigos", pa.list_(pa.string())),
            pa.field("tipo_asignatura", pa.string()),
            pa.field("chunk_index", pa.int64()),
            pa.field("total_chunks", pa.int64()),
        ]
    )


class AlmacenLance:
    """Adaptador de una tabla de LanceDB a ``AlmacenVectorial``."""

    def __init__(self, tabla: Any) -> None:
        self.tabla = tabla

    def anadir(
        self,
        ids: list[str],
        vectores: list[Sequence[float]],
        textos: list[str],
        metadatos: list[dict[str, Any]],
    ) -> None:
        """Almacena un lote como filas de la tabla."""
        registros = [
            {
                "id": ids[i],
                "vector": list(vectores[i]),
                "texto": textos[i],
                **metadatos[i],
            }
            for i in range(len(ids))
        ]
        self.tabla.add(registros)


def _consultador_lancedb(tabla: Any, total: int) -> Consultador:
    """Adapta las tres operaciones que mide el experimento a la API de Lance.

    Args:
        tabla: Tabla ya construida e indexada.
        total: Filas que tiene, para pedirlas todas al comprobar U2 (que no es
            una búsqueda por similitud, sino una consulta estructural sin K).

    Returns:
        El adaptador con el que ``medir_candidata`` la interroga.
    """

    def vecinos(consulta: np.ndarray, k: int) -> list[int]:
        # `distance_type("cosine")` es OBLIGATORIO, no decorativo: la métrica
        # por defecto de LanceDB es `l2` (comprobado ejecutándolo). Con este
        # modelo el ranking coincide ---e5 devuelve vectores de norma 1 y para
        # vectores normalizados ||a-b||² = 2 - 2·cos(a,b), así que ordenar por
        # una cosa o por la otra da lo mismo--- pero eso es una propiedad del
        # modelo, no de la base: dejarlo implícito haría que un cambio de
        # modelo rompiera el ranking sin que fallara nada.
        filas = (
            tabla.search(consulta.tolist()).distance_type("cosine").limit(k).to_list()
        )
        return [id_a_indice(f["id"]) for f in filas]

    def filtro(grado: str, tipo: str | None) -> set[int]:
        expr = f"array_has_any(grados, ['{_sql_literal(grado)}'])"
        if tipo is not None:
            expr += f" AND tipo_asignatura = '{_sql_literal(tipo)}'"
        filas = tabla.search().where(expr, prefilter=True).limit(total).to_list()
        return {id_a_indice(f["id"]) for f in filas}

    def vecinos_filtrados(consulta: np.ndarray, k: int, grado: str) -> list[int]:
        filas = (
            tabla.search(consulta.tolist())
            .distance_type("cosine")
            .where(f"array_has_any(grados, ['{_sql_literal(grado)}'])", prefilter=True)
            .limit(k)
            .to_list()
        )
        return [id_a_indice(f["id"]) for f in filas]

    return Consultador(
        vecinos=vecinos, filtro=filtro, vecinos_filtrados=vecinos_filtrados
    )


def _modo_lancedb(tabla: Any) -> str:
    """Describe cómo responde LanceDB, que es lo que U1 exige declarar.

    Args:
        tabla: Tabla ya construida.

    Returns:
        La descripción del modo, tal como aparece en el informe.
    """
    # El modo se LEE de la tabla, no se afirma por documentación: si algún día
    # LanceDB decidiera construir un índice a esta escala, el informe lo diría
    # en vez de seguir asegurando que no lo hay.
    indices = tabla.list_indices()
    return (
        f"escaneo completo — MEDIDO: list_indices() = {indices or '[]'}, "
        "ningún índice ANN construido (el corpus está por debajo de las "
        "«few thousand rows» que recomienda su documentación)"
    )


def medir_lancedb(
    chunks: list[Chunk],
    vectores: np.ndarray,
    consultas: np.ndarray,
    exactos: list[list[int]],
    ruta_indice: Path,
    caso_prefiltrado: tuple[int, str, int] | None = None,
) -> Medida:
    """Construye y mide LanceDB."""
    import lancedb

    from tfg_uja.indexer import indexar_chunks

    def construir() -> Any:
        db = lancedb.connect(str(ruta_indice))
        tabla = db.create_table(
            "chunks_epsj", schema=_esquema_lance(vectores.shape[1]), mode="overwrite"
        )
        almacen = AlmacenLance(tabla)
        indexar_chunks(chunks, almacen, incrustador_fijo(vectores))
        return almacen.tabla

    tabla, segundos_construir, memoria_mb = construir_con_metricas(construir)

    return medir_candidata(
        nombre="LanceDB",
        version=version_instalada("lancedb"),
        modo=_modo_lancedb(tabla),
        segundos_construir=segundos_construir,
        memoria_mb=memoria_mb,
        consultador=_consultador_lancedb(tabla, tabla.count_rows()),
        consultas=consultas,
        exactos=exactos,
        chunks=chunks,
        caso_prefiltrado=caso_prefiltrado,
        esfuerzo=ESFUERZO_LANCEDB,
        notas=list(NOTAS_LANCEDB),
    )


# --- Qdrant ----------------------------------------------------------------

#: Coste de operar Qdrant (U7). Mismas claves y mismo orden que
#: :data:`ESFUERZO_CHROMA`: son las filas de la tabla del informe.
ESFUERZO_QDRANT: Final[dict[str, str]] = {
    "¿Servicio aparte?": "**Sí**: servidor en `localhost:6333`",
    "¿Docker?": (
        "**Sí** para el experimento. Solo en desarrollo: el sistema "
        "no depende de Docker en marcha"
    ),
    "¿Esquema declarado?": (
        "Parcial: `VectorParams(size, distance)`. El payload es JSON libre"
    ),
    "¿Métrica declarada?": "**Sí**, en `VectorParams`",
    "Preparación antes de insertar": (
        "**Dos índices de payload** (`grados`, `tipo_asignatura`), y "
        "conviene crearlos ANTES de insertar porque son los que "
        "generan las aristas del HNSW filtrable"
    ),
    "Índices de apoyo para filtrar": "Dos, del tipo `KEYWORD`",
    "Sintaxis del filtro": "Objetos `Filter(must=[FieldCondition...])`",
}

#: Observaciones sobre cómo se ha medido Qdrant.
NOTAS_QDRANT: Final[tuple[str, ...]] = (
    "Memoria del contenedor completo (docker stats), no del proceso "
    "cliente: incluye el sistema base del contenedor.",
    "Índices de payload creados antes de insertar los datos.",
)


class AlmacenQdrant:
    """Adaptador de una colección de Qdrant a ``AlmacenVectorial``."""

    def __init__(self, cliente: Any, coleccion: str) -> None:
        self.cliente = cliente
        self.coleccion = coleccion

    def anadir(
        self,
        ids: list[str],
        vectores: list[Sequence[float]],
        textos: list[str],
        metadatos: list[dict[str, Any]],
    ) -> None:
        """Almacena un lote como puntos, con id numérico (posición del chunk)."""
        from qdrant_client.models import PointStruct

        puntos = [
            PointStruct(
                id=id_a_indice(ids[i]),
                vector=list(vectores[i]),
                payload={"texto": textos[i], **metadatos[i]},
            )
            for i in range(len(ids))
        ]
        self.cliente.upsert(collection_name=self.coleccion, points=puntos)


def _crear_coleccion_qdrant(cliente: Any, nombre: str, dimension: int) -> None:
    """Deja la colección vacía y con sus índices de payload, lista para insertar.

    Args:
        cliente: Cliente del servidor de Qdrant.
        nombre: Nombre de la colección.
        dimension: Dimensión de los vectores del modelo.
    """
    from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

    # `collection_exists` en vez de un delete envuelto en `except: pass`:
    # ese patrón se traga también un Qdrant caído o un fallo de red, y
    # entonces el error aparece más adelante, en `create_collection`, con
    # un mensaje que no dice cuál era el problema real.
    if cliente.collection_exists(nombre):
        cliente.delete_collection(nombre)
    cliente.create_collection(
        collection_name=nombre,
        vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
    )
    # Los índices de payload se crean ANTES de insertar: son los que
    # generan las aristas extra del HNSW filtrable (§2.3 de
    # 02_los_3_candidatos.md). A esta escala no llega a construirse HNSW,
    # pero es la forma correcta de operar la candidata igualmente.
    cliente.create_payload_index(
        nombre, "grados", field_schema=PayloadSchemaType.KEYWORD
    )
    cliente.create_payload_index(
        nombre,
        "tipo_asignatura",
        field_schema=PayloadSchemaType.KEYWORD,
    )


def _consultador_qdrant(cliente: Any, nombre_coleccion: str) -> Consultador:
    """Adapta las tres operaciones que mide el experimento a la API de Qdrant.

    Args:
        cliente: Cliente del servidor de Qdrant.
        nombre_coleccion: Colección ya construida e indexada.

    Returns:
        El adaptador con el que ``medir_candidata`` la interroga.
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    def vecinos(consulta: np.ndarray, k: int) -> list[int]:
        resultado = cliente.query_points(
            collection_name=nombre_coleccion, query=consulta.tolist(), limit=k
        )
        return [int(p.id) for p in resultado.points]

    def filtro(grado: str, tipo: str | None) -> set[int]:
        # Anotación explícita: `must` admite una unión de tipos de condición y
        # list es invariante, así que una list[FieldCondition] no encaja.
        condiciones: list[Any] = [
            FieldCondition(key="grados", match=MatchValue(value=grado))
        ]
        if tipo is not None:
            condiciones.append(
                FieldCondition(key="tipo_asignatura", match=MatchValue(value=tipo))
            )
        # Se pagina hasta agotar el cursor en vez de pedir `limit=len(chunks)`
        # y confiar en que entre todo: Qdrant tiene un tope propio por
        # respuesta, y quedarse con la primera página devolvería menos
        # fragmentos de los que cumplen el filtro. U2 lo leería como que la
        # candidata «pierde» resultados, cuando el que se los deja es el guion.
        encontrados: set[int] = set()
        desplazamiento: Any = None
        while True:
            puntos, desplazamiento = cliente.scroll(
                collection_name=nombre_coleccion,
                scroll_filter=Filter(must=condiciones),
                limit=1000,
                offset=desplazamiento,
                with_payload=False,
            )
            encontrados.update(int(p.id) for p in puntos)
            if desplazamiento is None:
                return encontrados

    def vecinos_filtrados(consulta: np.ndarray, k: int, grado: str) -> list[int]:
        resultado = cliente.query_points(
            collection_name=nombre_coleccion,
            query=consulta.tolist(),
            limit=k,
            query_filter=Filter(
                must=[FieldCondition(key="grados", match=MatchValue(value=grado))]
            ),
        )
        return [int(p.id) for p in resultado.points]

    return Consultador(
        vecinos=vecinos, filtro=filtro, vecinos_filtrados=vecinos_filtrados
    )


def _modo_qdrant(info: Any) -> str:
    """Describe cómo responde Qdrant, leyéndolo de la colección.

    Qdrant es la única de las tres que expone cuántos vectores tiene
    realmente indexados, así que aquí el modo no hay que suponerlo: se lee.
    Es la comprobación que evita el quinto caso de «el verificador medía algo
    distinto de lo que creía medir»: una fidelidad de 1,000 obtenida por
    escaneo completo significa «no perdió nada», no «su índice es fiel».

    Args:
        info: Descripción de la colección, tal como la devuelve
            ``get_collection``.

    Returns:
        La descripción del modo, tal como aparece en el informe.
    """
    indexados = info.indexed_vectors_count or 0
    umbral_indexado = info.config.optimizer_config.indexing_threshold
    umbral_escaneo = info.config.hnsw_config.full_scan_threshold
    return (
        f"{'escaneo completo' if indexados == 0 else 'HNSW'} — MEDIDO: "
        f"indexed_vectors_count = {indexados} de {info.points_count} "
        f"puntos (indexing_threshold = {umbral_indexado} KiB, "
        f"full_scan_threshold = {umbral_escaneo} KiB; el corpus ocupa "
        "~2001 KiB, por debajo de ambos; no se han bajado a mano para "
        "forzar la construcción del índice)"
    )


def medir_qdrant(
    chunks: list[Chunk],
    vectores: np.ndarray,
    consultas: np.ndarray,
    exactos: list[list[int]],
    caso_prefiltrado: tuple[int, str, int] | None = None,
) -> Medida:
    """Construye y mide Qdrant. Requiere el contenedor levantado.

    No pasa por :func:`construir_con_metricas` porque su memoria no se mide
    igual: el proceso de Python solo ve al cliente, así que la construcción se
    cronometra aquí y la memoria se le pide al contenedor.
    """
    from qdrant_client import QdrantClient

    from tfg_uja.indexer import indexar_chunks

    cliente = QdrantClient(url=URL_QDRANT)
    nombre_coleccion = "chunks_epsj"

    inicio = time.perf_counter()
    _crear_coleccion_qdrant(cliente, nombre_coleccion, vectores.shape[1])
    indexar_chunks(
        chunks, AlmacenQdrant(cliente, nombre_coleccion), incrustador_fijo(vectores)
    )
    segundos_construir = time.perf_counter() - inicio
    memoria_mb = memoria_contenedor_mb(CONTENEDOR_QDRANT)

    return medir_candidata(
        nombre="Qdrant",
        version=(
            f"cliente {version_instalada('qdrant-client')} · "
            "imagen qdrant/qdrant:v1.19.0 (pyproject.toml)"
        ),
        modo=_modo_qdrant(cliente.get_collection(nombre_coleccion)),
        segundos_construir=segundos_construir,
        memoria_mb=memoria_mb,
        consultador=_consultador_qdrant(cliente, nombre_coleccion),
        consultas=consultas,
        exactos=exactos,
        chunks=chunks,
        caso_prefiltrado=caso_prefiltrado,
        esfuerzo=ESFUERZO_QDRANT,
        notas=list(NOTAS_QDRANT),
    )


def comprobar_normas(vectores: np.ndarray) -> tuple[float, float, bool]:
    """Mide si el modelo entrega vectores normalizados, y por qué importa.

    Para vectores de norma 1, ``||a-b||² = 2 - 2·cos(a,b)``, así que ordenar
    por distancia euclídea y por similitud coseno da **el mismo ranking**. Eso
    obliga a matizar una conclusión que si no se leería mal: que las tres
    candidatas coincidan con la fuerza bruta no demuestra que las tres estén
    usando la métrica que se les ha pedido. Con este modelo no se puede
    distinguir, y hay que decirlo en vez de dar por bueno el 1,000.

    Returns:
        Norma mínima, norma máxima y si los vectores están **normalizados**.

        Lo tercero exige norma constante **y próxima a 1**, no solo constante:
        una matriz de ceros tiene desviación cero y no está normalizada, y
        afirmar lo contrario en el informe sería una cifra inventada.
    """
    normas = np.linalg.norm(vectores, axis=1)
    normalizados = bool(normas.std() < 1e-5 and abs(float(normas.mean()) - 1.0) < 1e-5)
    return float(normas.min()), float(normas.max()), normalizados


def poder_discriminante_u2(chunks: list[Chunk]) -> dict[str, tuple[int, int]]:
    """Cuántos fragmentos devolvería un filtro por subcadena en cada caso de U2.

    Un umbral que se cumple igual con la implementación buena y con la mala no
    mide nada, y este proyecto ya ha visto cuatro veces un verificador dando
    «OK» sobre algo que no comprobaba. Esto lo cuantifica: si las dos columnas
    coinciden, ese caso **no discrimina** y no se puede presentar como
    evidencia de que el filtrado es correcto.

    Returns:
        Por caso: (esperados con pertenencia exacta, devueltos por subcadena).
    """
    resultado: dict[str, tuple[int, int]] = {}
    for etiqueta, grado, tipo in CASOS_FILTRO:
        exactos = esperados_del_filtro(chunks, grado, tipo)
        por_subcadena = {
            i
            for i, c in enumerate(chunks)
            if any(grado in g for g in c.get("grados", []))
            and (tipo is None or c.get("tipo_asignatura") == tipo)
        }
        resultado[etiqueta] = (len(exactos), len(por_subcadena))
    return resultado


# --- Veredictos contra los umbrales ----------------------------------------


def _veredicto_u1(m: Medida) -> str:
    """U1: fidelidad frente a la fuerza bruta, con el 1,000 exacto por criterio."""
    return (
        f"U1 (fidelidad = 1,000 exacto): "
        f"{'CUMPLE' if m.fidelidad == 1.0 else 'NO CUMPLE'} ({m.fidelidad:.4f})"
    )


def _veredicto_u2(m: Medida) -> str:
    """U2: el filtrado por metadatos, caso a caso, con su detalle."""
    u2_ok = all(fp == 0 and rec == esp for rec, esp, fp in m.filtros.values())
    detalle = "; ".join(
        f"{etq}: {rec}/{esp} recuperados/esperados, {fp} falsos positivos"
        for etq, (rec, esp, fp) in m.filtros.items()
    )
    return (
        f"U2 (precisión y exhaustividad 1,000, 0 falsos positivos): "
        f"{'CUMPLE' if u2_ok else 'NO CUMPLE'} ({detalle})"
    )


def _veredicto_u3(m: Medida) -> str:
    """U3: latencia mediana, con el p90 al lado para no leerla sola."""
    return (
        f"U3 (latencia mediana <= 500 ms): "
        f"{'CUMPLE' if m.latencia_mediana_ms <= 500 else 'NO CUMPLE'} "
        f"({m.latencia_mediana_ms:.2f} ms, p90 {m.latencia_p90_ms:.2f} ms)"
    )


def _veredicto_u5(m: Medida) -> str:
    """U5: memoria residente, que no es binario sino de tres tramos."""
    if m.memoria_mb <= 512:
        u5 = "CUMPLE (<= 0,5 GiB)"
    elif m.memoria_mb <= 1024:
        u5 = "ZONA INTERMEDIA (> 0,5 GiB y <= 1 GiB)"
    else:
        u5 = "DESCARTA (> 1 GiB)"
    return f"U5 (memoria residente): {u5} ({m.memoria_mb:.2f} MiB)"


def _veredicto_prefiltrado(prefiltrado: tuple[int, int, bool]) -> str:
    """Prefiltrado: no es un umbral, es una garantía de corrección.

    Args:
        prefiltrado: ``(devueltos, pedidos, todos cumplen el filtro)``.

    Returns:
        La línea del informe, con el veredicto y sus cifras.
    """
    devueltos, pedidos, correctos = prefiltrado
    prefiltra = devueltos == pedidos and correctos
    return (
        f"Prefiltrado (no es un umbral, es una garantía de corrección): "
        f"{'PREFILTRA' if prefiltra else 'POSFILTRA O PIERDE'} "
        f"({devueltos} de {pedidos} pedidos"
        + ("" if correctos else ", y alguno NO cumple el filtro")
        + ")"
    )


def evaluar_umbrales(medidas: dict[str, Medida]) -> dict[str, list[str]]:
    """Contrasta cada candidata (no la línea base de NumPy) contra U1-U5.

    U6 (reproducibilidad) y U7 (simplicidad) no son magnitudes que este guion
    calcule por sí solo: la primera exige repetir la ejecución completa y
    comparar, y la segunda es un juicio de ingeniería. U8 es una conclusión
    sobre el conjunto, no un veredicto por candidata; se deja para el ADR.

    No decide nada: solo dice qué umbral cumple y cuál no cada candidata, con
    sus cifras. La lectura -qué significa un incumplimiento, si el esquema o
    la base es responsable- se escribe a mano en el ADR.
    """
    veredictos: dict[str, list[str]] = {}
    for nombre, m in medidas.items():
        if nombre == "NumPy":
            continue
        lineas = [_veredicto_u1(m)]
        if m.filtros:
            lineas.append(_veredicto_u2(m))
        lineas.append(_veredicto_u3(m))
        lineas.append(_veredicto_u5(m))
        if m.prefiltrado is not None:
            lineas.append(_veredicto_prefiltrado(m.prefiltrado))
        veredictos[nombre] = lineas
    return veredictos


def _tabla_resumen(medidas: dict[str, Medida]) -> str:
    filas = [
        "| Candidata | Versión | Modo | Fidelidad (U1) | Latencia mediana (U3) "
        "| Latencia p90 | Construcción | Memoria (U5) |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for m in medidas.values():
        filas.append(
            f"| {m.nombre} | {m.version} | {m.modo} | {m.fidelidad:.4f} | "
            f"{m.latencia_mediana_ms:.2f} ms | {m.latencia_p90_ms:.2f} ms | "
            f"{m.segundos_construir:.2f} s | {m.memoria_mb:.2f} MiB |"
        )
    return "\n".join(filas)


def _tabla_filtrado(medidas: dict[str, Medida]) -> str:
    filas = [
        "| Candidata | Caso | Recuperados | Esperados | Falsos positivos |",
        "|---|---|---:|---:|---:|",
    ]
    for m in medidas.values():
        for etiqueta, (rec, esp, fp) in m.filtros.items():
            filas.append(f"| {m.nombre} | {etiqueta} | {rec} | {esp} | {fp} |")
    return "\n".join(filas)


def _tabla_discriminante(discriminante: dict[str, tuple[int, int]]) -> str:
    filas = [
        "| Caso de U2 | Correctos (pertenencia exacta) | Devueltos por un "
        "filtro de subcadena | ¿Discrimina? |",
        "|---|---:|---:|---|",
    ]
    for etiqueta, (exactos, subcadena) in discriminante.items():
        discrimina = (
            f"**sí**, {subcadena - exactos} falsos positivos"
            if subcadena != exactos
            else "**no**: los dos coinciden"
        )
        filas.append(f"| {etiqueta} | {exactos} | {subcadena} | {discrimina} |")
    return "\n".join(filas)


def _tabla_esfuerzo(medidas: dict[str, Medida]) -> str:
    """Tabla de U7: el coste de operar cada candidata, en hechos verificables."""
    candidatas = [m for m in medidas.values() if m.esfuerzo]
    if not candidatas:
        return "_(sin registrar)_"
    aspectos = list(candidatas[0].esfuerzo.keys())
    filas = [
        "| Aspecto | " + " | ".join(m.nombre for m in candidatas) + " |",
        "|---" * (len(candidatas) + 1) + "|",
    ]
    for aspecto in aspectos:
        celdas = " | ".join(m.esfuerzo.get(aspecto, "—") for m in candidatas)
        filas.append(f"| {aspecto} | {celdas} |")
    return "\n".join(filas)


def _tabla_prefiltrado(
    medidas: dict[str, Medida], caso: tuple[int, str, int] | None, preguntas: list[str]
) -> str:
    """Tabla de la comprobación de prefiltrado, con el caso real usado."""
    if caso is None:
        return (
            "_No se ha encontrado en el corpus ninguna consulta cuyos "
            "fragmentos filtrados queden todos fuera del top-K, así que la "
            "comprobación no se ha podido hacer._"
        )
    indice, grado, cuantos = caso
    filas = [
        f"**Caso real usado:** pregunta {indice} del conjunto de evaluación "
        f"—«{preguntas[indice]}»— filtrando por «{grado}», que tiene "
        f"**{cuantos} fragmentos** en el corpus y **ninguno** entre los "
        f"{K} primeros de esa consulta sin filtrar.",
        "",
        "Quien prefiltra devuelve los 10 pedidos; quien posfiltra devuelve 0, "
        "porque de los 10 más parecidos del corpus entero ninguno pasa el "
        "filtro.",
        "",
        "| Candidata | Devueltos | Pedidos | ¿Todos cumplen el filtro? | Veredicto |",
        "|---|---:|---:|---|---|",
    ]
    for m in medidas.values():
        if m.prefiltrado is None:
            continue
        devueltos, pedidos, correctos = m.prefiltrado
        veredicto = (
            "**prefiltra**"
            if devueltos == pedidos and correctos
            else "**posfiltra o pierde**"
        )
        filas.append(
            f"| {m.nombre} | {devueltos} | {pedidos} | "
            f"{'sí' if correctos else '**no**'} | {veredicto} |"
        )
    return "\n".join(filas)


def _seccion_cabecera(
    medidas: dict[str, Medida], chunks: list[Chunk], preguntas: list[str]
) -> list[str]:
    """Encabezado con la procedencia de las cifras y la tabla comparativa."""
    return [
        f"**Generado el {datetime.now():%Y-%m-%d} por "
        f"`scripts/experimento_vectordb.py`, sobre {len(chunks)} fragmentos y "
        f"{len(preguntas)} preguntas de `eval/preguntas_evaluacion.json`. "
        f"K = {K}, {REPETICIONES} repeticiones por pregunta para la latencia. "
        "Las cuatro condiciones reciben los mismos vectores, incrustados una "
        "sola vez.**",
        "",
        "### Tabla comparativa",
        "",
        _tabla_resumen(medidas),
        "",
    ]


def _seccion_filtrado(
    medidas: dict[str, Medida], discriminante: dict[str, tuple[int, int]]
) -> list[str]:
    """U2 y, justo detrás, el poder discriminante de cada uno de sus casos."""
    return [
        "### Filtrado por metadatos (U2)",
        "",
        _tabla_filtrado(medidas),
        "",
        "#### ¿Mide algo U2? Poder discriminante de cada caso",
        "",
        "Un umbral que se cumple igual con la implementación correcta y con la "
        "defectuosa no separa nada. Esta tabla compara la verdad de referencia "
        "(pertenencia exacta a la lista `grados`) con lo que devolvería la "
        "implementación defectuosa que este proyecto ya tuvo, la de comparar "
        "subcadenas:",
        "",
        _tabla_discriminante(discriminante),
        "",
    ]


def _seccion_prefiltrado(
    medidas: dict[str, Medida],
    caso_prefiltrado: tuple[int, str, int] | None,
    preguntas: list[str],
) -> list[str]:
    """La comprobación que ni U1 ni U2 cubren, con el caso real que la ejerce."""
    return [
        "### Prefiltrado frente a posfiltrado",
        "",
        "Ni U1 ni U2 lo detectan: U2 pide **todos** los fragmentos que cumplen "
        "el filtro, y sin un top-K que romper las dos estrategias dan el mismo "
        "resultado. Pero es la garantía que el recuperador de la Fase 2 "
        "necesita, porque posfiltrar es un **fallo silencioso**: el sistema "
        "devolvería una lista corta o vacía y respondería «no tengo "
        "información» sobre algo que sí está indexado.",
        "",
        _tabla_prefiltrado(medidas, caso_prefiltrado, preguntas),
        "",
    ]


def _seccion_esfuerzo(medidas: dict[str, Medida]) -> list[str]:
    """U7, el desempate, registrado en hechos verificables."""
    return [
        "### Esfuerzo de configuración (U7)",
        "",
        "U7 es un desempate y no una cifra, así que se registra en **hechos "
        "verificables** y no en opiniones sobre lo cómoda que resulta cada una:",
        "",
        _tabla_esfuerzo(medidas),
        "",
    ]


def _seccion_veredictos(
    medidas: dict[str, Medida], veredictos: dict[str, list[str]]
) -> list[str]:
    """Umbral a umbral por candidata, con sus notas de medición debajo."""
    partes = ["### Veredicto contra los umbrales U1-U5", ""]
    for nombre, lineas in veredictos.items():
        partes.append(f"**{nombre}**")
        for linea in lineas:
            partes.append(f"- {linea}")
        for nota in medidas[nombre].notas:
            partes.append(f"- Nota: {nota}")
        partes.append("")
    return partes


def _seccion_limitaciones(
    chunks: list[Chunk], normas: tuple[float, float, bool]
) -> list[str]:
    """Lo que las cifras NO permiten concluir, que es lo que las hace defendibles."""
    norma_min, norma_max, constantes = normas
    return [
        "### Lo que estas cifras NO permiten concluir",
        "",
        f"- **La métrica de distancia no es distinguible con este modelo.** Las "
        f"normas de los {len(chunks)} vectores del corpus van de "
        f"{norma_min:.6f} a {norma_max:.6f}"
        + (
            " —es decir, `e5-small` los entrega **normalizados**—, y para "
            "vectores de norma 1 se cumple `||a-b||² = 2 - 2·cos(a,b)`, así que "
            "el ranking por distancia euclídea y por similitud coseno es "
            "**idéntico por construcción**. Una fidelidad de 1,000 no demuestra, "
            "por tanto, que una candidata esté usando la métrica que se le pidió. "
            "Se declara la métrica en las tres de todos modos, porque esa "
            "equivalencia es una propiedad del modelo y no de la base: cambiar de "
            "modelo la rompería sin que fallara nada."
            if constantes
            else ", que no son constantes, de modo que euclídea y coseno sí "
            "pueden ordenar distinto."
        ),
        "- **La fidelidad no separa índice aproximado de recorrido completo.** "
        "Donde la columna «Modo» dice escaneo completo, un 1,000 significa «no "
        "perdió nada respecto de la fuerza bruta», **no** «su índice es fiel»: "
        "no llegó a usar índice. Y en ChromaDB el modo no se ha podido "
        "determinar desde el cliente.",
        "- **U6 (reproducibilidad a tres decimales) exige una segunda "
        "ejecución** y compararla con esta. Un solo pase no la comprueba.",
        "- **U7 (simplicidad) es un juicio de ingeniería**, no una cifra que "
        "este guion pueda calcular.",
        f"- **Las latencias son de una máquina concreta** (Ryzen 7 5800H, 16 GB, "
        f"PyTorch solo-CPU) que estaba haciendo otras cosas. Valen para "
        f"comparar las candidatas entre sí, no como cifras absolutas. Se "
        f"descartan las {CALENTAMIENTO} primeras consultas de cada candidata "
        f"para que la carga perezosa del índice no entre en la muestra.",
        "- **Las memorias no son homogéneas entre candidatas:** en ChromaDB y "
        "LanceDB es el delta de RSS del proceso; en Qdrant, el contenedor "
        "completo con su sistema base; en NumPy, el tamaño calculado de la "
        "matriz. Es el coste real de cada solución en este proyecto, no «la "
        "memoria del algoritmo».",
        "- **El orden de medición no se ha alternado** entre candidatas: se "
        "miden en el mismo orden en cada ejecución, así que un proceso pesado "
        "de fondo penalizaría siempre a la misma.",
        "",
    ]


def generar_bloque_resultados(
    medidas: dict[str, Medida],
    veredictos: dict[str, list[str]],
    chunks: list[Chunk],
    preguntas: list[str],
    normas: tuple[float, float, bool],
    discriminante: dict[str, tuple[int, int]],
    caso_prefiltrado: tuple[int, str, int] | None,
) -> str:
    """Compone el bloque de resultados brutos, listo para insertarse en el ADR.

    Solo ensambla las secciones en orden. El texto de cada una vive en su
    propia función, y las marcas de apertura y cierre son responsabilidad de
    esta: son las que permiten reescribir el bloque sin tocar el resto del ADR.
    """
    return "\n".join(
        [
            MARCA_INICIO,
            "",
            *_seccion_cabecera(medidas, chunks, preguntas),
            *_seccion_filtrado(medidas, discriminante),
            *_seccion_prefiltrado(medidas, caso_prefiltrado, preguntas),
            *_seccion_esfuerzo(medidas),
            *_seccion_veredictos(medidas, veredictos),
            *_seccion_limitaciones(chunks, normas),
            MARCA_FIN,
        ]
    )


def escribir_resultados(bloque: str) -> None:
    """Inserta o reemplaza el bloque de resultados dentro del ADR-0004.

    Si el ADR no existe todavía, crea el esqueleto mínimo con el bloque
    dentro: el resto (Contexto, Alternativas, Decisión, Consecuencias) es una
    decisión del autor y este guion no la redacta. Si ya existe, solo
    sustituye lo que hay entre las marcas, para no tocar nada escrito a mano.
    """
    if RUTA_ADR.exists():
        contenido = RUTA_ADR.read_text(encoding="utf-8")
        if MARCA_INICIO in contenido and MARCA_FIN in contenido:
            antes, resto = contenido.split(MARCA_INICIO, 1)
            _, despues = resto.split(MARCA_FIN, 1)
            nuevo = antes + bloque + despues
        else:
            nuevo = contenido.rstrip("\n") + "\n\n" + bloque + "\n"
    else:
        nuevo = ESQUELETO_ADR.format(fecha=f"{datetime.now():%Y-%m-%d}", bloque=bloque)
    RUTA_ADR.parent.mkdir(parents=True, exist_ok=True)
    RUTA_ADR.write_text(nuevo, encoding="utf-8")
    print(f"Resultados escritos en {RUTA_ADR}")


def main() -> None:
    """Ejecuta la comparativa completa y escribe los resultados."""
    print("Cargando corpus y preguntas...")
    chunks = cargar_corpus()
    preguntas = cargar_preguntas()
    print(f"  {len(chunks)} fragmentos · {len(preguntas)} preguntas")

    from tfg_uja.incrustaciones import (
        MODELO,
        incrustador_de_consultas,
        incrustador_de_documentos,
    )

    print(f"Incrustando el corpus una sola vez con {MODELO}...")
    vectores = np.asarray(
        incrustador_de_documentos()([c["texto"] for c in chunks]), dtype=np.float32
    )
    consultas = np.asarray(incrustador_de_consultas()(preguntas), dtype=np.float32)
    print(f"  corpus {vectores.shape} · consultas {consultas.shape}")

    print("Midiendo NumPy (línea base y referencia de fidelidad)...")
    medida_numpy, exactos = medir_numpy(vectores, consultas)
    medidas: dict[str, Medida] = {"NumPy": medida_numpy}

    print("Buscando un caso real que distinga prefiltrado de posfiltrado...")
    caso = elegir_caso_prefiltrado(vectores, consultas, chunks)
    if caso is None:
        print("  no hay ninguno en este corpus: la comprobación se omite")
    else:
        print(
            f"  pregunta {caso[0]} filtrando por «{caso[1]}» "
            f"({caso[2]} fragmentos, ninguno en el top-{K} sin filtrar)"
        )

    with carpeta_temporal() as carpeta_chroma:
        print("Midiendo ChromaDB...")
        medidas["ChromaDB"] = medir_chroma(
            chunks, vectores, consultas, exactos, carpeta_chroma / "indice", caso
        )

    with carpeta_temporal() as carpeta_lance:
        print("Midiendo LanceDB...")
        medidas["LanceDB"] = medir_lancedb(
            chunks, vectores, consultas, exactos, carpeta_lance / "indice", caso
        )

    print("Midiendo Qdrant (requiere el contenedor levantado)...")
    medidas["Qdrant"] = medir_qdrant(chunks, vectores, consultas, exactos, caso)

    print("Comprobando qué NO se puede concluir de las cifras...")
    normas = comprobar_normas(vectores)
    detalle_normas = (
        "constantes: euclídea y coseno ordenan igual" if normas[2] else "no constantes"
    )
    print(f"  normas del corpus: [{normas[0]:.6f}, {normas[1]:.6f}] · {detalle_normas}")
    discriminante = poder_discriminante_u2(chunks)
    for etiqueta, (exactos_u2, subcadena) in discriminante.items():
        veredicto = (
            f"discrimina ({subcadena - exactos_u2} falsos positivos)"
            if subcadena != exactos_u2
            else "NO discrimina: se cumple igual con el esquema defectuoso"
        )
        print(
            f"  U2 «{etiqueta}»: {exactos_u2} correctos, "
            f"{subcadena} por subcadena — {veredicto}"
        )

    print("Evaluando contra los umbrales U1-U5...")
    veredictos = evaluar_umbrales(medidas)
    for nombre, lineas in veredictos.items():
        print(f"\n{nombre}:")
        for linea in lineas:
            print(f"  {linea}")

    bloque = generar_bloque_resultados(
        medidas, veredictos, chunks, preguntas, normas, discriminante, caso
    )
    escribir_resultados(bloque)


if __name__ == "__main__":
    main()

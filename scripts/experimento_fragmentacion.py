"""Rejilla completa de estrategias de fragmentación sobre la colección (IT-16).

El ADR-0001 eligió el troceado **estructural por unidad semántica** frente a
tres alternativas, y descartó el **semántico por incrustaciones** por un motivo
de secuencia: exigía tener elegido el modelo de incrustaciones, que entonces
era una decisión pendiente. Ese motivo caducó al cerrarse el ADR-0003, así que
la alternativa se mide en vez de darse por descartada.

Por qué es una rejilla y no una comparación simple
--------------------------------------------------
Una primera versión de este guion barría el umbral de la estrategia semántica
y **congelaba** los parámetros de las otras dos en los valores que el proyecto
ya usaba. Eso le daba a la semántica once intentos y a las demás uno, de modo
que quedarse con su mejor resultado la favorecía aunque no hubiera diferencia
real: el máximo de once tiradas gana al de una por puro muestreo.

Aquí las tres compiten en igualdad: el **mismo eje de tamaño máximo** y el
**mismo número de configuraciones** cada una. Cada estrategia se presenta con
su mejor configuración, no con la que le tocaba por defecto.

Lo que sigue congelado, y hay que declararlo: el **mínimo** de fragmento, que
es una preferencia y no una restricción, y el conjunto de evaluación.

Diseño
------
La única variable que cambia entre estrategias es **dónde se proponen las
fronteras**. Todo lo demás ---construcción de unidades, deduplicación,
encabezados, dobles grados, planes de estudio y fusión de residuos--- lo aporta
el fragmentador real: el guion sustituye ``chunker._chunks_de_unidad`` y deja
que ``trocear_dataset`` haga el resto. Sin eso, cualquier diferencia medida
podría venir de otra parte del proceso.

- ``estructural``: la del ADR-0001. Corta por párrafos y, si hace falta, por
  frases. Su parámetro propio es el tamaño objetivo, como fracción del máximo.
- ``semantica``: corta entre dos piezas consecutivas cuando la distancia coseno
  entre sus incrustaciones supera un percentil de la distribución real de
  saltos del corpus. Su parámetro propio es ese percentil.
- ``fijo``: ventana de caracteres, ignorando el contenido. Su parámetro propio
  es el solape. Se mide también con solape **cero**, porque un solape duplica
  contenido y le regala oportunidades de ser recuperado.

Métricas
--------
La métrica principal es la **exhaustividad por unidad**: el conjunto de
evaluación anota unidades semánticas, no fragmentos. Aun así, tampoco es
inmune al troceo ---una unidad partida en más fragmentos ocupa más huecos del
top-K---, de modo que el informe recoge el número de fragmentos junto a cada
resultado para que la comparación no se lea sin ese dato delante.

La exhaustividad **por fragmento** se recoge junto a su techo, porque al
cambiar el troceo cambian el denominador de esa métrica y su máximo
alcanzable.

Uso
---
Requiere ``pip install -e ".[index]"`` y red la primera vez. Tarda del orden de
una hora: son 45 configuraciones y cada una reindexa la colección entera. Desde
la raíz del repositorio::

    py -u scripts/experimento_fragmentacion.py

Reescribe ``docs/experimentos/it16-fragmentacion.md``.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Final

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tfg_uja import chunker  # noqa: E402
from tfg_uja.chunker import (  # noqa: E402
    _dividir_en_piezas,
    _empaquetar,
    _fusionar_pequenos,
    trocear_dataset,
)
from tfg_uja.evaluacion import chunks_relevantes, evaluar_modelo  # noqa: E402
from tfg_uja.incrustaciones import (  # noqa: E402
    MODELO,
    PREFIJO_CONSULTA,
    PREFIJO_DOCUMENTO,
    con_prefijo,
)

RAIZ: Final[Path] = Path(__file__).resolve().parent.parent
RUTA_DATASET: Final[Path] = RAIZ / "data" / "grados.json"
RUTA_PREGUNTAS: Final[Path] = RAIZ / "eval" / "preguntas_evaluacion.json"
RUTA_SALIDA: Final[Path] = RAIZ / "docs" / "experimentos" / "it16-fragmentacion.md"

#: Valores de K sobre los que se informa. Conviene distinguir dos cosas que se
#: llaman igual: la K con la que se **mide** y la K con la que el sistema
#: **operará**. Medir es gratis, porque el orden se calcula una vez y cada K es
#: leerlo en un punto distinto.
#:
#: Los valores pequeños no sobran por exigentes, sino al contrario: con K
#: grande la exhaustividad por unidad se satura por encima de 0,99 y todas las
#: configuraciones empatan, de modo que el experimento no distinguiría nada.
#: **K=1 y K=3 son los que discriminan.** Los grandes dicen dónde se aplana la
#: curva, que es lo que hará falta en la Fase 2 para elegir la K de operación.
KS: Final[tuple[int, ...]] = (1, 3, 5, 10, 15)

#: Eje común de tamaño máximo de fragmento, en caracteres. Es el mismo para las
#: tres estrategias: es lo que hace que compitan en igualdad.
#:
#: El extremo superior está elegido a propósito por encima de lo que el modelo
#: puede leer. Con ventana de 510 *tokens*, 1.500 caracteres de español rondan
#: los 469 y caben; 1.800 no. Esa configuración debería degradarse por truncado
#: silencioso, y el informe cuenta los fragmentos truncados de cada una para
#: comprobar si ocurre en vez de darlo por supuesto.
MAXIMOS: Final[tuple[int, ...]] = (600, 900, 1200, 1500, 1800)

#: Tamaño objetivo de la estrategia estructural, como fracción del máximo.
RATIOS_OBJETIVO: Final[tuple[float, ...]] = (0.6, 0.8, 1.0)

#: Solape de la estrategia de tamaño fijo, como fracción de la ventana. El cero
#: entra a propósito: con solape, el contenido de las fronteras aparece en dos
#: fragmentos y se recupera con el doble de oportunidades.
RATIOS_SOLAPE: Final[tuple[float, ...]] = (0.0, 0.1, 0.2)

#: Percentiles de corte de la estrategia semántica. Un percentil alto corta
#: solo en los saltos más grandes y produce fragmentos largos.
PERCENTILES: Final[tuple[int, ...]] = (30, 50, 70)

#: Mínimo de fragmento. Se mantiene fijo en las tres estrategias: es una
#: preferencia de calidad, no una restricción dura, y barrerlo multiplicaría la
#: rejilla sin responder a la pregunta que se investiga.
MINIMO: Final[int] = 200

#: Incrustaciones de las piezas, cacheadas por texto. La misma pieza reaparece
#: en casi todas las configuraciones del barrido.
_CACHE: dict[str, np.ndarray] = {}

Incrustador = Callable[[list[str]], list[list[float]]]
Trozador = Callable[..., list[dict[str, Any]]]


def _incrustar_piezas(piezas: list[str], incrustar: Incrustador) -> np.ndarray:
    """Incrusta piezas de texto reutilizando la caché del módulo.

    Args:
        piezas: Textos a incrustar.
        incrustar: Función de incrustación del lado documento.

    Returns:
        np.ndarray: Matriz de vectores, una fila por pieza y en su orden.
    """
    faltan = [p for p in piezas if p not in _CACHE]
    if faltan:
        vectores = np.asarray(incrustar(faltan), dtype=np.float32)
        for texto, vector in zip(faltan, vectores):
            _CACHE[texto] = vector
    return np.stack([_CACHE[p] for p in piezas])


def _distancias_consecutivas(vectores: np.ndarray) -> list[float]:
    """Distancia coseno entre cada par de piezas consecutivas.

    Args:
        vectores: Matriz de incrustaciones, una fila por pieza.

    Returns:
        list[float]: ``len(vectores) - 1`` distancias, en orden.
    """
    normas = np.linalg.norm(vectores, axis=1)
    normas[normas == 0] = 1.0
    unitarios = vectores / normas[:, None]
    return [
        float(1.0 - np.dot(unitarios[i], unitarios[i + 1]))
        for i in range(len(unitarios) - 1)
    ]


def _construir_chunks(
    encabezado: str, cuerpos: list[str], base: dict[str, Any], origen: str
) -> list[dict[str, Any]]:
    """Envuelve unos cuerpos ya troceados en ítems ``chunk`` completos.

    Args:
        encabezado: Línea de contexto que encabeza cada fragmento.
        cuerpos: Textos de los fragmentos, sin encabezado.
        base: Campos comunes del ítem (grados, codigos, nombre).
        origen: Procedencia del contenido.

    Returns:
        list[dict]: Ítems de tipo ``chunk``.
    """
    return [
        {
            "tipo": "chunk",
            "origen": origen,
            **base,
            "texto": f"{encabezado}\n{cuerpo}".strip(),
            "chunk_index": indice,
            "total_chunks": len(cuerpos),
        }
        for indice, cuerpo in enumerate(cuerpos)
    ]


def hacer_semantico(umbral: float, incrustar: Incrustador) -> Trozador:
    """Sustituto de ``_chunks_de_unidad`` que corta por salto semántico.

    Args:
        umbral: Distancia coseno a partir de la cual se abre un fragmento.
        incrustar: Función de incrustación del lado documento.

    Returns:
        Trozador con la misma firma que ``chunker._chunks_de_unidad``.
    """

    def _semantico(
        encabezado: str,
        texto: str,
        base: dict[str, Any],
        origen: str,
        tamanos: tuple[int, int, int],
    ) -> list[dict[str, Any]]:
        _, tam_maximo, tam_minimo = tamanos
        maximo = max(tam_maximo - len(encabezado) - 1, 1)
        piezas = _dividir_en_piezas(texto, maximo)
        if not piezas:
            return []
        if len(piezas) == 1:
            cuerpos = list(piezas)
        else:
            distancias = _distancias_consecutivas(_incrustar_piezas(piezas, incrustar))
            grupos: list[list[str]] = [[piezas[0]]]
            for indice, pieza in enumerate(piezas[1:]):
                if distancias[indice] >= umbral:
                    grupos.append([pieza])
                else:
                    grupos[-1].append(pieza)
            cuerpos = []
            for grupo in grupos:
                unido = "\n".join(grupo)
                if len(unido) <= maximo:
                    cuerpos.append(unido)
                else:
                    cuerpos.extend(_empaquetar(grupo, maximo, maximo))
        cuerpos = _fusionar_pequenos(cuerpos, min(tam_minimo, maximo), maximo)
        return _construir_chunks(encabezado, cuerpos, base, origen)

    return _semantico


def hacer_fijo(ratio_solape: float) -> Trozador:
    """Sustituto que trocea por ventanas de tamaño fijo con solape.

    Ignora la estructura del texto: avanza contando caracteres. Sigue
    respetando la unidad, de modo que la comparación no le atribuya además el
    defecto de mezclar asignaturas, que el ADR-0001 documenta aparte.

    Args:
        ratio_solape: Solape como fracción de la ventana.

    Returns:
        Trozador con la misma firma que ``chunker._chunks_de_unidad``.
    """

    def _fijo(
        encabezado: str,
        texto: str,
        base: dict[str, Any],
        origen: str,
        tamanos: tuple[int, int, int],
    ) -> list[dict[str, Any]]:
        _, tam_maximo, _ = tamanos
        ventana = max(tam_maximo - len(encabezado) - 1, 1)
        paso = max(ventana - int(ventana * ratio_solape), 1)
        cuerpos = [
            texto[inicio : inicio + ventana].strip()
            for inicio in range(0, max(len(texto), 1), paso)
        ]
        cuerpos = [c for c in cuerpos if c]
        return _construir_chunks(encabezado, cuerpos or [texto], base, origen)

    return _fijo


def techo_por_fragmento(
    chunks: list[dict[str, Any]], preguntas: list[dict[str, Any]], k: int
) -> float:
    """Máximo alcanzable de exhaustividad por fragmento.

    Una unidad repartida en más de K fragmentos no cabe entera en el top-K, así
    que la métrica no puede llegar a 1. Ese máximo depende de la fragmentación
    y por eso se recalcula para cada configuración.

    Args:
        chunks: Fragmentos de la configuración evaluada.
        preguntas: Preguntas del conjunto de evaluación.
        k: Número de resultados que se miran.

    Returns:
        float: Media del máximo alcanzable sobre todas las preguntas.
    """
    valores = []
    for pregunta in preguntas:
        relevantes = chunks_relevantes(pregunta, chunks)
        valores.append(min(len(relevantes), k) / len(relevantes) if relevantes else 0.0)
    return sum(valores) / len(valores) if valores else 0.0


def _distancias_del_corpus(
    datos: list[dict[str, Any]],
    incrustar: Incrustador,
    original: Trozador,
    maximo: int,
) -> list[float]:
    """Reúne las distancias entre piezas consecutivas de todas las unidades.

    Se calculan **por unidad** y no sobre el corpus entero en fila, porque la
    frontera entre dos unidades distintas no es un salto semántico interno y
    contaminaría la distribución de la que sale el umbral. Y se recalculan por
    cada tamaño máximo, porque el máximo cambia cómo se parten las piezas.

    Args:
        datos: Colección completa del rastreador.
        incrustar: Función de incrustación del lado documento.
        original: Referencia a la ``_chunks_de_unidad`` real.
        maximo: Tamaño máximo de fragmento de esta configuración.

    Returns:
        list[float]: Todas las distancias internas del corpus.
    """
    distancias: list[float] = []

    def _espia(
        encabezado: str,
        texto: str,
        base: dict[str, Any],
        origen: str,
        tamanos: tuple[int, int, int],
    ) -> list[dict[str, Any]]:
        tope = max(tamanos[1] - len(encabezado) - 1, 1)
        piezas = _dividir_en_piezas(texto, tope)
        if len(piezas) > 1:
            distancias.extend(
                _distancias_consecutivas(_incrustar_piezas(piezas, incrustar))
            )
        return original(encabezado, texto, base, origen, tamanos)

    chunker._chunks_de_unidad = _espia  # type: ignore[assignment]
    try:
        trocear_dataset(datos, (maximo, maximo, MINIMO))
    finally:
        chunker._chunks_de_unidad = original  # type: ignore[assignment]
    return distancias


def _evaluar(
    chunks: list[dict[str, Any]],
    preguntas: list[dict[str, Any]],
    incrustar_doc: Incrustador,
    incrustar_con: Incrustador,
    tokenizar: Callable[[list[str]], list[int]],
    ventana: int,
) -> dict[str, Any]:
    """Evalúa una fragmentación concreta y reúne sus cifras.

    Args:
        chunks: Fragmentos de la configuración.
        preguntas: Conjunto de evaluación.
        incrustar_doc: Incrustador del lado documento.
        incrustar_con: Incrustador del lado consulta.
        tokenizar: Función que devuelve la longitud en tokens de cada texto.
        ventana: Tokens que el modelo llega a leer.

    Returns:
        dict: Métricas, tamaños y recuento de fragmentos truncados.
    """
    arranque = time.perf_counter()
    resultado = evaluar_modelo(chunks, preguntas, incrustar_doc, incrustar_con, ks=KS)
    agregados = resultado["agregados"]
    largos = [len(c["texto"]) for c in chunks]
    tokens = tokenizar([c["texto"] for c in chunks])
    return {
        "fragmentos": len(chunks),
        "mediana": int(np.median(largos)),
        "maximo_real": max(largos),
        "truncados": sum(1 for t in tokens if t > ventana),
        "segundos": time.perf_counter() - arranque,
        **{f"ru@{k}": agregados[f"recall_unidad@{k}"] for k in KS},
        **{f"r@{k}": agregados[f"recall@{k}"] for k in KS},
        **{f"techo@{k}": techo_por_fragmento(chunks, preguntas, k) for k in KS},
        "mrr": agregados["mrr"],
    }


def main() -> int:
    """Ejecuta la rejilla completa y escribe el informe.

    Returns:
        int: 0 si todo fue bien.
    """
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    datos = json.loads(RUTA_DATASET.read_text(encoding="utf-8"))
    crudo = json.loads(RUTA_PREGUNTAS.read_text(encoding="utf-8"))
    preguntas = crudo["preguntas"] if isinstance(crudo, dict) else crudo

    # Se carga el modelo aquí, y no con `incrustador_de_documentos`, por dos
    # razones: esa función lo cargaría una vez por cada papel y en esta máquina
    # eso son 2,5 GB innecesarios, y el experimento necesita el tokenizador
    # para contar truncados, que la interfaz pública no expone.
    from sentence_transformers import SentenceTransformer

    modelo = SentenceTransformer(MODELO)
    ventana = int(modelo.max_seq_length)

    def _incrustar(textos: list[str]) -> list[list[float]]:
        return modelo.encode(textos, show_progress_bar=False).tolist()

    def _tokenizar(textos: list[str]) -> list[int]:
        return [len(x) for x in modelo.tokenizer(textos)["input_ids"]]

    incrustar_doc = con_prefijo(PREFIJO_DOCUMENTO, _incrustar)
    incrustar_con = con_prefijo(PREFIJO_CONSULTA, _incrustar)
    original = chunker._chunks_de_unidad

    total = len(MAXIMOS) * (
        len(RATIOS_OBJETIVO) + len(RATIOS_SOLAPE) + len(PERCENTILES)
    )
    print(f"Colección: {len(datos)} ítems | preguntas: {len(preguntas)}")
    print(f"Modelo: {MODELO} | ventana: {ventana} tokens")
    print(f"Rejilla: {total} configuraciones\n", flush=True)

    filas: list[dict[str, Any]] = []
    hecho = 0
    for maximo in MAXIMOS:
        distancias = _distancias_del_corpus(datos, incrustar_doc, original, maximo)
        umbrales = {p: float(np.percentile(distancias, p)) for p in PERCENTILES}

        configuraciones: list[tuple[str, str, Trozador, tuple[int, int, int]]] = []
        for ratio in RATIOS_OBJETIVO:
            configuraciones.append(
                (
                    "estructural",
                    f"objetivo {ratio:.0%}",
                    original,
                    (int(maximo * ratio), maximo, MINIMO),
                )
            )
        for percentil in PERCENTILES:
            configuraciones.append(
                (
                    "semantica",
                    f"percentil {percentil}",
                    hacer_semantico(umbrales[percentil], incrustar_doc),
                    (maximo, maximo, MINIMO),
                )
            )
        for solape in RATIOS_SOLAPE:
            configuraciones.append(
                (
                    "fijo",
                    f"solape {solape:.0%}",
                    hacer_fijo(solape),
                    (maximo, maximo, MINIMO),
                )
            )

        for estrategia, ajuste, funcion, tamanos in configuraciones:
            chunker._chunks_de_unidad = funcion  # type: ignore[assignment]
            try:
                chunks = trocear_dataset(datos, tamanos)
            finally:
                chunker._chunks_de_unidad = original  # type: ignore[assignment]
            fila = {
                "estrategia": estrategia,
                "maximo": maximo,
                "ajuste": ajuste,
                **_evaluar(
                    chunks,
                    preguntas,
                    incrustar_doc,
                    incrustar_con,
                    _tokenizar,
                    ventana,
                ),
            }
            filas.append(fila)
            hecho += 1
            print(
                f"[{hecho:>2}/{total}] {estrategia:<12} max={maximo:<5} "
                f"{ajuste:<15} frag={fila['fragmentos']:>5} "
                f"RU@1={fila['ru@1']:.3f} RU@3={fila['ru@3']:.3f} "
                f"MRR={fila['mrr']:.3f} trunc={fila['truncados']:>4}",
                flush=True,
            )

    _escribir_informe(filas, len(preguntas), ventana)
    print(f"\nInforme escrito en {RUTA_SALIDA.relative_to(RAIZ)}")
    return 0


def _escribir_informe(
    filas: list[dict[str, Any]], n_preguntas: int, ventana: int
) -> None:
    """Vuelca la rejilla completa en un fichero Markdown.

    Args:
        filas: Una fila por configuración evaluada.
        n_preguntas: Tamaño del conjunto de evaluación.
        ventana: Tokens que el modelo llega a leer.
    """
    lineas = [
        "# IT-16 — Rejilla de estrategias de fragmentación",
        "",
        f"Generado el {date.today():%d/%m/%Y} con "
        "`py -u scripts/experimento_fragmentacion.py` sobre `data/grados.json`, "
        f"con {n_preguntas} preguntas de `eval/preguntas_evaluacion.json` y el "
        f"modelo `{MODELO}` (ventana de {ventana} tokens), en CPU.",
        "",
        f"**{len(filas)} configuraciones.** Las tres estrategias comparten el eje "
        "de tamaño máximo y tienen el mismo número de variantes de su parámetro "
        "propio, de modo que ninguna compite con más intentos que otra.",
        "",
        "| Estrategia | Máx. | Ajuste | Frag. | Mediana | "
        + " | ".join(f"RU@{k}" for k in KS)
        + " | R@5 / techo | MRR | Trunc. |",
        "|---|---:|---|---:|---:|" + "---:|" * (len(KS) + 3),
    ]
    for f in sorted(filas, key=lambda x: (-x["ru@1"], -x["mrr"])):
        lineas.append(
            f"| {f['estrategia']} | {f['maximo']} | {f['ajuste']} | "
            f"{f['fragmentos']} | {f['mediana']} | "
            + " | ".join(f"{f[f'ru@{k}']:.3f}" for k in KS)
            + f" | {f['r@5']:.3f} / {f['techo@5']:.3f} | {f['mrr']:.3f} "
            f"| {f['truncados']} |"
        )
    lineas += [
        "",
        "Ordenada por exhaustividad por unidad en el primer resultado, que es "
        "donde las configuraciones se distinguen: a partir de K=5 se saturan y "
        "empatan casi todas.",
        "",
        "## Cómo leer la tabla",
        "",
        "- **RU@K** es la exhaustividad por unidad: si se ha encontrado la "
        "asignatura correcta. Es la métrica principal porque el conjunto de "
        "evaluación anota unidades y no fragmentos. Aun así **no es inmune al "
        "troceo**: una unidad partida en más fragmentos ocupa más huecos del "
        "top-K, así que la columna **Frag.** hay que leerla al lado.",
        "- **R@5 / techo** es la exhaustividad por fragmento con su máximo "
        "alcanzable. Al cambiar el troceo cambian el denominador de esa "
        "métrica y su techo, de modo que la cifra suelta no es comparable "
        "entre configuraciones.",
        "- **Trunc.** son los fragmentos que superan la ventana del modelo y "
        "que `encode` recorta **en silencio**, sin avisar ni fallar. Es la "
        "comprobación directa de por qué el máximo de fragmento no puede "
        "subirse sin mirar.",
        "",
    ]
    RUTA_SALIDA.parent.mkdir(parents=True, exist_ok=True)
    RUTA_SALIDA.write_text("\n".join(lineas), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

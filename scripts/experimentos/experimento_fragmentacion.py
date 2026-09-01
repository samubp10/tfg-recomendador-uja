"""Rejilla completa de estrategias de fragmentación sobre la colección (IT-16).

Diseño
------
La única variable que cambia entre estrategias es **dónde se proponen las
fronteras**. Todo lo demás ---construcción de unidades, deduplicación,
encabezados, dobles grados, planes de estudio y fusión de residuos--- lo aporta
el fragmentador real: el guion sustituye ``chunker._chunks_de_unidad`` y deja
que ``trocear_dataset`` haga el resto. Sin eso, cualquier diferencia medida
podría venir de otra parte del proceso.

**Las tres pasan por la misma fusión de residuos** (:data:`MINIMO`), que es lo
que hace cierta esa frase: si una estrategia se la saltara, competiría con otro
pipeline y las diferencias medidas no serían solo de dónde corta.

- ``estructural``: la del ADR-0001. Corta por párrafos y, si hace falta, por
  frases. Su parámetro propio es el tamaño objetivo, como fracción del máximo.
- ``semantica``: corta entre dos piezas consecutivas cuando la distancia coseno
  entre sus incrustaciones supera un percentil de la distribución real de
  saltos del corpus. Su parámetro propio es ese percentil.
- ``fijo``: ventana de caracteres, ignorando el contenido. Su parámetro propio
  es el solape. Se mide también con solape **cero**, porque un solape duplica
  contenido y le regala oportunidades de ser recuperado.

Qué NO mide
-----------
Conviene tenerlo delante al leer el informe, porque son cosas que la tabla
podría sugerir y no sostiene:

- **No mide el coste de construir la fragmentación.** El campo
  ``segundos_evaluacion`` cronometra la evaluación y la tokenización, no el
  troceo ni las incrustaciones que la estrategia semántica necesita para
  decidir sus cortes. Esa estrategia es bastante más cara de construir que las
  otras dos, y ese coste no aparece en ninguna columna.
- **No mide la calidad del fragmento**, solo si se recupera. El ADR-0001 elige
  la estructural sobre la de longitud por un argumento de calidad que esta
  rejilla no puede sostener, y allí queda declarado.
- **El eje de la rejilla son caracteres y el límite del modelo son tokens.**
  La correspondencia depende del idioma y del texto, así que 1.500 caracteres
  no son un número fijo de tokens. Por eso el truncado se cuenta con el
  analizador léxico del modelo en vez de estimarse.

Uso
---
Requiere ``pip install -e ".[index]"`` y red la primera vez. Tarda del orden de
una hora: son 45 configuraciones y cada una reindexa la colección entera.
Ejecutar desde la raíz del repositorio y **con el entorno virtual activado**
---el ``py`` del sistema no tiene las dependencias---::

    source .venv/Scripts/activate
    python -u scripts/experimentos/experimento_fragmentacion.py

Reescribe el anexo del ADR-0001, entre sus marcas de resultados automáticos.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Final

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from tfg_uja.indexacion import chunker  # noqa: E402
from tfg_uja.indexacion.chunker import (  # noqa: E402
    _dividir_en_piezas,
    _empaquetar,
    _fusionar_pequenos,
    trocear_dataset,
)
from tfg_uja.indexacion.evaluacion import (  # noqa: E402
    chunks_relevantes,
    evaluar_modelo,
)
from tfg_uja.indexacion.incrustaciones import (  # noqa: E402
    MODELO,
    PREFIJO_CONSULTA,
    PREFIJO_DOCUMENTO,
    con_prefijo,
)

RAIZ: Final[Path] = Path(__file__).resolve().parent.parent.parent
RUTA_DATASET: Final[Path] = RAIZ / "data" / "grados.json"
RUTA_PREGUNTAS: Final[Path] = RAIZ / "eval" / "preguntas_evaluacion.json"
RUTA_SALIDA: Final[Path] = RAIZ / "docs" / "adr" / "adr-0001-estrategia-chunking.md"

# El ayudante que coloca el bloque dentro del ADR es el vecino de carpeta.
# `scripts/` no es un paquete importable, asi que se anade la carpeta propia al
# camino de busqueda, que es lo mismo que hace el interprete al ejecutar esto.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _adr  # noqa: E402

#: Marcas entre las que vive el bloque que escribe este guion. El resultado del
#: experimento va **dentro del ADR** y no en un fichero aparte: separarlos hizo
#: que el 14/08/2026 cuatro cifras del cuerpo del ADR-0001 contradijeran a su
#: propio anexo, porque una se refrescó y la otra no.
MARCA_INICIO: Final[str] = _adr.marca_inicio(
    "scripts/experimentos/experimento_fragmentacion.py"
)
MARCA_FIN: Final[str] = _adr.MARCA_FIN


def escribir_en_el_adr(bloque: str) -> None:
    """Sustituye el bloque de resultados del ADR por el recién calculado.

    Args:
        bloque: Texto que va entre las marcas, sin ellas.

    Raises:
        SystemExit: Si el ADR no existe o no tiene las dos marcas. Es
            preferible fallar a escribir el resultado donde nadie va a leerlo.
    """
    _adr.sustituir(
        RUTA_SALIDA,
        MARCA_INICIO,
        f"{MARCA_INICIO}\n{bloque.strip()}\n\n{MARCA_FIN}",
    )


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
#: puede leer. La ventana de `e5-small` son **512 tokens contando los dos
#: especiales** que añade el analizador léxico, así que el contenido dispone de
#: 510; 1.500 caracteres de español rondan los 469 y caben, 1.800 no. Esa
#: configuración debería degradarse por truncado silencioso, y el informe
#: cuenta los fragmentos truncados de cada una para comprobar si ocurre en vez
#: de darlo por supuesto. El recuento compara contra los 512 porque es el
#: límite que aplica ``encode``, y lo que cuenta el analizador incluye ya los
#: especiales.
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
#:
#: La clave es solo el texto, lo que da por supuesto que **el modelo y el
#: prefijo no cambian dentro de una ejecución**. Es cierto hoy: el guion carga
#: un modelo y usa siempre el prefijo de documento. Si algún día se barriera
#: también el modelo, la clave tendría que incluirlo o la caché devolvería
#: vectores de otro modelo sin que nada fallara.
_CACHE: dict[str, np.ndarray] = {}

Incrustador = Callable[[list[str]], list[list[float]]]
Trozador = Callable[..., list[dict[str, Any]]]
#: Función que devuelve la longitud en tokens de cada texto.
Tokenizador = Callable[[list[str]], list[int]]
#: Una configuración de la rejilla: estrategia, ajuste propio, trozador y la
#: terna de tamaños ``(objetivo, máximo, mínimo)`` con la que se ejecuta.
Configuracion = tuple[str, str, Trozador, tuple[int, int, int]]


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
        # strict=True: si el incrustador devolviera menos vectores que textos,
        # un zip normal truncaría en silencio y las piezas sobrantes se
        # quedarían fuera de la caché sin que nada fallara.
        for texto, vector in zip(faltan, vectores, strict=True):
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


def _trocear_con(
    funcion: Trozador, datos: list[dict[str, Any]], tamanos: tuple[int, int, int]
) -> list[dict[str, Any]]:
    """Trocea la colección sustituyendo el troceador de unidad del fragmentador.

    La sustitución se deshace en un ``finally`` porque el resto del guion
    ---y la propia estrategia semántica, que llama al troceador original---
    depende de que ``chunker`` quede como estaba: una configuración que
    fallara a medio troceo dejaría contaminadas todas las siguientes.

    Args:
        funcion: Troceador de unidad que se quiere probar.
        datos: Colección completa del rastreador.
        tamanos: Terna ``(objetivo, máximo, mínimo)``.

    Returns:
        list[dict]: Fragmentos de esa configuración.
    """
    original = chunker._chunks_de_unidad
    chunker._chunks_de_unidad = funcion  # type: ignore[assignment]
    try:
        return trocear_dataset(datos, tamanos)
    finally:
        chunker._chunks_de_unidad = original  # type: ignore[assignment]


def _agrupar_por_salto(
    piezas: list[str], distancias: list[float], umbral: float
) -> list[list[str]]:
    """Agrupa piezas consecutivas y abre grupo donde el salto supera el umbral.

    Args:
        piezas: Piezas de una unidad, en su orden.
        distancias: Distancia entre cada pieza y la siguiente.
        umbral: Distancia coseno a partir de la cual se abre un fragmento.

    Returns:
        list[list[str]]: Piezas agrupadas, sin unir todavía.
    """
    grupos: list[list[str]] = [[piezas[0]]]
    for indice, pieza in enumerate(piezas[1:]):
        if distancias[indice] >= umbral:
            grupos.append([pieza])
        else:
            grupos[-1].append(pieza)
    return grupos


def _unir_grupos(grupos: list[list[str]], maximo: int) -> list[str]:
    """Une cada grupo en un cuerpo, repartiendo el que no quepa en el máximo.

    Args:
        grupos: Piezas agrupadas por salto semántico.
        maximo: Tamaño máximo del cuerpo, ya descontado el encabezado.

    Returns:
        list[str]: Cuerpos de fragmento, ninguno por encima del máximo.
    """
    cuerpos: list[str] = []
    for grupo in grupos:
        unido = "\n".join(grupo)
        if len(unido) <= maximo:
            cuerpos.append(unido)
        else:
            cuerpos.extend(_empaquetar(grupo, maximo, maximo))
    return cuerpos


def hacer_semantico(umbral: float, incrustar: Incrustador) -> Trozador:
    """Sustituto de ``_chunks_de_unidad`` que corta por salto semántico.

    Dos precisiones sobre qué es exactamente esta estrategia, porque el nombre
    sugiere algo más ambicioso de lo que hace:

    - **La distancia se mide entre las piezas intermedias** que produce
      :func:`_dividir_en_piezas` (párrafos, y frases cuando un párrafo no
      cabe), no entre los fragmentos finales. Primero se parte en piezas, luego
      se miden los saltos entre piezas consecutivas, después se agrupan y por
      último se fusionan los residuos. La decisión de corte, por tanto, se toma
      sobre las piezas y no sobre lo que acaba indexándose.
    - **El umbral es global**, uno por cada tamaño máximo, y sale del percentil
      de la distribución de saltos de todo el corpus. No es adaptativo por
      titulación ni por asignatura. Lo que la rejilla compara es esa política
      concreta, no «el corte semántico» en abstracto.

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
            cuerpos = _unir_grupos(
                _agrupar_por_salto(piezas, distancias, umbral), maximo
            )
        cuerpos = _fusionar_pequenos(cuerpos, min(tam_minimo, maximo), maximo)
        return _construir_chunks(encabezado, cuerpos, base, origen)

    return _semantico


def hacer_fijo(ratio_solape: float) -> Trozador:
    """Sustituto que trocea por ventanas de tamaño fijo con solape.

    Ignora la estructura del texto: avanza contando caracteres. Sigue
    respetando la unidad, de modo que la comparación no le atribuya además el
    defecto de mezclar asignaturas, que el ADR-0001 documenta aparte.

    **Sí pasa por la fusión de residuos**, igual que las otras dos: la ventana
    fija deja casi siempre una cola corta al final de cada unidad, y no
    fusionarla sería medir esta estrategia con un pipeline distinto del de sus
    competidoras. Lo que se compara es dónde se ponen las fronteras, no quién
    limpia sus residuos.

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
        _, tam_maximo, tam_minimo = tamanos
        ventana = max(tam_maximo - len(encabezado) - 1, 1)
        paso = max(ventana - int(ventana * ratio_solape), 1)
        cuerpos = [
            texto[inicio : inicio + ventana].strip()
            for inicio in range(0, max(len(texto), 1), paso)
        ]
        cuerpos = [c for c in cuerpos if c]
        if cuerpos:
            cuerpos = _fusionar_pequenos(cuerpos, min(tam_minimo, ventana), ventana)
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

    _trocear_con(_espia, datos, (maximo, maximo, MINIMO))
    return distancias


def _configuraciones(
    maximo: int,
    umbrales: dict[int, float],
    estructural: Trozador,
    incrustar: Incrustador,
) -> list[Configuracion]:
    """Enumera las configuraciones que se prueban con un tamaño máximo dado.

    Las tres estrategias aportan el mismo número de variantes de su parámetro
    propio, para que ninguna compita con más intentos que otra.

    Args:
        maximo: Tamaño máximo de fragmento, en caracteres.
        umbrales: Umbral de corte semántico de cada percentil.
        estructural: La ``_chunks_de_unidad`` real, que es la estrategia del
            ADR-0001.
        incrustar: Función de incrustación del lado documento.

    Returns:
        list: Configuraciones a evaluar, en el orden en que se recorren.
    """
    configuraciones: list[Configuracion] = [
        (
            "estructural",
            f"objetivo {ratio:.0%}",
            estructural,
            (int(maximo * ratio), maximo, MINIMO),
        )
        for ratio in RATIOS_OBJETIVO
    ]
    configuraciones += [
        (
            "semantica",
            f"percentil {percentil}",
            hacer_semantico(umbrales[percentil], incrustar),
            (maximo, maximo, MINIMO),
        )
        for percentil in PERCENTILES
    ]
    configuraciones += [
        (
            "fijo",
            f"solape {solape:.0%}",
            hacer_fijo(solape),
            (maximo, maximo, MINIMO),
        )
        for solape in RATIOS_SOLAPE
    ]
    return configuraciones


def _evaluar(
    chunks: list[dict[str, Any]],
    preguntas: list[dict[str, Any]],
    incrustar_doc: Incrustador,
    incrustar_con: Incrustador,
    tokenizar: Tokenizador,
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
        "mediana": int(np.median(largos)) if largos else 0,
        "maximo_real": max(largos, default=0),
        "truncados": sum(1 for t in tokens if t > ventana),
        # El nombre lleva «evaluacion» a propósito: NO es el coste de la
        # estrategia. Deja fuera el troceo y, en la semántica, las
        # incrustaciones que necesita para decidir dónde cortar, que son lo más
        # caro de las tres. Llamarlo «segundos» invitaría a leer la columna
        # como si comparase el coste de las estrategias, y no lo hace.
        "segundos_evaluacion": time.perf_counter() - arranque,
        **{f"ru@{k}": agregados[f"recall_unidad@{k}"] for k in KS},
        **{f"r@{k}": agregados[f"recall@{k}"] for k in KS},
        **{f"techo@{k}": techo_por_fragmento(chunks, preguntas, k) for k in KS},
        "mrr": agregados["mrr"],
    }


def _cargar_entradas() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Lee la colección del rastreador y el conjunto de evaluación.

    Returns:
        Tupla ``(datos, preguntas)``.
    """
    datos = json.loads(RUTA_DATASET.read_text(encoding="utf-8"))
    crudo = json.loads(RUTA_PREGUNTAS.read_text(encoding="utf-8"))
    preguntas = crudo["preguntas"] if isinstance(crudo, dict) else crudo
    return datos, preguntas


def _cargar_modelo() -> tuple[Incrustador, Incrustador, Tokenizador, int]:
    """Carga el modelo del ADR-0003 y expone lo que la rejilla necesita de él.

    Se carga aquí, y no con ``incrustador_de_documentos``, por dos razones:
    esa función lo cargaría una vez por cada papel y en esta máquina eso son
    2,5 GB innecesarios, y el experimento necesita el tokenizador para contar
    truncados, que la interfaz pública no expone.

    Returns:
        Tupla ``(incrustar_doc, incrustar_con, tokenizar, ventana)``.
    """
    from sentence_transformers import SentenceTransformer

    modelo = SentenceTransformer(MODELO)

    def _incrustar(textos: list[str]) -> list[list[float]]:
        return modelo.encode(textos, show_progress_bar=False).tolist()

    def _tokenizar(textos: list[str]) -> list[int]:
        return [len(x) for x in modelo.tokenizer(textos)["input_ids"]]

    return (
        con_prefijo(PREFIJO_DOCUMENTO, _incrustar),
        con_prefijo(PREFIJO_CONSULTA, _incrustar),
        _tokenizar,
        int(modelo.max_seq_length),
    )


def _imprimir_avance(hecho: int, total: int, fila: dict[str, Any]) -> None:
    """Escribe una línea de progreso por configuración evaluada.

    Args:
        hecho: Configuraciones ya evaluadas, contando esta.
        total: Configuraciones de la rejilla.
        fila: Cifras de la configuración recién evaluada.
    """
    print(
        f"[{hecho:>2}/{total}] {fila['estrategia']:<12} max={fila['maximo']:<5} "
        f"{fila['ajuste']:<15} frag={fila['fragmentos']:>5} "
        f"RU@1={fila['ru@1']:.3f} RU@3={fila['ru@3']:.3f} "
        f"MRR={fila['mrr']:.3f} trunc={fila['truncados']:>4}",
        flush=True,
    )


def main() -> int:
    """Ejecuta la rejilla completa y escribe el informe.

    Returns:
        int: 0 si todo fue bien.
    """
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    datos, preguntas = _cargar_entradas()
    incrustar_doc, incrustar_con, tokenizar, ventana = _cargar_modelo()
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

        for estrategia, ajuste, funcion, tamanos in _configuraciones(
            maximo, umbrales, original, incrustar_doc
        ):
            chunks = _trocear_con(funcion, datos, tamanos)
            fila = {
                "estrategia": estrategia,
                "maximo": maximo,
                "ajuste": ajuste,
                **_evaluar(
                    chunks,
                    preguntas,
                    incrustar_doc,
                    incrustar_con,
                    tokenizar,
                    ventana,
                ),
            }
            filas.append(fila)
            hecho += 1
            _imprimir_avance(hecho, total, fila)

    _escribir_informe(filas, len(preguntas), ventana)
    print(f"\nAnexo de {RUTA_SALIDA.name} reescrito.")
    return 0


def _cabecera_del_informe(
    n_configuraciones: int, n_preguntas: int, ventana: int
) -> list[str]:
    """Redacta la procedencia de las cifras de la rejilla.

    Args:
        n_configuraciones: Configuraciones evaluadas.
        n_preguntas: Tamaño del conjunto de evaluación.
        ventana: Tokens que el modelo llega a leer.

    Returns:
        list[str]: Líneas de cabecera del informe.
    """
    return [
        f"Generado el {date.today():%d/%m/%Y} con "
        "`py -u scripts/experimentos/experimento_fragmentacion.py` sobre "
        "`data/grados.json`, "
        f"con {n_preguntas} preguntas de `eval/preguntas_evaluacion.json` y el "
        f"modelo `{MODELO}` (ventana de {ventana} tokens), en CPU.",
        "",
        f"**{n_configuraciones} configuraciones.** Las tres estrategias comparten "
        "el eje de tamaño máximo y tienen el mismo número de variantes de su "
        "parámetro propio, de modo que ninguna compite con más intentos que otra.",
        "",
    ]


def _tabla_del_informe(filas: list[dict[str, Any]]) -> list[str]:
    """Ordena la rejilla y le da formato de tabla Markdown.

    El orden no es neutral y por eso se explica en las notas: prioriza RU@1 y
    desempata por MRR, que es donde las configuraciones se distinguen.

    Args:
        filas: Una fila por configuración evaluada.

    Returns:
        list[str]: Encabezado, separador y una línea por configuración.
    """
    lineas = [
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
    return lineas


#: Notas que acompañan a la tabla. Son fijas: no dependen de lo que salga en la
#: ejecución, sino de qué se puede y qué no se puede leer en esas columnas.
_NOTAS: Final[tuple[str, ...]] = (
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
    "## Qué NO dice esta tabla",
    "",
    "- **No compara el coste de las estrategias.** Lo que se cronometra es "
    "la evaluación, no el troceo: construir la fragmentación semántica "
    "exige incrustar todas las piezas del corpus y es mucho más caro que "
    "las otras dos, y ese coste no aparece en ninguna columna.",
    "- **No mide la calidad del fragmento**, solo si se recupera. Un "
    "fragmento cortado a mitad de frase puede recuperarse igual de bien y "
    "servir peor como contexto para el modelo que redacta.",
    "- **El eje son caracteres; el límite del modelo son tokens.** La "
    "correspondencia depende del texto, así que las columnas de máximo no "
    "son una ventana fija en tokens. Por eso el truncado se cuenta con el "
    "analizador léxico del modelo y no se estima.",
    "- **El orden de la tabla no es neutral:** prioriza RU@1 y desempata "
    "por MRR. Se elige así porque es donde las configuraciones se "
    "distinguen, pero elegir una configuración por salir primera exige "
    "justificar que RU@1 es la prioridad correcta para el sistema final.",
    "",
)


def _escribir_informe(
    filas: list[dict[str, Any]], n_preguntas: int, ventana: int
) -> None:
    """Vuelca la rejilla completa en el anexo del ADR.

    El informe no lleva título propio: dentro del ADR ya lo encabeza su
    apartado, y repetirlo dejaría dos encabezados seguidos.

    Args:
        filas: Una fila por configuración evaluada.
        n_preguntas: Tamaño del conjunto de evaluación.
        ventana: Tokens que el modelo llega a leer.
    """
    lineas = [
        *_cabecera_del_informe(len(filas), n_preguntas, ventana),
        *_tabla_del_informe(filas),
        *_NOTAS,
    ]
    escribir_en_el_adr("\n".join(lineas))


if __name__ == "__main__":
    raise SystemExit(main())

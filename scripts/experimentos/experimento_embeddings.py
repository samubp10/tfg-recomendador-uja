"""Experimento comparativo de modelos de embeddings (IT-28).

Descarga (o reutiliza de caché) cada modelo candidato, incrusta el
``data/chunks.json`` real y el conjunto de evaluación de IT-27
(``eval/preguntas_evaluacion.json``), y calcula Recall@K por fragmento y por
unidad, más el MRR, sobre todas las preguntas anotadas. Imprime las tablas de
resultados y los deja también en el anexo del ADR-0003 para
no perder el resultado real de la ejecución.

El número de modelos, de preguntas y de fragmentos NO se escribe aquí a
propósito: son cifras que cambian y que el propio informe recoge de la
ejecución. Este módulo dice cómo se mide, no cuánto salió.

Necesita la dependencia opcional ``[index]`` (arrastra PyTorch) y red para
descargar los modelos la primera vez; por eso, igual que los verificadores del
dataset, se ejecuta SOLO en local y no en CI:

    py scripts/experimentos/experimento_embeddings.py
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Final

RAIZ = Path(__file__).resolve().parent.parent.parent
RUTA_CHUNKS = RAIZ / "data" / "chunks.json"
RUTA_EVAL = RAIZ / "eval" / "preguntas_evaluacion.json"
RUTA_RESULTADOS = RAIZ / "docs" / "adr" / "adr-0003-modelo-de-embeddings.md"

# El ayudante que coloca el bloque dentro del ADR es el vecino de carpeta.
# `scripts/` no es un paquete importable, asi que se anade la carpeta propia al
# camino de busqueda, que es lo mismo que hace el interprete al ejecutar esto.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _adr  # noqa: E402

#: Firma de la función de incrustación: recibe una lista de textos y devuelve
#: un vector de números reales por texto, en el mismo orden.
Incrustador = Callable[[list[str]], list[list[float]]]

#: Marcas entre las que vive el bloque que escribe este guion. Los resultados
#: viven **dentro del ADR** y no en un fichero aparte: tenerlos separados fue lo
#: que permitió que las cifras del cuerpo de un ADR se quedaran atrás respecto a
#: las de su propio anexo.
MARCA_INICIO = _adr.marca_inicio("scripts/experimentos/experimento_embeddings.py")
MARCA_FIN = _adr.MARCA_FIN


def escribir_en_el_adr(destino: Path, bloque: str) -> None:
    """Sustituye el bloque de resultados del ADR por el recién calculado.

    Args:
        destino: Fichero del ADR.
        bloque: Texto que va entre las marcas, sin ellas.

    Raises:
        SystemExit: Si el destino no existe o no tiene las dos marcas. Es
            preferible fallar a dejar el resultado donde nadie va a leerlo.
    """
    _adr.sustituir(
        destino, MARCA_INICIO, f"{MARCA_INICIO}\n{bloque.strip()}\n\n{MARCA_FIN}"
    )


#: Puntos de corte del ranking para Recall@K.
#:
#: Vienen de la Definición de Hecho de IT-28 («al menos K=3 y K=5») y hasta el
#: 01/08/2026 no estaban justificados en ninguna parte. La razón es el
#: presupuesto de contexto del LLM local: con una mediana real de 264 tokens por
#: fragmento, K=3 consume unos 790 tokens y K=5 unos 1.320, que caben de sobra
#: junto al prompt y la respuesta en un modelo cuantizado ejecutable en esta
#: máquina. No es un techo del modelo —los candidatos abiertos admiten de 32k
#: tokens en adelante— sino una elección de coste: cada fragmento de más es
#: tiempo de proceso del prompt y un distractor más para el generador.
#:
#: CUIDADO, son dos K distintos que hoy coinciden por casualidad:
#:   - el K de la MÉTRICA, que es este, y solo dice dónde se corta el ranking
#:     para medir;
#:   - el K del SISTEMA, cuántos fragmentos se meten de verdad en el prompt, que
#:     no está decidido y es parámetro del estudio de ablación (IT-49).
#: Si el segundo cambia, este debería seguirlo, o se estará midiendo una
#: configuración que el sistema no usa.
#: K=10 se añade en IT-100 para poder responder si conviene subir el corte. Con
#: la mediana de 264 tokens por fragmento son unos 2.640 tokens de contexto,
#: holgado para cualquier LLM local. Ojo al leerlo: Recall@K es MONÓTONO
#: creciente en K —mirar más resultados nunca puede reducir los aciertos—, así
#: que «K=10 gana a K=5» no es un hallazgo sino una propiedad de la métrica. Lo
#: que decide K es el coste, y se mide con métricas de generación (IT-38).
KS = (3, 5, 10)


@dataclass(frozen=True)
class ModeloCandidato:
    """Un modelo a comparar y cómo se le debe pedir que incruste texto."""

    nombre: str
    descripcion: str
    prefijo_consulta: str = ""
    prefijo_documento: str = ""
    #: Algunos modelos solo cargan si se les permite ejecutar código
    #: descargado del Hub. Se marca explícitamente porque es una decisión de
    #: confianza, no un detalle de configuración.
    codigo_remoto: bool = False


#: Tamaño de lote de incrustación.
#:
#: Se fija explícitamente en vez de dejar el de sentence-transformers (32)
#: porque en esta máquina la memoria es la restricción, no la velocidad: con
#: 16 GB de RAM y unos 3,5 GB realmente libres, un modelo de 560M parámetros y
#: lotes de 32 agota la memoria a mitad de la ejecución. Comprobado: la
#: ejecución del 04/08/2026 murió cargando multilingual-e5-large. Con lotes de
#: 8, ese mismo modelo termina dejando 2,3 GB libres en el pico.
TAMANO_LOTE: Final[int] = 8

#: Modelos a comparar.
#:
#: La selección original (IT-28) exigía un mínimo de 3, multilingües o
#: específicos de español y ninguno monolingüe inglés. Tenía un defecto que solo
#: se vio al medir: **dos de los cuatro candidatos no podían leer los fragmentos
#: del corpus**, porque sentence-transformers los sirve con una ventana de 128
#: tokens. Comparar un modelo que lee el 100 % con otro que lee el 50 % no es
#: comparar modelos.
#:
#: La selección actual resuelve eso **por construcción y no por parches**: los
#: cuatro candidatos tienen ventana >= 512 tokens, así que los cuatro leen el
#: corpus entero y compiten en las mismas condiciones. La columna «Corpus
#: leído» del informe es la comprobación, no una promesa.
#:
#: Criterios, en orden:
#:   1. Ventana >= 512 tokens, para que ninguno lea menos corpus que otro.
#:   2. Cuatro papeles distintos y complementarios, uno por candidato (abajo).
#:   3. Licencia permisiva compatible con la GPL-3.0 del repositorio.
#:      Verificadas el 04/08/2026 contra la API de Hugging Face, campo
#:      `cardData.license`, no leyendo las fichas a ojo.
#:   4. Ejecutable en ESTA máquina (Ryzen 7 5800H, 16 GB, PyTorch solo-CPU).
#:   5. Disponible en sentence-transformers sin código remoto.
#:
#: DESCARTADO por licencia: jinaai/jina-embeddings-v3 (570M, ventana 8192) es
#: CC-BY-NC-4.0, que prohíbe el uso comercial y es incompatible con la GPL-3.0.
#: Se deja escrito porque descartar por licencia es una decisión, no un olvido.
#:
#: DESCARTADO por código remoto: Alibaba-NLP/gte-multilingual-base (305M,
#: ventana 8192, Apache 2.0) exige `trust_remote_code=True`, es decir, ejecutar
#: código descargado del Hub dentro del entorno. Para un trabajo que se defiende
#: y se publica, esa cadena de suministro no compensa el beneficio marginal.
#:
#: DESCARTADO por inviable en esta máquina: Qwen/Qwen3-Embedding-0.6B (2025,
#: Apache 2.0, ventana 32k). Es un modelo decodificador y, medido el 04/08/2026,
#: no llegó a incrustar 100 fragmentos en diez minutos, frente a los ~10 min que
#: tardan los dos grandes en incrustar los 797. El criterio «ejecutable en esta
#: máquina» está en la lista desde IT-28: se aplica con una medición, no con una
#: impresión. Con GPU disponible sería un candidato a reconsiderar.
#:
#: RETIRADOS de la comparativa: los dos modelos *paraphrase* de ventana 128.
#: No desaparecen del trabajo —sus cifras y el hallazgo del truncado están en
#: el ADR-0003—, pero
#: mantenerlos aquí obligaba a comparar en la misma tabla modelos que leen la
#: mitad del corpus con modelos que lo leen entero, que es justo lo que esta
#: selección viene a evitar.
CANDIDATOS = [
    ModeloCandidato(
        "intfloat/multilingual-e5-small",
        "PEQUEÑO / titular. El elegido en el ADR-0003 y ganador de IT-28. "
        "Orientado a recuperación; exige prefijos 'query:'/'passage:' según su "
        "ficha, aplicados aquí. 118M parámetros, 384 dimensiones, MIT.",
        prefijo_consulta="query: ",
        prefijo_documento="passage: ",
    ),
    ModeloCandidato(
        "intfloat/multilingual-e5-large",
        "GRANDE 1. Misma familia, mismo entrenamiento y mismos prefijos que el "
        "titular, con 5x su tamaño: es el único par que aísla el efecto del "
        "TAMAÑO sin cambiar nada más. 560M, 1024 dimensiones, MIT.",
        prefijo_consulta="query: ",
        prefijo_documento="passage: ",
    ),
    ModeloCandidato(
        "BAAI/bge-m3",
        "GRANDE 2. Tamaño parecido al anterior pero otra arquitectura y otro "
        "entrenamiento, y sin prefijos: es el contraste de FAMILIA. Ventana de "
        "8192 tokens, así que no puede truncar. 568M, 1024 dimensiones, MIT.",
    ),
    ModeloCandidato(
        "hiiamsid/sentence_similarity_spanish_es",
        "ESPAÑOL. El mejor específico de español disponible: comprobado el "
        "04/08/2026, es el único con uso real (22.500 descargas/mes) frente a "
        "derivados con decenas. Entrenado para similitud semántica y no para "
        "recuperación, que es la hipótesis que pone a prueba. 110M, Apache 2.0.",
    ),
]


def techos_de_recall(
    preguntas: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> dict[int, float]:
    """Calcula el máximo alcanzable de Recall@K por fragmento, para cada K.

    Recall@K por fragmento **no tiene techo 1**. Una pregunta cuya unidad
    relevante está repartida en 11 fragmentos no puede aportar más de 3/11 con
    K=3, por perfecto que sea el modelo. Sin este dato, la tabla invita a
    interpretar un 0,83 como «falla en uno de cada seis», cuando la distancia
    real al máximo posible es mucho menor.

    Se calcula aquí y no se escribe a mano en el informe porque **ya se quedó
    obsoleto una vez**: el techo de R@3 era 0,868 con las 36 preguntas de IT-27
    y pasó a 0,905 con las 50 actuales. Una cifra escrita a mano en un texto
    envejece en silencio; una calculada, no.

    Args:
        preguntas: Preguntas del conjunto de evaluación.
        chunks: Corpus sobre el que se resuelven los selectores.

    Returns:
        Diccionario ``{K: techo}``.
    """
    from tfg_uja.indexacion.evaluacion import chunks_relevantes

    cuantos = [len(chunks_relevantes(p, chunks)) for p in preguntas]
    return {k: sum(min(k, n) / n for n in cuantos if n) / len(cuantos) for k in KS}


def cargar_datos(
    ruta_chunks: Path = RUTA_CHUNKS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Carga los chunks reales y las preguntas del conjunto de evaluación.

    El ``chunks.json`` encabeza la lista con un item ``procedencia`` (IT-90)
    que describe el corpus pero no es contenido recuperable: se descarta
    filtrando por ``tipo``, porque incrustarlo falsearía las métricas.

    Args:
        ruta_chunks: Corpus a evaluar. Es parámetro para poder medir el mismo
            conjunto de preguntas sobre un troceado distinto sin tocar el
            corpus real. Sirvió para la rejilla de IT-16, que fijó los tamaños
            de fragmento en 900/900, y sigue haciendo falta para volver a
            medirlos si la fuente cambia.

    Returns:
        Tupla ``(chunks, preguntas)``.
    """
    items = json.loads(ruta_chunks.read_text(encoding="utf-8"))
    chunks = [i for i in items if i.get("tipo") == "chunk"]
    preguntas = json.loads(RUTA_EVAL.read_text(encoding="utf-8"))["preguntas"]
    return chunks, preguntas


def crear_incrustadores(
    candidato: ModeloCandidato,
) -> tuple[Incrustador, Incrustador, Any]:
    """Construye las funciones de incrustación (documento y consulta) del modelo.

    Devuelve también el modelo cargado porque hace falta para medir la
    ventana de contexto y el truncado: sin eso, la tabla compararía modelos
    sin decir cuánto texto ha leído cada uno.

    Args:
        candidato: Modelo a cargar.

    Returns:
        Tupla ``(incrustar_chunks, incrustar_preguntas, modelo)``.
    """
    from sentence_transformers import SentenceTransformer

    modelo = SentenceTransformer(
        candidato.nombre, trust_remote_code=candidato.codigo_remoto
    )

    def incrustador_con(prefijo: str) -> Incrustador:
        """Incrustador que antepone el prefijo del papel que le toca."""

        def incrustar(textos: list[str]) -> list[list[float]]:
            return modelo.encode(
                [prefijo + texto for texto in textos],
                batch_size=TAMANO_LOTE,
                show_progress_bar=False,
            ).tolist()

        return incrustar

    return (
        incrustador_con(candidato.prefijo_documento),
        incrustador_con(candidato.prefijo_consulta),
        modelo,
    )


def medir_truncado(
    modelo: Any, textos: list[str], prefijo: str
) -> tuple[int, int, float]:
    """Mide cuánto del corpus cabe en la ventana de contexto del modelo.

    ``SentenceTransformer.encode`` recorta en silencio todo lo que pase de
    ``max_seq_length``: no avisa, no falla y devuelve un vector de aspecto
    normal. Un modelo puede quedar por debajo de otro simplemente porque no
    ha llegado a leer la mitad del fragmento, y sin esta medida la tabla de
    resultados no permite distinguir las dos cosas.

    Se descuentan dos posiciones de la ventana, que son los tokens
    especiales que el propio modelo añade al principio y al final.

    Args:
        modelo: ``SentenceTransformer`` ya cargado.
        textos: Fragmentos del corpus, tal como se van a incrustar.
        prefijo: Prefijo que el modelo exige para los documentos (cuenta
            como tokens, así que se incluye en la medida).

    Returns:
        Tupla ``(ventana_util, fragmentos_truncados, fraccion_leida)``, donde
        la fracción es la proporción de tokens del corpus que el modelo
        llega a mirar.
    """
    ventana = int(modelo.max_seq_length) - 2
    largos = [
        len(modelo.tokenizer.encode(prefijo + t, add_special_tokens=False))
        for t in textos
    ]
    # Un corpus vacío no es un corpus con truncado 0: es un corpus del que no
    # hay nada que decir. Sin esta salida, la división de abajo revienta y el
    # modelo entero se contabilizaría como fallido.
    if not sum(largos):
        return ventana, 0, 0.0
    truncados = sum(1 for n in largos if n > ventana)
    leidos = sum(min(ventana, n) for n in largos)
    return ventana, truncados, leidos / sum(largos)


def _dispositivo() -> str:
    """Describe dónde se está ejecutando el experimento.

    Va en la cabecera del informe porque los tiempos de la tabla no se pueden
    comparar entre ejecuciones si el dispositivo cambia, y porque una tabla que
    no dice en qué se midió invita a compararla con cualquier otra.

    Returns:
        Descripción legible del dispositivo (GPU concreta o CPU).
    """
    import torch

    if torch.cuda.is_available():
        return f"GPU ({torch.cuda.get_device_name(0)})"
    return "CPU"


def _tabla_markdown(columnas: list[str], celdas: list[list[str]]) -> str:
    """Compone una tabla Markdown a partir de sus rótulos y sus celdas.

    Args:
        columnas: Rótulos de la fila de encabezado.
        celdas: Valores ya formateados, una lista por fila.

    Returns:
        Tabla Markdown, sin salto de línea final.
    """
    lineas = [
        "| " + " | ".join(columnas) + " |",
        "|" + "---|" * len(columnas),
    ]
    lineas += ["| " + " | ".join(fila) + " |" for fila in celdas]
    return "\n".join(lineas)


def _celdas_de_contexto(fila: dict[str, Any]) -> list[str]:
    """Escribe las tres columnas de ventana, truncado y corpus leído.

    Las tres pueden faltar: la medida del truncado se hace aparte de la
    evaluación, y si falla el modelo sigue teniendo métricas válidas. Se
    escribe «sin medir» y no un cero, porque un cero en la columna de
    truncados dice «este modelo lee el corpus entero», que es justo lo que no
    se sabe.

    Args:
        fila: Fila de resultados de un modelo.

    Returns:
        Las tres celdas, ya formateadas.
    """
    sin_medir = "sin medir"
    return [
        sin_medir if fila["ventana"] is None else str(fila["ventana"]),
        sin_medir if fila["truncados"] is None else str(fila["truncados"]),
        (
            sin_medir
            if fila["fraccion_leida"] is None
            else f"{fila['fraccion_leida']:.0%}"
        ),
    ]


def formatear_tabla(filas: list[dict[str, Any]]) -> str:
    """Da formato Markdown a los resultados agregados por modelo.

    Args:
        filas: Una fila por modelo, con sus métricas agregadas, el tiempo de
            ejecución y las cifras de truncado.

    Returns:
        Tabla Markdown lista para pegar en la memoria o en un documento.
    """
    metricas = [f"recall@{k}" for k in KS] + [f"recall_unidad@{k}" for k in KS]
    columnas = (
        ["Modelo"]
        + [f"R@{k}" for k in KS]
        + [f"RU@{k}" for k in KS]
        + ["MRR", "Tiempo (s)", "Ventana", "Truncados", "Corpus leído"]
    )
    celdas = [
        [fila["nombre"]]
        + [f"{fila[m]:.3f}" for m in metricas]
        + [f"{fila['mrr']:.3f}", f"{fila['tiempo_s']:.1f}"]
        + _celdas_de_contexto(fila)
        for fila in filas
    ]
    return _tabla_markdown(columnas, celdas)


def formatear_por_tipo(filas: list[dict[str, Any]]) -> str:
    """Tabla de Recall@5 por tipo de pregunta, para el mejor modelo de cada fila.

    La media general deja de ser interpretable en cuanto conviven tipos con
    techos muy distintos: una pregunta de listado tiene un techo de Recall@5
    de 0,042 por su propia naturaleza, así que arrastra la media sin que el
    sistema haya empeorado en nada. Verlo desglosado es lo que evita leer un
    número peor como un sistema peor.

    Args:
        filas: Una fila por modelo, con su diccionario ``por_tipo``.

    Returns:
        Tabla Markdown con una columna por tipo de pregunta.
    """
    tipos = sorted({t for f in filas for t in f["por_tipo"]})
    columnas = ["Modelo"] + [
        f"{t} (n={int(filas[0]['por_tipo'][t]['n'])})" for t in tipos
    ]
    celdas = [
        [fila["nombre"]] + [f"{fila['por_tipo'][t]['recall@5']:.3f}" for t in tipos]
        for fila in filas
    ]
    return _tabla_markdown(columnas, celdas)


def _evaluar_candidato(
    candidato: ModeloCandidato,
    chunks: list[dict[str, Any]],
    preguntas: list[dict[str, Any]],
    evaluar: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:
    """Carga un modelo, lo evalúa y mide cuánto corpus llega a leer.

    Args:
        candidato: Modelo a evaluar.
        chunks: Corpus a incrustar.
        preguntas: Conjunto de evaluación.
        evaluar: ``tfg_uja.evaluacion.evaluar_modelo``, ya importada por quien
            llama: así el fallo de importación salta antes de tocar la red y
            no se confunde con un modelo que no ha podido descargarse.

    Returns:
        Tupla ``(fila, aviso)``. El aviso es ``None`` salvo que el modelo se
        haya evaluado sin poder medir su ventana de contexto.

    Raises:
        Exception: Lo que falle al cargar el modelo o al evaluarlo. Quien
            llama decide si sigue con el resto de candidatos.
    """
    inicio = time.monotonic()
    ventana: int | None = None
    truncados: int | None = None
    fraccion: float | None = None
    aviso: str | None = None
    try:
        incrustar_doc, incrustar_consulta, modelo = crear_incrustadores(candidato)
        resultado = evaluar(chunks, preguntas, incrustar_doc, incrustar_consulta, ks=KS)
        # El cronómetro se para ANTES de medir el truncado: esa medida
        # tokeniza el corpus una vez más y añadía 16 s a la línea base,
        # con lo que la columna de tiempo dejaba de ser comparable con la
        # ejecución del 24/07. Se mide lo mismo que se medía entonces:
        # cargar el modelo, incrustar el corpus y evaluar.
        tiempo = time.monotonic() - inicio
        # La medida de la ventana va en su propio `try`, y no por prudencia
        # decorativa: estaba dentro del grande, así que un fallo al
        # tokenizar ---un modelo que sirve su tokenizador de otra manera---
        # tiraba a la basura unas métricas que YA se habían calculado bien y
        # declaraba el modelo como no evaluado. Son dos cosas distintas: no
        # haber podido evaluar un modelo, y haberlo evaluado sin saber
        # cuánto corpus llegó a leer. La segunda se dice, no se disfraza de
        # la primera ni se rellena con un número inventado.
        try:
            ventana, truncados, fraccion = medir_truncado(
                modelo,
                [c["texto"] for c in chunks],
                candidato.prefijo_documento,
            )
        except Exception as error:  # noqa: BLE001 - la evaluación sí vale
            print(f"  AVISO: no se ha podido medir la ventana: {error}")
            aviso = (
                f"{candidato.nombre}: evaluado, pero sin poder medir su "
                f"ventana de contexto ni el truncado ({error}). Sus "
                f"métricas no se pueden comparar con las de otro modelo "
                f"sin saber cuánto corpus ha leído cada uno."
            )
    finally:
        # Soltar el modelo ANTES de cargar el siguiente. Sin esto, dos
        # modelos de 560M coincidían en memoria durante la carga del
        # segundo y la ejecución moría por falta de RAM, no por un error
        # del código. Va en `finally` para que también se suelte cuando el
        # modelo ha fallado a medio cargar, que es justo el momento en el
        # que menos memoria queda.
        #
        # Hay que soltar las TRES referencias: las dos funciones de
        # incrustación son cierres que capturan el modelo, así que anular
        # solo `modelo` no liberaría ni un byte.
        # El `type: ignore` es la contrapartida de soltar el modelo: las
        # tres variables se anotaron con el tipo que tienen mientras se
        # usan, y aqui se anulan a proposito para que el recolector pueda
        # llevarselas. Sin el, `mypy scripts/` arrastra un error conocido
        # y deja de mirarse.
        incrustar_doc = incrustar_consulta = modelo = None  # type: ignore[assignment] # noqa: F841,E501
        gc.collect()
    fila = {
        "nombre": candidato.nombre,
        "tiempo_s": tiempo,
        "ventana": ventana,
        "truncados": truncados,
        "fraccion_leida": fraccion,
        "por_tipo": resultado["por_tipo"],
        **resultado["agregados"],
    }
    return fila, aviso


def _imprimir_resultado(fila: dict[str, Any], total_chunks: int) -> None:
    """Escribe por consola lo que ha salido de un modelo.

    Args:
        fila: Fila de resultados del modelo.
        total_chunks: Fragmentos del corpus, para leer el truncado en
            proporción y no como un número suelto.
    """
    print(
        f"  fragmento R@3={fila['recall@3']:.3f} R@5={fila['recall@5']:.3f} "
        f"R@10={fila['recall@10']:.3f}"
    )
    print(
        f"  unidad     R@3={fila['recall_unidad@3']:.3f} "
        f"R@5={fila['recall_unidad@5']:.3f} "
        f"R@10={fila['recall_unidad@10']:.3f}  "
        f"MRR={fila['mrr']:.3f}  ({fila['tiempo_s']:.1f}s)"
    )
    if fila["truncados"]:
        print(
            f"  AVISO: ventana de {fila['ventana']} tokens; {fila['truncados']} de "
            f"{total_chunks} fragmentos se truncan; el modelo llega a leer "
            f"el {fila['fraccion_leida']:.2%} de los tokens del corpus."
        )


def _texto_de_techos(techos: dict[int, float]) -> str:
    """Redacta los techos de Recall@K en una frase reutilizable.

    La misma frase va por consola y dentro del informe: si se escribieran por
    separado, una de las dos podría quedarse con cifras viejas.

    Args:
        techos: Diccionario ``{K: techo}``.

    Returns:
        Frase con los techos de cada K.
    """
    return (
        "sobre este corpus el máximo posible es "
        + ", ".join(f"**{v:.3f}** para R@{k}" for k, v in sorted(techos.items()))
        + "."
    )


def _cabecera_del_informe(
    ruta_chunks: Path, total_chunks: int, total_preguntas: int
) -> str:
    """Escribe la procedencia de las cifras: corpus, preguntas y dispositivo.

    Args:
        ruta_chunks: Corpus que se ha evaluado.
        total_chunks: Fragmentos evaluados.
        total_preguntas: Preguntas del conjunto de evaluación.

    Returns:
        Párrafo de cabecera del informe.
    """
    # Ruta relativa a la raíz del repositorio: la absoluta lleva el nombre de
    # usuario de quien lo ejecuta y además no significa nada para quien lea el
    # informe en otra máquina.
    try:
        corpus = ruta_chunks.resolve().relative_to(RAIZ).as_posix()
    except ValueError:
        corpus = ruta_chunks.name
    return (
        f"Generado el {date.today():%d/%m/%Y} ejecutando "
        f"`py scripts/experimentos/experimento_embeddings.py` contra `{corpus}` "
        f"({total_chunks} fragmentos, {total_preguntas} preguntas de "
        f"`eval/preguntas_evaluacion.json`), en **{_dispositivo()}**.\n\n"
    )


def _pie_del_informe(
    tabla_por_tipo: str, techos_texto: str, fallos: list[str], avisos: list[str]
) -> str:
    """Escribe el desglose por tipo, cómo leer las columnas y las incidencias.

    Args:
        tabla_por_tipo: Tabla de Recall@5 por tipo de pregunta.
        techos_texto: Frase de :func:`_texto_de_techos`.
        fallos: Modelos que no han podido evaluarse.
        avisos: Modelos evaluados sin poder medir su ventana.

    Returns:
        Texto que va debajo de la tabla principal.
    """
    pie_md = (
        "\n\n### Recall@5 por tipo de pregunta\n\n" + tabla_por_tipo + "\n\n"
        "La media general no se puede leer sin este desglose. Las preguntas de "
        "tipo `listado` piden **todas** las asignaturas de un grupo, así que su "
        "techo depende de cuántas unidades relevantes tengan y no de lo bien "
        "que recupere el modelo.\n"
        "\n### Cómo leer las columnas\n\n"
        "- **R@K** es Recall@K por **fragmento**: cuántos de los trozos de la "
        "unidad correcta se han recuperado. Mide cobertura. **Su techo no es "
        "1**, porque una unidad repartida en más de K fragmentos no cabe "
        "entera en el top-K: " + techos_texto + " Hay que restar del techo, no "
        "de 1, para saber lo que falta de verdad.\n"
        "- **RU@K** es Recall@K por **unidad**: si se ha encontrado la "
        "asignatura correcta, sin castigar que falte alguno de sus trozos. "
        "Mide acierto, y su techo sí es 1.\n"
        "- Las dos van juntas a propósito. La primera describe el sistema tal "
        "como está hoy; la segunda, el sistema con expansión por unidad, que "
        "todavía no existe. **La brecha entre ambas es el dato**: dice si lo "
        "que falla es encontrar la asignatura o completarla.\n"
        "- **Ventana** es el `max_seq_length` con el que sentence-transformers "
        "sirve el modelo, descontados los dos tokens especiales. Todo lo que "
        "pase de ahí, `encode` lo recorta **en silencio**: no avisa, no falla "
        "y devuelve un vector de aspecto normal. Por eso una diferencia de "
        "Recall entre modelos de ventana distinta no se puede atribuir solo a "
        "la calidad de sus representaciones.\n"
        "- **Tiempo** es reloj de pared de un portátil que está haciendo otras "
        "cosas, así que solo separa órdenes de magnitud. Medido: entre dos "
        "ejecuciones seguidas del 04/08/2026 **todas las métricas salieron "
        "idénticas a tres decimales**, pero los tiempos variaron hasta un 25 % "
        "y los dos modelos grandes llegaron a intercambiarse el orden. Sirve "
        "para decir «este tarda cinco veces más que aquel», no para ordenar "
        "dos modelos que quedan cerca.\n"
        "\n⚠️ Recall@K es **monótono creciente en K**: mirar más resultados no "
        "puede reducir los aciertos. Que K=10 gane a K=5 es una propiedad de "
        "la métrica, no un hallazgo. Lo que decide K es el coste de contexto y "
        "la distracción del generador, y eso se mide en la Fase 2.\n"
    )
    pie_md += "\n### Modelos evaluados\n\n" + "\n".join(
        f"- `{c.nombre}`: {c.descripcion}" for c in CANDIDATOS
    )
    if fallos:
        pie_md += "\n\n### Fallos\n\n" + "\n".join(f"- {f}" for f in fallos)
    if avisos:
        pie_md += (
            "\n\n### Modelos evaluados sin caracterizar\n\n"
            + "\n".join(f"- {a}" for a in avisos)
            + "\n\nSus métricas son válidas, pero **no son comparables** con "
            "las de los demás mientras no se sepa cuánto corpus lee cada uno.\n"
        )
    return pie_md


def main(argumentos: list[str] | None = None) -> int:
    """Ejecuta el experimento completo y muestra/guarda los resultados.

    Uso::

        py scripts/experimentos/experimento_embeddings.py
        py scripts/experimentos/experimento_embeddings.py --chunks otro_corpus.json \\
            --salida docs/adr/adr-0003-modelo-de-embeddings.md

    Args:
        argumentos: Argumentos de línea de comandos. ``None`` toma los reales.

    Returns:
        0 solo si todos los modelos se evaluaron **y** se caracterizaron; 1 si
        alguno falló (p. ej. por no poder descargarse) y también si alguno se
        evaluó sin poder medir cuánto corpus lee. Lo segundo no invalida sus
        métricas, pero sí la comparación, que es para lo que existe la tabla:
        sin la columna de truncado no se puede separar «mejor modelo» de
        «modelo que sí lee el fragmento entero», que es exactamente el hallazgo
        de IT-29 que obligó a rehacer esta comparativa.
    """
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--chunks", type=Path, default=RUTA_CHUNKS)
    analizador.add_argument("--salida", type=Path, default=RUTA_RESULTADOS)
    opciones = analizador.parse_args(argumentos)

    # Import perezoso: solo evaluar_modelo, no crear_incrustadores, para dar
    # un error claro y rápido si faltan los chunks/eval antes de tocar red.
    from tfg_uja.indexacion.evaluacion import evaluar_modelo

    chunks, preguntas = cargar_datos(opciones.chunks)
    print(
        f"Corpus: {opciones.chunks} | Chunks: {len(chunks)} | "
        f"Preguntas: {len(preguntas)}\n"
    )

    filas: list[dict[str, Any]] = []
    fallos: list[str] = []
    #: Modelos que sí se han evaluado pero de los que falta alguna medida de
    #: contexto. No invalidan su fila, pero sí lo que se puede concluir de ella.
    avisos: list[str] = []
    for candidato in CANDIDATOS:
        print(f"Evaluando {candidato.nombre} ({candidato.descripcion}) ...")
        try:
            fila, aviso = _evaluar_candidato(
                candidato, chunks, preguntas, evaluar_modelo
            )
        except Exception as error:  # noqa: BLE001 - se informa y se sigue con el resto
            print(f"  FALLÓ: {error}")
            fallos.append(f"{candidato.nombre}: {error}")
            continue
        if aviso:
            avisos.append(aviso)
        filas.append(fila)
        _imprimir_resultado(fila, len(chunks))

    if not filas:
        print("\nNingún modelo pudo evaluarse.")
        return 1

    tabla = formatear_tabla(filas)
    print("\n" + tabla)
    por_tipo = formatear_por_tipo(filas)
    print("\nRecall@5 por tipo de pregunta:\n" + por_tipo)

    techos_texto = _texto_de_techos(techos_de_recall(preguntas, chunks))
    print("\nTechos de Recall@K por fragmento: " + techos_texto)

    opciones.salida.parent.mkdir(parents=True, exist_ok=True)
    escribir_en_el_adr(
        opciones.salida,
        _cabecera_del_informe(opciones.chunks, len(chunks), len(preguntas))
        + tabla
        + _pie_del_informe(por_tipo, techos_texto, fallos, avisos),
    )
    print(f"\nAnexo de {opciones.salida.name} reescrito.")
    for aviso in avisos:
        print(f"AVISO: {aviso}")

    return 1 if fallos or avisos else 0


if __name__ == "__main__":
    sys.exit(main())

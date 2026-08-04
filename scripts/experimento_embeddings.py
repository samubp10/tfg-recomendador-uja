"""Experimento comparativo de modelos de embeddings (IT-28).

Descarga (o reutiliza de caché) cada modelo candidato, incrusta el
``data/chunks.json`` real y el conjunto de evaluación de IT-27
(``eval/preguntas_evaluacion.json``), y calcula Recall@K por fragmento y por
unidad, más el MRR, sobre todas las preguntas anotadas. Imprime las tablas de
resultados y las deja también en ``docs/experimentos/it28-embeddings.md`` para
no perder el resultado real de la ejecución.

El número de modelos, de preguntas y de fragmentos NO se escribe aquí a
propósito: son cifras que cambian y que el propio informe recoge de la
ejecución. Este módulo dice cómo se mide, no cuánto salió.

Necesita la dependencia opcional ``[index]`` (arrastra PyTorch) y red para
descargar los modelos la primera vez; por eso, igual que el resto de
verificadores del proyecto, se ejecuta SOLO en local y no en CI:

    py scripts/experimento_embeddings.py
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
from typing import Any, Final

RAIZ = Path(__file__).resolve().parent.parent
RUTA_CHUNKS = RAIZ / "data" / "chunks.json"
RUTA_EVAL = RAIZ / "eval" / "preguntas_evaluacion.json"
RUTA_RESULTADOS = RAIZ / "docs" / "experimentos" / "it28-embeddings.md"

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
#: `docs/experimentos/it28-embeddings-historico.md` y en el ADR-0003—, pero
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
    from tfg_uja.evaluacion import chunks_relevantes

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
            corpus real, que es lo que hará falta cuando se validen
            experimentalmente los tamaños de fragmento (siguen provisionales
            según el ADR-0001).

    Returns:
        Tupla ``(chunks, preguntas)``.
    """
    items = json.loads(ruta_chunks.read_text(encoding="utf-8"))
    chunks = [i for i in items if i.get("tipo") == "chunk"]
    preguntas = json.loads(RUTA_EVAL.read_text(encoding="utf-8"))["preguntas"]
    return chunks, preguntas


def crear_incrustadores(candidato: ModeloCandidato):
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

    def incrustar_documentos(textos: list[str]) -> list[list[float]]:
        con_prefijo = [candidato.prefijo_documento + t for t in textos]
        return modelo.encode(
            con_prefijo, batch_size=TAMANO_LOTE, show_progress_bar=False
        ).tolist()

    def incrustar_consultas(textos: list[str]) -> list[list[float]]:
        con_prefijo = [candidato.prefijo_consulta + t for t in textos]
        return modelo.encode(
            con_prefijo, batch_size=TAMANO_LOTE, show_progress_bar=False
        ).tolist()

    return incrustar_documentos, incrustar_consultas, modelo


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
    lineas = [
        "| " + " | ".join(columnas) + " |",
        "|" + "---|" * len(columnas),
    ]
    for fila in filas:
        valores = (
            [fila["nombre"]]
            + [f"{fila[m]:.3f}" for m in metricas]
            + [
                f"{fila['mrr']:.3f}",
                f"{fila['tiempo_s']:.1f}",
                str(fila["ventana"]),
                str(fila["truncados"]),
                f"{fila['fraccion_leida']:.0%}",
            ]
        )
        lineas.append("| " + " | ".join(valores) + " |")
    return "\n".join(lineas)


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
    encabezado = ["Modelo"] + [
        f"{t} (n={int(filas[0]['por_tipo'][t]['n'])})" for t in tipos
    ]
    lineas = [
        "| " + " | ".join(encabezado) + " |",
        "|" + "---|" * len(encabezado),
    ]
    for fila in filas:
        valores = [fila["nombre"]] + [
            f"{fila['por_tipo'][t]['recall@5']:.3f}" for t in tipos
        ]
        lineas.append("| " + " | ".join(valores) + " |")
    return "\n".join(lineas)


def main(argumentos: list[str] | None = None) -> int:
    """Ejecuta el experimento completo y muestra/guarda los resultados.

    Uso::

        py scripts/experimento_embeddings.py
        py scripts/experimento_embeddings.py --chunks otro_corpus.json \\
            --salida docs/experimentos/otro-informe.md

    Args:
        argumentos: Argumentos de línea de comandos. ``None`` toma los reales.

    Returns:
        0 si todos los modelos se evaluaron correctamente; 1 si alguno falló
        (p. ej. por no poder descargarse), para no ocultar un experimento a
        medias.
    """
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--chunks", type=Path, default=RUTA_CHUNKS)
    analizador.add_argument("--salida", type=Path, default=RUTA_RESULTADOS)
    opciones = analizador.parse_args(argumentos)
    candidatos = CANDIDATOS

    # Import perezoso: solo evaluar_modelo, no crear_incrustadores, para dar
    # un error claro y rápido si faltan los chunks/eval antes de tocar red.
    from tfg_uja.evaluacion import evaluar_modelo

    chunks, preguntas = cargar_datos(opciones.chunks)
    print(
        f"Corpus: {opciones.chunks} | Chunks: {len(chunks)} | "
        f"Preguntas: {len(preguntas)}\n"
    )

    filas: list[dict[str, Any]] = []
    fallos: list[str] = []
    for candidato in candidatos:
        print(f"Evaluando {candidato.nombre} ({candidato.descripcion}) ...")
        inicio = time.monotonic()
        try:
            incrustar_doc, incrustar_consulta, modelo = crear_incrustadores(candidato)
            resultado = evaluar_modelo(
                chunks, preguntas, incrustar_doc, incrustar_consulta, ks=KS
            )
            # El cronómetro se para ANTES de medir el truncado: esa medida
            # tokeniza el corpus una vez más y añadía 16 s a la línea base,
            # con lo que la columna de tiempo dejaba de ser comparable con la
            # ejecución del 24/07. Se mide lo mismo que se medía entonces:
            # cargar el modelo, incrustar el corpus y evaluar.
            tiempo = time.monotonic() - inicio
            ventana, truncados, fraccion = medir_truncado(
                modelo,
                [c["texto"] for c in chunks],
                candidato.prefijo_documento,
            )
        except Exception as error:  # noqa: BLE001 - se informa y se sigue con el resto
            print(f"  FALLÓ: {error}")
            fallos.append(f"{candidato.nombre}: {error}")
            continue
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
            incrustar_doc = incrustar_consulta = modelo = None  # noqa: F841
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
        filas.append(fila)
        print(
            f"  fragmento R@3={fila['recall@3']:.3f} R@5={fila['recall@5']:.3f} "
            f"R@10={fila['recall@10']:.3f}"
        )
        print(
            f"  unidad     R@3={fila['recall_unidad@3']:.3f} "
            f"R@5={fila['recall_unidad@5']:.3f} "
            f"R@10={fila['recall_unidad@10']:.3f}  "
            f"MRR={fila['mrr']:.3f}  ({tiempo:.1f}s)"
        )
        if truncados:
            print(
                f"  AVISO: ventana de {ventana} tokens; {truncados} de "
                f"{len(chunks)} fragmentos se truncan; el modelo llega a leer "
                f"el {fraccion:.2%} de los tokens del corpus."
            )

    if not filas:
        print("\nNingún modelo pudo evaluarse.")
        return 1

    tabla = formatear_tabla(filas)
    print("\n" + tabla)
    por_tipo = formatear_por_tipo(filas)
    print("\nRecall@5 por tipo de pregunta:\n" + por_tipo)

    techos = techos_de_recall(preguntas, chunks)
    techos_texto = (
        "sobre este corpus el máximo posible es "
        + ", ".join(f"**{v:.3f}** para R@{k}" for k, v in sorted(techos.items()))
        + "."
    )
    print("\nTechos de Recall@K por fragmento: " + techos_texto)

    opciones.salida.parent.mkdir(parents=True, exist_ok=True)
    # Ruta relativa a la raíz del repositorio: la absoluta lleva el nombre de
    # usuario de quien lo ejecuta y además no significa nada para quien lea el
    # informe en otra máquina.
    try:
        corpus = opciones.chunks.resolve().relative_to(RAIZ).as_posix()
    except ValueError:
        corpus = opciones.chunks.name
    cabecera_md = (
        "# IT-28 — Resultados del experimento comparativo de embeddings\n\n"
        f"Generado el {date.today():%d/%m/%Y} ejecutando "
        f"`py scripts/experimento_embeddings.py` contra `{corpus}` "
        f"({len(chunks)} fragmentos, {len(preguntas)} preguntas de "
        f"`eval/preguntas_evaluacion.json`), en **{_dispositivo()}**.\n\n"
    )
    pie_md = (
        "\n\n## Recall@5 por tipo de pregunta\n\n" + por_tipo + "\n\n"
        "La media general no se puede leer sin este desglose. Las preguntas de "
        "tipo `listado` piden **todas** las asignaturas de un grupo, así que su "
        "techo depende de cuántas unidades relevantes tengan y no de lo bien "
        "que recupere el modelo.\n"
        "\n## Cómo leer las columnas\n\n"
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
    pie_md += "\n## Modelos evaluados\n\n" + "\n".join(
        f"- `{c.nombre}`: {c.descripcion}" for c in candidatos
    )
    if fallos:
        pie_md += "\n\n## Fallos\n\n" + "\n".join(f"- {f}" for f in fallos)
    opciones.salida.write_text(cabecera_md + tabla + pie_md + "\n", encoding="utf-8")
    print(f"\nResultados guardados en {opciones.salida}")

    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())

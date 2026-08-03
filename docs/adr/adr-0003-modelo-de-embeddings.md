# ADR-0003: Modelo de incrustaciones (embeddings)

*Basado en https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions*

- **Estado:** Propuesta (pendiente de aceptación del autor)
- **Fecha:** 2026-07-29
- **Decisores:** Samuel Blanco Palmero
- **Contexto técnico:** Fase 1 (indexación y recuperación) del Recomendador UJA

## Contexto

El sistema convierte cada fragmento del corpus y cada pregunta del usuario en
un vector, y recupera comparando esos vectores. El modelo que hace esa
conversión fija el techo de todo lo que viene después: **ningún prompt puede
recuperar un fragmento que la recuperación no ha traído.** Si el modelo no
distingue «Aprendizaje automático» de «Aprendizaje profundo», el generador
responderá con seguridad sobre la asignatura equivocada, y lo hará sin ninguna
señal de que algo va mal.

Restricciones que condicionan la elección:

- **Idioma.** El corpus y las preguntas están en español. Un modelo
  monolingüe inglés queda descartado de entrada, sin necesidad de medirlo.
- **Hardware.** El entorno del proyecto tiene PyTorch compilado **solo para
  CPU**. El tamaño del modelo se paga en tiempo de indexación y, sobre todo,
  en latencia por consulta cuando llegue la aplicación web de la Fase 3.
- **Tamaño del corpus.** 781 fragmentos, unos 190.000 tokens. Indexar es
  barato y se rehace completo en cada ejecución, así que el coste de
  indexación **no** es un criterio de peso. La latencia de consulta sí.
- **Reproducibilidad.** Los pesos se descargan una vez y quedan en caché; a
  partir de ahí el experimento corre sin red. Depender de un servicio de
  incrustaciones por API habría atado la reproducibilidad a un tercero y a una
  clave de pago.
- **Longitud de los fragmentos.** El máximo de fragmento son 1.500 caracteres,
  que en español llegan a **469 tokens**. Esta restricción resultó ser mucho
  más determinante de lo previsto: ver el apartado del truncado.

La comparación se hace contra el conjunto etiquetado de IT-27
(`eval/preguntas_evaluacion.json`, 36 preguntas), con Recall@3, Recall@5 y MRR
implementados en `tfg_uja/evaluacion.py`, mediante
`scripts/experimento_embeddings.py`.

## Alternativas consideradas

### Opción A — paraphrase-multilingual-MiniLM-L12-v2

Modelo multilingüe destilado de la familia *paraphrase* de sentence-transformers.
Es el que `indexer.py` monta de forma provisional desde IT-30, y funciona aquí
como **línea base**: sin él, cualquier mejora sería una cifra sin referencia.

- **URL:** [https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
- 118 M parámetros · 384 dimensiones · **ventana de 128 tokens**
- **Pros:** el más rápido de los cuatro; vectores pequeños, índice ligero; sin
  convención de llamada especial.
- **Contras:** entrenado para *similitud entre paráfrasis*, no para
  recuperación asimétrica pregunta→documento, que es el problema real aquí. Y
  su ventana de 128 tokens **no le deja leer los fragmentos de este corpus**.
- **Descartada:** peor en las tres métricas, en dos corpus distintos.

### Opción B — paraphrase-multilingual-mpnet-base-v2

La misma familia y el mismo entrenamiento que la línea base, pero con una
arquitectura mayor. Está en la comparación para responder a una pregunta
concreta: **¿basta con un modelo más grande?**

- **URL:** [https://huggingface.co/sentence-transformers/paraphrase-multilingual-mpnet-base-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-mpnet-base-v2)
- 278 M parámetros · 768 dimensiones · **ventana de 128 tokens**
- **Pros:** mejora claramente a la línea base (Recall@3 0,420 → 0,584) sin
  cambiar nada más que el tamaño.
- **Contras:** más del doble de parámetros, el doble de dimensiones (índice
  el doble de grande) y el doble de tiempo, y aun así se queda por debajo de la
  opción C, que es del tamaño de la línea base. Arrastra la misma ventana de
  128 tokens.
- **Descartada:** paga el doble en memoria y en tiempo para quedar por detrás.
  La respuesta a «¿basta con más tamaño?» es **no**.

### Opción C — intfloat/multilingual-e5-small (elegida)

Modelo multilingüe entrenado específicamente para **recuperación**, con un
esquema contrastivo débilmente supervisado. Su ficha exige prefijar los textos:
`"query: "` para las preguntas y `"passage: "` para los documentos, porque el
modelo aprendió a tratar los dos papeles de forma distinta.

- **URL:** [https://huggingface.co/intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small)
- 118 M parámetros · 384 dimensiones · **ventana de 512 tokens**
- **Pros:** el mejor en las tres métricas y en los dos corpus; **exactamente
  el mismo tamaño y la misma dimensión que la línea base**, así que la mejora
  no cuesta ni un byte más de índice; es el único de los cuatro que lee los
  fragmentos completos.
- **Contras:** los prefijos son obligatorios y asimétricos, así que son un
  invariante que hay que proteger con una prueba (olvidarlo en la consulta
  degrada la recuperación sin error visible). Y 512 tokens siguen siendo un
  techo: el fragmento más largo del corpus gasta 473 de los 510 útiles, así que
  **no queda margen** si el máximo de fragmento subiera.

### Opción D — hiiamsid/sentence_similarity_spanish_es

Modelo **específico de español**, no multilingüe. Está en la comparación como
contraste: la hipótesis razonable era que un modelo dedicado al idioma del
corpus batiese a los multilingües.

- **URL:** [https://huggingface.co/hiiamsid/sentence_similarity_spanish_es](https://huggingface.co/hiiamsid/sentence_similarity_spanish_es)
- 110 M parámetros · 768 dimensiones · ventana de 512 tokens
- **Pros:** entrenado en español; ventana suficiente para el corpus (solo
  trunca 1 fragmento de 781).
- **Contras:** el peor de los cuatro por un margen enorme (Recall@3 de 0,233
  frente a 0,705) y el más lento, unas cuatro veces la línea base.
- **Descartada:** la hipótesis del modelo específico de idioma **no se
  sostiene**, y conviene decirlo así en la memoria en vez de omitir el
  resultado. Está entrenado para *similitud semántica entre frases*, una tarea
  simétrica; aquí se le pide recuperación asimétrica sobre documentos largos.
  Es la evidencia más limpia de que **la tarea de entrenamiento pesa más que el
  idioma**.

## Decisión

**`intfloat/multilingual-e5-small`, con los prefijos `"query: "` y `"passage: "`
que exige su ficha.**

Se apoya en el experimento de IT-28, ejecutado dos veces sobre **dos corpus
distintos** (24/07 con 892 fragmentos del curso 2025-26; 29/07 con 781 del
curso 2026-27, tras el re-rastreo de IT-80). Las cifras del 29/07:

| Modelo | Recall@3 | Recall@5 | MRR | Tiempo (s) | Ventana | Truncados | Corpus leído |
|---|---:|---:|---:|---:|---:|---:|---:|
| A — MiniLM-L12 (línea base) | 0,420 | 0,570 | 0,619 | 63,9 | 126 | 685 | 50 % |
| B — mpnet-base | 0,584 | 0,668 | 0,730 | 125,1 | 126 | 685 | 50 % |
| **C — multilingual-e5-small** | **0,705** | **0,787** | **0,856** | 108,5 | 510 | **0** | **100 %** |
| D — sentence\_similarity\_spanish\_es | 0,233 | 0,302 | 0,381 | 281,1 | 510 | 1 | 100 % |

**El orden de los cuatro modelos es idéntico en las dos ejecuciones**, con el
mismo ganador y un margen parecido. Eso es lo que permite fijar la decisión: la
conclusión no dependía de un corpus concreto, que era la duda razonable al
haber medido sobre un corpus que después cambió.

Sobre los 781 fragmentos hubo además **dos ejecuciones el mismo día**, la
segunda tras añadir las columnas de ventana y truncado. **Las doce cifras de
Recall y MRR salieron idénticas hasta el tercer decimal**, lo que confirma que
el experimento es determinista y que la tabla no depende del orden ni del azar.
Los **tiempos, en cambio, subieron entre un 25 % y un 60 %** por carga de la
máquina, sin que cambiara nada del código medido: valen para ordenar los cuatro
modelos entre sí —y ese orden sí se mantuvo—, pero **no como cifras absolutas**.
Se recogen los de la segunda ejecución, que es la que queda registrada en
`docs/experimentos/it28-embeddings.md`.

### El truncado silencioso, que es la mitad de la explicación

Al preparar este ADR se midió algo que el experimento original no miraba: la
**ventana de contexto** de cada modelo. Las dos opciones de la familia
*paraphrase* las sirve sentence-transformers con `max_seq_length = 128`, no con
los 512 del transformador que llevan dentro.

Consecuencia sobre este corpus, medida y no estimada:

- La mediana de fragmento son **264 tokens**; el máximo, **469**.
- **685 de los 781 fragmentos (88 %) se truncan** con la línea base.
- El modelo llega a leer **94.023 de los 189.929 tokens del corpus: se
  descarta el 50,5 %.** De media ve el 56 % de cada fragmento, y en el peor
  caso el 27 %.

Y `encode` **no avisa de nada**: recorta, devuelve un vector de aspecto normal
y sigue. Se comprobó de forma directa, no leyendo la configuración: se incrustó
un fragmento completo, y después ese mismo fragmento con su cola sustituida por
texto basura. Con la línea base los dos vectores son **idénticos**
(coseno 1,0000): el modelo nunca vio esa parte. Con la opción C el vector sí
cambia (coseno 0,9673).

Esto obliga a matizar la lectura del resultado, y hay que hacerlo en voz alta
porque la lectura fácil es la equivocada:

- ✅ **La comparación sigue siendo válida.** Cada modelo se usó como prescribe
  su propia ficha, y la ventana **es parte de lo que se elige**: un modelo que
  no puede leer los documentos del sistema no sirve para el sistema, y eso no
  es un defecto del experimento sino un resultado suyo.
- ⚠️ **Pero la explicación del margen no es «la arquitectura orientada a
  recuperación».** Al menos una parte grande de la diferencia entre A y C es que
  A lee la mitad del texto y C lo lee todo. Presentar 0,420 → 0,705 como una
  mejora de calidad de las representaciones sería atribuir a una causa lo que
  produce otra. Las dos son razones para elegir C; no son la misma razón.
- ⚠️ **El experimento no separa las dos causas.** Para separarlas habría que
  re-fragmentar el corpus a ≤ 126 tokens y volver a medir los cuatro modelos en
  igualdad de ventana. Queda como amenaza declarada y como el siguiente
  experimento natural, que además se solapa con la validación pendiente de los
  parámetros de fragmentación (ADR-0001).

Esto contradice además una afirmación del **ADR-0001**, que daba por hecho que
«los modelos de embeddings multilingües habituales admiten ~512 tokens» y
listaba entre sus consecuencias positivas que ningún fragmento «supera la
ventana de embeddings». Con el modelo que el sistema montaba de verdad, esa
afirmación era falsa para el 88 % del corpus. El ADR-0001 lo recoge ya en su
adenda; **es la clase de premisa que hay que medir en vez de suponer.**

## Consecuencias

### Positivas

- **+0,285 en Recall@3 y +0,237 en MRR** sobre la línea base, medido en dos
  corpus.
- **La mejora es gratis en espacio:** misma dimensión (384) y mismo número de
  parámetros (118 M) que la línea base, así que el índice no crece.
- **Por primera vez se indexa el corpus entero.** Los 781 fragmentos entran
  completos, sin recorte.
- Más rápido que la opción B **en las dos ejecuciones** —y además mejor que
  ella—, aunque los tiempos absolutos no son estables (ver arriba).
- El resultado negativo de la opción D es aprovechable en la memoria: aporta
  evidencia de que la tarea de entrenamiento pesa más que el idioma, que es una
  conclusión más interesante que «gana el mejor».

### Negativas

- **Los prefijos son un invariante frágil.** `"query: "` y `"passage: "` no son
  decorativos: el modelo trata los dos papeles de forma distinta. Olvidar el
  prefijo en la consulta degrada la recuperación **sin ningún error visible**,
  que es justo el patrón de fallo que este proyecto ya ha sufrido tres veces.
  Debe protegerse con una prueba, no con un comentario.
- **Techo de 512 tokens sin margen.** El fragmento más largo gasta 473 de los
  510 útiles. Si el experimento de fragmentación de la Fase 1 recomendase
  fragmentos mayores, este modelo dejaría de servir y habría que revisar este
  ADR.
- Ata el código a una familia de modelos con una convención de llamada poco
  obvia, que cualquiera que retome el proyecto puede romper sin darse cuenta.
- La reproducibilidad depende de que Hugging Face siga sirviendo esos pesos.
  Mitigación: quedan en caché local tras la primera descarga.
- `indexer.py` **sigue montando la línea base**. Mientras no se cambie, el
  índice del sistema se construye con el modelo que este ADR descarta, y
  truncando la mitad del corpus.

## Amenazas a la validez

1. 🔴 **Los umbrales de la hipótesis se fijaron después de medir.** El
   experimento de IT-28 se lanzó sin declarar antes qué mejora se consideraría
   suficiente. Que el ganador arrase **no lo arregla**: es la definición de
   hipótesis *post hoc*. Repetir el experimento sobre el corpus nuevo tampoco lo
   arregla, porque el resultado ya se conocía.
2. **Ventana y calidad no están separadas** (arriba). Es la amenaza a la
   validez de construcción más seria de este ADR: se cree estar midiendo
   «calidad de las representaciones» y se está midiendo también «cuánto texto
   ha leído el modelo».
3. **36 preguntas son pocas y no hay intervalos de confianza.** Una diferencia
   de 0,285 en Recall@3 son unas 10 preguntas: es un margen grande, pero no está
   respaldado por ninguna prueba inferencial. No se debe presentar como
   significativo en sentido estadístico.
4. **Un solo anotador.** El conjunto de evaluación lo escribió el propio autor,
   sin acuerdo entre anotadores. Los juicios de relevancia pueden favorecer sin
   querer la forma en que el corpus está redactado.
5. **La categoría `sin guía` del conjunto solo tiene 2 preguntas** (bajó de 5
   al publicar la fuente tres guías nuevas). Es precisamente el punto ciego del
   corpus —62 asignaturas sin contenido, concentradas en las dos titulaciones
   más nuevas— y es donde peor se está midiendo.
6. **Los tiempos son de CPU** en una máquina concreta. Valen para comparar
   entre sí los cuatro modelos, no como afirmación de rendimiento del sistema.
7. **El Recall@3 de este ADR no puede llegar a 1: su techo es 0,868.** Añadida
   el 01/08/2026 y desarrollada en el apartado siguiente. Es la que más cambia
   cómo se leen las cifras de la tabla.

## Adenda de 2026-08-01 — de dónde sale K, y su techo

Dos cosas que este ADR usaba sin decirlas. Ninguna cambia la decisión; las dos
cambian cómo hay que leer los números.

### Por qué K vale 3 y 5

Vienen de la Definición de Hecho de IT-28 («al menos K=3 y K=5»), y hasta hoy no
estaban justificados en ninguna parte: ni aquí, ni en el cuerpo del commit que
los introdujo, ni en la memoria. La razón es el **presupuesto de contexto** del
LLM local. Con la mediana real de **264 tokens por fragmento**:

| K | Contexto que consume |
|---:|---:|
| 3 | ~790 tokens |
| 5 | ~1.320 |
| 10 | ~2.640 |
| 20 | ~5.280 |

No es un techo del modelo —los candidatos de pesos abiertos admiten de 32k
tokens en adelante— sino una elección de coste: cada fragmento de más es tiempo
de proceso del *prompt* en CPU y un distractor más para el generador. **K podrá
subir** si la evaluación de la Fase 2 muestra que hace falta; lo que decidirá no
es la recuperación sino la fidelidad de la respuesta.

⚠️ **Son dos K distintos y hoy coinciden por casualidad:** el de la métrica (este)
y el del sistema, es decir, cuántos fragmentos entran de verdad en el *prompt*,
que no está decidido y es parámetro del estudio de ablación (IT-49). Si el
segundo cambia, este debe seguirlo, o se estará midiendo una configuración que el
sistema no usa.

### El techo de Recall@3 es 0,868, no 1

Medido el 01/08/2026 sobre el conjunto de evaluación:

| Fragmentos relevantes por pregunta | 1 | 2 | 3 | 4 | 5 | 6 | 9 | 11 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Nº de preguntas | 9 | 11 | 4 | 5 | 4 | 1 | 1 | 1 |

**12 de las 36 preguntas apuntan a más de 3 fragmentos**, así que es
matemáticamente imposible recuperarlos todos en un top-3. Una pregunta con 11
fragmentos relevantes tiene un Recall@3 máximo de 0,27 aunque el sistema acierte
perfectamente. Promediando el máximo alcanzable de cada una sale **0,868**.

Consecuencia para la lectura de la tabla de este ADR:

| | |
|---|---:|
| Recall@3 del modelo elegido | 0,705 |
| Techo alcanzable con este etiquetado | **0,868** |
| Hueco real | **0,163**, no 0,295 |

No invalida la comparación —los cuatro modelos comparten el mismo techo, así que
el orden no se mueve— pero **presentar el 0,705 sin el techo hace que el sistema
parezca bastante peor de lo que es**.

El origen no es un defecto del recuperador sino la definición de relevancia:
`evaluacion.py` documenta que Recall@K aquí mide **cobertura** y no acierto
binario, y esa elección era deliberada. Lo que no se había calculado es su
consecuencia numérica. Dónde está el orden real de lo recuperado:

- **35 de 36 preguntas** ya tienen al menos un fragmento relevante en el top-3.
- La posición mediana del primer relevante es **1**; la peor de las 36, la 6.

Es decir: lo que falta para llegar al techo **no son documentos mal ordenados,
son los demás fragmentos de la misma unidad**. Revisar el criterio de relevancia
corresponde a IT-69, y la posible expansión por unidad al recuperar es una
decisión del recuperador de la Fase 2.

## Referencias

- Fichas de los cuatro modelos evaluados, enlazadas en cada alternativa.
- Resultados literales de las dos ejecuciones:
  `docs/experimentos/it28-embeddings.md` (29/07) y
  `docs/experimentos/it28-embeddings-historico.md` (24/07).
- Documentación de sentence-transformers, sobre `max_seq_length` y el recorte
  automático: [https://www.sbert.net/](https://www.sbert.net/)
- L. Wang et al., "Multilingual E5 Text Embeddings: A Technical Report"
  (familia E5 multilingüe y el uso de los prefijos `query:`/`passage:`).
- N. Reimers, I. Gurevych, "Sentence-BERT: Sentence Embeddings using Siamese
  BERT-Networks", EMNLP 2019 (base de la familia *paraphrase*).
- N. Muennighoff et al., "MTEB: Massive Text Embedding Benchmark" (contexto
  sobre por qué un modelo entrenado para recuperación rinde distinto que uno
  entrenado para similitud).
- M. Nygard, "Documenting Architecture Decisions", cognitect.com
  ([2011-11-15](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)).

# ADR-0004: Base de datos vectorial

_Basado en https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions_

- **Estado:** Aceptada
- **Decisores:** Samuel Blanco Palmero
- **Contexto técnico:** Fase 2 (pipeline RAG y base vectorial) del Recomendador UJA

## Contexto

Fijados el modelo de incrustaciones (ADR-0003) y la estrategia de fragmentación
(ADR-0001), el corpus es una matriz de **1.334 vectores de 384 dimensiones**.
Responder a una pregunta consiste en incrustarla en ese mismo espacio y devolver
los K fragmentos más próximos. Falta decidir **qué componente guarda esos
vectores y resuelve esa consulta**, que es lo que fija este ADR.

El indexador está escrito contra ChromaDB, elegida como valor de trabajo y sin
comparar nada. Es la incumbente, no una decisión tomada.

Restricciones que condicionan la decisión:

- **Tamaño del corpus.** 1.334 × 384 × 4 B = **2.049.024 bytes, 1,95 MB**. Cabe
  entero en memoria y, de hecho, en la caché de la máquina. **A esta escala la
  búsqueda exacta por fuerza bruta no es el plan B: es competitiva**, y no
  introduce ningún error. Elegir un índice aproximado «porque es lo que se usa»
  sería exactamente el tipo de decisión sin justificar que este proyecto no
  admite.
- **Hardware.** 16 GB de RAM y PyTorch compilado **solo para CPU**: los 6 GB de
  la GPU no se usan. En la Fase 2 la base vectorial tendrá que convivir en esa
  misma memoria con un modelo generativo que aún no se ha elegido y que es el
  componente grande. Cada gigabyte que se lleve la base es uno que le falta al
  generador.
- **Filtrado por metadatos.** El 48 % de los fragmentos pertenece a más de una
  titulación, así que `grados` y `codigos` son **listas**. Las preguntas reales
  del estudiante son del tipo «obligatorias de Informática», que exige combinar
  una consulta vectorial con una condición sobre un campo de tipo lista.
- **Reproducibilidad.** El sistema tiene que poder ejecutarse en el ordenador de
  un tribunal: sin servicio de pago, sin clave de API y sin red en tiempo de
  consulta.
- **Persistencia.** El índice se reconstruye completo en cada ejecución del
  indexador, pero la aplicación web de la Fase 3 no puede recalcularlo en cada
  arranque.

**Alcance.** Este ADR decide para **este corpus**. La generalización a la oferta
completa de la Universidad de Jaén queda fuera del alcance del trabajo, pero es
la continuación natural, y decidir hoy condiciona si esa continuación es viable
o hay que rehacer la capa de recuperación entera.

### Los umbrales, fijados ANTES de ejecutar

Los ocho umbrales se escribieron **antes de la primera ejecución**, no después de
ver los resultados:

| | Criterio | Umbral |
|---|---|---|
| **U1** | Fidelidad frente a la búsqueda exacta | **1,000**. A esta escala no hay motivo para aceptar ninguna pérdida |
| **U2** | Filtrado por metadatos | Precisión y exhaustividad **1,000**, y **0 falsos positivos** en el caso trampa |
| **U3** | Latencia de consulta | **> 500 ms descalifica** |
| **U4** | Banda de indiferencia | Diferencias de **≤ 50 ms** se consideran empate |
| **U5** | Memoria residente | **≤ 0,5 GB**; por encima de **1 GB**, descarte. En Qdrant se mide el contenedor |
| **U6** | Reproducibilidad | Los resultados se repiten **a tres decimales** |
| **U7** | Simplicidad | Desempate cuando lo demás empata |
| **U8** | Conclusión | Si ninguna gana a la fuerza bruta por más de la banda, **la base vectorial no se justifica por velocidad** |

Cuatro cosas de este cuadro que no son obvias y que conviene tener delante al
leer los resultados:

- **U3 y U4 están puestos para NO discriminar por velocidad.** 500 ms es un
  listón bajísimo para este corpus y 50 ms de banda es enorme frente a las
  latencias esperables. Es deliberado: la hipótesis era que la velocidad no
  decide, y los umbrales se pusieron de forma que solo la contradijera un
  resultado escandaloso.
- **U1 exige el 1,000 exacto**, no «pérdida ≤ 0,02», por el motivo escrito
  entonces: a 1.334 vectores, un índice que pierda algo está cobrando un precio
  sin dar nada a cambio.
- **U2 mide la base y el esquema de metadatos a la vez.** Se mitiga fijando **el
  mismo esquema para las tres** —listas nativas, `metadatos_de_chunk()`
  compartida—, de modo que deja de ser una variable; pero la ambigüedad
  existiría el día que una candidata falle.
- **U8 es el que hace que el experimento pueda fallar.** Sin él la comparativa
  solo podría concluir «gana esta»; con él puede concluir «no hacía falta
  ninguna».

**Hipótesis contrastada:** sustituir la búsqueda exacta por un índice aproximado
no degrada de forma apreciable la recuperación en un corpus de este tamaño, y la
elección debe decidirse por criterios de ingeniería y no por Recall.

## Alternativas consideradas

Los criterios de admisión se fijaron antes de mirar candidatas: licencia abierta,
ejecutable en un portátil sin servicio de pago, persistencia en disco, filtrado
por campos de tipo lista y madurez declarada por el propio proyecto. Las tres que
quedaron cubren **tres puntos distintos del espacio de diseño**, no tres
variantes de lo mismo. Las tres parten de cero: que ChromaDB tuviera el código
del proyecto escrito a su favor no cuenta como argumento.

### Opción A — ChromaDB

La que el proyecto ya usaba. Es la que había que batir.

- **URL:** [https://www.trychroma.com/](https://www.trychroma.com/) · versión medida **1.5.9**
- Licencia Apache-2.0. En proceso, `PersistentClient(path=...)`. Persiste en un
  SQLite más una carpeta binaria por colección. Índice HNSW.
- **Pros:** cero configuración —no hay esquema que declarar ni índices de apoyo
  que crear—; es la más rápida de las tres (1,17–1,43 ms de mediana); y el código
  del proyecto ya estaba escrito para ella.
- **Contras:** 🔴 **no cumple U1.** Pierde vecinos respecto de la búsqueda exacta
  en **4 de cada 20 reconstrucciones**, y por tanto tampoco cumple U6. Además es
  la única de las tres cuyo **modo de respuesta no se ha podido determinar**: no
  expone ningún contador de vectores indexados, así que no hay forma, desde el
  cliente, de saber si recorre el grafo o el conjunto completo.
- **Descartada:** por incumplir un umbral eliminatorio fijado antes de medir.

### Opción B — LanceDB (elegida)

La apuesta por la simplicidad: biblioteca embebida sobre el formato columnar
Lance, con búsqueda exacta por defecto a esta escala.

- **URL:** [https://lancedb.com/](https://lancedb.com/) · versión medida **0.37.1**
- Licencia Apache-2.0. En proceso, `lancedb.connect(ruta)`. Esquema Arrow
  explícito. Índice vectorial **opcional**: su documentación recomienda «*at
  least a few thousand rows*» antes de que entrenarlo tenga sentido, de modo que
  con 1.334 filas no construye ninguno y responde por escaneo completo, es decir,
  de forma **exacta**.
- **Pros:** cumple U1 a U5 y prefiltra. Es la de **menor memoria residente**
  (~22 MiB). No necesita servidor ni Docker: el sistema de la Fase 3 no adquiere
  ninguna dependencia de infraestructura. El esquema Arrow declarado obliga a
  decir el tipo de cada metadato, incluido el vector como `list_(float32, 384)`
  de tamaño fijo, lo que convierte en error ruidoso lo que en otras sería un dato
  mal guardado en silencio.
- **Contras:** su distancia por defecto es `l2` y hay que declarar el coseno **en
  cada consulta**, no una vez al crear la tabla. El prefiltrado viene de fábrica
  pero es desactivable. Y es la más lenta de las tres, aunque por un margen que
  U4 declara empate.

### Opción C — Qdrant

La apuesta por el filtrado: la única de las tres pensada desde el principio para
consultas vectoriales con condiciones sobre el payload, con **HNSW filtrable**
—añade aristas entre puntos que comparten valor en un campo indexado, para que el
subgrafo de cada valor siga siendo navegable—.

- **URL:** [https://qdrant.tech/](https://qdrant.tech/) · cliente **1.19.0**, imagen `qdrant/qdrant:v1.19.0`
- Licencia Apache-2.0. Servidor en contenedor, expone REST y gRPC.
- **Pros:** cumple U1 a U5 y prefiltra. Es la más rápida de las dos finalistas
  (5,62 ms frente a 7,35 ms de mediana). Su filtrado por listas es nativo y sin
  sintaxis especial. Es la que mejor crecería si el corpus se multiplicara.
- **Contras:** **exige un servidor aparte y Docker**, que es un salto cualitativo
  respecto de las otras dos y no una molestia de grado. ~150 MiB de memoria
  frente a ~22 MiB, aunque las dos cifras no se miden igual: en Qdrant es el
  contenedor completo. Requiere crear dos índices de payload **antes** de
  insertar los datos, porque son los que generan las aristas del HNSW filtrable.
- **Descartada:** no por rendimiento —empata con la elegida dentro de U4— sino
  por U7. Ver la decisión.

### Línea base — NumPy, fuerza bruta exacta

**No es candidata: es el cero de la comparación.** Una matriz de 1.334 × 384 en
`float32` y un producto matriz-vector, exactamente lo que ya hace
`evaluacion.py`. Su fidelidad es 1,000 por construcción, no por suerte. No aporta
persistencia, gestión de colecciones ni filtrado declarativo: habría que
escribirlos.

### Descartadas antes de medir, con su motivo

Se dejan por escrito porque «no la miré» es peor respuesta que «la miré y la
descarté por esto»:

| Descartada | Motivo | Evidencia |
|---|---|---|
| **`sqlite-vec`** | Demasiado joven para apostar el TFG | Su README dice «*`sqlite-vec` is a pre-v1, so expect breaking changes!*» |
| **FAISS** | Es una **biblioteca de índices**, no una base de datos: no gestiona metadatos ni persistencia. Obligaría a escribir a mano justo lo que el criterio de filtrado exige que resuelva la herramienta | Argumento de categoría, no de versión |
| **pgvector** | Exige levantar y administrar un PostgreSQL completo para 1,95 MB de vectores | Argumento de categoría |
| **Milvus, Weaviate** | Pensadas para escala distribuida. Sobredimensionadas para 1.334 vectores | Argumento de categoría |
| **Qdrant Edge** | En beta declarada y con licencia sin verificar: los dos motivos por los que se descartó `sqlite-vec`. Aplicar el criterio a una y no a la otra sería incoherente | «*Qdrant Edge is in beta*», documentación oficial |

⚠️ Las cuatro últimas se descartan **por argumento de diseño, no por medición**.
Es una exclusión legítima —no se puede medir todo— pero se presenta como lo que
es: de ellas no hay cifras, y este es el motivo por el que no entraron.

## Resultados del experimento

<!-- INICIO RESULTADOS AUTOMÁTICOS (scripts/experimento_vectordb.py) -->

**Generado el 2026-08-13 por `scripts/experimento_vectordb.py`, sobre 1334 fragmentos y 50 preguntas de `eval/preguntas_evaluacion.json`. K = 10, 5 repeticiones por pregunta para la latencia. Las cuatro condiciones reciben los mismos vectores, incrustados una sola vez.**

### Tabla comparativa

| Candidata | Versión | Modo | Fidelidad (U1) | Latencia mediana (U3) | Latencia p90 | Construcción | Memoria (U5) |
|---|---|---|---:|---:|---:|---:|---:|
| NumPy (fuerza bruta, línea base) | 2.5.1 | exacto por construcción; no es candidata, es la referencia de U1 | 1.0000 | 0.20 ms | 0.24 ms | 0.00 s | 1.95 MiB |
| ChromaDB | 1.5.9 | NO VERIFICABLE desde el cliente — la colección se configura con HNSW (space=cosine, ef_search=100, max_neighbors=16), pero ChromaDB **no expone un contador de vectores indexados** como Qdrant, así que no se puede comprobar por esta vía si a 1.334 vectores responde recorriendo el grafo o el conjunto completo | 0.9980 | 1.43 ms | 1.68 ms | 1.81 s | 26.12 MiB |
| LanceDB | 0.37.1 | escaneo completo — MEDIDO: list_indices() = [], ningún índice ANN construido (el corpus está por debajo de las «few thousand rows» que recomienda su documentación) | 1.0000 | 7.35 ms | 8.41 ms | 0.30 s | 22.71 MiB |
| Qdrant | cliente 1.19.0 · imagen qdrant/qdrant:v1.19.0 (pyproject.toml) | escaneo completo — MEDIDO: indexed_vectors_count = 0 de 1334 puntos (indexing_threshold = 10000 KiB, full_scan_threshold = 10000 KiB; el corpus ocupa ~2001 KiB, por debajo de ambos; no se han bajado a mano para forzar la construcción del índice) | 1.0000 | 5.62 ms | 16.61 ms | 1.51 s | 149.10 MiB |

### Filtrado por metadatos (U2)

| Candidata | Caso | Recuperados | Esperados | Falsos positivos |
|---|---|---:|---:|---:|
| ChromaDB | obligatorias de Informática | 58 | 58 | 0 |
| ChromaDB | Eléctrica (caso trampa) | 417 | 417 | 0 |
| LanceDB | obligatorias de Informática | 58 | 58 | 0 |
| LanceDB | Eléctrica (caso trampa) | 417 | 417 | 0 |
| Qdrant | obligatorias de Informática | 58 | 58 | 0 |
| Qdrant | Eléctrica (caso trampa) | 417 | 417 | 0 |

#### ¿Mide algo U2? Poder discriminante de cada caso

Un umbral que se cumple igual con la implementación correcta y con la defectuosa no separa nada. Esta tabla compara la verdad de referencia (pertenencia exacta a la lista `grados`) con lo que devolvería la implementación defectuosa que este proyecto ya tuvo, la de comparar subcadenas:

| Caso de U2 | Correctos (pertenencia exacta) | Devueltos por un filtro de subcadena | ¿Discrimina? |
|---|---:|---:|---|
| obligatorias de Informática | 58 | 58 | **no**: los dos coinciden |
| Eléctrica (caso trampa) | 417 | 584 | **sí**, 167 falsos positivos |

### Prefiltrado frente a posfiltrado

Ni U1 ni U2 lo detectan: U2 pide **todos** los fragmentos que cumplen el filtro, y sin un top-K que romper las dos estrategias dan el mismo resultado. Pero es la garantía que el recuperador de la Fase 2 necesita, porque posfiltrar es un **fallo silencioso**: el sistema devolvería una lista corta o vacía y respondería «no tengo información» sobre algo que sí está indexado.

**Caso real usado:** pregunta 0 del conjunto de evaluación —«¿Qué salidas profesionales tiene el Grado en Ingeniería Informática?»— filtrando por «Doble Grado en Ingeniería Electrónica Industrial y Mecánica», que tiene **412 fragmentos** en el corpus y **ninguno** entre los 10 primeros de esa consulta sin filtrar.

Quien prefiltra devuelve los 10 pedidos; quien posfiltra devuelve 0, porque de los 10 más parecidos del corpus entero ninguno pasa el filtro.

| Candidata | Devueltos | Pedidos | ¿Todos cumplen el filtro? | Veredicto |
|---|---:|---:|---|---|
| ChromaDB | 10 | 10 | sí | **prefiltra** |
| LanceDB | 10 | 10 | sí | **prefiltra** |
| Qdrant | 10 | 10 | sí | **prefiltra** |

### Esfuerzo de configuración (U7)

U7 es un desempate y no una cifra, así que se registra en **hechos verificables** y no en opiniones sobre lo cómoda que resulta cada una:

| Aspecto | ChromaDB | LanceDB | Qdrant |
|---|---|---|---|
| ¿Servicio aparte? | No: en proceso, `PersistentClient(path=...)` | No: en proceso, `lancedb.connect(ruta)` | **Sí**: servidor en `localhost:6333` |
| ¿Docker? | No | No | **Sí** para el experimento. Solo en desarrollo: el sistema no depende de Docker en marcha |
| ¿Esquema declarado? | No: los metadatos se infieren de cada `add` | **Sí**: esquema Arrow explícito, con el vector como `list_(float32, 384)` de tamaño fijo | Parcial: `VectorParams(size, distance)`. El payload es JSON libre |
| ¿Métrica declarada? | **Sí, obligatorio**: por defecto es `l2` | **Sí, obligatorio**: por defecto es `l2` | **Sí**, en `VectorParams` |
| Preparación antes de insertar | Ninguna | Crear la tabla con su esquema | **Dos índices de payload** (`grados`, `tipo_asignatura`), y conviene crearlos ANTES de insertar porque son los que generan las aristas del HNSW filtrable |
| Índices de apoyo para filtrar | Ninguno | Ninguno creado. Su documentación menciona un índice escalar `LABEL_LIST` para columnas lista; **el filtrado da 58/58 y 417/417 sin él**, así que a esta escala es de rendimiento y no de corrección | Dos, del tipo `KEYWORD` |
| Sintaxis del filtro | `$and` de `$contains` y `$eq` (dict) | SQL de DataFusion: `array_has_any(...)` | Objetos `Filter(must=[FieldCondition...])` |

### Veredicto contra los umbrales U1-U5

**ChromaDB**
- U1 (fidelidad = 1,000 exacto): NO CUMPLE (0.9980)
- U2 (precisión y exhaustividad 1,000, 0 falsos positivos): CUMPLE (obligatorias de Informática: 58/58 recuperados/esperados, 0 falsos positivos; Eléctrica (caso trampa): 417/417 recuperados/esperados, 0 falsos positivos)
- U3 (latencia mediana <= 500 ms): CUMPLE (1.43 ms, p90 1.68 ms)
- U5 (memoria residente): CUMPLE (<= 0,5 GiB) (26.12 MiB)
- Prefiltrado (no es un umbral, es una garantía de corrección): PREFILTRA (10 de 10 pedidos)
- Nota: Distancia coseno declarada explícitamente al crear la colección (la de ChromaDB por defecto es l2).
- Nota: Su fidelidad NO permite concluir «su índice es fiel» mientras el modo no esté determinado.

**LanceDB**
- U1 (fidelidad = 1,000 exacto): CUMPLE (1.0000)
- U2 (precisión y exhaustividad 1,000, 0 falsos positivos): CUMPLE (obligatorias de Informática: 58/58 recuperados/esperados, 0 falsos positivos; Eléctrica (caso trampa): 417/417 recuperados/esperados, 0 falsos positivos)
- U3 (latencia mediana <= 500 ms): CUMPLE (7.35 ms, p90 8.41 ms)
- U5 (memoria residente): CUMPLE (<= 0,5 GiB) (22.71 MiB)
- Prefiltrado (no es un umbral, es una garantía de corrección): PREFILTRA (10 de 10 pedidos)
- Nota: Prefiltrado por defecto (prefilter=True).
- Nota: Distancia coseno declarada en cada consulta: la de LanceDB por defecto es l2 (comprobado ejecutándolo).

**Qdrant**
- U1 (fidelidad = 1,000 exacto): CUMPLE (1.0000)
- U2 (precisión y exhaustividad 1,000, 0 falsos positivos): CUMPLE (obligatorias de Informática: 58/58 recuperados/esperados, 0 falsos positivos; Eléctrica (caso trampa): 417/417 recuperados/esperados, 0 falsos positivos)
- U3 (latencia mediana <= 500 ms): CUMPLE (5.62 ms, p90 16.61 ms)
- U5 (memoria residente): CUMPLE (<= 0,5 GiB) (149.10 MiB)
- Prefiltrado (no es un umbral, es una garantía de corrección): PREFILTRA (10 de 10 pedidos)
- Nota: Memoria del contenedor completo (docker stats), no del proceso cliente: incluye el sistema base del contenedor.
- Nota: Índices de payload creados antes de insertar los datos.

### Lo que estas cifras NO permiten concluir

- **La métrica de distancia no es distinguible con este modelo.** Las normas de los 1334 vectores del corpus van de 1.000000 a 1.000000 —es decir, `e5-small` los entrega **normalizados**—, y para vectores de norma 1 se cumple `||a-b||² = 2 - 2·cos(a,b)`, así que el ranking por distancia euclídea y por similitud coseno es **idéntico por construcción**. Una fidelidad de 1,000 no demuestra, por tanto, que una candidata esté usando la métrica que se le pidió. Se declara la métrica en las tres de todos modos, porque esa equivalencia es una propiedad del modelo y no de la base: cambiar de modelo la rompería sin que fallara nada.
- **La fidelidad no separa índice aproximado de recorrido completo.** Donde la columna «Modo» dice escaneo completo, un 1,000 significa «no perdió nada respecto de la fuerza bruta», **no** «su índice es fiel»: no llegó a usar índice. Y en ChromaDB el modo no se ha podido determinar desde el cliente.
- **U6 (reproducibilidad a tres decimales) exige una segunda ejecución** y compararla con esta. Un solo pase no la comprueba.
- **U7 (simplicidad) es un juicio de ingeniería**, no una cifra que este guion pueda calcular.
- **Las latencias son de una máquina concreta** (Ryzen 7 5800H, 16 GB, PyTorch solo-CPU) que estaba haciendo otras cosas. Valen para comparar las candidatas entre sí, no como cifras absolutas. Se descartan las 5 primeras consultas de cada candidata para que la carga perezosa del índice no entre en la muestra.
- **Las memorias no son homogéneas entre candidatas:** en ChromaDB y LanceDB es el delta de RSS del proceso; en Qdrant, el contenedor completo con su sistema base; en NumPy, el tamaño calculado de la matriz. Es el coste real de cada solución en este proyecto, no «la memoria del algoritmo».
- **El orden de medición no se ha alternado** entre candidatas: se miden en el mismo orden en cada ejecución, así que un proceso pesado de fondo penalizaría siempre a la misma.

<!-- FIN RESULTADOS AUTOMÁTICOS -->

### U6: las 20 reconstrucciones

El informe automático de arriba es **un solo pase**, y él mismo advierte de que U6
exige una segunda ejecución. Se hicieron **20 ciclos completos**
(`scripts/repeticiones_vectordb.py`), reconstruyendo los tres índices desde cero
en cada uno y con los mismos vectores:

| Candidata | Modo (medido) | Fidelidad (U1) | Ciclos que fallan U1 | Latencia mediana | ¿Cumple U6? |
|---|---|---|---:|---:|---|
| NumPy (línea base) | Exacto por construcción | 1,0000 | — | **0,17 ms** | ✅ |
| **ChromaDB** | ⚠️ No verificable desde el cliente | 0,9980 / 1,0000 | 🔴 **4 de 20 (20 %)** | 1,17 ms | ❌ **No** |
| **LanceDB** | Escaneo completo (`list_indices() = []`) | **1,0000 siempre** | **0 de 20** | 5,66 ms | ✅ Sí |
| **Qdrant** | Escaneo completo (`indexed_vectors_count = 0`) | **1,0000 siempre** | **0 de 20** | 4,67 ms | ✅ Sí |

Tres lecturas, y la segunda es la que decide:

1. **La variabilidad está en la construcción, no en la consulta.** Consultar el
   *mismo* índice varias veces da idéntico resultado. Cuando ChromaDB falla,
   pierde **exactamente un vecino de 500**.
2. 🔴 **ChromaDB no cumple U1 ni U6.** Un solo pase no lo habría visto: en el
   informe automático aparece como 0,9980, un único valor que podría haberse leído
   como ruido. Son las repeticiones las que muestran que es intermitente.
3. **Es evidencia indirecta del modo de ChromaDB**, que no se pudo determinar por
   la vía del contador: un recorrido completo es exacto por construcción y no
   puede perder vecinos. Las otras dos son deterministas justamente porque
   respondieron por escaneo completo.

⚠️ **No se ha investigado la causa dentro de ChromaDB.** Lo que este ADR afirma es
el comportamiento observable, no un diagnóstico de su implementación.

⚠️ **El delta de RSS solo es válido en la primera construcción de un proceso.** A
lo largo de los 20 ciclos la memoria medida se desploma (ChromaDB de 27,2 a
~7,7 MiB; LanceDB de 22,8 a ~0,2 MiB) porque el intérprete ya pidió esa memoria
al sistema operativo y no la devuelve. Las cifras válidas de U5 son las de **una
ejecución única en proceso limpio**, que son las del informe automático.

## Decisión

**Se adopta LanceDB 0.37.1 como base de datos vectorial del sistema**, con la
distancia coseno declarada explícitamente en cada consulta y el prefiltrado
activo.

La decisión se toma en tres pasos, porque los umbrales operan en niveles
distintos y mezclarlos sería contar mal el argumento.

### Paso 1 — ChromaDB queda descartada por U1

Es el único descarte por incumplimiento de un umbral eliminatorio. Pierde vecinos
respecto de la búsqueda exacta en el 20 % de las reconstrucciones.

Hay que decir con precisión **cuánto es esa pérdida, porque es pequeña**: un
vecino de 500, en 4 de 20 ciclos. Alguien puede objetar razonablemente que a
efectos prácticos eso no se nota. La respuesta no es que la pérdida sea grave,
sino que **U1 se fijó en el 1,000 exacto antes de medir, y por un motivo escrito
entonces**: a 1.334 vectores un índice que pierde algo está cobrando un precio sin
dar nada a cambio. Relajar el umbral ahora, después de ver quién lo incumple,
sería exactamente la hipótesis *post hoc* que el ADR-0003 tuvo que declarar como
su amenaza principal y que este experimento se diseñó para evitar. **Un umbral que
se afloja cuando molesta no es un umbral.**

Lo que sí acota el argumento: **«4 de 20» es lo observado, no una tasa estimada.**
Los ciclos permiten afirmar que el fallo es intermitente, no con qué frecuencia
ocurre.

Y hay un segundo motivo, independiente del primero: ChromaDB es la única de las
tres cuyo **modo de respuesta no se ha podido verificar**. No poder saber si un
componente recorre un grafo o el conjunto completo es, en un trabajo que tiene que
defender lo que mide, un problema por sí mismo.

El experimento se diseñó, además, dentro de un proyecto que ya usaba ChromaDB y
con el código escrito para ella. Ese sesgo no se elimina: se declara. Lo que sí
puede decirse es que **el resultado va contra la incumbente**, que es lo contrario
de lo que produciría una racionalización.

### Paso 2 — entre LanceDB y Qdrant deciden U4 y U7, no el rendimiento

Las dos cumplen U1, U2, U3, U5 y U6, y las dos prefiltran. La comparación queda
así:

| | LanceDB | Qdrant | ¿Separa? |
|---|---:|---:|---|
| Fidelidad (U1) | 1,000 | 1,000 | no |
| Filtrado (U2) | 58/58 · 417/417 | 58/58 · 417/417 | no |
| Latencia mediana, pase único (U3) | 7,35 ms | 5,62 ms | **no**: 1,73 ms está dentro de la banda de 50 ms de U4 |
| Latencia mediana, 20 ciclos | 5,66 ms | 4,67 ms | **no**: 0,99 ms, misma banda |
| Memoria (U5) | ~22 MiB | ~150 MiB | sí, pero la medición no es homogénea |
| Servidor y Docker | no | **sí** | **sí** |

**Qdrant es más rápida en las dos ejecuciones, y esa ventaja es irrelevante por
decisión previa.** U4 fijó la banda de indiferencia en 50 ms antes de medir nada,
y la diferencia real es de 1 a 2 ms. Reivindicarla ahora sería usar un criterio
que se había declarado inaplicable justamente para no caer en él. A esto se suma
que **las 50 preguntas del conjunto de evaluación son pocas y no dan intervalos de
confianza**: con esa muestra, una diferencia de milisegundos no se puede presentar
como una separación establecida. Es la misma razón por la que U4 fija una banda
tan ancha y por la que U1 se exige exacto en vez de «casi»: son formas de no leer
ruido como señal.

Lo que queda, por tanto, es **U7**, y este ADR tiene que decir con todas las
letras lo que U7 es: **un juicio de ingeniería, no una medición**. Se declaró como
tal desde antes de ejecutar y se resuelve sobre los hechos verificables de la
tabla de esfuerzo de configuración —¿servidor?, ¿Docker?, ¿esquema?, ¿índices
previos?— en vez de sobre impresiones, pero sigue siendo un juicio. El hecho que
pesa es que Qdrant **exige un servicio aparte y Docker** y las otras dos no. Eso
no es una molestia de grado sino un cambio de naturaleza: la aplicación web de la
Fase 3 pasaría de arrancar sola a depender de que alguien levante un contenedor,
y el requisito de que el sistema se ejecute en el ordenador de un tribunal se
volvería mucho más frágil.

La memoria apunta en la misma dirección (~22 frente a ~150 MiB) y es un argumento
real en una máquina donde la Fase 2 tiene que meter además un modelo generativo,
pero **es un argumento de apoyo y no el principal**, porque las dos cifras no se
midieron igual (proceso frente a contenedor completo) y las dos cumplen U5 con
holgura.

### Paso 3 — U8 se activa, y hay que decirlo, no esquivarlo

🔴 **Ninguna de las tres candidatas gana a la fuerza bruta.** NumPy responde en
**0,17 ms**, entre 7 y 33 veces más rápido que todas ellas. U8 estaba escrito
antes de medir precisamente para este caso, y dice lo que hay que concluir: **la
base de datos vectorial no se justifica por velocidad en este corpus.**

La decisión de usar una, en consecuencia, **no se apoya en el rendimiento**, y
presentarla como si lo hiciera sería falso. Se apoya en cuatro servicios que la
fuerza bruta no da y que habría que escribir a mano:

1. **Persistencia** en disco, para que la aplicación de la Fase 3 no reconstruya
   el índice en cada arranque.
2. **Filtrado declarativo** sobre campos de tipo lista, prefiltrado y verificado,
   que es lo que hace posibles las preguntas del tipo «obligatorias de
   Informática».
3. **Gestión de colecciones**, versionado del índice y esquema tipado.
4. **El camino de crecimiento.** El alcance de este trabajo es la EPSJ, pero el
   sistema es una prueba de concepto de algo que podría cubrir la oferta completa
   de la UJA. La fuerza bruta es correcta y competitiva hoy y deja de serlo
   cuando el corpus crece, porque su coste es lineal. Elegir una base vectorial
   es no tener que reescribir la capa de recuperación ese día.

⚠️ **Cómo enunciar el punto 4 sin pasarse**, que es donde es fácil afirmar de más:
que el diseño *admita* ese crecimiento es una decisión de ingeniería justificada;
que el sistema *escale* a la universidad entera es una afirmación que este trabajo
**no ha medido y no puede sostener**.

Y lo que este argumento **no** es: no vale decir «para no reimplementar lo que ya
existe». Una búsqueda exacta sobre 1,95 MB son unas líneas de NumPy, y si hiciera
falta se escribirían. El ahorro de trabajo no justifica una dependencia; el camino
de crecimiento sí.

### En qué condiciones se revisaría

Las conclusiones valen para **1.334 vectores de 384 dimensiones**. No generalizan
a un corpus de un millón, donde el orden de las candidatas podría invertirse:
Qdrant, que aquí se descarta por complejidad operativa, es la mejor preparada de
las tres para esa escala. Este ADR no mide qué base vectorial es mejor, mide cuál
conviene a este corpus.

De ahí salen las dos premisas identificables que la hacen revisable: **si el
corpus creciera hasta necesitar un índice aproximado**, habría que medirlo
entonces —y ninguna de las cifras de aquí serviría—; y **si el despliegue dejara
de ser un equipo personal**, el argumento de U7 contra el servidor y Docker
perdería casi toda su fuerza.

## Consecuencias

### Positivas

- **La recuperación pasa a ser exacta.** A esta escala LanceDB no construye
  índice y responde por escaneo completo, con fidelidad 1,000 en las 20
  reconstrucciones. Eso tiene una consecuencia práctica que ahorra trabajo:
  **las cifras de recuperación del ADR-0003 se trasladan sin recalcular**, porque
  la base devuelve exactamente lo mismo que la fuerza bruta con la que se
  midieron. Solo habría que volver a medirlas si la fidelidad bajara de 1,000.
- **Se elimina una fuente de no determinismo del sistema.** Con ChromaDB, dos
  reconstrucciones del índice podían dar resultados distintos sin que nada
  fallara; una evaluación de la Fase 2 podría haber medido esa diferencia y
  atribuirla al *prompt* o al modelo.
- **El sistema no adquiere ninguna dependencia de infraestructura.** Sin
  servidor, sin Docker, sin puerto. La Fase 3 despliega una aplicación, no un
  sistema distribuido.
- **Menor memoria residente de las tres** (~22 MiB frente a ~26 y ~150), en una
  máquina donde el modelo generativo de la Fase 2 competirá por ella.
- **El esquema Arrow obliga a declarar el tipo de cada metadato**, incluido el
  vector como `list_(float32, 384)` de tamaño fijo. Es más ceremonia que en
  ChromaDB, y a cambio convierte en error ruidoso lo que en otra sería un dato
  mal guardado en silencio — que es el patrón de fallo que este proyecto ya ha
  sufrido varias veces.

### Negativas

- **Hay que migrar el indexador.** `src/tfg_uja/indexer.py` está escrito contra
  ChromaDB (3 referencias) y `tests/test_indexer.py` monta una colección en
  memoria (6 referencias). Las dos cosas hay que rehacerlas, y `chromadb` sale de
  las dependencias de ejecución mientras entra `lancedb`.
- 🔴 **La distancia coseno hay que declararla en CADA consulta**, no una vez al
  crear la tabla: el valor por defecto de LanceDB es `l2`. Es un invariante del
  mismo tipo que los prefijos `"query: "` y `"passage: "` del ADR-0003 —se olvida
  sin que falle nada visible— con el agravante de que hoy **no cambiaría ni un
  resultado**: `e5-small` entrega los vectores normalizados (norma 1,000000) y
  para norma 1 la euclídea y el coseno ordenan idéntico, así que **la métrica no
  es distinguible con este modelo** y una fidelidad de 1,000 no demuestra que
  ninguna candidata usara la que se le pidió. Se rompería en silencio el día que
  se cambie de modelo. **Debe protegerse con una prueba, no con un comentario.**
- 🔴 **El prefiltrado es el valor por defecto, pero es desactivable**
  (`prefilter=False`, `.postfilter()`). Posfiltrar es un fallo silencioso: el
  sistema respondería «no tengo información» sobre algo que sí está indexado.
  Mismo tratamiento: prueba de regresión con el caso real del experimento.
- 🔴 **No se ha medido ningún índice aproximado.** Dos de las tres candidatas
  respondieron por escaneo completo —medido en el servidor, no deducido— y de
  ChromaDB no se pudo determinar el modo, así que la comparación se hizo sin
  forzar el índice en ninguna. Donde la tabla dice fidelidad 1,000 significa «no
  perdió nada respecto de la fuerza bruta», **no** «su índice es fiel». Este ADR
  no dice nada sobre la calidad de HNSW ni de IVF, y el coste real en fidelidad
  de un índice aproximado a esta escala sigue sin medirse.
- 🔴 **El argumento del camino de crecimiento no está medido.** Es la
  justificación principal para usar una base vectorial y descansa en que LanceDB
  permita crecer sin rehacer la capa de recuperación. Eso es una expectativa
  razonable apoyada en que su índice IVF existe y está documentado, **no un
  resultado**: no se ha ejecutado LanceDB con índice ni a esta escala ni a
  ninguna otra. El día que el corpus lo exija, habrá que medirlo.
- **Las memorias no son homogéneas entre candidatas.** En ChromaDB y LanceDB es
  el delta de RSS del proceso; en Qdrant, el contenedor completo con su sistema
  base. Comparar los dos números es legítimo —es el coste real de cada solución
  en este proyecto— pero **no es «la memoria del algoritmo»**, y por eso el
  argumento de memoria se usa como apoyo y no como criterio principal.
- **Es la más lenta de las tres**, aunque la diferencia esté dentro de la banda de
  U4 y todas estén dos órdenes de magnitud por debajo de U3.
- **Solo se midió K = 10**, el caso más exigente para el índice; K = 3 y K = 5 no
  se comprobaron.
- **Las 20 reconstrucciones no dejan artefacto versionado:**
  `scripts/repeticiones_vectordb.py` imprime por pantalla y la tabla de U6 está
  transcrita de esa ejecución, a diferencia del informe automático, que se
  escribe solo dentro de este fichero.
- **La reproducibilidad depende de una versión concreta** (0.37.1). Los valores
  por defecto que sostienen parte del argumento —la métrica `l2`, el prefiltrado,
  el umbral de «few thousand rows»— pueden cambiar entre versiones. Se fija la
  versión y se declara.
- **Las cifras son las de este corpus** (curso 2026-27) y la fuente sigue viva:
  una recolección posterior movería el número de fragmentos sobre el que se han
  medido.

## Referencias

**Candidatas**

- ChromaDB — [docs.trychroma.com](https://docs.trychroma.com/): filtrado por
  metadatos, arrays y operadores `$contains`/`$not_contains`; parámetros HNSW por
  defecto y `l2` como distancia por defecto; SPANN limitado a Chroma Cloud y
  distribuido. Licencia Apache-2.0 en
  [github.com/chroma-core/chroma](https://github.com/chroma-core/chroma).
- LanceDB — [docs.lancedb.com](https://docs.lancedb.com/): índice vectorial
  opcional, escaneo exhaustivo sin índice, `bypass_vector_index()` y la
  recomendación de «*at least a few thousand rows*»; DataFusion como motor SQL,
  `array_has_any`/`array_has_all`, índice `LABEL_LIST` y prefiltrado por defecto.
  Licencia Apache-2.0 en
  [github.com/lancedb/lancedb](https://github.com/lancedb/lancedb).
- Qdrant — [qdrant.tech/documentation](https://qdrant.tech/documentation/):
  filtrado sobre campos con varios valores, índice de payload y HNSW filtrable.
  [`config/config.yaml`](https://raw.githubusercontent.com/qdrant/qdrant/master/config/config.yaml)
  para `indexing_threshold_kb: 10000`, `full_scan_threshold_kb: 10000`, `m: 16`,
  `ef_construct: 100` y la nota «1Kb = 1 vector of size 256». Licencia Apache-2.0
  en [github.com/qdrant/qdrant](https://github.com/qdrant/qdrant).
- `sqlite-vec` — [github.com/asg017/sqlite-vec](https://github.com/asg017/sqlite-vec):
  «*`sqlite-vec` is a pre-v1, so expect breaking changes!*».

**Método y fundamento**

- Y. A. Malkov, D. A. Yashunin, "Efficient and Robust Approximate Nearest
  Neighbor Search Using Hierarchical Navigable Small World Graphs", *IEEE TPAMI*,
  2020. arXiv:1603.09320
  ([https://arxiv.org/abs/1603.09320](https://arxiv.org/abs/1603.09320)) — el
  índice HNSW que usan ChromaDB y Qdrant.
- M. Aumüller, E. Bernhardsson, A. Faithfull, "ANN-Benchmarks: A Benchmarking
  Tool for Approximate Nearest Neighbor Algorithms", 2018. arXiv:1807.05614
  ([https://arxiv.org/abs/1807.05614](https://arxiv.org/abs/1807.05614)) —
  referencia canónica de la métrica de fidelidad del índice (U1) y de su
  distinción respecto del Recall@K del sistema.

**Del propio proyecto**

- `scripts/experimento_vectordb.py` — el experimento que genera el informe
  incrustado en este ADR.
- `scripts/repeticiones_vectordb.py` — las 20 reconstrucciones con las que se
  comprueba U6.
- ADR-0003 (modelo de incrustaciones) — fija la dimensión de los vectores, el
  techo de recuperación y la normalización que hace indistinguibles las dos
  métricas de distancia.
- ADR-0001 (estrategia de fragmentación) — fija los 1.334 fragmentos sobre los
  que se mide.
- `eval/preguntas_evaluacion.json` — las 50 preguntas usadas como consultas.
- M. Nygard, "Documenting Architecture Decisions", cognitect.com
  ([2011-11-15](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)).

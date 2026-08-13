# ADR-0004: Base de datos vectorial

*Basado en https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions*

- **Estado:** propuesta
- **Fecha:** 2026-08-12
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

## Decisión

_(IT-32, pendiente: a partir de los resultados de arriba.)_

## Consecuencias

_(IT-32, pendiente.)_

## Amenazas a la validez

_(IT-32, pendiente. Ver `04_como_se_mide_una_base_vectorial.md` §4.7 para la
lista ya identificada antes de ejecutar nada.)_

## Referencias

_(IT-32, pendiente.)_

# ADR-0001: Estrategia de chunking del dataset

*Basado en https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions*

- **Estado:** Aceptada
- **Fecha:** 2026-07-06
- **Decisores:** Samuel Blanco Palmero
- **Contexto técnico:** Fase 0 (chunking) del Recomendador UJA

## Contexto

El sistema RAG recupera fragmentos ("chunks") del dataset para responder a
las preguntas del usuario. La forma de trocear el contenido condiciona la
calidad del retrieval: chunks demasiado grandes diluyen la señal y exceden
la ventana de los modelos de embeddings; demasiado pequeños pierden
contexto.

Distribución real medida (no estimada): 296 guías docentes, mediana de
2.677 caracteres de contenido por guía, percentil 90 de 6.450 y máximo de
23.940. Los modelos de embeddings multilingües habituales admiten ~512
tokens (~2.000 caracteres en español), por lo que la mayoría de guías no
cabe en un único chunk.

Restricción de diseño (DoD de IT-08): un chunk nunca puede mezclar
contenido de dos asignaturas distintas.

## Alternativas consideradas

### Opción A — Tamaño fijo con solape
Ventanas de tamaño fijo sobre el texto completo. Trivial, pero corta frases
por la mitad y, sobre el dataset completo, puede mezclar asignaturas
(viola la restricción); el solape duplica contenido. Descartada.

### Opción B — Chunking estructural por unidad semántica (elegida)
La unidad es la asignatura (su guía) o el bloque de salidas de una
titulación; se divide solo si excede el máximo, cortando por párrafos y
frases; los residuos bajo el mínimo se fusionan reequilibrando el par;
encabezado autocontenido con nombre, tipo, ECTS y titulación. Respeta la
restricción por construcción y corta en fronteras naturales. Descartadas
las demás frente a esta.

### Opción C — Chunking semántico por embeddings
Cortar donde cae la similitud de embeddings entre frases. Exige elegir ya
el modelo de embeddings (decisión de Fase 1, ADR-0003, sin experimento aún)
y añade una dependencia pesada a la Fase 0. Prematuro. Descartada.

### Opción D — Un chunk por asignatura sin dividir
El 50 % de las guías supera los 2.675 caracteres y el máximo llega a
23.938: el sobrante se truncaría en silencio en el embedding. Descartada.

## Decisión

Opción B con parámetros iniciales: objetivo 1.200 caracteres, máximo
estricto 1.500 (encabezado incluido) y mínimo 200. Los parámetros son
**provisionales**: el valor definitivo se fijará experimentalmente en la
Fase 1 (Recall@K, MRR, nDCG sobre el conjunto etiquetado de IT-27). Por eso
el chunker es un módulo separado del spider: re-chunkear es barato y no
exige re-scrapear.

### Deduplicación de guías compartidas (revisión, 2026-07-06)

Al medir el corpus se detectó que una parte importante de las guías es
contenido repetido: muchas asignaturas de primeros cursos (Matemáticas I,
Física, Automática industrial...) se imparten en varias titulaciones con la
misma guía byte a byte. Esa redundancia sesga el retrieval: hasta cuatro
copias idénticas podían acaparar el top-K y expulsar resultados diversos.

El diagnóstico inicial se hizo agrupando **solo por contenido**: 31 grupos y
**71 guías excedentes de 296 (24 %)**. Con la clave que finalmente se adopta
—`(nombre, contenido)`, ver más abajo— las cifras son **28 grupos y 68 guías
excedentes de 296 (23 %)**, sobre 96 guías implicadas. Se deja constancia de
ambas porque la diferencia entre las dos claves es justamente el argumento de
esta decisión.

Decisión: **deduplicar en el chunker**. Las guías se agrupan por
`(nombre, contenido)` y cada grupo produce una sola unidad con la lista de
titulaciones en las que se imparte (campos `grados` y `codigos`). La clave
incluye el **nombre y no solo el contenido** porque el fallback de IT-06
puede producir texto idéntico para asignaturas distintas —caso real: las
guías de "Smart Grids" y "Técnicas de ingeniería gráfica" de Eléctrica
comparten el cuerpo de respaldo—, y fusionarlas sería un error. `grados.json`
permanece intacto (fiel a la fuente); la deduplicación es una transformación
de representación en el índice.

Se verificó que el tipo de asignatura y los ECTS **nunca varían** entre
titulaciones que comparten guía (0 de los 28 grupos), por lo que colapsarlos
en el encabezado no pierde información.

Los 3 casos en que un mismo contenido aparece bajo nombres distintos —la
diferencia exacta entre las dos claves (31 - 28)— son:

1. "Fundamentos de la programación" / "Fundamentos de programación"
   (Informática e IA y Ciberseguridad): **falso negativo**, no se agrupan.
2. "Fundamentos físicos de la Informática" / "...de la informática"
   (mismas titulaciones, solo cambia una mayúscula): **falso negativo**.
3. "Smart Grids. Redes Eléctricas Inteligentes" / "Técnicas de ingeniería
   gráfica aplicadas a ingeniería eléctrica" (ambas de Eléctrica, comparten
   6.452 caracteres de cuerpo de respaldo del fallback de IT-06):
   **verdadero negativo**, son asignaturas distintas y NO deben agruparse.

Es decir, la clave `(nombre, contenido)` cuesta 2 falsos negativos y evita 1
falso positivo. Se acepta ese balance: fusionar dos asignaturas distintas
corrompe el índice, mientras que no fusionar dos copias solo lo hace algo
más grande.

## Resultado (medido sobre el dataset real)

Cifras re-verificadas el 21/07/2026 sobre `data/grados.json` y
`data/chunks.json` completos:

- Sin deduplicar: 1.172 chunks (1.098 de guías + 65 + 9).
- **Con deduplicación: 892 chunks** (818 de guías + 65 informativos de
  asignaturas sin guía + 9 de salidas), un **24 % menos** del total.
- Los 280 chunks eliminados son el **25 % de los 1.098 de guía** sin
  deduplicar.
- 28 unidades de guía compartidas entre titulaciones.
- Mínimo 227, mediana 1.093, máximo 1.499 caracteres (0 chunks por encima
  del máximo), 0 inconsistencias de numeración en 301 unidades.
- Verificado por `scripts/check_chunks.py` (en positivo y en negativo).

### Adenda de 2026-07-29 — las mismas cifras sobre el corpus 2026-27

Las cifras de arriba son las del corpus de julio (curso 2025-26, 296 guías) y
se dejan tal cual porque son las que justificaron la decisión. Pero ese corpus
ya no existe: el rastreo del 29/07/2026 trae el curso 2026-27, sin la
titulación en extinción (IT-77), con las tablas de Geomática recuperadas
(IT-76) y con el 100 % de las guías servidas en PDF (DQA-0002). Se vuelven a
medir aquí para que nadie tenga que preguntarse cuál de las dos series es la
buena.

| Magnitud | Corpus 2025-26 (21/07) | Corpus 2026-27 (29/07) |
|---|---:|---:|
| Guías | 296 | 288 |
| Unidades de guía tras deduplicar | 225 | 210 |
| Unidades compartidas entre titulaciones | 28 | 38 |
| Chunks sin deduplicar | 1.172 | 1.134 |
| **Chunks con deduplicación** | **892** (−24 %) | **781** (−31 %) |
| Reparto (guía · sin guía · salidas) | 818 · 65 · 9 | 711 · 62 · 8 |
| Tamaño mín / mediana / p90 / máx | 227 / 1.093 / — / 1.499 | 227 / 1.128 / 1.234 / 1.499 |

**La decisión no cambia, pero su efecto es mayor de lo que decía el ADR:** la
deduplicación quita ahora 353 de los 1.064 chunks de guía, un 33 %, frente al
25 % de julio. El motivo es que las unidades compartidas han pasado de 28 a
38: la fuente publica cada curso más guías comunes entre titulaciones, así que
el argumento que sostiene la deduplicación se refuerza con el tiempo en vez de
desgastarse.

Dos matices que sí son nuevos:

- Las asignaturas sin contenido de guía bajan de 65 a 62, pero **5 de ellas ya
  no son «sin guía» sino «guía publicada y vacía»** (DQA-0004): la EPSJ publica
  el PDF con los rótulos «Resumen» y «Descripción de contenidos» impresos y
  nada debajo. En julio ese caso no existía. El fragmento informativo lo dice
  con otras palabras para no atribuirle a la fuente algo que no ha hecho.
- El máximo de 1.499 sigue por debajo de la restricción dura de 1.500 y ningún
  chunk la supera, verificado por `check_chunks.py` sobre el corpus completo.

Los parámetros (1.200 objetivo, 1.500 máximo, 200 mínimo) **siguen sin
validación experimental propia**. La amenaza que declaraba el ADR en julio
sigue viva y se resuelve en la Fase 1, no aquí.

### 🔴 Corrección de 2026-07-29 — la premisa de los «~512 tokens» era falsa

El apartado «Contexto» de este ADR afirma que «los modelos de embeddings
multilingües habituales admiten ~512 tokens (~2.000 caracteres en español)», y
sobre esa premisa se eligió el máximo de 1.500 caracteres. La lista de
consecuencias positivas remata diciendo que ningún chunk «supera la ventana de
embeddings».

**Medido el 29/07/2026 con el modelo que el sistema monta de verdad
—`paraphrase-multilingual-MiniLM-L12-v2` en `indexer.py`— eso no es cierto.**
Sentence-transformers lo sirve con `max_seq_length = 128`, no con los 512 del
transformador que lleva dentro:

| | |
|---|---:|
| Mediana de fragmento | 264 tokens |
| Máximo | 469 tokens |
| Ventana útil del modelo | 126 tokens |
| **Fragmentos truncados** | **685 de 781 (88 %)** |
| **Tokens del corpus que el modelo llega a leer** | **94.023 de 189.929 (49,5 %)** |

Y `encode` recorta **en silencio**: no avisa, no falla y devuelve un vector de
aspecto normal. Se comprobó de forma directa, no leyendo la configuración:
incrustar un fragmento completo y ese mismo fragmento con la cola sustituida
por texto basura da vectores **idénticos** (coseno 1,0000).

Qué se corrige y qué no:

- **La premisa era falsa, pero la decisión de fragmentación no se toca.** El
  troceo estructural por unidad semántica no depende de la ventana del modelo:
  la restricción de que un chunk nunca mezcle dos asignaturas sigue siendo la
  razón principal, y sigue en pie.
- **Lo que queda invalidado es la justificación del valor 1.500.** Se eligió
  para caber en una ventana que el modelo no tenía. Sigue sin validar, como ya
  decía el ADR, pero ahora se sabe además que la referencia estaba mal.
- **La consecuencia positiva «ni supera la ventana de embeddings» hay que
  leerla tachada** para el modelo de la línea base. Con el modelo que elige el
  **ADR-0003** (`intfloat/multilingual-e5-small`, ventana de 510 útiles) vuelve
  a ser cierta: 0 fragmentos truncados. Es decir, la afirmación no se arregla
  cambiando el troceo, sino cambiando el modelo.
- **Lección, que es la parte que importa:** este ADR daba por buena una cifra
  general sobre «los modelos habituales» sin medirla en el modelo concreto que
  el proyecto usaba. Cuarto caso de la serie de este proyecto en que algo pasa
  desapercibido porque nada lo comprobaba: no falló ningún test, no falló ningún
  verificador, y el sistema llevaba desde IT-30 indexando media guía.

Detalle completo, con la tabla de los cuatro modelos y sus ventanas, en el
**ADR-0003** y en `docs/experimentos/it28-embeddings.md`.

### Revisión de 2026-08-05 — la rejilla completa (IT-16)

#### Por qué se reabre

La Opción C se descartó por una razón de **secuencia**: «exige elegir ya el modelo de
embeddings (decisión de Fase 1, ADR-0003, **sin experimento aún**)». Ese motivo describe un
estado del proyecto que ya no existe: el ADR-0003 se cerró y ratificó en IT-29. Un descarte
por calendario que ya se ha cumplido deja de ser un descarte, así que la alternativa se
mide en vez de darse por buena.

Y al medirla apareció un problema de diseño mayor. Una primera versión del experimento
barría el umbral de la estrategia semántica y **congelaba** los parámetros de las otras dos
en los valores que el proyecto ya usaba. Eso daba a la semántica once intentos y a las demás
uno: quedarse con su mejor resultado la favorecía aunque no hubiera diferencia real, porque
el máximo de once tiradas gana al de una por puro muestreo. La comparación se rehízo como
**rejilla**, con las tres estrategias sobre el mismo eje de tamaño máximo y con el mismo
número de variantes de su parámetro propio.

#### Diseño

`scripts/experimento_fragmentacion.py`, ejecutado el 2026-08-05 sobre `data/grados.json`
con las 50 preguntas del conjunto de evaluación y el modelo del ADR-0003, en CPU.

- **Eje común:** tamaño máximo de 600, 900, 1.200, 1.500 y 1.800 caracteres.
- **Estructural:** tamaño objetivo al 60 %, 80 % y 100 % del máximo.
- **Semántica:** corte en el percentil 30, 50 y 70 de la distribución real de distancias
  coseno entre piezas consecutivas del corpus. Se usa percentil y no una distancia
  absoluta porque el valor absoluto depende del modelo, mientras que el percentil se
  adapta solo a la distribución que ese modelo produzca.
- **Tamaño fijo:** solape del 0 %, 10 % y 20 %. El 0 % entra a propósito, porque un solape
  duplica contenido y le regala oportunidades de ser recuperado.

**45 configuraciones, quince por estrategia.** La única variable que cambia es dónde se
proponen las fronteras: el guion sustituye `chunker._chunks_de_unidad` y deja que
`trocear_dataset` aporte todo lo demás —unidades, deduplicación, encabezados, dobles
grados, planes de estudio y fusión de residuos—, de modo que ninguna diferencia medida
pueda venir de otra parte del proceso. El mínimo de fragmento se mantiene fijo en 200 y se
declara: es una preferencia, no una restricción dura.

La tabla completa de las 45 está en `docs/experimentos/it16-fragmentacion.md`.

#### Resultado 1 — la estrategia casi no importa; el tamaño sí

Ordenadas por acierto por unidad en el primer resultado, las tres estrategias aparecen
mezcladas en la cabeza y en la cola. Lo que ordena la tabla es el **tamaño máximo**. Con
`fijo, solape 0 %`, cambiando solo el máximo:

| Máximo | Fragmentos | RU@1 |
|---:|---:|---:|
| 600 | 2.312 | 0,950 |
| 900 | 1.228 | 0,930 |
| 1.200 | 912 | 0,910 |
| 1.500 | 736 | 0,850 |
| 1.800 | 623 | 0,790 |

Monótono, y el mismo patrón en las otras dos estrategias. **El ADR-0001 comparó lo que menos
influía y declaró «provisional» lo que más.**

#### Resultado 2 — el sesgo que impide quedarse con la primera fila

El orden de RU@1 sigue al número de fragmentos: con 2.312 fragmentos cada unidad tiene unos
siete trozos en el índice y con 884 tiene dos y medio, es decir, siete papeletas frente a
dos y media para caer en el primer puesto. Y hay algo peor: recuperar el primer resultado
de 600 caracteres entrega 600 caracteres de contexto, y el de 1.500 entrega 1.500. **A K
fijo no se está comparando lo mismo.**

Por eso no se elige la primera fila. La comparación que sí aísla el efecto es a **igualdad
de número de fragmentos**:

| Configuración | Fragmentos | RU@1 | MRR |
|---|---:|---:|---:|
| estructural, máx. 900, objetivo 100 % | 1.334 | **0,930** | **0,970** |
| estructural, máx. 1.200, objetivo 60 % | 1.499 | 0,890 | 0,940 |

Con **165 fragmentos menos**, el máximo de 900 gana en las dos métricas. Ahí el conteo ya no
lo explica.

#### Resultado 3 — el truncado, que no depende de ninguna métrica discutible

Contado con el tokenizador del modelo, no estimado:

| Máximo | Fragmentos truncados |
|---:|---:|
| 600, 900, 1.200 | **0** en las nueve configuraciones de cada uno |
| 1.500 | 3 – 4 |
| 1.800 | hasta **29** |

Con 1.800 el modelo deja de leer parte de hasta 29 fragmentos **sin avisar**. Con 1.500 —el
valor vigente hasta ahora— ya hay 3 o 4 en algunas configuraciones. Es la comprobación
directa de que el máximo no se puede subir a ojo, y confirma sobre el terreno la corrección
del 2026-07-29.

#### Qué se decide

1. **La Opción B se confirma, y ahora con evidencia en vez de con un razonamiento.** Las
   tres estrategias son indistinguibles a igualdad de tamaño, de modo que se elige la más
   simple y la única que **no ata el fragmentador al modelo de incrustaciones**: con
   troceo semántico, cambiar de modelo obligaría a re-trocear todo el corpus.
2. **Los parámetros cambian: máximo y objetivo pasan a 900 caracteres**, frente a los 1.500
   y 1.200 anteriores. Dejan de ser provisionales: salen de la rejilla.
3. **La Opción C queda medida y descartada**, ya no aplazada. No es peor, es que no es
   mejor, y cuesta una dependencia que la estructural no tiene.

La configuración vigente hasta esta revisión (estructural, máximo 1.500, objetivo 1.200)
resultó ser **la segunda peor de las 45** en RU@1, con 0,780.

#### Amenazas a la validez de esta revisión

- **Cincuenta preguntas anotadas por una sola persona**, que es además quien construyó el
  sistema. Una diferencia de una pregunta vale 0,020: las diferencias de ese orden que
  aparecen en la tabla **no son distinguibles** de lo que movería otra anotación.
- **RU@K no es del todo inmune al troceo**, como se explica en el resultado 2. La decisión
  se apoya en la comparación a igualdad de fragmentos, no en el orden bruto de la tabla.
- **No se ha medido el efecto sobre la generación**, que es donde la fragmentación actúa de
  verdad: si un fragmento parte una definición y solo llega la mitad, la recuperación
  puntúa igual de bien y la respuesta sale peor. Eso exige métricas de la Fase 2.
- **El mínimo de fragmento no se barrió.** Queda como el único parámetro sin validar.

### Aplicación de 2026-08-06 — lo que salió al cambiarlo de verdad (IT-16)

La rejilla se midió con un guion que sustituía la colocación de los cortes y dejaba que el
fragmentador de producción hiciera todo lo demás. Un experimento así puede medir algo que
luego el sistema no reproduce, así que se anota aparte lo que ocurrió al aplicar la decisión.

**El corpus pasa de 884 a 1.334 fragmentos, que es exactamente la cifra que predijo la
rejilla** para «estructural, máximo 900, objetivo 100 %». Que coincida al fragmento es la
comprobación de que el guion no medía una fragmentación distinta de la real.

| | Antes (1.500 / 1.200) | Ahora (900 / 900) |
| --- | ---: | ---: |
| Fragmentos | 884 | 1.334 |
| Guía · sin guía · plan · salidas | 761 · 86 · 24 · 13 | 1.193 · 86 · 33 · 22 |
| Unidades | 322 | 322 |
| Tamaño mín / mediana / p90 / máx | 227 / 1.139 / 1.267 / 1.498 | 171 / 838 / 894 / 900 |
| Fragmentos truncados por el modelo | 0 | 0 |

`check_dataset.py` no cambia (528 asignaturas, 288 guías, 8 salidas): trocear distinto no
toca el dataset, solo el corpus derivado. Las unidades tampoco: siguen siendo 322, porque la
fragmentación reparte dentro de la unidad y no crea ni destruye ninguna.

#### Las métricas se vuelven a medir sobre el corpus real, no sobre el del experimento

| Métrica | Rejilla (guion) | Producción (`data/chunks.json`) |
| --- | ---: | ---: |
| RU@1 | 0,930 | **0,930** |
| RU@3 | 0,985 | **0,985** |
| MRR | 0,970 | **0,970** |
| Truncados | 0 | **0** |

Coinciden en las tres cifras, no solo en el número de fragmentos. La sustitución que hacía
el guion queda validada y sus 45 filas se pueden leer como lo que el sistema haría.

Aparecen además dos cosas que la rejilla no reportaba:

- **RU@10 sube de 0,995 a 1,000.** Con 884 fragmentos quedaba una pregunta sin acierto ni
  siquiera con diez unidades: P-008, sobre las salidas profesionales de los grados de la
  rama industrial, que es una pregunta de agregación sin fragmento agregado que la conteste.
  Con el troceo fino entra. No es un resultado grande —hablamos de una pregunta de
  cincuenta— pero sí es la primera vez que el conjunto entero se recupera.
- **El fragmento más largo del corpus ocupa 335 tokens, y la mediana 204**, sobre una
  ventana de 512. Es decir: **la configuración ganadora deja la ventana del modelo a dos
  tercios de su capacidad**, y aun así recupera mejor que las que la llenaban. Eso derriba
  del todo la premisa con la que se eligió el 1.500 original, que era aprovechar los ~512
  tokens: el problema nunca fue desaprovechar la ventana, sino que un fragmento largo mezcla
  varios asuntos y su vector queda a medio camino de todos ellos.

La cobertura por fragmento, en cambio, **empeora** (R@3 pasa de 0,965 a 0,697). No es una
regresión: al multiplicarse los fragmentos de cada unidad, el denominador de esa métrica
crece y su techo baja. Es justamente por lo que la métrica comparable entre dos
fragmentaciones distintas es la de unidad y no la de fragmento.

#### Un defecto que solo apareció al bajar el máximo

`check_chunks.py` **falló**, y al mirarlo el equivocado era el verificador. Exigía
`len(texto) >= TAMANO_MINIMO` sin excepciones, es decir, trataba el mínimo como restricción
dura cuando la decisión 5 de este proyecto dice lo contrario: el máximo es duro y el mínimo
es una preferencia. El propio `_fusionar_pequenos` lo documenta —«alguno puede quedar por
debajo del mínimo si no había manera de evitarlo»— porque unir una cola corta a su vecino a
veces desborda el máximo, y romper la restricción dura es peor.

Con el máximo en 1.500 ese caso no llegaba a darse sobre el corpus real y la comprobación
pasaba sin que nadie notara que era incorrecta. Con 900 aparecen **seis colas de entre 171 y
196 caracteres**, el 0,45 % del corpus, todas el último fragmento de su unidad y todas
legítimas.

La corrección no afloja el umbral: aflojarlo con un margen sería repetir el error del margen
de 250 caracteres que ocultó 40 fragmentos por encima del máximo. Se sustituye por el
**invariante exacto** —un fragmento corto solo es admisible si unirlo a su vecino desbordaría
el máximo—, reconstruyendo la unión igual que la haría el fragmentador. El recuento de colas
se imprime como estadística, para que una subida se vea.

Se aprovecha para quitar de ese guion la copia a mano de `TAMANO_MAXIMO` y `TAMANO_MINIMO`,
que se justificaba diciendo que el verificador corría en CI. No corre: `data/` no está
versionado. De haberse quedado la copia, el verificador habría seguido exigiendo `<= 1500`
sobre un corpus cuyo máximo es 900, que se cumple siempre; habría pasado en verde sin
verificar nada. Es el mismo patrón que los encabezados cruzados de IT-91.

**Coste de la decisión que la rejilla no medía:** con 900, el mínimo empieza a rozarse. No
pasaba con 1.500. Es un argumento más para no bajar a 600, donde el margen entre mínimo y
máximo se estrecha todavía más y las colas irreducibles serían bastantes más.

## Consecuencias

### Positivas
- Ningún chunk mezcla asignaturas ni supera la ventana de embeddings.
  ⚠️ **La segunda mitad de esta frase es falsa para el modelo de la línea base**
  (88 % de fragmentos truncados) y solo es cierta con el modelo del ADR-0003.
  Ver la corrección del 29/07/2026, más arriba.
- Se elimina el 28 % de redundancia del índice de guías y el sesgo que
  causaba en el retrieval.
- Chunks autocontenidos; las 65 asignaturas sin guía quedan representadas
  con un chunk informativo explícito, no como huecos.
- Consulta filtrada por titulación posible: el campo `grados` es una lista y
  los vector DB filtran por pertenencia.

### Negativas
- El tamaño de chunk no tiene todavía validación experimental propia
  (amenaza reconocida; se resuelve en Fase 1).
- Dos asignaturas compartidas con el nombre escrito de forma distinta no se
  deduplican (falso negativo conservador; impacto: 2 de 31 grupos).
- El fallback de IT-06 puede producir texto idéntico para asignaturas
  distintas: no afecta a la deduplicación (la clave usa el nombre), pero
  revela que esos chunks de respaldo son poco informativos (amenaza a la
  validez de construcción, anotada para la Fase 1).
- Sin solape entre chunks: hipótesis a contrastar en Fase 1.

## Referencias
- Documentación de LangChain, "Text splitters":
  [https://python.langchain.com/docs/concepts/text_splitters/](https://python.langchain.com/docs/concepts/text_splitters/)
- Pinecone, "Chunking strategies for LLM applications":
  [https://www.pinecone.io/learn/chunking-strategies/](https://www.pinecone.io/learn/chunking-strategies/)
- Documentación de Sentence-Transformers (límite de secuencia de los
  modelos): [https://www.sbert.net/](https://www.sbert.net/)
- M. Nygard, "Documenting Architecture Decisions", cognitect.com
  ([2011-11-15](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)).

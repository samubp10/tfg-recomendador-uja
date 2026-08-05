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

### 🔴 Revisión de 2026-08-05 — el motivo por el que se descartó la Opción C ha caducado

La Opción C (chunking semántico por embeddings) se descartó por una razón de
**secuencia**, no de calidad: «exige elegir ya el modelo de embeddings (decisión
de Fase 1, ADR-0003, **sin experimento aún**)». Esa frase describe un estado del
proyecto que ya no existe. El ADR-0003 está cerrado y ratificado, el modelo es
`intfloat/multilingual-e5-small`, y por tanto **hoy nada impide implementar la
Opción C**. Un motivo de calendario que ya se ha cumplido deja de ser un motivo.

Se plantea entonces la pregunta directa: ¿hay que probarla ahora? Se responde
midiendo qué podría enseñar el experimento **antes** de ejecutarlo.

#### Lo que un experimento de fragmentación podría resolver hoy

Medido el 2026-08-05 sobre el corpus vigente (884 fragmentos, 322 unidades) con
el modelo del ADR-0003 y las 50 preguntas del conjunto de evaluación:

| Métrica | Valor | Margen hasta su techo | En preguntas de 50 |
|---|---:|---:|---:|
| Acierto por unidad, K=3 | 0,965 | 0,035 | 1,75 |
| **Acierto por unidad, K=5** | **0,990** | **0,010** | **0,5** |
| Acierto por unidad, K=10 | 0,995 | 0,005 | 0,25 |
| Cobertura por fragmento, K=5 | 0,849 | 0,114 (techo 0,963) | — |

Y la estructura del corpus explica por qué: la mediana de una unidad son **2
fragmentos**, y **116 de las 322 unidades caben en uno solo**, de modo que en más
de un tercio del corpus la estrategia de troceo no llega ni a intervenir.

🔴 **Hay un problema metodológico que pesa más que los márgenes.** La cobertura
por fragmento **no es comparable entre dos fragmentaciones distintas**: al
cambiar el troceo cambia cuántos fragmentos tiene cada unidad, es decir, cambia
el denominador de la propia métrica y también su techo. Una fragmentación que
produjese trozos más grandes subiría esa cifra sin recuperar mejor: estaría
moviendo la vara, no saltando más alto. La única métrica que sí se puede
comparar entre fragmentaciones es el acierto por unidad, porque el conjunto de
evaluación anota unidades y no fragmentos.

Juntando las dos cosas: **la única métrica comparable está saturada en 0,990, y
las que tienen margen no son comparables.** Un experimento entre estrategias de
fragmentación produciría, en el mejor de los casos, una diferencia de media
pregunta sobre cincuenta, que es menos que la resolución del propio conjunto
(1/50 = 0,02). No se podría distinguir de la variación de una anotación
distinta.

#### Qué se decide en esta revisión

**La Opción B se mantiene, y la Opción C queda aplazada a la Fase 2, no
descartada.** El motivo que se registra a partir de ahora **no es la secuencia
del proyecto ni el coste de reindexar** —el autor ha manifestado explícitamente
que asume ese coste—, sino que **el experimento no puede resolver la pregunta
con los instrumentos de medida disponibles hoy**.

Esto no es un tecnicismo, es dónde actúa realmente la fragmentación. Las métricas
de recuperación responden a «¿ha encontrado la asignatura correcta?», y la
respuesta ya es «casi siempre». Lo que la fragmentación decide de verdad es si el
trozo que llega al modelo generativo **se entiende por sí solo**: si una
definición queda partida entre dos fragmentos y solo llega la mitad, la
recuperación puntúa igual de bien y la respuesta sale peor. Eso lo miden las
métricas de generación, que no existirán hasta la Fase 2.

**Condición explícita de reapertura**, para que no quede como una promesa vaga:
si la evaluación de la generación encuentra fallos de fidelidad atribuibles a
fragmentos que parten el contexto, se reabre este ADR y se compara la Opción C
contra la B **con métricas de generación**, no de recuperación.

#### Consecuencia para la memoria

La Tabla de estrategias del Capítulo 4 no puede seguir diciendo que la Opción C
es «prematura», porque ya no lo es. El motivo del descarte hay que sustituirlo
por el de esta revisión: aplazada por falta de un instrumento de medida capaz de
distinguirla, con su condición de reapertura escrita.

### Adenda de 2026-08-05 — cifras del corpus tras IT-101

Las series anteriores tampoco son ya las vigentes. IT-101 incorporó los planes de
estudio de los dobles grados y los fragmentos agregados de plan de estudios:

| Magnitud | Corpus 2026-27 (29/07) | Corpus vigente (05/08) |
|---|---:|---:|
| Guías | 288 | 288 |
| **Fragmentos** | **781** | **884** |
| Reparto | 711 guía · 62 sin guía · 8 salidas | 761 guía · 86 sin guía · 24 plan de estudios · 13 salidas |
| Unidades | — | 322 |
| Tamaño mín / mediana / p90 / máx | 227 / 1.128 / 1.234 / 1.499 | 227 / 1.139 / 1.267 / **1.498** |

El máximo sigue por debajo de la restricción dura de 1.500 y ningún fragmento la
supera. Los parámetros (1.200 / 1.500 / 200) **continúan sin validación
experimental propia**, y por lo dicho arriba tampoco la tendrán en la Fase 1: la
amenaza se mantiene declarada y pasa a trabajo futuro.

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

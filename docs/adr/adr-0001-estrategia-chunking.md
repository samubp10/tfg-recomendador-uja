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

## Consecuencias

### Positivas
- Ningún chunk mezcla asignaturas ni supera la ventana de embeddings.
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

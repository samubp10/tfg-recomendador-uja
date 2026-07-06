# ADR-0001: Estrategia de chunking del dataset

*Basado en <https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>*

- **Estado:** Aceptada
- **Fecha:** 07/07/2026
- **Decisores:** Samuel Blanco Palmero
- **Contexto técnico:** Fase 0 (scraping + chunking) del Recomendador UJA

## Contexto

El sistema RAG recupera fragmentos ("chunks") del dataset para responder a
las preguntas del usuario. La forma de trocear el contenido condiciona
directamente la calidad de la respuesta: chunks demasiado grandes diluyen la
respuesta y exceden la ventana de los modelos de embeddings; demasiado pequeños
pierden calidad y contexto.

La distribución real del dataset (medida, no estimada) condiciona la
decisión: 296 guías docentes con una mediana de 2.675 caracteres de
contenido por guía, percentil 90 de 6.450 y un máximo de 23.938 (guía de
"Simulación de flujos industriales"). Los modelos de embeddings
multilingües habituales admiten aproximadamente 512 tokens (alrededor de 2.000 caracteres en español),
por lo que la mayoría de guías no cabe en un único chunk.

Restricción de diseño (Definición de Hecho del item de trabajo IT-08): un chunk nunca puede
mezclar contenido de dos asignaturas, porque una respuesta sobre una
asignatura contaminada con el temario de otra sería un error grave del
recomendador.

## Alternativas consideradas

### Opción A — Tamaño fijo con solape (sliding window)

División del texto completo en ventanas de tamaño fijo (p. ej. 500
caracteres con solape de 50). Es la técnica por defecto en muchos tutoriales
de RAG por ser muy sencilla de implementar.

- **Pros:** muy sencilla de implementar; tamaño de chunk uniforme.
- **Contras:** corta frases y párrafos por la mitad; aplicada sobre el
  dataset completo puede mezclar dos asignaturas en un chunk, violando la
  restricción de diseño; el solape duplica contenido en el índice.

### Opción B — Chunking estructural por unidad semántica (elegida)

La unidad es la asignatura (su guía docente) o el bloque de salidas de un
grado. Una unidad solo se divide si excede el tamaño máximo, cortando por
párrafos y, dentro de un párrafo largo, por frases; los fragmentos
residuales por debajo del mínimo se fusionan con su vecino (reequilibrando
el par si la fusión excediera el máximo). Cada chunk se hace autocontenido
anteponiendo un encabezado con la asignatura, su carácter, sus ECTS y su
grado.

- **Pros:** respeta la restricción de no mezclar asignaturas por
  construcción; los cortes caen en fronteras naturales del texto; los
  chunks son autocontenidos al recuperarse de forma aislada.
- **Contras:** tamaño de chunk variable (acotado entre mínimo y máximo) por lo 
que conlleva algo más de complejidad que la opción A.

### Opción C — Chunking semántico por embeddings

Cortar donde cae la similitud de embeddings entre frases consecutivas.

- **Pros:** cortes potencialmente más coherentes semánticamente.
- **Contras:** exige elegir ya un modelo de embeddings, decisión que
  corresponde a la Fase 1, por lo que será más adelante, además de que aún no 
  tiene experimento que la respalde, y que añade una dependencia pesada a la 
  Fase 0, por último, el beneficio sobre la opción B no está demostrado para 
  textos ya estructurados como los temarios.

### Opción D — Un chunk por asignatura, sin dividir

- **Pros:** máxima simplicidad; ninguna asignatura se fragmenta.
- **Contras:** La mayoría de las guías supera los 2.675 caracteres y el máximo 
  llega a 23.938: chunks así exceden la ventana de los modelos de embeddings
  (el contenido sobrante se truncaría en silencio) y diluyen la precisión de 
  la respuesta.

## Decisión

Se adopta la **opción B** con estos parámetros iniciales: tamaño objetivo
de 1.200 caracteres, máximo estricto de 1.500 (encabezado incluido) y
mínimo de 200. Sobre el dataset real produce 1.174 chunks (1.098 de guías,
65 informativos de asignaturas sin guía, 11 de salidas profesionales), con
mediana de 1.098 caracteres y máximo de 1.499; los invariantes se
comprueban con `scripts/check_chunks.py`.

Los parámetros son **provisionales**: el valor definitivo del tamaño se
fijará experimentalmente en la Fase 1 midiendo el retrieval (Recall@K,
MRR, nDCG) sobre el conjunto de evaluación etiquetado (IT-27). Por eso el
chunking vive en un módulo separado del spider: re-chunkear con otros
parámetros es barato y no exige hacer de nuevo scraping.

## Consecuencias

### Positivas

- Ningún chunk mezcla asignaturas ni supera la ventana de embeddings.
- Chunks autocontenidos: un fragmento intermedio de un temario identifica
  su asignatura y su grado.
- Las asignaturas sin guía quedan representadas con un chunk informativo
  explícito, no como huecos silenciosos.
- Volver a hacer el chunking con otros parámetros es barato, no exige hacer de nuevo scraping: permite el experimento de tamaño de la Fase 1.

### Negativas

- El tamaño de chunk elegido no tiene todavía validación experimental
  propia (amenaza reconocida; se resuelve en Fase 1).
- Las guías compartidas entre grados (p. ej. "Matemáticas I" de
  Organización Industrial y de Eléctrica, byte a byte idénticas) generan
  chunks casi duplicados que difieren solo en el encabezado. Se mantienen
  porque el metadato de grado es relevante para consultas dirigidas; si en
  la Fase 1 se observa que sesgan el retrieval, se evaluará deduplicar.
- No se usa solape entre chunks: se asume que el encabezado y el corte por
  fronteras naturales lo hacen innecesario. Es una hipótesis a contrastar
  en la Fase 1.

## Referencias

- Documentación de LangChain, "Text splitters":
  [https://python.langchain.com/docs/concepts/text_splitters/](https://python.langchain.com/docs/concepts/text_splitters/)
- Pinecone, "Chunking strategies for LLM applications":
  [https://www.pinecone.io/learn/chunking-strategies/](https://www.pinecone.io/learn/chunking-strategies/)
- Documentación de Sentence-Transformers (límite de secuencia de los
  modelos): [https://www.sbert.net/](https://www.sbert.net/)
- M. Nygard, "Documenting Architecture Decisions", cognitect.com
  ([2011-11-15](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)).

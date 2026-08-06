# IT-28 — Ejecuciones anteriores del experimento de embeddings

`it28-embeddings.md` lo reescribe el script en cada ejecución, así que solo
conserva la última. Aquí quedan las anteriores, con el corpus contra el que se
midieron.

Esto no es un archivo por nostalgia: el corpus cambia (la fuente publica guías
nuevas, se regenera el dataset) y una métrica de recuperación no significa nada
sin decir sobre cuántos fragmentos se calculó. Comparar dos ejecuciones sobre
corpus distintos es comparar dos cosas distintas; tenerlas separadas y fechadas
permite además una pregunta que sí es interesante: **si el orden de los modelos
se mantiene al cambiar el corpus, el resultado es más robusto que si depende de
una foto concreta.**

---

## 24/07/2026 — corpus de 892 fragmentos (curso 2025-26)

Primera ejecución. Dataset del 09/07/2026: 13 titulaciones, 361 asignaturas,
296 guías, todas por el camino HTML salvo 62. Conjunto de evaluación de IT-27
con las 36 preguntas originales (17 temario · 8 salidas · 6 metadatos ·
5 sin guía).

| Modelo | Recall@3 | Recall@5 | MRR | Tiempo (s) |
|---|---|---|---|---|
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | 0.407 | 0.526 | 0.594 | 42.0 |
| sentence-transformers/paraphrase-multilingual-mpnet-base-v2 | 0.490 | 0.622 | 0.712 | 179.5 |
| intfloat/multilingual-e5-small | 0.677 | 0.833 | 0.870 | 109.7 |
| hiiamsid/sentence_similarity_spanish_es | 0.299 | 0.315 | 0.458 | 255.9 |

Amenaza a la validez que arrastra esta ejecución y hay que declarar en el
ADR-0003: **los umbrales de la hipótesis no se fijaron antes de medir.** Que el
ganador saque tanta ventaja no lo arregla.

---

## 29/07/2026 — corpus de 781 fragmentos, 36 preguntas, 4 modelos

Segunda ejecucion sobre el corpus 2026-27, ya con las columnas de ventana
y truncado. Es la que sostiene el ADR-0003 tal como se escribio.

Se archiva aqui porque IT-100 rehace el experimento con dos cambios que la
dejan sin comparar: entran tres modelos mas (todos de ventana >= 512, para
que la comparacion sea en igualdad de condiciones) y el corpus pasa a 797
fragmentos y 50 preguntas al incorporar los listados de plan de estudios.

| Modelo | Recall@3 | Recall@5 | MRR | Tiempo (s) | Ventana (tokens) | Fragmentos truncados | Corpus leído |
|---|---|---|---|---|---|---|---|
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | 0.420 | 0.570 | 0.619 | 63.9 | 126 | 685 | 50% |
| sentence-transformers/paraphrase-multilingual-mpnet-base-v2 | 0.584 | 0.668 | 0.730 | 125.1 | 126 | 685 | 50% |
| intfloat/multilingual-e5-small | 0.705 | 0.787 | 0.856 | 108.5 | 510 | 0 | 100% |
| hiiamsid/sentence_similarity_spanish_es | 0.233 | 0.302 | 0.381 | 281.1 | 510 | 1 | 100% |

## 04/08/2026 — corpus de 797 fragmentos, 50 preguntas, candidatos de ventana >= 512

Primera ejecución en igualdad de condiciones: los cuatro candidatos leen el corpus entero.
Salen los dos modelos *paraphrase* de ventana 128 y entran `e5-large` y `bge-m3`. Corpus del
rastreo del 01/08/2026, con los fragmentos de plan de estudios de IT-100 y **el troceado
todavía con el máximo en 1.500 caracteres**.

| Modelo | R@3 | R@5 | R@10 | RU@3 | RU@5 | RU@10 | MRR | Tiempo (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| intfloat/multilingual-e5-small | 0,771 | 0,835 | 0,938 | 0,945 | 0,970 | 1,000 | 0,881 | 61,3 |
| intfloat/multilingual-e5-large | 0,831 | 0,936 | 0,985 | 0,995 | 1,000 | 1,000 | 0,948 | 485,8 |
| BAAI/bge-m3 | 0,808 | 0,895 | 0,973 | 0,950 | 0,990 | 0,995 | 0,955 | 475,6 |
| hiiamsid/sentence_similarity_spanish_es | 0,168 | 0,218 | 0,273 | 0,320 | 0,400 | 0,480 | 0,278 | 140,7 |

Recall@5 por tipo de pregunta:

| Modelo | listado (14) | metadatos (6) | salidas (8) | sin_guia (2) | temario (20) |
|---|---:|---:|---:|---:|---:|
| e5-small | 1,000 | 0,602 | 0,812 | 1,000 | 0,782 |
| e5-large | 1,000 | 0,870 | 1,000 | 1,000 | 0,878 |
| bge-m3 | 1,000 | 0,787 | 0,938 | 1,000 | 0,826 |
| hiiamsid | 0,000 | 0,111 | 0,188 | 1,000 | 0,336 |

Es la ejecución sobre la que se escribió la adenda del 04/08 del ADR-0003 y la que sostiene
la ratificación de `e5-small`. **Sus dos argumentos principales quedan matizados por la
ejecución del 06/08**, hecha ya con el troceado de IT-16: allí la distancia entre el modelo
pequeño y el grande se reduce a la décima parte y el MRR se iguala, de modo que la
ratificación deja de depender de operar con diez resultados por consulta.

Techos de exhaustividad por fragmento sobre este corpus: 0,905 (K=3), 0,977 (K=5) y
0,998 (K=10).

## Cómo leer las tres últimas columnas

«Ventana» es el `max_seq_length` del modelo tal como lo sirve sentence-transformers, descontados los dos tokens especiales. Todo lo que pase de ahí `encode` lo recorta **en silencio**: no avisa, no falla y devuelve un vector de aspecto normal. «Corpus leído» es la proporción de tokens del corpus que el modelo llega a mirar, así que una diferencia de Recall entre dos modelos con ventanas distintas no se puede atribuir solo a la calidad de sus representaciones.

## Modelos evaluados

- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`: Modelo provisional actual del indexador (IT-30): línea base.
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`: Misma familia que la línea base, mayor tamaño (mpnet-base vs MiniLM-L12).
- `intfloat/multilingual-e5-small`: Modelo orientado a recuperación; exige prefijos 'query:'/'passage:' según su model card, aplicados aquí.
- `hiiamsid/sentence_similarity_spanish_es`: Específico de español (no multilingüe): contraste frente a los tres anteriores.

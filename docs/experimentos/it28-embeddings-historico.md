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

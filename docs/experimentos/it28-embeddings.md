# IT-28 — Resultados del experimento comparativo de embeddings

Generado ejecutando `py scripts/experimento_embeddings.py` contra el dataset real (781 chunks, 36 preguntas de eval/preguntas_evaluacion.json).

| Modelo | Recall@3 | Recall@5 | MRR | Tiempo (s) |
|---|---|---|---|---|
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | 0.420 | 0.570 | 0.619 | 40.0 |
| sentence-transformers/paraphrase-multilingual-mpnet-base-v2 | 0.584 | 0.668 | 0.730 | 86.2 |
| intfloat/multilingual-e5-small | 0.705 | 0.787 | 0.856 | 70.0 |
| hiiamsid/sentence_similarity_spanish_es | 0.233 | 0.302 | 0.381 | 174.5 |

## Modelos evaluados

- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`: Modelo provisional actual del indexador (IT-30): línea base.
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`: Misma familia que la línea base, mayor tamaño (mpnet-base vs MiniLM-L12).
- `intfloat/multilingual-e5-small`: Modelo orientado a recuperación; exige prefijos 'query:'/'passage:' según su model card, aplicados aquí.
- `hiiamsid/sentence_similarity_spanish_es`: Específico de español (no multilingüe): contraste frente a los tres anteriores.

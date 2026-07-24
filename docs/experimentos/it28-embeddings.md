# IT-28 — Resultados del experimento comparativo de embeddings

Generado ejecutando `py scripts/experimento_embeddings.py` contra el dataset real (892 chunks, 36 preguntas de eval/preguntas_evaluacion.json).

| Modelo | Recall@3 | Recall@5 | MRR | Tiempo (s) |
|---|---|---|---|---|
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | 0.407 | 0.526 | 0.594 | 42.0 |
| sentence-transformers/paraphrase-multilingual-mpnet-base-v2 | 0.490 | 0.622 | 0.712 | 179.5 |
| intfloat/multilingual-e5-small | 0.677 | 0.833 | 0.870 | 109.7 |
| hiiamsid/sentence_similarity_spanish_es | 0.299 | 0.315 | 0.458 | 255.9 |

## Modelos evaluados

- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`: Modelo provisional actual del indexador (IT-30): línea base.
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`: Misma familia que la línea base, mayor tamaño (mpnet-base vs MiniLM-L12).
- `intfloat/multilingual-e5-small`: Modelo orientado a recuperación; exige prefijos 'query:'/'passage:' según su model card, aplicados aquí.
- `hiiamsid/sentence_similarity_spanish_es`: Específico de español (no multilingüe): contraste frente a los tres anteriores.

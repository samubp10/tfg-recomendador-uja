# IT-28 — Resultados del experimento comparativo de embeddings

Generado ejecutando `py scripts/experimento_embeddings.py` contra el dataset real (781 chunks, 36 preguntas de eval/preguntas_evaluacion.json).

| Modelo | Recall@3 | Recall@5 | MRR | Tiempo (s) | Ventana (tokens) | Fragmentos truncados | Corpus leído |
|---|---|---|---|---|---|---|---|
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | 0.420 | 0.570 | 0.619 | 63.9 | 126 | 685 | 50% |
| sentence-transformers/paraphrase-multilingual-mpnet-base-v2 | 0.584 | 0.668 | 0.730 | 125.1 | 126 | 685 | 50% |
| intfloat/multilingual-e5-small | 0.705 | 0.787 | 0.856 | 108.5 | 510 | 0 | 100% |
| hiiamsid/sentence_similarity_spanish_es | 0.233 | 0.302 | 0.381 | 281.1 | 510 | 1 | 100% |

## Cómo leer las tres últimas columnas

«Ventana» es el `max_seq_length` del modelo tal como lo sirve sentence-transformers, descontados los dos tokens especiales. Todo lo que pase de ahí `encode` lo recorta **en silencio**: no avisa, no falla y devuelve un vector de aspecto normal. «Corpus leído» es la proporción de tokens del corpus que el modelo llega a mirar, así que una diferencia de Recall entre dos modelos con ventanas distintas no se puede atribuir solo a la calidad de sus representaciones.

## Modelos evaluados

- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`: Modelo provisional actual del indexador (IT-30): línea base.
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`: Misma familia que la línea base, mayor tamaño (mpnet-base vs MiniLM-L12).
- `intfloat/multilingual-e5-small`: Modelo orientado a recuperación; exige prefijos 'query:'/'passage:' según su model card, aplicados aquí.
- `hiiamsid/sentence_similarity_spanish_es`: Específico de español (no multilingüe): contraste frente a los tres anteriores.

# IT-28 — Resultados del experimento comparativo de embeddings

Generado el 04/08/2026 ejecutando `py scripts/experimento_embeddings.py` contra `data/chunks.json` (797 fragmentos, 50 preguntas de `eval/preguntas_evaluacion.json`), en **CPU**.

| Modelo | R@3 | R@5 | R@10 | RU@3 | RU@5 | RU@10 | MRR | Tiempo (s) | Ventana | Truncados | Corpus leído |
|---|---|---|---|---|---|---|---|---|---|---|---|
| intfloat/multilingual-e5-small | 0.771 | 0.835 | 0.938 | 0.945 | 0.970 | 1.000 | 0.881 | 61.3 | 510 | 0 | 100% |
| intfloat/multilingual-e5-large | 0.831 | 0.936 | 0.985 | 0.995 | 1.000 | 1.000 | 0.948 | 485.8 | 510 | 0 | 100% |
| BAAI/bge-m3 | 0.808 | 0.895 | 0.973 | 0.950 | 0.990 | 0.995 | 0.955 | 475.6 | 8190 | 0 | 100% |
| hiiamsid/sentence_similarity_spanish_es | 0.168 | 0.218 | 0.273 | 0.320 | 0.400 | 0.480 | 0.278 | 140.7 | 510 | 1 | 100% |

## Recall@5 por tipo de pregunta

| Modelo | listado (n=14) | metadatos (n=6) | salidas (n=8) | sin_guia (n=2) | temario (n=20) |
|---|---|---|---|---|---|
| intfloat/multilingual-e5-small | 1.000 | 0.602 | 0.812 | 1.000 | 0.782 |
| intfloat/multilingual-e5-large | 1.000 | 0.870 | 1.000 | 1.000 | 0.878 |
| BAAI/bge-m3 | 1.000 | 0.787 | 0.938 | 1.000 | 0.826 |
| hiiamsid/sentence_similarity_spanish_es | 0.000 | 0.111 | 0.188 | 1.000 | 0.336 |

La media general no se puede leer sin este desglose. Las preguntas de tipo `listado` piden **todas** las asignaturas de un grupo, así que su techo depende de cuántas unidades relevantes tengan y no de lo bien que recupere el modelo.

## Cómo leer las columnas

- **R@K** es Recall@K por **fragmento**: cuántos de los trozos de la unidad correcta se han recuperado. Mide cobertura. **Su techo no es 1**, porque una unidad repartida en más de K fragmentos no cabe entera en el top-K: sobre este corpus el máximo posible es **0.905** para R@3, **0.977** para R@5, **0.998** para R@10. Hay que restar del techo, no de 1, para saber lo que falta de verdad.
- **RU@K** es Recall@K por **unidad**: si se ha encontrado la asignatura correcta, sin castigar que falte alguno de sus trozos. Mide acierto, y su techo sí es 1.
- Las dos van juntas a propósito. La primera describe el sistema tal como está hoy; la segunda, el sistema con expansión por unidad, que todavía no existe. **La brecha entre ambas es el dato**: dice si lo que falla es encontrar la asignatura o completarla.
- **Ventana** es el `max_seq_length` con el que sentence-transformers sirve el modelo, descontados los dos tokens especiales. Todo lo que pase de ahí, `encode` lo recorta **en silencio**: no avisa, no falla y devuelve un vector de aspecto normal. Por eso una diferencia de Recall entre modelos de ventana distinta no se puede atribuir solo a la calidad de sus representaciones.
- **Tiempo** es reloj de pared de un portátil que está haciendo otras cosas, así que solo separa órdenes de magnitud. Medido: entre dos ejecuciones seguidas del 04/08/2026 **todas las métricas salieron idénticas a tres decimales**, pero los tiempos variaron hasta un 25 % y los dos modelos grandes llegaron a intercambiarse el orden. Sirve para decir «este tarda cinco veces más que aquel», no para ordenar dos modelos que quedan cerca.

⚠️ Recall@K es **monótono creciente en K**: mirar más resultados no puede reducir los aciertos. Que K=10 gane a K=5 es una propiedad de la métrica, no un hallazgo. Lo que decide K es el coste de contexto y la distracción del generador, y eso se mide en la Fase 2.

## Modelos evaluados

- `intfloat/multilingual-e5-small`: PEQUEÑO / titular. El elegido en el ADR-0003 y ganador de IT-28. Orientado a recuperación; exige prefijos 'query:'/'passage:' según su ficha, aplicados aquí. 118M parámetros, 384 dimensiones, MIT.
- `intfloat/multilingual-e5-large`: GRANDE 1. Misma familia, mismo entrenamiento y mismos prefijos que el titular, con 5x su tamaño: es el único par que aísla el efecto del TAMAÑO sin cambiar nada más. 560M, 1024 dimensiones, MIT.
- `BAAI/bge-m3`: GRANDE 2. Tamaño parecido al anterior pero otra arquitectura y otro entrenamiento, y sin prefijos: es el contraste de FAMILIA. Ventana de 8192 tokens, así que no puede truncar. 568M, 1024 dimensiones, MIT.
- `hiiamsid/sentence_similarity_spanish_es`: ESPAÑOL. El mejor específico de español disponible: comprobado el 04/08/2026, es el único con uso real (22.500 descargas/mes) frente a derivados con decenas. Entrenado para similitud semántica y no para recuperación, que es la hipótesis que pone a prueba. 110M, Apache 2.0.

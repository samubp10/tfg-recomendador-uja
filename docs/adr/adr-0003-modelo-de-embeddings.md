# ADR-0003: Modelo de incrustaciones (embeddings)

_Basado en https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions_

- **Estado:** Aceptada
- **Decisores:** Samuel Blanco Palmero
- **Contexto técnico:** Fase 1 (indexación y recuperación) del Recomendador UJA

## Contexto

El sistema convierte cada fragmento del corpus y cada pregunta del usuario en un
vector, y recupera comparando esos vectores. El modelo que hace esa conversión
**fija el techo de todo lo que viene después**: ningún _prompt_ puede usar un
fragmento que la recuperación no ha traído. Si el modelo no distingue
«Aprendizaje automático» de «Aprendizaje profundo», el generador responderá con
seguridad sobre la asignatura equivocada y sin ninguna señal de que algo va mal.

Restricciones que condicionan la elección:

- **Idioma.** El corpus y las preguntas están en español, así que un modelo
  monolingüe inglés queda descartado sin necesidad de medirlo.
- **Memoria principal.** La máquina tiene 16 GB y PyTorch compilado **solo para
  CPU**: la GPU no es utilizable. El modelo de incrustaciones tendrá que
  convivir en esa memoria con el modelo generativo de la Fase 2, que es el
  componente grande. Es la restricción que más aprieta.
- **Reproducibilidad.** Los pesos se descargan una vez y quedan en caché; a
  partir de ahí el sistema funciona sin red. Depender de un servicio de
  incrustaciones por API habría atado la reproducibilidad a un tercero y a una
  clave de pago.
- **Coste de indexación.** El índice se reconstruye entero, pero solo cuando
  cambia la colección. No es un criterio de peso.

**Criterio de admisión: ventana de al menos 512 _tokens_.** No es un detalle de
configuración. `sentence-transformers` sirve algunos modelos con
`max_seq_length = 128` aunque el transformador que llevan dentro admita 512, y
`encode` recorta lo que sobra **en silencio**: no avisa, no falla y devuelve un
vector de aspecto normal. Un modelo que no lee el fragmento entero no sirve
aquí, y su diferencia de rendimiento frente a otro que sí lo lee no se podría
atribuir a la calidad de las representaciones. Por eso la ventana se comprueba
en cada ejecución y se informa junto a las métricas.

La comparación se hace sobre la colección completa (**1.334 fragmentos**, curso
2026-27) y las **50 preguntas** etiquetadas de `eval/preguntas_evaluacion.json`,
mediante `scripts/experimento_embeddings.py`. Los cuatro candidatos reciben el
mismo corpus y las mismas preguntas.

## Alternativas consideradas

### Opción A — intfloat/multilingual-e5-small (elegida)

Modelo multilingüe entrenado específicamente para **recuperación**, con un
esquema contrastivo débilmente supervisado. Su ficha exige prefijar los textos:
`"query: "` para las preguntas y `"passage: "` para los documentos, porque el
modelo aprendió a tratar los dos papeles de forma distinta.

- **URL:** [https://huggingface.co/intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small)
- 384 dimensiones · ventana de 512 _tokens_ · **~0,5 GB** de memoria residente
- **Pros:** el de menor huella de los cuatro, con diferencia. Vectores pequeños,
  así que el índice es ligero. Alcanza `RU@10 = 1,000`: la unidad correcta
  siempre está entre los diez primeros resultados.
- **Contras:** no es el mejor en las métricas —lo es la opción B—. Los prefijos
  son obligatorios y asimétricos, de modo que constituyen un invariante frágil.

### Opción B — intfloat/multilingual-e5-large

El mismo entrenamiento y la misma convención de llamada que la opción A, con una
arquitectura mayor. Responde a la pregunta de si compensa pagar por el modelo
grande de la misma familia.

- **URL:** [https://huggingface.co/intfloat/multilingual-e5-large](https://huggingface.co/intfloat/multilingual-e5-large)
- Ventana de 512 _tokens_ · **~2,2 GB** de memoria residente
- **Pros:** el mejor de los cuatro en todas las métricas de recuperación.
- **Contras:** más de cuatro veces la memoria de la opción A, en una máquina
  donde tendrá que convivir con un modelo generativo. Vectores de mayor
  dimensión, así que el índice crece. Y su ventaja sobre la opción A es de
  **media pregunta de cincuenta**.
- **Descartada:** por memoria, no por calidad. Ver la decisión.

### Opción C — BAAI/bge-m3

Modelo multilingüe de recuperación de otra familia. Está para comprobar que la
elección no depende de quedarse dentro de una sola familia de modelos.

- **URL:** [https://huggingface.co/BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3)
- 1.024 dimensiones · ventana de 8.192 _tokens_
- **Pros:** exhaustividad por fragmento por encima de la opción A.
- **Contras:** queda por detrás de las dos opciones E5 en exhaustividad por
  unidad y en MRR, con vectores casi tres veces más grandes que los de la opción
  A. Su ventana de 8.192 _tokens_ no aporta nada aquí: el fragmento más largo del
  corpus ocupa 335.
- **Descartada:** paga índice y memoria por una capacidad que este corpus no usa.

### Opción D — hiiamsid/sentence_similarity_spanish_es

Modelo **específico de español**, no multilingüe. Está en la comparación como
contraste deliberado: la hipótesis razonable era que un modelo dedicado al idioma
del corpus batiese a los multilingües.

- **URL:** [https://huggingface.co/hiiamsid/sentence_similarity_spanish_es](https://huggingface.co/hiiamsid/sentence_similarity_spanish_es)
- Ventana de 512 _tokens_
- **Contras:** el peor de los cuatro por un margen enorme, y **0,000 en las
  preguntas de listado**, que no acierta ninguna.
- **Descartada:** la hipótesis del modelo específico de idioma **no se sostiene**.
  Está entrenado para _similitud semántica entre frases_, una tarea simétrica;
  aquí se le pide recuperación asimétrica pregunta→documento. Es la evidencia más
  limpia de que **la tarea de entrenamiento pesa más que el idioma**, y conviene
  conservar el resultado negativo en vez de omitirlo. Lo que no demuestra es que
  no pueda existir un modelo español bueno para recuperación, sino que el único
  con uso real hoy no lo es.

### Excluidos por el criterio de admisión

Los dos modelos de la familia _paraphrase_ de `sentence-transformers`
—`paraphrase-multilingual-MiniLM-L12-v2` y
`paraphrase-multilingual-mpnet-base-v2`— quedan fuera porque la biblioteca los
sirve con ventana de 128 _tokens_. **No es una decisión de conveniencia:** con
esa ventana `encode` recorta en silencio, y medido sobre el corpus de entonces
solo llegaban a leer la mitad del texto:

| Modelo (ventana 126 _tokens_ útiles) |  R@3 |  R@5 |  MRR | Frag. truncados | Corpus leído |
| ------------------------------------ | ---: | ---: | ---: | --------------: | -----------: |
| paraphrase-multilingual-MiniLM-L12-v2 | 0,420 | 0,570 | 0,619 | 685 | 50 % |
| paraphrase-multilingual-mpnet-base-v2 | 0,584 | 0,668 | 0,730 | 685 | 50 % |

Compararlos con los demás sería atribuir a la calidad de sus representaciones
una diferencia que viene de haber leído la mitad del corpus. De ahí sale el
criterio de admisión: **ventana ≥ 512 _tokens_**.

## Decisión

**`intfloat/multilingual-e5-small`, con los prefijos `"query: "` y `"passage: "`**
que exige su ficha.

Resultados sobre la colección completa (los literales, en el anexo):

| Modelo                             |   R@3 |   R@5 |  R@10 |      RU@3 |      RU@5 |     RU@10 |       MRR | Tiempo (s) |
| ---------------------------------- | ----: | ----: | ----: | --------: | --------: | --------: | --------: | ---------: |
| **A — multilingual-e5-small**      | 0,697 | 0,803 | 0,911 |     0,985 |     0,990 | **1,000** | **0,970** |  **108,0** |
| B — multilingual-e5-large          | 0,740 | 0,852 | 0,938 | **0,995** | **1,000** | **1,000** | **0,970** |      604,3 |
| C — BAAI/bge-m3                    | 0,720 | 0,836 | 0,917 |     0,985 |     0,995 |     0,995 |     0,949 |      650,3 |
| D — sentence_similarity_spanish_es | 0,152 | 0,194 | 0,307 |     0,410 |     0,505 |     0,610 |     0,342 |      220,6 |

**El techo de R@K no es 1.** Una unidad repartida en más de K fragmentos no cabe
entera en un top-K: sobre esta colección el máximo alcanzable es **0,789** para
R@3, **0,906** para R@5 y **0,968** para R@10. Lo que falta se mide contra ese
techo, no contra 1.

**Dónde se paga cada coste.** El factor más llamativo de la tabla —que el
grande tarda ocho veces más en incrustar la colección— es justo el que **casi no
se paga**: reindexar es un proceso por lotes que se lanza cuando cambia el
dataset, y que tarde uno u ocho minutos no lo nota nadie. Lo que se paga en cada
consulta es incrustar la pregunta, que son milisegundos en los dos, y **tener el
modelo residente en memoria**.

| Operación | Cada cuánto | e5-small | e5-large |
| --------- | ----------- | -------: | -------: |
| Incrustar la colección | Al regenerar el dataset | 61 s | 486 s |
| Incrustar una consulta | En cada pregunta | ~ms | ~ms |
| Recorrer el índice | En cada pregunta | 1,2 MB | 3,1 MB |
| Tener el modelo cargado | Mientras el servicio viva | ~0,5 GB | ~2,2 GB |

🔴 Por tanto **el argumento no es que el grande sea ocho veces más lento**, que
mide lo que menos importa. Es que en la máquina donde este sistema se ejecuta el
recuperador tiene que convivir con el modelo generativo, y 2,2 GB frente a
0,5 GB sobre 16 GB es la diferencia entre que quepa y que no. **Es un coste de
memoria, no de tiempo.**

**El criterio que decide no es la calidad de la recuperación sino la viabilidad
del sistema completo**, y este ADR tiene que decirlo con esas palabras en lugar
de dar a entender que el modelo elegido gana en las métricas, porque no gana:

1. **La opción B es mejor en todas las métricas de recuperación.** No se elige
   porque **ocupa ~2,2 GB frente a ~0,5 GB**, y en la Fase 2 el recuperador
   tendrá que compartir 16 GB con un modelo generativo. No es un argumento
   teórico: la primera ejecución de esta misma comparativa **murió por falta de
   memoria** cargando la opción B.
2. **La distancia entre las dos es de media pregunta sobre cincuenta**
   (RU@3 de 0,985 frente a 0,995) y el MRR es idéntico. El conjunto de evaluación
   lo ha etiquetado una sola persona, así que una diferencia de esa magnitud cabe
   dentro de lo que movería otra anotación: **no se presenta como una separación
   establecida**.
3. **Lo que la opción A pierde está localizado y es atacable por otra vía.** Su
   desventaja vive en las preguntas de salidas profesionales (0,690 frente a
   0,889) y de temario (0,723 frente a 0,776); en cambio va por delante en las de
   metadatos (0,697 frente a 0,664), y las dos aciertan por igual las de listado.
   Filtrar por metadatos en el índice ataca ese hueco sin cambiar de modelo.

El factor de tiempo —108 s frente a 604 s al indexar— es lo que más llama la
atención y lo que **menos** pesa, porque solo se paga al reconstruir el índice.

### En qué condiciones se revisaría

Lo que hace esta decisión revisable y no arbitraria es que su premisa es
identificable: **si desapareciera la restricción de memoria, la elección sería la
opción B.** En concreto, si hubiera una GPU utilizable o si el sistema se
desplegara en un servidor en lugar de en un equipo personal.

También habría que reabrirla si el máximo de fragmento del ADR-0001 subiera lo
suficiente como para agotar la ventana de 512 _tokens_.

## Consecuencias

### Positivas

- **El corpus se indexa entero.** Ningún fragmento se trunca: el más largo ocupa
  **335 de los 510 _tokens_ útiles**, con 175 de margen.
- **El índice es el más ligero de los cuatro candidatos:** 384 dimensiones frente
  a las 1.024 de las opciones B y C.
- **La unidad correcta siempre entra en el top-10** (`RU@10 = 1,000`), de modo
  que el recuperador de la Fase 2 no necesita más de diez resultados para tener
  delante la asignatura por la que se pregunta.
- El resultado negativo de la opción D es aprovechable en la memoria: aporta
  evidencia de que la tarea de entrenamiento pesa más que el idioma, que es una
  conclusión más interesante que «gana el mejor».

### Negativas

- **Los prefijos son un invariante frágil.** `"query: "` y `"passage: "` no son
  decorativos: el modelo trata los dos papeles de forma distinta, y olvidar el
  prefijo en la consulta degrada la recuperación **sin ningún error visible**. Se
  protege con una prueba, y el modelo vive en un único módulo
  (`incrustaciones.py`) del que tiran tanto el indexador como el recuperador,
  para que no puedan discrepar entre sí.
- **Se renuncia a la mejor recuperación disponible** para caber en la máquina. Es
  un compromiso consciente, no un empate.
- Ata el código a una familia de modelos con una convención de llamada poco
  obvia, que cualquiera que retome el proyecto puede romper sin darse cuenta.
- La reproducibilidad depende de que Hugging Face siga sirviendo esos pesos.
  Mitigación: quedan en caché local tras la primera descarga.
- **El coste por consulta no está medido.** Lo que se cronometra es incrustar la
  colección entera; la latencia de una consulta suelta, con uno u otro modelo, no
  se ha tomado. El razonamiento sobre el tamaño de la operación es plausible,
  pero es razonamiento y no medición, y es lo primero que habría que medir si
  esta decisión se pone en duda.
- **Tampoco está medido el consumo de memoria del sistema completo**
  ---recuperador más modelo generativo---, porque el generativo no se elige aquí.
  El argumento se apoya en que 2,2 GB frente a 0,5 GB es una diferencia grande
  sobre 16 GB, no en una medición del conjunto.
- **Las 50 preguntas son un conjunto pequeño y anotado por una sola persona.** La
  diferencia entre el modelo elegido y el grande cabe dentro de lo que podría
  mover una anotación distinta, así que no se presenta como una separación
  establecida.

## Referencias

- Fichas de los cuatro modelos evaluados, enlazadas en cada alternativa.
- Documentación de `sentence-transformers`, sobre `max_seq_length` y el recorte
  automático: [https://www.sbert.net/](https://www.sbert.net/)
- L. Wang, N. Yang, X. Huang, L. Yang, R. Majumder, F. Wei, "Multilingual E5 Text
  Embeddings: A Technical Report", 2024. arXiv:2402.05672
  ([https://arxiv.org/abs/2402.05672](https://arxiv.org/abs/2402.05672)) —
  familia E5 multilingüe y el uso de los prefijos de papel.
- L. Wang, N. Yang, X. Huang, B. Jiao, L. Yang, D. Jiang, R. Majumder, F. Wei,
  "Text Embeddings by Weakly-Supervised Contrastive Pre-training", 2022.
  arXiv:2212.03533
  ([https://arxiv.org/abs/2212.03533](https://arxiv.org/abs/2212.03533)) — el
  entrenamiento contrastivo del que sale la familia E5.
- J. Chen, S. Xiao, P. Zhang, K. Luo, D. Lian, Z. Liu, "M3-Embedding:
  Multi-Linguality, Multi-Functionality, Multi-Granularity Text Embeddings
  Through Self-Knowledge Distillation", 2024. arXiv:2402.03216
  ([https://arxiv.org/abs/2402.03216](https://arxiv.org/abs/2402.03216)) — el
  modelo distribuido como `BAAI/bge-m3`.
- N. Muennighoff, N. Tazi, L. Magne, N. Reimers, "MTEB: Massive Text Embedding
  Benchmark", 2022. arXiv:2210.07316
  ([https://arxiv.org/abs/2210.07316](https://arxiv.org/abs/2210.07316)) —
  contexto sobre por qué un modelo entrenado para recuperación rinde distinto que
  uno entrenado para similitud.
- M. Nygard, "Documenting Architecture Decisions", cognitect.com
  ([2011-11-15](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)).

## Anexo — resultados del experimento

<!-- INICIO RESULTADOS AUTOMÁTICOS (scripts/experimento_embeddings.py) -->
Generado el 06/08/2026 ejecutando `py scripts/experimento_embeddings.py` contra `data/chunks.json` (1334 fragmentos, 50 preguntas de `eval/preguntas_evaluacion.json`), en **CPU**.

| Modelo | R@3 | R@5 | R@10 | RU@3 | RU@5 | RU@10 | MRR | Tiempo (s) | Ventana | Truncados | Corpus leído |
|---|---|---|---|---|---|---|---|---|---|---|---|
| intfloat/multilingual-e5-small | 0.697 | 0.803 | 0.911 | 0.985 | 0.990 | 1.000 | 0.970 | 108.0 | 510 | 0 | 100% |
| intfloat/multilingual-e5-large | 0.740 | 0.852 | 0.938 | 0.995 | 1.000 | 1.000 | 0.970 | 604.3 | 510 | 0 | 100% |
| BAAI/bge-m3 | 0.720 | 0.836 | 0.917 | 0.985 | 0.995 | 0.995 | 0.949 | 650.3 | 8190 | 0 | 100% |
| hiiamsid/sentence_similarity_spanish_es | 0.152 | 0.194 | 0.307 | 0.410 | 0.505 | 0.610 | 0.342 | 220.6 | 510 | 0 | 100% |

### Recall@5 por tipo de pregunta

| Modelo | listado (n=14) | metadatos (n=6) | salidas (n=8) | sin_guia (n=2) | temario (n=20) |
|---|---|---|---|---|---|
| intfloat/multilingual-e5-small | 1.000 | 0.697 | 0.690 | 1.000 | 0.723 |
| intfloat/multilingual-e5-large | 1.000 | 0.664 | 0.889 | 1.000 | 0.776 |
| BAAI/bge-m3 | 1.000 | 0.631 | 0.917 | 1.000 | 0.733 |
| hiiamsid/sentence_similarity_spanish_es | 0.000 | 0.096 | 0.350 | 0.500 | 0.266 |

La media general no se puede leer sin este desglose. Las preguntas de tipo `listado` piden **todas** las asignaturas de un grupo, así que su techo depende de cuántas unidades relevantes tengan y no de lo bien que recupere el modelo.

### Cómo leer las columnas

- **R@K** es Recall@K por **fragmento**: cuántos de los trozos de la unidad correcta se han recuperado. Mide cobertura. **Su techo no es 1**, porque una unidad repartida en más de K fragmentos no cabe entera en el top-K: sobre este corpus el máximo posible es **0.789** para R@3, **0.906** para R@5, **0.968** para R@10. Hay que restar del techo, no de 1, para saber lo que falta de verdad.
- **RU@K** es Recall@K por **unidad**: si se ha encontrado la asignatura correcta, sin castigar que falte alguno de sus trozos. Mide acierto, y su techo sí es 1.
- Las dos van juntas a propósito. La primera describe el sistema tal como está hoy; la segunda, el sistema con expansión por unidad, que todavía no existe. **La brecha entre ambas es el dato**: dice si lo que falla es encontrar la asignatura o completarla.
- **Ventana** es el `max_seq_length` con el que sentence-transformers sirve el modelo, descontados los dos tokens especiales. Todo lo que pase de ahí, `encode` lo recorta **en silencio**: no avisa, no falla y devuelve un vector de aspecto normal. Por eso una diferencia de Recall entre modelos de ventana distinta no se puede atribuir solo a la calidad de sus representaciones.
- **Tiempo** es reloj de pared de un portátil que está haciendo otras cosas, así que solo separa órdenes de magnitud. Medido: entre dos ejecuciones seguidas del 04/08/2026 **todas las métricas salieron idénticas a tres decimales**, pero los tiempos variaron hasta un 25 % y los dos modelos grandes llegaron a intercambiarse el orden. Sirve para decir «este tarda cinco veces más que aquel», no para ordenar dos modelos que quedan cerca.

⚠️ Recall@K es **monótono creciente en K**: mirar más resultados no puede reducir los aciertos. Que K=10 gane a K=5 es una propiedad de la métrica, no un hallazgo. Lo que decide K es el coste de contexto y la distracción del generador, y eso se mide en la Fase 2.

### Modelos evaluados

- `intfloat/multilingual-e5-small`: PEQUEÑO / titular. El elegido en el ADR-0003 y ganador de IT-28. Orientado a recuperación; exige prefijos 'query:'/'passage:' según su ficha, aplicados aquí. 118M parámetros, 384 dimensiones, MIT.
- `intfloat/multilingual-e5-large`: GRANDE 1. Misma familia, mismo entrenamiento y mismos prefijos que el titular, con 5x su tamaño: es el único par que aísla el efecto del TAMAÑO sin cambiar nada más. 560M, 1024 dimensiones, MIT.
- `BAAI/bge-m3`: GRANDE 2. Tamaño parecido al anterior pero otra arquitectura y otro entrenamiento, y sin prefijos: es el contraste de FAMILIA. Ventana de 8192 tokens, así que no puede truncar. 568M, 1024 dimensiones, MIT.
- `hiiamsid/sentence_similarity_spanish_es`: ESPAÑOL. El mejor específico de español disponible: comprobado el 04/08/2026, es el único con uso real (22.500 descargas/mes) frente a derivados con decenas. Entrenado para similitud semántica y no para recuperación, que es la hipótesis que pone a prueba. 110M, Apache 2.0.

<!-- FIN RESULTADOS AUTOMÁTICOS -->

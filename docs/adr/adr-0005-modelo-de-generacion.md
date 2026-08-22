# ADR-0005: Modelo de generación

_Basado en https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions_

- **Estado:** Propuesta
- **Decisores:** Samuel Blanco Palmero
- **Contexto técnico:** Fase 2 (pipeline RAG) del Recomendador UJA

## Contexto

Con el modelo de incrustaciones fijado (ADR-0003), la estrategia de fragmentación
(ADR-0001) y la base de datos vectorial (ADR-0004), el sistema ya recupera los
fragmentos pertinentes a una pregunta. Falta decidir **qué modelo redacta la
respuesta** con ellos.

La decisión no se parece a las tres anteriores. Aquellas comparaban candidatos
sobre una tarea de respuesta conocida, y el ganador salía de un número. La
generación de texto libre no ofrece eso, y las dos salidas fáciles no se
sostienen ante un tribunal:

- **Una nota de calidad puesta por el autor** no es reproducible ni
  independiente de quien la pone.
- **Un modelo que ejerza de juez** traslada el problema en vez de resolverlo:
  habría que validar al juez, y esa validación es otro experimento con la misma
  dificultad.

Lo que sí se puede medir contra el corpus, sin modelo adicional y sin criterio
del autor, es **si lo que la respuesta nombra existe** y **si nombra lo que
debía**. El corpus contiene todos los nombres de titulación, mención y
asignatura de la EPSJ, así que comprobar una respuesta contra él son
comparaciones de cadena: deterministas, reproducibles y del todo independientes
del modelo evaluado.

### Restricciones que condicionan la decisión

- **El modelo se ejecuta en local.** No se contempla un servicio de pago: el
  sistema debe poder ejecutarlo quien lea esta memoria, y los datos de la
  consulta no salen del equipo.
- **Tiene que convivir con el modelo de incrustaciones** en 16 GB de memoria
  principal, la misma restricción de viabilidad que decidió el ADR-0003.
- **La tarjeta gráfica del equipo tiene 6 GB de memoria dedicada** y los
  candidatos ocupan entre 5,3 y 8,9 GB ya cuantizados a 4 bits. El servidor de
  inferencia carga en la tarjeta las capas que caben y ejecuta el resto en el
  procesador, así que **ningún candidato de este tamaño se ejecuta entero en
  GPU**.
- **El destinatario es un estudiante de bachillerato.** Una respuesta correcta
  pero ilegible no sirve, y eso no lo mide ninguna de las métricas de abajo.

## Instrumento de medida

El banco de preguntas lo genera `scripts/generar_banco_generacion.py` a partir de
`data/grados.json`: **ni las preguntas ni las respuestas correctas se escriben a
mano**. Son 1.023 preguntas de seis familias, y de ellas se sortea con semilla
fija una muestra de decisión de 80 con todas las familias representadas. Las dos
están versionadas en `eval/`.

Sobre cada respuesta se calculan cuatro medidas:

| Medida | Qué cuenta |
| --- | --- |
| **Titulaciones inventadas** | Nombres con forma de titulación que no están en el catálogo del corpus |
| **Precisión** | De lo que la respuesta enumera, qué proporción existe en el corpus |
| **Cobertura** | De lo que debía nombrar, qué proporción aparece |
| **Acierto escalar** | Para las preguntas de valor único: créditos, número de asignaturas, cursos |

**Lo que este instrumento no mide**, y hay que tenerlo delante al leer cualquier
cifra: si la respuesta está bien escrita, si la recomendación es acertada, o si
el temario que resume es fiel al original. Una respuesta correcta y sosa puntúa
igual que una correcta y bien redactada. Las familias sin respuesta computable
—temario, salidas— **no entran en la decisión**: se observan en sesiones a mano
y se reportan como modos de fallo.

## Umbrales, fijados antes de medir

Se escriben aquí antes de la primera medición, por el mismo motivo que en el
ADR-0004: un umbral que se fija después es un umbral que se acomoda al candidato
que convenga.

- **U1 — Cero titulaciones inventadas. Eliminatorio.** Un sistema cuyo cometido
  es recomendar carreras no puede nombrar una que no existe: el estudiante al
  que va dirigido no tiene forma de detectarlo. Si ningún candidato lo cumple,
  se declara y se decide entre los que menos incurran, dejándolo escrito como
  limitación.
- **U2 — Ninguna pregunta sin contexto recuperado.** Un candidato que dependa de
  que el recuperador le traiga más fragmentos que a los demás no se estaría
  comparando en igualdad.

### Lo que explícitamente NO decide

- **El tiempo de respuesta.** Se mide y se informa, pero no elimina. Descartar
  por tiempo exige una máquina en condiciones controladas y esta no lo está: el
  mismo candidato, sobre la misma muestra, ha dado medianas de 15,9 y de 31,9
  segundos según la carga del equipo, y una respuesta de 581 caracteres llegó a
  marcar 16.677 segundos por paginación a disco. Con esa varianza el tiempo
  describe la máquina, no al candidato.
- **El reparto entre procesador y tarjeta gráfica.** Por la restricción de 6 GB,
  el tiempo de cada candidato mide sobre todo **cuánto de él cupo en la
  tarjeta**, no lo rápido que es. Justificar la elección con eso sería
  justificarla con el portátil de desarrollo. Se registra para el anexo de
  instalación.

## Alternativas consideradas

Las tres se ejecutan con el mismo servidor de inferencia local, cuantizadas a
**Q4_K_M**, con la misma ventana de contexto y el mismo mensaje de sistema. Lo
único que cambia entre ellas es el modelo.

### Opción A — qwen3.5:9b

Modelo de Alibaba, el intermedio de los tres en tamaño.
- **URL:** [https://ollama.com/library/qwen3.5](https://ollama.com/library/qwen3.5)
- **Tamaño:** 9,7 B de parámetros · 6,6 GB en disco · licencia Apache 2.0.

- **Pros:** licencia permisiva sin condiciones de uso añadidas, y la talla
  intermedia entre los otros dos, de modo que ninguna diferencia entre
  candidatos se pueda confundir con el tamaño.
- **Contras:** su ventana declarada es de 262.144 fichas y la del sistema se
  fija en 8.192, así que la comparación no lo ejercita en aquello para lo que
  se anuncia.

### Opción B — gemma3:12b

Modelo de Google, el mayor de los tres.
- **URL:** [https://ollama.com/library/gemma3](https://ollama.com/library/gemma3)
- **Tamaño:** 12,2 B de parámetros · 8,1 GB en disco · licencia *Gemma Terms of
  Use*, no una licencia libre estándar.

- **Pros:** el más consistente del cribado a mano: no rellenó el dato ausente y
  no infirió salidas que no estaban.
- **Contras:** de sus 8,92 GB en memoria solo **3,28 GB caben en la tarjeta
  gráfica**, un 37 %, así que el resto se ejecuta en el procesador. Y redacta
  para un lector que no es el suyo: llegó a repetir el mismo inciso veinte veces
  en una respuesta dirigida a alguien de 17 años.

### Opción C — ministral-8b

Modelo de Mistral AI.
- **URL:** [https://ollama.com/library/ministral](https://ollama.com/library/ministral)
- **Tamaño:** 8,5 B de parámetros · 6,1 GB en disco.

- **Pros:** el más rápido de los tres por un margen amplio, y tampoco rellenó el
  dato ausente.
- **Contras:** se va del dominio con facilidad; en una sesión a mano terminó
  recomendando cursos de una plataforma comercial que no aparece en ninguna
  parte del corpus.

### Descartados en la criba previa

La criba amplia pasó por ocho candidatos y de ella salieron estos descartes, que
no llegan a la comparación final. Se cuentan con su motivo y no con su cifra:
sus respuestas se midieron repartidas entre dos versiones del servidor de
inferencia, y una tabla que mezcla dos versiones compara además los servidores.

- **granite4.1:8b** (8,8 B, 5,3 GB, Apache 2.0) era el único que cabía casi
  entero en los 6 GB de la tarjeta gráfica. Declaró que el contexto no contenía
  las salidas profesionales de una titulación y a continuación redactó siete,
  inventadas. Declarar la carencia y responder igual es peor que fallar, porque
  la respuesta suena informada.
- **mistral-7b** se inventó tres titulaciones enteras, que es el umbral
  eliminatorio U1.

### Sobre el modelo entrenado en español

**salamandra-7b** (7,8 B, 4,9 GB) es el modelo del Barcelona Supercomputing
Center entrenado con corpus en español y en las lenguas cooficiales, y era el
candidato con el argumento más natural para este trabajo: el sistema responde en
español a estudiantes españoles sobre una universidad española.

**Se descarta, y no por sus métricas sino por el umbral eliminatorio.**
Preguntado por los créditos de la única asignatura del corpus cuya ficha no los
publica, respondió «9 créditos» y añadió que era obligatoria: se inventó el dato
**y** el tipo. En la misma sesión enumeró cuatro asignaturas de un curso después
de afirmar que eran diez.

Merece decirse con precisión, porque la conclusión fácil sería equivocada: **el
descarte no dice que un modelo entrenado en español rinda peor en español**.
Dice que este modelo, a este tamaño y con esta cuantización, no respeta el
contexto recuperado, que es el requisito del que depende todo lo demás en un
sistema RAG. Un modelo que redacta bien y se inventa los datos es exactamente el
fallo que este trabajo intenta evitar.

Aun así **se mide junto a los tres finalistas**, y por eso aparece en la tabla
de resultados: un descarte apoyado solo en una sesión a mano es más débil que
uno que además se contrasta sobre la muestra entera. Lo que la medición añade
hay que leerlo con cuidado, porque no confirma sin más aquella sesión. Sobre las
80 preguntas **no nombró ninguna titulación inexistente**, de modo que el umbral
U1, que habla de titulaciones, lo cumple; el dato que se inventó en la sesión a
mano eran unos créditos, que es otro fallo y no el que U1 mide. Donde sí se
separa del resto es en la cobertura: **0,908 frente a 0,996 o más** de los
otros tres, porque a tres preguntas de optativas respondió con el recuento
—«ofrece un total de 16 asignaturas optativas»— en lugar de la lista.

## Resultados del experimento

<!-- INICIO RESULTADOS AUTOMÁTICOS (scripts/experimento_generacion.py) -->

> Lo escribe `scripts/experimento_generacion.py --adr`. **No editar a mano.**

- Preguntas del banco: **80** · respuestas medidas: **320**
- Corpus extraído el 2026-08-16 de https://eps.ujaen.es/grados
- Servidor de inferencia: 0.32.14

### Comparativa de los candidatos

| Modelo | Titul. inventadas | Precisión | Sin medir | Cobertura | Acierto escalar | Mediana (s) | p90 (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ministral-8b:latest` | 0 | 1.000 | 0/34 | 0.996 | 0.957 | 12.1 | 42.1 |
| `qwen3.5:9b` | 0 | 0.996 | 0/34 | 0.997 | 0.957 | 18.2 | 67.2 |
| `gemma3:12b` | 0 | 1.000 | 2/34 | 1.000 | 0.978 | 21.6 | 74.4 |
| `salamandra-7b` | 0 | 0.992 | 15/34 | 0.908 | 0.935 | 3.8 | 11.1 |

**Titulaciones inventadas** es el criterio eliminatorio: un nombre con forma de titulación que no está en el catálogo del índice. **Sin medir** son las respuestas de listado redactadas en prosa, que no enumeran nada: su precisión no existe y queda fuera de la media (IT-110). Que no se pueda medir no las exime, porque la cobertura se mide sobre el texto entero y sí las recoge.

### Desglose por familia de pregunta

#### `ministral-8b:latest`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 35.2 |
| creditos | 23 | — | — | 1.000 | 8.4 |
| curso_de_asignatura | 23 | — | — | 0.913 | 7.1 |
| menciones | 13 | 1.000 | 1.000 | — | 18.4 |
| optativas | 7 | 1.000 | 1.000 | — | 43.2 |
| plan_por_curso | 13 | 1.000 | 0.989 | — | 27.5 |

#### `qwen3.5:9b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 42.9 |
| creditos | 23 | — | — | 1.000 | 13.1 |
| curso_de_asignatura | 23 | — | — | 0.913 | 14.5 |
| menciones | 13 | 0.989 | 1.000 | — | 20.2 |
| optativas | 7 | 1.000 | 1.000 | — | 45.2 |
| plan_por_curso | 13 | 1.000 | 0.992 | — | 34.7 |

#### `gemma3:12b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 67.1 |
| creditos | 23 | — | — | 1.000 | 15.2 |
| curso_de_asignatura | 23 | — | — | 0.957 | 16.0 |
| menciones | 13 | 1.000 | 1.000 | — | 25.4 |
| optativas | 7 | 1.000 | 1.000 | — | 78.3 |
| plan_por_curso | 13 | 1.000 | 1.000 | — | 53.7 |

#### `salamandra-7b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 19.8 |
| creditos | 23 | — | — | 1.000 | 3.7 |
| curso_de_asignatura | 23 | — | — | 0.870 | 2.0 |
| menciones | 13 | 0.976 | 1.000 | — | 4.4 |
| optativas | 7 | 1.000 | 0.571 | — | 8.3 |
| plan_por_curso | 13 | 1.000 | 0.989 | — | 8.5 |

<!-- FIN RESULTADOS AUTOMÁTICOS -->

## Decisión

**Se adopta `gemma3:12b` como modelo de generación del sistema.**

Los cuatro candidatos cumplen el umbral eliminatorio U1: ninguno nombró una
titulación inexistente en las 320 respuestas. También cumplen U2: ninguna
pregunta se quedó sin contexto recuperado. Los umbrales, por tanto, no separan a
nadie, y la decisión se toma sobre las medidas descriptivas.

Sobre ellas, `gemma3:12b` es **primero o empatado en las tres**: precisión
1,000, cobertura 1,000 y acierto escalar 0,978, el más alto de los cuatro. No
gana por poco en una y pierde en otra: no pierde en ninguna.

Y es el más lento, con 21,6 segundos de mediana frente a los 12,1 de
`ministral-8b`. Esa es la contrapartida que se acepta, y se acepta porque el
orden de prelación del sistema está fijado de antemano: **antes que responder
deprisa, no inventar**. Un asistente que orienta a alguien que va a elegir
carrera no puede permitirse un dato falso para llegar antes, y quien lo consulta
tolera esperar veinte segundos mucho mejor que una recomendación equivocada.

El descarte de los otros tres no necesita el tiempo para sostenerse.
`ministral-8b` y `qwen3.5:9b` quedan por detrás en cobertura y en acierto
escalar, que son las dos medidas que dicen si la respuesta contiene lo que debía
contener. `salamandra-7b` es con diferencia el más rápido —3,8 segundos— y es el
único que cabe entero en la tarjeta gráfica, pero su cobertura es 0,908: a las
preguntas de optativas contesta cuántas hay en lugar de cuáles son, y ese es
justo el tipo de pregunta que un preuniversitario hace.

Conviene decir qué **no** sostiene esta decisión. No la sostiene que
`gemma3:12b` escriba mejor: el instrumento no mide la redacción, y en las
sesiones a mano este mismo modelo llegó a repetir el mismo inciso veinte veces
en una respuesta dirigida a alguien de diecisiete años. Tampoco la sostiene su
tamaño, porque el mayor de los candidatos podría haber quedado último sin que
nada de este experimento lo impidiera.

## Consecuencias

### Positivas

- **El sistema no nombra titulaciones que no existen**, medido sobre 320
  respuestas y no sobre una impresión. Es el requisito del que depende que el
  trabajo tenga sentido.
- **La cobertura y el acierto escalar son los más altos de los cuatro**, así que
  la elección no obliga a compensar en otro sitio lo que se gana en fidelidad.
- **El modelo se ejecuta en local**, sin servicio de pago, y con él la consulta
  de un estudiante no sale del equipo.
- **La comparación es reproducible**: banco generado por código con semilla
  fija, cuatro candidatos en la misma tanda y sobre el mismo servidor de
  inferencia, y las cifras de este apartado las escribe el propio guion.

### Negativas

- **Es el candidato más lento de los cuatro**, con 21,6 segundos de mediana y un
  p90 de 74,4. Es la contrapartida aceptada a propósito, no un efecto imprevisto.
- **De sus 8,92 GB en memoria solo caben 3,28 GB en la tarjeta gráfica**, de
  modo que el resto se ejecuta en el procesador. Las cifras de tiempo describen
  este equipo y **no son extrapolables** a otro.
- **El instrumento no mide la calidad de la redacción**, y el destinatario es un
  lector de diecisiete años. Una respuesta correcta y farragosa puntúa igual que
  una correcta y clara.
- **La decisión se toma sobre 80 preguntas de las 1.023 del banco**, sorteadas
  con semilla fija y con todas las familias representadas, pero 80 al fin y al
  cabo.
- **Las familias sin respuesta computable —temario y salidas— no entran en la
  decisión**, y son precisamente las que más texto libre generan.
- **La licencia de `gemma3` no es una licencia libre estándar** sino los *Gemma
  Terms of Use*, con condiciones de uso añadidas. `qwen3.5:9b` y `granite4.1:8b`
  eran Apache 2.0 y se han quedado fuera.

## Referencias

- ADR-0001: estrategia de fragmentación.
- ADR-0003: modelo de incrustaciones.
- ADR-0004: base de datos vectorial.
- `eval/preguntas_generacion.json` y `eval/preguntas_generacion_muestra.json`.
- `scripts/generar_banco_generacion.py` y `scripts/experimento_generacion.py`.
- `src/tfg_uja/verificacion.py`: las comprobaciones deterministas.

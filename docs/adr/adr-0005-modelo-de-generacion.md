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

### Opción A — granite4.1:8b

Modelo de propósito general de IBM, orientado a tareas empresariales sobre
documentos propios.
- **URL:** [https://ollama.com/library/granite4.1](https://ollama.com/library/granite4.1)
- **Tamaño:** 8,8 B de parámetros · 5,3 GB en disco · licencia Apache 2.0.

- **Pros:** el único de los tres que **cabe casi entero** en los 6 GB de memoria
  de la tarjeta gráfica del equipo. Licencia permisiva sin condiciones de uso
  añadidas.
- **Contras:** en el cribado a mano declaró que el contexto no contenía las
  salidas profesionales de una titulación y a continuación redactó siete,
  inventadas. Declarar la carencia y responder igual es peor que fallar, porque
  la respuesta suena informada.

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

## Resultados del experimento

<!-- Pendiente: el bloque lo escribe scripts/experimento_generacion.py entre
     marcadores automáticos, como en el ADR-0001 y el ADR-0004. No se edita a
     mano. -->

## Decisión

<!-- Pendiente hasta que termine la medición de los tres finalistas. -->

## Consecuencias

### Positivas

<!-- Pendiente. -->

### Negativas

<!-- Pendiente. Al menos estas tres, que ya se saben:
     - El instrumento no mide la calidad de la redacción, y el destinatario es
       un lector de 17 años.
     - La decisión se toma sobre 80 preguntas de las 1.023 del banco.
     - Los candidatos no se ejecutan enteros en GPU, así que las cifras de
       latencia no son extrapolables a otro equipo. -->

## Referencias

- ADR-0001: estrategia de fragmentación.
- ADR-0003: modelo de incrustaciones.
- ADR-0004: base de datos vectorial.
- `eval/preguntas_generacion.json` y `eval/preguntas_generacion_muestra.json`.
- `scripts/generar_banco_generacion.py` y `scripts/experimento_generacion.py`.
- `src/tfg_uja/verificacion.py`: las comprobaciones deterministas.

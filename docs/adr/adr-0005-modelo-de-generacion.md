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

<!-- Pendiente: una entrada por candidato, con tamaño, cuantización, licencia y
     ventana de contexto. Los descartados en el cribado a mano llevan además el
     motivo del descarte con su caso real. -->

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

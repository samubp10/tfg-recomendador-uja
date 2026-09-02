# ADR-0005: Modelo de generación

_Basado en https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions_

- **Estado:** Aceptada
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

- **Una nota de calidad puesta por un humano** no es reproducible ni
  independiente de quien la pone.
- **Un modelo que ejerza de juez** traslada el problema en vez de resolverlo:
  habría que validar al juez, y esa validación es otro experimento con la misma
  dificultad.

Lo que sí se puede medir contra el corpus, sin modelo adicional y sin criterio
humano, es **si lo que la respuesta nombra existe** y **si nombra lo que debía**.
El corpus contiene todos los nombres de titulación, mención y asignatura de la
EPSJ, así que comprobar una respuesta contra él son comparaciones de cadena:
deterministas, reproducibles e independientes del modelo evaluado.

### Restricciones que condicionan la decisión

- **El modelo se ejecuta en local.** No se contempla un servicio de pago: el
  sistema debe poder ejecutarlo quien lea esta memoria, y los datos de la
  consulta no salen del equipo.
- **Tiene que convivir con el modelo de incrustaciones** en 16 GB de memoria
  principal, la misma restricción de viabilidad que decidió el ADR-0003.
- **La tarjeta gráfica del equipo tiene 6 GB de memoria dedicada** y los tres
  finalistas ocupan entre 6,1 y 8,1 GB en disco ya cuantizados a 4 bits, así que
  **ninguno se ejecuta entero en GPU**: el servidor de inferencia carga las capas
  que caben y deja el resto en el procesador. Solo `salamandra-7b` cabe entero,
  con 4,9 GB. De ahí que la comparación de tiempos mida sobre todo cuánto de cada
  modelo cupo en la tarjeta.
- **El destinatario es un estudiante de bachillerato**, y una respuesta correcta
  pero ilegible no le sirve.

## Instrumento de medida

El banco de preguntas lo genera `scripts/bancos/generar_banco_generacion.py` a partir de
`data/grados.json`: **ni las preguntas ni las respuestas correctas se escriben a
mano**. Son 1.023 preguntas de seis familias, y de ellas se sortea con semilla
fija una muestra de decisión de 80 con todas las familias representadas. Las dos
están versionadas en `eval/`.

Sobre cada respuesta se calculan cuatro medidas:

| Medida                      | Qué cuenta                                                                 |
| --------------------------- | -------------------------------------------------------------------------- |
| **Titulaciones inventadas** | Nombres con forma de titulación que no están en el catálogo del corpus     |
| **Precisión**               | De lo que la respuesta enumera, qué proporción existe en el corpus         |
| **Cobertura**               | De lo que debía nombrar, qué proporción aparece                            |
| **Acierto escalar**         | Para las preguntas de valor único: créditos, número de asignaturas, cursos |

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
- **El reparto entre procesador y tarjeta gráfica**, por la razón dicha arriba:
  justificar la elección con él sería justificarla con el portátil de
  desarrollo. Se registra para el anexo de instalación.

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
- **Tamaño:** 12,2 B de parámetros · 8,1 GB en disco · licencia _Gemma Terms of
  Use_, no una licencia libre estándar.

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

**Se descarta.** Preguntado por los créditos de la única asignatura del corpus
cuya ficha no los publica, respondió «9 créditos» y añadió que era obligatoria:
se inventó el dato **y** el tipo. En la misma sesión enumeró cuatro asignaturas
de un curso después de afirmar que eran diez.

Aun así **se mide junto a los tres finalistas**, porque un descarte apoyado solo
en una sesión a mano es más débil que uno contrastado sobre la muestra entera. La
medición **no confirma aquella sesión**: sobre las 80 preguntas no nombró ninguna
titulación inexistente, así que cumple U1, que habla de titulaciones y no de
créditos. Donde sí se separa del resto es en la cobertura, **0,770 frente al
0,971 de los otros tres**, porque a las preguntas de optativas responde con el
recuento —«ofrece un total de 16 asignaturas optativas»— en lugar de la lista:
su cobertura en esa familia es de **0,295**. Y deja **13 de 34** listados sin
computar por redactarlos en prosa, frente a los 3 de `gemma3` y ninguno de los
otros dos. El descarte se sostiene, por tanto, en esa cobertura y en el dato
inventado de la sesión a mano; **no en el umbral eliminatorio, que cumple**.

> 🔧 **ANDAMIAJE — dos cosas que decidir aquí.**
>
> 1. **Este párrafo ya no encaja bajo «Descartados en la criba previa»**, porque
>    salamandra-7b sí entra en la comparación final y se mide en la misma tanda
>    que los otros tres. O se sube a una cuarta opción junto a A, B y C, o el
>    epígrafe pasa a decir otra cosa.
> 2. **Falta declarar una limitación de la medición.** Sus autores desaconsejan
>    servirlo con la cuantización que se usa aquí, así que lo medido acota a
>    _esta forma de ejecutarlo_ y no al modelo. Sin esa frase, la cifra de
>    cobertura se lee como una propiedad de salamandra-7b y no lo es del todo.

## Resultados del experimento

<!-- INICIO RESULTADOS AUTOMÁTICOS (scripts/experimentos/experimento_generacion.py) -->

> Lo escribe `scripts/experimentos/experimento_generacion.py --adr`. **No editar a mano.**

- Preguntas del banco: **80** · respuestas medidas: **320**
- Corpus extraído el 2026-08-16 de https://eps.ujaen.es/grados
- Servidor de inferencia: 0.32.14

### Comparativa de los candidatos

| Modelo | Titul. inventadas | Precisión | Sin medir | Cobertura | Acierto escalar | Mediana (s) | p90 (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ministral-8b:latest` | 0 | 1.000 | 0/34 | 0.971 | 1.000 | 24.4 | 87.2 |
| `qwen3.5:9b` | 0 | 1.000 | 0/34 | 0.971 | 1.000 | 17.4 | 47.7 |
| `gemma3:12b` | 0 | 1.000 | 3/34 | 0.971 | 1.000 | 26.0 | 72.1 |
| `salamandra-7b:latest` | 0 | 0.995 | 13/34 | 0.770 | 0.978 | 7.1 | 21.2 |

**Titulaciones inventadas** es el criterio eliminatorio: un nombre con forma de titulación que no está en el catálogo del índice. **Sin medir** son las respuestas de listado redactadas en prosa, que no enumeran nada: su precisión no existe y queda fuera de la media (IT-110). Que no se pueda medir no las exime, porque la cobertura se mide sobre el texto entero y sí las recoge.

### Desglose por familia de pregunta

#### `ministral-8b:latest`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 32.8 |
| creditos | 23 | — | — | 1.000 | 18.2 |
| curso_de_asignatura | 23 | — | — | 1.000 | 12.3 |
| menciones | 13 | 1.000 | 1.000 | — | 48.3 |
| optativas | 7 | 1.000 | 1.000 | — | 76.3 |
| plan_por_curso | 13 | 1.000 | 0.923 | — | 47.8 |

#### `qwen3.5:9b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 42.5 |
| creditos | 23 | — | — | 1.000 | 15.1 |
| curso_de_asignatura | 23 | — | — | 1.000 | 15.2 |
| menciones | 13 | 1.000 | 1.000 | — | 22.6 |
| optativas | 7 | 1.000 | 1.000 | — | 43.1 |
| plan_por_curso | 13 | 1.000 | 0.923 | — | 32.8 |

#### `gemma3:12b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 70.3 |
| creditos | 23 | — | — | 1.000 | 24.0 |
| curso_de_asignatura | 23 | — | — | 1.000 | 19.1 |
| menciones | 13 | 1.000 | 1.000 | — | 34.3 |
| optativas | 7 | 1.000 | 1.000 | — | 75.5 |
| plan_por_curso | 13 | 1.000 | 0.923 | — | 58.2 |

#### `salamandra-7b:latest`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 21.2 |
| creditos | 23 | — | — | 1.000 | 7.3 |
| curso_de_asignatura | 23 | — | — | 0.957 | 3.5 |
| menciones | 13 | 1.000 | 0.963 | — | 9.7 |
| optativas | 7 | 1.000 | 0.295 | — | 7.0 |
| plan_por_curso | 13 | 0.991 | 0.815 | — | 18.7 |

<!-- FIN RESULTADOS AUTOMÁTICOS -->

## Decisión

> 🔧 **ANDAMIAJE — pendiente de redactar.** Lo que sigue son los datos y el
> esqueleto del argumento, no la redacción definitiva. La versión anterior de
> este apartado sostenía la elección sobre que `gemma3:12b` era «primero o
> empatado en las tres» medidas descriptivas, y sobre el corpus vigente eso ya
> no es cierto. Todo lo de aquí abajo sale del bloque de resultados de más
> arriba y del informe de comparación pareada; nada está redondeado ni
> interpretado.

**Los umbrales no separan a nadie, y ahora las medidas descriptivas tampoco.**

Los cuatro candidatos cumplen U1: ninguno nombró una titulación inexistente en
las 320 respuestas. Los cuatro cumplen U2. Eso no ha cambiado.

Lo que ha cambiado es lo de después. Los tres candidatos grandes empatan en las
tres medidas descriptivas:

| Modelo | Precisión | Cobertura | Acierto escalar |
| --- | ---: | ---: | ---: |
| `ministral-8b:latest` | 1,000 | 0,971 | 1,000 |
| `qwen3.5:9b` | 1,000 | 0,971 | 1,000 |
| `gemma3:12b` | 1,000 | 0,971 | 1,000 |
| `salamandra-7b:latest` | 0,995 | 0,770 | 0,978 |

**Por qué se cerró el hueco.** El acierto escalar era la única medida en la que
`gemma3` destacaba (0,978 frente al 0,957 de los otros dos). Se puntúa por
coincidencia exacta sobre preguntas de créditos y de curso, y una parte de esa
diferencia no medía a los modelos: medía el corpus. Mientras una guía compartida
afirmaba el curso de su primera titulación para todas, los tres fallaban las
mismas preguntas de curso porque recibían el mismo dato equivocado. Corregido el
corpus, los tres las aciertan.

**Una comparación pareada no los separa tampoco.** Sobre 250 preguntas, con cada
tasa acompañada de su intervalo de Wilson y la diferencia contrastada con la
prueba exacta de McNemar sobre los pares discordantes:

| Métrica | n | `qwen3.5:9b` | `gemma3:12b` | Discordantes | p |
| --- | ---: | --- | --- | :---: | ---: |
| Precisión | 67 | 0,985 [0,920–0,997] | 0,985 [0,920–0,997] | 0 / 0 | 1,000 |
| Cobertura | 70 | 0,986 [0,923–0,997] | 0,971 [0,902–0,992] | 1 / 0 | 1,000 |
| Acierto escalar | 180 | 0,989 | **1,000** | 0 / 2 | 0,500 |

La única asimetría de las 250 favorece a `gemma3`: acierta **180 de 180** en las
preguntas de valor único y `qwen3.5` acierta 178. Son dos preguntas y **no se
distinguen del azar**; presentarlo como una victoria sería falso. Y un `p` alto
no demuestra que los modelos sean equivalentes, sino que este banco no los
separa: lo que acota cuánta diferencia podría quedar sin verse es la anchura de
los intervalos, no el valor de `p`.

**Qué queda para decidir, y qué no vale.**

El apartado «Lo que explícitamente NO decide» excluye el tiempo de respuesta, y
esa exclusión se fijó antes de medir. Así que la ventaja de `qwen3.5` en mediana
---17,4 s frente a 26,0 s--- **no puede usarse como criterio de desempate** sin
retirar antes esa exclusión y justificar por qué.

Lo que sí está registrado en este ADR y sí distingue a los candidatos:

1. **La licencia.** `qwen3.5:9b` es Apache 2.0; `gemma3` se distribuye bajo los
   _Gemma Terms of Use_, con condiciones de uso añadidas. Ya figura entre los
   pros de la Opción A y entre las consecuencias negativas de la elección
   actual.
2. **Las respuestas no computables.** `gemma3` redacta en prosa 3 de 34
   listados y `qwen3.5` ninguno. Quedan fuera de la media de precisión, así que
   su 1,000 se calcula sobre menos casos.
3. **El acierto escalar pareado**, 180/180 frente a 178/180, con la salvedad de
   arriba.

**Las tres salidas posibles, para elegir una y argumentarla:**

- **Mantener `gemma3:12b`.** Ante un empate que ninguna medida rompe, no se
  cambia el modelo adoptado; el 180 de 180 apoya la continuidad aunque no la
  demuestre. Hay que decir explícitamente que la elección **ya no se sostiene
  sobre las métricas**, porque no separan.
- **Adoptar `qwen3.5:9b`.** Empata en calidad, no deja ningún listado sin
  computar y su licencia es libre estándar. Exige reconocer que se cambia por un
  criterio ---la licencia--- que no era el que decidía antes, y rehacer con él
  las cifras del sistema.
- **Declarar el empate y elegir con un criterio nuevo, escrito aquí.** El más
  defendible sería la licencia, por ser una propiedad del modelo y no del
  portátil. Obliga a explicar por qué no se contempló como criterio desde el
  principio.

⚠️ Elijas la que elijas, la frase que **no** puede volver a escribirse es que
`gemma3` gane en cobertura o en acierto escalar, ni que `qwen3.5` quede por
detrás en ninguna de las dos.

## Consecuencias

### Positivas

- **El sistema no nombra titulaciones que no existen**, medido sobre 320
  respuestas y no sobre una impresión. Es el requisito del que depende que el
  trabajo tenga sentido.
- 🔧 **ANDAMIAJE.** Aquí decía «la cobertura y el acierto escalar son los más
  altos de los cuatro, así que la elección no obliga a compensar en otro sitio
  lo que se gana en fidelidad». Sobre el corpus vigente los tres candidatos
  grandes empatan en las dos, de modo que esta consecuencia positiva ya no
  distingue a la elección: lo que se puede afirmar es que **no obliga a
  compensar nada**, no que gane. Depende de qué salida se elija en la Decisión.
- **El modelo se ejecuta en local**, sin servicio de pago, y con él la consulta
  de un estudiante no sale del equipo.
- **La comparación es reproducible**: los cuatro candidatos se miden en la misma
  tanda y sobre el mismo servidor, y las cifras de este apartado las escribe el
  propio guion.

### Negativas

- **Es el candidato más lento de los cuatro**, con 26,0 segundos de mediana y un
  p90 de 72,1. Es la contrapartida aceptada a propósito, no un efecto imprevisto.
  Buena parte de esa lentitud es del equipo: de sus 8,92 GB en memoria solo caben
  3,28 GB en la tarjeta gráfica, de modo que las cifras de tiempo describen este
  portátil y **no son extrapolables** a otro.
- **El instrumento no mide la calidad de la redacción**, y el destinatario es un
  lector de diecisiete años. Una respuesta correcta y farragosa puntúa igual que
  una correcta y clara.
- **La decisión se toma sobre 80 preguntas de las 1.023 del banco**, y ochenta
  son ochenta por bien repartidas que estén.
- **Las familias sin respuesta computable —temario y salidas— no entran en la
  decisión**, y son precisamente las que más texto libre generan.
- **La licencia de `gemma3` no es una licencia libre estándar** sino los _Gemma
  Terms of Use_, con condiciones de uso añadidas. `qwen3.5:9b` y `granite4.1:8b`
  eran Apache 2.0 y se han quedado fuera.

## Referencias

- ADR-0001: estrategia de fragmentación.
- ADR-0003: modelo de incrustaciones.
- ADR-0004: base de datos vectorial.
- `eval/preguntas_generacion.json` y `eval/preguntas_generacion_muestra.json`.
- `scripts/bancos/generar_banco_generacion.py` y `scripts/experimentos/experimento_generacion.py`.
- `src/tfg_uja/dialogo/verificacion.py`: las comprobaciones deterministas.

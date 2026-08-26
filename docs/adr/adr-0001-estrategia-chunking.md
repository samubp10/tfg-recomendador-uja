# ADR-0001: Estrategia de fragmentación de la colección

_Basado en https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions_

- **Estado:** Aceptada
- **Decisores:** Samuel Blanco Palmero
- **Contexto técnico:** fragmentación de la colección documental del Recomendador UJA

## Contexto

El sistema recupera fragmentos de la colección para responder a las preguntas del
usuario. Cómo se parta el texto condiciona todo lo que viene después: un fragmento
demasiado grande mezcla asuntos y su vector queda a medio camino de todos ellos;
uno demasiado pequeño pierde el contexto que lo hace comprensible por sí solo.

**El troceado no es opcional.** Medido sobre la colección, el cuerpo de una guía
docente ocupa una mediana de **2.653 caracteres**, con percentil 90 de **6.024** y
un máximo de **24.047**. El **99 %** de las guías no cabe en un fragmento de 900
caracteres y el **83 %** tampoco en uno de 1.500. Indexar cada guía entera obligaría
a que el modelo recortase la mayoría, y lo haría **en silencio**: `encode` no avisa
ni falla cuando el texto excede la ventana.

A esa restricción de tamaño se suma una restricción de diseño que el sistema no
puede violar: **un fragmento nunca puede mezclar contenido de dos asignaturas
distintas**. Un fragmento así, recuperado, atribuiría a una asignatura el temario de
otra, y el modelo generativo no tendría forma de detectarlo.

La decisión se toma sobre el corpus del curso 2026-27 de la EPSJ —528 asignaturas,
288 guías docentes y 8 bloques de salidas profesionales— y se mide con las **50
preguntas** anotadas de `eval/preguntas_evaluacion.json`. Depende del ADR-0003, el
modelo de incrustaciones, porque medir la calidad de un troceado exige vectorizar.

## Alternativas consideradas

### Opción A — Corte por longitud, con o sin solape

Ventanas de tamaño fijo sobre el texto.

- **Pros:** la más simple de implementar, no necesita conocer la estructura del
  documento y no depende del modelo de incrustaciones.
- **Contras:** corta a mitad de frase y, si se aplica sobre la colección entera en
  lugar de dentro de cada unidad, puede juntar dos asignaturas en un mismo fragmento.
  El solape duplica contenido y regala oportunidades de ser recuperado.

### Opción B — Corte estructural por unidad _(elegida)_

La unidad es la asignatura —su guía— o el bloque de salidas de una titulación. Se
parte solo si excede el máximo: primero por párrafos y, si algún trozo sigue siendo
demasiado grande, por frases. Los residuos por debajo del mínimo se fusionan con su
vecino reequilibrando el par. A cada fragmento se le antepone un encabezado
autocontenido con nombre, tipo, ECTS y titulación.

- **Pros:** respeta la restricción de diseño **por construcción**, corta en fronteras
  del propio texto y tampoco depende del modelo de incrustaciones.
- **Contras:** necesita conocer la estructura de la fuente y es más código que la
  opción A.

### Opción C — Corte semántico por incrustaciones

Partir donde cae la similitud entre piezas consecutivas del texto, es decir, donde
el propio modelo detecta un cambio de tema.

- **Pros:** es la alternativa conceptualmente más atractiva y la que más se cita en
  la literatura divulgativa.
- **Contras:** obliga a calcular incrustaciones _antes_ de fragmentar, con lo que el
  fragmentador queda atado al modelo.

### Opción D — Un fragmento por asignatura, sin dividir

Descartada por el contexto: el 99 % de las guías supera el máximo y el sobrante se
truncaría sin aviso. No es una alternativa real, se documenta porque es la primera
que se le ocurre a cualquiera.

### Cómo se comparan las tres primeras: una rejilla de 45 configuraciones

Comparar «la estrategia A contra la estrategia B» no significa nada mientras cada
una lleve sus propios parámetros: se estaría comparando dos cosas a la vez. El
experimento se organiza por eso como una **búsqueda en rejilla**, que prueba
sistemáticamente todas las combinaciones de los parámetros en juego, con
`scripts/experimentos/experimento_fragmentacion.py` sobre `data/grados.json`, las 50 preguntas del
conjunto de evaluación y el modelo del ADR-0003, en CPU.

- **Eje común a las tres:** tamaño máximo de 600, 900, 1.200, 1.500 y 1.800
  caracteres.
- **Estructural:** tamaño objetivo al 60 %, 80 % y 100 % del máximo.
- **Longitud:** solape del 0 %, 10 % y 20 %. El 0 % entra a propósito: un solape
  duplica contenido y hay que poder ver cuánto de la mejora viene de ahí.
- **Semántica:** corte en el percentil 30, 50 y 70 de la distribución real de
  distancias entre piezas consecutivas. Se usa un percentil y no una distancia
  absoluta porque el valor absoluto depende del modelo, mientras que el percentil se
  adapta solo a la distribución que ese modelo produzca; y se recalcula para cada
  tamaño máximo, porque al cambiar el máximo cambian las piezas entre las que se
  mide.

**45 configuraciones, quince por estrategia.** La simetría no es estética: si una
estrategia recibe once intentos y otra uno, quedarse con el mejor resultado de cada
una favorece a la primera aunque no haya ninguna diferencia real, porque el máximo
de once tiradas gana al de una por puro muestreo.

De cada configuración se sustituye **únicamente** la función que decide dónde
colocar los cortes dentro de una unidad, y a continuación se invoca el fragmentador
real del sistema. Todo lo demás —la construcción de las unidades, la deduplicación,
los encabezados, el tratamiento de las titulaciones dobles, los fragmentos de plan
de estudios y la fusión de residuos— es idéntico en las cuarenta y cinco. Sin esa
precaución, cualquier diferencia medida podría venir de otra parte del proceso y
atribuirse por error a la estrategia.

Sobre la colección resultante se calculan las incrustaciones de todos los fragmentos
y de las cincuenta preguntas, y se ordenan **de forma exacta**, recorriéndolos todos.
La base de datos vectorial no interviene: un índice aproximado devuelve un orden que
depende de sus propios parámetros, de modo que cada medida mezclaría la decisión que
aquí se estudia con otra distinta. Lo que se obtiene es el techo de lo que ese
troceado permite recuperar.

El tamaño mínimo se mantiene en 200 caracteres en las cuarenta y cinco y **no queda
validado por este experimento**.

## Decisión

1. **Opción B, corte estructural**, con **tamaño máximo y objetivo de 900
   caracteres** —encabezado incluido— y **mínimo de 200**. El máximo es una
   restricción dura; el mínimo, una preferencia.
2. **La Opción C queda medida y descartada.** No es peor: es que **no es mejor**, y
   cuesta una dependencia que la estructural no tiene. Trocear semánticamente obliga
   a calcular incrustaciones _antes_ de fragmentar, de modo que el fragmentador
   quedaría atado al modelo y cambiar de modelo obligaría a re-trocear el corpus
   entero.
3. **La unión de fragmentos solo ocurre si el resultado cabe dentro del máximo.** Si
   no cabe, el algoritmo conserva el fragmento corto: violar la restricción dura es
   peor que quedarse por debajo de una preferencia.

### El tamaño manda; la estrategia casi no

Ordenadas por acierto por unidad en el primer resultado, las tres estrategias
aparecen mezcladas en la cabeza y en la cola. Lo que ordena la tabla es el **tamaño
máximo**. Con corte por longitud y solape 0 %, cambiando solo el máximo:

| Máximo | Fragmentos |  RU@1 |
| -----: | ---------: | ----: |
|    600 |      2.312 | 0,950 |
|    900 |      1.228 | 0,930 |
|  1.200 |        912 | 0,910 |
|  1.500 |        736 | 0,850 |
|  1.800 |        623 | 0,810 |

Monótono, y el mismo patrón en las otras dos estrategias.

### El factor de confusión que impide quedarse con la primera fila

El orden de RU@1 sigue al número de fragmentos, y eso tiene una explicación que **no
es calidad**: con 2.312 fragmentos cada unidad ocupa unos siete huecos del índice y
con 900 ocupa dos y medio, es decir, siete papeletas frente a dos y media para caer
en el primer puesto. Y hay algo peor: recuperar el primer resultado de 600 caracteres
entrega 600 caracteres de contexto, y el de 1.500 entrega 1.500. **A K fijo no se
está comparando lo mismo.**

⚠️ Esto es una limitación de la propia métrica principal: **RU@K no es del todo
inmune al troceo**, porque una unidad partida en más fragmentos ocupa más huecos del
top-K. Por eso no se elige la fila con mejor número. La comparación que sí aísla el
efecto es a **igualdad de número de fragmentos**:

| Configuración                          | Fragmentos |      RU@1 |       MRR |
| -------------------------------------- | ---------: | --------: | --------: |
| estructural, máx. 900, objetivo 100 %  |      1.334 | **0,930** | **0,970** |
| estructural, máx. 1.200, objetivo 60 % |      1.499 |     0,890 |     0,940 |

Con **165 fragmentos menos**, el máximo de 900 gana en las dos métricas. Ahí el
recuento ya no lo explica.

### A igualdad de tamaño, las tres estrategias son indistinguibles

Las nueve configuraciones que comparten el máximo de 900 caracteres se reparten entre
**0,890 y 0,935** de RU@1: poco más de dos preguntas de cincuenta de recorrido total,
y las cuatro mejores caben en un cuarto de pregunta.

| Estrategia      | Ajuste         | Fragmentos |      RU@1 |      RU@3 |       MRR |
| --------------- | -------------- | ---------: | --------: | --------: | --------: |
| Longitud        | solape 20 %    |      1.445 | **0,935** |     0,965 | **0,974** |
| **Estructural** | objetivo 100 % |      1.334 |     0,930 | **0,985** |     0,970 |
| Longitud        | solape 0 %     |  **1.228** |     0,930 |     0,985 |     0,963 |
| Semántica       | percentil 70   |      1.647 |     0,930 |     0,985 |     0,963 |

Las cincuenta preguntas las ha anotado una sola persona, que es además quien
construyó el sistema, y **una pregunta de cincuenta vale 0,020**. Diferencias de ese
orden **no se distinguen** de lo que movería otra anotación, así que la elección
entre las tres estrategias no puede apoyarse en ellas.

### El truncado, que no depende de ninguna métrica discutible

Contado con el analizador léxico del propio modelo, no estimado:

|          Máximo |                           Fragmentos truncados |
| --------------: | ---------------------------------------------: |
| 600, 900, 1.200 | **0** en las nueve configuraciones de cada uno |
|           1.500 |                                          0 – 4 |
|           1.800 |                                   hasta **31** |

A partir de 1.500 empieza a haber configuraciones en las que el modelo deja de leer
parte del fragmento **sin avisar**: no falla,
no da error, simplemente vectoriza menos texto del que se le entregó. Cualquier
configuración que trunque queda descartada sin necesidad de discutir sus métricas,
porque sobre esos fragmentos el sistema estaría midiendo algo que el modelo nunca
llegó a leer.

### Por qué la estructural y no la de longitud

Este es el punto que hay que dejar atado, porque **la recuperación no lo justifica**.
El troceo por longitud sin solape, con el mismo máximo, produce 1.228 fragmentos
—ciento seis menos— y **empata** en RU@1 y RU@3. Tampoco necesita el modelo de
incrustaciones, así que el argumento que descarta la semántica no lo descarta a él, y
además es más simple de implementar. Si el único criterio fuera el rendimiento
medido, las dos serían igual de defendibles.

Lo que las separa no aparece en ninguna columna de métricas: **dónde cortan**. La
estructural parte por fronteras del propio texto —final de párrafo o de frase—;
la de longitud parte al alcanzar un número de caracteres, con lo que empieza y
termina a mitad de frase y a veces a mitad de palabra. Para recuperar da igual, y la
tabla lo demuestra: el vector de un fragmento cortado a mitad de frase representa su
contenido igual de bien. Pero el fragmento recuperado no se queda en el buscador: se
le entrega al modelo generativo para que redacte con él delante, y ahí una definición
partida por la mitad sí importa.

🔴 **Ese argumento no está medido.** La rejilla mide recuperación, no calidad de la
respuesta generada, que exige las métricas de la Fase 2. La forma honesta de enunciar
la decisión es, por tanto: se elige la estructural por una ventaja que este
experimento no captura, y no porque gane en las métricas, porque no gana.

### Lo que la configuración elegida produce sobre la colección real

La rejilla mide con un guion que sustituye la colocación de los cortes. Un
experimento así puede medir algo que después el sistema no reproduce, así que se
comprueba contra el corpus de producción.

**El corpus resultante tiene 1.334 fragmentos, que es exactamente la cifra que
predijo la rejilla** para «estructural, máximo 900, objetivo 100 %». Que coincida al
fragmento es la comprobación de que el guion no medía una fragmentación distinta de
la real.

| Métrica   | Rejilla (guion) | Producción (`data/chunks.json`) |
| --------- | --------------: | ------------------------------: |
| RU@1      |           0,930 |                       **0,930** |
| RU@3      |           0,985 |                       **0,985** |
| MRR       |           0,970 |                       **0,970** |
| Truncados |               0 |                           **0** |

Coinciden en las cuatro cifras. La sustitución que hacía el guion queda validada y
las 45 filas se pueden leer como lo que el sistema haría.

**Composición del corpus:** 1.193 fragmentos de guía, 86 informativos de asignaturas
sin guía publicada, 33 de plan de estudios y 22 de salidas profesionales, repartidos
en **322 unidades** de las que **78 se comparten** entre titulaciones. Tamaños de
**171 a 900** caracteres, mediana 838 y percentil 90 de 894.

**Seis fragmentos quedan por debajo del mínimo**, entre 171 y 196 caracteres: el
0,45 % del corpus. Son colas irreducibles —unirlas a su vecino habría desbordado el
máximo— y por eso el verificador comprueba el **invariante exacto** (un fragmento
corto solo es admisible si unirlo a su vecino desbordaría el máximo) y no un margen
de tolerancia. Un margen arbitrario es un test que miente.

**El fragmento más largo del corpus ocupa 335 _tokens_ y la mediana 204**, sobre una
ventana de 512. Es decir: la configuración elegida deja la ventana del modelo a dos
tercios de su capacidad y aun así recupera mejor que las que la llenaban. **El
problema nunca fue desaprovechar la ventana**, sino que un fragmento largo mezcla
varios asuntos y su vector queda a medio camino de todos ellos.

La cobertura por fragmento, en cambio, es más baja que con fragmentos grandes (R@3 =
0,697). No es una regresión: al multiplicarse los fragmentos de cada unidad, el
denominador de esa métrica crece y su techo baja. Es justamente por lo que la métrica
comparable entre dos fragmentaciones distintas es la de **unidad** y no la de
fragmento.

### Deduplicación de las guías compartidas

Al medir la colección aparece una redundancia que no viene del sistema sino de la
fuente: muchas asignaturas de primeros cursos —Matemáticas I, Física, Automática
industrial— se imparten en varias titulaciones con la misma guía carácter por
carácter. Esa redundancia sesga la recuperación, porque varias copias idénticas
pueden acaparar los primeros puestos y expulsar resultados distintos.

**Se deduplica dentro del fragmentador.** Las guías se agrupan y cada grupo produce
una sola unidad que arrastra la lista de titulaciones en las que se imparte; de ahí
que los campos `grados` y `codigos` de un fragmento sean listas y no cadenas.
`grados.json` permanece intacto y fiel a la fuente: la deduplicación es una
transformación de representación en el índice, no una pérdida de datos. Su efecto
sobre el corpus es directo: los fragmentos de guía son 1.193 frente a los **3.631**
que habría si cada titulación llevara su propia copia.

#### Qué clave decide que dos guías son la misma

| Clave                   | Grupos compartidos | Copias excedentes | Unidades resultantes |
| ----------------------- | -----------------: | ----------------: | -------------------: |
| Solo el contenido       |                 41 |                81 |                  207 |
| **(nombre, contenido)** |             **39** |            **79** |              **209** |

La diferencia exacta entre las dos claves son **dos parejas** con el mismo contenido
publicado bajo nombres distintos:

1. «Fundamentos de la programación» (Ingeniería Informática) y «Fundamentos de
   programación» (Inteligencia Artificial y Ciberseguridad), con 1.181 caracteres
   idénticos. Es la misma asignatura escrita de dos maneras: **la clave elegida no
   las agrupa, y ahí pierde**.
2. «Seguridad en gestión de la información» (Inteligencia Artificial y
   Ciberseguridad) y «Seguridad en tecnologías de la información» (Ingeniería
   Informática), con 1.228 caracteres idénticos. Son **asignaturas distintas de
   titulaciones distintas** que comparten el texto de la guía: agruparlas atribuiría
   el contenido de una a la otra, y ahí la clave elegida **acierta**.

Se elige `(nombre, contenido)` aceptando ese balance a propósito, porque los dos
errores no cuestan lo mismo: fusionar dos asignaturas distintas corrompe el índice y
puede hacer que el sistema atribuya un temario a quien no le corresponde, mientras
que no fusionar dos copias idénticas solo deja el índice ligeramente más grande.

La comparación se hace además sobre el nombre normalizado —sin distinguir mayúsculas
ni espacios sobrantes—, porque la fuente no es consistente al escribirlos.

### Identidad de la asignatura dentro del fragmentador

Decidir cuándo dos guías son la misma no es lo único que obliga a fijar un criterio
de identidad. El fragmentador necesita además localizar, para cada guía, la
asignatura de la que salen los metadatos del encabezado. Esa búsqueda **no puede
hacerse por el código**: la fuente publica sin código las asignaturas de los planes
de implantación reciente, y todas ellas caerían bajo la misma clave dentro de su
titulación, sobrescribiéndose unas a otras sin que nada avisara. El encabezado
resultante atribuiría el temario a una materia distinta, y lo haría dentro del campo
que se convierte en vector.

**Una asignatura se identifica por el par (titulación, código o nombre)**, y esa
regla vive en una única función para que el rastreador, el fragmentador y el
verificador identifiquen una asignatura de la misma manera.

## Consecuencias

### Positivas

- Ningún fragmento mezcla asignaturas: la restricción se cumple por construcción y no
  por comprobación posterior.
- Ningún fragmento supera la ventana del modelo, contado con su propio analizador
  léxico y no estimado.
- Los fragmentos son autocontenidos: el encabezado permite entenderlos recuperados
  aislados.
- Las asignaturas sin guía publicada quedan representadas con un fragmento
  informativo explícito, no como huecos silenciosos.
- La deduplicación elimina la redundancia del índice y el sesgo que causaba, y la
  consulta filtrada por titulación sigue siendo posible porque `grados` es una lista.
- Re-fragmentar es barato y no exige volver a rastrear la web: por eso el fragmentador
  es un módulo separado del rastreador.

### Negativas

- Dos asignaturas con el mismo contenido y el nombre escrito de forma distinta no se
  deduplican. Es un falso negativo conservador y asumido.
- El corte estructural se sostiene sobre un argumento que este experimento no mide.
  **No se ha medido el efecto de la fragmentación sobre la generación**, que es donde
  actúa de verdad y donde está el único argumento que separa la estrategia elegida de
  la de longitud. Exige métricas de la Fase 2.
- Con el máximo en 900 el mínimo empieza a rozarse: aparecen seis colas irreducibles.
  Con máximos mayores no ocurría, y con 600 el margen entre mínimo y máximo se
  estrecharía todavía más.

## Referencias

- Documentación de LangChain, "Text splitters":
  [https://python.langchain.com/docs/concepts/text_splitters/](https://python.langchain.com/docs/concepts/text_splitters/)
- Pinecone, "Chunking strategies for LLM applications":
  [https://www.pinecone.io/learn/chunking-strategies/](https://www.pinecone.io/learn/chunking-strategies/)
- Documentación de Sentence-Transformers (límite de secuencia de los modelos):
  [https://www.sbert.net/](https://www.sbert.net/)
- M. Nygard, "Documenting Architecture Decisions", cognitect.com
  ([2011-11-15](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)).

## Anexo — las 45 configuraciones

<!-- INICIO RESULTADOS AUTOMÁTICOS (scripts/experimentos/experimento_fragmentacion.py) -->
Generado por `scripts/experimentos/experimento_fragmentacion.py` sobre `data/grados.json`, con las
50 preguntas de `eval/preguntas_evaluacion.json` y el modelo
`intfloat/multilingual-e5-small` (ventana de 512 _tokens_), en CPU. Ordenada por
exhaustividad por unidad en el primer resultado, que es donde las configuraciones se
distinguen: a partir de K=5 se saturan y empatan casi todas.

| Estrategia  | Máx. | Ajuste        | Frag. | Mediana |  RU@1 |  RU@3 |  RU@5 | RU@10 | RU@15 |   R@5 / techo |   MRR | Trunc. |
| ----------- | ---: | ------------- | ----: | ------: | ----: | ----: | ----: | ----: | ----: | ------------: | ----: | -----: |
| fijo        |  600 | solape 0%     |  2312 |     600 | 0.950 | 0.985 | 0.985 | 1.000 | 1.000 | 0.709 / 0.805 | 0.972 |      0 |
| fijo        |  900 | solape 20%    |  1445 |     900 | 0.935 | 0.965 | 0.990 | 1.000 | 1.000 | 0.785 / 0.893 | 0.974 |      0 |
| estructural |  900 | objetivo 100% |  1334 |     838 | 0.930 | 0.985 | 0.990 | 1.000 | 1.000 | 0.803 / 0.906 | 0.970 |      0 |
| estructural |  600 | objetivo 80%  |  3054 |     479 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.656 / 0.745 | 0.965 |      0 |
| semantica   |  600 | percentil 30  |  2931 |     546 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.651 / 0.751 | 0.965 |      0 |
| semantica   |  600 | percentil 50  |  2951 |     544 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.651 / 0.752 | 0.965 |      0 |
| estructural |  600 | objetivo 60%  |  3040 |     525 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.633 / 0.716 | 0.964 |      0 |
| semantica   |  600 | percentil 70  |  2949 |     546 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.645 / 0.748 | 0.964 |      0 |
| semantica   |  900 | percentil 70  |  1647 |     673 | 0.930 | 0.985 | 0.985 | 1.000 | 1.000 | 0.776 / 0.870 | 0.963 |      0 |
| fijo        |  900 | solape 0%     |  1228 |     900 | 0.930 | 0.985 | 0.990 | 1.000 | 1.000 | 0.811 / 0.917 | 0.963 |      0 |
| fijo        |  600 | solape 10%    |  2528 |     600 | 0.930 | 0.985 | 0.990 | 1.000 | 1.000 | 0.689 / 0.788 | 0.962 |      0 |
| fijo        |  600 | solape 20%    |  2801 |     600 | 0.930 | 0.980 | 0.990 | 1.000 | 1.000 | 0.671 / 0.767 | 0.962 |      0 |
| semantica   |  900 | percentil 30  |  1614 |     671 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.762 / 0.856 | 0.961 |      0 |
| estructural |  600 | objetivo 100% |  2695 |     569 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.687 / 0.778 | 0.960 |      0 |
| estructural |  900 | objetivo 60%  |  1949 |     526 | 0.930 | 0.980 | 0.985 | 1.000 | 1.000 | 0.722 / 0.825 | 0.960 |      0 |
| estructural |  900 | objetivo 80%  |  1612 |     691 | 0.930 | 0.985 | 0.985 | 1.000 | 1.000 | 0.784 / 0.874 | 0.960 |      0 |
| fijo        | 1200 | solape 0%     |   912 |    1199 | 0.910 | 0.985 | 0.990 | 0.995 | 0.995 | 0.805 / 0.956 | 0.960 |      0 |
| semantica   |  900 | percentil 50  |  1662 |     653 | 0.910 | 0.980 | 0.985 | 1.000 | 1.000 | 0.768 / 0.864 | 0.951 |      0 |
| semantica   | 1200 | percentil 30  |  1263 |     738 | 0.890 | 0.980 | 0.990 | 1.000 | 1.000 | 0.794 / 0.897 | 0.942 |      0 |
| estructural | 1200 | objetivo 60%  |  1499 |     695 | 0.890 | 0.985 | 0.990 | 1.000 | 1.000 | 0.792 / 0.883 | 0.940 |      0 |
| semantica   | 1200 | percentil 70  |  1311 |     724 | 0.890 | 0.985 | 0.990 | 1.000 | 1.000 | 0.797 / 0.905 | 0.938 |      0 |
| fijo        |  900 | solape 10%    |  1314 |     900 | 0.890 | 0.960 | 0.990 | 1.000 | 1.000 | 0.795 / 0.912 | 0.937 |      0 |
| fijo        | 1200 | solape 20%    |  1044 |    1200 | 0.890 | 0.965 | 0.990 | 0.995 | 0.995 | 0.806 / 0.939 | 0.936 |      0 |
| semantica   | 1200 | percentil 50  |  1324 |     714 | 0.870 | 0.980 | 0.990 | 1.000 | 1.000 | 0.796 / 0.905 | 0.932 |      0 |
| fijo        | 1800 | solape 20%    |   705 |    1799 | 0.870 | 0.960 | 0.970 | 0.995 | 0.995 | 0.868 / 0.985 | 0.929 |     31 |
| estructural | 1500 | objetivo 60%  |  1149 |     864 | 0.850 | 0.985 | 0.990 | 1.000 | 1.000 | 0.839 / 0.930 | 0.927 |      0 |
| fijo        | 1500 | solape 0%     |   736 |    1499 | 0.850 | 0.985 | 0.990 | 0.995 | 0.995 | 0.853 / 0.979 | 0.927 |      3 |
| estructural | 1200 | objetivo 80%  |  1140 |     910 | 0.850 | 0.990 | 0.995 | 1.000 | 1.000 | 0.813 / 0.920 | 0.925 |      0 |
| estructural | 1200 | objetivo 100% |   947 |    1104 | 0.850 | 0.960 | 0.990 | 0.995 | 0.995 | 0.820 / 0.953 | 0.913 |      0 |
| semantica   | 1500 | percentil 30  |  1046 |     837 | 0.850 | 0.965 | 0.990 | 1.000 | 1.000 | 0.811 / 0.929 | 0.913 |      4 |
| fijo        | 1500 | solape 10%    |   777 |    1499 | 0.840 | 0.925 | 0.995 | 1.000 | 1.000 | 0.844 / 0.977 | 0.899 |      3 |
| fijo        | 1500 | solape 20%    |   830 |    1499 | 0.835 | 0.905 | 0.990 | 0.995 | 0.995 | 0.817 / 0.966 | 0.903 |      3 |
| fijo        | 1800 | solape 10%    |   658 |    1780 | 0.830 | 0.945 | 0.990 | 0.995 | 0.995 | 0.859 / 0.987 | 0.908 |     28 |
| semantica   | 1500 | percentil 50  |  1119 |     774 | 0.830 | 0.965 | 0.990 | 1.000 | 1.000 | 0.833 / 0.941 | 0.901 |      4 |
| semantica   | 1800 | percentil 70  |  1048 |     794 | 0.830 | 0.945 | 0.990 | 0.995 | 0.995 | 0.813 / 0.945 | 0.901 |      7 |
| semantica   | 1800 | percentil 50  |  1018 |     810 | 0.830 | 0.945 | 0.990 | 0.995 | 0.995 | 0.830 / 0.955 | 0.900 |      7 |
| estructural | 1500 | objetivo 100% |   753 |    1344 | 0.830 | 0.945 | 0.990 | 0.995 | 0.995 | 0.831 / 0.976 | 0.898 |      4 |
| semantica   | 1500 | percentil 70  |  1139 |     764 | 0.830 | 0.945 | 0.990 | 1.000 | 1.000 | 0.824 / 0.940 | 0.898 |      4 |
| fijo        | 1200 | solape 10%    |   972 |    1199 | 0.820 | 0.965 | 0.990 | 0.995 | 0.995 | 0.790 / 0.946 | 0.900 |      0 |
| estructural | 1800 | objetivo 60%  |   940 |    1037 | 0.820 | 0.965 | 0.990 | 0.995 | 0.995 | 0.831 / 0.945 | 0.893 |      0 |
| semantica   | 1800 | percentil 30  |   942 |     872 | 0.810 | 0.985 | 0.990 | 0.995 | 0.995 | 0.833 / 0.945 | 0.907 |      8 |
| fijo        | 1800 | solape 0%     |   623 |    1627 | 0.810 | 0.945 | 0.970 | 0.995 | 0.995 | 0.866 / 0.989 | 0.895 |     17 |
| estructural | 1800 | objetivo 80%  |   751 |    1334 | 0.790 | 0.965 | 0.990 | 0.995 | 0.995 | 0.853 / 0.977 | 0.882 |      1 |
| estructural | 1500 | objetivo 80%  |   884 |    1139 | 0.780 | 0.965 | 0.990 | 0.995 | 0.995 | 0.849 / 0.963 | 0.875 |      0 |
| estructural | 1800 | objetivo 100% |   632 |    1497 | 0.770 | 0.945 | 0.970 | 0.995 | 0.995 | 0.869 / 0.989 | 0.868 |     11 |

### Cómo leer la tabla

- **RU@K** es la exhaustividad por unidad: si se ha encontrado la asignatura correcta.
  Es la métrica principal porque el conjunto de evaluación anota unidades y no
  fragmentos. Aun así **no es inmune al troceo**: una unidad partida en más fragmentos
  ocupa más huecos del top-K, así que la columna **Frag.** hay que leerla al lado.
- **R@5 / techo** es la exhaustividad por fragmento con su máximo alcanzable. Al
  cambiar el troceo cambian el denominador de esa métrica y su techo, de modo que la
  cifra suelta no es comparable entre configuraciones.
- **Trunc.** son los fragmentos que superan la ventana del modelo y que `encode`
  recorta **en silencio**, sin avisar ni fallar.

<!-- FIN RESULTADOS AUTOMÁTICOS -->

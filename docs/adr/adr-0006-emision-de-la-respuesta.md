# ADR-0006: Emisión de la respuesta y la barrera de retirada

*Basado en https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions*

- **Estado:** Aceptada
- **Decisores:** Samuel Blanco Palmero
- **Contexto técnico:** Fase 3 (aplicación web), punto de entrada HTTP y `generador.responder()`

## Contexto

La aplicación web tiene que devolver al estudiante la respuesta que produce el
recorrido RAG. Cuánto tarda esa respuesta está medido sobre el registro del
banco del sistema, contando solo las preguntas de un turno que llegan a llamar
al modelo (n = 34, `gemma3:12b`, servidor de inferencia 0.32.14):

| Estadístico | Segundos |
| --- | ---: |
| Mínimo | 10,8 |
| Mediana | **62,7** |
| Percentil 90 | 125,3 |
| Máximo | 213,0 |

El 100 % pasa de 10 segundos y el 62 % pasa de 30. Las respuestas fijas
—cortesía, contexto vacío, centro ajeno— salen en 0,1 s porque no llegan a
llamar al modelo.

Con emisión síncrona el estudiante mira una pantalla sin cambios durante más de
un minuto, que es indistinguible de una aplicación bloqueada. La historia de
usuario de IT-44 pide responder «sin esperar tiempos absurdos», y el RNF-07
obliga a que la interfaz sea usable con un lector de pantalla, que necesita algo
que anunciar mientras la respuesta se compone.

**La restricción que condiciona la decisión** es que una de las tres barreras
de dominio actúa *después* de generar. `generador.responder()` pasa la respuesta
completa por `verificacion.titulaciones_inventadas()` y, si nombra una
titulación que no existe en el catálogo del índice, la descarta y devuelve
`RESPUESTA_TITULACION_INVENTADA`. Emitir la respuesta a trozos hace imposible
retirar lo que el estudiante ya ha leído.

Las otras dos barreras no se ven afectadas: el suelo de pertinencia y la
comprobación de centro ajeno actúan antes de generar, y sin fragmentos
recuperados no se llama al modelo.

## Alternativas consideradas

### Opción A — Emisión por partes verificada por unidades (elegida)

El servidor acumula la salida del modelo hasta una **frontera segura** —fin de
frase o fin de línea de lista—, pasa el **texto acumulado** por
`titulaciones_inventadas()` y solo entonces suelta esa unidad. Si la
comprobación falla, corta la emisión, descarta lo emitido y entrega la respuesta
fija.

- **Pros:** el primer texto aparece en segundos en lugar de en un minuto, y la
  barrera de retirada sigue existiendo con el mismo poder de detección.
- **Contras:** una titulación inventada detectada tarde obliga a borrar texto
  que el estudiante ya ha visto; y la verificación por unidades exige respetar
  la frontera segura (ver Decisión).

### Opción B — Emisión síncrona

Se genera la respuesta entera y se entrega de una vez. Es lo que hace hoy
`responder()`.

- **Pros:** las tres barreras quedan intactas sin tocar una línea; el estudiante
  nunca ve texto que después se retire.
- **Contras:** más de un minuto de pantalla sin cambios en la mediana, y más de
  dos en el percentil 90.

### Opción C — Emisión por partes sin verificar

Se reenvía al navegador lo que el modelo va produciendo, sin comprobar nada.

- **Pros:** la más simple de implementar y la de menor latencia percibida.
- **Contras:** **elimina la barrera de retirada**. El sistema pasaría de
  sostener la restricción de dominio sobre tres barreras a sostenerla sobre dos
  y sobre que el modelo se porte bien, que no es un control.

## Decisión

Se adopta la **opción A**.

Lo que cambia no es qué detecta la barrera, sino cuándo: pasa de *verificar la
respuesta completa antes de mostrarla* a *verificar el texto acumulado antes de
soltar cada unidad*. Detecta exactamente los mismos casos, porque la
comprobación es la misma función sobre el mismo texto.

**La frontera segura no es un detalle de implementación.**
`titulaciones_inventadas()` admite que las palabras de lo dicho sean un
subconjunto de las de una titulación real, para no retirar respuestas que
abrevian el nombre oficial. Esa tolerancia obliga a no verificar nunca un trozo
cortado a mitad de palabra: «Grado en Ingeniería» es subconjunto de una
titulación real y pasa, mientras que «Grado en Ingeniería Infor» no es
subconjunto de nada y produciría un **falso positivo** que retiraría una
respuesta correcta. Por eso solo se suelta en fin de frase o fin de línea, y por
eso se verifica el acumulado y no la unidad suelta: así un nombre partido entre
dos unidades tampoco puede engañar a la comprobación.

Lo que se pierde es la **discreción** de la retirada: hasta ahora el estudiante
nunca sabía que había habido una, y con la emisión por partes puede ver
desaparecer texto. Se acepta porque la evidencia dice que el suceso es raro:
**cero titulaciones inventadas en las 320 respuestas** del cribado de modelos
(ADR-0005) y **una sola retirada en las 57 entradas** del banco del sistema.

## Consecuencias

### Positivas

- El primer texto llega en segundos en lugar de en más de un minuto, sin tocar
  el modelo ni reabrir el ADR-0005.
- Las tres barreras de dominio siguen en pie. La restricción de dominio se sigue
  pudiendo defender sobre mecanismos y no sobre el buen comportamiento del
  modelo.
- La lógica de emisión queda en una función que devuelve las unidades ya
  verificadas, sin HTTP dentro, así que se prueba entera sin red y sin modelo.

### Negativas

- Una retirada tardía es visible: el estudiante puede leer texto que después
  desaparece. Es peor experiencia que la de la opción B, y se asume a cambio de
  no esperar un minuto en blanco.
- La respuesta deja de aparecer de golpe y aparece por frases, así que el tiempo
  total sigue siendo el mismo: **la emisión por partes no acelera nada**, solo
  cambia cuándo se ve lo primero. Presentarla como una mejora de rendimiento
  sería falso.
- El aviso de respuesta cortada por longitud solo se conoce al terminar, así que
  se añade al final y no puede anticiparse.

## Referencias

- ADR-0005, elección del modelo generativo: 320 respuestas medidas, cero
  titulaciones inventadas.
- `src/tfg_uja/verificacion.py`, `titulaciones_inventadas()`: la comparación por
  subconjunto de palabras que obliga a la frontera segura.
- `src/tfg_uja/generador.py`, `responder()`: las tres barreras y el orden en que
  actúan.
- `docs/experimentos/it38-sistema.md`: el banco de 57 entradas y la única
  retirada registrada.

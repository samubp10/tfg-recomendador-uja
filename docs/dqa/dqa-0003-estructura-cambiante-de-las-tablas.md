# DQA-0003: la estructura de las tablas de asignaturas cambia entre planes

*Formato adaptado de los registros de decisión de arquitectura (ADR) del
proyecto, aplicado aquí a anomalías de calidad de datos en lugar de a
decisiones de arquitectura: cada anomalía individual es demasiado pequeña
para justificar un ADR propio, pero exige la misma evidencia y el mismo
rigor que una decisión de diseño.*

- **Estado:** aceptada
- **Fecha:** 2026-08-05
- **Anomalías detectadas:** 03/07/2026 y 27/07/2026 (ver «Pruebas y evidencia»)
- **Ámbito técnico:** Fase 0 — rastreo del catálogo de asignaturas
  (`grados_spider.parse_asignaturas`)

## Contexto

El rastreador obtiene el catálogo de asignaturas de la tabla HTML que cada
titulación publica en su página de «Asignaturas y profesorado». La suposición
de partida, razonable al escribir el rastreador y falsa en cuanto se miró de
cerca, era que **todas esas tablas comparten estructura**: mismas columnas, en
el mismo orden, en todas las titulaciones y en todos los planes.

No la comparten. Y el modo en que fallan es el peor posible: **no fallan**. Una
tabla con las columnas cambiadas de sitio se sigue leyendo sin lanzar ninguna
excepción, solo que cada dato se toma de la columna equivocada. El resultado es
un catálogo incompleto que ningún test unitario detecta, porque los tests usan
la estructura que sí se conocía.

Es la tercera anomalía de la fuente que se documenta, después de la DQA-0001
(anomalías generales de la web) y la DQA-0002 (guías servidas en PDF). Las tres
juntas dicen algo que conviene tener escrito antes de que lo pregunten: **la
fuente es un blanco móvil**, y el corpus solo es fiable si el rastreador
sobrevive a que se mueva.

## Anomalías detectadas y tratamiento

### 1. Columna «Curso recomendado» intercalada en las tablas de mención

- **Evidencia.** Fixture real `tests/fixtures/tabla_geomatica_plan2025.html`,
  descargada de la página del Grado en Ingeniería Geomática y Topográfica
  (plan 2025). Contiene diez tablas con **dos estructuras distintas conviviendo
  en la misma página**:

  | Tablas | Cabecera |
  |---|---|
  | 1 a 8 (troncales) | `['Código', 'Asignatura', 'Tipo', 'Créditos ECTS']` |
  | 9 y 10 (menciones) | `['Código', 'Asignatura', '`**`Curso recomendado`**`', 'Mención', 'Créditos ECTS']` |

  Fila real de la tabla 9:

  ```text
  ['', 'Bases de datos geoespaciales', '4', 'TIG', '6']
  ```

  Leída por posición con el esquema de las tablas troncales, la tercera celda
  ---que debería ser el tipo de asignatura--- vale `'4'`, y la cuarta ---que
  debería ser los ECTS--- vale `'TIG'`. Como `'4'` no es un tipo válido, la
  fila se descarta. Sin excepción y sin traza.

  **Alcance medido sobre el corpus vigente:** las tablas afectadas aportan
  **19 de las 39 asignaturas** de la titulación, es decir el **49 %** de su
  catálogo. Son todas las optativas de mención.

- **Tratamiento.** `grados_spider._columnas_de_cabecera` resuelve la posición
  de cada columna **a partir de su rótulo**, no de su índice. Devuelve un
  diccionario con las claves que existan (`codigo`, `nombre`, `tipo`,
  `mencion`, `ects`) y **las columnas que no reconoce sencillamente se
  ignoran**: «Curso recomendado» no forma parte del modelo de datos del
  proyecto y no hay razón para incorporarlo.

  Los rótulos se comparan normalizados ---en minúsculas y sin tildes--- y por
  prefijo, porque la fuente no es consistente ni consigo misma: la misma
  columna aparece como «Tipo» en los grados simples y como «Carácter» en los
  planes de los dobles grados (DQA-0005).

  Si tras resolver los rótulos falta una columna imprescindible, la tabla se
  omite **con un aviso explícito** en lugar de leerse mal. Perder una tabla
  ruidosamente es preferible a leerla en silencio con las celdas cruzadas.

- **Alternativa descartada.** Mantener las posiciones fijas y añadir una
  excepción para el caso de Geomática. Se descarta porque no resuelve el
  problema, solo el síntoma: la anomalía no es que exista esa columna
  concreta, sino que la fuente **puede añadir columnas cuando quiera**. Una
  excepción por cada columna nueva obliga a descubrir cada cambio a base de
  que algo se rompa, que es exactamente lo que no ocurre aquí.

### 2. Cabecera reducida en el plan en extinción

- **Evidencia.** La misma titulación publicaba, en su plan anterior, una
  tercera estructura sin columna de tipo:

  ```text
  ['Código', 'Asignatura', 'ECTS']
  ```

  ⚠️ **Esta estructura no está reproducida en ninguna fixture**, y hay que
  decirlo: el plan en extinción se descarta en `parse` antes de rastrearlo
  (IT-77, a petición del tutor), porque un preuniversitario no puede
  matricularse en un plan que ya no admite alumnado nuevo. La observación
  quedó registrada al analizar la fuente, pero el caso salió del corpus antes
  de que hubiera un test que lo cubriera.

- **Tratamiento.** Sin columna de tipo ni de mención no se puede saber qué es
  cada asignatura, así que la tabla se omite avisando. Es el comportamiento
  correcto aquí: el dato no está, y el proyecto refleja los datos ausentes en
  lugar de imputarlos.

## Consecuencias

### Positivas

- El rastreador **sobrevive a que la fuente añada columnas**. Cualquier
  columna nueva que no se reconozca se ignora, y las conocidas se siguen
  localizando por su rótulo.
- Se recuperan las 19 asignaturas de mención de Geomática que antes se
  perdían, la mitad del catálogo de esa titulación.
- El fallo pasa de silencioso a ruidoso: una tabla que no se pueda interpretar
  deja un aviso, en vez de producir un catálogo incompleto que parece completo.

### Negativas

- 🔴 **El reconocimiento por prefijo está acotado a los rótulos observados.**
  Si la EPSJ renombrase «Asignatura» a «Materia» o «Créditos ECTS» a «Carga
  lectiva», la columna dejaría de reconocerse. El fallo sería ruidoso ---la
  tabla se omitiría con aviso--- pero seguiría siendo un fallo, y nadie lo ve
  si no se leen los avisos del rastreo.
- Los avisos del rastreador **no los comprueba la integración continua**,
  porque `data/` no se versiona y el rastreo no corre en CI. Detectar un
  cambio de la fuente depende de que alguien ejecute el rastreo y lea la
  salida, es decir, de una comprobación manual.
- «Curso recomendado» **se descarta**, no se almacena. Es un dato que la
  fuente publica y que el corpus no recoge; si en el futuro interesara
  recomendar un itinerario por cursos, habría que volver a rastrear.

## Pruebas y evidencia

> **Sobre la columna «Detectada».** Es la fecha del commit que incorpora la prueba de
> regresión de esa anomalía, que es la constancia verificable más próxima al hallazgo:
> el hallazgo en sí no deja rastro en el repositorio, la prueba sí. Cada fecha se puede
> comprobar con `git log -S "def <nombre de la prueba>" -- tests/`.

| Anomalía | Detectada | Evidencia | Prueba de regresión |
|---|---|---|---|
| Columna «Curso recomendado» intercalada en las tablas de mención | 27/07/2026 | `tabla_geomatica_plan2025.html` | `test_grados_spider.py::test_geomatica_no_pierde_las_tablas_con_columna_intercalada`, `::test_geomatica_la_mencion_no_se_lee_de_la_columna_equivocada`, `::test_geomatica_fusiona_la_optativa_repetida_sin_codigo`, `::test_geomatica_conserva_las_troncales_de_la_misma_pagina` |
| Las columnas deben localizarse por su rótulo y no por su posición | 27/07/2026 | `tabla_geomatica_plan2025.html` | `test_grados_spider.py::test_columnas_de_cabecera_localiza_por_rotulo_no_por_posicion`, `::test_columnas_de_cabecera_ignora_las_columnas_desconocidas` |
| Cabeceras envueltas en `<strong>` que impedían reconocer la tabla | 03/07/2026 | `tabla_asignaturas_iayc.html` | `test_grados_spider.py::test_extrae_grado_con_cabeceras_envueltas_en_strong` |
| Cabecera reducida del plan en extinción, sin columna de tipo | 03/07/2026 | **sin fixture**, ver la advertencia de la anomalía 2 | cubierta indirectamente por `test_grados_spider.py::test_no_rastrea_la_titulacion_en_extincion` (27/07/2026), que saca ese plan del corpus antes de leerlo |

La segunda fila de la tabla es la que sostiene el registro entero: la regla general no es
«añádase la columna de Geomática», sino **localizar cada columna por su rótulo**, comparado en
minúsculas y sin tildes porque la fuente no es consistente. Sobre la colección completa,
`scripts/check_dataset.py` comprueba el recuento por titulación, que es donde se vería una
tabla perdida.

## Cómo se corrige y cómo se detecta si vuelve

Esta anomalía es la más peligrosa de las cinco documentadas, porque **el modo en que falla es
no fallar**: una tabla con las columnas cambiadas se lee sin excepción, cada dato se toma de la
columna equivocada, la fila no valida y se descarta con un aviso. La titulación entera puede
desaparecer del corpus con el rastreo aparentemente correcto.

1. Ejecutar `py scripts/check_dataset.py`. Una titulación que pierde asignaturas se ve en el
   recuento; es la única señal que hay.
2. Revisar el registro del rastreo buscando avisos de filas descartadas. Un número alto en una
   sola titulación apunta a una cabecera nueva.
3. Descargar la página, guardarla como fixture y comprobar qué rótulos trae su cabecera.
4. Añadir el rótulo nuevo al mapa de `grados_spider._columnas_de_cabecera`, no un índice.
   Las columnas que no se reconocen se ignoran a propósito: no forman parte del modelo de
   datos y no hay razón para incorporarlas.

**Lo que no hay que hacer:** leer ninguna celda por su posición, ni siquiera «temporalmente».
Es el origen de esta anomalía y de la segunda del DQA-0005, que es la misma en otra titulación.


## Referencias

- Código: `src/tfg_uja/grados_spider.py`
  (`_columnas_de_cabecera`, `parse_asignaturas`).
- Fixture con el caso real: `tests/fixtures/tabla_geomatica_plan2025.html`.
- Tests de regresión: los de IT-76 en `tests/test_grados_spider.py`, que
  comprueban que las optativas de mención se extraen de las tablas con la
  columna intercalada.
- DQA-0001: anomalías generales de la web de la EPSJ.
- DQA-0002: guías docentes servidas en PDF.
- DQA-0005: los planes de los dobles grados, donde la misma columna se rotula
  «Carácter» y su valor se abrevia «OBL».
- ADR-0002: elección de Scrapy como extractor, que fija la extracción por
  `href` real y nunca por patrón, misma familia de razonamiento que llevar
  aquí a localizar columnas por rótulo y nunca por posición.

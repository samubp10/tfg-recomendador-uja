# DQA-0001: Anomalías de la fuente de datos (web EPSJ) y su tratamiento

- **Estado:** aceptada
- **Ámbito técnico:** Fase 0 — extracción (`grados_spider.py`) y limpieza de
  texto (`text_cleaner.py`, `validators.py`)

## Contexto

La web de la EPSJ contiene irregularidades estructurales y tipográficas que no
aparecen en la documentación de la fuente. El rastreador necesita reglas
deterministas para tratarlas sin completar, corregir ni perder datos en silencio.
Se agrupan en este registro porque comparten ámbito y ninguna justifica por sí
sola una decisión de arquitectura independiente.

## Alternativas consideradas

1. **Navegación.** Construir las URL a partir del nombre de la titulación es más
   simple, pero los *slugs* no siguen un patrón estable y existen URL reales que
   no se pueden deducir así. La alternativa es seguir siempre el `href` publicado.
2. **Tablas híbridas.** Tratar cada fila como una asignatura independiente
   duplicaría las optativas presentes en varias menciones. La alternativa es
   distinguir las tablas por sus cabeceras y fusionar las menciones por código.
3. **Trabajo Fin de Grado.** Normalizar todas sus apariciones a un único tipo
   impondría una uniformidad que la fuente no tiene. La alternativa es admitir
   tanto `OB` como `TFG`.
4. **Filas de relleno.** Mantener una lista manual por titulación no sería
   reproducible. La alternativa es reconocer el patrón `Optativa \d+` y excluirlo.
5. **Asignaturas sin guía.** Omitirlas ocultaría parte del plan de estudios. La
   alternativa es conservar sus datos y declarar que no tienen guía publicada.
6. **Ruido tipográfico.** Conservar espacios duros, caracteres de ancho cero,
   asteriscos de nota y marcas de oferta degradaría la comparación de textos. La
   alternativa es limpiarlos con reglas acotadas a los casos observados.
7. **URL de guía dañadas.** Aceptar el sufijo completo conduce a enlaces rotos.
   La alternativa es truncar tras la primera extensión `.html`, porque no existe
   contenido útil después de ella en los casos observados.
8. **Codificación.** Forzar la declaración UTF-8 del HTML produce texto corrupto
   cuando la cabecera HTTP indica ISO-8859-1. La alternativa es respetar la
   prioridad de codificación de Scrapy, documentada en el ADR-0002.

## Decisión

- Las peticiones siguen los `href` reales y nunca construyen URL por patrón.
- `parse_asignaturas` distingue tablas troncales y de mención por sus cabeceras;
  las optativas repetidas acumulan menciones sin duplicarse.
- `TIPOS_VALIDOS` admite `OB` y `TFG` tal como los publica cada plan.
- `es_placeholder` y `es_asignatura_valida` descartan las filas genéricas de
  optativas.
- Las asignaturas sin guía se conservan con `tiene_guia = False` y
  `url_guia = None`: un dato ausente se refleja, no se imputa.
- `limpiar_texto`, `quitar_nota_al_pie`, `separar_oferta` y `reparar_url`
  aplican las transformaciones tipográficas acotadas a los casos reales.
- Scrapy decide la codificación con la cabecera HTTP por delante del `<meta>`.

## Consecuencias

### Positivas

- Cada anomalía tiene una regla explícita y comprobable sobre fixtures reales.
- La extracción conserva las entidades incompletas sin inventar sus datos.
- Las irregularidades conocidas no dependen de una curación manual del corpus.

### Negativas

- Los patrones de limpieza cubren las variantes observadas; una anomalía nueva
  puede exigir ampliar las reglas.
- La aceptación de inconsistencias de la fuente traslada a las fases posteriores
  la obligación de interpretar correctamente los metadatos.
- Un rastreo puede terminar sin excepción aunque la fuente haya cambiado. Por
  eso `scripts/verificadores/check_dataset.py` comprueba la colección completa,
  además de las pruebas unitarias sobre fixtures.

## Referencias

- `src/tfg_uja/text_cleaner.py`, `src/tfg_uja/extraccion/validators.py` y
  `src/tfg_uja/extraccion/grados_spider.py`.
- `tests/fixtures/tabla_asignaturas.html`,
  `tests/fixtures/tabla_asignaturas_iayc.html` y
  `tests/fixtures/tabla_electrica.html`.
- `tests/test_text_cleaner.py`, `tests/test_validators.py` y
  `tests/test_grados_spider.py` contienen las pruebas de regresión de estos casos.
- `scripts/verificadores/check_dataset.py` valida los recuentos, los campos
  obligatorios y los tipos sobre la colección completa.
- ADR-0002, elección de Scrapy y tratamiento de la codificación.

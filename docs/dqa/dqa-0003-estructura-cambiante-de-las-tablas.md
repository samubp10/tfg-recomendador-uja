# DQA-0003: La estructura de las tablas de asignaturas cambia entre planes

- **Estado:** aceptada
- **Ámbito técnico:** Fase 0 — rastreo del catálogo de asignaturas
  (`grados_spider.parse_asignaturas`)

## Contexto

Las tablas de asignaturas de la EPSJ no comparten un esquema fijo. Una misma
página puede combinar cabeceras de cuatro columnas con tablas de mención que
intercalan «Curso recomendado», y otros planes emplean rótulos distintos o
carecen de una columna necesaria. Leer las celdas por posición puede cruzar los
datos y descartar filas válidas sin lanzar una excepción.

La fixture `tabla_geomatica_plan2025.html` contiene diez tablas: ocho usan
`Código · Asignatura · Tipo · Créditos ECTS` y dos añaden «Curso recomendado»
antes de «Mención». Estas dos últimas aportan 19 de las 39 asignaturas de la
titulación.

## Alternativas consideradas

1. **Posiciones fijas.** Mantiene el extractor simple, pero interpreta de forma
   incorrecta cualquier columna intercalada.
2. **Excepción para Geomática.** Resuelve el caso conocido, pero obliga a añadir
   otra excepción por cada cambio de la fuente.
3. **Localización por rótulo.** Identifica cada columna por el significado de su
   cabecera y permite ignorar las columnas ajenas al modelo de datos.
4. **Imputar un tipo cuando falta la columna.** Conserva filas, pero atribuye a la
   fuente un dato que no publica.
5. **Omitir la tabla incompleta con un aviso.** Pierde esos datos, pero hace la
   pérdida visible y respeta el principio de no imputación.

## Decisión

- `_columnas_de_cabecera` localiza `codigo`, `nombre`, `tipo`, `mencion` y `ects`
  por el rótulo, no por la posición.
- Los rótulos se comparan en minúsculas, sin tildes y por prefijo para admitir las
  variantes reales «Tipo» y «Carácter».
- Las columnas desconocidas, como «Curso recomendado», se ignoran porque no
  pertenecen al modelo de datos.
- Si falta una columna imprescindible, la tabla se omite con un aviso. No se
  inventa el valor ausente.
- Los planes en extinción se excluyen antes del rastreo y no forman parte del
  corpus destinado a estudiantes de nuevo ingreso.

## Consecuencias

### Positivas

- Añadir una columna a la fuente no desplaza las que sí consume el rastreador.
- Las optativas de mención de Geomática se extraen con su tipo, mención y ECTS
  correctos.
- Una cabecera que no se pueda interpretar produce un aviso en vez de un catálogo
  aparentemente válido e incompleto.

### Negativas

- El reconocimiento sigue limitado a los rótulos observados. Renombrar
  «Asignatura» como «Materia», por ejemplo, exige ampliar el mapa.
- Los avisos del rastreo no se comprueban en CI porque `data/` no se versiona.
- «Curso recomendado» se descarta; incorporarlo requeriría ampliar el modelo de
  datos y regenerar la colección.

## Referencias

- `src/tfg_uja/extraccion/grados_spider.py` (`_columnas_de_cabecera`,
  `parse_asignaturas`).
- `tests/fixtures/tabla_geomatica_plan2025.html` y
  `tests/fixtures/tabla_asignaturas_iayc.html`.
- Pruebas de IT-76 en `tests/test_grados_spider.py`, especialmente las que
  verifican la columna intercalada y la localización por rótulo.
- `scripts/verificadores/check_dataset.py`, que comprueba el recuento por
  titulación sobre la colección completa.
- DQA-0005, rótulo «Carácter» y abreviatura `OBL` en los dobles grados.

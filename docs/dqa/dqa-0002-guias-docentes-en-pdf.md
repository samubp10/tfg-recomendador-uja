# DQA-0002: Guías docentes servidas como PDF (curso 2026-27) y su tratamiento

- **Estado:** aceptada
- **Ámbito técnico:** Fase 1 — extracción (`grados_spider.py`, `guia_pdf.py`) y
  verificación (`check_dataset.py`, `check_guias_pdf.py`)

## Contexto

Las guías docentes del curso 2026-27 se sirven como PDF detrás de URL que
conservan la extensión `.html`. El tipo del recurso no se puede deducir de la
URL. Los PDF contienen el resumen y el temario que necesita el corpus, pero
también secciones ajenas al alcance, incluido un bloque de profesorado con
correos y teléfonos. Las 288 guías del corpus vigente proceden de PDF; el camino
HTML no participa en ese corpus.

## Alternativas consideradas

1. **Descartar los PDF.** Evita incorporar binario, pero elimina información
   docente extraíble y puede dejar sin contenido todas las guías del curso.
2. **Decidir por la extensión de la URL.** Es simple, pero clasifica estos PDF
   como HTML y contradice el tipo real de la respuesta.
3. **Filtrar por lista de prohibidos.** Permite retirar el profesorado conocido,
   pero una sección nueva con datos personales entraría en el corpus por defecto.
4. **Filtrar por lista de permitidos.** Solo admite «Resumen» y «Descripción de
   contenidos» y excluye cualquier sección nueva hasta revisarla.
5. **Retirar el extractor HTML.** Reduce código no ejercitado por el corpus
   vigente, pero deja al rastreador sin compatibilidad si la fuente vuelve a
   servir guías HTML.
6. **Conservar el extractor HTML.** Mantiene esa compatibilidad con un coste de
   mantenimiento acotado y pruebas sobre fixtures reales.

## Decisión

- El spider detecta el formato mediante `Content-Type` y la firma `%PDF` del
  cuerpo, nunca mediante la extensión de la URL.
- `guia_pdf.py` extrae exclusivamente «Resumen» y «Descripción de contenidos».
  Una redacción final elimina correos y teléfonos que pudieran atravesar el
  filtrado estructural.
- Si el PDF es ilegible o no aporta ninguna de las dos secciones, no se emite una
  guía con contenido: la asignatura conserva sus datos y recibe el tratamiento
  informativo correspondiente.
- `check_dataset.py` rechaza firmas PDF y densidades anómalas de caracteres de
  control en los campos de texto.
- El camino HTML se conserva como compatibilidad, aunque el corpus vigente no lo
  ejercita. El campo `formato` declara en cada guía qué extractor la produjo.
- El rastreo guarda los PDF originales en `data/guias_pdf/` para poder auditar la
  extracción con `check_guias_pdf.py`.

## Consecuencias

### Positivas

- El corpus conserva las guías publicadas sin introducir binario ni datos del
  profesorado.
- La lista de permitidos mantiene fuera cualquier sección desconocida por defecto.
- El formato real queda declarado y se puede verificar sobre la colección completa.

### Negativas

- La maquetación a dos columnas degrada a veces la separación de palabras y el
  orden de lectura frente al HTML.
- La extracción depende de una lista manual de rótulos observados. Un cambio de
  plantilla puede desplazar los límites de una sección sin producir una excepción.
- El extractor HTML se prueba con fixtures de otro curso, pero no con el corpus
  vigente; sus pruebas demuestran compatibilidad, no uso actual.
- `check_guias_pdf.py` debe ejecutarse al regenerar la colección, porque el CI no
  dispone de los datos ni de las copias originales.

## Referencias

- `src/tfg_uja/extraccion/guia_pdf.py` y
  `src/tfg_uja/extraccion/grados_spider.py` (`parse_guia`, `_guia_desde_pdf`).
- `scripts/verificadores/check_dataset.py` y
  `scripts/verificadores/check_guias_pdf.py`.
- `tests/fixtures/guia_estadistica_iayc.pdf`,
  `tests/fixtures/guia_matematica_discreta_informatica.pdf` y
  `tests/fixtures/guia_cartografia_geomatica2025.pdf`.
- `tests/test_guia_pdf.py` y `tests/test_grados_spider.py` cubren la detección del
  formato, el recorte de secciones, la exclusión de datos personales y el manejo
  de PDF ilegibles.
- DQA-0001, anomalías generales de la fuente.

# DQA-0002: Guías docentes servidas como PDF (curso 2026-27) y su tratamiento

_Aplicado, como el DQA-0001, a una anomalía de calidad de datos y no a una
decisión de arquitectura: la fuente cambia de formato a mitad de curso y el
rastreador debe adaptarse sin volcar binario ni datos personales en la
colección._

- **Estado:** aceptada
- **Fecha:** 2026-07-23
- **Ámbito técnico:** Fase 1 — extracción (`grados_spider.py`,
  `guia_pdf.py`) y verificación del dataset (`scripts/check_dataset.py`)

## Contexto

El DQA-0001 documentó las anomalías descubiertas durante el desarrollo de la
Fase 0, todas sobre un rastreo del curso 2025-26. Al re-ejecutar el rastreador
el 23/07/2026 —el primero desde el 09/07— aparece una anomalía nueva, de una
naturaleza distinta a las anteriores: no es un defecto tipográfico de una
página concreta, sino un **cambio de formato de la fuente** que rompe una
suposición del rastreador.

La EPSJ ha empezado a publicar las guías docentes del curso **2026-27**, y las
sirve como **PDF** en lugar de HTML, pero detrás de una URL que sigue acabando
en `.html`. En el momento de escribir este registro, **62 de las 296** guías ya
son de 2026-27 y las 62 llegan como PDF; las 234 de 2025-26 siguen en HTML. La
proporción crecerá conforme la EPSJ publique el resto de guías del nuevo curso.

## Anomalía detectada y tratamiento

### El formato de la guía cambia de HTML a PDF a mitad de curso

- **Evidencia:** el servidor responde con `Content-Type: application/pdf` y
  `Content-Disposition: inline; filename=guia_docente_2026-27_NNNNNNNN.pdf`
  ante una URL acabada en `.html` (por ejemplo, la guía `15711008`, Estadística
  del Grado en Inteligencia Artificial y Ciberseguridad). El rastreador, que
  esperaba HTML, no encontraba la estructura, activaba el mecanismo de respaldo
  y guardaba ~48 000 caracteres del binario del PDF en `cuerpo_general`. Las
  guías con respaldo pasaban de 5 a 67 y una sola guía contaminada generaba 43
  fragmentos de binario en el campo que se vectoriza.
- **Tratamiento:** el spider decide por el **tipo de contenido de la respuesta**
  (cabecera `Content-Type` y firma `%PDF` del cuerpo), no por la extensión de la
  URL. Cuando la respuesta es un PDF, la extracción se delega en el módulo
  `guia_pdf.py`, que saca el resumen y el temario del texto del PDF y devuelve
  la guía con la misma forma que la extracción desde HTML. Si el PDF no se puede
  leer o no contiene ninguna de las dos secciones, no se emite guía: la
  asignatura queda como «sin guía» (un chunk informativo, IT-09), nunca con el
  binario volcado por el mecanismo de respaldo.
- **Alternativa descartada:** descartar por completo las guías en PDF y tratar
  esas 62 asignaturas como «sin guía». Descartada porque los PDF son texto
  extraíble (no escaneos) y contienen exactamente el resumen y el temario que la
  colección necesita: renunciar a ellos empobrecería el corpus sin motivo, y a
  final de curso podrían ser la totalidad de las guías.

### Riesgo asociado: datos personales en el PDF

- **Evidencia:** a diferencia del HTML, el PDF incluye un bloque `PROFESORADO`
  con nombre, departamento, categoría, despacho, **correo electrónico y
  teléfono** de cada profesor. En los tres PDF reales analizados aparecían entre
  4 y 6 correos y entre 2 y 4 teléfonos. La colección excluye el profesorado a
  propósito (decisión de proyecto por privacidad/RGPD), y sobre esa exclusión se
  apoya el marco legal descrito en la memoria.
- **Tratamiento:** la extracción funciona por **lista de permitidos**: solo
  pasan al corpus las secciones «Resumen» y «Descripción de contenidos»; el
  resto del PDF, incluido el bloque de profesorado, se descarta por defecto.
  Como red de seguridad final, el texto ya filtrado se redacta de cualquier
  correo o teléfono que hubiera escapado. Un test de regresión comprueba, sobre
  los tres PDF reales, que no sale ni un correo ni un teléfono.
- **Alternativa descartada:** filtrar por lista de prohibidos (eliminar la
  sección de profesorado y conservar el resto). Descartada porque una sección
  nueva con datos personales, añadida por la UJA en el futuro, se colaría sola;
  una lista de permitidos la deja fuera por defecto.

### Los verificadores no detectaban la contaminación

- **Evidencia:** `check_dataset.py` respondía «Dataset OK» sobre los datos
  contaminados con binario. Es el cuarto defecto que la batería de pruebas en
  verde no detecta (los tres anteriores están en la memoria).
- **Tratamiento:** `check_dataset.py` falla ahora si cualquier campo de texto
  (`resumen`, `temario`, `cuerpo_general`, `texto`) contiene la firma `%PDF` o
  una densidad alta de caracteres de control. Verificado: falla sobre el rastreo
  contaminado (62 ítems) y sigue pasando sobre el dataset limpio.

## Consecuencias

### Positivas

- El rastreador deja de depender de la extensión de la URL y decide por el tipo
  real de la respuesta, más robusto ante futuros cambios de la fuente.
- El corpus conserva las 62 guías del nuevo curso en lugar de perderlas.
- El filtrado por lista de permitidos hace que la exclusión del profesorado sea
  robusta ante cambios de plantilla, no un parche sobre la estructura conocida.
- El verificador ya no puede dar «OK» sobre un dataset con binario.

### Negativas

- El texto extraído del PDF es de peor calidad estructural que el del HTML: la
  maquetación a dos columnas junta a veces palabras (`adecuadosde`) y el orden
  de lectura no siempre es perfecto. Es aceptable para incrustar, pero no es tan
  limpio como el HTML.
- La lista de rótulos de sección (`_ROTULOS_SECCION`) está acotada a las
  variantes observadas en la plantilla actual de la UJA; una plantilla nueva con
  rótulos distintos podría hacer que una sección permitida sobre-recoja hasta el
  siguiente rótulo conocido. La lista de permitidos y la redacción final de
  datos personales acotan el daño, pero conviene revisarla si cambia la
  plantilla.
- La cifra «5 guías activan el respaldo» de la memoria es del snapshot de
  2025-26 y hay que reinterpretarla al caracterizar el corpus (IT-58): el corpus
  ya no es una foto atemporal, sino de un curso concreto.

## Referencias

- `src/tfg_uja/guia_pdf.py`, `src/tfg_uja/grados_spider.py`
  (`parse_guia`, `_guia_desde_pdf`).
- `scripts/check_dataset.py` (comprobación de binario en campos de texto).
- `tests/test_guia_pdf.py`, `tests/test_grados_spider.py`
  (fixtures `guia_estadistica_iayc.pdf`,
  `guia_matematica_discreta_informatica.pdf`,
  `guia_cartografia_geomatica2025.pdf`).
- DQA-0001 (anomalías de la Fase 0 sobre el rastreo de 2025-26).

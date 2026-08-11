# DQA-0002: Guías docentes servidas como PDF (curso 2026-27) y su tratamiento

_Aplicado, como el DQA-0001, a una anomalía de calidad de datos y no a una
decisión de arquitectura: la fuente cambia de formato a mitad de curso y el
rastreador debe adaptarse sin volcar binario ni datos personales en la
colección._

- **Estado:** aceptada
- **Fecha:** 2026-07-23
- **Anomalías detectadas entre:** 23/07/2026 y 29/07/2026 (ver «Pruebas y evidencia»)
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

## Actualización (29/07/2026): la migración se completó

Lo de arriba se escribió el 23/07/2026, con la migración a medias: **62 de 296**
guías en PDF y las 234 restantes todavía en HTML. Seis días después, sobre el
rastreo del 28/07, la proporción ya no es una proporción:

```text
guías del corpus                                   288
campos con la firma del troceado HTML («\n\n»)       0
campos con la firma del troceado PDF  («\n»)       564
guías que activaron el mecanismo de respaldo         0
```

**Las 288 vienen de PDF. Ninguna de HTML.**

La comprobación no es una estimación. El camino HTML (`_contenido_seccion`) une
sus bloques con **doble** salto de línea, y cada bloque pasa por
`limpiar_texto`, que colapsa todo espacio en blanco —saltos incluidos— en
espacios simples. Un texto extraído del HTML **no puede contener un salto de
línea suelto**: o no tiene ninguno, o los tiene de dos en dos. El camino PDF
(`_seccion`) une línea a línea con salto simple. No hay ni un doble salto en
todo el corpus, y sí 564 campos con saltos simples.

### El camino HTML se conserva por retrocompatibilidad

Quedan sin ejercitar, con el corpus actual, cuatro piezas del rastreador
—unas 64 líneas, en torno al 9 % de `grados_spider.py`—:

| Pieza | Para qué era | Veces que se ejecuta hoy |
| --- | --- | --- |
| `_contenido_seccion` | Localizar resumen y temario por el `id` de su sección | 0 |
| `UMBRAL_CONTENIDO_GUIA` | Detectar que la estructura esperada no aparece | 0 |
| `_limpieza_general` | Mecanismo de respaldo | 0 |
| `cuerpo_general` (campo) | Guardar lo que produce ese respaldo | 0 |

- **Tratamiento:** se conservan, y se declaran explícitamente como camino de
  retrocompatibilidad en vez de dejarlo implícito en el código. La decisión no
  se apoya en que el código sea barato de mantener, sino en la **asimetría del
  riesgo**: conservarlo no cuesta nada apreciable, y retirarlo cuesta volver a
  escribirlo si la fuente vuelve al HTML. Y la fuente no da garantías: ha
  cambiado de formato **dos veces en un año** (este DQA y el DQA-0003), y servir
  un PDF detrás de una URL acabada en `.html` tiene más aspecto de artefacto de
  una migración en curso que de decisión firme.
- **Alternativa descartada:** retirar el camino HTML y quedarse solo con el PDF.
  Descartada por lo anterior. Simplificaría el rastreador y la explicación de la
  memoria, pero a cambio de tener que reimplementarlo bajo presión de calendario
  si la Escuela revierte el formato antes de la entrega.
- **Alternativa descartada:** dejarlo sin declarar, tal como estaba. Descartada
  porque un camino que no se ejecuta nunca y que nadie ha marcado como tal acaba
  leyéndose como parte del flujo normal —de hecho, así estaba escrita la sección
  correspondiente de la memoria—, y eso induce a error a quien lo lea después.

### Riesgo que hay que declarar, no tapar

Sus pruebas **seguirán pasando indefinidamente**, porque usan fixtures HTML de
2025-26 que ya no se corresponden con lo que sirve la web. No es que mientan:
comprueban correctamente un escenario que hoy no ocurre. Pero un conjunto de
pruebas en verde sobre un camino muerto es, otra vez, un verificador que mide
algo distinto de lo que parece medir, así que conviene decirlo en voz alta.

La consecuencia práctica es que **el esfuerzo de mejora va íntegro al camino
PDF**. Para enterarse el día que esto cambie, IT-95 añade un campo `formato` al
ítem `guia` y hace que `check_dataset.py` informe del reparto HTML/PDF: hoy esa
proporción solo se puede deducir mirando los saltos de línea, que es una pista,
no un dato.

### Corrección a lo que decía este registro

La sección «Negativas» de arriba anticipaba el riesgo de la lista
`_ROTULOS_SECCION` y lo daba por acotado. Con la migración completa hay que
subirle el peso: esa lista de 17 rótulos, escrita a mano contra la plantilla
observada, sostiene ahora **el 100 % del contenido de la colección**, no una
parte. Se recoge como amenaza a la validez de constructo en la memoria y motiva
la tarjeta IT-95.

## Pruebas y evidencia

La evidencia son **tres PDF reales** descargados de la EPSJ, no documentos construidos para la
ocasión: un PDF sintético no trae el bloque de profesorado, ni el pie de página, ni la
tipografía que hace que un tema en mayúsculas se confunda con un rótulo de sección.

> **Sobre la columna «Detectada».** Es la fecha del commit que incorpora la prueba de
> regresión de esa anomalía, que es la constancia verificable más próxima al hallazgo:
> el hallazgo en sí no deja rastro en el repositorio, la prueba sí. Cada fecha se puede
> comprobar con `git log -S "def <nombre de la prueba>" -- tests/`.

| Anomalía o riesgo | Detectada | Evidencia | Prueba de regresión |
|---|---|---|---|
| La guía llega en PDF tras una URL acabada en `.html` | 23/07/2026 | `guia_estadistica_iayc.pdf` | `test_guia_pdf.py::test_es_pdf_detecta_por_cabecera_y_por_firma`, `test_grados_spider.py::test_una_guia_en_pdf_se_extrae_sin_binario_ni_fallback` |
| El PDF trae correos y teléfonos del profesorado | 23/07/2026 | los tres PDF | `test_guia_pdf.py::test_no_incluye_el_bloque_de_profesorado`, `::test_no_filtra_datos_personales` |
| El temario se cortaba en el primer tema escrito en mayúsculas | 23/07/2026 | `guia_matematica_discreta_informatica.pdf` | `test_guia_pdf.py::test_el_temario_no_se_corta_en_el_primer_tema_en_mayusculas` |
| El pie de página se colaba en el contenido | 23/07/2026 | `guia_cartografia_geomatica2025.pdf` | `test_guia_pdf.py::test_no_arrastra_el_pie_de_pagina` |
| Un PDF ilegible no debe emitir guía ni activar el respaldo | 23/07/2026 | — | `test_guia_pdf.py::test_un_pdf_ilegible_devuelve_none`, `test_grados_spider.py::test_una_guia_en_pdf_ilegible_no_emite_item` |
| El rastreo debe conservar copia del original para poder auditarlo | 29/07/2026 | — | `test_grados_spider.py::test_el_rastreo_guarda_una_copia_del_pdf_para_auditarlo`, `::test_tambien_se_guarda_el_pdf_del_que_no_se_extrae_nada`, `::test_un_fallo_al_guardar_el_pdf_no_tumba_el_rastreo` |
| Un cambio de la plantilla movería las fronteras de sección | 29/07/2026 | los tres PDF | `test_guia_pdf.py::test_no_le_falta_a_la_guia_ningun_rotulo_de_la_plantilla`, `::test_se_detecta_que_la_fuente_renombre_un_rotulo`, `::test_ni_el_profesorado_ni_la_cabecera_se_confunden_con_un_rotulo`, `::test_los_rotulos_salen_en_orden_de_lectura` |
| El formato de cada guía debe quedar declarado en el dato | 29/07/2026 | — | `test_grados_spider.py::test_la_guia_declara_de_que_formato_viene` |

Sobre la colección completa lo comprueba `scripts/check_guias_pdf.py`, que audita las 288
guías contra su PDF original y enumera, sección por sección, qué se conserva y qué se
descarta. Su salida sobre el corpus vigente: **946 218 caracteres conservados de 5 010 100, un
18,9 %**, y el resto descartado con nombre ---cláusulas, sistemas de evaluación, metodologías,
competencias, bibliografía y profesorado---. `check_dataset.py` falla además si cualquier campo
de texto contiene la firma `%PDF` o una densidad alta de caracteres de control.

## Cómo se corrige y cómo se detecta si vuelve

El riesgo vivo de este registro no es el cambio de formato, que ya está tratado, sino que
**la plantilla del PDF cambie**: si un rótulo se renombra o desaparece, una sección deja de
terminar donde debe y o se pierde contenido o se arrastra el bloque de profesorado. No se
manifiesta como error.

1. Ejecutar `py scripts/check_guias_pdf.py`. Comprueba por **ausencia**: avisa si a alguna
   guía le falta uno de los rótulos que la plantilla compone siempre. Un rótulo de más no
   significa nada; uno de menos significa que la plantilla ha cambiado.
2. Si avisa, abrir el PDF de `data/guias_pdf/` ---el rastreo guarda una copia de cada uno
   justamente para esto--- y comparar sus rótulos con `_ROTULOS_SECCION` de `guia_pdf.py`.
3. Añadir el PDF real como fixture y escribir la prueba antes de tocar el código.
4. Al ampliar la lista de rótulos, **mantener la lista de PERMITIDOS**: solo «Resumen» y
   «Descripción de contenidos» pasan al corpus. Con una lista de prohibidos, una sección
   nueva con datos personales entraría sola.
5. Volver a ejecutar `check_guias_pdf.py` y `check_dataset.py` sobre la colección completa.

**Lo que no hay que hacer:** decidir el formato por la extensión de la URL. Sigue acabando en
`.html` y devuelve un PDF; la decisión se toma por el tipo de contenido de la respuesta y por
la firma `%PDF` del cuerpo.


## Referencias

- `src/tfg_uja/guia_pdf.py`, `src/tfg_uja/grados_spider.py`
  (`parse_guia`, `_guia_desde_pdf`).
- `scripts/check_dataset.py` (comprobación de binario en campos de texto).
- `tests/test_guia_pdf.py`, `tests/test_grados_spider.py`
  (fixtures `guia_estadistica_iayc.pdf`,
  `guia_matematica_discreta_informatica.pdf`,
  `guia_cartografia_geomatica2025.pdf`).
- DQA-0001 (anomalías de la Fase 0 sobre el rastreo de 2025-26).

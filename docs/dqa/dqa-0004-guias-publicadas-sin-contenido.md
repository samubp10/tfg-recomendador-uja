# DQA-0004: Guías docentes publicadas con las secciones de contenido vacías

_Anomalía de calidad de datos, con la misma estructura que un ADR: no es una
decisión de arquitectura, pero exige la misma evidencia. Continúa la serie del
DQA-0001 (anomalías de la Fase 0), DQA-0002 (el cambio de formato a PDF) y
DQA-0003 (el cambio de estructura de las tablas)._

- **Estado:** aceptada
- **Fecha:** 2026-07-29
- **Ámbito técnico:** Fase 1 — extracción (`guia_pdf.py`, `grados_spider.py`) y
  fragmentación (`chunker.py`)

## Contexto

IT-94 encontró cinco asignaturas que desaparecían del corpus enteras: la tabla
del plan de estudios enlazaba su guía, pero el ítem de guía nunca llegaba a
emitirse, y el fragmentador tampoco les daba el fragmento informativo que da a
las asignaturas sin guía. Se corrigió, y el fragmento resultante decía que el
contenido de la guía **«no ha podido obtenerse»**.

Al preparar IT-95 se comprobó de dónde venía ese fallo, y resultó que no había
tal fallo.

## Anomalía detectada y tratamiento

### La fuente publica la guía con la plantilla vacía

- **Evidencia:** descargadas el 29/07/2026 las seis guías implicadas (las cinco
  de IT-94 más la única del corpus con menos de 200 caracteres útiles), las seis
  responden `200 application/pdf`, se abren sin error y `pypdf` extrae de ellas
  entre 9 324 y 12 990 caracteres, con los 13 rótulos de la plantilla en su sitio.

  | Código | Bytes | Caracteres extraídos | Rótulos | RESUMEN | CONTENIDOS |
  | --- | ---: | ---: | ---: | ---: | ---: |
  | 15411008 | 46 759 | 9 324 | 13 / 13 | 0 | 0 |
  | 15712013 | 47 858 | 10 298 | 13 / 13 | 0 | 0 |
  | 15712014 | 48 100 | 10 372 | 13 / 13 | 0 | 0 |
  | 15712018 | 48 779 | 10 760 | 13 / 13 | 0 | 0 |
  | 15712020 | 51 213 | 12 990 | 13 / 13 | 0 | 0 |
  | 15712019 | 48 059 | 10 610 | 13 / 13 | 110 | 0 |

  En 15411008, las tres líneas consecutivas del PDF son:

  ```text
  RESUMEN
  DESCRIPCIÓN DE CONTENIDOS
  METODOLOGÍAS DOCENTES Y ACTIVIDADES FORMATIVAS
  ```

  Un rótulo detrás de otro, sin nada en medio. La sección existe y está vacía.

  El caso 15712019 lo confirma desde el otro lado: su resumen son 110 caracteres
  de plantilla («Sin conocimientos previos exigidos. Sin prerrequisitos.») y su
  temario está vacío. Aporta un fragmento al corpus que no dice nada.

  Las seis pertenecen a planes en implantación (154A y 157A), lo que encaja: son
  asignaturas de cursos superiores cuyo contenido docente aún no se ha publicado
  para 2026-27.

- **Tratamiento:** se separa el motivo del efecto. El efecto —la asignatura
  entra al corpus con sus datos básicos— ya lo resolvió IT-94 y no cambia. Lo
  que cambia es lo que el corpus **afirma**: el fragmento pasa a decir que la
  guía está publicada y que no recoge ni resumen ni temario. Y el aviso del
  rastreo deja de llamar «PDF ilegible» a un PDF que se lee, gracias a
  `motivo_sin_guia`, que distingue cuatro causas posibles: PDF corrupto o
  cifrado, PDF sin capa de texto, rótulos que no encajan con los conocidos, y
  secciones vacías en el origen. **Solo la última se ha observado.**

- **Alternativa descartada:** un único texto vago («no se dispone del contenido
  de la guía») para todos los casos. Nunca miente, pero pierde información útil
  de verdad: a un estudiante no le dicen lo mismo «todavía no está publicada»
  —conviene volver a mirar más adelante— y «está publicada y vacía».

- **Alternativa descartada:** distinguir en el texto del fragmento las cuatro
  causas. Para quien pregunta no hay diferencia entre «no se pudo leer» y «está
  vacía»: en los dos casos no hay contenido. El motivo exacto se registra donde
  sirve —el aviso del rastreo y la auditoría de IT-95—, no en un texto que solo
  puede decir lo mismo con más palabras.

## Consecuencias

### Positivas

- El corpus deja de contener una afirmación falsa sobre sí mismo. Es el mismo
  criterio de IT-94 en la otra dirección: allí no se podía negar una publicación
  que existe; aquí no se puede insinuar un fallo propio que no ha ocurrido.
- El rastreo informa del motivo real, así que un cambio de plantilla —el caso
  peligroso, que no se ha dado— se distinguiría de una guía vacía, que es
  rutinario.

### Negativas

- **La cobertura de guías está inflada.** Estas guías cuentan hoy como cobertura
  y aportan cero contenido. La cifra que se publique en la memoria debería
  separar guías con contenido de guías publicadas y vacías, o al menos declarar
  que no lo hace. Refuerza la amenaza a la validez ya declarada sobre el sesgo
  de cobertura hacia las titulaciones en implantación: no solo concentran las
  asignaturas sin guía, sino también las guías vacías.
- El recuento exacto de guías vacías se conocerá al regenerar el dataset (IT-80).
  Las seis de arriba son las observadas sobre el rastreo del 28/07/2026, no una
  cifra definitiva.
- Queda sin prueba de regresión el caso «guía publicada con las secciones
  vacías»: añadir su PDF a las fixtures agravaría un problema aparte —las tres
  fixtures actuales versionan 9 correos y 6 teléfonos de profesorado real— que
  se resuelve antes de hacer público el repositorio.

## Referencias

- `src/tfg_uja/guia_pdf.py` (`motivo_sin_guia`), `src/tfg_uja/chunker.py`
  (texto del fragmento informativo).
- `scripts/check_guias_pdf.py` (auditoría de la extracción, IT-95).
- IT-94 (la asignatura no desaparece), IT-95 (auditoría de las guías en PDF).
- DQA-0002 (cambio de formato de la fuente a PDF).

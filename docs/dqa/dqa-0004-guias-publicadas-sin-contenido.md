# DQA-0004: Guías docentes publicadas con las secciones de contenido vacías

- **Estado:** aceptada
- **Ámbito técnico:** Fase 1 — extracción (`guia_pdf.py`, `grados_spider.py`) y
  fragmentación (`chunker.py`)

## Contexto

La fuente publica guías PDF válidas cuya plantilla incluye los rótulos «Resumen»
y «Descripción de contenidos», pero sin texto útil dentro de esas secciones. Seis
guías reales presentan este caso: cinco tienen ambas secciones vacías y una solo
contiene un resumen genérico de 110 caracteres. El PDF se descarga y se puede
leer; la ausencia pertenece a la fuente y no a la extracción.

La asignatura debe seguir formando parte del plan de estudios. El corpus, además,
debe distinguir una guía publicada y vacía de una guía inexistente o ilegible.

## Alternativas consideradas

1. **Texto único para cualquier ausencia.** «No se dispone del contenido» evita
   afirmar una causa incorrecta, pero oculta si la guía no existe o está publicada
   sin resumen ni temario.
2. **Exponer las cuatro causas técnicas en el fragmento.** Conserva todo el
   diagnóstico, pero añade detalle sin utilidad para quien consulta: en todos los
   casos falta el contenido docente.
3. **Distinguir solo el estado relevante para el usuario.** El fragmento separa
   «sin guía publicada» de «guía publicada sin resumen ni temario», mientras que
   el registro del rastreo conserva la causa técnica exacta.
4. **Completar desde otro curso o titulación.** Aumenta la cobertura aparente,
   pero imputa contenido que la fuente vigente no atribuye a esa asignatura.

## Decisión

- La asignatura se conserva y recibe un fragmento informativo aunque no exista
  contenido útil de guía.
- `motivo_sin_guia` distingue PDF corrupto o cifrado, PDF sin capa de texto,
  rótulos no reconocidos y secciones vacías en el origen.
- El texto dirigido al usuario distingue la guía no publicada de la guía publicada
  sin resumen ni temario; el detalle técnico queda en el registro y la auditoría.
- El contenido ausente no se completa con otro curso, otra titulación ni un texto
  generado: se refleja, no se imputa.

## Consecuencias

### Positivas

- Ninguna asignatura desaparece por carecer de contenido en su guía.
- El corpus describe la ausencia sin atribuirla erróneamente a un fallo de lectura.
- Un cambio de plantilla queda separado del caso rutinario de una sección vacía.

### Negativas

- Contar guías publicadas no equivale a medir cobertura útil: estas guías aportan
  cero contenido docente. Las cifras de cobertura deben separar ambos conceptos.
- Los casos vacíos se concentran en planes en implantación, lo que aumenta el sesgo
  de cobertura entre titulaciones.
- No se versiona como fixture ninguno de los seis PDF vacíos porque contienen datos
  personales del profesorado. La regresión se cubre en el nivel de clasificación y
  fragmentación, no con uno de esos documentos completos.

## Referencias

- `src/tfg_uja/extraccion/guia_pdf.py` (`motivo_sin_guia`) y
  `src/tfg_uja/indexacion/chunker.py` (fragmento informativo).
- `tests/test_guia_pdf.py`, `tests/test_chunker.py` y
  `tests/test_check_chunks.py`.
- `scripts/verificadores/check_guias_pdf.py`, auditoría de la extracción sobre los
  PDF originales.
- DQA-0002, tratamiento de las guías servidas como PDF.

# DQA-NNNN: título del ámbito de anomalías

*Formato adaptado de los registros de decisión de arquitectura (ADR) del
proyecto, aplicado aquí a anomalías de calidad de datos en lugar de a
decisiones de arquitectura: cada anomalía individual es demasiado pequeña
para justificar un ADR propio, pero exige la misma evidencia y el mismo
rigor que una decisión de diseño.*

- **Estado:** propuesta | aceptada | sustituida por DQA-XXXX
- **Fecha:** AAAA-MM-DD
- **Ámbito técnico:** [Fase, módulo o componente afectado]

## Contexto

Qué proceso o módulo reveló las anomalías (rastreo, fragmentación,
indexación...) y por qué ninguna de ellas justifica un ADR propio, pero en
conjunto merecen un registro con evidencia.

## Anomalías detectadas y tratamiento

### N. [Nombre breve de la anomalía]

- **Evidencia:** qué se observó y dónde (fichero, línea, fixture, caso
  real). Nunca una anomalía hipotética.
- **Tratamiento:** qué hace el código ante esa anomalía, con la función o
  módulo responsable.
- **Alternativa descartada:** *(si la hay)* qué otro tratamiento se
  consideró y por qué se descartó.

*(Repetir una subsección por cada anomalía del mismo ámbito.)*

## Consecuencias

### Positivas
- Qué se gana al tratar la anomalía de esta forma.

### Negativas
- Qué riesgo o limitación queda abierto (p. ej. un patrón acotado a los
  casos observados que no cubre variantes futuras no vistas).

## Referencias
- Módulos de código afectados.
- Fixtures o tests que reproducen la anomalía.
- ADR relacionados, si el tratamiento se apoya en una decisión de
  arquitectura ya documentada (para no duplicar contenido).
# Recuperación del sistema sobre el conjunto de IT-27 (IT-38)

> Lo escribe `scripts/experimentos/experimento_recuperacion.py`. **No editar a mano.**

- Modelo de incrustaciones: `intfloat/multilingual-e5-small`
- Fragmentos del corpus: **1499**
- Preguntas de dominio: **56**
- Preguntas ajenas al dominio: **10**
- Procedencia del corpus: extracción 2026-08-16, origen ?

## Techos alcanzables

Hay preguntas cuyas unidades relevantes son más que K, así que su
Recall@K no puede valer 1. **Cada cifra se lee contra su techo, no
contra 1.** Por unidad el techo siempre es 1 y la cifra se interpreta
sola.

| K | Techo de Recall@K por fragmento |
| ---: | ---: |
| 3 | 0.754 |
| 5 | 0.906 |
| 10 | 0.966 |

## Resultado

| K | Recall@K | Techo | Recall de unidad@K |
| ---: | ---: | ---: | ---: |
| 3 | 0.652 | 0.754 | 0.906 |
| 5 | 0.789 | 0.906 | 0.973 |
| 10 | 0.881 | 0.966 | 0.991 |

**MRR: 0.926**

## Preguntas ajenas al dominio

No entran en las métricas de arriba: su lista de relevantes está vacía
y aportarían un cero fijo a las dos. Aquí el acierto es el contrario,
quedarse sin ningún fragmento, porque entonces no se llega a llamar al
modelo.

**Rechazadas por el recuperador: 6 de 10.**

De las 4 que pasan el suelo, no todas son un
fallo, y mezclarlas exagera el problema. Se separan en tres:

* **2 son peticiones de
  consejo**, y que pasen es deliberado: a esas el sistema les entrega la
  banda completa a propósito. Quien pregunta qué carrera le pega no debe
  recibir silencio, sino lo que sí se imparte aquí. Contarlas como fallo
  del filtro sería contar como error el comportamiento que se busca.
* **0 las para la comprobación
  de otro centro**, que actúa después del suelo y antes del modelo. Pasar
  el suelo no es lo mismo que ser respondida.
* **2 pasan sin ninguna de las dos
  cosas.** Esta es la cifra que mide de verdad el hueco, y la única que
  hay que mirar para saber si el sistema se sale de su dominio.

| Pregunta | Fragmentos recibidos | Petición de consejo | Otro centro |
| --- | ---: | :---: | :---: |
| P-051 | 3 | no | no |
| P-052 | 20 | no | no |
| P-053 | 20 | sí | no |
| P-054 | 20 | sí | no |
| P-055 | rechazada | no | sí |
| P-056 | rechazada | no | sí |
| P-057 | rechazada | no | no |
| P-058 | rechazada | no | no |
| P-059 | rechazada | no | no |
| P-060 | rechazada | no | no |

## Rechazo sobre preguntas que no intervinieron en el ajuste

El suelo de pertinencia se eligió optimizando el rechazo sobre las
preguntas ajenas de la tabla anterior, así que aquella cifra dice lo
bien que se ajustó el parámetro, no lo bien que el sistema rechaza.
**Esta es la que sostiene una conclusión**: ninguna de estas
preguntas ha intervenido en ningún ajuste.

**Rechazadas por el suelo: 5 de 10.**

De las 5 que pasan, **2 piden consejo** y **2 las para la comprobación de otro centro**. Queda **1 sin ninguna red debajo**, y esa es la cifra del hueco.

| Pregunta | Fragmentos recibidos | Petición de consejo | Otro centro |
| --- | ---: | :---: | :---: |
| V-001 | rechazada | no | no |
| V-002 | 20 | no | no |
| V-003 | 20 | sí | no |
| V-004 | 20 | sí | no |
| V-005 | 20 | no | sí |
| V-006 | 3 | no | sí |
| V-007 | rechazada | no | no |
| V-008 | rechazada | no | no |
| V-009 | rechazada | no | no |
| V-010 | rechazada | no | no |

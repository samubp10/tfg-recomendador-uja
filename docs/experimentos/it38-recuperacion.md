# Recuperación del sistema sobre el conjunto de IT-27 (IT-38)

> Lo escribe `scripts/experimento_recuperacion.py`. **No editar a mano.**

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

De las 4 que pasan, **2 son peticiones
de consejo**, y que pasen es deliberado: a esas el sistema les entrega la
banda completa a propósito. Quien pregunta qué carrera le pega no debe
recibir silencio, sino lo que sí se imparte aquí; a esas respuestas las
vigila la barrera de titulaciones, no el suelo. Contarlas como fallo del
filtro sería contar como error el comportamiento que se busca.

| Pregunta | Fragmentos recibidos | Petición de consejo |
| --- | ---: | :---: |
| P-051 | 3 | no |
| P-052 | 20 | no |
| P-053 | 20 | sí |
| P-054 | 20 | sí |
| P-055 | rechazada | no |
| P-056 | rechazada | no |
| P-057 | rechazada | no |
| P-058 | rechazada | no |
| P-059 | rechazada | no |
| P-060 | rechazada | no |

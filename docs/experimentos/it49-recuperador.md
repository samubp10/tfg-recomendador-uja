# Rejilla de parámetros del recuperador (IT-49)

> Lo escribe `scripts/barrido_recuperador.py`. **No editar a mano.**

- Configuraciones probadas: **240**
- Sin llamar a ningún modelo generativo: los tres parámetros solo deciden dónde se corta una lista ya ordenada.

## La configuración de hoy

- mín 3, máx 20, factor 1.2, suelo 0.142
- unidad **1.000** · rechazo **0.700** · 7.2 fragmentos por pregunta · 0 sin contexto

## Las veinte mejores

| mín | máx | factor | suelo | Unidad | Rechazo | Frag. | Sin ctx. |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 10 | 1.10 | 0.137 | 1.000 | 0.800 | 3.3 | 0 |
| 1 | 15 | 1.10 | 0.137 | 1.000 | 0.800 | 3.4 | 0 |
| 1 | 20 | 1.10 | 0.137 | 1.000 | 0.800 | 3.4 | 0 |
| 1 | 30 | 1.10 | 0.137 | 1.000 | 0.800 | 3.4 | 0 |
| 3 | 10 | 1.10 | 0.137 | 1.000 | 0.800 | 4.1 | 0 |
| 3 | 15 | 1.10 | 0.137 | 1.000 | 0.800 | 4.2 | 0 |
| 3 | 20 | 1.10 | 0.137 | 1.000 | 0.800 | 4.2 | 0 |
| 3 | 30 | 1.10 | 0.137 | 1.000 | 0.800 | 4.2 | 0 |
| 1 | 10 | 1.20 | 0.137 | 1.000 | 0.800 | 5.4 | 0 |
| 5 | 10 | 1.10 | 0.137 | 1.000 | 0.800 | 5.5 | 0 |
| 5 | 15 | 1.10 | 0.137 | 1.000 | 0.800 | 5.6 | 0 |
| 5 | 20 | 1.10 | 0.137 | 1.000 | 0.800 | 5.6 | 0 |
| 5 | 30 | 1.10 | 0.137 | 1.000 | 0.800 | 5.6 | 0 |
| 3 | 10 | 1.20 | 0.137 | 1.000 | 0.800 | 5.8 | 0 |
| 1 | 15 | 1.20 | 0.137 | 1.000 | 0.800 | 6.2 | 0 |
| 3 | 15 | 1.20 | 0.137 | 1.000 | 0.800 | 6.5 | 0 |
| 5 | 10 | 1.20 | 0.137 | 1.000 | 0.800 | 6.6 | 0 |
| 1 | 20 | 1.20 | 0.137 | 1.000 | 0.800 | 6.9 | 0 |
| 1 | 10 | 1.30 | 0.137 | 1.000 | 0.800 | 7.2 | 0 |
| 3 | 20 | 1.20 | 0.137 | 1.000 | 0.800 | 7.2 | 0 |

**Unidad** es la proporción de preguntas de dominio en las que se recupera al menos un fragmento de la unidad que las responde. **Rechazo** es la proporción de preguntas ajenas al dominio que se quedan sin contexto, que es el acierto en esa familia. **Frag.** es la media de fragmentos por pregunta, que se paga en tiempo y en ventana. **Sin ctx.** son las preguntas de dominio que se quedan sin nada, que es el peor fallo posible del recuperador.

## Las que no pierden ninguna pregunta de dominio

| mín | máx | factor | suelo | Unidad | Rechazo | Frag. |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 10 | 1.10 | 0.137 | 1.000 | 0.800 | 3.3 |
| 1 | 15 | 1.10 | 0.137 | 1.000 | 0.800 | 3.4 |
| 1 | 20 | 1.10 | 0.137 | 1.000 | 0.800 | 3.4 |
| 1 | 30 | 1.10 | 0.137 | 1.000 | 0.800 | 3.4 |
| 3 | 10 | 1.10 | 0.137 | 1.000 | 0.800 | 4.1 |
| 3 | 15 | 1.10 | 0.137 | 1.000 | 0.800 | 4.2 |
| 3 | 20 | 1.10 | 0.137 | 1.000 | 0.800 | 4.2 |
| 3 | 30 | 1.10 | 0.137 | 1.000 | 0.800 | 4.2 |
| 1 | 10 | 1.20 | 0.137 | 1.000 | 0.800 | 5.4 |
| 5 | 10 | 1.10 | 0.137 | 1.000 | 0.800 | 5.5 |

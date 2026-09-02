# Cribado de modelos generativos (IT-35)

> Lo escribe `scripts/experimentos/experimento_generacion.py`. **No editar a mano.**

- Preguntas del banco usadas: **250**
- Respuestas medidas: **500**
- Presupuesto de tiempo: **sin tope**. El equipo no está en condiciones controladas mientras se mide, así que el tiempo se informa pero **no descarta a ningún candidato**.
- tipo: procedencia
- fecha_extraccion: 2026-08-16
- origen: https://eps.ujaen.es/grados
- Servidor de inferencia: 0.32.14

## Resumen por modelo

| Modelo | n | Titul. inventadas | Precisión | Sin medir | Cobertura | Acierto escalar | Mediana (s) | p90 (s) | Máx (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `qwen3.5:9b` | 250 | 1 | 0.999 | 0/70 | 0.986 | 0.989 | 16.0 | 35.9 | 97.9 |
| `gemma3:12b` | 250 | 0 | 0.999 | 3/70 | 0.984 | 1.000 | 25.0 | 59.1 | 211.7 |

Precisión y cobertura se promedian sobre las preguntas de listado; el acierto escalar, sobre las de créditos y curso.

**Sin medir** son las respuestas de listado que no enumeran nada porque están redactadas en prosa: su precisión no es cero, no existe, y quedan fuera de la media. Contarlas como cero puntuaría el formato de la redacción y no la veracidad de lo dicho. Que una respuesta quede sin medir no la exime: si además no dijo lo que debía, la cobertura lo recoge, porque se mide sobre el texto entero.

## Titulaciones inventadas

Un nombre con forma de titulación que no está en el catálogo del índice. Es el fallo más grave que puede cometer el sistema.

- `qwen3.5:9b` — en 1 respuestas:
  - «Grado en Inteligencia Artificial y Cibersegurity»
- `gemma3:12b` — ninguna.

## Desglose por familia de pregunta

### `qwen3.5:9b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 43.7 |
| creditos | 99 | — | — | 0.980 | 14.7 |
| curso_de_asignatura | 81 | — | — | 1.000 | 14.4 |
| menciones | 20 | 1.000 | 1.000 | — | 26.6 |
| optativas | 7 | 1.000 | 1.000 | — | 45.5 |
| plan_por_curso | 42 | 0.998 | 0.976 | — | 32.4 |

### `gemma3:12b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 72.7 |
| creditos | 99 | — | — | 1.000 | 23.1 |
| curso_de_asignatura | 81 | — | — | 1.000 | 20.1 |
| menciones | 20 | 1.000 | 1.000 | — | 36.4 |
| optativas | 7 | 1.000 | 1.000 | — | 75.5 |
| plan_por_curso | 42 | 0.998 | 0.973 | — | 56.6 |

## Recuperación

Cuántas preguntas se quedaron sin ningún fragmento. Es fallo del recuperador, no del modelo, y por eso se cuenta aparte: sin contexto ningún generador puede acertar.

- `qwen3.5:9b`: 0 de 250
- `gemma3:12b`: 0 de 250


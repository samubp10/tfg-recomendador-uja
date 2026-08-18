# Cribado de modelos generativos (IT-35)

> Lo escribe `scripts/experimento_generacion.py`. **No editar a mano.**

- Preguntas del banco usadas: **80**
- Respuestas medidas: **239**
- Presupuesto de tiempo por respuesta: **60 s**
- tipo: procedencia
- fecha_extraccion: 2026-08-16
- origen: https://eps.ujaen.es/grados

## Resumen por modelo

| Modelo | Titul. inventadas | Precisión | Cobertura | Acierto escalar | Mediana (s) | p90 (s) | Máx (s) | Fuera de presupuesto |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ministral-8b:latest` | 0 | 0.944 | 0.992 | 0.913 | 8.1 | 24.4 | 39.9 | 0/80 |
| `gemma3:12b` | 0 | 0.967 | 1.000 | 0.957 | 18.0 | 54.6 | 107.3 | 7/80 |
| `qwen2.5:14b` | 0 | 0.965 | 0.969 | 0.935 | 26.7 | 80.3 | 16677.8 | 13/79 |

Precisión y cobertura se promedian sobre las preguntas de listado; el acierto escalar, sobre las de créditos y curso.

## Titulaciones inventadas

Un nombre con forma de titulación que no está en el catálogo del índice. Es el fallo más grave que puede cometer el sistema.

- `ministral-8b:latest` — ninguna.
- `gemma3:12b` — ninguna.
- `qwen2.5:14b` — ninguna.

## Desglose por familia de pregunta

### `ministral-8b:latest`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 23.9 |
| creditos | 23 | — | — | 1.000 | 5.7 |
| curso_de_asignatura | 23 | — | — | 0.826 | 5.9 |
| menciones | 13 | 0.862 | 1.000 | — | 20.9 |
| optativas | 7 | 0.992 | 1.000 | — | 21.6 |
| plan_por_curso | 13 | 0.996 | 0.978 | — | 17.9 |

### `gemma3:12b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 67.8 |
| creditos | 23 | — | — | 1.000 | 12.4 |
| curso_de_asignatura | 23 | — | — | 0.913 | 11.7 |
| menciones | 13 | 0.923 | 1.000 | — | 21.0 |
| optativas | 7 | 0.992 | 1.000 | — | 66.8 |
| plan_por_curso | 13 | 0.996 | 1.000 | — | 36.9 |

### `qwen2.5:14b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| creditos | 23 | — | — | 1.000 | 16.3 |
| curso_de_asignatura | 23 | — | — | 0.870 | 14.7 |
| menciones | 13 | 0.974 | 0.974 | — | 37.2 |
| optativas | 7 | 0.982 | 0.990 | — | 80.3 |
| plan_por_curso | 13 | 0.948 | 0.952 | — | 54.5 |

## Recuperación

Cuántas preguntas se quedaron sin ningún fragmento. Es fallo del recuperador, no del modelo, y por eso se cuenta aparte: sin contexto ningún generador puede acertar.

- `ministral-8b:latest`: 0 de 80
- `gemma3:12b`: 0 de 80
- `qwen2.5:14b`: 0 de 79


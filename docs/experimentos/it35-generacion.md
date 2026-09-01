# Cribado de modelos generativos (IT-35)

> Lo escribe `scripts/experimentos/experimento_generacion.py`. **No editar a mano.**

- Preguntas del banco usadas: **80**
- Respuestas medidas: **240**
- Presupuesto de tiempo: **sin tope**. El equipo no está en condiciones controladas mientras se mide, así que el tiempo se informa pero **no descarta a ningún candidato**.
- tipo: procedencia
- fecha_extraccion: 2026-08-16
- origen: https://eps.ujaen.es/grados
- Servidor de inferencia: 0.32.14

## Resumen por modelo

| Modelo | n | Titul. inventadas | Precisión | Sin medir | Cobertura | Acierto escalar | Mediana (s) | p90 (s) | Máx (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ministral-8b:latest` | 80 | 0 | 0.997 | 0/34 | 0.968 | 1.000 | 17.9 | 56.7 | 117.6 |
| `qwen3.5:9b` | 80 | 0 | 1.000 | 0/34 | 0.971 | 1.000 | 17.0 | 45.7 | 75.9 |
| `gemma3:12b` | 80 | 0 | 1.000 | 3/34 | 0.971 | 1.000 | 25.7 | 72.1 | 109.3 |

Precisión y cobertura se promedian sobre las preguntas de listado; el acierto escalar, sobre las de créditos y curso.

**Sin medir** son las respuestas de listado que no enumeran nada porque están redactadas en prosa: su precisión no es cero, no existe, y quedan fuera de la media. Contarlas como cero puntuaría el formato de la redacción y no la veracidad de lo dicho. Que una respuesta quede sin medir no la exime: si además no dijo lo que debía, la cobertura lo recoge, porque se mide sobre el texto entero.

## Titulaciones inventadas

Un nombre con forma de titulación que no está en el catálogo del índice. Es el fallo más grave que puede cometer el sistema.

- `ministral-8b:latest` — ninguna.
- `qwen3.5:9b` — ninguna.
- `gemma3:12b` — ninguna.

## Desglose por familia de pregunta

### `ministral-8b:latest`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 39.4 |
| creditos | 23 | — | — | 1.000 | 13.8 |
| curso_de_asignatura | 23 | — | — | 1.000 | 11.1 |
| menciones | 13 | 1.000 | 1.000 | — | 23.2 |
| optativas | 7 | 1.000 | 1.000 | — | 38.6 |
| plan_por_curso | 13 | 0.992 | 0.915 | — | 51.0 |

### `qwen3.5:9b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 41.6 |
| creditos | 23 | — | — | 1.000 | 14.7 |
| curso_de_asignatura | 23 | — | — | 1.000 | 14.8 |
| menciones | 13 | 1.000 | 1.000 | — | 22.5 |
| optativas | 7 | 1.000 | 1.000 | — | 42.1 |
| plan_por_curso | 13 | 1.000 | 0.923 | — | 31.9 |

### `gemma3:12b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 67.4 |
| creditos | 23 | — | — | 1.000 | 22.4 |
| curso_de_asignatura | 23 | — | — | 1.000 | 19.1 |
| menciones | 13 | 1.000 | 1.000 | — | 34.2 |
| optativas | 7 | 1.000 | 1.000 | — | 73.9 |
| plan_por_curso | 13 | 1.000 | 0.923 | — | 56.7 |

## Recuperación

Cuántas preguntas se quedaron sin ningún fragmento. Es fallo del recuperador, no del modelo, y por eso se cuenta aparte: sin contexto ningún generador puede acertar.

- `ministral-8b:latest`: 0 de 80
- `qwen3.5:9b`: 0 de 80
- `gemma3:12b`: 0 de 80


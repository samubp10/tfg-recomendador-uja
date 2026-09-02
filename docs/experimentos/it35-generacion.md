# Cribado de modelos generativos (IT-35)

> Lo escribe `scripts/experimentos/experimento_generacion.py`. **No editar a mano.**

- Preguntas del banco usadas: **80**
- Respuestas medidas: **320**
- Presupuesto de tiempo: **sin tope**. El equipo no está en condiciones controladas mientras se mide, así que el tiempo se informa pero **no descarta a ningún candidato**.
- tipo: procedencia
- fecha_extraccion: 2026-08-16
- origen: https://eps.ujaen.es/grados
- Servidor de inferencia: 0.32.14

## Resumen por modelo

| Modelo | n | Titul. inventadas | Precisión | Sin medir | Cobertura | Acierto escalar | Mediana (s) | p90 (s) | Máx (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ministral-8b:latest` | 80 | 0 | 1.000 | 0/34 | 0.971 | 1.000 | 24.4 | 87.2 | 176.7 |
| `qwen3.5:9b` | 80 | 0 | 1.000 | 0/34 | 0.971 | 1.000 | 17.4 | 47.7 | 78.7 |
| `gemma3:12b` | 80 | 0 | 1.000 | 3/34 | 0.971 | 1.000 | 26.0 | 72.1 | 110.6 |
| `salamandra-7b:latest` | 80 | 0 | 0.995 | 13/34 | 0.770 | 0.978 | 7.1 | 21.2 | 145.5 |

Precisión y cobertura se promedian sobre las preguntas de listado; el acierto escalar, sobre las de créditos y curso.

**Sin medir** son las respuestas de listado que no enumeran nada porque están redactadas en prosa: su precisión no es cero, no existe, y quedan fuera de la media. Contarlas como cero puntuaría el formato de la redacción y no la veracidad de lo dicho. Que una respuesta quede sin medir no la exime: si además no dijo lo que debía, la cobertura lo recoge, porque se mide sobre el texto entero.

## Titulaciones inventadas

Un nombre con forma de titulación que no está en el catálogo del índice. Es el fallo más grave que puede cometer el sistema.

- `ministral-8b:latest` — ninguna.
- `qwen3.5:9b` — ninguna.
- `gemma3:12b` — ninguna.
- `salamandra-7b:latest` — ninguna.

## Desglose por familia de pregunta

### `ministral-8b:latest`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 32.8 |
| creditos | 23 | — | — | 1.000 | 18.2 |
| curso_de_asignatura | 23 | — | — | 1.000 | 12.3 |
| menciones | 13 | 1.000 | 1.000 | — | 48.3 |
| optativas | 7 | 1.000 | 1.000 | — | 76.3 |
| plan_por_curso | 13 | 1.000 | 0.923 | — | 47.8 |

### `qwen3.5:9b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 42.5 |
| creditos | 23 | — | — | 1.000 | 15.1 |
| curso_de_asignatura | 23 | — | — | 1.000 | 15.2 |
| menciones | 13 | 1.000 | 1.000 | — | 22.6 |
| optativas | 7 | 1.000 | 1.000 | — | 43.1 |
| plan_por_curso | 13 | 1.000 | 0.923 | — | 32.8 |

### `gemma3:12b`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 70.3 |
| creditos | 23 | — | — | 1.000 | 24.0 |
| curso_de_asignatura | 23 | — | — | 1.000 | 19.1 |
| menciones | 13 | 1.000 | 1.000 | — | 34.3 |
| optativas | 7 | 1.000 | 1.000 | — | 75.5 |
| plan_por_curso | 13 | 1.000 | 0.923 | — | 58.2 |

### `salamandra-7b:latest`

| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| catalogo | 1 | 1.000 | 1.000 | — | 21.2 |
| creditos | 23 | — | — | 1.000 | 7.3 |
| curso_de_asignatura | 23 | — | — | 0.957 | 3.5 |
| menciones | 13 | 1.000 | 0.963 | — | 9.7 |
| optativas | 7 | 1.000 | 0.295 | — | 7.0 |
| plan_por_curso | 13 | 0.991 | 0.815 | — | 18.7 |

## Recuperación

Cuántas preguntas se quedaron sin ningún fragmento. Es fallo del recuperador, no del modelo, y por eso se cuenta aparte: sin contexto ningún generador puede acertar.

- `ministral-8b:latest`: 0 de 80
- `qwen3.5:9b`: 0 de 80
- `gemma3:12b`: 0 de 80
- `salamandra-7b:latest`: 0 de 80


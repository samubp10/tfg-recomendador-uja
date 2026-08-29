# Evaluación del sistema completo (IT-37)

> Lo escribe `scripts/experimento_sistema.py`. **No editar a mano.**

- Entradas del banco: **57**
- Servidor de inferencia: 0.32.14

## Aciertos por modelo

| Modelo | Aciertos | Tasa | Mediana (s) |
| --- | ---: | ---: | ---: |
| `gemma3:12b` | 56 de 57 | 0.982 | 42.3 |

## Aciertos por familia

| Familia | n | `gemma3:12b` |
| --- | ---: | ---: |
| ambigua | 3 | 3/3 |
| catalogo | 1 | 1/1 |
| consejo | 6 | 6/6 |
| conversacion | 8 | 8/8 |
| cortesia | 4 | 4/4 |
| creditos | 4 | 4/4 |
| curso_de_asignatura | 4 | 3/4 |
| fuera_de_dominio | 15 | 15/15 |
| menciones | 4 | 4/4 |
| optativas | 4 | 4/4 |
| plan_por_curso | 4 | 4/4 |

## Lo que falla

- `gemma3:12b` · G-ASI-0078 (curso_de_asignatura)

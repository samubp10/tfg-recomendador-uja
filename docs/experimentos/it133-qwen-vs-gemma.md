# Comparación pareada: `qwen3.5:9b` frente a `gemma3:12b`

> Lo escribe `scripts/experimentos/comparar_dos_modelos.py`. **No editar a mano.**

Los dos modelos respondieron **las mismas preguntas**, así que se comparan por pares y no como dos medias sueltas. Cada tasa lleva su intervalo de Wilson al 95 %; la diferencia, la prueba exacta de McNemar sobre los pares discordantes, que son los únicos que distinguen a alguien.

- Preguntas del banco: **250**
- Respuestas medidas: **500**
- Umbral de decisión, fijado de antemano: **p < 0.05**

## Resultados

| Métrica | n | `qwen3.5:9b` | `gemma3:12b` | Solo A | Solo B | p | ¿Se distinguen? |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| precision | 67 | 0.985 [0.920–0.997] | 0.985 [0.920–0.997] | 0 | 0 | 1.000 | no |
| cobertura | 70 | 0.986 [0.923–0.997] | 0.971 [0.902–0.992] | 1 | 0 | 1.000 | no |
| acierto | 180 | 0.989 [0.960–0.997] | 1.000 [0.979–1.000] | 0 | 2 | 0.500 | no |

**Solo A** son las preguntas que acierta el primero y falla el segundo, y **Solo B** al revés. Si las dos columnas son cero, los modelos respondieron igual de bien en todas y **no hay diferencia que medir**, por muchas preguntas que se añadan.

## Tiempo

| Modelo | Mediana de generación (s) |
| --- | ---: |
| `qwen3.5:9b` | 16.0 |
| `gemma3:12b` | 25.0 |

El tiempo se informa y **no descarta**: la máquina no está en condiciones controladas mientras se mide.

## Cómo se lee esto

Un `p` alto **no demuestra que los dos modelos sean iguales**. Demuestra que este banco no los distingue, que es una afirmación más débil y es la única que los datos sostienen. Lo que acota cuánta diferencia podría seguir habiendo sin verse es la anchura de los intervalos, no el valor de `p`.

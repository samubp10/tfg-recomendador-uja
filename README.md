# Recomendador de Grados de la EPSJ

[![Español](https://img.shields.io/badge/lang-Espa%C3%B1ol-blue.svg)](README.md)
[![English](https://img.shields.io/badge/lang-English-red.svg)](README.en.md)
[![Tests](https://github.com/samubp10/tfg-recomendador-uja/actions/workflows/tests.yml/badge.svg)](https://github.com/samubp10/tfg-recomendador-uja/actions/workflows/tests.yml)
![Python 3.13](https://img.shields.io/badge/python-3.13-blue)
![Licencia GPL-3.0](https://img.shields.io/badge/licencia-GPL--3.0-green)

Chatbot de recomendación e información sobre las titulaciones de grado de la
Escuela Politécnica Superior de Jaén (EPSJ). Está pensado para ayudar a
estudiantes preuniversitarios a decidir qué carrera estudiar: responde
preguntas sobre asignaturas, planes de estudio y salidas profesionales a
partir de la información publicada por la Universidad de Jaén.

Por dentro combina recuperación aumentada por generación (RAG) sobre un
modelo de lenguaje de código abierto ejecutado en local, de manera que las
respuestas se apoyan en datos reales de la universidad y no en el
conocimiento genérico del modelo.

Este repositorio corresponde a un Trabajo Fin de Grado del Grado en
Ingeniería Informática de la Universidad de Jaén, curso 2025/2026.

**Autor:** Samuel Blanco Palmero · **Tutor:** Juan Carlos Cuevas Martinez

## Estado del proyecto

| Fase | Contenido | Estado |
| ---- | --------- | ------ |
| 0 | Extracción web, limpieza, validación y fragmentación (*chunking*) | ✅ Completa |
| 1 | Indexación vectorial, conjunto de evaluación y comparativa de *embeddings* | 🚧 En curso |
| 2 | *Pipeline* RAG completo con LLM local y evaluación | Pendiente |
| 3 | Aplicación web de chat | Pendiente |
| 4 | Validación con usuarios | Pendiente |

## Arquitectura

```text
Web EPSJ ──spider──▶ grados.json ──chunker──▶ chunks.json ──indexer──▶ índice vectorial ──▶ [RAG + LLM] ──▶ [web de chat]
```

Cada etapa está desacoplada de la siguiente y produce un artefacto
regenerable: re-fragmentar o re-indexar es barato y se hace a menudo al
experimentar; re-rastrear la web es caro y descortés con el servidor de la
universidad, por lo que solo se hace cuando cambia la fuente.

## Requisitos

- Python 3.13 (mínimo 3.10).
- Para ejecutar la indexación real: el extra `[index]` (véase abajo), que
  instala PyTorch a través de `sentence-transformers`.

## Instalación

### Windows (CMD o PowerShell)

```console
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

### Linux / macOS

```console
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

> En Git Bash sobre Windows: `source .venv/Scripts/activate`.

Para la indexación vectorial (descarga el modelo de *embeddings*, cientos de MB):

```console
pip install -e ".[dev,index]"
```

## Uso

Los datos generados viven en `data/` y **no se versionan**: se regeneran con
el propio *pipeline* (esa regeneración es la garantía de reproducibilidad).

```console
# 1. Extraer el dataset — hace peticiones REALES a la web de la UJA.
#    Usar con moderación (respeta robots.txt y aplica retardo entre peticiones).
scrapy runspider src/tfg_uja/grados_spider.py -O data/grados.json

# 2. Fragmentar (offline, barato)
py -m tfg_uja.chunker data/grados.json data/chunks.json

# 3. Indexar en la base de datos vectorial (requiere el extra [index])
#    El modelo por defecto es el del ADR-0003; se puede pasar otro como
#    tercer argumento para repetir el experimento sin tocar el código.
py -m tfg_uja.indexer data/chunks.json data/indice_lance
```

### Verificadores del dataset (solo en local)

No corren en CI porque `data/` no existe en un *checkout* limpio; se ejecutan
antes de cada *push*:

```console
py scripts/check_dataset.py    # integridad de grados/asignaturas/guías/salidas
py scripts/check_chunks.py     # tamaños y deduplicación de los fragmentos
py scripts/check_evalset.py    # el conjunto de evaluación resuelve contra el dataset
py scripts/check_guias_pdf.py  # la extracción de los PDF es fiel a los originales
```

`check_guias_pdf.py` compara lo extraído con los PDF que el rastreo guarda en
`data/guias_pdf/`, y falla si aparece un rótulo de sección que el código no
conoce: sería la señal de que la plantilla de la fuente ha cambiado y de que una
sección puede estar quedándose corta o tragándose la siguiente. Enumera además
qué se descarta y cuánto, por sección, para que el filtrado se pueda revisar en
lugar de tener que creérselo.

### Experimentos

```console
# Compara modelos de embeddings (Recall@3, Recall@5, MRR) sobre el conjunto de
# evaluación. Requiere el extra [index] y red la primera vez. Solo en local.
py scripts/experimento_embeddings.py
```

Los resultados reales de cada ejecución quedan en `docs/experimentos/`.

## Calidad

```console
pytest                                          # 184 pruebas, con fixtures HTML/PDF/JSON reales
mypy src/tfg_uja/ --ignore-missing-imports      # tipado estático limpio
black src/ tests/ scripts/                      # formato
flake8 src/ tests/ scripts/                     # estilo (configurado en .flake8)
```

Principios de las pruebas: fixtures **reales** descargadas de la EPSJ (nunca
peticiones de red en los tests, nunca datos inventados), y todo defecto
encontrado entra como test de regresión con su caso real.

## Estructura del repositorio

```text
src/tfg_uja/        # código fuente (spider, guías en PDF, limpieza, validación,
                    #   chunker, indexer y métricas de recuperación)
tests/              # pruebas con fixtures reales (HTML y PDF de la EPSJ, chunks del dataset)
scripts/            # verificadores del dataset y experimentos
eval/               # conjunto de evaluación del retrieval (manual, versionado)
docs/adr/           # registro de decisiones de arquitectura (ADR)
docs/dqa/           # registro de anomalías de calidad de datos (DQA)
docs/experimentos/  # resultados reales de los experimentos
memoria/            # memoria del TFG en LaTeX (plantilla EPSJ)
data/               # artefactos generados (NO versionados)
```

## Metodología

- **Kanban** en GitHub Projects: cada tarea es una *issue* `IT-XX` con fase,
  prioridad MoSCoW y *milestone*.
- **Conventional Commits** (`tipo(IT-XX): descripción`), con cuerpo
  obligatorio que explica el *porqué* de cada decisión.
- Ramas efímeras desde `main` (código) o `doc` (memoria); fusión siempre con
  *merge commit*, nunca *squash*.
- Decisiones de diseño registradas como **ADR** en `docs/adr/`.
- CI en GitHub Actions: `pytest` + `mypy` en cada *push* y *pull request*.

## Alcance

La primera versión cubre las titulaciones de grado de la EPSJ. El sistema se
ha diseñado para poder ampliarse al resto de centros de la Universidad de
Jaén añadiendo nuevas fuentes al proceso de extracción, sin rehacer el núcleo
de recuperación y generación. El profesorado se excluye deliberadamente de
los datos extraídos (privacidad).

## Licencia

[GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html)

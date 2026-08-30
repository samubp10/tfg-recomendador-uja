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
conocimiento genérico del modelo. **No se consulta ningún servicio externo:**
el modelo generativo, el de incrustaciones y el índice vectorial se ejecutan
en la misma máquina.

Este repositorio corresponde a un Trabajo Fin de Grado del Grado en
Ingeniería Informática de la Universidad de Jaén, curso 2025/2026.

**Autor:** Samuel Blanco Palmero · **Tutor:** Juan Carlos Cuevas Martinez

## Estado del proyecto

| Fase | Contenido | Estado |
| ---- | --------- | ------ |
| 0 | Extracción web, limpieza, validación y fragmentación (*chunking*) | ✅ Completa |
| 1 | Estrategia de troceado y comparativa de *embeddings* | ✅ Completa |
| 2 | Base de datos vectorial, LLM local y *pipeline* RAG | ✅ Completa |
| 3 | Aplicación web de chat | ✅ Completa |
| 4 | Validación y estudio de ablación | 🚧 En curso |
| 5 | Cierre y defensa | Pendiente |

## Arquitectura

```text
Web EPSJ ──spider──▶ grados.json ──chunker──▶ chunks.json ──indexer──▶ índice LanceDB
                                                                            │
                                    navegador ◀── servidor ◀── RAG ◀────────┘
                                                     │
                                                     └──▶ Ollama (gemma3:12b)
```

Cada etapa está desacoplada de la siguiente y produce un artefacto
regenerable: re-fragmentar o re-indexar es barato y se hace a menudo al
experimentar; re-rastrear la web es caro y descortés con el servidor de la
universidad, por lo que solo se hace cuando cambia la fuente.

La aplicación web es **un solo proceso de Python** que sirve la interfaz y
atiende las consultas, e importa el flujo de recuperación y generación como
biblioteca. Lo único que corre aparte es el servidor de inferencia.

## Requisitos

### Software

| Qué | Versión probada | Para qué |
| --- | --- | --- |
| **Python** | 3.13.5 (mínimo 3.10) | todo el código |
| **[Ollama](https://ollama.com/)** | 0.32.14 | servidor de inferencia local, en `http://127.0.0.1:11434` |
| Docker | — | **opcional**, solo para el experimento que compara bases vectoriales (Qdrant) |

### Modelos

Se descargan una vez y se quedan en local:

| Modelo | Tamaño en disco | Cómo llega |
| --- | ---: | --- |
| `gemma3:12b` — generación (ADR-0005) | 8,1 GB | `ollama pull gemma3:12b` |
| `intfloat/multilingual-e5-small` — incrustaciones (ADR-0003) | ~0,5 GB | lo descarga solo `sentence-transformers` la primera vez |

> El modelo de incrustaciones es el pequeño y no el grande **a propósito**: los
> dos tienen que convivir en memoria con el generativo, y la primera ejecución
> de la comparativa murió por falta de memoria cargando el grande (ADR-0003).

## Instalación

### 1. Entorno de Python

#### Windows (CMD o PowerShell)

```console
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

#### Linux / macOS

```console
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

> En Git Bash sobre Windows: `source .venv/Scripts/activate`.

Para ejecutar el sistema de verdad (indexación y consultas) hace falta además
el extra `[index]`, que arrastra PyTorch a través de `sentence-transformers`
(cientos de MB). Los tests **no** lo necesitan: inyectan un incrustador falso.

```console
pip install -e ".[dev,index]"
```

### 2. Servidor de inferencia

```console
ollama pull gemma3:12b
ollama serve
```

`ollama serve` deja el servidor escuchando en `http://127.0.0.1:11434`, que es
donde el sistema lo busca. En Windows y macOS la aplicación de escritorio de
Ollama ya lo levanta al arrancar.

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

# 4. Levantar la aplicación web
py -m tfg_uja.servidor
```

El paso 4 abre el asistente en **<http://127.0.0.1:8000>**. Necesita que
existan `data/indice_lance` y `data/grados.json`, y que Ollama esté
respondiendo; si falta el índice, el propio programa lo dice y no arranca.

También hay un cliente de consola, útil para probar el flujo sin navegador:

```console
py scripts/chat_rag.py
```

> ⚠️ **El servidor no es apto para producción, y así está declarado.** Está
> construido sobre `http.server` de la biblioteca estándar: atiende en serie, no
> limita el tamaño de la petición y no ofrece HTTPS. Escucha solo en
> `127.0.0.1`. El despliegue queda fuera del alcance de este trabajo.

### Verificadores del dataset (solo en local)

No corren en CI porque `data/` no existe en un *checkout* limpio; se ejecutan
antes de cada *push*:

```console
py scripts/verificadores/check_dataset.py    # integridad de grados/asignaturas/guías/salidas
py scripts/verificadores/check_chunks.py     # tamaños y deduplicación de los fragmentos
py scripts/verificadores/check_evalset.py    # el conjunto de evaluación resuelve contra el dataset
py scripts/verificadores/check_guias_pdf.py  # la extracción de los PDF es fiel a los originales
```

`check_guias_pdf.py` compara lo extraído con los PDF que el rastreo guarda en
`data/guias_pdf/`, y falla si aparece un rótulo de sección que el código no
conoce: sería la señal de que la plantilla de la fuente ha cambiado y de que una
sección puede estar quedándose corta o tragándose la siguiente. Enumera además
qué se descarta y cuánto, por sección, para que el filtrado se pueda revisar en
lugar de tener que creérselo.

### Experimentos

Están en `scripts/experimentos/` y cada uno escribe sus resultados en el ADR o
en el fichero de `docs/experimentos/` que le corresponde. Varios tardan horas y
los de las fases 2 y 3 exigen Ollama levantado.

```console
py scripts/experimentos/experimento_embeddings.py   # ADR-0003: compara modelos de incrustaciones
py scripts/experimentos/experimento_vectordb.py     # ADR-0004: compara bases vectoriales
py scripts/experimentos/experimento_generacion.py   # ADR-0005: compara modelos generativos
py scripts/experimentos/experimento_recuperacion.py # Recall@K, MRR y rechazo de preguntas ajenas
py scripts/experimentos/experimento_sistema.py      # el recorrido completo, de punta a punta
```

⚠️ **No lances nada más contra Ollama mientras un experimento está midiendo.**
Los tiempos dejan de significar nada, y con el modelo cargado la redacción
cambia entre llamadas.

## Calidad

```console
pytest                                          # 861 pruebas, con fixtures HTML/PDF/JSON reales
mypy src/tfg_uja/ --ignore-missing-imports      # tipado estático limpio
black src/ tests/ scripts/                      # formato
flake8 src/ tests/ scripts/                     # estilo (configurado en .flake8)
```

Tres pruebas se saltan solas si Ollama no responde, y lo anuncian en vez de
pasar en verde en silencio. La prueba lenta de integración recorre el conjunto
de evaluación entero llamando al modelo y queda fuera de la tanda por defecto:

```console
py -m pytest tests/test_integracion_rag.py -m lento -q -ra
```

Principios de las pruebas: fixtures **reales** descargadas de la EPSJ (nunca
peticiones de red en los tests, nunca datos inventados), y todo defecto
encontrado entra como test de regresión con su caso real.

## Estructura del repositorio

```text
src/tfg_uja/        # código fuente
  grados_spider.py  #   rastreo de la web de la EPSJ
  guia_pdf.py       #   extracción de las guías servidas en PDF
  text_cleaner.py · validators.py · invariantes.py
  chunker.py        #   fragmentación y deduplicación
  incrustaciones.py · indexer.py · recuperador.py · evaluacion.py
  ambito.py         #   de qué titulación se está hablando
  conversacion.py   #   estado del diálogo y ventana de contexto
  generador.py      #   prompt y llamada al modelo
  verificacion.py   #   comprobaciones deterministas de la respuesta
  servidor.py       #   aplicación web (interfaz + /api/chat)
  sugerencias.py · registro_chat.py
web/                # interfaz: HTML, CSS y JavaScript, sin dependencias
tests/              # pruebas con fixtures reales (HTML y PDF de la EPSJ)
scripts/            # verificadores, experimentos y bancos de preguntas
eval/               # conjunto de evaluación del retrieval (manual, versionado)
docs/adr/           # registro de decisiones de arquitectura (ADR)
docs/dqa/           # registro de anomalías de calidad de datos (DQA)
docs/experimentos/  # resultados reales, escritos por los propios guiones
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
- Decisiones de diseño registradas como **ADR** en `docs/adr/`; anomalías de la
  fuente de datos como **DQA** en `docs/dqa/`.
- CI en GitHub Actions: `pytest` + `mypy` en cada *push* y *pull request*.

## Alcance

La primera versión cubre las titulaciones de grado de la EPSJ. El sistema se
ha diseñado para poder ampliarse al resto de centros de la Universidad de
Jaén añadiendo nuevas fuentes al proceso de extracción, sin rehacer el núcleo
de recuperación y generación. **Que el diseño admita crecer está justificado;
que el sistema escale no está medido.** El profesorado se excluye
deliberadamente de los datos extraídos (privacidad).

## Licencia

[GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html)

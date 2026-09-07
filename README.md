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
| 4 | Evaluación del sistema y estudio de ablación | ✅ Completa¹ |
| 5 | Cierre y defensa | 🚧 En curso |

> ¹ La **validación con usuarios reales quedó fuera del alcance** del trabajo por
> falta de margen para diseñarla con las garantías que exigiría (muestra,
> consentimiento y protocolo). No se sustituye por ninguna aproximación: se
> declara como limitación en la memoria y se enumera allí qué preguntas quedan
> sin responder por ello. Lo que sí se mide es todo lo demás, con los bancos y
> los verificadores que se describen más abajo.

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

## Conjunto de datos

Las cifras son una **fotografía, no una constante**: la EPSJ publica guías
nuevas a lo largo del curso, así que cambian en cada rastreo. Tanto
`grados.json` como `chunks.json` llevan dentro su propia fecha de extracción y
su curso académico.

| Métrica | Valor |
| --- | ---: |
| Rastreado el | 2026-08-16 (curso 2026-27) |
| Troceado el | 2026-09-01 |
| Titulaciones (5 de ellas dobles grados) | 12 |
| Titulaciones con asignaturas propias | 11 |
| Asignaturas | 528 |
| Guías docentes (todas servidas en PDF) | 288 |
| Cobertura de guías | 83,7 % |
| Asignaturas sin contenido de guía | 86 |
| Bloques de salidas profesionales | 8 |
| **Fragmentos tras deduplicar** | **1 922** |
| Unidades a las que pertenecen (63 compartidas entre titulaciones) | 471 |

Reparto de fragmentos por origen: 1 719 de guía · 86 de asignatura sin guía ·
56 de plan de estudios · 24 de mención · 22 de salidas · 12 de ficha de
titulación · 3 de catálogo.

La titulación número doce es un doble grado internacional con una universidad
alemana que no publica plan de estudios propio, de modo que no aporta
fragmentos.

Dos rastreos con un día de diferencia (2026-07-29 y 2026-07-30) produjeron un
corpus **idéntico byte a byte**, fragmento por fragmento.

No te fíes de esta tabla: comprueba cualquiera de estas cifras con los
verificadores que aparecen más abajo, porque solo está tan fresca como la
última vez que alguien la editó.

## Resultados

Las cifras las escriben los propios guiones en `docs/experimentos/` y en el
bloque automático de cada ADR. **Valen para el corpus con el que se midieron**
---1 922 fragmentos, curso 2026-27---, no son constantes del proyecto.

**Recuperación**, sobre las 56 preguntas de dominio del conjunto de evaluación
([`it38-recuperacion.md`](docs/experimentos/it38-recuperacion.md)):

| K | Recall@K | Techo | Recall de unidad@K |
| ---: | ---: | ---: | ---: |
| 3 | 0,644 | 0,756 | 0,906 |
| 5 | 0,777 | 0,905 | 0,973 |
| 10 | 0,865 | 0,964 | 0,991 |

**MRR: 0,914.** El techo es el máximo que Recall@K puede alcanzar con esa K,
porque hay preguntas con más unidades relevantes que K: cada cifra se lee
contra su techo y no contra 1.

**Sistema completo**, sobre el banco de 57 entradas
([`it38-sistema.md`](docs/experimentos/it38-sistema.md)): **57 de 57**, y las
15 preguntas ajenas al centro se rechazan todas.

Dos lecturas que esas cifras **no** admiten:

- **57 de 57 no es una tasa de acierto de 1.** Con 57 observaciones la cota
  inferior al 95 % es **0,949**; la de las quince ajenas, **0,819**. Y repetir
  la tanda no estrecha esas cotas, porque salen del tamaño del banco y no del
  número de ejecuciones: dos tiradas de 57 preguntas son 57 observaciones, no
  114. Lo único que las estrecha es añadir preguntas distintas.
- **El 15 de 15 no es todo mérito del sistema.** Once rechazos los produce una
  barrera propia (8 el suelo de pertinencia, 3 la comprobación de centro ajeno)
  y uno la retirada de la respuesta; los **tres restantes los rechaza el modelo
  por su cuenta**, y eso no es un control: cambiar de modelo bastaría para
  perderlo.

## Requisitos

### Software

| Qué | Versión probada | Para qué |
| --- | --- | --- |
| **Python** | 3.13 | todo el código |
| **[Ollama](https://ollama.com/)** | 0.32.14 | servidor de inferencia local, en `http://127.0.0.1:11434` |
| Docker | — | **opcional**, solo para el experimento que compara bases vectoriales (Qdrant) |

El proyecto exige **Python 3.13.** y no admite otras versiones: así lo declaran
`pyproject.toml`, `mypy`, `black`, el fichero `.python-version` y el CI, y hay
una prueba que falla si alguno de ellos se desalinea. Se ha desarrollado sobre
la 3.13.5.

### Modelos

Se descargan una vez y se quedan en local:

| Modelo | Tamaño en disco | Cómo llega |
| --- | ---: | --- |
| `gemma3:12b` — generación (ADR-0005) | 8,1 GB | `ollama pull gemma3:12b` |
| `intfloat/multilingual-e5-small` — incrustaciones (ADR-0003) | ~0,5 GB | autorizar la primera descarga con `TFG_DESCARGAR_MODELO=1` |

> El modelo de incrustaciones es el pequeño y no el grande **a propósito**: los
> dos tienen que convivir en memoria con el generativo, y la primera ejecución
> de la comparativa murió por falta de memoria cargando el grande (ADR-0003).

## Instalación

La [guía de instalación completa](docs/instalacion.md) recoge la ruta probada
en contenedores nuevos, incluidos los modelos, LanceDB y la aplicación web.

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

Para **repetir un experimento con el mismo entorno con el que se midió**, se
añade `-c constraints.txt`, que fija las versiones exactas de esa fotografía.
Sin él se resuelven las de hoy, que es lo que se quiere para trabajar y lo que
no se quiere para comparar contra una cifra ya publicada.

### 2. Servidor de inferencia

```console
ollama pull gemma3:12b
ollama serve
```

`ollama serve` deja el servidor escuchando en `http://127.0.0.1:11434`, que es
donde el sistema lo busca. En Windows y macOS la aplicación de escritorio de
Ollama ya lo levanta al arrancar.

## Uso

Antes de la primera indexación hay que autorizar la descarga de las
incrustaciones. En PowerShell: `$env:TFG_DESCARGAR_MODELO='1'`; en CMD:
`set TFG_DESCARGAR_MODELO=1`; en Linux o Git Bash:
`export TFG_DESCARGAR_MODELO=1`. Tras descargar el modelo, quitar esa variable
(`Remove-Item Env:TFG_DESCARGAR_MODELO`, `set TFG_DESCARGAR_MODELO=` o
`unset TFG_DESCARGAR_MODELO`, respectivamente). Las siguientes ejecuciones
cargan la caché local. El procedimiento completo comprueba también esa carga.

Los datos generados viven en `data/` y **no se versionan**: se regeneran con
el propio *pipeline* (esa regeneración es la garantía de reproducibilidad).

```console
# 1. Extraer el dataset — hace peticiones REALES a la web de la UJA.
#    Usar con moderación (respeta robots.txt y aplica retardo entre peticiones).
scrapy runspider src/tfg_uja/extraccion/grados_spider.py -O data/grados.json

# 2. Fragmentar (offline, barato)
py -m tfg_uja.indexacion.chunker data/grados.json data/chunks.json

# 3. Indexar en la base de datos vectorial (requiere el extra [index])
#    El modelo por defecto es el del ADR-0003; se puede pasar otro como
#    tercer argumento para repetir el experimento sin tocar el código.
py -m tfg_uja.indexacion.indexer data/chunks.json data/indice_lance

# 4. Levantar la aplicación web
py -m tfg_uja.aplicacion.servidor
```

El paso 4 abre el asistente en **<http://127.0.0.1:8000>**. Necesita que
existan `data/indice_lance` y `data/grados.json`, y que Ollama esté
respondiendo; si falta el índice, el propio programa lo dice y no arranca.

También hay un cliente de consola, útil para probar el flujo sin navegador:

```console
py scripts/chat_rag.py
```

> ⚠️ **El servidor no es apto para producción, y así está declarado.** Está
> construido sobre `http.server` de la biblioteca estándar: atiende una petición
> cada vez y no ofrece HTTPS. Escucha solo en `127.0.0.1`, limita el cuerpo de
> la petición y solo atiende consultas que lleguen desde su propia interfaz
> ---comprueba `Host`, `Origin` y `Content-Type`---, de modo que una página
> ajena abierta en el mismo navegador no puede usarlo. El despliegue queda
> fuera del alcance de este trabajo.

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
pytest                                          # la tanda entera, con fixtures HTML/PDF/JSON reales
mypy src/tfg_uja/ --ignore-missing-imports      # tipado estático limpio
black src/ tests/ scripts/                      # formato
flake8 src/ tests/ scripts/                     # estilo (configurado en .flake8)
```

Algunas pruebas se saltan solas cuando falta el índice vectorial o Ollama no
responde, y dicen cuál de las dos cosas falta en vez de pasar en verde en
silencio. La prueba lenta de integración recorre el conjunto
de evaluación entero llamando al modelo y queda fuera de la tanda por defecto:

```console
py -m pytest tests/test_integracion_rag.py -m lento -q -ra
```

Principios de las pruebas: fixtures **reales** descargadas de la EPSJ (nunca
peticiones de red en los tests, nunca datos inventados), y todo defecto
encontrado entra como test de regresión con su caso real.

## Estructura del repositorio

```text
src/tfg_uja/          # código fuente, repartido por fases del trabajo
  text_cleaner.py     #   compartido: normalización y limpieza de texto
  invariantes.py      #   compartido: comprobación de invariantes sin assert
  extraccion/         # Fase 0 — obtención del corpus
    grados_spider.py  #   rastreo de la web de la EPSJ
    guia_pdf.py       #   extracción de las guías servidas en PDF
    validators.py     #   validación de las filas de la tabla
  indexacion/         # Fase 1 — del corpus al índice vectorial
    chunker.py        #   fragmentación y deduplicación
    incrustaciones.py · indexer.py · evaluacion.py
  dialogo/            # Fase 2 — de la pregunta a la respuesta comprobada
    recuperador.py    #   búsqueda y acotado del contexto
    ambito.py         #   de qué titulación se está hablando
    conversacion.py   #   estado del diálogo y ventana de contexto
    generador.py      #   prompt y llamada al modelo
    verificacion.py   #   comprobaciones deterministas de la respuesta
  aplicacion/         # Fase 3 — la aplicación web
    servidor.py       #   interfaz + /api/chat
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

De cada figura se versiona **solo el fichero que compila LaTeX**, que es el
`.pdf`. La fuente editable (`.svg` y sus exportaciones a `.png`) se guarda
fuera del repositorio: dos formatos del mismo dibujo obligan a saber cuál es el
bueno, y el que manda es el que aparece en el `\includegraphics`.

## Metodología

- **Kanban** en GitHub Projects: cada tarea es una *issue* `IT-XX` con fase,
  prioridad MoSCoW y *milestone*.
- Ramas efímeras desde `main` (código) o `doc` (memoria), nombradas
  `IT-XX-descripcion-corta`; fusión siempre con *merge commit*, nunca *squash*.
- **Conventional Commits** (`tipo(IT-XX): descripción`), con el tipo en inglés
  por ser parte del estándar y la descripción en español. Los tipos en uso son
  `feat`, `fix`, `docs`, `test`, `refactor`, `chore` y `ci`. El cuerpo es
  obligatorio y explica el *porqué* de la decisión, no el qué.
- Cada rama se cierra con un *pull request* que enlaza su *issue*
  (`Closes #NN`) y no se fusiona hasta que la CI está en verde.
- Decisiones de diseño registradas como **ADR** en `docs/adr/`; anomalías de la
  fuente de datos como **DQA** en `docs/dqa/`.
- CI en GitHub Actions: `pytest` + `mypy` en cada *push* y *pull request*.

### Definición de Hecho

Una tarea se da por terminada cuando cumple los seis criterios: **funciona**
---ejecutado, no solo leído---, **tiene pruebas** con casos reales, **está
documentada** (docstrings, cuerpo del commit y ADR si procede), **está
integrada** en `main` con la CI en verde, **es defendible** en dos minutos y
**está reflejada en la memoria**.

## Decisiones de diseño

Las decisiones de arquitectura se documentan como ADR, cada una con las
alternativas consideradas y la evidencia que la resolvió:

| ADR | Decisión |
| --- | --- |
| [ADR-0001](docs/adr/adr-0001-estrategia-chunking.md) | Estrategia de fragmentación y deduplicación |
| [ADR-0002](docs/adr/adr-0002-alternativas-extraccion-datos.md) | Scrapy como marco de extracción |
| [ADR-0003](docs/adr/adr-0003-modelo-de-embeddings.md) | Modelo de incrustaciones |
| [ADR-0004](docs/adr/adr-0004-base-vectorial.md) | Base de datos vectorial |
| [ADR-0005](docs/adr/adr-0005-modelo-de-generacion.md) | Modelo generativo |
| [ADR-0006](docs/adr/adr-0006-emision-de-la-respuesta.md) | Cómo se emite la respuesta |

## Alcance

La primera versión cubre las titulaciones de grado de la EPSJ. El sistema se
ha diseñado para poder ampliarse al resto de centros de la Universidad de
Jaén añadiendo nuevas fuentes al proceso de extracción, sin rehacer el núcleo
de recuperación y generación. **Que el diseño admita crecer está justificado;
que el sistema escale no está medido.** El profesorado se excluye
deliberadamente de los datos extraídos (privacidad).

## Aviso legal y ético

- Se respeta `robots.txt` (`ROBOTSTXT_OBEY = True`) y se aplica retardo entre
  peticiones (`DOWNLOAD_DELAY`) hacia el servidor de la UJA.
- Solo se extraen **datos públicos** de naturaleza académica.
- **El profesorado se excluye** por privacidad. Las guías servidas en PDF sí
  traen un bloque de profesorado con nombres, correos y teléfonos: se extraen
  únicamente las secciones *Resumen* y *Descripción de contenidos* ---una lista
  de permitidos, no de prohibidos--- y después se redactan correos y teléfonos
  como red de seguridad. **Ningún dato personal llega a la base vectorial.**
- «Los principios de la protección de datos no deben aplicarse a la información
  anónima, es decir, información que no guarda relación con una persona física
  identificada o identificable» (considerando 26, Reglamento (UE) 2016/679).

## Licencia

[GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html). Véase [`LICENSE`](LICENSE).

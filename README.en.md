# EPSJ Degree Recommender

[![Español](https://img.shields.io/badge/lang-Español-blue.svg)](README.md)
[![English](https://img.shields.io/badge/lang-English-red.svg)](README.en.md)
[![Tests](https://github.com/samubp10/tfg-recomendador-uja/actions/workflows/tests.yml/badge.svg)](https://github.com/samubp10/tfg-recomendador-uja/actions/workflows/tests.yml)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/)
[![License GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-green)](https://www.gnu.org/licenses/gpl-3.0.html)

> English version of [`README.md`](README.md). The project itself — code comments,
> documentation, thesis and commit messages — is written in Spanish.

Chatbot that answers questions about the bachelor's degrees of the Higher
Polytechnic School of Jaén (EPSJ), University of Jaén. It is aimed at
pre-university students deciding what to study: it answers questions about
subjects, curricula and career prospects using the information the university
publishes.

Internally it combines Retrieval-Augmented Generation (RAG) with an open-weights
language model run locally, so that answers rest on real university data rather
than on the model's generic knowledge. **No external service is ever queried:**
the generative model, the embeddings model and the vector index all run on the
same machine.

This repository is a Bachelor's Thesis (TFG) in Computer Engineering at the
University of Jaén, academic year 2025/2026.

**Author:** Samuel Blanco Palmero · **Supervisor:** Juan Carlos Cuevas Martinez

## Project status

| Phase | Contents | Status |
| ----- | -------- | ------ |
| 0 | Web scraping, cleaning, validation and chunking | ✅ Complete |
| 1 | Chunking strategy and embeddings comparison | ✅ Complete |
| 2 | Vector database, local LLM and full RAG pipeline | ✅ Complete |
| 3 | Web chat application | ✅ Complete |
| 4 | User validation and ablation study | 🚧 In progress |
| 5 | Wrap-up and defence | Pending |

## Architecture

```text
EPSJ website ──spider──▶ grados.json ──chunker──▶ chunks.json ──indexer──▶ LanceDB index
                                                                                │
                                        browser ◀── server ◀── RAG ◀────────────┘
                                                      │
                                                      └──▶ Ollama (gemma3:12b)
```

Each stage is decoupled from the next and produces a regenerable artefact:
re-chunking or re-indexing is cheap and happens often while experimenting;
re-crawling the website is expensive and impolite towards the university's
server, so it only happens when the source changes.

The web application is **a single Python process** that serves the interface and
answers the queries, importing the retrieval-and-generation pipeline as a
library. The only thing running apart from it is the inference server.

## Dataset

Figures are a **snapshot, not a constant**: the EPSJ publishes new syllabuses
throughout the year, so they change on every crawl. Both `grados.json` and
`chunks.json` carry their own extraction date and academic year inside the file.

| Metric | Value |
| --- | ---: |
| Crawled on | 2026-08-16 (academic year 2026-27) |
| Chunked on | 2026-08-19 |
| Degrees (5 of them double degrees) | 12 |
| Degrees with subjects of their own | 11 |
| Subjects | 528 |
| Syllabuses (all served as PDF) | 288 |
| Syllabus coverage | 83.7 % |
| Subjects with no syllabus content | 86 |
| Career-prospects blocks | 8 |
| **Chunks after deduplication** | **1,499** |
| Units they belong to (81 shared between degrees) | 398 |

The twelfth degree is a double degree run jointly with a German university and
publishes no curriculum of its own, so it contributes no chunks.

Two crawls a day apart (2026-07-29 and 2026-07-30) produced a **byte-identical
corpus**, chunk by chunk.

Verify any of these figures yourself with the checkers below — do not trust this
table, it is only as fresh as the last time someone edited it.

## Requirements

### Software

| What | Tested version | What for |
| --- | --- | --- |
| **Python** | 3.13 | all the code |
| **[Ollama](https://ollama.com/)** | 0.32.14 | local inference server, on `http://127.0.0.1:11434` |
| Docker | — | **optional**, only for the experiment comparing vector databases (Qdrant) |

The project requires **Python 3.13.** and admits no other version: that is what
`pyproject.toml`, `mypy`, `black`, the `.python-version` file and CI all declare,
and a test fails if any of them drifts. Development happened on 3.13.5.

### Models

Downloaded once, then kept locally:

| Model | On-disk size | How it gets there |
| --- | ---: | --- |
| `gemma3:12b` — generation (ADR-0005) | 8.1 GB | `ollama pull gemma3:12b` |
| `intfloat/multilingual-e5-small` — embeddings (ADR-0003) | ~0.5 GB | downloaded automatically by `sentence-transformers` on first use |

> The small embeddings model was chosen over the large one **deliberately**: both
> have to share memory with the generative model, and the first run of the
> comparison died out of memory loading the large one (ADR-0003).

## Installation

### 1. Python environment

#### Windows (CMD or PowerShell)

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

> On Git Bash for Windows: `source .venv/Scripts/activate`.

To actually run the system (indexing and queries) you also need the `[index]`
extra, which pulls in PyTorch through `sentence-transformers` (hundreds of MB).
The tests do **not** need it: they inject a fake embedder.

```console
pip install -e ".[dev,index]"
```

To **reproduce an experiment with the environment it was measured on**, add
`-c constraints.txt`, which pins that snapshot exactly. Without it you get
today's versions, which is what you want for working and not what you want for
comparing against an already published figure.

### 2. Inference server

```console
ollama pull gemma3:12b
ollama serve
```

`ollama serve` leaves the server listening on `http://127.0.0.1:11434`, which is
where the system looks for it. On Windows and macOS the Ollama desktop app
starts it on login.

## Usage

Generated data lives in `data/` and is **not versioned**: it is regenerated by
the pipeline itself, and that regeneration is what guarantees reproducibility.

```console
# 1. Extract the dataset — makes REAL requests to the UJA website.
#    Use sparingly (respects robots.txt and delays requests).
scrapy runspider src/tfg_uja/extraccion/grados_spider.py -O data/grados.json

# 2. Chunk the corpus (offline, cheap)
py -m tfg_uja.indexacion.chunker data/grados.json data/chunks.json

# 3. Index into the vector database (requires the [index] extra).
#    The default model is the one chosen in ADR-0003; another one can be
#    passed as a third argument to repeat the experiment without touching code.
py -m tfg_uja.indexacion.indexer data/chunks.json data/indice_lance

# 4. Start the web application
py -m tfg_uja.aplicacion.servidor
```

Step 4 opens the assistant at **<http://127.0.0.1:8000>**. It needs
`data/indice_lance` and `data/grados.json` to exist and Ollama to be answering;
if the index is missing the program says so and refuses to start.

There is also a console client, handy for exercising the pipeline without a
browser:

```console
py scripts/chat_rag.py
```

> ⚠️ **The server is not production-ready, and says so.** It is built on the
> standard library's `http.server`: it serves one request at a time and offers
> no HTTPS. It listens on `127.0.0.1` only, caps the request body, and answers
> queries only when they come from its own interface ---it checks `Host`,
> `Origin` and `Content-Type`---, so a foreign page open in the same browser
> cannot drive it. Deployment is out of the scope of this work.

### Dataset checkers (local only)

They do not run in CI because `data/` does not exist in a clean checkout; they
are run before every push:

```console
py scripts/verificadores/check_dataset.py    # integrity of degrees/subjects/syllabuses/prospects
py scripts/verificadores/check_chunks.py     # chunk sizes and deduplication
py scripts/verificadores/check_evalset.py    # the evaluation set resolves against the dataset
py scripts/verificadores/check_guias_pdf.py  # PDF extraction is faithful to the originals
```

### Experiments

They live in `scripts/experimentos/` and each writes its results into the ADR or
the `docs/experimentos/` file it belongs to. Several take hours, and the phase 2
and 3 ones need Ollama running.

```console
py scripts/experimentos/experimento_embeddings.py   # ADR-0003: compares embedding models
py scripts/experimentos/experimento_vectordb.py     # ADR-0004: compares vector databases
py scripts/experimentos/experimento_generacion.py   # ADR-0005: compares generative models
py scripts/experimentos/experimento_recuperacion.py # Recall@K, MRR and out-of-domain rejection
py scripts/experimentos/experimento_sistema.py      # the full end-to-end run
```

⚠️ **Do not send anything else to Ollama while an experiment is measuring.** The
timings stop meaning anything, and with the model loaded the wording changes
between calls.

## Tests

```console
pytest                                          # the whole run, with real HTML/PDF/JSON fixtures
mypy src/tfg_uja/ --ignore-missing-imports      # clean static typing
black src/ tests/ scripts/                      # formatting
flake8 src/ tests/ scripts/                     # style (configured in .flake8)
```

Some tests skip themselves when the vector index is missing or Ollama is not
answering, and say which of the two is missing rather than passing green in
silence. The slow integration test walks the whole
evaluation set calling the model, and is excluded from the default run:

```console
py -m pytest tests/test_integracion_rag.py -m lento -q -ra
```

Testing principles: **real** fixtures downloaded from the EPSJ (never network
requests in tests, never made-up data), and every defect found enters as a
regression test with its real case.

## Repository structure

```text
src/tfg_uja/          # source code, split by phase of the work
  text_cleaner.py     #   shared: text normalisation and cleaning
  invariantes.py      #   shared: invariant checks that survive python -O
  extraccion/         # Phase 0 — obtaining the corpus
    grados_spider.py  #   crawls the EPSJ website
    guia_pdf.py       #   extracts the syllabuses served as PDF
    validators.py     #   validates the rows of the subject table
  indexacion/         # Phase 1 — from corpus to vector index
    chunker.py        #   chunking and deduplication
    incrustaciones.py · indexer.py · evaluacion.py
  dialogo/            # Phase 2 — from question to checked answer
    recuperador.py    #   retrieval and context cut-off
    ambito.py         #   which degree the conversation is about
    conversacion.py   #   dialogue state and context window
    generador.py      #   prompt building and model call
    verificacion.py   #   deterministic checks on the answer
  aplicacion/         # Phase 3 — the web application
    servidor.py       #   interface + /api/chat
    sugerencias.py · registro_chat.py
web/                # interface: HTML, CSS and JavaScript, no dependencies
tests/              # tests with real fixtures (EPSJ HTML and PDF)
scripts/            # checkers, experiments and question banks
eval/               # retrieval evaluation set (manual, versioned)
docs/adr/           # Architecture Decision Records (ADR)
docs/dqa/           # Data Quality Assessment records (DQA)
docs/experimentos/  # real results, written by the scripts themselves
memoria/            # the thesis itself, in LaTeX (EPSJ template)
data/               # generated artefacts (NOT versioned)
```

> **Note:** the thesis document (*memoria*), written in LaTeX, lives in the
> **`doc`** branch, not in `main`.

## Methodology

- **Kanban** on GitHub Projects: every task is an `IT-XX` issue with its phase,
  MoSCoW priority and milestone.
- **Conventional Commits** (`type(IT-XX): description`), with a mandatory body
  explaining the *why* of each decision.
- Short-lived branches off `main` (code) or `doc` (thesis); always merged with a
  *merge commit*, never *squash*.
- Design decisions recorded as **ADRs** in `docs/adr/`; data-source anomalies as
  **DQAs** in `docs/dqa/`.
- CI on GitHub Actions: `pytest` + `mypy` on every push and pull request.

## Design decisions

Architectural decisions are documented as ADRs, each with the alternatives
considered and the evidence that settled it:

| ADR | Decision |
| --- | --- |
| [ADR-0001](docs/adr/adr-0001-estrategia-chunking.md) | Chunking strategy and deduplication |
| [ADR-0002](docs/adr/adr-0002-alternativas-extraccion-datos.md) | Scrapy as the extraction framework |
| [ADR-0003](docs/adr/adr-0003-modelo-de-embeddings.md) | Embeddings model |
| [ADR-0004](docs/adr/adr-0004-base-vectorial.md) | Vector database |
| [ADR-0005](docs/adr/adr-0005-modelo-de-generacion.md) | Generative model |
| [ADR-0006](docs/adr/adr-0006-emision-de-la-respuesta.md) | How the answer is streamed back |

## Scope

The first version covers the EPSJ bachelor's degrees. The system is designed to
be extended to other schools of the University of Jaén by adding sources to the
extraction stage, without rewriting the retrieval and generation core. **That the
design allows growth is argued; that the system scales is not measured.**
Teaching staff is deliberately excluded from the extracted data (privacy).

## Legal & ethical notice

- `robots.txt` is respected (`ROBOTSTXT_OBEY = True`) and polite throttling is
  applied (`DOWNLOAD_DELAY`) towards the UJA server.
- Only **public data** of an academic nature is extracted.
- **Teaching staff is excluded** for privacy. Syllabuses served as PDF do carry a
  staff block with names, e-mail addresses and phone numbers: only the *Summary*
  and *Description of contents* sections are extracted — an allowlist, not a
  blocklist — and e-mail addresses and phone numbers are stripped afterwards as a
  safety net. **No personal data ever reaches the vector database.**
- "The principles of data protection should therefore not apply to anonymous
  information, namely information which does not relate to an identified or
  identifiable natural person" (Recital 26, Regulation (EU) 2016/679).

## License

[GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html). See [`LICENSE`](LICENSE).

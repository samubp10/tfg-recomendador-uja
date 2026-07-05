# Recomendador UJA

[![Español](https://img.shields.io/badge/lang-Español-blue.svg)](README.md)
[![English](https://img.shields.io/badge/lang-English-red.svg)](README.en.md)
[![CI](https://github.com/samubp10/tfg-recomendador-uja/actions/workflows/tests.yml/badge.svg)](https://github.com/samubp10/tfg-recomendador-uja/actions/workflows/tests.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)

RAG Chatbot that recommends bachelor's degrees from the Higher Polytechnic School of Jaén (EPSJ) at the University of Jaén. Bachelor's Thesis (TFG) for the Degree in Computer Engineering.

## Table of contents
- [Problem & solution](#problem--solution)
- [Phased architecture](#phased-architecture)
- [Dataset](#dataset)
- [Repository structure](#repository-structure)
- [Installation](#installation)
- [Usage](#usage)
- [Tests](#tests)
- [Methodology](#methodology)
- [Design decisions](#design-decisions)
- [Legal & ethical notice](#legal--ethical-notice)
- [License](#license)
- [Authorship & acknowledgments](#authorship--acknowledgments)

## Problem & solution
Choosing a university degree is difficult: official information is scattered across dozens of pages. **Recomendador UJA** centralizes this information and allows querying it in natural language through a RAG (Retrieval-Augmented Generation) system built on public data from the EPSJ.

## Phased architecture
- **Phase 0 — Scraping + chunking (completed):** dataset extraction using Scrapy and chunk preparation.
- **Phase 1 — RAG (planned):** vector indexing and retrieval.
- **Phase 2 — Evaluation (planned):** quality metrics for the recommender.
- **Phase 3 — Application (planned):** chatbot interface.

## Dataset
| Metric | Value |
|---|---|
| Degrees | 8 |
| Subjects | 361 |
| Syllabuses | 296 |
| Syllabus coverage | 81 % |

Generated with Scrapy from the public website of the EPSJ.

## Repository structure
```text
src/tfg_uja/       # Source code (spider + utilities)
tests/             # Tests + real HTML fixtures
data/              # Dataset (grados.json) & check_dataset.py
docs/adr/          # Architecture Decision Records
.github/workflows/ # CI (GitHub Actions)
```

> **Note**: The project's thesis document (memoria), written in LaTeX, is kept in the `docs` branch.

## Installation
Requires **Python 3.13**.

```bash
# Create virtual environment
py -m venv .venv

# Activate on Windows (CMD / PowerShell)
.venv\Scripts\activate
# (On Linux, macOS or Git Bash use: source .venv/bin/activate)

# Install dependencies
pip install -e ".[dev]"
```

## Usage

### Run the spider
```bash
scrapy runspider src/tfg_uja/grados_spider.py -O data/grados.json
```

### Verify the dataset
```bash
py data/check_dataset.py
```

## Tests
```bash
pytest
```

## Methodology
- **Kanban** with GitHub Projects.
- **Conventional Commits** (`type(IT-XX): description`).
- **ADRs** in `docs/adr/`.
- **Real HTML fixtures** for deterministic, offline testing.

## Design decisions
Relevant architectural decisions are documented as ADRs in [`docs/adr/`](docs/adr/), e.g., the choice of Scrapy ([ADR-0002](docs/adr/adr-0002-alternativas-extraccion-datos.md)).

## Legal & ethical notice
- `robots.txt` is respected (`ROBOTSTXT_OBEY = True`) and polite throttling is applied (`DOWNLOAD_DELAY`) towards the UJA server.
- Only **public data** of an academic nature is extracted.
- **Teaching staff is excluded** for privacy: personal data is not collected. "The principles of data protection should therefore not apply to anonymous information, namely information which does not relate to an identified or identifiable natural person" (Recital 26, Regulation (EU) 2016/679).

## License
Distributed under the **GPL-3.0** license. See [`LICENSE`](LICENSE).

## Authorship & acknowledgments
- **Author:** Samuel (samubp10).
- **Tutor:** [TFG tutor].
- Bachelor's Thesis (TFG) in Computer Engineering, University of Jaén (UJA).

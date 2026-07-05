# Recomendador de Grados de la EPSJ

Chatbot de recomendación e información sobre las titulaciones de grado de la Escuela Politécnica Superior de Jaén. Está pensado para ayudar a estudiantes o personas que tienen que decidir qué carrera estudiar: responde preguntas sobre asignaturas, planes de estudio y salidas profesionales a partir de la información publicada por la Universidad de Jaén.

Por dentro combina recuperación de información (RAG) sobre un modelo de lenguaje de código abierto, de manera que las respuestas se apoyan en datos reales de la universidad y no en el conocimiento genérico del modelo.

Este repositorio corresponde a un Trabajo Fin de Grado del Grado en Ingeniería Informática de la Universidad de Jaén, curso 2025/2026.

Autor: Samuel Blanco Palmero  
Tutor: Juan Carlos Cuevas Martinez

## Alcance

La primera versión cubre las titulaciones de la EPSJ. El sistema se ha diseñado para poder ampliarse al resto de facultades de la Universidad de Jaén añadiendo nuevas fuentes al proceso de extracción de datos, sin tener que rehacer el núcleo de recuperación y generación.

## Requisitos

- Python 3.10 o superior (desarrollado con la versión 3.13)

## Instalación
Requiere **Python 3.13**.

**Windows (CMD o PowerShell)**
```
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

**Linux / macOS**
```
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```
> En Git Bash sobre Windows: `source .venv/Scripts/activate`.

## Uso

El proyecto está en desarrollo. Las instrucciones de ejecución de cada componente se irán añadiendo en esta sección conforme estén disponibles.

## Estructura del repositorio

- `src/tfg_uja/` — código fuente
- `docs/adr/` — registro de las decisiones de diseño (ADR)

La memoria del proyecto, escrita en LaTeX, se mantiene en la rama `doc`.

## Licencia

GPL-3.0

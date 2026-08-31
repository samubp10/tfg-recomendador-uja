"""Coherencia de la versión de Python declarada por el proyecto."""

from pathlib import Path
import tomllib

RAIZ = Path(__file__).resolve().parents[1]
VERSION = "3.13"


def test_todo_el_proyecto_declara_python_313() -> None:
    """Evita que instalación, herramientas, CI y documentación diverjan."""
    proyecto = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    flujo = (RAIZ / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    leeme = (RAIZ / "README.md").read_text(encoding="utf-8")
    leeme_ingles = (RAIZ / "README.en.md").read_text(encoding="utf-8")

    assert proyecto["project"]["requires-python"] == ">=3.13,<3.14"
    assert proyecto["tool"]["black"]["target-version"] == ["py313"]
    assert proyecto["tool"]["mypy"]["python_version"] == VERSION
    assert f'python-version: "{VERSION}"' in flujo
    assert (RAIZ / ".python-version").read_text(encoding="utf-8").strip() == VERSION
    assert "Python 3.13." in leeme
    assert "Python 3.13." in leeme_ingles
    assert "3.10" not in leeme
    assert "3.10" not in leeme_ingles

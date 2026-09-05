"""Sugerencias de preguntas que el sistema sabe responder (Fase 3)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from itertools import islice
from typing import Any, Final, TypeVar

from tfg_uja.dialogo.recuperador import escapar

#: Cuántas sugerencias se ofrecen como mucho. Son botones bajo la
#: conversación: pasar de cuatro deja de ser un atajo y se convierte en un
#: menú que hay que leer.
MAXIMO: Final[int] = 4

# La mitad de las sugerencias sigue el ámbito actual; el resto permite explorar otras
# titulaciones.
DEL_AMBITO: Final[int] = 2

# Preguntas iniciales respaldadas por los fragmentos de catálogo.
ARRANQUE_CATALOGO: Final[tuple[str, ...]] = (
    "¿Qué titulaciones puedo estudiar en la Escuela Politécnica Superior de Jaén?",
    "¿Qué dobles grados ofrece la Escuela Politécnica Superior de Jaén?",
)

# La petición de consejo usa la consulta ampliada del recuperador.
PETICION_DE_CONSEJO: Final[str] = "No sé qué estudiar, ¿qué me recomiendas?"

# Cada pregunta exige contenido del origen indicado para la titulación.

# Alterna asuntos para no ofrecer seguidas preguntas sobre lo mismo.

# Los orígenes deben coincidir con los nombres exactos que escribe el fragmentador.

# La plantilla incluye el artículo que falta en el nombre oficial del catálogo.
PLANTILLAS: Final[tuple[tuple[str, str], ...]] = (
    # 11 de 12
    ("origen = 'plan_de_estudios'", "¿Qué asignaturas tiene el {titulacion}?"),
    # 8 de 12
    (
        "origen = 'salidas'",
        "¿Qué salidas profesionales tiene el {titulacion}?",
    ),
    # 5 de 12
    ("origen = 'mencion'", "¿Qué menciones ofrece el {titulacion}?"),
    # 11 de 12. El curso casa por prefijo, igual que en el recuperador.
    (
        "origen = 'guia' AND starts_with(lower(curso), 'primer')",
        "¿Qué se aprende en las asignaturas de primer curso del {titulacion}?",
    ),
    # 7 de 12: las optativas las publica la EPSJ sin curso asignado.
    (
        "tipo_asignatura = 'OP'",
        "¿Qué asignaturas optativas se pueden elegir en el {titulacion}?",
    ),
    # 12 de 12: la ficha es lo único que tienen todas, incluido el doble grado
    # internacional, al que la Escuela no le publica ni una asignatura.
    (
        "origen = 'ficha_titulacion'",
        "¿Cuántas asignaturas tiene el {titulacion} y cómo se reparten por curso?",
    ),
    # 11 de 12
    (
        "origen = 'plan_de_estudios' AND starts_with(lower(curso), 'cuarto')",
        "¿Qué asignaturas se dan en cuarto curso del {titulacion}?",
    ),
    # 8 de 12
    (
        "tipo_asignatura = 'TFG'",
        "¿En qué consiste el Trabajo Fin de Grado del {titulacion}?",
    ),
    # 10 de 12
    (
        "tipo_asignatura = 'FB'",
        "¿Qué asignaturas de formación básica se cursan en el {titulacion}?",
    ),
    # 9 de 12
    (
        "origen = 'guia' AND starts_with(lower(curso), 'cuarto')",
        "¿Qué se estudia en cuarto curso del {titulacion}?",
    ),
)

T = TypeVar("T")


def _rotar(secuencia: Sequence[T], desplazamiento: int) -> list[T]:
    """La misma secuencia, empezando por otro sitio."""
    corte = desplazamiento % len(secuencia) if secuencia else 0
    return list(secuencia[corte:]) + list(secuencia[:corte])


def _hay(tabla: Any, filtro: str) -> bool:
    """Dice si el índice guarda algún fragmento que case con el filtro."""
    return tabla.count_rows(filtro) > 0


def _preguntas(tabla: Any, titulacion: str, desplazamiento: int) -> Iterator[str]:
    """Va soltando las preguntas que el índice respalda para una titulación."""
    # La pertenencia exacta evita arrastrar dobles grados por coincidencia parcial.
    suya = f"array_has_any(grados, ['{escapar(titulacion)}'])"
    for condicion, pregunta in _rotar(PLANTILLAS, desplazamiento):
        if _hay(tabla, f"{suya} AND {condicion}"):
            yield pregunta.format(titulacion=titulacion)


def _del_ambito(tabla: Any, conocidas: list[str], desplazamiento: int) -> list[str]:
    """Preguntas de las titulaciones de las que se está hablando."""
    cada_una = max(1, DEL_AMBITO // len(conocidas))
    return [
        pregunta
        for indice, titulacion in enumerate(conocidas)
        for pregunta in islice(
            _preguntas(tabla, titulacion, desplazamiento + indice), cada_una
        )
    ][:DEL_AMBITO]


def _de_arranque(tabla: Any, desplazamiento: int) -> list[str]:
    """Preguntas con las que empezar cuando no se habla de nada todavía."""
    catalogo = _rotar(ARRANQUE_CATALOGO, desplazamiento)
    respaldadas = catalogo[:1] if _hay(tabla, "origen = 'catalogo'") else []
    return respaldadas + [PETICION_DE_CONSEJO]


def _de_otras(
    tabla: Any, otras: list[str], desplazamiento: int, cuantas: int
) -> list[str]:
    """Una pregunta de cada una de otras titulaciones, para abrir el abanico."""
    elegidas: list[str] = []
    for indice, titulacion in enumerate(_rotar(otras, desplazamiento)):
        if len(elegidas) >= cuantas:
            break
        elegidas += islice(_preguntas(tabla, titulacion, desplazamiento + indice), 1)
    return elegidas


def sugerencias_para(
    tabla: Any, ambito: list[str], catalogo: list[str], desplazamiento: int = 0
) -> list[str]:
    """Preguntas que ofrecerle al estudiante en el punto en que va el diálogo."""
    # Solo interpola nombres del catálogo del índice en el filtro SQL.
    conocidas = [t for t in ambito if t in catalogo]
    if conocidas:
        propias = _del_ambito(tabla, conocidas, desplazamiento)
    else:
        propias = _de_arranque(tabla, desplazamiento)
    otras = [t for t in catalogo if t not in conocidas]
    return propias + _de_otras(tabla, otras, desplazamiento, MAXIMO - len(propias))

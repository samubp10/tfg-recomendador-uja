"""De qué titulación se está hablando, decidido turno a turno por el modelo."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Final

from tfg_uja.dialogo.generador import ErrorDelModelo, generar
from tfg_uja.text_cleaner import normalizar

# Decisiones admitidas: conservar, cambiar, ampliar o descartar el ámbito.
SIGUE: Final[str] = "SIGUE"
CAMBIA: Final[str] = "CAMBIA"
TODAS: Final[str] = "TODAS"
NINGUNA: Final[str] = "NINGUNA"

# Marca el fallo del decisor; no es una decisión del modelo.
FALLO: Final[str] = "FALLO"

# Recorta la respuesta anterior para limitar el contexto de la decisión.
LARGO_RESPUESTA_ANTERIOR: Final[int] = 420

# El límite admite el nombre más largo del catálogo y la etiqueta de decisión.
TOPE_DECISION: Final[int] = 40

#: Longitud a partir de la cual se admite que lo escrito case por subcadena con
#: un nombre del catálogo. Por debajo, cualquier palabra suelta ---«grado»,
#: «doble»--- casaría con las doce.
LARGO_MINIMO_PARCIAL: Final[int] = 12

#: Veces que se le pide la decisión al modelo antes de darla por perdida.

# Reintenta una vez ante fallos transitorios del servidor de inferencia.

#: Un reintento cuesta unos segundos en el único caso en que la alternativa es
#: responder de la titulación equivocada. Más de uno no: si el servidor está
#: caído de verdad, la generación va a fallar a continuación de todos modos.
INTENTOS: Final[int] = 2

# Registra el fallo antes de recurrir al respaldo determinista.
_registro: Final[logging.Logger] = logging.getLogger(__name__)


@dataclass(frozen=True)
class Decision:
    """Qué hay que buscar para responder al mensaje de este turno."""

    clase: str
    titulaciones: list[str]


# La función inyectable mantiene la conversación independiente del modelo generativo.
Decisor = Callable[[str, list[str], "tuple[str, str] | None"], "Decision | None"]


def _bloque_ultimo_turno(ultimo_turno: tuple[str, str] | None) -> str:
    """El último turno completo, tal como se le enseña al modelo."""
    if ultimo_turno is None:
        return ""
    pregunta, respuesta = ultimo_turno
    recortada = respuesta.strip()[:LARGO_RESPUESTA_ANTERIOR]
    return (
        " Último turno:\n" f"  ESTUDIANTE: «{pregunta}»\n" f"  ASISTENTE: «{recortada}»"
    )


def construir_peticion(
    pregunta: str,
    ambito: list[str],
    ultimo_turno: tuple[str, str] | None,
    catalogo: list[str],
) -> str:
    """Arma el texto con el que se le pide la decisión al modelo."""
    lista = "\n".join(f"- {t}" for t in catalogo)
    if ambito:
        if len(ambito) == 1:
            actual = ambito[0]
            encabezado = f"Se está hablando con un estudiante sobre el {actual}."
            opcion_sigue = f"- SIGUE  si su mensaje se sigue refiriendo al {actual}\n"
        else:
            actual = "; ".join(ambito)
            encabezado = (
                "Se está hablando con un estudiante sobre estas titulaciones: "
                f"{actual}."
            )
            opcion_sigue = (
                "- SIGUE  si su mensaje se sigue refiriendo a estas titulaciones: "
                f"{actual}\n"
            )
        opcion_nombre = (
            "- uno o varios nombres exactos de la lista, separados por punto y "
            "coma, si trata de otras titulaciones o las compara\n"
        )
    else:
        encabezado = "Se está hablando con un estudiante."
        opcion_sigue = ""
        opcion_nombre = (
            "- uno o varios nombres exactos de la lista, separados por punto y "
            "coma, si su mensaje trata de esas titulaciones o las compara\n"
        )
    return (
        f"Titulaciones de la Escuela Politécnica Superior de Jaén:\n{lista}\n\n"
        f"{encabezado}{_bloque_ultimo_turno(ultimo_turno)}\n\n"
        f"Y ahora el estudiante escribe: «{pregunta}»\n\n"
        "¿De qué hay que buscar información para responderle? Contesta con una "
        "sola línea:\n"
        f"{opcion_sigue}"
        f"{opcion_nombre}"
        "- TODAS  si pregunta por la oferta de la Escuela en general, sin una "
        "titulación concreta\n"
        "- NINGUNA  si su mensaje no trata de las titulaciones de la Escuela"
    )


def interpretar(salida: str, catalogo: list[str]) -> Decision:
    """Traduce lo que ha escrito el modelo, comprobándolo contra el catálogo."""
    lineas = [linea for linea in salida.splitlines() if linea.strip()]
    if not lineas:
        return Decision(NINGUNA, [])
    plano = normalizar(lineas[0].strip().strip(".-–—*: "))
    if plano.startswith("sigue"):
        return Decision(SIGUE, [])
    if plano.startswith("todas"):
        return Decision(TODAS, [])
    if plano.startswith("ninguna"):
        return Decision(NINGUNA, [])
    nombradas = _resolver(lineas[0], catalogo)
    return Decision(CAMBIA, nombradas) if nombradas else Decision(NINGUNA, [])


def _resolver(linea: str, catalogo: list[str]) -> list[str]:
    """Titulaciones del catálogo que la línea nombra."""
    encontradas: list[str] = []
    for trozo in linea.split(";"):
        dicho = normalizar(trozo.strip().strip(".-–—*: "))
        if not dicho:
            continue
        exactas = [t for t in catalogo if normalizar(t) == dicho]
        parciales = [
            t
            for t in catalogo
            if len(dicho) >= LARGO_MINIMO_PARCIAL and dicho in normalizar(t)
        ]
        for titulacion in exactas or parciales:
            if titulacion not in encontradas:
                encontradas.append(titulacion)
    return [t for t in catalogo if t in encontradas]


def decisor_con_modelo(
    catalogo: list[str],
    modelo: str,
    generador: Callable[..., str] = generar,
) -> Decisor:
    """Construye el decisor que consulta al modelo."""

    def decidir(
        pregunta: str,
        ambito: list[str],
        ultimo_turno: tuple[str, str] | None,
    ) -> Decision | None:
        peticion = construir_peticion(pregunta, ambito, ultimo_turno, catalogo)
        for intento in range(INTENTOS):
            try:
                return interpretar(
                    generador(peticion, modelo, tope=TOPE_DECISION), catalogo
                )
            except ErrorDelModelo as fallo:
                _registro.warning(
                    "Decisión de ámbito fallida (intento %d de %d): %s",
                    intento + 1,
                    INTENTOS,
                    fallo,
                )
        return None

    return decidir

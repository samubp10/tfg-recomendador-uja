"""Estado de la conversación con el asistente (IT-106)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from tfg_uja.dialogo.ambito import CAMBIA, FALLO, NINGUNA, SIGUE, TODAS, Decisor
from tfg_uja.dialogo.recuperador import palabras_distintivas
from tfg_uja.text_cleaner import normalizar, palabras

# La ventana conserva preguntas recientes y mantiene el sujeto aparte; las respuestas no
# entran en el prompt.
TURNOS_RECORDADOS: Final[int] = 3

#: Palabras que no aportan tema. Sirven para decidir si una pregunta dice algo
#: por sí misma o solo cambia un dato de la anterior. La lista es corta a
#: propósito: solo partículas y los verbos más vacíos del castellano.
PALABRAS_VACIAS: Final[frozenset[str]] = frozenset("""
    a al algo cual cuales cuando de del donde el ella ellas ello ellos en esa
    esas ese eso esos esta estas este esto estos hay la las le les lo los me mi
    mis o para pero por que se ser son su sus tambien te tiene tienen tu un una
    unas uno unos y ya
    """.split())

# Un ordinal indica posición en el plan y hereda el asunto de la pregunta anterior.
ORDINALES: Final[frozenset[str]] = frozenset("""
    primer primero primera segundo segunda tercer tercero tercera cuarto
    cuarta quinto quinta ultimo ultima
    """.split())


def titulaciones_de_la_pregunta(pregunta: str, catalogo: list[str]) -> list[str]:
    """Titulaciones que la pregunta menciona, aunque sea con un nombre parcial."""
    distintivas = palabras_distintivas(catalogo)
    dichas = palabras(pregunta) & distintivas
    if not dichas:
        return []
    return [t for t in catalogo if palabras(t) & dichas]


def nombrada_por_si_misma(titulacion: str, texto: str, otras: list[str]) -> bool:
    """Si la titulación aparece por sí misma y no dentro del nombre de otra."""
    aguja = normalizar(titulacion)
    arrastradas = sum(
        texto.count(normalizar(o)) * normalizar(o).count(aguja)
        for o in otras
        if o != titulacion and aguja in normalizar(o)
    )
    return texto.count(aguja) > arrastradas


def titulaciones_de_la_respuesta(respuesta: str, catalogo: list[str]) -> list[str]:
    """Titulaciones que la respuesta del asistente nombra por su nombre entero."""
    dicho = normalizar(respuesta)
    presentes = [t for t in catalogo if normalizar(t) in dicho]
    return [t for t in presentes if nombrada_por_si_misma(t, dicho, presentes)]


#: Fórmulas con las que una pregunta se refiere a lo que acaba de decirse en
#: vez de nombrarlo. Son el rastro de que recorta el resultado anterior en
#: lugar de plantear un tema.
ANAFORAS: Final[tuple[str, ...]] = (
    "de esas",
    "de esos",
    "de estas",
    "de estos",
    "de ellas",
    "de ellos",
    "de las anteriores",
    "de los anteriores",
)


def recorta_lo_anterior(pregunta: str) -> bool:
    """Dice si la pregunta afina el resultado anterior en vez de plantear tema."""
    dicho = normalizar(pregunta)
    return any(anafora in dicho for anafora in ANAFORAS)


def contenido(pregunta: str, catalogo: list[str]) -> set[str]:
    """Palabras de la pregunta que dicen qué se pregunta."""
    # Retira todas las palabras del catálogo, incluidas las comunes como «grado».
    del_catalogo = {p for t in catalogo for p in palabras(t)}
    return palabras(pregunta) - PALABRAS_VACIAS - ORDINALES - del_catalogo


@dataclass(frozen=True)
class Consulta:
    """Lo que la conversación entrega al recuperador."""

    texto: str
    ambito: list[str]
    respaldo: str = ""
    abierta: bool = False
    decision: str = ""


@dataclass
class Conversacion:
    """Recuerda de qué se habla para que las preguntas de seguimiento funcionen."""

    catalogo: list[str]
    turnos_recordados: int = TURNOS_RECORDADOS
    decisor: Decisor | None = None
    _preguntas: list[str] = field(default_factory=list, init=False)
    _ambito: list[str] = field(default_factory=list, init=False)
    _predicado: str = field(default="", init=False)
    _ultimo_turno: tuple[str, str] | None = field(default=None, init=False)
    _decidido: str | None = field(default=None, init=False)

    @property
    def ambito(self) -> list[str]:
        """Titulaciones de las que se está hablando ahora mismo."""
        return list(self._ambito)

    def _decidir_ambito(self, pregunta: str) -> str:
        """Reapunta el ámbito con lo que decida el decisor, si lo hay."""
        self._decidido = None
        if self.decisor is None:
            return ""
        decision = self.decisor(pregunta, list(self._ambito), self._ultimo_turno)
        if decision is None:
            return FALLO
        self._decidido = decision.clase
        if decision.clase == CAMBIA:
            self._ambito = list(decision.titulaciones)
        elif decision.clase in (TODAS, NINGUNA):
            # Soltar el ámbito permite medir la pregunta sin el nombre de la titulación
            # anterior.
            self._ambito = []
        return decision.clase

    def preparar(self, pregunta: str) -> Consulta:
        """Convierte la pregunta en una consulta que se sostiene sola."""
        decidida = self._decidir_ambito(pregunta)
        decidio = decidida not in ("", FALLO)
        mencionadas = titulaciones_de_la_pregunta(pregunta, self.catalogo)
        # La decisión del modelo prevalece sobre coincidencias parciales en la pregunta.
        ambito = self._ambito if decidio else (mencionadas or self._ambito)
        # Dos nombres oficiales explícitos conservan la comparación aunque el decisor
        # devuelva uno solo.
        exactas = titulaciones_de_la_respuesta(pregunta, self.catalogo)
        if len(exactas) >= 2:
            self._ambito = list(exactas)
            ambito = exactas
        abierta = decidida == TODAS and len(exactas) < 2

        texto = pregunta
        if not contenido(pregunta, self.catalogo) and self._predicado:
            # Hereda el predicado sin las palabras distintivas de la titulación.
            # Sustituye el ordinal solo si la nueva pregunta aporta otro.
            sobran = palabras_distintivas(self.catalogo)
            if palabras(pregunta) & ORDINALES:
                sobran = sobran | ORDINALES
            anterior = " ".join(
                p for p in self._predicado.split() if not palabras(p) & sobran
            )
            texto = f"{anterior} {pregunta}".strip()
        elif not mencionadas and len(ambito) == 1:
            # La pregunta dice qué quiere pero no de quién: se le pone el
            # nombre oficial, no el texto entero de la pregunta anterior.
            texto = f"{pregunta} {ambito[0]}"

        # Prepara el reintento para búsquedas vacías, salvo si el decisor soltó el
        # ámbito: arrastrar el predicado recuperaría el sujeto descartado.
        respaldo = ""
        rescatable = not decidio or decidida == SIGUE
        if rescatable and self._predicado and self._predicado != pregunta:
            respaldo = f"{self._predicado} {pregunta}".strip()
        return Consulta(
            texto=texto,
            ambito=list(ambito),
            respaldo=respaldo,
            abierta=abierta,
            decision=decidida,
        )

    def anotar(self, pregunta: str, respuesta: str, cambia_ambito: bool = True) -> None:
        """Registra un turno y actualiza de qué se está hablando."""
        self._preguntas.append(pregunta)
        # El corte por el final también vacía la lista cuando la ventana vale cero.
        del self._preguntas[: len(self._preguntas) - self.turnos_recordados]
        self._ultimo_turno = (pregunta, respuesta)

        # Un saludo no cambia el predicado que heredará la siguiente pregunta.
        if (
            cambia_ambito
            and contenido(pregunta, self.catalogo)
            and not recorta_lo_anterior(pregunta)
        ):
            self._predicado = pregunta

        # Aplica el respaldo si el decisor falló en este turno, aunque esté configurado.
        decidido = self._decidido
        self._decidido = None
        if decidido is not None or not cambia_ambito:
            return
        nuevo = titulaciones_de_la_pregunta(
            pregunta, self.catalogo
        ) or titulaciones_de_la_respuesta(respuesta, self.catalogo)
        if nuevo:
            self._ambito = nuevo

    def preguntas(self) -> list[str]:
        """Preguntas que se le recuerdan al modelo, de más antigua a más nueva."""
        return list(self._preguntas)

    def olvidar(self) -> None:
        """Vacía la conversación y el sujeto. Deja el objeto como recién creado."""
        self._preguntas.clear()
        self._ambito.clear()
        self._predicado = ""
        self._ultimo_turno = None
        self._decidido = None

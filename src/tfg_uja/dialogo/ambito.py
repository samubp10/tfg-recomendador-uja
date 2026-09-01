"""De qué titulación se está hablando, decidido turno a turno por el modelo.

`Conversacion` deducía el sujeto de la conversación con reglas deterministas y
lo guardaba en `_ambito`, y ese ámbito **solo se sustituía, nunca se vaciaba**:
en cuanto una titulación entraba, todas las preguntas siguientes se filtraban
por ella. Siete formas distintas de cambiar de tema —«enséñame todas», «prefiero
algo de máquinas y motores», «olvídalo, cuéntame de topografía»— no lo
conseguían, y la última traía veinte fragmentos sin ninguno de Geomática.

El daño no era solo de navegación. Al ámbito se le pega su nombre detrás de la
consulta antes de incrustarla, y ese texto añadido acerca **todo** al corpus:
medido sobre las diez preguntas ajenas del conjunto de validación, el
recuperador rechaza 5 en el primer turno de una conversación y **0 en el
noveno**. «Hazme un resumen de la Segunda Guerra Mundial» pasa de cero a veinte
fragmentos por llevar ocho turnos detrás.

Por qué lo decide el modelo y no una regla
------------------------------------------
Porque no hay ninguna otra señal en los datos. Medido sobre el índice real:

* la titulación de los vecinos más próximos es ruido —«¿y en segundo?», que es
  un seguimiento legítimo, apunta a Geomática, y «¿cuál es la capital de
  Francia?» apunta a Mecánica—;
* las preguntas que cambian de tema caen en la misma banda de distancia que las
  ajenas (0,156–0,203 frente a 0,193–0,231), así que ningún umbral las separa;
* y comparar la frase con los doce nombres del catálogo ordena bien pero no
  decide: aplicado de extremo a extremo le asignó Geomática a «¿quieres ser mi
  novio?».

Una lista cerrada de fórmulas —«otra titulación», «qué más hay», «olvídalo»—
cubre lo que está escrito en ella y nada más. El turno que motivó todo esto
estaba en rumano.

Dónde está la raya
------------------
Esto **no** contradice que una instrucción no sea un control. Lo que se delega
es a qué titulación se acota la búsqueda, que es una ayuda a la recuperación: si
se equivoca, la respuesta es peor, no es falsa. Las tres barreras del sistema
—el suelo de pertinencia, la comprobación de centro ajeno y la retirada de la
respuesta que nombra una titulación inexistente— siguen siendo deterministas y
siguen ejecutándose después.

Y lo que el modelo escribe **no se cree: se comprueba** contra el catálogo del
índice, igual que IT-87 comprueba la respuesta. Cuando se inventó una titulación
—contestó «Grado en Administración y Dirección de Empresas» a una pregunta
ajena— la comprobación la rechazó sola.

Lo que sí se midió que no se puede hacer es dejarle **reescribir** la pregunta,
que es lo que recomienda la literatura: reescribió tres preguntas ajenas como
preguntas legítimas del dominio y las metió en el corpus a 0,0494, más cerca que
cualquier pregunta de dominio del conjunto de evaluación. El suelo mide el texto
que escribe el estudiante y solo ese. Se puede decidir **sobre** ese texto; no se
puede sustituirlo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Final

from tfg_uja.dialogo.generador import ErrorDelModelo, generar
from tfg_uja.text_cleaner import normalizar

#: Las cuatro respuestas que se admiten. Cada una se traduce a un camino de
#: recuperación que ya existía en el código: ``SIGUE`` deja el ámbito como
#: estaba, ``CAMBIA`` lo reapunta, ``TODAS`` es la rama de
#: :func:`tfg_uja.recuperador.pide_recomendacion` y ``NINGUNA`` deja la consulta
#: desnuda y sin filtro, que es la única condición en la que el suelo de
#: pertinencia mide lo que dice medir.
SIGUE: Final[str] = "SIGUE"
CAMBIA: Final[str] = "CAMBIA"
TODAS: Final[str] = "TODAS"
NINGUNA: Final[str] = "NINGUNA"

#: La quinta, que no es una decisión: es no haberla podido tomar. No la
#: devuelve el modelo, la pone la conversación cuando el decisor se rinde, y
#: existe para que quede escrita en el registro. Sin ella, un turno decidido y
#: un turno con el servidor caído se ven idénticos desde fuera, y el segundo se
#: confunde con el defecto que esta tarjeta corrige.
FALLO: Final[str] = "FALLO"

#: Cuánto de la respuesta anterior se le enseña. Enseñársela entera costaría
#: hasta 1.200 fichas por decisión ---más que todo el resto del prompt--- y no
#: aporta: la titulación de la que habla una respuesta aparece en sus primeras
#: líneas, porque las instrucciones de generación piden citar de dónde sale cada
#: dato. Con este recorte se acertaron los seis turnos del registro real.
LARGO_RESPUESTA_ANTERIOR: Final[int] = 420

#: Tope de la respuesta del modelo, en fichas. La respuesta válida más larga es
#: el nombre de titulación más largo del catálogo ---el doble grado internacional
#: con Schmalkalden, 103 caracteres--- que a unas 3,6 letras por ficha son unas
#: 29. Se deja en 40 para que no se corte: un nombre truncado sigue casando por
#: subcadena, pero «Doble Grado en Ingeniería Mecánica» es prefijo de dos
#: titulaciones distintas y la decisión se volvería ambigua sin necesidad.
TOPE_DECISION: Final[int] = 40

#: Longitud a partir de la cual se admite que lo escrito case por subcadena con
#: un nombre del catálogo. Por debajo, cualquier palabra suelta ---«grado»,
#: «doble»--- casaría con las doce.
LARGO_MINIMO_PARCIAL: Final[int] = 12

#: Veces que se le pide la decisión al modelo antes de darla por perdida.
#:
#: Dos, y sale de un caso real del 27/08/2026: con dos clientes hablando a la
#: vez con el mismo servidor de inferencia, la llamada de decisión se llevó un
#: 500 y el sistema cayó al mecanismo determinista **sin que nada lo dijera**.
#: Desde fuera eso se ve exactamente igual que el defecto que esta tarjeta
#: corrige ---la conversación se queda pegada a la titulación anterior---, así
#: que un tropiezo pasajero del servidor se lee como una regresión.
#:
#: Un reintento cuesta unos segundos en el único caso en que la alternativa es
#: responder de la titulación equivocada. Más de uno no: si el servidor está
#: caído de verdad, la generación va a fallar a continuación de todos modos.
INTENTOS: Final[int] = 2

#: Registro del módulo. Existe por el mismo motivo que el de
#: :mod:`tfg_uja.generador`: un mecanismo que se rinde en silencio no se puede
#: auditar, y aquí rendirse significa volver al comportamiento que la tarjeta
#: venía a corregir. Quien use la biblioteca decide dónde va y con qué nivel.
_registro: Final[logging.Logger] = logging.getLogger(__name__)


@dataclass(frozen=True)
class Decision:
    """Qué hay que buscar para responder al mensaje de este turno.

    Attributes:
        clase: Una de :data:`SIGUE`, :data:`CAMBIA`, :data:`TODAS` o
            :data:`NINGUNA`.
        titulaciones: Titulaciones del catálogo a las que se reapunta la
            búsqueda. Solo tiene contenido cuando ``clase`` es :data:`CAMBIA`.
    """

    clase: str
    titulaciones: list[str]


#: Lo que `Conversacion` espera recibir. Se pasa como función y no como
#: dependencia dura para que el módulo de la conversación siga sin saber que
#: existe un modelo generativo: sus pruebas inyectan una decisión fija y no
#: necesitan servidor, igual que las del indexador inyectan un incrustador
#: falso. Devolver ``None`` significa «no he podido decidir»; entonces la
#: conversación se queda con su mecanismo determinista.
Decisor = Callable[[str, list[str], "tuple[str, str] | None"], "Decision | None"]


def _bloque_ultimo_turno(ultimo_turno: tuple[str, str] | None) -> str:
    """El último turno completo, tal como se le enseña al modelo.

    La **respuesta** anterior entra aquí, y eso no contradice la regla de no
    meterla en el prompt de generación. Allí el peligro es que el modelo copie
    a la respuesta de ahora datos de la suya de antes; aquí lo único que sale es
    una etiqueta que se comprueba contra el catálogo y que no lee nadie.

    Y hace falta: es lo que permite sostener el sujeto cuando la titulación no
    la nombró ninguna pregunta sino el propio asistente, que es el caso que
    motivó IT-106. Sin este bloque, «da spune mi despre optiunile de la aceasta
    facultate» ---el turno 14 del registro real, en rumano--- se contestaba otra
    vez con la titulación anterior.

    Args:
        ultimo_turno: Par ``(pregunta, respuesta)`` del turno anterior, o
            ``None`` si este es el primer mensaje.

    Returns:
        El bloque del prompt, con un espacio delante para pegarse al final de
        la línea que abre el contexto, o cadena vacía si no hay turno anterior.
    """
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
    """Arma el texto con el que se le pide la decisión al modelo.

    El catálogo va entero y por delante, igual que en el prompt de generación:
    es lo que hace que el modelo solo pueda elegir entre titulaciones que
    existen, y lo que convierte su respuesta en algo comprobable.

    La opción ``SIGUE`` **solo se ofrece si hay ámbito**. Sin ella, cuando no se
    ha hablado todavía de ninguna titulación no hay nada a lo que seguir, y
    ofrecerla invitaba a contestar que sí a un mensaje que no continuaba nada.

    La redacción no es la primera que se escribió: se eligió midiendo tres, con
    el mismo material ---las siete formas de cambiar de tema, tres seguimientos
    y las diez preguntas ajenas del conjunto de validación---, porque cambiarle
    una frase a un prompt cambia lo que decide:

    * la que está aquí sale del atasco en 6 de 7, conserva los 3 seguimientos y
      etiqueta bien 9 de las 10 ajenas;
    * la misma con el bloque del turno anterior en su propio párrafo baja a
      5 de 7 sin ganar nada;
    * y añadirle a ``TODAS`` un «o dice qué le gusta o qué busca» ---que parece
      inofensivo y resuelve un caso--- **derrumba el rechazo de ajenas a 6 de
      10**, porque «me gusta el derecho penal, ¿qué carrera me pega?» encaja en
      esa frase palabra por palabra.

    La última es la que hay que recordar antes de retocar este texto.

    Args:
        pregunta: Mensaje del usuario, tal cual lo escribe.
        ambito: Titulaciones de las que se venía hablando. Puede estar vacío.
        ultimo_turno: Par ``(pregunta, respuesta)`` del turno anterior.
        catalogo: Titulaciones que declara el índice.

    Returns:
        El prompt completo, listo para enviar al modelo.
    """
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
    """Traduce lo que ha escrito el modelo, comprobándolo contra el catálogo.

    Nada de lo que escriba se usa sin resolverlo antes contra los nombres que
    declara el índice. Es la misma arquitectura con la que IT-87 comprueba la
    respuesta, aplicada a la consulta: el modelo propone y el catálogo dispone.

    **Lo que no se entiende se trata como :data:`NINGUNA`**, y no como
    :data:`SIGUE`, que sería quedarse con el ámbito anterior. Hay dos razones.
    La primera es que el caso real de respuesta ilegible fue el modelo
    contestando «Grado en Administración y Dirección de Empresas» a una pregunta
    ajena: nombrar una titulación que la Escuela no imparte es señal de que el
    mensaje va de otra cosa, no de que siga con la de antes. La segunda es que
    :data:`NINGUNA` deja la consulta desnuda y sin filtro, que es el camino en el
    que manda el suelo de pertinencia; es el estado neutro, no el peligroso.

    Args:
        salida: Lo que devolvió el modelo, tal cual.
        catalogo: Titulaciones que declara el índice.

    Returns:
        La decisión ya comprobada.
    """
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
    """Titulaciones del catálogo que la línea nombra.

    Se admite el punto y coma como separador aunque el prompt pida una sola
    titulación: cuando el modelo escribe dos, quedarse sin entender la línea
    entera sería peor que atender a las dos, y el filtro admite varias.

    Se admite también la coincidencia parcial, porque el modelo escribe
    «Ingeniería Mecánica» donde el catálogo dice «Grado en Ingeniería Mecánica».
    Si un nombre parcial casa con varias ---y pasa: «Ingeniería Mecánica» está
    dentro de tres títulos--- se devuelven todas, que es lo honesto: la
    respuesta era ambigua y el vector ordenará entre ellas.

    **El nombre exacto corta la búsqueda parcial**, y es la misma regla que
    :func:`tfg_uja.recuperador.resolver_titulacion`. Sin ella, escribir el
    nombre entero de un grado simple arrastraba a los dobles que lo contienen:
    «Grado en Ingeniería Mecánica» está dentro de «Doble Grado en Ingeniería
    Mecánica y Organización Industrial», así que nombrar dos titulaciones
    acotaba la búsqueda a cuatro. Es el mismo defecto de subcadena que
    :func:`nombrada_por_si_misma` resuelve para las respuestas.

    Args:
        linea: La primera línea de lo que escribió el modelo.
        catalogo: Titulaciones que declara el índice.

    Returns:
        Nombres del catálogo, en el orden del catálogo y sin repetir.
    """
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
    """Construye el decisor que consulta al modelo.

    Se devuelve una función y no una clase porque no hay estado que guardar: el
    ámbito y el turno anterior los aporta la conversación en cada llamada.

    **Un fallo del servidor no pierde el turno.** Si el modelo no contesta se
    devuelve ``None``, y la conversación se queda con su mecanismo determinista,
    que es lo que hacía antes de esta tarjeta. Una decisión de ámbito no merece
    tumbar una consulta que aún se puede responder.

    Args:
        catalogo: Titulaciones que declara el índice.
        modelo: Nombre del modelo en el servidor local.
        generador: Con qué se pide la respuesta. Se inyecta para poder probar el
            decisor entero sin servidor.

    Returns:
        La función que espera :class:`tfg_uja.conversacion.Conversacion`.
    """

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

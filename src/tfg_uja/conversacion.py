"""Estado de la conversación con el asistente (IT-106).

Lo que IT-37 dejó era lo mínimo para encadenar tres preguntas: pegar la
pregunta anterior delante de la actual antes de incrustarla. Probándolo a mano
aparecieron tres formas de romperlo, y las tres tienen la misma raíz: **pegar
texto no es entender de qué se habla**.

1. *El sujeto lo dice el asistente, no el estudiante.* «Me gustan los
   videojuegos» → el asistente recomienda Informática → «¿y qué asignaturas
   tiene en primero?». Ninguna **pregunta** nombró la titulación, así que no
   había nada que arrastrar y la consulta se fue a las doce.
2. *Nombrar una titulación no basta para sostenerse solo.* «Y en el grado de
   electrónica?» nombra una, así que IT-37 soltaba el arrastre y la incrustaba
   tal cual; pero «electrónica» suelta es un **tema**, no una pregunta, y
   recuperó guías de asignaturas en vez del plan de estudios.
3. *Concatenar mete ruido.* Arrastrar el texto de la pregunta anterior mete en
   el vector palabras de temas ya cerrados.

Aquí se cambia el enfoque. En vez de confiar en que el vector caiga donde toca,
la conversación **deduce la titulación de la que se habla y acota la búsqueda
con un filtro exacto**. El filtro no depende de que el modelo obedezca ni de
que la incrustación acierte: o el fragmento es de esa titulación o no lo es.

Todo lo que hace este módulo es determinista. Se descartó reescribir la
pregunta pidiéndoselo al modelo ---que es lo que hace la literatura--- por dos
motivos: cuesta una llamada más por consulta, y este proyecto ya tiene
documentado que un mecanismo que depende de que el modelo obedezca no es un
control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from tfg_uja.recuperador import palabras_distintivas
from tfg_uja.text_cleaner import normalizar, palabras

#: Turnos que se conservan. **Política de ventana:** al llenarse se descartan
#: las preguntas más antiguas, nunca el sujeto de la conversación, que ocupa
#: unas pocas palabras y es lo único que la pregunta de seguimiento necesita
#: de verdad. Las respuestas no se conservan en ningún caso: no entran en el
#: prompt desde IT-37, porque el modelo copiaba de ellas datos que ya no venían
#: a cuento. Así la conversación no puede desplazar al contexto recuperado, que
#: es lo que llenaba la ventana de 8.192 *tokens*.
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

#: Posiciones dentro del plan de estudios. **No dicen qué se pregunta, solo
#: cuál**, así que una pregunta que no aporte nada más que un ordinal sigue
#: siendo de seguimiento. Medido con las conversaciones derivadas del dataset:
#: tratando «¿y en segundo?» como pregunta que se sostiene sola, la unidad
#: buscada aparecía en el 48 % de los casos; heredando el predicado de la
#: pregunta anterior, en el 100 %.
ORDINALES: Final[frozenset[str]] = frozenset("""
    primer primero primera segundo segunda tercer tercero tercera cuarto
    cuarta quinto quinta ultimo ultima
    """.split())


def titulaciones_de_la_pregunta(pregunta: str, catalogo: list[str]) -> list[str]:
    """Titulaciones que la pregunta menciona, aunque sea con un nombre parcial.

    Se comparan las palabras distintivas de cada titulación con las de la
    pregunta: «electrónica» sitúa en las tres que la llevan en el nombre, y no
    en una elegida al azar. Devolver las tres es lo honesto, porque la pregunta
    de verdad es ambigua; el filtro las admite todas y el vector ordena.

    Args:
        pregunta: Pregunta tal cual la escribe el usuario.
        catalogo: Titulaciones que declara el índice.

    Returns:
        Nombres del catálogo mencionados, en el orden del catálogo.
    """
    distintivas = palabras_distintivas(catalogo)
    dichas = palabras(pregunta) & distintivas
    if not dichas:
        return []
    return [t for t in catalogo if palabras(t) & dichas]


def nombrada_por_si_misma(titulacion: str, texto: str, otras: list[str]) -> bool:
    """Si la titulación aparece por sí misma y no dentro del nombre de otra.

    El nombre de un grado simple está contenido en el de los dobles que lo
    incluyen: «Grado en Ingeniería Mecánica» es una subcadena literal de «Doble
    Grado en Ingeniería Mecánica y Organización Industrial». Buscar la
    subcadena a secas da por nombrado el grado simple en cuanto se menciona el
    doble, y eso bastó para cambiar el sujeto de una conversación entera hacia
    una titulación de la que nadie había hablado.

    Se resuelve contando en lugar de decidiendo por presencia: si el nombre
    aparece más veces de las que lo arrastran las titulaciones más largas que
    también están en el texto, es que en alguna de ellas se nombró solo.

    Args:
        titulacion: Nombre que se comprueba.
        texto: Texto normalizado en el que se busca.
        otras: Nombres del catálogo presentes en ese mismo texto.

    Returns:
        ``True`` si el nombre aparece al menos una vez fuera de otro más largo.
    """
    aguja = normalizar(titulacion)
    arrastradas = sum(
        texto.count(normalizar(o)) * normalizar(o).count(aguja)
        for o in otras
        if o != titulacion and aguja in normalizar(o)
    )
    return texto.count(aguja) > arrastradas


def titulaciones_de_la_respuesta(respuesta: str, catalogo: list[str]) -> list[str]:
    """Titulaciones que la respuesta del asistente nombra por su nombre entero.

    Aquí **no** se usan palabras distintivas, sino el nombre completo. Una
    respuesta larga menciona de pasada muchos términos, y bastaría con que
    citase «informática» dentro de una frase para cambiar el sujeto de la
    conversación. Que escriba el nombre oficial entero sí es señal de que está
    hablando de esa titulación.

    Que el nombre esté escrito no basta: tiene que estar escrito **por sí
    mismo**, y de eso se ocupa :func:`nombrada_por_si_misma`.

    Args:
        respuesta: Texto que devolvió el asistente.
        catalogo: Titulaciones que declara el índice.

    Returns:
        Nombres del catálogo que aparecen enteros, en el orden del catálogo.
    """
    dicho = normalizar(respuesta)
    presentes = [t for t in catalogo if normalizar(t) in dicho]
    return [t for t in presentes if nombrada_por_si_misma(t, dicho, presentes)]


#: Fórmulas con las que una pregunta se refiere a lo que acaba de decirse en
#: vez de nombrarlo. Son el rastro de que **recorta** el resultado anterior en
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
    """Dice si la pregunta afina el resultado anterior en vez de plantear tema.

    Sirve para decidir **qué predicado se hereda**. Una pregunta que recorta
    no puede ser la referencia de las siguientes, porque arrastraría su propio
    recorte a preguntas que ya no lo piden.

    Medido el 17/08/2026: «¿Y en el segundo?» heredó de «¿y cuántas **de esas**
    son optativas?». La consulta quedó dominada por «optativas», el listado de
    segundo curso no entró en el contexto y el modelo rellenó el hueco con
    **seis asignaturas que no existen**.

    No vale con mirar si empieza por «y». Medido el 18/08/2026 sobre la
    conversación real: «¿Y qué asignaturas tiene en primero?» empieza por «y»
    pero sí plantea tema, y descartarla dejaba a la siguiente heredando de
    «soy de bachillerato y me gustan los videojuegos», que no dice nada del
    plan de estudios. Lo que distingue a una de otra es la anáfora.

    Args:
        pregunta: Pregunta tal cual la escribe el usuario.

    Returns:
        ``True`` si se refiere a lo anterior en lugar de nombrarlo.
    """
    dicho = normalizar(pregunta)
    return any(anafora in dicho for anafora in ANAFORAS)


def contenido(pregunta: str, catalogo: list[str]) -> set[str]:
    """Palabras de la pregunta que dicen **qué** se pregunta.

    Se quitan las partículas y las palabras que solo nombran la titulación:
    lo que queda es el predicado. Si no queda nada, la pregunta no pregunta
    nada por sí misma, solo cambia el sujeto de la anterior.

    Args:
        pregunta: Pregunta tal cual la escribe el usuario.
        catalogo: Titulaciones que declara el índice.

    Returns:
        Las palabras con contenido temático.
    """
    # Aquí se quitan **todas** las palabras del catálogo, no solo las
    # distintivas: «grado» está en los doce nombres, así que no distingue
    # ninguna titulación, pero tampoco dice qué se pregunta. Dejarla dentro
    # hacía que «¿y en el grado de electrónica?» pareciera sostenerse sola.
    del_catalogo = {p for t in catalogo for p in palabras(t)}
    return palabras(pregunta) - PALABRAS_VACIAS - ORDINALES - del_catalogo


@dataclass(frozen=True)
class Consulta:
    """Lo que la conversación entrega al recuperador.

    Attributes:
        texto: Lo que se incrusta.
        ambito: Titulaciones a las que se acota la búsqueda. Vacío significa
            buscar en todo el corpus.
    """

    texto: str
    ambito: list[str]


@dataclass
class Conversacion:
    """Recuerda de qué se habla para que las preguntas de seguimiento funcionen.

    Attributes:
        catalogo: Titulaciones que declara el índice.
        turnos_recordados: Cuántas preguntas se conservan para el prompt.
    """

    catalogo: list[str]
    turnos_recordados: int = TURNOS_RECORDADOS
    _preguntas: list[str] = field(default_factory=list, init=False)
    _ambito: list[str] = field(default_factory=list, init=False)
    _predicado: str = field(default="", init=False)

    @property
    def ambito(self) -> list[str]:
        """Titulaciones de las que se está hablando ahora mismo."""
        return list(self._ambito)

    def preparar(self, pregunta: str) -> Consulta:
        """Convierte la pregunta en una consulta que se sostiene sola.

        Args:
            pregunta: Pregunta tal cual la escribe el usuario.

        Returns:
            El texto a incrustar y las titulaciones a las que acotar.
        """
        mencionadas = titulaciones_de_la_pregunta(pregunta, self.catalogo)
        ambito = mencionadas or self._ambito

        texto = pregunta
        if not contenido(pregunta, self.catalogo) and self._predicado:
            # La pregunta solo cambia el sujeto: el predicado es el de antes.
            # Se recupera de la última pregunta que sí decía qué se preguntaba,
            # y sin sus palabras de titulación, que ya no son las de ahora.
            # Se quitan solo las palabras **distintivas**, no todas las del
            # catálogo: «en» y «de» están en «Grado en Ingeniería...» y
            # quitarlas dejaba la frase descosida («tiene primero»).
            #
            # El ordinal heredado solo sobra **si la pregunta de ahora trae el
            # suyo**. Medido el 18/08/2026 con la conversación real: heredando
            # «¿y qué asignaturas tiene en primero?» entera, a «¿y en segundo?»
            # le seguían llegando los listados de *primer* curso; quitándolo
            # siempre, «¿y en el grado de electrónica?» perdía el curso del que
            # se venía hablando y dejaba de recuperar ningún plan.
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

        return Consulta(texto=texto, ambito=list(ambito))

    def anotar(self, pregunta: str, respuesta: str) -> None:
        """Registra un turno y actualiza de qué se está hablando.

        El sujeto se busca **también en la respuesta**, y esa es la corrección
        central de IT-106: en «me gustan los videojuegos» → «el Grado en
        Ingeniería Informática te encaja» → «¿y qué asignaturas tiene en
        primero?», la titulación no aparece en ninguna pregunta. Mirando solo
        las preguntas, el sistema no sabía de qué se hablaba y respondía de
        otra titulación con total seguridad.

        Args:
            pregunta: Lo que se preguntó.
            respuesta: Lo que contestó el asistente.
        """
        self._preguntas.append(pregunta)
        del self._preguntas[: -self.turnos_recordados]

        if contenido(pregunta, self.catalogo) and not recorta_lo_anterior(pregunta):
            self._predicado = pregunta

        nuevo = titulaciones_de_la_pregunta(
            pregunta, self.catalogo
        ) or titulaciones_de_la_respuesta(respuesta, self.catalogo)
        if nuevo:
            self._ambito = nuevo

    def preguntas(self) -> list[str]:
        """Preguntas que se le recuerdan al modelo, de más antigua a más nueva.

        Solo preguntas. Las respuestas no se devuelven nunca, para que una
        respuesta equivocada de un turno no pueda usarse como fuente en el
        siguiente: lo que no está en el prompt no se puede copiar.
        """
        return list(self._preguntas)

    def olvidar(self) -> None:
        """Vacía la conversación y el sujeto. Deja el objeto como recién creado."""
        self._preguntas.clear()
        self._ambito.clear()
        self._predicado = ""

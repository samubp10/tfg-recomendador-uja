"""Sugerencias de preguntas que el sistema sabe responder (Fase 3).

Los botones que acompañan a la conversación no se escriben a mano ni se le
piden al modelo: se deducen de lo que el índice contiene **para la titulación
de la que se está hablando**. Las dos alternativas fallan cada una por su
lado:

* una lista fija ofrece «¿qué menciones tiene?» en las siete titulaciones que
  no tienen ninguna ---los cinco dobles grados, Organización Industrial e
  Inteligencia Artificial y Ciberseguridad, contado sobre el corpus del
  19/08/2026, curso 2026-27---, y ahí la pregunta no la puede responder el
  corpus. Medido sobre ese índice: «¿Qué menciones ofrece el Grado en
  Ingeniería de Organización Industrial?», con el ámbito acotado a esa
  titulación, recupera cinco fragmentos y ninguno es de mención; son de plan
  de estudios, de salidas y de ficha. **Qué contesta el modelo con ese
  contexto no se ha medido aquí**, pero venga lo que venga no puede salir del
  corpus, porque el dato no está;
* pedírselas al modelo las inventa, que es justo lo que las tres barreras de
  restricción de dominio están ahí para impedir.

Así que aquí no se llama a ningún modelo. Se le pregunta al índice si existe
el fragmento que respalda cada pregunta, y la pregunta se ofrece solo si
existe. La consulta es de conteo, no de similitud: no hace falta incrustar
nada para saber si una titulación tiene salidas profesionales indexadas.
"""

from __future__ import annotations

from typing import Any, Final

# Se reutiliza el escapado del recuperador en vez de repetirlo: dos copias de
# la misma defensa acaban divergiendo, y esta compone la misma expresión SQL
# sobre la misma tabla.
from tfg_uja.recuperador import escapar

#: Cuántas sugerencias se ofrecen como mucho. Son botones bajo la
#: conversación: pasar de cuatro deja de ser un atajo y se convierte en un
#: menú que hay que leer.
MAXIMO: Final[int] = 4

#: Preguntas con las que se arranca una conversación. Las respaldan los
#: fragmentos de origen ``catalogo``, que son los tres que enumeran las
#: titulaciones de la Escuela, así que se ofrecen solo si el índice los trae:
#: un índice construido a partir de un ``chunks.json`` anterior a que el
#: fragmentador los emitiera no los tiene.
ARRANQUE_CATALOGO: Final[tuple[str, ...]] = (
    "¿Qué titulaciones puedo estudiar en la Escuela Politécnica Superior de Jaén?",
    "¿Qué dobles grados ofrece la Escuela Politécnica Superior de Jaén?",
)

#: La petición de consejo se ofrece siempre, y no depende de que exista un
#: fragmento concreto: el recuperador la reconoce y la trata aparte ---busca
#: con la consulta ampliada y sin aplicar el suelo de pertinencia---, de modo
#: que es la única pregunta que no se queda sin contexto por construcción.
#: El verbo «recomiendas» no es decorativo: es una de las palabras con las que
#: ``pide_recomendacion`` distingue esa petición.
PETICION_DE_CONSEJO: Final[str] = "No sé qué estudiar, ¿qué me recomiendas?"

#: Qué pregunta respalda cada origen, en el orden en que se ofrecen. Primero
#: el plan de estudios, que es de lo que más se pregunta en el conjunto de
#: evaluación, y la ficha al final porque es la única que existe en las doce
#: titulaciones y, por tanto, la que menos distingue a una de otra.
#:
#: Los nombres de origen son los que escribe el fragmentador, no una versión
#: abreviada: ``plan_de_estudios`` y ``ficha_titulacion``, no ``plan`` ni
#: ``ficha``. Escribir uno mal no da ningún error: solo deja de ofrecerse esa
#: pregunta, para siempre y en silencio.
#:
#: El artículo va dentro de la plantilla porque el nombre del catálogo no lo
#: trae, y sin él la pregunta queda mal escrita («¿Qué asignaturas tiene Grado
#: en Ingeniería Informática?»). Es «el» en las doce, que empiezan todas por
#: «Grado en» o «Doble Grado en».
POR_ORIGEN: Final[tuple[tuple[str, str], ...]] = (
    ("plan_de_estudios", "¿Qué asignaturas tiene el {titulacion}?"),
    ("mencion", "¿Qué menciones ofrece el {titulacion}?"),
    ("salidas", "¿Qué salidas profesionales tiene el {titulacion}?"),
    (
        "ficha_titulacion",
        "¿Cuántas asignaturas tiene el {titulacion} y cómo se reparten por curso?",
    ),
)


def _hay(tabla: Any, filtro: str) -> bool:
    """Dice si el índice guarda algún fragmento que case con el filtro.

    Se cuenta en vez de traer las filas y mirarlas porque una consulta que
    devuelve filas necesita un límite, y un límite corto se traga en silencio
    justo lo que se está buscando: de los 277 fragmentos de Informática solo
    dos son de salidas profesionales.

    Args:
        tabla: Tabla abierta con :func:`tfg_uja.recuperador.abrir_indice`.
        filtro: Expresión SQL de filtrado.

    Returns:
        ``True`` si hay al menos un fragmento.
    """
    return tabla.count_rows(filtro) > 0


def _de_una(tabla: Any, titulacion: str) -> list[str]:
    """Preguntas respaldadas por lo que el índice tiene de una titulación.

    Args:
        tabla: Tabla abierta con :func:`tfg_uja.recuperador.abrir_indice`.
        titulacion: Nombre tal como lo declara el catálogo del índice.

    Returns:
        Las preguntas cuyo origen aparece en esa titulación, en el orden de
        :data:`POR_ORIGEN`.
    """
    # `array_has_any` casa por elemento exacto, igual que en el recuperador:
    # con una coincidencia de subcadena, «Grado en Ingeniería Eléctrica»
    # arrastraría los fragmentos de sus dos dobles grados y ofrecería sus
    # menciones, que el grado simple sí tiene y el doble no.
    suya = f"array_has_any(grados, ['{escapar(titulacion)}'])"
    return [
        pregunta.format(titulacion=titulacion)
        for origen, pregunta in POR_ORIGEN
        if _hay(tabla, f"{suya} AND origen = '{escapar(origen)}'")
    ]


def _de_arranque(tabla: Any) -> list[str]:
    """Preguntas con las que empezar cuando no se habla de nada todavía.

    Args:
        tabla: Tabla abierta con :func:`tfg_uja.recuperador.abrir_indice`.

    Returns:
        Las del catálogo, si el índice lo trae, y la petición de consejo.
    """
    catalogo = list(ARRANQUE_CATALOGO) if _hay(tabla, "origen = 'catalogo'") else []
    return (catalogo + [PETICION_DE_CONSEJO])[:MAXIMO]


def sugerencias_para(tabla: Any, ambito: list[str], catalogo: list[str]) -> list[str]:
    """Preguntas que ofrecerle al estudiante en el punto en que va el diálogo.

    Con **una** titulación en el ámbito se ofrece lo que el índice tenga de
    ella, y nada más. Con **varias** ---que es lo que pasa cuando el
    estudiante escribe «eléctrica» y eso resuelve al grado simple y a sus dos
    dobles--- se ofrece la primera pregunta respaldada de cada una. Se
    descartaron las otras dos salidas: dar las cuatro preguntas de una de
    ellas es elegir por el estudiante cuál era, y ofrecer una comparación
    («¿en qué se diferencian X e Y?») no la respalda ningún fragmento, porque
    en el corpus no hay ningún texto que compare dos titulaciones y la
    respuesta saldría de que el modelo las junte por su cuenta. Una pregunta
    por titulación, además, sirve para deshacer la ambigüedad: al pulsar una,
    el ámbito se queda en esa sola.

    Args:
        tabla: Tabla abierta con :func:`tfg_uja.recuperador.abrir_indice`.
        ambito: Titulaciones de las que se está hablando, ya resueltas contra
            el catálogo por :class:`tfg_uja.conversacion.Conversacion`.
        catalogo: Titulaciones que declara el índice, de
            :func:`tfg_uja.recuperador.catalogo_del_indice`.

    Returns:
        Como mucho :data:`MAXIMO` preguntas, todas respondibles con este
        índice. Nunca lanza: quedarse sin sugerencias que ofrecer no es un
        error, es una conversación en la que no hay atajo que proponer.
    """
    # Solo pasan los nombres que el propio índice declara, por lo mismo que
    # `resolver_titulacion` obliga a resolver antes de filtrar: lo que se
    # interpola en la expresión SQL no puede ser texto de fuera, y un nombre
    # que no está en el catálogo no tiene ni un fragmento, así que todas sus
    # preguntas serían un rechazo garantizado.
    conocidas = [t for t in ambito if t in catalogo]
    if not conocidas:
        return _de_arranque(tabla)
    if len(conocidas) == 1:
        return _de_una(tabla, conocidas[0])[:MAXIMO]
    return [p for t in conocidas for p in _de_una(tabla, t)[:1]][:MAXIMO]

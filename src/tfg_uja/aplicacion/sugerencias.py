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

**La mitad de los huecos es siempre de otras titulaciones.** Ofrecer las
cuatro preguntas de la titulación de la que se está hablando da la impresión
de que el asistente solo conoce esa ---que es lo que pasó al probarlo con
Informática---, y además le cierra el abanico justo a quien se supone que lo
usa: alguien que todavía no sabe qué quiere estudiar. Así que dos huecos son
para el ámbito y dos para titulaciones de fuera, con su nombre delante, que
son las que enseñan que hay doce y no una.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from itertools import islice
from typing import Any, Final, TypeVar

from tfg_uja.dialogo.recuperador import escapar

#: Cuántas sugerencias se ofrecen como mucho. Son botones bajo la
#: conversación: pasar de cuatro deja de ser un atajo y se convierte en un
#: menú que hay que leer.
MAXIMO: Final[int] = 4

#: Cuántos de esos huecos se reservan a lo que se está hablando. El reparto es
#: por la mitad, y el motivo de que no sea mayor está en el docstring del
#: módulo: con los cuatro huecos ocupados por una sola titulación, el
#: asistente parece saber solo de ella.
DEL_AMBITO: Final[int] = 2

#: Preguntas con las que se arranca una conversación. Las respaldan los
#: fragmentos de origen ``catalogo``, que son los tres que enumeran las
#: titulaciones de la Escuela, así que se ofrecen solo si el índice los trae:
#: un índice construido a partir de un ``chunks.json`` anterior a que el
#: fragmentador los emitiera no los tiene. Se enseña una de las dos, y cuál
#: depende del desplazamiento.
ARRANQUE_CATALOGO: Final[tuple[str, ...]] = (
    "¿Qué titulaciones puedo estudiar en la Escuela Politécnica Superior de Jaén?",
    "¿Qué dobles grados ofrece la Escuela Politécnica Superior de Jaén?",
)

#: La petición de consejo se ofrece siempre al arrancar, y no depende de que
#: exista un fragmento concreto: el recuperador la reconoce y la trata aparte
#: ---busca con la consulta ampliada y sin aplicar el suelo de pertinencia---,
#: de modo que es la única pregunta que no se queda sin contexto por
#: construcción. El verbo «recomiendas» no es decorativo: es una de las
#: palabras con las que ``pide_recomendacion`` distingue esa petición.
PETICION_DE_CONSEJO: Final[str] = "No sé qué estudiar, ¿qué me recomiendas?"

#: El banco de preguntas: qué fragmento respalda a cada una. La condición se
#: encadena con la de la titulación, así que cada pregunta se ofrece solo
#: donde el índice tiene con qué responderla; ninguna está aquí sin haberse
#: contado antes contra el índice completo. Entre paréntesis, en cuántas de
#: las doce titulaciones hay respaldo (corpus del 19/08/2026, curso 2026-27).
#:
#: El orden importa dos veces. Es el orden en que se ofrecen, y es también el
#: que hace que dos sugerencias seguidas no hablen de lo mismo: van alternando
#: de asunto, porque el plan de estudios, sus cursos y sus tipos de asignatura
#: darían si no cuatro maneras de preguntar por la lista de asignaturas.
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
    """La misma secuencia, empezando por otro sitio.

    Es lo que hace que las sugerencias varíen entre un turno y el siguiente
    sin sortearlas: con la misma entrada sale siempre lo mismo, que es lo que
    permite escribir una prueba que compruebe cuáles salen. Un ``random`` sin
    semilla daría variedad y ninguna forma de comprobarla.

    Args:
        secuencia: Lo que se rota.
        desplazamiento: Por cuántos puestos. Puede ser mayor que la longitud.

    Returns:
        Los mismos elementos, en el mismo orden circular, empezando por el que
        toque. Lista vacía si la secuencia lo está.
    """
    corte = desplazamiento % len(secuencia) if secuencia else 0
    return list(secuencia[corte:]) + list(secuencia[:corte])


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


def _preguntas(tabla: Any, titulacion: str, desplazamiento: int) -> Iterator[str]:
    """Va soltando las preguntas que el índice respalda para una titulación.

    Devuelve un iterador y no una lista porque casi siempre se le pide solo la
    primera o las dos primeras: así se dejan de consultar las plantillas que
    ya no se van a ofrecer, en vez de comprobar las diez para tirar ocho.

    Args:
        tabla: Tabla abierta con :func:`tfg_uja.recuperador.abrir_indice`.
        titulacion: Nombre tal como lo declara el catálogo del índice.
        desplazamiento: Por dónde empezar el banco de plantillas.

    Yields:
        Las preguntas con respaldo, en el orden rotado de :data:`PLANTILLAS`.
    """
    # `array_has_any` casa por elemento exacto, igual que en el recuperador:
    # con una coincidencia de subcadena, «Grado en Ingeniería Eléctrica»
    # arrastraría los fragmentos de sus dos dobles grados y ofrecería sus
    # menciones, que el grado simple sí tiene y el doble no.
    suya = f"array_has_any(grados, ['{escapar(titulacion)}'])"
    for condicion, pregunta in _rotar(PLANTILLAS, desplazamiento):
        if _hay(tabla, f"{suya} AND {condicion}"):
            yield pregunta.format(titulacion=titulacion)


def _del_ambito(tabla: Any, conocidas: list[str], desplazamiento: int) -> list[str]:
    """Preguntas de las titulaciones de las que se está hablando.

    Los huecos reservados se reparten entre ellas: si el ámbito es una sola,
    se lleva los dos; si son varias ---lo que pasa cuando el estudiante
    escribe «eléctrica» y eso resuelve al grado simple y a sus dos dobles---,
    va una de cada, que además sirve para deshacer la ambigüedad, porque al
    pulsar una el ámbito se queda en esa sola.

    Args:
        tabla: Tabla abierta con :func:`tfg_uja.recuperador.abrir_indice`.
        conocidas: Titulaciones del ámbito, ya validadas contra el catálogo.
        desplazamiento: Por dónde empezar el banco de plantillas.

    Returns:
        Como mucho :data:`DEL_AMBITO` preguntas.
    """
    cada_una = max(1, DEL_AMBITO // len(conocidas))
    return [
        pregunta
        for indice, titulacion in enumerate(conocidas)
        for pregunta in islice(
            _preguntas(tabla, titulacion, desplazamiento + indice), cada_una
        )
    ][:DEL_AMBITO]


def _de_arranque(tabla: Any, desplazamiento: int) -> list[str]:
    """Preguntas con las que empezar cuando no se habla de nada todavía.

    Args:
        tabla: Tabla abierta con :func:`tfg_uja.recuperador.abrir_indice`.
        desplazamiento: Cuál de las preguntas de catálogo toca.

    Returns:
        Una del catálogo, si el índice lo trae, y la petición de consejo.
    """
    catalogo = _rotar(ARRANQUE_CATALOGO, desplazamiento)
    respaldadas = catalogo[:1] if _hay(tabla, "origen = 'catalogo'") else []
    return respaldadas + [PETICION_DE_CONSEJO]


def _de_otras(
    tabla: Any, otras: list[str], desplazamiento: int, cuantas: int
) -> list[str]:
    """Una pregunta de cada una de otras titulaciones, para abrir el abanico.

    Cada titulación estrena el banco por un sitio distinto ---se le suma su
    posición al desplazamiento---, porque si no las dos sugerencias de fuera
    saldrían con la misma plantilla y la lista parecería un formulario:
    «¿Qué asignaturas tiene el X?», «¿Qué asignaturas tiene el Y?».

    Args:
        tabla: Tabla abierta con :func:`tfg_uja.recuperador.abrir_indice`.
        otras: Titulaciones del catálogo que no están en el ámbito.
        desplazamiento: Por dónde empezar, tanto la lista de titulaciones como
            el banco de plantillas.
        cuantas: Cuántas preguntas hacen falta.

    Returns:
        Hasta ``cuantas`` preguntas, cada una de una titulación distinta.
    """
    elegidas: list[str] = []
    for indice, titulacion in enumerate(_rotar(otras, desplazamiento)):
        if len(elegidas) >= cuantas:
            break
        elegidas += islice(_preguntas(tabla, titulacion, desplazamiento + indice), 1)
    return elegidas


def sugerencias_para(
    tabla: Any, ambito: list[str], catalogo: list[str], desplazamiento: int = 0
) -> list[str]:
    """Preguntas que ofrecerle al estudiante en el punto en que va el diálogo.

    Salen siempre de varias titulaciones: :data:`DEL_AMBITO` huecos para
    aquello de lo que se está hablando ---o, si no se habla de nada todavía,
    el catálogo y la petición de consejo--- y el resto para titulaciones de
    fuera del ámbito.

    Los botones no proponen comparaciones de forma automática. RU-04 sí las
    atiende cuando el estudiante las pide: el recuperador trae evidencia de
    cada titulación por separado y el generador las contrasta. Elegir aquí dos
    grados al azar produciría una sugerencia poco relacionada con el diálogo.

    Args:
        tabla: Tabla abierta con :func:`tfg_uja.recuperador.abrir_indice`.
        ambito: Titulaciones de las que se está hablando, ya resueltas contra
            el catálogo por :class:`tfg_uja.conversacion.Conversacion`.
        catalogo: Titulaciones que declara el índice, de
            :func:`tfg_uja.recuperador.catalogo_del_indice`.
        desplazamiento: Por dónde empezar a recorrer el banco de preguntas y
            la lista de titulaciones. Sirve para que dos turnos seguidos no
            ofrezcan lo mismo; quien llama puede pasarle el número de turno.
            Con el mismo valor sale siempre la misma lista, que es lo que
            permite comprobarla en una prueba.

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
    if conocidas:
        propias = _del_ambito(tabla, conocidas, desplazamiento)
    else:
        propias = _de_arranque(tabla, desplazamiento)
    otras = [t for t in catalogo if t not in conocidas]
    return propias + _de_otras(tabla, otras, desplazamiento, MAXIMO - len(propias))

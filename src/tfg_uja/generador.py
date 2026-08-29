"""Generación de la respuesta a partir del contexto recuperado (IT-37).

Cierra el recorrido: la pregunta llega, :mod:`tfg_uja.recuperador` trae los
fragmentos pertinentes y aquí se arma el texto que lee el modelo y se le pide
la respuesta.

El **diseño fino del prompt es IT-34**, y el **guardarraíl de dominio, IT-87**.
Lo que hay aquí es lo que el recorrido necesita para funcionar de extremo a
extremo, con dos decisiones que no son de redacción sino de arquitectura:

* **El contexto va identificado.** Cada fragmento entra con el nombre de su
  unidad y su titulación, no como un montón de texto anónimo, para que la
  respuesta pueda decir de dónde sale cada dato y para que el modelo no mezcle
  asignaturas.
* **El contexto va ordenado por unidad, no por distancia.** El recuperador
  entrega los fragmentos de más a menos próximo, y una unidad partida en varios
  llega intercalada con otras. Preguntado por las asignaturas de Informática,
  el listado del plan llegaba en el orden 3, optativas, 2, 1, y la respuesta
  reproducía ese orden: empezaba por la mitad de la lista y volvía al principio
  más abajo. Aquí se vuelven a juntar las partes de cada unidad y se ponen en
  su orden.
* **Cada parte dice cuál es.** Las tres partes del listado de obligatorias de
  Informática repiten el mismo encabezado, «En total son 50», y ninguna dice de
  cuál se trata. Si llega una sola, el modelo lee que son cincuenta, ve once y
  presenta once como si fueran las cincuenta, sin ninguna señal de que le falta
  contexto.
* **La ventana se declara.** El valor por defecto del servidor es de cientos de
  miles de *tokens*, y con él el modelo no cabe entero en una tarjeta de 6 GB:
  se reparte con la CPU y rinde a un tercio. Medido, no supuesto.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Final

from tfg_uja.chunker import ORDEN_CURSOS
from tfg_uja.recuperador import Fragmento
from tfg_uja.text_cleaner import normalizar, palabras
from tfg_uja.verificacion import (
    Atributos,
    atributos_del_contexto,
    corregir_atributos,
    titulaciones_inventadas,
)

#: Registro del módulo. Existe solo para dejar constancia de las respuestas
#: retiradas: una barrera que descarta en silencio no se puede auditar, y la
#: cifra de cuántas veces salta es lo que dice si está haciendo algo o si
#: estorba. Quien use la biblioteca decide dónde va y con qué nivel.
_registro: Final[logging.Logger] = logging.getLogger(__name__)

#: Servidor de inferencia local. No se consulta ningún servicio externo: el
#: sistema tiene que poder ejecutarse entero en el equipo del autor.
SERVIDOR: Final[str] = "http://127.0.0.1:11434"

#: Ventana de contexto, en *tokens*. Dimensionada para lo que arma el sistema
#: ---diez fragmentos de 900 caracteres, más las instrucciones y la respuesta---
#: y no para el máximo que admita el modelo: con la ventana por defecto el
#: caché no cabe en la tarjeta y expulsa parte del modelo a la CPU.
VENTANA: Final[int] = 8192

#: Tope de la respuesta. Acota lo que puede tardar y evita que un modelo
#: locuaz convierta una consulta de chat en un minuto de espera.
#:
#: Dimensionado sobre la respuesta más larga que el corpus puede exigir: las 67
#: asignaturas de Ingeniería Informática, con sus créditos, ocupan 2.819
#: caracteres, que a razón de unos 3,6 caracteres por *token* en español son
#: unos 783. Con el tope anterior, de 400, esa respuesta se cortaba a mitad de
#: palabra, y el corte no era del modelo sino nuestro.
#:
#: Se deja en 1.200 y no en los 783 justos porque una respuesta útil no es el
#: listado pelado: lleva una frase de entrada, separa obligatorias de optativas
#: y cierra con algo. Ese margen es el que evita que se corte la última línea,
#: que es justo donde se notaba.
TOPE_RESPUESTA: Final[int] = 1200

#: Cuánto se espera una respuesta antes de darla por perdida, en segundos. No
#: es un criterio de calidad ---el tiempo se mide aparte---, sino el punto a
#: partir del cual se asume que el modelo se ha colgado: diez minutos para una
#: respuesta de mil doscientos *tokens* no es lentitud, es que no va a llegar.
ESPERA_MAXIMA: Final[int] = 600

#: Mensaje de sistema que se manda con cada petición. **Su función no es dar
#: instrucciones ---esas van en :data:`INSTRUCCIONES`--- sino tapar el que trae
#: cada modelo de fábrica.**
#:
#: Medido el 18/08/2026: al no mandar ninguno, Ollama aplica el de la plantilla
#: del modelo, y cada candidato trae el suyo. Preguntados «¿quién eres?»,
#: ministral-3 contestó «un modelo creado por Mistral AI» y gemma3 «entrenado
#: por Google», sin que el proyecto hubiera escrito eso en ninguna parte. El de
#: ministral-3 ocupa más de mil palabras, le hace creer que es «Le Chat», le
#: manda usar herramientas y le dice que pida aclaraciones cuando la pregunta
#: sea ambigua ---lo contrario de lo que pide este sistema.
#:
#: Comparar modelos así no mide los modelos: mide además el texto que cada uno
#: lleva escondido. Un `system` vacío no sirve, porque Ollama lo trata como
#: ausente y vuelve a poner el de la plantilla; hace falta uno con contenido.
SISTEMA: Final[str] = (
    "Eres un asistente que responde en español siguiendo las instrucciones "
    "del mensaje que recibes. No tienes herramientas ni acceso a internet."
)

#: Instrucciones del sistema. La regla que las ordena es que el sistema
#: prefiere callar a inventar: un estudiante va a decidir su carrera con esto.
INSTRUCCIONES: Final[str] = (
    "Eres un asistente que informa sobre las titulaciones de la Escuela "
    "Politécnica Superior de Jaén, de la Universidad de Jaén.\n"
    "Respondes a estudiantes que están decidiendo qué carrera estudiar, así "
    "que escribes claro y sin tecnicismos innecesarios.\n\n"
    "Reglas:\n"
    "- Usa ÚNICAMENTE la información del CONTEXTO. No añadas datos que no "
    "estén ahí, aunque los conozcas.\n"
    "- Si el contexto no contiene la respuesta, dilo con claridad en lugar de "
    "suponerla.\n"
    "- Si una asignatura aparece sin contenido de guía, di que su guía no está "
    "publicada; no es lo mismo que no exista la asignatura.\n"
    "- Al enumerar asignaturas, agrúpalas por curso y termina siempre con las "
    "optativas, que no tienen curso asignado. No te dejes ningún grupo.\n"
    "- Si hay un ÁMBITO declarado, responde sobre la titulación o las "
    "titulaciones que enumera. Varias asignaturas se imparten en más de una, "
    "y el contexto las nombra todas; menciónalo si viene al caso, pero no "
    "introduzcas otra titulación.\n"
    "- Si la pregunta compara varias titulaciones, deja claro a cuál "
    "corresponde cada dato y no declares una diferencia que el CONTEXTO no "
    "muestre.\n"
    "- Las PREGUNTAS ANTERIORES sirven solo para entender a qué se refiere la "
    "pregunta actual. Todos los datos salen del CONTEXTO.\n"
    "- Cita la asignatura o la titulación de la que sale cada dato.\n"
    "- No recomiendes ninguna titulación que no aparezca en el CONTEXTO ni en "
    "la lista de titulaciones de la Escuela.\n"
    "- Al enumerar, escribe el nombre y los créditos de cada asignatura y nada "
    "más. No la describas si no te lo piden.\n"
    "- Si el contexto trae listas de dos itinerarios de un doble grado, no las "
    "mezcles: responde con la que pide la pregunta y di cuál es.\n"
    "- Tutea al estudiante y escribe cercano y directo."
)

#: Cuántas preguntas anteriores se le recuerdan al modelo. Son **preguntas**,
#: no respuestas: ver :func:`_conversacion`.
TURNOS_EN_EL_PROMPT: Final[int] = 3


class ErrorDelModelo(RuntimeError):
    """El servidor de inferencia no ha podido responder.

    Existe para que quien llama pueda distinguir «el modelo ha fallado» de un
    fallo del propio sistema, y decidir qué hacer. El caso real que la motivó,
    el 18/08/2026: descargando un modelo de 9 GB mientras se cargaba uno de 7B,
    el servidor devolvió un 500 por falta de memoria y la excepción sin capturar
    **se llevó por delante la sesión de pruebas entera**, con su conversación.
    Una herramienta para probar a mano no puede perder el trabajo por un fallo
    pasajero del servidor.
    """


def ordenar_contexto(fragmentos: list[Fragmento]) -> list[Fragmento]:
    """Reagrupa las partes de cada unidad y las pone en su orden.

    El recuperador ordena por distancia, que es lo correcto para decidir **qué**
    entra en el contexto pero no para decidir **en qué orden** se lee. Una
    unidad partida en tres llega con sus partes separadas por fragmentos de
    otras unidades, y el modelo redacta siguiendo el orden en que lo recibe.

    Cada unidad conserva el sitio que le da su fragmento más próximo, de modo
    que la relevancia sigue mandando entre unidades; lo único que cambia es que
    los trozos de una misma unidad viajan juntos y en orden.

    Args:
        fragmentos: Fragmentos recuperados, en cualquier orden.

    Returns:
        Los mismos fragmentos, agrupados por unidad y ordenados dentro de ella.
    """
    mejor: dict[tuple[str, str], float] = {}
    for f in fragmentos:
        clave = (f.nombre, f.origen)
        mejor[clave] = min(mejor.get(clave, f.distancia), f.distancia)

    # Los listados del plan se leen en el orden en que se cursan, no por
    # proximidad. Medido: con el orden por distancia, las optativas caían entre
    # los cursos segundo y primero, y el modelo enumeró los cuatro cursos y se
    # dejó las diecisiete optativas fuera aunque las tenía delante.
    #
    # El ancla es **por titulación**, no una sola para todos los listados. Con
    # una sola, los cursos se ordenaban entre sí ignorando de qué titulación
    # eran, y las titulaciones quedaban intercaladas: medido el 17/08/2026, a
    # «¿y en el segundo?» el listado correcto llegaba el octavo de dieciocho,
    # detrás de cinco listados de primer curso de otras titulaciones, y el
    # modelo contestó por un doble grado que no se le había preguntado. Así
    # cada titulación viaja entera y en orden, y entre titulaciones sigue
    # mandando la proximidad.
    anclas: dict[tuple[str, ...], float] = {}
    for f in fragmentos:
        if f.origen != "plan_de_estudios":
            continue
        titulacion = tuple(f.grados)
        distancia = mejor[(f.nombre, f.origen)]
        anclas[titulacion] = min(anclas.get(titulacion, distancia), distancia)

    def orden(f: Fragmento) -> tuple[float, int, str, int]:
        if f.origen == "plan_de_estudios":
            return (
                anclas[tuple(f.grados)],
                _curso_del_listado(f.nombre),
                f.nombre,
                f.chunk_index,
            )
        return (mejor[(f.nombre, f.origen)], 0, f.nombre, f.chunk_index)

    return sorted(fragmentos, key=orden)


def _curso_del_listado(nombre: str) -> int:
    """Sitúa un listado del plan en el curso que enuncia su propio nombre.

    El fragmentador los llama «Asignaturas obligatorias de primer curso del…»,
    así que el curso está en el nombre y no hace falta una columna nueva en el
    índice para ordenarlos. Los que no nombran ninguno ---las optativas, que no
    tienen curso publicado--- van al final.

    Args:
        nombre: Nombre de la unidad, tal como lo compone el fragmentador.

    Returns:
        Posición del curso, o un valor mayor que cualquiera si no lo nombra.
    """
    bajo = nombre.lower()
    for posicion, ordinal in enumerate(ORDEN_CURSOS, start=1):
        if f"de {ordinal}" in bajo:
            return posicion
    return len(ORDEN_CURSOS) + 1


def _etiqueta(fragmento: Fragmento) -> str:
    """Compone la línea que encabeza un fragmento dentro del contexto.

    **No lleva número de parte, y se quitó a la vista de dos medidas.** Se puso
    para que el modelo supiera cuándo le faltaba un trozo de una lista, y no lo
    consiguió: aun con una regla explícita prohibiéndolo, se lo contó al usuario
    dos veces, la segunda inventándose una asignatura llamada «Sistemas
    inteligentes de información (parte 3 de 4)» y afirmando que su guía no
    estaba publicada. Es el mismo patrón que las titulaciones inventadas: una
    instrucción no basta para impedir un comportamiento.

    Además, lo que motivó la marca ---un listado de cincuenta asignaturas
    partido en tres tercios alfabéticos--- lo resolvió IT-105 de raíz, partiendo
    los listados por curso. El aviso costaba más de lo que evitaba.

    **Tampoco lleva número de orden**, por lo mismo y con una medida más. El
    número servía para citar, pero el modelo no cita fragmentos: cita
    asignaturas, que es lo que le piden las instrucciones. Lo único que hizo
    fue escaparse tal cual a la respuesta de un estudiante ---«...según el
    contexto ([20])»---, que es una referencia interna del sistema y no
    significa nada para quien la lee. Tercera vez que un dato puesto en el
    encabezado para uso del modelo acaba en la pantalla del usuario.

    Args:
        fragmento: Fragmento que se va a encabezar.

    Returns:
        La línea de encabezado, sin el texto del fragmento.
    """
    return f"{fragmento.nombre} — {', '.join(fragmento.grados)}"


#: Lo que se responde cuando la recuperación no ha traído nada pertinente.
#: Es texto fijo y no una respuesta del modelo, a propósito: ver
#: :func:`responder`.
RESPUESTA_SIN_CONTEXTO: Final[str] = (
    "No he encontrado información sobre eso en la web de la Escuela "
    "Politécnica Superior de Jaén. Puedo ayudarte con las titulaciones que "
    "se imparten allí: sus asignaturas, qué se estudia en cada una y qué "
    "salidas profesionales tienen. ¿Sobre cuál te gustaría saber?"
)

#: Con lo que se responde cuando la comprobación posterior encuentra una
#: titulación que no existe. Se retira la respuesta entera y no solo el nombre
#: inventado: el estudiante lee una lista, no una nota al pie, y una
#: recomendación falsa entre tres verdaderas se lee con la misma confianza que
#: las otras tres.
RESPUESTA_TITULACION_INVENTADA: Final[str] = (
    "No puedo darte esa respuesta: al redactarla he nombrado titulaciones que "
    "no se imparten en la Escuela Politécnica Superior de Jaén. Prueba a "
    "preguntármelo de otra forma, o pídeme la lista de las que sí se imparten."
)

#: Con lo que se abre la conversación. Un saludo no es una pregunta fallida:
#: es la primera línea que escribe casi cualquiera, y se aprovecha para decir
#: de qué sabe el sistema en vez de para decir que no sabe.
RESPUESTA_SALUDO: Final[str] = (
    "¡Hola! Te puedo ayudar con las titulaciones de la Escuela Politécnica "
    "Superior de Jaén: qué grados y dobles grados se estudian allí, qué "
    "asignaturas tiene cada uno y en qué curso se dan, qué se ve en cada "
    "asignatura y a qué se puede dedicar uno al terminar.\n\n"
    "Pregúntame por la titulación que te interese, o por lo que te gustaría "
    "estudiar y te digo cuáles encajan."
)

#: Con lo que se cierra. Contestar «no he encontrado información sobre eso» a
#: un «gracias» es el mismo despropósito que contestárselo a un «hola».
RESPUESTA_DESPEDIDA: Final[str] = (
    "¡De nada! Si te surge cualquier otra duda sobre las titulaciones de la "
    "Escuela Politécnica Superior de Jaén, aquí estoy."
)

#: Vocabulario con el que se puede escribir un mensaje entero sin preguntar
#: nada. Es una lista **cerrada** y se exige que **todas** las palabras del
#: mensaje estén en ella, de modo que «hola, ¿qué asignaturas tiene
#: Informática?» no se toma por un saludo y sigue su camino normal.
_CORTESIA: Final[frozenset[str]] = frozenset(
    {
        "hola",
        "buenas",
        "buenos",
        "dias",
        "tardes",
        "noches",
        "saludos",
        "saludo",
        "hello",
        "hi",
        "hallo",
        "hey",
        "ey",
        "que",
        "tal",
        "como",
        "estas",
        "va",
        "muy",
        "bien",
        "gracias",
        "muchas",
        "mil",
        "adios",
        "chao",
        "hasta",
        "luego",
        "pronto",
        "manana",
        "vale",
        "ok",
        "nada",
        "por",
        "favor",
        "un",
        "una",
        "y",
        "de",
        "a",
        "eres",
        "quien",
        "todo",
    }
)

#: Las que además tienen que aparecer para que el mensaje sea un saludo. Sin
#: esta condición, un resto de frase como «vale» o «y a mí» entraría por ser
#: todo cortesía.
#:
#: Las tres últimas no son españolas, y entran porque un estudiante abre en el
#: idioma que le sale: medido el 17/08/2026, «Hallo» cayó en la respuesta de
#: contexto vacío y se llevó un «no he encontrado información sobre eso». Lo
#: que se reconoce es la apertura, no el idioma: el asistente sigue
#: respondiendo en español.
_SALUDO: Final[frozenset[str]] = frozenset(
    {"hola", "buenas", "buenos", "saludos", "hey", "ey", "hello", "hi", "hallo"}
)

#: Y las que lo convierten en una despedida o un agradecimiento.
_DESPEDIDA: Final[frozenset[str]] = frozenset(
    {"gracias", "adios", "chao", "hasta", "luego", "pronto"}
)


def cortesia(pregunta: str) -> str | None:
    """Devuelve la respuesta fija si el mensaje es solo cortesía.

    Un «hola» no recupera nada, porque no se parece a ningún fragmento del
    corpus, y el suelo de pertinencia lo rechaza como debe. El problema es lo
    que venía después: el sistema contestaba «no he encontrado información
    sobre eso», que para un saludo no tiene ningún sentido y deja al estudiante
    pensando que ha preguntado mal en su primera frase.

    Se reconoce por vocabulario cerrado y exigiendo que **todo** el mensaje
    quepa en él, no por buscar «hola» dentro del texto: si no, «hola, ¿qué
    asignaturas tiene Informática?» se quedaría sin responder. Es el mismo
    criterio que el resto del módulo ---un mecanismo que no depende de que el
    modelo obedezca--- y por eso no se le pide al modelo que salude.

    Args:
        pregunta: Mensaje del usuario, tal cual lo escribe.

    Returns:
        La respuesta fija que corresponda, o ``None`` si el mensaje pregunta
        algo y hay que seguir el camino normal.
    """
    dichas = palabras(pregunta)
    if not dichas or not dichas <= _CORTESIA:
        return None
    if dichas & _DESPEDIDA:
        return RESPUESTA_DESPEDIDA
    if dichas & _SALUDO:
        return RESPUESTA_SALUDO
    return None


#: Marcas de que el mensaje pregunta algo, aunque también dé las gracias. Es
#: la condición que separa «gracias, ¿y qué asignaturas tiene?» de «me gusta la
#: idea, muchas gracias»: la primera hay que responderla, la segunda no.
#: Van también los imperativos de petición, que piden algo sin preguntar nada.
#: Medido el 20/08/2026: «Dame una receta de tortilla de patatas» no lleva
#: interrogación ni palabra interrogativa, así que los tres candidatos
#: contestaron con la bienvenida en vez de decir que de eso no saben.
#: Hasta cuántas palabras puede tener un mensaje sin fórmula conocida para que
#: se le siga dando la bienvenida en vez de decirle que no se ha encontrado
#: nada. Dos, porque un saludo que no está en la lista es «hei» o «q tal»; con
#: tres ya cabe una petición («resumeme la guerra») y el saludo de respaldo se
#: convertiría en la respuesta a cualquier cosa que el sistema no entienda.
_PALABRAS_DEL_SALUDO_DE_RESPALDO: Final[int] = 2

_INTERROGATIVAS: Final[frozenset[str]] = frozenset("""
    que cual cuales cuando cuanto cuanta cuantos cuantas como donde quien
    quienes dime cuentame hablame explicame ensename recomiendame dame damelo
    muestrame ponme escribeme buscame ayudame necesito quiero busco escribe
    haz dale informacion info
    """.split())


#: Con lo que se responde a quien pregunta por otra universidad. El asistente
#: informa de un centro concreto y decirlo es más útil que callar.
RESPUESTA_OTRA_UNIVERSIDAD: Final[str] = (
    "Solo puedo informarte de las titulaciones de la Escuela Politécnica "
    "Superior de Jaén. De otros centros, aunque sean de la propia Universidad "
    "de Jaén, tendrás que consultar su web. ¿Te ayudo con las de aquí?"
)

#: Cómo se nombra un centro universitario dentro de una pregunta. Sirve para
#: reconocer que se pregunta por **otro centro**, que es algo que el suelo de
#: pertinencia no puede detectar: «¿La Universidad de Granada tiene Ingeniería
#: Informática?» tiene su mejor fragmento a 0,1185 ---más cerca que la mayoría
#: de las preguntas legítimas--- porque nombra una titulación que sí existe
#: aquí. La distancia entre vectores mide parecido de vocabulario, y el
#: vocabulario es casi el mismo.
#:
#: Lo que identifica al centro es **el topónimo que va detrás del «de»**, no la
#: palabra «universidad». Reconocer solo la fórmula «Universidad de X» dejaba
#: pasar dos formas muy corrientes, medidas sobre el conjunto de validación:
#:
#: * «Universidad **Politécnica** de Valencia», donde detrás de «universidad»
#:   viene el adjetivo y no la preposición. De ahí el hueco opcional para uno o
#:   dos adjetivos.
#: * «**Escuela** Politécnica Superior de **Linares**», que no contiene la
#:   palabra «universidad» en absoluto. Y es el caso incómodo, porque la EPS de
#:   Linares es un centro real de la propia Universidad de Jaén cuyo nombre se
#:   distingue del de la EPS de Jaén en una sola palabra: un preuniversitario
#:   de la provincia puede confundirlas sin ninguna mala intención.
#:
#: Se sigue sin usar una lista de universidades, que nunca estaría completa.
_OTRA_UNIVERSIDAD: Final[re.Pattern[str]] = re.compile(
    r"(?:universidad|universitat|escuela|facultad|campus)"
    r"(?:\s+[a-z]+){0,3}?\s+(?:de\s+la|del|de)\s+([a-z]+)"
)


def pregunta_por_otro_centro(pregunta: str) -> str | None:
    """Respuesta fija si la pregunta nombra una universidad que no es la de Jaén.

    Se reconoce por la fórmula «Universidad de X» y no por una lista de
    universidades, que nunca estaría completa. Lo que se comprueba es lo único
    que se sabe con certeza: de qué centro informa este asistente.

    Args:
        pregunta: Mensaje del usuario, tal cual lo escribe.

    Returns:
        La respuesta fija, o ``None`` si no nombra otra universidad.
    """
    for encontrado in _OTRA_UNIVERSIDAD.finditer(normalizar(pregunta)):
        if encontrado.group(1) != "jaen":
            return RESPUESTA_OTRA_UNIVERSIDAD
    return None


def cierre_de_conversacion(pregunta: str) -> str | None:
    """Respuesta fija para un mensaje que agradece y no pregunta nada.

    «Me gusta la idea, muchas gracias» no cabe en :func:`cortesia`, que exige
    que el mensaje entero sea cortesía, y acababa recibiendo «no he encontrado
    información sobre eso». Aquí basta con que aparezca la fórmula, y lo que se
    exige a cambio es que **no haya pregunta**: ni signo de interrogación ni
    palabra interrogativa.

    Se comprueba antes de buscar en el índice, porque un agradecimiento no es
    una consulta: si se dejara pasar, la ampliación de la consulta que hace
    :func:`tfg_uja.recuperador.pide_recomendacion` le encontraría contexto y el
    modelo respondería a una pregunta que nadie ha hecho.

    Args:
        pregunta: Mensaje del usuario, tal cual lo escribe.

    Returns:
        La despedida, o ``None`` si el mensaje pregunta algo o no agradece.
    """
    dichas = palabras(pregunta)
    if not dichas & _DESPEDIDA:
        return None
    if "?" in pregunta or dichas & _INTERROGATIVAS:
        return None
    return RESPUESTA_DESPEDIDA


def cortesia_sin_contexto(pregunta: str) -> str | None:
    """Respuesta fija para un mensaje cortés del que no se recuperó nada.

    :func:`cortesia` exige que **todo** el mensaje quepa en el vocabulario
    cerrado, y por eso deja pasar «me gusta la idea, muchas gracias»: cuatro de
    sus palabras no son fórmulas. Ese mensaje no recuperaba nada ---no pregunta
    nada--- y recibía «no he encontrado información sobre eso», que a un
    agradecimiento le sienta igual de mal que a un saludo.

    Aquí la condición se relaja a que la fórmula **aparezca**. Es también lo
    que hace que la respuesta a un mismo mensaje no dependa de en qué turno se
    escriba.

    Lo que **no** se puede relajar es la otra mitad de la regla de
    :func:`cierre_de_conversacion`: que el mensaje no pregunte nada. Al
    relajar la primera se perdió la segunda, y la despedida pasó a ganarle a
    la pregunta que venía detrás. Fallo medido el 27/08/2026: «Vale, gracias,
    me podrías decir cómo se harían unas costillas topográficas?» recibió «¡De
    nada!» y la pregunta se quedó sin contestar. Se creía que no podía pasar
    porque esta función solo se consulta con la recuperación vacía, y de ahí
    se dedujo que el mensaje no preguntaba nada del dominio; volver vacía
    significa que no se ha encontrado, no que no se haya preguntado.

    El signo de interrogación solo desactiva la **despedida**, no el saludo. Un
    agradecimiento cierra algo, así que si el mensaje sigue preguntando, la
    fórmula era el preámbulo y lo que hay que contestar es que eso no se ha
    encontrado. Un saludo abre, y a «hola, ¿me puedes ayudar?» se le da la
    bienvenida aunque no se recupere nada, que es justo lo que invita a
    preguntar. Queda fuera del arreglo el mismo mensaje **sin** interrogación
    escrita: no hay forma de separarlo de «buenas, quiero información» sin
    perseguir casos, y perseguir casos es lo que ya falló con el vocabulario
    interrogativo.

    Y cuando no trae fórmula ninguna se mira si **pregunta algo**. Sin
    interrogación ni palabra interrogativa, y sin nada que recuperar, no hay
    pregunta a la que contestar que no se ha encontrado: lo que hay es alguien
    que ha escrito «hei» o «q tal», y a eso se le da la bienvenida. La regla
    anterior lo resolvía mirando si era el primer mensaje, y por eso contestaba
    distinto a la misma frase según el turno.

    Esa bienvenida de respaldo se limita a los mensajes **muy cortos**, y la
    razón es un fallo medido: «Hazme un resumen de la Segunda Guerra Mundial» y
    «Tradúceme al inglés...» no llevan interrogación, y sus verbos ---``hazme``,
    ``traduceme``--- no están en el vocabulario interrogativo, que recoge unas
    formas con pronombre enclítico y otras no. Las dos recibían un saludo.
    Ampliar esa lista con cada verbo nuevo es perseguir casos; lo que separa de
    verdad un saludo no reconocido de una petición ajena es la longitud, porque
    un saludo que no está en la lista tiene una palabra o dos y una petición
    tiene las que hagan falta para decir qué se pide.

    Args:
        pregunta: Mensaje del usuario, tal cual lo escribe.

    Returns:
        La respuesta fija que corresponda, o ``None`` si el mensaje pregunta
        algo que no se ha encontrado.
    """
    dichas = palabras(pregunta)
    if dichas & _DESPEDIDA and "?" not in pregunta:
        return RESPUESTA_DESPEDIDA
    if dichas & _SALUDO:
        return RESPUESTA_SALUDO
    if "?" in pregunta or dichas & _INTERROGATIVAS:
        return None
    if len(dichas) <= _PALABRAS_DEL_SALUDO_DE_RESPALDO:
        return RESPUESTA_SALUDO
    return None


def respuesta_fija(pregunta: str) -> str | None:
    """La respuesta que no necesita ni contexto recuperado ni modelo, si la hay.

    Reúne las tres salidas anticipadas que se deciden mirando solo lo que se ha
    escrito: la cortesía, el cierre de la conversación y la pregunta por otro
    centro. Existe como función propia, y no repetida en cada sitio, porque
    quien la llama necesita saber **antes de recuperar** si el modelo va a
    intervenir: recuperar para un saludo es trabajo tirado, y anunciar los
    fragmentos de un saludo es peor que tirar el trabajo, porque presenta como
    respaldo de la respuesta algo que nadie ha usado para redactarla.

    Args:
        pregunta: Lo que ha escrito el estudiante.

    Returns:
        El texto fijo con el que se contesta, o ``None`` si esta pregunta hay
        que responderla de verdad.
    """
    return (
        cortesia(pregunta)
        or cierre_de_conversacion(pregunta)
        or pregunta_por_otro_centro(pregunta)
    )


def _con_el_plan_corregido(
    unidad: str, del_plan: dict[str, Atributos], pregunta: str
) -> str:
    """Pone curso, cuatrimestre y ECTS a lo que dice el contexto, y lo anota.

    Aqui **no se retira** la respuesta, a diferencia de lo que pasa con una
    titulacion inventada, y la razon es que los dos fallos no se parecen.
    Nombrar una titulacion que no existe invalida la respuesta entera: no hay
    nada que salvar. Equivocar el cuatrimestre de una asignatura entre diez
    correctas deja una respuesta que sigue siendo util, y tirarla completa
    castigaria al estudiante por un fallo de una linea.

    Lo que se corrige sale del propio contexto que se le entrego al modelo, no
    de un criterio nuestro: si el fragmento decia «primer cuatrimestre», eso es
    lo que se escribe. Cada cambio se registra, porque un sistema que corrige
    en silencio no se puede auditar despues.

    Args:
        unidad: Trozo de respuesta ya cerrado por una frontera segura.
        del_plan: Lo que el contexto dice de cada asignatura.
        pregunta: Solo para el registro, si hay algo que anotar.

    Returns:
        La unidad, con los atributos que contradecian al contexto corregidos.
    """
    corregida, avisos = corregir_atributos(unidad, del_plan)
    for aviso in avisos:
        _registro.warning(
            "Atributo corregido contra el contexto. Pregunta: %r. %s",
            pregunta,
            aviso,
        )
    return corregida


def responder(
    pregunta: str,
    fragmentos: list[Fragmento],
    modelo: str,
    historial: list[tuple[str, str]] | None = None,
    ambito: str | list[str] | None = None,
    catalogo: list[str] | None = None,
    traza: dict[str, object] | None = None,
) -> str:
    """Devuelve la respuesta del sistema a una pregunta.

    **La cortesía se atiende antes de mirar el contexto.** Un saludo no
    recupera nada, y sin esta rama caía en la respuesta de contexto vacío:
    a un estudiante que escribía «hola» el sistema le contestaba que no había
    encontrado información sobre eso.

    **Sin fragmentos no se llama al modelo.** No es una optimización: es la
    única forma que hemos encontrado de evitar el peor fallo del sistema.

    Medido el 17/08/2026 con un modelo de 7B: el recuperador rechazó
    correctamente un saludo y no devolvió ningún fragmento, el prompt decía
    «no se ha recuperado ningún fragmento» y las instrucciones ya mandaban
    decirlo en vez de suponer. El modelo respondió inventándose un plan de
    estudios completo de Ingeniería Informática, con asignaturas repartidas
    por cursos. De los catorce nombres que dio, **trece no existen** en la
    EPSJ.

    El contexto vacío es el estado más peligroso de un sistema RAG, porque el
    modelo responde con la misma seguridad que cuando ha leído algo. Y ya
    sabemos, de tres intentos, que una instrucción no lo impide. Cortocircuitar
    sí, porque no depende de que el modelo obedezca.

    Args:
        pregunta: Pregunta del usuario, tal cual la escribe.
        fragmentos: Fragmentos recuperados, ya acotados.
        modelo: Nombre del modelo en el servidor local.
        historial: Turnos anteriores de la conversación, si los hay.
        ambito: Titulación o titulaciones a las que está acotada la búsqueda.
        catalogo: Titulaciones que declara el índice, para que el prompt las
            enumere.
        traza: Diccionario donde dejar constancia de lo que la barrera retira.
            Si se pasa, y solo entonces, se rellena con las titulaciones que la
            dispararon y con el texto retirado. El chat no lo necesita; los
            experimentos sí, porque sin el texto no hay forma de distinguir un
            modelo que se inventó una titulación de una barrera que descartó
            una respuesta buena, y las dos cosas se ven igual desde fuera: una
            respuesta de rechazo. Ya pasó ---una respuesta correcta se retiró
            por escribir «Grado en Mecánica» en corto--- y no quedó rastro.

    **Lo que el modelo escribe se comprueba antes de entregarlo.** Nombrar
    una titulación que no existe es el fallo más grave del sistema ---un
    estudiante no tiene forma de detectarlo--- y es el umbral eliminatorio de
    IT-35. Si la respuesta nombra alguna que no está en el catálogo, se retira
    entera.

    Returns:
        La respuesta, del modelo o una de las fijas del módulo.
    """
    fija = respuesta_fija(pregunta)
    if fija is not None:
        return fija
    if not fragmentos:
        # Qué se contesta con el contexto vacío depende de lo que diga el
        # mensaje, nunca de en qué turno llegue. La regla anterior ---saludo si
        # era el primero, «no he encontrado» si venía después--- daba dos
        # respuestas distintas a la misma frase escrita dos veces seguidas, y
        # eso lo vio cualquiera a la primera sesión.
        return cortesia_sin_contexto(pregunta) or RESPUESTA_SIN_CONTEXTO
    respuesta = generar(
        construir_prompt(pregunta, fragmentos, historial, ambito, catalogo), modelo
    )
    # Curso, cuatrimestre y ECTS se ponen a lo que dice el contexto antes de
    # comprobar nada más. Va aquí y no solo en `responder_por_partes` porque
    # las dos son implementaciones del mismo contrato ---una bloqueante y otra
    # por partes--- y el experimento del sistema usa esta: una barrera que solo
    # estuviera en la otra mediría un sistema distinto del que se entrega.
    respuesta = _con_el_plan_corregido(
        respuesta, atributos_del_contexto([f.texto for f in fragmentos]), pregunta
    )
    # La comprobación va DESPUÉS de generar y no en las instrucciones, que es
    # lo que distingue un mecanismo de una petición. El prompt ya prohíbe
    # añadir lo que no esté en el contexto, y aun así el 19/08/2026
    # mistral-nemo:12b recomendó a un estudiante de FP el «Grado en Ingeniería
    # de Edificación», que no existe en la EPSJ, junto a tres titulaciones que
    # sí. Sin catálogo no se puede comprobar nada, y entonces no se comprueba.
    inventadas = titulaciones_inventadas(respuesta, catalogo) if catalogo else set()
    if inventadas:
        _registro.warning(
            "Respuesta retirada: nombra titulaciones que no existen (%s). "
            "Pregunta: %r. Texto retirado: %r",
            ", ".join(sorted(inventadas)),
            pregunta,
            respuesta,
        )
        if traza is not None:
            traza["inventadas"] = sorted(inventadas)
            traza["retirada"] = respuesta
        return RESPUESTA_TITULACION_INVENTADA
    return respuesta


def _conversacion(historial: list[tuple[str, str]]) -> str:
    """Rehace los turnos anteriores. **Solo las preguntas.**

    Las respuestas del propio modelo ya no entran. Entraban recortadas a 300
    caracteres y con la regla «los datos salen del CONTEXTO, nunca de tus
    respuestas anteriores» escrita en las instrucciones, y no bastó: medido el
    17/08/2026, preguntado por los dobles grados, el modelo cerró su respuesta
    con «En el primer curso de todos los títulos mencionados se imparte
    Matemáticas I», frase copiada de su propia respuesta dos turnos antes y sin
    ninguna relación con lo que se le había preguntado.

    Es el patrón de siempre en este proyecto: una prohibición en el prompt no es
    un control. Lo que no está en el prompt no se puede copiar, y para entender
    a qué se refiere «¿y en el segundo?» basta con saber qué se preguntó antes;
    lo que el modelo contestó no aporta nada y sí arrastra sus propios errores.

    Args:
        historial: Pares ``(pregunta, respuesta)``, del más antiguo al último.
            La respuesta se ignora a propósito.

    Returns:
        El bloque de preguntas anteriores, o cadena vacía si no hay ninguna.
    """
    if not historial:
        return ""
    preguntas = [p for p, _ in historial[-TURNOS_EN_EL_PROMPT:]]
    lista = "\n".join(f"- {p}" for p in preguntas)
    return f"PREGUNTAS ANTERIORES DEL ESTUDIANTE:\n{lista}\n\n"


def construir_prompt(
    pregunta: str,
    fragmentos: list[Fragmento],
    historial: list[tuple[str, str]] | None = None,
    ambito: str | list[str] | None = None,
    catalogo: list[str] | None = None,
) -> str:
    """Arma el texto que lee el modelo.

    Cada fragmento entra encabezado por su unidad y su titulación: sin esa
    etiqueta, el modelo recibe varios textos seguidos sin saber a qué
    asignatura pertenece cada uno, y atribuir el temario de una a otra es
    justo el defecto que la fragmentación evita desde la Fase 1.

    El historial entra **separado del contexto y anunciado como tal**. Sin esa
    separación, las respuestas anteriores del propio modelo quedarían al mismo
    nivel que los fragmentos del corpus, y cualquier dato inventado en un turno
    se convertiría en fuente para el siguiente.

    **El catálogo se declara siempre, y es un dato, no una prohibición.** El
    fallo más grave que se le ha visto al sistema es recomendar titulaciones
    que no existen: el 16/08/2026 recomendó seis a un estudiante interesado en
    electricidad y **dos no existen** en la EPSJ. Las instrucciones ya decían
    «usa ÚNICAMENTE la información del CONTEXTO», así que prohibirlo otra vez
    no habría cambiado nada. Lo que sí se puede hacer desde el prompt es que la
    lista verdadera esté delante en todas las consultas, cueste lo que cueste
    ---son unas 150 fichas de las 8.192 de la ventana---, en vez de esperar a
    que la recuperación la traiga. Comprobar la respuesta contra ese catálogo,
    que es lo único que no depende de que el modelo obedezca, es IT-87.

    Args:
        pregunta: Pregunta del usuario, tal cual la escribe.
        fragmentos: Fragmentos recuperados, de más a menos próximo.
        historial: Turnos anteriores de la conversación, si los hay.
        ambito: Titulación o titulaciones a las que está acotada la búsqueda.
        catalogo: Titulaciones que declara el índice. Si no se pasa, el prompt
            no las enumera y el modelo solo cuenta con el contexto.

    Returns:
        Prompt completo, listo para enviar al modelo.
    """
    if not fragmentos:
        contexto = "(no se ha recuperado ningún fragmento)"
    else:
        contexto = "\n\n".join(
            f"{_etiqueta(f)}\n{f.texto}" for f in ordenar_contexto(fragmentos)
        )
    oferta = (
        "TITULACIONES DE LA ESCUELA. Son estas y no hay ninguna más:\n"
        + "\n".join(f"- {t}" for t in catalogo)
        + "\n\n"
        if catalogo
        else ""
    )
    # El ámbito se **declara como dato**, no como prohibición. 78 guías del
    # corpus se imparten en varias titulaciones y su encabezado las nombra
    # todas, así que acotar la búsqueda a una no impide que el modelo hable de
    # las otras: medido, con el filtro puesto en Informática respondió con un
    # apartado entero sobre Inteligencia Artificial y Ciberseguridad.
    encabezado = _encabezado_de_ambito(ambito)
    return (
        f"{INSTRUCCIONES}\n\n"
        f"{oferta}"
        f"{encabezado}"
        f"{_conversacion(historial or [])}"
        f"CONTEXTO:\n{contexto}\n\n"
        f"PREGUNTA: {pregunta}\n\n"
        f"RESPUESTA:"
    )


def _encabezado_de_ambito(ambito: str | list[str] | None) -> str:
    """Declara el sujeto de la consulta sin perder un ámbito comparativo.

    Args:
        ambito: Una titulación, varias o ninguna.

    Returns:
        Bloque que precede al contexto, o cadena vacía sin ámbito.
    """
    if not ambito:
        return ""
    titulaciones = [ambito] if isinstance(ambito, str) else list(ambito)
    if len(titulaciones) == 1:
        return f"ÁMBITO: la consulta es sobre el {titulaciones[0]}.\n\n"
    lista = "\n".join(f"- {titulacion}" for titulacion in titulaciones)
    return f"ÁMBITO: la consulta abarca estas titulaciones:\n{lista}\n\n"


#: Con lo que se cierra una respuesta que el modelo no llegó a terminar. Se
#: escribe siempre que el servidor diga que paró por longitud, porque el
#: estudiante no tiene forma de distinguir una respuesta completa de una
#: cortada, y una lista interrumpida se lee como si fuera la lista entera.
AVISO_RESPUESTA_CORTADA: Final[str] = (
    "\n\n*He tenido que cortar aquí: la respuesta se estaba haciendo muy "
    "larga. Pregúntame por la parte que te interese y te la cuento entera.*"
)


def cerrar_en_frase_completa(texto: str) -> str:
    """Recorta un texto hasta su última frase o línea terminada.

    El tope de la respuesta se agota a mitad de palabra ---«**Nota:** Todas las
    titul», medido el 19/08/2026---, y entregar eso es peor que entregar menos:
    la frase partida parece un fallo del sistema y además deja al lector sin
    saber qué iba a decir.

    Se corta por el final de frase o de línea más avanzado de los dos, porque
    las respuestas alternan prosa y listas, y en una lista lo que cierra el
    último elemento es el salto de línea, no el punto.

    Args:
        texto: Respuesta tal como la devolvió el modelo.

    Returns:
        El texto hasta el último cierre, o el texto entero si no hay ninguno.
    """
    cierres = [texto.rfind(c) for c in (".", "!", "?", "\n")]
    ultimo = max(cierres)
    if ultimo < 0:
        return texto
    return texto[: ultimo + 1].rstrip()


def generar(
    prompt: str,
    modelo: str,
    servidor: str = SERVIDOR,
    ventana: int = VENTANA,
    tope: int = TOPE_RESPUESTA,
    semilla: int = 42,
    sistema: str = SISTEMA,
) -> str:
    """Pide la respuesta al modelo local.

    La temperatura va a cero y la semilla fijada, que es lo que quita el azar
    del muestreo. **Eso no basta para que el texto sea reproducible**, y
    conviene no dar a entender lo contrario: con la misma pregunta, el mismo
    prompt y estos mismos parámetros, la primera llamada tras cargar el modelo
    devuelve una redacción y de la segunda en adelante devuelve otra. Las dos
    son estables y se repiten sin fallo, pero son distintas.

    Lo que sí se sostiene es el resultado: en dos pasadas completas del banco
    de evaluación cambió la redacción de 27 de las 42 respuestas generadas y
    **no cambió ni uno de los 57 veredictos**. Eso no es suerte, es
    consecuencia de que los correctores comparan hechos y no cómo están
    escritos; medir el formato habría dado cifras distintas cada vez.

    Args:
        prompt: Texto que devuelve :func:`construir_prompt`.
        modelo: Nombre del modelo en el servidor local.
        servidor: Dirección del servidor de inferencia.
        ventana: Ventana de contexto en *tokens*.
        tope: Máximo de *tokens* de la respuesta.
        semilla: Semilla del muestreo.
        sistema: Mensaje de sistema. Se manda siempre, e igual para todos los
            modelos, para que ninguno responda bajo el suyo de fábrica.

    Returns:
        La respuesta del modelo, sin espacios sobrantes.
    """
    cuerpo = {
        "model": modelo,
        "prompt": prompt,
        "system": sistema,
        "stream": False,
        "think": False,
        "options": {
            "num_ctx": ventana,
            "temperature": 0,
            "seed": semilla,
            "num_predict": tope,
        },
    }
    peticion = urllib.request.Request(
        f"{servidor}/api/generate",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=ESPERA_MAXIMA) as respuesta:
            datos = json.loads(respuesta.read())
    except urllib.error.HTTPError as error:
        detalle = error.read().decode("utf-8", "replace").strip()
        raise ErrorDelModelo(
            f"el servidor respondió {error.code} al generar con «{modelo}»"
            + (f": {detalle[:200]}" if detalle else "")
        ) from error
    # Va antes de URLError a propósito: agotar la espera de lectura levanta
    # TimeoutError, que **no** es un URLError, así que sin esta rama se escapa
    # de las dos y sube. El 19/08/2026 tumbó una tanda de 560 respuestas cuando
    # llevaba 85: `command-r7b` se colgó en una pregunta y se perdieron las
    # nueve horas siguientes. Un modelo colgado tiene que costar una pregunta,
    # no la sesión.
    except TimeoutError as error:
        raise ErrorDelModelo(f"«{modelo}» no respondió en {ESPERA_MAXIMA} s") from error
    except urllib.error.URLError as error:
        raise ErrorDelModelo(
            f"no se pudo hablar con el servidor en {servidor}: {error.reason}. "
            "¿Está Ollama en marcha?"
        ) from error
    escrito = str(datos.get("response", "")).strip()
    if datos.get("done_reason") == "length":
        return cerrar_en_frase_completa(escrito) + AVISO_RESPUESTA_CORTADA
    return escrito


#: Caracteres que cierran una unidad emitible. Son las **fronteras seguras** del
#: ADR-0006: soltar un trozo cortado a mitad de palabra daria un falso positivo
#: en `titulaciones_inventadas`, que admite subconjuntos de palabras. «Grado en
#: Ingenieria» pasa la comprobacion; «Grado en Ingenieria Infor» no.
FRONTERAS: Final[str] = ".!?\n"


def partir_en_unidades(texto: str) -> tuple[list[str], str]:
    """Separa lo que ya se puede soltar de lo que hay que seguir acumulando.

    Args:
        texto: Todo lo que el modelo ha escrito y aun no se ha soltado.

    Returns:
        ``(unidades, resto)``. Cada unidad termina en una frontera segura y el
        resto se queda en el acumulador hasta que llegue la suya.
    """
    unidades: list[str] = []
    inicio = 0
    for i, caracter in enumerate(texto):
        if caracter in FRONTERAS:
            unidades.append(texto[inicio : i + 1])
            inicio = i + 1
    return unidades, texto[inicio:]


def generar_por_partes(
    prompt: str,
    modelo: str,
    servidor: str = SERVIDOR,
    ventana: int = VENTANA,
    tope: int = TOPE_RESPUESTA,
    semilla: int = 42,
    sistema: str = SISTEMA,
) -> Iterator[str]:
    """Lo mismo que :func:`generar`, pero devolviendo el texto segun se produce.

    El servidor de inferencia manda un objeto JSON por linea con el trozo
    recien escrito. Aqui solo se reenvian esos trozos: **no se comprueba nada**,
    porque la comprobacion necesita fronteras seguras y de eso se encarga
    :func:`responder_por_partes`.

    Args:
        prompt: Texto que devuelve :func:`construir_prompt`.
        modelo: Nombre del modelo en el servidor local.
        servidor: Direccion del servidor de inferencia.
        ventana: Ventana de contexto en *tokens*.
        tope: Maximo de *tokens* de la respuesta.
        semilla: Semilla del muestreo.
        sistema: Mensaje de sistema.

    Yields:
        Los trozos de texto en el orden en que los escribe el modelo, y al
        final el aviso de respuesta cortada si se agoto el tope.

    Raises:
        ErrorDelModelo: si el servidor no responde, tarda demasiado o falla.
    """
    cuerpo = {
        "model": modelo,
        "prompt": prompt,
        "system": sistema,
        "stream": True,
        "think": False,
        "options": {
            "num_ctx": ventana,
            "temperature": 0,
            "seed": semilla,
            "num_predict": tope,
        },
    }
    peticion = urllib.request.Request(
        f"{servidor}/api/generate",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=ESPERA_MAXIMA) as respuesta:
            for linea in respuesta:
                if not linea.strip():
                    continue
                datos = json.loads(linea)
                trozo = str(datos.get("response", ""))
                if trozo:
                    yield trozo
                if datos.get("done_reason") == "length":
                    yield AVISO_RESPUESTA_CORTADA
    except urllib.error.HTTPError as error:
        detalle = error.read().decode("utf-8", "replace").strip()
        raise ErrorDelModelo(
            f"el servidor respondió {error.code} al generar con «{modelo}»"
            + (f": {detalle[:200]}" if detalle else "")
        ) from error
    except TimeoutError as error:
        raise ErrorDelModelo(f"«{modelo}» no respondió en {ESPERA_MAXIMA} s") from error
    except urllib.error.URLError as error:
        raise ErrorDelModelo(
            f"no se pudo hablar con el servidor en {servidor}: {error.reason}. "
            "¿Está Ollama en marcha?"
        ) from error


def responder_por_partes(
    pregunta: str,
    fragmentos: list[Fragmento],
    modelo: str,
    historial: list[tuple[str, str]] | None = None,
    ambito: str | list[str] | None = None,
    catalogo: list[str] | None = None,
) -> Iterator[str | None]:
    """Devuelve la respuesta por partes, **cada una ya verificada** (ADR-0006).

    Mismos desvios que :func:`responder`: la cortesia se atiende antes de mirar
    el contexto y sin fragmentos no se llama al modelo. En esos dos casos sale
    una sola parte con la respuesta fija.

    Cuando si se llama al modelo, se acumula hasta una frontera segura y se pasa
    el **texto acumulado entero** por :func:`titulaciones_inventadas` antes de
    soltar nada. Verificar solo la unidad nueva dejaria pasar un nombre partido
    entre dos unidades.

    Si la comprobacion falla, se corta la emision y se emite
    ``None`` como senal de que hay que **descartar lo ya emitido** y poner en su
    lugar :data:`RESPUESTA_TITULACION_INVENTADA`, que llega justo despues.

    Args:
        pregunta: Lo que ha escrito el estudiante.
        fragmentos: Los que ha traido el recuperador.
        modelo: Nombre del modelo en el servidor local.
        historial: Preguntas de los turnos anteriores.
        ambito: Titulacion o titulaciones de las que se viene hablando.
        catalogo: Titulaciones que declara el indice. Sin el no se comprueba.

    Yields:
        Cadenas con las partes verificadas. Un ``None`` significa «borra lo
        emitido»: lo que venga despues sustituye a todo lo anterior.
    """
    fija = respuesta_fija(pregunta)
    if fija is not None:
        yield fija
        return
    if not fragmentos:
        yield cortesia_sin_contexto(pregunta) or RESPUESTA_SIN_CONTEXTO
        return

    prompt = construir_prompt(pregunta, fragmentos, historial, ambito, catalogo)
    # Lo que el contexto afirma del plan de cada asignatura. Se calcula una vez
    # por turno: son los mismos fragmentos para todas las partes.
    del_plan = atributos_del_contexto([f.texto for f in fragmentos])
    acumulado = ""
    pendiente = ""
    for trozo in generar_por_partes(prompt, modelo):
        pendiente += trozo
        unidades, pendiente = partir_en_unidades(pendiente)
        for unidad in unidades:
            unidad = _con_el_plan_corregido(unidad, del_plan, pregunta)
            acumulado += unidad
            if catalogo and titulaciones_inventadas(acumulado, catalogo):
                _registro.warning(
                    "Respuesta retirada en curso: nombra titulaciones que no "
                    "existen. Pregunta: %r. Texto retirado: %r",
                    pregunta,
                    acumulado,
                )
                yield None
                yield RESPUESTA_TITULACION_INVENTADA
                return
            yield unidad

    # La cola que no llego a cerrar frontera se comprueba igual antes de salir.
    if pendiente:
        pendiente = _con_el_plan_corregido(pendiente, del_plan, pregunta)
        acumulado += pendiente
        if catalogo and titulaciones_inventadas(acumulado, catalogo):
            yield None
            yield RESPUESTA_TITULACION_INVENTADA
            return
        yield pendiente

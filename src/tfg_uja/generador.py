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
import urllib.request
from typing import Final

from tfg_uja.chunker import ORDEN_CURSOS
from tfg_uja.recuperador import Fragmento
from tfg_uja.text_cleaner import palabras

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
    "- Si hay un ÁMBITO declarado, responde sobre esa titulación. Varias "
    "asignaturas se imparten en más de una, y el contexto las nombra todas; "
    "menciónalo si viene al caso, pero no cambies de titulación.\n"
    "- Las PREGUNTAS ANTERIORES sirven solo para entender a qué se refiere la "
    "pregunta actual. Todos los datos salen del CONTEXTO.\n"
    "- Cita la asignatura o la titulación de la que sale cada dato."
)

#: Cuántas preguntas anteriores se le recuerdan al modelo. Son **preguntas**,
#: no respuestas: ver :func:`_conversacion`.
TURNOS_EN_EL_PROMPT: Final[int] = 3


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


def responder(
    pregunta: str,
    fragmentos: list[Fragmento],
    modelo: str,
    historial: list[tuple[str, str]] | None = None,
    ambito: str | None = None,
    catalogo: list[str] | None = None,
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
        ambito: Titulación a la que está acotada la búsqueda, si lo está.
        catalogo: Titulaciones que declara el índice, para que el prompt las
            enumere.

    Returns:
        La respuesta, del modelo o una de las fijas del módulo.
    """
    fija = cortesia(pregunta)
    if fija is not None:
        return fija
    if not fragmentos:
        return RESPUESTA_SIN_CONTEXTO
    return generar(
        construir_prompt(pregunta, fragmentos, historial, ambito, catalogo), modelo
    )


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
    ambito: str | None = None,
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
        ambito: Titulación a la que está acotada la búsqueda, si lo está.
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
    encabezado = f"ÁMBITO: la consulta es sobre el {ambito}.\n\n" if ambito else ""
    return (
        f"{INSTRUCCIONES}\n\n"
        f"{oferta}"
        f"{encabezado}"
        f"{_conversacion(historial or [])}"
        f"CONTEXTO:\n{contexto}\n\n"
        f"PREGUNTA: {pregunta}\n\n"
        f"RESPUESTA:"
    )


def generar(
    prompt: str,
    modelo: str,
    servidor: str = SERVIDOR,
    ventana: int = VENTANA,
    tope: int = TOPE_RESPUESTA,
    semilla: int = 42,
) -> str:
    """Pide la respuesta al modelo local.

    La temperatura va a cero y la semilla fijada: con muestreo libre, dos
    ejecuciones de la misma pregunta dan respuestas distintas y ninguna
    medición sobre ellas sería reproducible.

    Args:
        prompt: Texto que devuelve :func:`construir_prompt`.
        modelo: Nombre del modelo en el servidor local.
        servidor: Dirección del servidor de inferencia.
        ventana: Ventana de contexto en *tokens*.
        tope: Máximo de *tokens* de la respuesta.
        semilla: Semilla del muestreo.

    Returns:
        La respuesta del modelo, sin espacios sobrantes.
    """
    cuerpo = {
        "model": modelo,
        "prompt": prompt,
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
    with urllib.request.urlopen(peticion, timeout=600) as respuesta:
        datos = json.loads(respuesta.read())
    return str(datos.get("response", "")).strip()

"""Generación de la respuesta a partir del contexto recuperado (IT-37)."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

from tfg_uja.indexacion.chunker import ORDEN_CURSOS
from tfg_uja.dialogo.recuperador import Fragmento
from tfg_uja.text_cleaner import normalizar, palabras
from tfg_uja.dialogo.verificacion import (
    Atributos,
    asignatura_del_segmento,
    atributos_del_contexto,
    corregir_atributos,
    titulaciones_inventadas,
)

# Registra las respuestas retiradas para poder auditar la barrera de dominio.
_registro: Final[logging.Logger] = logging.getLogger(__name__)

#: Servidor de inferencia local. No se consulta ningún servicio externo: el
#: sistema tiene que poder ejecutarse entero en el equipo del autor.
SERVIDOR: Final[str] = "http://127.0.0.1:11434"

# Ventana de contexto acotada para que la caché no desplace el modelo a CPU.
VENTANA: Final[int] = 8192

#: Tope de la respuesta. Acota lo que puede tardar y evita que un modelo
#: locuaz convierta una consulta de chat en un minuto de espera.

# 1.200 tokens cubren el listado de 67 asignaturas de Informática (2.819 caracteres) y
# su presentación.
TOPE_RESPUESTA: Final[int] = 1200

# Tiempo máximo de espera, en segundos; la latencia se evalúa por separado.
ESPERA_MAXIMA: Final[int] = 600

#: Mensaje de sistema que se manda con cada petición. Su función no es dar
#: instrucciones ---esas van en :data:`INSTRUCCIONES`--- sino tapar el que trae
#: cada modelo de fábrica.

# Un mensaje de sistema explícito sustituye las instrucciones predeterminadas de cada
# modelo en Ollama.

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

#: Cuántas preguntas anteriores se le recuerdan al modelo. Son preguntas,
#: no respuestas: ver :func:`_conversacion`.
TURNOS_EN_EL_PROMPT: Final[int] = 3


class ErrorDelModelo(RuntimeError):
    """El servidor de inferencia no ha podido responder."""


def ordenar_contexto(fragmentos: list[Fragmento]) -> list[Fragmento]:
    """Reagrupa las partes de cada unidad y las pone en su orden."""
    # La titulación distingue unidades homónimas y evita intercalar sus fragmentos.
    mejor: dict[tuple[str, str, tuple[str, ...]], float] = {}
    for f in fragmentos:
        clave = (f.origen, f.nombre, tuple(f.grados))
        mejor[clave] = min(mejor.get(clave, f.distancia), f.distancia)

    # Ordena los cursos dentro de cada titulación; entre titulaciones manda la
    # distancia.
    anclas: dict[tuple[str, ...], float] = {}
    for f in fragmentos:
        if f.origen != "plan_de_estudios":
            continue
        titulacion = tuple(f.grados)
        distancia = mejor[(f.origen, f.nombre, titulacion)]
        anclas[titulacion] = min(anclas.get(titulacion, distancia), distancia)

    def orden(f: Fragmento) -> tuple[float, int, str, int]:
        if f.origen == "plan_de_estudios":
            return (
                anclas[tuple(f.grados)],
                _curso_del_listado(f.nombre),
                f.nombre,
                f.chunk_index,
            )
        return (
            mejor[(f.origen, f.nombre, tuple(f.grados))],
            0,
            f.nombre,
            f.chunk_index,
        )

    return sorted(fragmentos, key=orden)


def _curso_del_listado(nombre: str) -> int:
    """Sitúa un listado del plan en el curso que enuncia su propio nombre."""
    bajo = nombre.lower()
    for posicion, ordinal in enumerate(ORDEN_CURSOS, start=1):
        if f"de {ordinal}" in bajo:
            return posicion
    return len(ORDEN_CURSOS) + 1


def _etiqueta(fragmento: Fragmento) -> str:
    """Compone la línea que encabeza un fragmento dentro del contexto."""
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

# Una titulación inexistente retira la respuesta completa para no entregar
# recomendaciones falsas.
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

# Solo es cortesía si todas las palabras pertenecen a esta lista.
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

# Reconoce también saludos en otros idiomas; la respuesta sigue en español.
_SALUDO: Final[frozenset[str]] = frozenset(
    {"hola", "buenas", "buenos", "saludos", "hey", "ey", "hello", "hi", "hallo"}
)

#: Y las que lo convierten en una despedida o un agradecimiento.
_DESPEDIDA: Final[frozenset[str]] = frozenset(
    {"gracias", "adios", "chao", "hasta", "luego", "pronto"}
)


def cortesia(pregunta: str) -> str | None:
    """Devuelve la respuesta fija si el mensaje es solo cortesía."""
    dichas = palabras(pregunta)
    if not dichas or not dichas <= _CORTESIA:
        return None
    if dichas & _DESPEDIDA:
        return RESPUESTA_DESPEDIDA
    if dichas & _SALUDO:
        return RESPUESTA_SALUDO
    return None


# Dos palabras admiten «q tal»; tres ya permiten peticiones como «resúmeme la guerra».
_PALABRAS_DEL_SALUDO_DE_RESPALDO: Final[int] = 2

#: Marcas de que el mensaje pregunta algo, aunque también dé las gracias. Es la
#: condición que separa «gracias, ¿y qué asignaturas tiene?» de «me gusta la
#: idea, muchas gracias»: la primera hay que responderla, la segunda no.

# Los imperativos también piden contenido, aunque no lleven interrogación.
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

# El centro ajeno se comprueba aparte: la similitud puede ser alta si coincide la
# titulación.

#: Lo que identifica al centro es el topónimo que va detrás del «de», no la
#: palabra «universidad»: la fórmula «Universidad de X» a secas deja pasar dos
#: formas muy corrientes del conjunto de validación:

# Admite adjetivos en «Universidad Politécnica» y centros como la EPS de Linares.

#: Se sigue sin usar una lista de universidades, que nunca estaría completa.
_OTRA_UNIVERSIDAD: Final[re.Pattern[str]] = re.compile(
    r"(?:universidad|universitat|escuela|facultad|campus)"
    r"(?:\s+[a-z]+){0,3}?\s+(?:de\s+la|del|de)\s+([a-z]+)"
)


def pregunta_por_otro_centro(pregunta: str) -> str | None:
    """Respuesta fija si la pregunta nombra una universidad que no es la de Jaén."""
    for encontrado in _OTRA_UNIVERSIDAD.finditer(normalizar(pregunta)):
        if encontrado.group(1) != "jaen":
            return RESPUESTA_OTRA_UNIVERSIDAD
    return None


def cierre_de_conversacion(pregunta: str) -> str | None:
    """Respuesta fija para un mensaje que agradece y no pregunta nada."""
    dichas = palabras(pregunta)
    if not dichas & _DESPEDIDA:
        return None
    if "?" in pregunta or dichas & _INTERROGATIVAS:
        return None
    return RESPUESTA_DESPEDIDA


def cortesia_sin_contexto(pregunta: str) -> str | None:
    """Respuesta fija para un mensaje cortés del que no se recuperó nada."""
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
    """La respuesta que no necesita ni contexto recuperado ni modelo, si la hay."""
    return (
        cortesia(pregunta)
        or cierre_de_conversacion(pregunta)
        or pregunta_por_otro_centro(pregunta)
    )


def _anotar_retirada(
    pregunta: str,
    texto: str,
    catalogo: list[str] | None,
    traza: dict[str, object] | None,
) -> None:
    """Deja constancia de una respuesta retirada por nombrar lo que no existe."""
    inventadas = sorted(titulaciones_inventadas(texto, catalogo) if catalogo else set())
    _registro.warning(
        "Respuesta retirada: nombra titulaciones que no existen (%s). "
        "Pregunta: %r. Texto retirado: %r",
        ", ".join(inventadas),
        pregunta,
        texto,
    )
    if traza is not None:
        traza["inventadas"] = inventadas
        traza["retirada"] = texto


def _sujeto_tras(
    unidad: str, del_plan: dict[str, Atributos], sujeto: str | None
) -> str | None:
    """De que asignatura se sigue hablando cuando termina esta unidad."""
    if "\n" in unidad:
        return asignatura_del_segmento(unidad.rsplit("\n", 1)[1], del_plan)
    return asignatura_del_segmento(unidad, del_plan) or sujeto


def _con_el_plan_corregido(
    unidad: str,
    del_plan: dict[str, Atributos],
    pregunta: str,
    sujeto: str | None = None,
) -> str:
    """Pone curso, cuatrimestre y ECTS a lo que dice el contexto, y lo anota."""
    corregida, avisos = corregir_atributos(unidad, del_plan, sujeto)
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
    """Devuelve la respuesta del sistema a una pregunta, de una sola pieza."""
    partes: list[str] = []
    for parte in responder_por_partes(
        pregunta,
        fragmentos,
        modelo,
        historial=historial,
        ambito=ambito,
        catalogo=catalogo,
        traza=traza,
        flujo=False,
    ):
        if parte is None:
            # Senal de «borra lo emitido»: lo que venga despues lo sustituye.
            partes.clear()
        else:
            partes.append(parte)
    return "".join(partes).strip()


def _conversacion(historial: list[tuple[str, str]]) -> str:
    """Rehace los turnos anteriores. Solo las preguntas."""
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
    """Arma el texto que lee el modelo."""
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
    # Declara el ámbito porque una guía compartida nombra también otras titulaciones.
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
    """Declara el sujeto de la consulta sin perder un ámbito comparativo."""
    if not ambito:
        return ""
    titulaciones = [ambito] if isinstance(ambito, str) else list(ambito)
    if len(titulaciones) == 1:
        return f"ÁMBITO: la consulta es sobre el {titulaciones[0]}.\n\n"
    lista = "\n".join(f"- {titulacion}" for titulacion in titulaciones)
    return f"ÁMBITO: la consulta abarca estas titulaciones:\n{lista}\n\n"


# Avisa cuando el servidor detiene la respuesta por longitud.
AVISO_RESPUESTA_CORTADA: Final[str] = (
    "\n\n*He tenido que cortar aquí: la respuesta se estaba haciendo muy "
    "larga. Pregúntame por la parte que te interese y te la cuento entera.*"
)


def cerrar_en_frase_completa(texto: str) -> str:
    """Recorta un texto hasta su última frase o línea terminada."""
    cierres = [texto.rfind(c) for c in (".", "!", "?", "\n")]
    ultimo = max(cierres)
    if ultimo < 0:
        return texto
    return texto[: ultimo + 1].rstrip()


def _peticion(
    prompt: str,
    modelo: str,
    servidor: str,
    ventana: int,
    tope: int,
    semilla: int,
    sistema: str,
    flujo: bool,
) -> urllib.request.Request:
    """Arma la peticion al servidor de inferencia."""
    cuerpo = {
        "model": modelo,
        "prompt": prompt,
        "system": sistema,
        "stream": flujo,
        "think": False,
        "options": {
            "num_ctx": ventana,
            "temperature": 0,
            "seed": semilla,
            "num_predict": tope,
        },
    }
    return urllib.request.Request(
        f"{servidor}/api/generate",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


@contextmanager
def _errores_del_modelo(modelo: str, servidor: str) -> Iterator[None]:
    """Traduce a :class:`ErrorDelModelo` los fallos de hablar con el servidor.

    Raises:
        ErrorDelModelo: siempre que el servidor no responda como debe.
    """
    try:
        yield
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
    except ConnectionError as error:
        raise ErrorDelModelo(
            f"el servidor en {servidor} cortó la conexión a media respuesta "
            f"({error}). Suele ser que se ha quedado sin memoria."
        ) from error


def generar(
    prompt: str,
    modelo: str,
    servidor: str = SERVIDOR,
    ventana: int = VENTANA,
    tope: int = TOPE_RESPUESTA,
    semilla: int = 42,
    sistema: str = SISTEMA,
) -> str:
    """Pide la respuesta al modelo local."""
    peticion = _peticion(
        prompt, modelo, servidor, ventana, tope, semilla, sistema, flujo=False
    )
    with _errores_del_modelo(modelo, servidor):
        with urllib.request.urlopen(peticion, timeout=ESPERA_MAXIMA) as respuesta:
            datos = json.loads(respuesta.read())
    escrito = str(datos.get("response", "")).strip()
    if datos.get("done_reason") == "length":
        return cerrar_en_frase_completa(escrito) + AVISO_RESPUESTA_CORTADA
    return escrito


# Verifica unidades completas: cortar una palabra puede producir falsas titulaciones
# inventadas (ADR-0006).
FRONTERAS: Final[str] = ".!?\n"


def partir_en_unidades(texto: str) -> tuple[list[str], str]:
    """Separa lo que ya se puede soltar de lo que hay que seguir acumulando."""
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

    Raises:
        ErrorDelModelo: si el servidor no responde, tarda demasiado o falla.
    """
    peticion = _peticion(
        prompt, modelo, servidor, ventana, tope, semilla, sistema, flujo=True
    )
    with _errores_del_modelo(modelo, servidor):
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


def responder_por_partes(
    pregunta: str,
    fragmentos: list[Fragmento],
    modelo: str,
    historial: list[tuple[str, str]] | None = None,
    ambito: str | list[str] | None = None,
    catalogo: list[str] | None = None,
    traza: dict[str, object] | None = None,
    flujo: bool = True,
) -> Iterator[str | None]:
    """Devuelve la respuesta por partes, cada una ya verificada (ADR-0006)."""
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
    # Conserva la asignatura entre frases para atribuirle los datos que no repiten su
    # nombre.
    sujeto: str | None = None
    # Si se ha llegado a cerrar alguna frase. Solo entonces se puede tirar la
    # cola al agotarse el tope: ver mas abajo.
    hubo_frontera = False
    trozos = (
        generar_por_partes(prompt, modelo) if flujo else iter([generar(prompt, modelo)])
    )
    for trozo in trozos:
        # Al agotar el límite, descarta el resto incompleto solo si hubo una frontera;
        # mantiene el criterio de la respuesta sin flujo.
        if trozo == AVISO_RESPUESTA_CORTADA and hubo_frontera:
            pendiente = ""
        pendiente += trozo
        unidades, pendiente = partir_en_unidades(pendiente)
        hubo_frontera = hubo_frontera or bool(unidades)
        for unidad in unidades:
            unidad = _con_el_plan_corregido(unidad, del_plan, pregunta, sujeto)
            sujeto = _sujeto_tras(unidad, del_plan, sujeto)
            acumulado += unidad
            if catalogo and titulaciones_inventadas(acumulado, catalogo):
                _anotar_retirada(pregunta, acumulado, catalogo, traza)
                yield None
                yield RESPUESTA_TITULACION_INVENTADA
                return
            yield unidad

    # La cola que no llego a cerrar frontera se comprueba igual antes de salir.
    if pendiente:
        pendiente = _con_el_plan_corregido(pendiente, del_plan, pregunta, sujeto)
        acumulado += pendiente
        if catalogo and titulaciones_inventadas(acumulado, catalogo):
            _anotar_retirada(pregunta, acumulado, catalogo, traza)
            yield None
            yield RESPUESTA_TITULACION_INVENTADA
            return
        yield pendiente

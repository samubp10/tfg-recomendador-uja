"""Recuperación de fragmentos del índice vectorial (IT-37).

Es la mitad que el indexador dejó sin escribir a propósito: ``indexer.py``
construye el índice y no lo consulta, porque diseñar la consulta antes de que
existiera el recuperador habría sido inventarse sus necesidades.

Este módulo lee del índice **lo que el índice dice de sí mismo**. Los tres datos
que graba :func:`tfg_uja.indexer.reconstruir_indice` ---modelo, prefijo y
métrica--- son tres formas de equivocarse que **no producen ningún error**, solo
resultados peores:

* consultar con un modelo distinto del que construyó el índice, que puede
  producir vectores de la misma dimensión y por tanto no falla;
* consultar sin declarar la métrica, porque la de LanceDB por defecto es
  ``l2`` y ordenaría por otra cosa;
* filtrar después de buscar en vez de antes, que devuelve listas cortas o
  vacías y hace que el sistema diga «no tengo información» sobre algo que sí
  está indexado.

Las tres se comprueban aquí, y las tres tienen prueba de regresión.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Any, Final

import lancedb

from tfg_uja.indexacion.incrustaciones import Incrustador
from tfg_uja.indexacion.indexer import (
    CATALOGO,
    COLECCION,
    DISTANCIA,
    metadatos_de_indice,
)
from tfg_uja.text_cleaner import normalizar, palabras

#: Fragmentos que se recuperan por consulta cuando no se dice otra cosa. Es el
#: punto de partida de la banda dinámica, no el número que acaba entregándose:
#: quien decide cuántos entran es :func:`acotar_por_distancia`, con los valores
#: que fijó la rejilla de IT-49.
K_POR_DEFECTO: Final[int] = 10

#: Longitud a partir de la cual una palabra del catálogo sirve para reconocer
#: una titulación. Por debajo quedan las partículas ---«y», «de», «en»--- que
#: aparecen en cualquier frase y reconocerían una titulación en todas.
LARGO_DISTINTIVO: Final[int] = 4


def palabras_distintivas(catalogo: list[str]) -> set[str]:
    """Palabras que identifican a una titulación concreta y no a todas.

    Se calculan del propio catálogo en vez de escribirse a mano, para que una
    titulación nueva no obligue a tocar esta lista. Una palabra es distintiva
    si aparece en menos de la mitad de los nombres: «ingeniería» está en once
    de los doce y no distingue nada; «informática», en uno.

    Args:
        catalogo: Titulaciones que declara el índice.

    Returns:
        Palabras que, apareciendo en una pregunta, la sitúan en alguna
        titulación.
    """
    conteo = Counter(p for titulacion in catalogo for p in palabras(titulacion))
    tope = len(catalogo) / 2
    return {
        p for p, veces in conteo.items() if veces < tope and len(p) >= LARGO_DISTINTIVO
    }


@dataclass(frozen=True)
class Fragmento:
    """Un fragmento recuperado, con lo que hace falta para citarlo.

    Se devuelve un objeto y no el diccionario crudo de la base para que el
    generador no dependa de cómo estén nombradas las columnas del índice.

    Attributes:
        texto: Contenido del fragmento.
        nombre: Unidad a la que pertenece (asignatura, plan o salidas).
        grados: Titulaciones en las que aparece esa unidad.
        origen: De dónde salió el fragmento (``guia``, ``salidas``, ...).
        distancia: Distancia al vector de la consulta; menor es más próximo.
        chunk_index: Posición de este fragmento dentro de su unidad, desde 0.
        total_chunks: En cuántos fragmentos se partió la unidad entera.
        curso: Curso en que se imparte, tal como lo publica la fuente. Vacío
            en las optativas, que la EPSJ publica sin curso.
    """

    texto: str
    nombre: str
    grados: list[str]
    origen: str
    distancia: float
    chunk_index: int
    total_chunks: int
    curso: str = ""


class ModeloDiscrepante(RuntimeError):
    """El índice se construyó con un modelo distinto del que se consulta."""


def abrir_indice(ruta_indice: Path, modelo: str) -> Any:
    """Abre el índice comprobando que se construyó con el modelo esperado.

    La comprobación no es ceremonia: dos modelos distintos pueden producir
    vectores de la misma dimensión ---384 tanto el del ADR-0003 como el
    anterior---, de modo que consultar con el equivocado no da ningún error y
    solo devuelve peores resultados. Al fallar aquí, y de forma ruidosa, el
    defecto aparece al abrir el índice y no meses después en una métrica.

    Args:
        ruta_indice: Carpeta donde persiste el índice.
        modelo: Modelo con el que se van a incrustar las consultas.

    Returns:
        Tabla de LanceDB lista para consultar.

    Raises:
        ModeloDiscrepante: Si el índice declara otro modelo.
    """
    metadatos = metadatos_de_indice(ruta_indice)
    registrado = metadatos.get("modelo")
    if registrado is not None and registrado != modelo:
        raise ModeloDiscrepante(
            f"el índice se construyó con «{registrado}» y se está consultando "
            f"con «{modelo}»: los resultados serían peores sin dar ningún error"
        )
    return lancedb.connect(str(ruta_indice)).open_table(COLECCION)


def distancia_del_indice(ruta_indice: Path) -> str:
    """Métrica con la que hay que consultar el índice.

    Se lee de los metadatos en vez de darla por sabida. Si un índice antiguo
    no la lleva grabada, se usa la del proyecto.

    Args:
        ruta_indice: Carpeta donde persiste el índice.

    Returns:
        Nombre de la métrica, tal como la espera LanceDB.
    """
    return metadatos_de_indice(ruta_indice).get("distancia", DISTANCIA)


#: Banda del número de fragmentos. Traer siempre los mismos es lo que metía
#: treinta fragmentos de doce titulaciones para una pregunta que se contestaba
#: con cuatro. El mínimo evita el desastre contrario: quedarse sin contexto
#: porque el corte fue agresivo.
K_MINIMO: Final[int] = 3
K_MAXIMO: Final[int] = 20

#: Cuánto más lejos que el mejor puede estar un fragmento y seguir entrando.
#: Sale de la rejilla de IT-49: 240 configuraciones sobre las 56 preguntas de
#: dominio y las 10 ajenas del conjunto de evaluación, simuladas sobre los
#: mismos vecinos, que es posible porque este parámetro solo decide dónde se
#: corta una lista ya ordenada.
#:
#: La rejilla sola diría 1,10: la unidad que responde sigue apareciendo en las
#: 56 preguntas y la media de fragmentos cae de 7,2 a 4,2. **Y sin embargo se
#: queda en 1,20**, porque medido sobre el banco del sistema completo ese
#: recorte hace perder tres respuestas de 47: dos preguntas cuyo contexto pasó
#: de 20 a 10 y de 12 a 3 fragmentos dejaron de contestarse bien.
#:
#: Es la lección de este parámetro y conviene no perderla: **que la unidad
#: correcta esté entre lo recuperado no basta para que el modelo responda con
#: ella**. Optimizar el recuperador contra métricas de recuperación mejora la
#: recuperación y empeora el sistema, y solo se ve midiendo el sistema entero.
FACTOR_CORTE: Final[float] = 1.20

#: Distancia por encima de la cual se considera que **nada** es pertinente.
#: El corte relativo quita la cola cuando arriba hay algo bueno, pero no
#: detecta que no haya nada: a «hola buenas tardes» le llegaron diez fragmentos
#: entre 0,170 y 0,182 ---lejísimos pero muy juntos entre sí--- y el sistema
#: contestó con un volcado del plan de estudios.
#:
#: Un suelo de 0,15 queda **por encima de las intrusas**: con él, un modelo de
#: 7B recibía contexto para «me gustan la biología y la salud» ---su mejor
#: fragmento estaba a 0,148--- y contestaba recomendando el «Grado en
#: Ingeniería Biomédica», el «Grado en Ingeniería Química» y el «Grado en
#: Medicina Veterinaria». Ninguno existe en la EPSJ.
#:
#: Se prefiere pecar de estricto: rechazar una pregunta legítima molesta, pero
#: admitir una ajena es lo que produce ese tipo de respuesta.
#:
#: 🔬 **Fijado por la rejilla de IT-49, y es un óptimo exacto.** Medido sobre
#: el conjunto actual, la peor pregunta legítima tiene su mejor fragmento a
#: 0,1367 y las intrusas más próximas están a 0,1039, 0,1358 y 0,1380. En
#: 0,137 se conservan las 56 preguntas de dominio y se rechazan 8 de las 10
#: ajenas; cualquier valor entre 0,139 y 0,145 rechaza solo 7 sin conservar ni
#: una más, y en 0,135 se pierde ya una legítima.
#:
#: **Las dos clases se solapan y ningún umbral puede separarlas**: «¿Puedo
#: estudiar Medicina en la Escuela Politécnica Superior de Jaén?» está a 0,1039,
#: más cerca que cincuenta preguntas legítimas. Que el suelo no sea un filtro
#: de dominio fiable no es una limitación de este valor, sino del mecanismo.
SUELO_PERTINENCIA: Final[float] = 0.137

#: Palabras con las que alguien pide consejo en vez de preguntar un dato. Es
#: una lista **cerrada**, y basta con que aparezca una: al contrario que en el
#: reconocimiento de la cortesía, aquí un falso positivo no rechaza nada, solo
#: hace que se busque con más contexto.
_CONSEJO: Final[frozenset[str]] = frozenset("""
    recomiendas recomiendame recomienda recomendacion recomendarias
    recomendable aconsejas aconsejarias gusta gustan gustaria encanta
    interesa interesan encaja encajan elegir elijo escoger escojo
    orientacion vocacion dudo decidir
    """.split())

#: Y las fórmulas que no son una palabra suelta. Se buscan sobre el texto
#: normalizado entero.
_FORMULAS_DE_CONSEJO: Final[tuple[str, ...]] = (
    "no se que estudiar",
    "no se que carrera",
    "no tengo claro",
    "que estudio",
    "que carrera",
    "se me da bien",
    "se me dan bien",
)

#: Lo que el usuario **cita** en lugar de preguntar. Se descuenta antes de
#: buscar las palabras de consejo, porque una frase entrecomillada es material
#: sobre el que se pide algo, no la petición.
#:
#: Sin esto, «Tradúceme al inglés: "me gustaría estudiar una ingeniería"» se
#: daba por petición de consejo, por la palabra «gustaría» de dentro de la
#: cita. No era un fallo inocuo: a las peticiones de consejo se les entrega la
#: banda completa a propósito, así que una petición ajena al dominio se colaba
#: **y además** el informe la contaba entre las que pasan por diseño. Medido
#: sobre el conjunto de validación de preguntas ajenas.
_ENTRECOMILLADO: Final[re.Pattern[str]] = re.compile(
    r"«[^»]*»|\"[^\"]*\"|“[^”]*”|'[^']{4,}'"
)

#: Lo que se le añade a una petición de consejo antes de incrustarla. La
#: pregunta de un estudiante que no sabe qué estudiar habla de lo que le gusta
#: ---la física, el dibujo--- y no nombra nada del corpus, así que su vector
#: cae lejos de todo. Añadiendo los términos que sí vertebran la colección, la
#: consulta se acerca a las fichas de titulación y a las salidas profesionales,
#: que es justo lo que hace falta para responderla.
TERMINOS_DEL_DOMINIO: Final[str] = (
    "Titulaciones, grados y dobles grados de la Escuela Politécnica Superior "
    "de Jaén, sus asignaturas y sus salidas profesionales."
)


class TitulacionDesconocida(ValueError):
    """El nombre de titulación no está en el catálogo del índice."""


def pide_recomendacion(pregunta: str) -> bool:
    """Si el mensaje pide consejo sobre qué estudiar.

    Se separa del resto de preguntas porque el recuperador la trata distinto,
    y la razón es medible. «No sé qué estudiar, me gusta la física y el dibujo
    técnico» tenía su fragmento más próximo a 0,1466, por encima del suelo de
    pertinencia que regía entonces: el sistema no recuperaba **nada** y contestaba
    que no había
    encontrado información. Con «¿qué me recomiendas?» detrás, la misma frase
    bajaba a 0,1339 y traía nueve fragmentos.

    Que tres palabras decidan si el sistema responde o no es un fallo, y sobre
    todo lo es en esta pregunta: recomendar titulaciones a quien todavía no
    sabe cuál quiere es el cometido del asistente.

    Args:
        pregunta: Mensaje del usuario, tal cual lo escribe.

    Returns:
        ``True`` si pide consejo.
    """
    sin_citas = _ENTRECOMILLADO.sub(" ", pregunta)
    if palabras(sin_citas) & _CONSEJO:
        return True
    normalizada = normalizar(sin_citas)
    return any(f in normalizada for f in _FORMULAS_DE_CONSEJO)


def expandir(pregunta: str) -> str:
    """Añade a la consulta los términos que vertebran la colección.

    Solo se usa para buscar. Al modelo se le entrega siempre la pregunta tal
    como la escribió el estudiante, porque lo que se corrige aquí es dónde se
    busca, no qué se ha preguntado.

    Args:
        pregunta: Mensaje del usuario.

    Returns:
        El texto con el que se consulta el índice.
    """
    return f"{pregunta} {TERMINOS_DEL_DOMINIO}"


def catalogo_del_indice(ruta_indice: Path) -> list[str]:
    """Titulaciones que el índice declara contener.

    Args:
        ruta_indice: Carpeta donde persiste el índice.

    Returns:
        Nombres de titulación, o lista vacía si el índice no los grabó.
    """
    crudo = metadatos_de_indice(ruta_indice).get(CATALOGO)
    return list(json.loads(crudo)) if crudo else []


def resolver_titulacion(texto: str, catalogo: list[str]) -> list[str]:
    """Traduce lo que escribe el usuario a nombres reales del catálogo.

    Resuelve tres cosas de golpe:

    * **Uso.** El filtro exigía el nombre exacto, así que «informática» devolvía
      cero fragmentos y el sistema decía no tener información sobre algo que sí
      está indexado ---un fallo con pinta de respuesta legítima---.
    * **Seguridad.** El filtro se compone interpolando en SQL, porque LanceDB no
      expone consultas parametrizadas, y escapar comillas es una defensa
      artesanal que hoy funciona solo porque ningún nombre de la EPSJ lleva una.
      Resolviendo contra el catálogo, **lo interpolado ya no es texto del
      usuario** sino un nombre del propio índice.
    * **Alcance.** Un nombre parcial como «eléctrica» devuelve la titulación
      simple **y sus dobles grados**, que es lo que le interesa a quien
      pregunta; el nombre completo y exacto devuelve solo esa.

    Args:
        texto: Lo que escribe el usuario.
        catalogo: Titulaciones que declara el índice.

    Returns:
        Nombres del catálogo con los que filtrar.

    Raises:
        TitulacionDesconocida: Si no casa ninguna. Se falla de forma ruidosa
            a propósito: filtrar por algo que no existe devolvería cero
            fragmentos, y no filtrar devolvería los de otra titulación.
    """
    buscado = normalizar(texto)
    exacto = [t for t in catalogo if normalizar(t) == buscado]
    if exacto:
        return exacto
    parciales = [t for t in catalogo if buscado in normalizar(t)]
    if parciales:
        return parciales
    raise TitulacionDesconocida(
        f"«{texto}» no es ninguna de las {len(catalogo)} titulaciones del índice"
    )


def acotar_por_distancia(
    fragmentos: list[Fragmento],
    minimo: int = K_MINIMO,
    maximo: int = K_MAXIMO,
    factor: float = FACTOR_CORTE,
    suelo: float = SUELO_PERTINENCIA,
) -> list[Fragmento]:
    """Recorta la lista donde deja de haber fragmentos pertinentes.

    Un K fijo trae siempre los mismos, pertinentes o no: a «qué asignaturas se
    dan en primer año» le bastaban cuatro fragmentos y entraban treinta, de las
    doce titulaciones, y el modelo mezclaba unas con otras.

    El corte es **relativo al mejor de cada consulta** y no un umbral absoluto,
    porque el fragmento más próximo de una pregunta estaba a 0,076 y el de otra
    a 0,107: un umbral fijo habría dejado la segunda sin nada. La banda protege
    los dos extremos, para que un corte agresivo no deje al modelo sin contexto
    y para que uno flojo no lo inunde.

    Args:
        fragmentos: Fragmentos recuperados, de más a menos próximo.
        minimo: Cuántos se conservan aunque el corte diga menos.
        maximo: Tope, aunque el corte diga más.
        factor: Distancia máxima admitida, como múltiplo de la mejor.
        suelo: Si ni el mejor baja de aquí, no se devuelve ninguno.

    Returns:
        Los fragmentos que quedan dentro del corte, o lista vacía si ninguno
        es pertinente.
    """
    if not fragmentos:
        return []
    # El mínimo no se aplica cuando NADA es pertinente: forzar tres fragmentos
    # irrelevantes es peor que no dar ninguno, porque el modelo responde igual
    # y con la misma seguridad. Con la lista vacía, el prompt dice que no se
    # recuperó nada y esa rama ya está cubierta.
    if fragmentos[0].distancia > suelo:
        return []
    umbral = fragmentos[0].distancia * factor
    dentro = [f for f in fragmentos if f.distancia <= umbral]
    return fragmentos[: max(minimo, min(len(dentro), maximo))]


def escapar(valor: str) -> str:
    """Escapa un literal para la expresión SQL del filtro.

    LanceDB no expone consultas parametrizadas, así que el filtro se compone
    interpolando. Ninguno de los nombres de titulación del corpus lleva hoy
    una comilla simple, pero eso es una propiedad de los datos de la EPSJ y no
    una garantía de este código.

    Args:
        valor: Texto que va dentro de la expresión.

    Returns:
        El texto con las comillas simples duplicadas, según el estándar SQL.
    """
    return valor.replace("'", "''")


def _filtro(
    titulaciones: list[str] | None,
    tipo_asignatura: str | None,
    curso: str | None = None,
) -> str | None:
    """Compone la expresión de filtrado por metadatos.

    ``array_has_any`` casa por elemento exacto sobre la lista de titulaciones.
    Es lo que evita que filtrar por una titulación arrastre los fragmentos de
    otra que la contenga como subcadena: sobre el corpus completo, filtrar por
    «Grado en Ingeniería Eléctrica» devuelve 417 fragmentos por pertenencia
    exacta frente a 584 por subcadena.

    Los nombres que llegan aquí **vienen del catálogo del índice**, no del
    usuario: los resuelve :func:`resolver_titulacion`. El escapado se conserva
    como red de seguridad, pero ya no es lo único que separa una consulta de una
    inyección.

    Args:
        titulaciones: Titulaciones a las que acotar, o ``None``.
        tipo_asignatura: Tipo al que acotar, o ``None``.
        curso: Curso al que acotar, o ``None``. Casa por prefijo para que
            «primer» encuentre «Primer curso», y también «Primer curso (común
            para todos los grados de la Rama Industrial)» si la fuente lo
            rotulara así algún día.

    Returns:
        Expresión SQL, o ``None`` si no hay nada que filtrar.
    """
    condiciones = []
    if titulaciones:
        lista = ", ".join(f"'{escapar(t)}'" for t in titulaciones)
        condiciones.append(f"array_has_any(grados, [{lista}])")
    if curso:
        condiciones.append(f"starts_with(lower(curso), '{escapar(curso.lower())}')")
    if tipo_asignatura is not None:
        condiciones.append(f"tipo_asignatura = '{escapar(tipo_asignatura)}'")
    return " AND ".join(condiciones) if condiciones else None


def recuperar(
    pregunta: str,
    tabla: Any,
    incrustar: Incrustador,
    distancia: str = DISTANCIA,
    k: int = K_POR_DEFECTO,
    grado: str | None = None,
    tipo_asignatura: str | None = None,
    catalogo: list[str] | None = None,
    curso: str | None = None,
    ambito: list[str] | None = None,
) -> list[Fragmento]:
    """Devuelve los ``k`` fragmentos más próximos a la pregunta.

    La métrica se declara **en cada consulta**: LanceDB usa ``l2`` por defecto
    y omitirla no falla, solo ordena por otra cosa. Y el filtro se aplica
    **antes** de buscar (``prefilter``), no después: filtrar el resultado
    dejaría menos de ``k`` fragmentos, o ninguno, y el sistema respondería que
    no tiene información sobre algo que sí está indexado.

    Args:
        pregunta: Pregunta del usuario, tal cual la escribe.
        tabla: Tabla abierta con :func:`abrir_indice`.
        incrustar: Incrustador de consultas, que aplica el prefijo del modelo.
        distancia: Métrica, la que devuelve :func:`distancia_del_indice`.
        k: Cuántos fragmentos recuperar.
        grado: Titulación a la que acotar la búsqueda. Admite el nombre
            parcial: se resuelve contra el catálogo del índice.
        tipo_asignatura: Tipo de asignatura al que acotarla, si procede.
        catalogo: Titulaciones que declara el índice, de
            :func:`catalogo_del_indice`. Hace falta para poder resolver
            ``grado``.
        ambito: Titulaciones **ya resueltas** contra el catálogo, tal como las
            deduce :class:`tfg_uja.conversacion.Conversacion`. Se ignora si se
            pasa ``grado``, que es la petición explícita del usuario y manda
            sobre lo que el sistema haya deducido.

    Returns:
        Fragmentos ordenados de más a menos próximo.

    Raises:
        TitulacionDesconocida: Si ``grado`` no casa con ninguna del catálogo.
    """
    if grado is not None:
        titulaciones: list[str] | None = resolver_titulacion(grado, catalogo or [])
    else:
        # El ámbito ya viene resuelto contra el catálogo (lo deduce la
        # conversación), así que no se vuelve a resolver: hacerlo trataría un
        # nombre oficial como texto del usuario y podría ampliarlo por
        # coincidencia parcial ---«Grado en Ingeniería Eléctrica» arrastraría
        # sus dos dobles grados--- justo cuando ya se sabe cuál es.
        titulaciones = list(ambito) if ambito else None
    vector = incrustar([pregunta])[0]
    consulta = tabla.search(list(vector)).distance_type(distancia).limit(k)
    expresion = _filtro(titulaciones, tipo_asignatura, curso)
    if expresion is not None:
        consulta = consulta.where(expresion, prefilter=True)
    return [
        Fragmento(
            texto=fila["texto"],
            nombre=fila["nombre"],
            grados=list(fila["grados"]),
            origen=fila["origen"],
            distancia=float(fila["_distance"]),
            chunk_index=int(fila["chunk_index"]),
            total_chunks=int(fila["total_chunks"]),
            curso=str(fila.get("curso") or ""),
        )
        for fila in consulta.to_list()
    ]


def contexto_para(
    pregunta: str,
    tabla: Any,
    incrustar: Incrustador,
    respaldo: str = "",
    abierta: bool = False,
    **opciones: Any,
) -> list[Fragmento]:
    """Recupera el contexto con el que se va a responder, ya acotado.

    Reúne las dos operaciones que siempre van juntas ---buscar y recortar--- y
    es donde se trata aparte la petición de consejo, que se busca con la
    consulta ampliada y **sin recortar**: ni suelo ni corte relativo.

    Las dos excepciones tienen el mismo motivo: una recomendación no la responde
    un puñado de fragmentos parecidos a la pregunta. El suelo comprueba que la
    pregunta se parezca a algo de la colección, y esta no se parece a nada por
    construcción ---habla de lo que le gusta al estudiante, no de lo que publica
    la Escuela---. El corte relativo hace daño por otra vía: con el mejor
    fragmento a 0,103 dejaba entrar tres, los del catálogo y las salidas, y
    **ninguno con asignaturas dentro**; de las once asignaturas que el modelo
    puso entonces como ejemplo, siete no existen en la EPSJ. No las inventó por
    desobedecer, sino porque no se le dio ninguna y la pregunta pedía concretar:
    dar poco contexto a una pregunta abierta produce invención igual que darle
    ninguno.

    Args:
        pregunta: Mensaje del usuario, tal cual lo escribe.
        tabla: Tabla abierta con :func:`abrir_indice`.
        incrustar: Incrustador de consultas.
        respaldo: Con qué volver a buscar si la primera búsqueda vuelve vacía.
            Lo compone :class:`tfg_uja.conversacion.Consulta`.
        abierta: Si la consulta pregunta por la oferta de la Escuela en general.
            Se trata igual que una petición de consejo y por el mismo motivo:
            «enséñame todas las titulaciones» no se parece a ninguna unidad del
            corpus, su mejor fragmento se queda en 0,156 ---por encima del
            suelo--- y se responde con el catálogo. Lo dice quien decide el
            ámbito; ``pide_recomendacion`` reconoce por su cuenta las peticiones
            de consejo.
        **opciones: El resto de argumentos de :func:`recuperar`.

    Returns:
        Los fragmentos que se le entregan al modelo.
    """
    consejo = abierta or pide_recomendacion(pregunta)
    consulta = expandir(pregunta) if consejo else pregunta
    traidos = _contexto_recuperado(
        consulta, tabla, incrustar, sin_recorte=consejo, opciones=opciones
    )
    if consejo:
        return traidos
    fragmentos = traidos
    if fragmentos or not respaldo:
        return fragmentos
    # Segundo intento con la pregunta anterior delante: tras preguntar por las
    # optativas de una titulación, «¿y cuántas son en total?» tenía su mejor
    # fragmento a 0,1722 y se quedaba sin contexto, de modo que el sistema
    # decía no haber encontrado información sobre lo que él mismo acababa de
    # contestar.
    #
    # El reintento se hace **solo con la lista vacía**, que es un hecho
    # comprobado y no una conjetura sobre la frase, y cuesta una búsqueda de
    # cinco centésimas de segundo en el único caso en que la alternativa es no
    # responder.
    return _contexto_recuperado(
        respaldo, tabla, incrustar, sin_recorte=False, opciones=opciones
    )


def _contexto_recuperado(
    pregunta: str,
    tabla: Any,
    incrustar: Incrustador,
    *,
    sin_recorte: bool,
    opciones: dict[str, Any],
) -> list[Fragmento]:
    """Busca y acota una consulta sin ocultar ninguno de sus ámbitos.

    Una consulta filtrada por varias titulaciones produce un único ranking.
    Eso no garantiza que todas estén representadas: una puede ocupar los
    veinte vecinos aunque la pregunta pida compararla con otra. Para RU-04 se
    hace la misma búsqueda con un filtro exacto por titulación y se alternan
    los resultados. No se añade otro *scorer*: dentro de cada grupo siguen
    mandando la distancia y el corte ya medidos en IT-49.

    Args:
        pregunta: Texto que se incrusta.
        tabla: Tabla vectorial abierta.
        incrustar: Incrustador de consultas.
        sin_recorte: Si se conservan los vecinos sin suelo ni corte relativo.
        opciones: Argumentos que recibe :func:`recuperar`.

    Returns:
        Hasta :data:`K_MAXIMO` fragmentos, alternados por titulación cuando el
        ámbito contiene varias.
    """
    ambito = opciones.get("ambito")
    if not isinstance(ambito, list) or len(ambito) < 2:
        recuperados = recuperar(pregunta, tabla, incrustar, **opciones)
        return (
            recuperados[:K_MAXIMO] if sin_recorte else acotar_por_distancia(recuperados)
        )

    por_titulacion: list[list[Fragmento]] = []
    for titulacion in ambito:
        propias = dict(opciones)
        propias["ambito"] = [titulacion]
        recuperados = recuperar(pregunta, tabla, incrustar, **propias)
        por_titulacion.append(
            recuperados[:K_MAXIMO] if sin_recorte else acotar_por_distancia(recuperados)
        )
    return _intercalar(por_titulacion)


def _intercalar(grupos: list[list[Fragmento]]) -> list[Fragmento]:
    """Alterna rankings conservando el orden interno de cada uno, sin repetir.

    **Deduplica, y no es un detalle.** Una unidad impartida en varias
    titulaciones aparece en el ranking de cada una, así que alternar a secas la
    devolvía una vez por titulación del ámbito: con una unidad compartida de
    seis fragmentos y dos titulaciones salían catorce fragmentos de los que solo
    ocho eran distintos. El tope se agotaba con texto repetido justo en las
    consultas comparativas para las que existe esta función.

    La clave es ``(origen, nombre, grados, chunk_index)`` y no el fragmento
    porque :class:`Fragmento` no es hasheable ---lleva ``grados`` como lista---:
    es la identidad de unidad de IT-126, la misma que usan
    :func:`tfg_uja.generador.ordenar_contexto` y
    :func:`tfg_uja.evaluacion.unidad_de_chunk`, más la posición dentro de ella.

    **Las titulaciones son parte de la identidad y no un adorno.** Sin ellas,
    dos unidades que solo comparten el nombre colisionan y la segunda se
    descarta ---ocho nombres de guía del corpus son más de una unidad, y
    «Trabajo fin de Grado» son cinco---, con lo que el modelo redactaría la
    comparación con la mitad de los datos y sin forma de saberlo. Que la clave
    lleve ``grados`` no reabre lo que arregló IT-120: una unidad genuinamente
    compartida llega a los dos grupos con la **misma** lista, la del índice, que
    enumera todas sus titulaciones y no la del filtro con el que se buscó.

    Args:
        grupos: Fragmentos ya ordenados y acotados de cada titulación.

    Returns:
        Como máximo :data:`K_MAXIMO` fragmentos, todos distintos.
    """
    vistos: set[tuple[str, str, tuple[str, ...], int]] = set()
    mezclados: list[Fragmento] = []
    for fila in zip_longest(*grupos):
        for fragmento in fila:
            if fragmento is None:
                continue
            clave = (
                fragmento.origen,
                fragmento.nombre,
                tuple(fragmento.grados),
                fragmento.chunk_index,
            )
            if clave in vistos:
                continue
            vistos.add(clave)
            mezclados.append(fragmento)
            if len(mezclados) == K_MAXIMO:
                return mezclados
    return mezclados

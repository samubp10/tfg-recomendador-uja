"""Recuperación de fragmentos del índice vectorial (IT-37).

Es la mitad que el indexador dejó sin escribir a propósito: ``indexer.py``
construye el índice y no lo consulta, porque diseñar la consulta antes de que
existiera el recuperador habría sido inventarse sus necesidades.

Este módulo lee del índice **lo que el índice dice de sí mismo** en vez de
suponerlo. Los tres datos que graba :func:`tfg_uja.indexer.reconstruir_indice`
---modelo, prefijo y métrica de distancia--- corresponden a tres formas de
equivocarse que **no producen ningún error**, solo resultados peores:

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
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import lancedb

from tfg_uja.incrustaciones import Incrustador
from tfg_uja.indexer import CATALOGO, COLECCION, DISTANCIA, metadatos_de_indice
from tfg_uja.text_cleaner import normalizar, palabras

#: Fragmentos que se recuperan por consulta cuando no se dice otra cosa.
#: Es un valor de partida, no una decisión cerrada: fijarlo es objeto de
#: IT-49, que lo barrerá con el conjunto de evaluación.
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
#: 🔴 **Provisional.** Sale de mirar tres preguntas, no de un barrido: en ellas
#: el salto entre lo pertinente y el ruido estaba en 1,22 y 1,25. Fijarlo en
#: serio es IT-49, con las 50 preguntas del conjunto de evaluación.
FACTOR_CORTE: Final[float] = 1.20

#: Distancia por encima de la cual se considera que **nada** es pertinente.
#: El corte relativo quita la cola cuando arriba hay algo bueno, pero no
#: detecta que no haya nada: a «hola buenas tardes» le llegaron diez fragmentos
#: entre 0,170 y 0,182 ---lejísimos pero muy juntos entre sí--- y el sistema
#: contestó con un volcado del plan de estudios.
#:
#: 🔴 **Provisional, igual que el factor.** Las cinco preguntas reales medidas
#: tenían su mejor fragmento entre 0,076 y 0,112, así que 0,15 las deja pasar
#: todas y descarta el saludo; pero cinco preguntas no son un barrido y el
#: valor lo fija IT-49. El rechazo por dominio es IT-87, que es otra cosa.
SUELO_PERTINENCIA: Final[float] = 0.15


class TitulacionDesconocida(ValueError):
    """El nombre de titulación no está en el catálogo del índice."""


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

    Resuelve tres cosas de golpe. La primera es que el filtro **exigía el
    nombre exacto**: escribir «informática» devolvía cero fragmentos, y el
    sistema respondía que no tenía información sobre algo que sí está
    indexado, que es un fallo con toda la pinta de respuesta legítima.

    La segunda es de seguridad. El filtro se compone interpolando texto en una
    expresión SQL, porque LanceDB no expone consultas parametrizadas; escapar
    las comillas es una defensa artesanal que hoy funciona solo porque ningún
    nombre de la EPSJ lleva una. Resolviendo contra el catálogo, **lo que se
    interpola ya no es texto del usuario** sino un nombre del propio índice.

    Y la tercera es de alcance: un nombre parcial como «eléctrica» devuelve la
    titulación simple **y sus dobles grados**, que es lo que le interesa a
    quien pregunta. El nombre completo y exacto devuelve solo esa.

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

    Un K fijo trae siempre los mismos, pertinentes o no: para «qué asignaturas
    se dan en primer año» bastaban cuatro fragmentos y entraban treinta, de las
    doce titulaciones, y el modelo mezcló asignaturas de unas y otras.

    El corte es **relativo al mejor de cada consulta**, no un umbral absoluto.
    Medido: el fragmento más próximo de una pregunta estaba a 0,076 y el de
    otra a 0,107, así que un umbral fijo habría dejado la segunda sin nada.

    La banda protege los dos extremos: nunca menos del mínimo, para que un
    corte agresivo no deje al modelo sin contexto, y nunca más del máximo.

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


def _escapar(valor: str) -> str:
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

    Los nombres que llegan aquí **ya vienen del catálogo del índice**, no del
    usuario: los resuelve :func:`resolver_titulacion`. El escapado se conserva
    como red de seguridad, pero deja de ser lo único que separa una consulta de
    una inyección.

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
        lista = ", ".join(f"'{_escapar(t)}'" for t in titulaciones)
        condiciones.append(f"array_has_any(grados, [{lista}])")
    if curso:
        condiciones.append(f"starts_with(lower(curso), '{_escapar(curso.lower())}')")
    if tipo_asignatura is not None:
        condiciones.append(f"tipo_asignatura = '{_escapar(tipo_asignatura)}'")
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

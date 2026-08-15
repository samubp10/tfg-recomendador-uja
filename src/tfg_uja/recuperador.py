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

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import lancedb

from tfg_uja.incrustaciones import Incrustador
from tfg_uja.indexer import COLECCION, DISTANCIA, metadatos_de_indice

#: Fragmentos que se recuperan por consulta cuando no se dice otra cosa.
#: Es un valor de partida, no una decisión cerrada: fijarlo es objeto de
#: IT-49, que lo barrerá con el conjunto de evaluación.
K_POR_DEFECTO: Final[int] = 10


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
    """

    texto: str
    nombre: str
    grados: list[str]
    origen: str
    distancia: float


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


def _filtro(grado: str | None, tipo_asignatura: str | None) -> str | None:
    """Compone la expresión de filtrado por metadatos.

    ``array_has_any`` casa por elemento exacto sobre la lista de titulaciones.
    Es lo que evita que filtrar por una titulación arrastre los fragmentos de
    otra que la contenga como subcadena: sobre el corpus completo, filtrar por
    «Grado en Ingeniería Eléctrica» devuelve 417 fragmentos por pertenencia
    exacta frente a 584 por subcadena.

    Args:
        grado: Titulación a la que acotar, o ``None``.
        tipo_asignatura: Tipo al que acotar, o ``None``.

    Returns:
        Expresión SQL, o ``None`` si no hay nada que filtrar.
    """
    condiciones = []
    if grado is not None:
        condiciones.append(f"array_has_any(grados, ['{_escapar(grado)}'])")
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
        grado: Titulación a la que acotar la búsqueda, si procede.
        tipo_asignatura: Tipo de asignatura al que acotarla, si procede.

    Returns:
        Fragmentos ordenados de más a menos próximo.
    """
    vector = incrustar([pregunta])[0]
    consulta = tabla.search(list(vector)).distance_type(distancia).limit(k)
    expresion = _filtro(grado, tipo_asignatura)
    if expresion is not None:
        consulta = consulta.where(expresion, prefilter=True)
    return [
        Fragmento(
            texto=fila["texto"],
            nombre=fila["nombre"],
            grados=list(fila["grados"]),
            origen=fila["origen"],
            distancia=float(fila["_distance"]),
        )
        for fila in consulta.to_list()
    ]

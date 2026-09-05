"""Recuperación de fragmentos del índice vectorial (IT-37)."""

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

# Punto de partida de la banda dinámica; acotar_por_distancia decide el número final.
K_POR_DEFECTO: Final[int] = 10

#: Longitud a partir de la cual una palabra del catálogo sirve para reconocer
#: una titulación. Por debajo quedan las partículas ---«y», «de», «en»--- que
#: aparecen en cualquier frase y reconocerían una titulación en todas.
LARGO_DISTINTIVO: Final[int] = 4


def palabras_distintivas(catalogo: list[str]) -> set[str]:
    """Palabras que identifican a una titulación concreta y no a todas."""
    conteo = Counter(p for titulacion in catalogo for p in palabras(titulacion))
    tope = len(catalogo) / 2
    return {
        p for p, veces in conteo.items() if veces < tope and len(p) >= LARGO_DISTINTIVO
    }


@dataclass(frozen=True)
class Fragmento:
    """Un fragmento recuperado, con lo que hace falta para citarlo."""

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
    """Métrica con la que hay que consultar el índice."""
    return metadatos_de_indice(ruta_indice).get("distancia", DISTANCIA)


# Banda de fragmentos: limita ruido sin recortar demasiado el contexto.
K_MINIMO: Final[int] = 3
K_MAXIMO: Final[int] = 20

# Corte relativo estudiado en 240 configuraciones de IT-49.

# Se conserva 1,20: reducir a 1,10 mantuvo la recuperación pero perdió tres respuestas
# del banco completo.

# Recuperar la unidad correcta no garantiza que el modelo tenga contexto suficiente.
FACTOR_CORTE: Final[float] = 1.20

# Si la mejor distancia supera el suelo, no se aporta contexto.

# 0,15 admitía preguntas ajenas que acababan en titulaciones inventadas.

#: Se prefiere pecar de estricto: rechazar una pregunta legítima molesta, pero
#: admitir una ajena es lo que produce ese tipo de respuesta.

# IT-49: 0,137 conserva las 56 preguntas de dominio y rechaza 8 de las 10 ajenas del
# conjunto medido.

# Las distancias de ambos grupos se solapan: el suelo por sí solo no filtra el dominio.
SUELO_PERTINENCIA: Final[float] = 0.137

# Una coincidencia amplía la búsqueda de consejo; no rechaza la pregunta.
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

#: Lo que el usuario cita en lugar de preguntar. Se descuenta antes de
#: buscar las palabras de consejo, porque una frase entrecomillada es material
#: sobre el que se pide algo, no la petición.

# Evita interpretar una cita dentro de una orden de traducción como petición de consejo.
_ENTRECOMILLADO: Final[re.Pattern[str]] = re.compile(
    r"«[^»]*»|\"[^\"]*\"|“[^”]*”|'[^']{4,}'"
)

# Añade vocabulario del corpus a consultas sobre intereses que no nombran titulaciones.
TERMINOS_DEL_DOMINIO: Final[str] = (
    "Titulaciones, grados y dobles grados de la Escuela Politécnica Superior "
    "de Jaén, sus asignaturas y sus salidas profesionales."
)


class TitulacionDesconocida(ValueError):
    """El nombre de titulación no está en el catálogo del índice."""


def pide_recomendacion(pregunta: str) -> bool:
    """Si el mensaje pide consejo sobre qué estudiar."""
    sin_citas = _ENTRECOMILLADO.sub(" ", pregunta)
    if palabras(sin_citas) & _CONSEJO:
        return True
    normalizada = normalizar(sin_citas)
    return any(f in normalizada for f in _FORMULAS_DE_CONSEJO)


def expandir(pregunta: str) -> str:
    """Añade a la consulta los términos que vertebran la colección."""
    return f"{pregunta} {TERMINOS_DEL_DOMINIO}"


def catalogo_del_indice(ruta_indice: Path) -> list[str]:
    """Titulaciones que el índice declara contener."""
    crudo = metadatos_de_indice(ruta_indice).get(CATALOGO)
    return list(json.loads(crudo)) if crudo else []


def resolver_titulacion(texto: str, catalogo: list[str]) -> list[str]:
    """Traduce lo que escribe el usuario a nombres reales del catálogo.

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
    """Recorta la lista donde deja de haber fragmentos pertinentes."""
    if not fragmentos:
        return []
    # El mínimo no obliga a recuperar fragmentos si ninguno es pertinente.
    if fragmentos[0].distancia > suelo:
        return []
    umbral = fragmentos[0].distancia * factor
    dentro = [f for f in fragmentos if f.distancia <= umbral]
    return fragmentos[: max(minimo, min(len(dentro), maximo))]


def escapar(valor: str) -> str:
    """Escapa un literal para la expresión SQL del filtro."""
    return valor.replace("'", "''")


def _filtro(
    titulaciones: list[str] | None,
    tipo_asignatura: str | None,
    curso: str | None = None,
) -> str | None:
    """Compone la expresión de filtrado por metadatos."""
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

    Raises:
        TitulacionDesconocida: Si ``grado`` no casa con ninguna del catálogo.
    """
    if grado is not None:
        titulaciones: list[str] | None = resolver_titulacion(grado, catalogo or [])
    else:
        # El ámbito ya resuelto se filtra por nombre exacto, sin arrastrar dobles por
        # coincidencia parcial.
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
    """Recupera el contexto con el que se va a responder, ya acotado."""
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
    # Reintenta con la pregunta anterior solo si la primera búsqueda no recupera
    # contexto.
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
    """Busca y acota una consulta sin ocultar ninguno de sus ámbitos."""
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
    """Alterna rankings conservando el orden interno de cada uno, sin repetir."""
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

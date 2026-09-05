"""Troceado (chunking) del dataset extraído por el spider."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Final

from tfg_uja.text_cleaner import normalizar_rotulo

# El antiguo _normalizar colapsaba espacios interiores; el del spider no.
# IT-137 sustituyó ambos tras verificar sus usos reales; véase normalizar_rotulo.

# Objetivo elegido por la rejilla de IT-16: 100 % del máximo (ADR-0001).
TAMANO_OBJETIVO: Final[int] = 900

#: Tamaño máximo estricto de un chunk. Ningún chunk lo supera: un párrafo
#: más largo se divide por frases.

# 900 conserva la mejora al controlar por número de fragmentos; 600 no (ADR-0001).

# Con 900 ningún fragmento del experimento excedió la ventana del modelo.
TAMANO_MAXIMO: Final[int] = 900

#: Tamaño mínimo de un chunk. Un fragmento residual por debajo de este
#: umbral se fusiona con el chunk anterior de su misma unidad (IT-09) para
#: no contaminar el índice con fragmentos sin entidad.
TAMANO_MINIMO: Final[int] = 200

#: Nombres legibles de los tipos de asignatura, para los encabezados.
_NOMBRE_TIPO: Final[dict[str, str]] = {
    "FB": "asignatura de formación básica",
    "OB": "asignatura obligatoria",
    "OP": "asignatura optativa",
    "OB-IS": "asignatura obligatoria de la especialidad Ingeniería del Software",
    "OB-SI": "asignatura obligatoria de la especialidad Sistemas de Información",
    "OB-TI": "asignatura obligatoria de la especialidad Tecnologías de la Información",
    "TFG": "Trabajo Fin de Grado",
}

#: Agrupaciones del plan de estudios que el corpus publica como listado
#: (IT-100). La clave es el nombre que aparece en el encabezado del fragmento;
#: el valor, los tipos de asignatura que agrupa.

# El listado obligatorio reúne FB, OB, especialidades y TFG; cada fragmento conserva su
# tipo concreto.
_GRUPOS_PLAN: Final[dict[str, frozenset[str]]] = {
    "obligatorias": frozenset({"FB", "OB", "OB-IS", "OB-SI", "OB-TI", "TFG"}),
    "optativas": frozenset({"OP"}),
}

#: Ordinales de curso, en el orden en que se estudian. Se usan para ordenar
#: los listados por curso: un rótulo disyuntivo como «Tercer o cuarto curso»
#: ordena por el primero que nombra, que es lo antes que puede cursarse.

# El generador comparte este orden para presentar los cursos sin discrepancias.
ORDEN_CURSOS: Final[tuple[str, ...]] = (
    "primer",
    "segundo",
    "tercer",
    "cuarto",
    "quinto",
    "sexto",
)

_FRONTERA_FRASE: Final[re.Pattern[str]] = re.compile(r"(?<=[.;!?])\s+")

# Este rótulo agrupa optativas comunes; no representa una mención.
_COMUN_A_TODAS: Final[str] = "comun a todas las menciones"


# El sufijo «(GIE)» o «(GIOI)» identifica el grado base y no pertenece al nombre de la
# asignatura.
_SUFIJO_GRADO: Final[re.Pattern[str]] = re.compile(r"\s*\([A-Z]{2,8}\)\s*$")


def _dividir_en_piezas(texto: str, maximo: int) -> list[str]:
    """Divide un texto en piezas que no superan el tamaño máximo."""
    piezas: list[str] = []
    for parrafo in re.split(r"\n{2,}", texto):
        parrafo = parrafo.strip()
        if not parrafo:
            continue
        if len(parrafo) <= maximo:
            piezas.append(parrafo)
            continue
        for frase in _FRONTERA_FRASE.split(parrafo):
            frase = frase.strip()
            while len(frase) > maximo:
                corte = frase.rfind(" ", 0, maximo)
                if corte <= 0:
                    corte = maximo
                piezas.append(frase[:corte].strip())
                frase = frase[corte:].strip()
            if frase:
                piezas.append(frase)
    return piezas


def _empaquetar(piezas: list[str], objetivo: int, maximo: int) -> list[str]:
    """Agrupa piezas consecutivas en chunks cercanos al tamaño objetivo."""
    chunks: list[str] = []
    actual = ""
    for pieza in piezas:
        candidata = f"{actual}\n{pieza}".strip() if actual else pieza
        if actual and len(candidata) > objetivo:
            chunks.append(actual)
            actual = pieza
        else:
            actual = candidata
    if actual:
        chunks.append(actual)
    return chunks


def _fusionar_pequenos(chunks: list[str], minimo: int, maximo: int) -> list[str]:
    """Fusiona con su vecino los chunks por debajo del mínimo (IT-09)."""
    resultado = list(chunks)
    i = 0
    while i < len(resultado):
        if len(resultado[i]) >= minimo or len(resultado) == 1:
            i += 1
            continue
        vecino = i - 1 if i > 0 else i + 1
        primero, segundo = min(i, vecino), max(i, vecino)
        combinado = f"{resultado[primero]}\n{resultado[segundo]}"
        if len(combinado) <= maximo:
            # El par cabe junto: dos fragmentos pasan a ser uno.
            resultado[primero : segundo + 1] = [combinado]
            i = 0  # hay progreso, se re-evalúa desde el principio
            continue
        # Reequilibrar: dos mitades equilibradas en lugar de un chunk
        # desbordado (caso real: la guía de Geofísica, 13212010).
        objetivo_local = min(len(combinado) // 2 + 1, maximo)
        piezas = _dividir_en_piezas(combinado, maximo)
        reequilibrado = _empaquetar(piezas, objetivo_local, maximo)
        if len(reequilibrado) > segundo - primero + 1:
            # Si el reparto aumenta los fragmentos, conserva el residual corto; así
            # termina la recursión.
            i = segundo + 1
            continue
        resultado[primero : segundo + 1] = reequilibrado
        if len(reequilibrado) < segundo - primero + 1:
            i = 0  # el reparto ha reducido el número de fragmentos
        else:
            # El reparto no reduce nada: puede ser el mismo de partida. Se
            # avanza en vez de reiniciar, para no repetirlo indefinidamente.
            i = segundo + 1
    return resultado


def _por_metadatos_del_plan(
    pares: list[tuple[str, str | None]],
    nombre: str,
    asignaturas: dict[tuple[str, str], dict[str, Any]],
) -> dict[tuple[Any, ...], list[tuple[str, str | None]]]:
    """Reparte las titulaciones de una guía según lo que el encabezado afirma."""
    subgrupos: dict[tuple[Any, ...], list[tuple[str, str | None]]] = {}
    for grado, codigo in pares:
        asignatura = asignaturas.get(_clave_asignatura(grado, codigo, nombre))
        clave = (
            (
                asignatura.get("tipo_asignatura"),
                asignatura.get("ects"),
                asignatura.get("curso"),
                asignatura.get("cuatrimestre"),
            )
            if asignatura
            # Sin ficha no hay nada que afirmar, y todas las que están en ese
            # caso comparten encabezado: van juntas en vez de una por cabeza.
            else ()
        )
        subgrupos.setdefault(clave, []).append((grado, codigo))
    return subgrupos


def _encabezado_asignatura(asignatura: dict[str, Any], grados: list[str]) -> str:
    """Compone el encabezado autocontenido de los chunks de una asignatura."""
    tipo = _NOMBRE_TIPO.get(
        asignatura["tipo_asignatura"], f"asignatura ({asignatura['tipo_asignatura']})"
    )
    partes = [f"«{asignatura['nombre']}», {tipo}"]
    if asignatura.get("ects"):
        partes.append(f"de {asignatura['ects']} ECTS")
    if len(grados) == 1:
        partes.append(f"del {grados[0]}")
    else:
        # Las menciones son específicas de cada titulación, por lo que no se
        # enuncian en una unidad compartida por varias.
        partes.append(f"impartida en {len(grados)} titulaciones: {'; '.join(grados)}")
    encabezado = " ".join(partes)
    if len(grados) == 1 and asignatura.get("menciones"):
        encabezado += f" (mención: {', '.join(asignatura['menciones'])})"
    # El modelo necesita leer el curso en el texto, además de disponer del metadato.
    situacion = _situacion_en_el_plan(asignatura)
    if situacion:
        encabezado += f". Se imparte en {situacion}"
    if not asignatura.get("ofertada", True):
        encabezado += ". No ofertada en el curso rastreado"
    # Explicita el dato ausente para que el modelo no lo complete por su cuenta.
    if not asignatura.get("ects"):
        encabezado += ". La web de la EPSJ no publica sus créditos"
    return encabezado + "."


def _situacion_en_el_plan(asignatura: dict[str, Any]) -> str:
    """Redacta en qué curso y cuatrimestre se imparte una asignatura."""
    curso = (asignatura.get("curso") or "").strip()
    cuatrimestre = (asignatura.get("cuatrimestre") or "").strip()
    if curso and cuatrimestre:
        return f"el {cuatrimestre.lower()} de {curso.lower()}"
    if curso:
        return f"el {curso.lower()}"
    if cuatrimestre:
        # Explicita el curso ausente: el cuatrimestre por sí solo no lo determina.
        return f"el {cuatrimestre.lower()}, sin curso asignado en el plan"
    return ""


def _encabezado_sin_metadatos(nombre: str, grados: list[str]) -> str:
    """Encabezado de respaldo cuando no hay asignatura asociada a la guía."""
    if len(grados) == 1:
        return f"«{nombre}», asignatura del {grados[0]}."
    return f"«{nombre}», asignatura impartida en: {'; '.join(grados)}."


def _chunks_de_unidad(
    encabezado: str,
    texto: str,
    base: dict[str, Any],
    origen: str,
    tamanos: tuple[int, int, int] = (TAMANO_OBJETIVO, TAMANO_MAXIMO, TAMANO_MINIMO),
) -> list[dict[str, Any]]:
    """Genera los chunks de una unidad semántica completa."""
    # Descuenta encabezado y salto de línea para respetar el máximo del fragmento
    # completo.
    tam_objetivo, tam_maximo, tam_minimo = tamanos
    hueco = len(encabezado) + 1
    maximo = max(tam_maximo - hueco, 1)
    objetivo = max(tam_objetivo - hueco, 1)
    minimo = min(tam_minimo, maximo)
    piezas = _dividir_en_piezas(texto, maximo)
    cuerpos = _empaquetar(piezas, objetivo, maximo)
    cuerpos = _fusionar_pequenos(cuerpos, minimo, maximo)
    total = len(cuerpos)
    return [
        {
            "tipo": "chunk",
            "origen": origen,
            **base,
            "texto": f"{encabezado}\n{cuerpo}".strip(),
            "chunk_index": indice,
            "total_chunks": total,
        }
        for indice, cuerpo in enumerate(cuerpos)
    ]


def _clave_asignatura(grado: str, codigo: str | None, nombre: str) -> tuple[str, str]:
    """Identifica una asignatura dentro de su titulación."""
    return (grado, codigo or nombre)


def _creditos(asignatura: dict[str, Any]) -> str:
    """Compone el paréntesis de créditos de una línea de listado."""
    if asignatura["ects"]:
        return f" ({asignatura['ects']} ECTS)"
    return " (créditos no publicados)"


def _chunks_de_plan_de_estudios(
    items: list[dict[str, Any]],
    tamanos: tuple[int, int, int],
) -> list[dict[str, Any]]:
    """Genera el listado de asignaturas de cada titulación, por grupo (IT-100)."""
    por_grado: dict[str, list[dict[str, Any]]] = {}
    for a in items:
        if a["tipo"] == "asignatura":
            por_grado.setdefault(a["grado"], []).append(a)

    chunks: list[dict[str, Any]] = []
    for grado in sorted(por_grado):
        for grupo, tipos in _GRUPOS_PLAN.items():
            asignaturas = [a for a in por_grado[grado] if a["tipo_asignatura"] in tipos]
            if not asignaturas:
                continue
            for curso, del_curso in _por_curso(asignaturas):
                # Orden alfabético y no el de la fuente: el de la fuente depende
                # del orden de las filas de la tabla, que ya ha cambiado una vez
                # (IT-76). Alfabético es estable y además se lee mejor.
                lineas = []
                for a in sorted(del_curso, key=lambda x: x["nombre"]):
                    # El ECTS ausente se refleja, no se imputa (decisión 9).
                    lineas.append(f"{a['nombre']}{_creditos(a)}.")
                titulo = f"Asignaturas {grupo} de {curso.lower()} del {grado}"
                if not curso:
                    titulo = f"Asignaturas {grupo} del {grado}"
                encabezado = f"{titulo}. En total son {len(del_curso)}:"
                base = {
                    "grados": [grado],
                    "codigos": [None],
                    "nombre": titulo,
                    "tipo_asignatura": "",
                    "curso": curso,
                }
                chunks.extend(
                    _chunks_de_unidad(
                        # Un párrafo por asignatura permite cortar entre asignaturas sin
                        # mezclarlas.
                        encabezado,
                        "\n\n".join(lineas),
                        base,
                        "plan_de_estudios",
                        tamanos,
                    )
                )
    return chunks


def _duracion_en_cursos(asignaturas: list[dict[str, Any]]) -> int:
    """Cuántos cursos abarca un plan, según el ordinal más alto que rotula."""
    tope = 0
    for asignatura in asignaturas:
        rotulo = (asignatura.get("curso") or "").lower()
        for posicion, ordinal in enumerate(ORDEN_CURSOS, start=1):
            if ordinal in rotulo:
                tope = max(tope, posicion)
    return tope


def _chunks_de_catalogo(
    items: list[dict[str, Any]],
    tamanos: tuple[int, int, int],
) -> list[dict[str, Any]]:
    """Genera el fragmento que enumera la oferta de la Escuela (IT-107)."""
    grados = sorted(
        (g for g in items if g["tipo"] == "grado"), key=lambda g: g["nombre"]
    )
    if not grados:
        return []
    simples = [g["nombre"] for g in grados if not g.get("es_doble_grado")]
    dobles = [g["nombre"] for g in grados if g.get("es_doble_grado")]

    def base_de(nombres: list[str], titulo: str) -> dict[str, Any]:
        return {
            # Las titulaciones de las que habla el fragmento. La lista no puede
            # ir vacía: el verificador exige que `grados` y `codigos` sean
            # listas paralelas y no vacías.
            "grados": nombres,
            "codigos": [None] * len(nombres),
            "nombre": titulo,
            "tipo_asignatura": "",
            "curso": "",
        }

    titulo = "Titulaciones que se imparten en la Escuela Politécnica Superior de Jaén"
    encabezado = (
        f"{titulo}. En total son {len(grados)}: {len(simples)} grados y "
        f"{len(dobles)} dobles grados."
    )
    bloques = []
    if simples:
        bloques.append("Grados:\n" + "\n".join(f"{n}." for n in simples))
    if dobles:
        bloques.append("Dobles grados:\n" + "\n".join(f"{n}." for n in dobles))
    chunks = _chunks_de_unidad(
        encabezado,
        "\n\n".join(bloques),
        base_de([g["nombre"] for g in grados], titulo),
        "catalogo",
        tamanos,
    )

    # El catálogo por familia permite recuperar el listado completo de dobles grados.
    for familia, nombres in (("Grados", simples), ("Dobles grados", dobles)):
        if not nombres:
            continue
        titulo_familia = (
            f"{familia} que se imparten en la Escuela Politécnica Superior de Jaén"
        )
        chunks.extend(
            _chunks_de_unidad(
                f"{titulo_familia}. En total son {len(nombres)}:",
                "\n\n".join(f"{n}." for n in nombres),
                base_de(nombres, titulo_familia),
                "catalogo",
                tamanos,
            )
        )
    return chunks


def _chunks_de_ficha(
    items: list[dict[str, Any]],
    tamanos: tuple[int, int, int],
) -> list[dict[str, Any]]:
    """Genera la ficha de cifras de cada titulación (IT-107)."""
    por_grado: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if item["tipo"] == "asignatura":
            por_grado.setdefault(item["grado"], []).append(item)

    chunks: list[dict[str, Any]] = []
    for grado in sorted(
        (g for g in items if g["tipo"] == "grado"), key=lambda g: g["nombre"]
    ):
        nombre = grado["nombre"]
        titulo = f"Datos generales del {nombre}"
        base = {
            "grados": [nombre],
            "codigos": [None],
            "nombre": titulo,
            "tipo_asignatura": "",
            "curso": "",
        }
        suyas = por_grado.get(nombre, [])
        if not suyas:
            chunks.extend(
                _chunks_de_unidad(
                    f"{titulo}.",
                    "La web de la EPSJ no publica el plan de estudios de esta "
                    "titulación, por lo que no se dispone de sus asignaturas.",
                    base,
                    "ficha_titulacion",
                    tamanos,
                )
            )
            continue

        optativas = [
            a for a in suyas if a["tipo_asignatura"] in _GRUPOS_PLAN["optativas"]
        ]
        obligatorias = [a for a in suyas if a not in optativas]
        cursos = _duracion_en_cursos(suyas)
        frases = [
            f"En total tiene {len(suyas)} asignaturas: {len(obligatorias)} "
            f"obligatorias y {len(optativas)} optativas."
        ]
        if cursos:
            frases.append(f"El plan de estudios se organiza en {cursos} cursos.")
        if not optativas:
            frases.append(
                "La web de la EPSJ no publica optativas para esta titulación."
            )
        # Enumera las menciones juntas para que el recuento no dependa de recuperar sus
        # fichas sueltas.
        menciones = sorted(
            {
                m
                for a in suyas
                for m in (a.get("menciones") or [])
                if normalizar_rotulo(m) != _COMUN_A_TODAS
            }
        )
        if menciones:
            frases.append(f"Tiene {len(menciones)} menciones: {', '.join(menciones)}.")
        reparto = [
            f"{curso}: {len(del_curso)} asignaturas."
            for curso, del_curso in _por_curso(obligatorias)
            if curso
        ]
        cuerpo = " ".join(frases)
        if reparto:
            cuerpo += "\n\nReparto de las obligatorias por curso:\n" + "\n".join(
                reparto
            )
        if optativas:
            cuerpo += (
                f"\n\nLas {len(optativas)} optativas no llevan curso asignado en "
                "el plan que publica la EPSJ."
            )
        chunks.extend(
            _chunks_de_unidad(f"{titulo}.", cuerpo, base, "ficha_titulacion", tamanos)
        )
    return chunks


def _chunks_de_mencion(
    items: list[dict[str, Any]],
    tamanos: tuple[int, int, int],
) -> list[dict[str, Any]]:
    """Genera el listado de asignaturas de cada mención (IT-107)."""
    por_mencion: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in items:
        if item["tipo"] != "asignatura":
            continue
        for mencion in item.get("menciones") or []:
            por_mencion.setdefault((item["grado"], mencion), []).append(item)

    chunks: list[dict[str, Any]] = []

    # El listado tiene encabezado propio para poder recuperarlo como unidad.
    por_grado: dict[str, list[str]] = {}
    for grado, mencion in por_mencion:
        if normalizar_rotulo(mencion) != _COMUN_A_TODAS:
            por_grado.setdefault(grado, []).append(mencion)
    for grado in sorted(por_grado):
        nombres = sorted(por_grado[grado])
        titulo = f"Menciones del {grado}"
        chunks.extend(
            _chunks_de_unidad(
                f"{titulo}. En total son {len(nombres)}:",
                "\n\n".join(f"{n}." for n in nombres),
                {
                    "grados": [grado],
                    "codigos": [None],
                    "nombre": titulo,
                    "tipo_asignatura": "",
                    "curso": "",
                },
                "mencion",
                tamanos,
            )
        )

    for grado, mencion in sorted(por_mencion):
        asignaturas = sorted(por_mencion[(grado, mencion)], key=lambda a: a["nombre"])
        if normalizar_rotulo(mencion) == _COMUN_A_TODAS:
            titulo = f"Asignaturas optativas comunes a todas las menciones del {grado}"
        else:
            titulo = f"Asignaturas de la mención «{mencion}» del {grado}"
        lineas = []
        for a in asignaturas:
            lineas.append(f"{a['nombre']}{_creditos(a)}.")
        base = {
            "grados": [grado],
            "codigos": [None],
            "nombre": titulo,
            "tipo_asignatura": "",
            "curso": "",
        }
        chunks.extend(
            _chunks_de_unidad(
                f"{titulo}. En total son {len(asignaturas)}:",
                "\n\n".join(lineas),
                base,
                "mencion",
                tamanos,
            )
        )
    return chunks


def _por_curso(
    asignaturas: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Agrupa un listado por el curso en que se imparte (IT-105)."""
    grupos: dict[str, list[dict[str, Any]]] = {}
    for a in asignaturas:
        grupos.setdefault((a.get("curso") or "").strip(), []).append(a)

    def orden(curso: str) -> tuple[int, str]:
        if not curso:
            return (99, "")
        for posicion, ordinal in enumerate(ORDEN_CURSOS, start=1):
            if curso.lower().startswith(ordinal):
                return (posicion, curso)
        return (98, curso)

    return [(curso, grupos[curso]) for curso in sorted(grupos, key=orden)]


def _agrupar_guias(
    items: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Agrupa por nombre y contenido; el contenido solo mezclaría asignaturas."""
    grupos_guia: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in items:
        if item["tipo"] != "guia":
            continue
        if item.get("fallback"):
            texto = item.get("cuerpo_general", "")
        else:
            texto = "\n\n".join(
                parte
                for parte in (item.get("resumen", ""), item.get("temario", ""))
                if parte
            )
        grupos_guia.setdefault((item["nombre"], texto), []).append(item)

    return grupos_guia


def _asociar_dobles(
    items: list[dict[str, Any]],
    grupos_guia: dict[tuple[str, str], list[dict[str, Any]]],
) -> tuple[dict[tuple[str, str], list[tuple[str, str | None]]], set[tuple[str, str]]]:
    """Asocia dobles por nombre; avisa y no asigna las coincidencias ambiguas."""
    dobles = {
        g["nombre"] for g in items if g["tipo"] == "grado" and g.get("es_doble_grado")
    }
    grupos_por_nombre: dict[str, list[tuple[str, str]]] = {}
    for clave in grupos_guia:
        grupos_por_nombre.setdefault(normalizar_rotulo(clave[0]), []).append(clave)
    dobles_por_grupo: dict[tuple[str, str], list[tuple[str, str | None]]] = {}
    atendidas: set[tuple[str, str]] = set()
    ambiguas: list[tuple[str, str]] = []
    for asig_doble in (
        a for a in items if a["tipo"] == "asignatura" and a["grado"] in dobles
    ):
        candidatos = grupos_por_nombre.get(normalizar_rotulo(asig_doble["nombre"]), [])
        if not candidatos:
            # Reintenta sin el acrónimo del grado base solo si el nombre completo no
            # coincide.
            candidatos = grupos_por_nombre.get(
                normalizar_rotulo(_SUFIJO_GRADO.sub("", asig_doble["nombre"])), []
            )
        if len(candidatos) != 1:
            # Una coincidencia ambigua o ausente conserva el fragmento informativo.
            if candidatos:
                ambiguas.append((asig_doble["grado"], asig_doble["nombre"]))
            continue

        dobles_por_grupo.setdefault(candidatos[0], []).append(
            (asig_doble["grado"], asig_doble["codigo"])
        )
        atendidas.add(
            _clave_asignatura(
                asig_doble["grado"], asig_doble["codigo"], asig_doble["nombre"]
            )
        )

    if ambiguas:
        # Un nombre que casa con varios grupos de guía no se reparte a ojo, y
        # el descarte se avisa: un dato que se pierde en silencio no se ve.
        print(
            f"AVISO: {len(ambiguas)} asignaturas de dobles grados con nombre "
            "ambiguo entre varias guías; no se enganchan a ninguna.",
            file=sys.stderr,
        )
        for grado_doble, nombre_asig in ambiguas:
            print(f"   {grado_doble} - {nombre_asig}", file=sys.stderr)

    return dobles_por_grupo, atendidas


def _chunks_de_guias(
    grupos_guia: dict[tuple[str, str], list[dict[str, Any]]],
    dobles_por_grupo: dict[tuple[str, str], list[tuple[str, str | None]]],
    asignaturas: dict[tuple[str, str], dict[str, Any]],
    tamanos: tuple[int, int, int],
) -> list[dict[str, Any]]:
    """Trocea guías compartidas, separándolas si difieren sus datos del plan."""
    chunks: list[dict[str, Any]] = []
    for (nombre, texto), guias in grupos_guia.items():
        # Orden estable de titulaciones para que el troceo sea determinista.
        guias = sorted(guias, key=lambda g: g["grado"])
        # Los dobles grados se añaden DESPUÉS de ordenar: así el primer par de
        # cada subgrupo es, siempre que lo haya, el de una titulación que sí
        # publica la guía.
        pares: list[tuple[str, str | None]] = [(g["grado"], g["codigo"]) for g in guias]
        pares += sorted(dobles_por_grupo.get((nombre, texto), []))

        for propios in _por_metadatos_del_plan(pares, nombre, asignaturas).values():
            grados = [grado for grado, _ in propios]
            codigos = [codigo for _, codigo in propios]
            asignatura = asignaturas.get(
                _clave_asignatura(grados[0], codigos[0], nombre)
            )
            encabezado = (
                # El encabezado usa el nombre de la unidad; los planes de dobles pueden
                # añadir un acrónimo al suyo.
                _encabezado_asignatura({**asignatura, "nombre": nombre}, grados)
                if asignatura
                else _encabezado_sin_metadatos(nombre, grados)
            )
            # El tipo permite filtrar el índice y es común a todas las titulaciones del
            # grupo.
            base = {
                "grados": grados,
                "codigos": codigos,
                "nombre": nombre,
                "tipo_asignatura": asignatura["tipo_asignatura"] if asignatura else "",
                "curso": (asignatura.get("curso", "") if asignatura else ""),
            }
            chunks.extend(_chunks_de_unidad(encabezado, texto, base, "guia", tamanos))

    return chunks


def _chunks_sin_guia(
    items: list[dict[str, Any]], atendidas: set[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Informa de asignaturas sin contenido, aunque la fuente enlace una guía."""
    chunks: list[dict[str, Any]] = []
    guias_presentes = {
        _clave_asignatura(g["grado"], g["codigo"], g["nombre"])
        for g in items
        if g["tipo"] == "guia"
    }
    for asignatura in (
        a
        for a in items
        if a["tipo"] == "asignatura"
        and _clave_asignatura(a["grado"], a["codigo"], a["nombre"])
        not in guias_presentes
        # Excluye los dobles que ya tienen contenido asociado a la guía del grado base.
        and _clave_asignatura(a["grado"], a["codigo"], a["nombre"]) not in atendidas
    ):
        encabezado = _encabezado_asignatura(asignatura, [asignatura["grado"]])
        # Distingue guía publicada sin contenido de guía no publicada (IT-95).
        if asignatura["tiene_guia"]:
            texto = (
                "La guía docente de esta asignatura está publicada en la web de "
                "la EPSJ, pero no recoge ni resumen ni temario, por lo que solo "
                "se dispone de sus datos básicos."
            )
        else:
            texto = (
                "La guía docente de esta asignatura no está publicada en la web "
                "de la EPSJ, por lo que solo se dispone de sus datos básicos."
            )
        base = {
            "grados": [asignatura["grado"]],
            "codigos": [asignatura["codigo"]],
            "nombre": asignatura["nombre"],
            "tipo_asignatura": asignatura["tipo_asignatura"],
            "curso": asignatura.get("curso", ""),
        }
        chunks.append(
            {
                "tipo": "chunk",
                "origen": "asignatura_sin_guia",
                **base,
                "texto": f"{encabezado}\n{texto}",
                "chunk_index": 0,
                "total_chunks": 1,
            }
        )
    return chunks


def trocear_dataset(
    items: list[dict[str, Any]],
    tamanos: tuple[int, int, int] = (
        TAMANO_OBJETIVO,
        TAMANO_MAXIMO,
        TAMANO_MINIMO,
    ),
) -> list[dict[str, Any]]:
    """Trocea el dataset sin mezclar asignaturas y conserva el orden de los orígenes."""
    asignaturas = {
        _clave_asignatura(a["grado"], a["codigo"], a["nombre"]): a
        for a in items
        if a["tipo"] == "asignatura"
    }
    grupos_guia = _agrupar_guias(items)
    dobles_por_grupo, atendidas = _asociar_dobles(items, grupos_guia)
    chunks = _chunks_de_guias(grupos_guia, dobles_por_grupo, asignaturas, tamanos)
    for item in items:
        if item["tipo"] == "salidas":
            encabezado = f"Salidas profesionales del {item['grado']}:"
            base = {
                "grados": [item["grado"]],
                "codigos": [None],
                "nombre": item["grado"],
                # Las salidas no son una asignatura: el campo queda vacío en
                # lugar de inventarle un tipo, con el mismo criterio que se
                # aplica al ECTS ausente. Lo mismo con el curso.
                "tipo_asignatura": "",
                "curso": "",
            }
            chunks.extend(
                _chunks_de_unidad(encabezado, item["texto"], base, "salidas", tamanos)
            )

    chunks.extend(_chunks_de_plan_de_estudios(items, tamanos))

    # Las agregaciones solo cuentan y agrupan datos publicados por la EPSJ.
    chunks.extend(_chunks_de_catalogo(items, tamanos))
    chunks.extend(_chunks_de_ficha(items, tamanos))
    chunks.extend(_chunks_de_mencion(items, tamanos))

    chunks.extend(_chunks_sin_guia(items, atendidas))
    return chunks


def procedencia_de(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Compone la procedencia de los fragmentos a partir del dataset (IT-90)."""
    del_spider = next(
        (i for i in items if i.get("tipo") == "procedencia"),
        {},
    )
    cursos = sorted(
        {
            item["curso"]
            for item in items
            if item.get("tipo") == "guia" and item.get("curso")
        }
    )
    guias_sin_curso = sum(
        1 for i in items if i.get("tipo") == "guia" and not i.get("curso")
    )
    return {
        "tipo": "procedencia",
        "fecha_extraccion": del_spider.get("fecha_extraccion"),
        "fecha_troceado": date.today().isoformat(),
        "cursos": cursos,
        "guias_sin_curso": guias_sin_curso,
    }


def main(
    ruta_entrada: str,
    ruta_salida: str,
    tamanos: tuple[int, int, int] = (
        TAMANO_OBJETIVO,
        TAMANO_MAXIMO,
        TAMANO_MINIMO,
    ),
) -> None:
    """Trocea un dataset JSON y escribe los chunks resultantes."""
    items = json.loads(Path(ruta_entrada).read_text(encoding="utf-8"))
    chunks = trocear_dataset(items, tamanos)
    procedencia = procedencia_de(items)
    procedencia["tamanos"] = list(tamanos)
    Path(ruta_salida).write_text(
        json.dumps([procedencia, *chunks], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    cursos = ", ".join(procedencia["cursos"]) or "sin determinar"
    print(
        f"{len(chunks)} chunks escritos en {ruta_salida} "
        f"(extraccion {procedencia['fecha_extraccion']}, curso {cursos}, "
        f"tamanos {tamanos[0]}/{tamanos[1]}/{tamanos[2]})"
    )


if __name__ == "__main__":
    # Parámetros opcionales para experimentos: entrada salida [objetivo maximo minimo].
    if len(sys.argv) >= 6:
        main(
            sys.argv[1],
            sys.argv[2],
            (int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])),
        )
    else:
        main(sys.argv[1], sys.argv[2])

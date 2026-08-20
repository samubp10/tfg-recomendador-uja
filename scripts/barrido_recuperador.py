"""Rejilla de los parámetros del recuperador (IT-49).

Los tres parámetros que deciden cuánto contexto recibe el modelo ---el mínimo y
el máximo de la banda, el factor de corte relativo y el suelo de pertinencia---
se fijaron mirando tres preguntas. Este guion los barre sobre el conjunto de
evaluación entero.

**No llama a ningún modelo generativo.** Se recuperan los vecinos una sola vez
por pregunta y todas las configuraciones se simulan sobre esas mismas listas de
distancias, de modo que la rejilla entera cuesta segundos en lugar de días. Es
posible porque los tres parámetros solo deciden **dónde se corta** una lista que
ya está ordenada: no cambian la búsqueda.

Se miden cuatro cosas, y no hay una sola que maximizar:

* **Exhaustividad por unidad**: de las preguntas de dominio, en cuántas aparece
  al menos un fragmento de la unidad que las responde.
* **Rechazo de lo ajeno**: de las preguntas fuera de dominio, en cuántas se
  devuelve la lista vacía, que es el acierto en esa familia.
* **Fragmentos por pregunta**: lo que cuesta en tiempo de generación y en
  ventana de contexto.
* **Preguntas de dominio sin contexto**: el fallo más grave del recuperador,
  porque deja al generador sin nada que leer.

Subir el suelo mejora el rechazo y empeora la exhaustividad. Bajarlo, al revés.
Por eso la salida es una tabla y no un número: la elección es un compromiso y
hay que verlo para poder defenderlo.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from tfg_uja.incrustaciones import MODELO, incrustador_de_consultas  # noqa: E402
from tfg_uja.recuperador import (  # noqa: E402
    abrir_indice,
    distancia_del_indice,
    recuperar,
)

#: Cuántos vecinos se traen de cada pregunta antes de simular. Tiene que ser
#: mayor que el máximo de la rejilla, o las configuraciones grandes se medirían
#: con una lista truncada y saldrían peores de lo que son.
VECINOS = 60

#: Tipo de pregunta del conjunto de IT-27 cuyo acierto es el contrario: no se
#: espera recuperar nada.
FUERA_DE_DOMINIO = "fuera_de_dominio"


@dataclass(frozen=True)
class Configuracion:
    """Una combinación de los parámetros que deciden el corte."""

    minimo: int
    maximo: int
    factor: float
    suelo: float


@dataclass(frozen=True)
class Recuperado:
    """Lo que hace falta de un fragmento para simular los cortes."""

    nombre: str
    origen: str
    distancia: float


def acotar(vecinos: list[Recuperado], config: Configuracion) -> list[Recuperado]:
    """Aplica un corte a una lista ya ordenada por distancia.

    Reproduce exactamente lo que hace
    :func:`tfg_uja.recuperador.acotar_por_distancia`, sobre la estructura
    reducida que guarda este guion.

    Args:
        vecinos: Fragmentos ordenados de más a menos próximo.
        config: Parámetros del corte.

    Returns:
        Los fragmentos que quedan dentro.
    """
    if not vecinos or vecinos[0].distancia > config.suelo:
        return []
    umbral = vecinos[0].distancia * config.factor
    dentro = [v for v in vecinos if v.distancia <= umbral]
    tope = max(config.minimo, min(len(dentro), config.maximo))
    return vecinos[:tope]


def acierta_la_unidad(
    devueltos: list[Recuperado], relevantes: list[dict[str, str]]
) -> bool:
    """Si entre lo devuelto hay algún fragmento de alguna unidad relevante.

    Se mide por unidad y no por fragmento porque para responder basta con
    alcanzar la asignatura correcta: que falte uno de sus trozos no deja al
    generador sin la información.

    Args:
        devueltos: Fragmentos que sobreviven al corte.
        relevantes: Unidades que responden la pregunta, del conjunto de IT-27.

    Returns:
        ``True`` si se alcanzó alguna.
    """
    esperadas = {(r["origen"], r["nombre"]) for r in relevantes}
    return any((d.origen, d.nombre) in esperadas for d in devueltos)


def medir(
    config: Configuracion,
    dominio: list[tuple[list[Recuperado], list[dict[str, str]]]],
    ajenas: list[list[Recuperado]],
) -> dict[str, Any]:
    """Evalúa una configuración sobre las preguntas ya recuperadas.

    Args:
        config: Parámetros del corte.
        dominio: Pares ``(vecinos, relevantes)`` de las preguntas del dominio.
        ajenas: Vecinos de las preguntas ajenas al dominio.

    Returns:
        Las cuatro medidas de esa configuración.
    """
    aciertos = 0
    vacias = 0
    total_fragmentos = 0
    for vecinos, relevantes in dominio:
        devueltos = acotar(vecinos, config)
        total_fragmentos += len(devueltos)
        if not devueltos:
            vacias += 1
        elif acierta_la_unidad(devueltos, relevantes):
            aciertos += 1
    rechazadas = sum(1 for vecinos in ajenas if not acotar(vecinos, config))
    return {
        "minimo": config.minimo,
        "maximo": config.maximo,
        "factor": config.factor,
        "suelo": config.suelo,
        "unidad": aciertos / len(dominio) if dominio else 0.0,
        "rechazo": rechazadas / len(ajenas) if ajenas else 0.0,
        "fragmentos": total_fragmentos / len(dominio) if dominio else 0.0,
        "sin_contexto": vacias,
    }


def preparar(
    preguntas: list[dict[str, Any]],
    tabla: Any,
    incrustar: Any,
    distancia: str,
    vecinos: int,
) -> tuple[list[tuple[list[Recuperado], list[dict[str, str]]]], list[list[Recuperado]]]:
    """Recupera una sola vez los vecinos de cada pregunta.

    Args:
        preguntas: Conjunto de evaluación de IT-27.
        tabla: Tabla del índice ya abierta.
        incrustar: Incrustador de consultas.
        distancia: Métrica del índice.
        vecinos: Cuántos vecinos traer.

    Returns:
        ``(preguntas de dominio con sus relevantes, preguntas ajenas)``.
    """
    dominio = []
    ajenas = []
    for i, pregunta in enumerate(preguntas, 1):
        traidos = [
            Recuperado(f.nombre, f.origen, f.distancia)
            for f in recuperar(
                pregunta["pregunta"], tabla, incrustar, distancia=distancia, k=vecinos
            )
        ]
        if pregunta["tipo"] == FUERA_DE_DOMINIO:
            ajenas.append(traidos)
        else:
            dominio.append((traidos, pregunta["relevantes"]))
        if i % 10 == 0:
            print(f"  recuperadas {i}/{len(preguntas)}", flush=True)
    return dominio, ajenas


def rejilla() -> list[Configuracion]:
    """Las configuraciones que se prueban.

    El mínimo se barre porque nunca se ha barrido: está en 3 desde el primer
    día. El máximo, el factor y el suelo cubren un entorno amplio de los valores
    actuales (3, 20, 1,20 y 0,142) para poder ver la forma del compromiso, no
    solo si el valor de al lado es mejor.

    Returns:
        Todas las combinaciones.
    """
    return [
        Configuracion(minimo, maximo, factor, suelo)
        for minimo in (1, 3, 5)
        for maximo in (10, 15, 20, 30)
        for factor in (1.10, 1.20, 1.30, 1.50)
        for suelo in (0.130, 0.137, 0.142, 0.150, 0.160)
        if minimo <= maximo
    ]


def informe(filas: list[dict[str, Any]], destino: Path, actual: dict[str, Any]) -> None:
    """Escribe la tabla con las mejores configuraciones.

    Args:
        filas: Todas las configuraciones medidas.
        destino: Fichero de salida.
        actual: La medida de la configuración que hoy usa el sistema.
    """
    ordenadas = sorted(
        filas, key=lambda f: (-f["unidad"], -f["rechazo"], f["fragmentos"])
    )
    lineas = [
        "# Rejilla de parámetros del recuperador (IT-49)",
        "",
        "> Lo escribe `scripts/barrido_recuperador.py`. **No editar a mano.**",
        "",
        f"- Configuraciones probadas: **{len(filas)}**",
        "- Sin llamar a ningún modelo generativo: los tres parámetros solo "
        "deciden dónde se corta una lista ya ordenada.",
        "",
        "## La configuración de hoy",
        "",
        f"- mín {actual['minimo']}, máx {actual['maximo']}, factor "
        f"{actual['factor']}, suelo {actual['suelo']}",
        f"- unidad **{actual['unidad']:.3f}** · rechazo **{actual['rechazo']:.3f}** "
        f"· {actual['fragmentos']:.1f} fragmentos por pregunta "
        f"· {actual['sin_contexto']} sin contexto",
        "",
        "## Las veinte mejores",
        "",
        "| mín | máx | factor | suelo | Unidad | Rechazo | Frag. | Sin ctx. |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for fila in ordenadas[:20]:
        lineas.append(
            f"| {fila['minimo']} | {fila['maximo']} | {fila['factor']:.2f} | "
            f"{fila['suelo']:.3f} | {fila['unidad']:.3f} | {fila['rechazo']:.3f} "
            f"| {fila['fragmentos']:.1f} | {fila['sin_contexto']} |"
        )
    lineas += [
        "",
        "**Unidad** es la proporción de preguntas de dominio en las que se "
        "recupera al menos un fragmento de la unidad que las responde. "
        "**Rechazo** es la proporción de preguntas ajenas al dominio que se "
        "quedan sin contexto, que es el acierto en esa familia. **Frag.** es la "
        "media de fragmentos por pregunta, que se paga en tiempo y en ventana. "
        "**Sin ctx.** son las preguntas de dominio que se quedan sin nada, que "
        "es el peor fallo posible del recuperador.",
        "",
        "## Las que no pierden ninguna pregunta de dominio",
        "",
        "| mín | máx | factor | suelo | Unidad | Rechazo | Frag. |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    limpias = [f for f in ordenadas if f["sin_contexto"] == 0]
    for fila in sorted(limpias, key=lambda f: (-f["rechazo"], f["fragmentos"]))[:10]:
        lineas.append(
            f"| {fila['minimo']} | {fila['maximo']} | {fila['factor']:.2f} | "
            f"{fila['suelo']:.3f} | {fila['unidad']:.3f} | {fila['rechazo']:.3f} "
            f"| {fila['fragmentos']:.1f} |"
        )
    lineas.append("")
    destino.write_text("\n".join(lineas), encoding="utf-8")
    print(f"\nInforme escrito en {destino}")


def main(argumentos: list[str] | None = None) -> None:
    """Punto de entrada."""
    analizador = argparse.ArgumentParser(description="Rejilla del recuperador.")
    analizador.add_argument(
        "--evalset", default=str(RAIZ / "eval" / "preguntas_evaluacion.json")
    )
    analizador.add_argument("--indice", default=str(RAIZ / "data" / "indice_lance"))
    analizador.add_argument(
        "--salida", default=str(RAIZ / "docs" / "experimentos" / "it49-recuperador.md")
    )
    analizador.add_argument("--vecinos", type=int, default=VECINOS)
    opciones = analizador.parse_args(argumentos)

    crudo = json.loads(Path(opciones.evalset).read_text(encoding="utf-8"))
    preguntas = crudo if isinstance(crudo, list) else crudo["preguntas"]
    ruta = Path(opciones.indice)

    print("Cargando el modelo de incrustaciones...")
    dominio, ajenas = preparar(
        preguntas,
        abrir_indice(ruta, MODELO),
        incrustador_de_consultas(MODELO),
        distancia_del_indice(ruta),
        opciones.vecinos,
    )
    print(f"{len(dominio)} preguntas de dominio, {len(ajenas)} ajenas")

    configuraciones = rejilla()
    print(f"Simulando {len(configuraciones)} configuraciones...")
    filas = [medir(c, dominio, ajenas) for c in configuraciones]
    actual = medir(Configuracion(3, 20, 1.20, 0.142), dominio, ajenas)

    destino = Path(opciones.salida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    informe(filas, destino, actual)


if __name__ == "__main__":
    main()

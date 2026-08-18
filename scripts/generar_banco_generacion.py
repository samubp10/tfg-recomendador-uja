"""Genera el banco de preguntas con el que se compara a los modelos (IT-35).

No es el conjunto de IT-27. Aquel anota **qué unidades debería recuperar** el
sistema y sirve para medir la recuperación; este anota **qué debería decir la
respuesta**, y sirve para medir la generación. Los dos hacen falta y miden
cosas distintas.

La diferencia que lo hace defendible: aquí **nada está escrito a mano**. Cada
pregunta y su respuesta correcta se derivan por cálculo de ``data/grados.json``,
de modo que:

- no cabe inventar una cifra ni una asignatura al redactar el banco;
- si la fuente cambia, el banco se regenera y no se queda mintiendo;
- la comparación entre modelos no depende de que alguien juzgue la respuesta,
  que es justo lo que impedía elegir el modelo con un criterio objetivo.

Solo se generan familias cuya respuesta correcta es **exacta y computable**.
Lo que no lo es ---de qué trata una asignatura, si la recomendación es buena---
se observa y se cuenta aparte, pero no decide.

Uso::

    py scripts/generar_banco_generacion.py
    py scripts/generar_banco_generacion.py --muestra 80 --semilla 42
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from tfg_uja.text_cleaner import normalizar  # noqa: E402

#: Tipos que un estudiante entiende como «hay que aprobarlas sí o sí». No se
#: llaman «obligatorias» en la pregunta a propósito: en el plan oficial `FB` es
#: formación básica y `OB` obligatoria, y hay cursos enteros que son solo `FB`.
#: Preguntar por «las obligatorias de primero de Informática» daría por buena
#: una respuesta a una pregunta mal formulada.
NO_OPTATIVAS = {"FB", "OB", "OB-IS", "OB-SI", "OB-TI", "TFG"}

#: Rótulo con el que la fuente marca las optativas que no pertenecen a ninguna
#: mención concreta. **No es una mención**, y darla por buena en la respuesta a
#: «¿en qué menciones puedo especializarme?» exigiría al modelo nombrar algo
#: que no existe como itinerario.
NO_ES_MENCION = "Común a todas las menciones"


def _como_se_escribe(nombre: str) -> str:
    """Devuelve el nombre en la caja en que lo escribiría una persona.

    La fuente publica parte de los nombres en mayúsculas («ADMINISTRACIÓN DE
    EMPRESAS») y otra parte no. Preguntar en mayúsculas mediría un sistema que
    nadie usa: un estudiante no escribe así, y el texto de la pregunta es lo
    que se incrusta para recuperar. Las siglas entre paréntesis ---«(GIM)»,
    «(GIE)»--- se respetan, que sí van en mayúsculas.

    **Solo cambia el texto de la pregunta.** La respuesta correcta se guarda
    tal como está en el dataset, sin tocar.

    Args:
        nombre: Nombre de la asignatura tal como lo publica la fuente.

    Returns:
        El nombre en caja de frase si venía todo en mayúsculas; si no, igual.
    """
    if not nombre.isupper():
        return nombre
    palabras = [
        palabra if palabra.startswith("(") else palabra.lower()
        for palabra in nombre.split()
    ]
    texto = " ".join(palabras)
    return texto[:1].upper() + texto[1:]


def _asignaturas(datos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Devuelve los ítems de asignatura del dataset."""
    return [d for d in datos if d.get("tipo") == "asignatura"]


def _titulaciones(datos: list[dict[str, Any]]) -> list[str]:
    """Devuelve los nombres de las titulaciones, en orden alfabético."""
    return sorted(d["nombre"] for d in datos if d.get("tipo") == "grado")


def preguntas_de_catalogo(datos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Qué titulaciones existen. La respuesta correcta es el catálogo entero.

    Es la pregunta que más daño hace fallada: el 16/08/2026 el sistema
    recomendó seis titulaciones y dos no existen en la EPSJ.
    """
    titulaciones = _titulaciones(datos)
    return [
        {
            "id": "G-CAT-001",
            "familia": "catalogo",
            "pregunta": (
                "¿Qué titulaciones se pueden estudiar en la Escuela "
                "Politécnica Superior de Jaén?"
            ),
            "respuesta": "conjunto",
            "esperado": titulaciones,
            "ambito": {},
        }
    ]


def preguntas_de_curso(datos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Qué asignaturas se cursan en cada año de cada titulación.

    Una pregunta por cada par (titulación, curso) que exista de verdad. No se
    inventa el curso: se toma el rótulo tal como lo publica la fuente, que a
    veces es un rango («Cuarto o tercer curso»).
    """
    por_curso: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for a in _asignaturas(datos):
        if a["tipo_asignatura"] not in NO_OPTATIVAS or not a["curso"]:
            continue
        por_curso[(a["grado"], a["curso"])].append(a["nombre"])

    preguntas = []
    for numero, ((grado, curso), nombres) in enumerate(sorted(por_curso.items()), 1):
        preguntas.append(
            {
                "id": f"G-CUR-{numero:03d}",
                "familia": "plan_por_curso",
                "pregunta": (
                    f"¿Qué asignaturas se cursan en {curso.lower()} " f"del {grado}?"
                ),
                "respuesta": "conjunto",
                "esperado": sorted(nombres),
                "ambito": {"grado": grado, "curso": curso},
            }
        )
    return preguntas


def preguntas_de_optativas(datos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Qué optativas ofrece cada titulación.

    Se separan de las de curso porque la fuente no les asigna año: preguntarlas
    «por año» no tendría respuesta correcta que computar.
    """
    por_grado: dict[str, list[str]] = collections.defaultdict(list)
    for a in _asignaturas(datos):
        if a["tipo_asignatura"] == "OP":
            por_grado[a["grado"]].append(a["nombre"])

    return [
        {
            "id": f"G-OPT-{numero:03d}",
            "familia": "optativas",
            "pregunta": f"¿Qué asignaturas optativas ofrece el {grado}?",
            "respuesta": "conjunto",
            "esperado": sorted(nombres),
            "ambito": {"grado": grado},
        }
        for numero, (grado, nombres) in enumerate(sorted(por_grado.items()), 1)
    ]


def preguntas_de_mencion(datos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Qué menciones tiene cada titulación y qué asignaturas las forman."""
    menciones: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for a in _asignaturas(datos):
        for mencion in a.get("menciones") or []:
            if mencion == NO_ES_MENCION:
                continue
            menciones[(a["grado"], mencion)].append(a["nombre"])

    preguntas: list[dict[str, Any]] = []
    por_grado: dict[str, set[str]] = collections.defaultdict(set)
    for grado, mencion in menciones:
        por_grado[grado].add(mencion)

    numero = 0
    for grado, nombres in sorted(por_grado.items()):
        numero += 1
        preguntas.append(
            {
                "id": f"G-MEN-{numero:03d}",
                "familia": "menciones",
                "pregunta": f"¿En qué menciones se puede especializar el {grado}?",
                "respuesta": "conjunto",
                "esperado": sorted(nombres),
                "ambito": {"grado": grado},
            }
        )
    for (grado, mencion), asigs in sorted(menciones.items()):
        numero += 1
        preguntas.append(
            {
                "id": f"G-MEN-{numero:03d}",
                "familia": "menciones",
                "pregunta": (
                    f"¿Qué asignaturas hay que cursar en la mención de "
                    f"{mencion} del {grado}?"
                ),
                "respuesta": "conjunto",
                "esperado": sorted(asigs),
                "ambito": {"grado": grado, "mencion": mencion},
            }
        )
    return preguntas


def preguntas_de_asignatura(datos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Una pregunta por cada asignatura de cada titulación.

    Se pregunta por los créditos y, cuando la fuente lo publica, por el curso.
    Son las dos cosas que un estudiante mira primero y las dos que el dataset
    sabe con exactitud. **La asignatura sin ECTS de la fuente se salta**: no se
    puede exigir una respuesta que el corpus no tiene, y rellenarla sería
    imputar un dato ausente.
    """
    preguntas: list[dict[str, Any]] = []
    numero = 0
    for a in sorted(_asignaturas(datos), key=lambda x: (x["grado"], x["nombre"])):
        if a.get("ects"):
            numero += 1
            preguntas.append(
                {
                    "id": f"G-ASI-{numero:04d}",
                    "familia": "creditos",
                    "pregunta": (
                        f"¿Cuántos créditos ECTS tiene la asignatura "
                        f"{_como_se_escribe(a['nombre'])} del {a['grado']}?"
                    ),
                    "respuesta": "escalar",
                    "esperado": [str(a["ects"])],
                    "ambito": {"grado": a["grado"], "asignatura": a["nombre"]},
                }
            )
        if a.get("curso"):
            numero += 1
            preguntas.append(
                {
                    "id": f"G-ASI-{numero:04d}",
                    "familia": "curso_de_asignatura",
                    "pregunta": (
                        f"¿En qué curso se imparte "
                        f"{_como_se_escribe(a['nombre'])} en el {a['grado']}?"
                    ),
                    "respuesta": "escalar",
                    "esperado": [a["curso"]],
                    "ambito": {"grado": a["grado"], "asignatura": a["nombre"]},
                }
            )
    return preguntas


def preguntas_de_ubicacion(datos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """En qué titulaciones se imparte una asignatura compartida.

    Solo se generan para las que se imparten en más de una: en las demás la
    respuesta es trivial y no distingue a un modelo de otro.
    """
    # Se agrupa por el nombre normalizado, no por el literal. La fuente publica
    # la misma asignatura en mayúsculas en los dobles grados y en caja normal
    # en los simples ---«ESTADÍSTICA» y «Estadística»---, y agrupar por el
    # literal las parte en dos: la respuesta correcta a «¿dónde se imparte
    # Estadística?» pasaba de las diez titulaciones reales a solo seis.
    # Son 22 los nombres a los que les pasa.
    donde: dict[str, set[str]] = collections.defaultdict(set)
    como_se_llama: dict[str, str] = {}
    for a in _asignaturas(datos):
        clave = normalizar(a["nombre"])
        donde[clave].add(a["grado"])
        # Entre las variantes se muestra la que no grita, si existe.
        if clave not in como_se_llama or not a["nombre"].isupper():
            como_se_llama[clave] = a["nombre"]

    compartidas = {como_se_llama[c]: g for c, g in donde.items() if len(g) > 1}
    return [
        {
            "id": f"G-UBI-{numero:03d}",
            "familia": "ubicacion",
            "pregunta": (
                f"¿En qué titulaciones de la EPSJ se imparte "
                f"{_como_se_escribe(nombre)}?"
            ),
            "respuesta": "conjunto",
            "esperado": sorted(grados),
            "ambito": {"asignatura": nombre},
        }
        for numero, (nombre, grados) in enumerate(sorted(compartidas.items()), 1)
    ]


def muestra_estratificada(
    preguntas: list[dict[str, Any]], tamano: int, semilla: int
) -> list[dict[str, Any]]:
    """Escoge un subconjunto con todas las familias representadas.

    El banco completo son cientos de preguntas y cada una cuesta una llamada al
    modelo: pasarlo entero por cada candidato no cabe en el calendario. Se
    reparte el tamaño entre familias a partes iguales y, dentro de cada una, se
    sortea con semilla fija para que la muestra sea siempre la misma.

    Args:
        preguntas: Banco completo.
        tamano: Cuántas preguntas se quieren.
        semilla: Semilla del sorteo, para poder repetir la selección.

    Returns:
        Las preguntas escogidas, en el orden del banco.
    """
    familias: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for p in preguntas:
        familias[p["familia"]].append(p)

    azar = random.Random(semilla)
    cupo = max(1, tamano // len(familias))
    escogidas: list[dict[str, Any]] = []
    for nombre in sorted(familias):
        grupo = familias[nombre]
        escogidas.extend(azar.sample(grupo, min(cupo, len(grupo))))

    # Si el reparto entero no llega al tamaño pedido, se completa del resto.
    faltan = tamano - len(escogidas)
    if faltan > 0:
        resto = [p for p in preguntas if p not in escogidas]
        escogidas.extend(azar.sample(resto, min(faltan, len(resto))))

    orden = {p["id"]: i for i, p in enumerate(preguntas)}
    return sorted(escogidas, key=lambda p: orden[p["id"]])


def construir(datos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Genera el banco completo a partir del dataset."""
    return [
        *preguntas_de_catalogo(datos),
        *preguntas_de_curso(datos),
        *preguntas_de_optativas(datos),
        *preguntas_de_mencion(datos),
        *preguntas_de_ubicacion(datos),
        *preguntas_de_asignatura(datos),
    ]


def main(argumentos: list[str]) -> None:
    """Punto de entrada."""
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--dataset", default=str(RAIZ / "data" / "grados.json"))
    analizador.add_argument(
        "--salida", default=str(RAIZ / "eval" / "preguntas_generacion.json")
    )
    analizador.add_argument(
        "--muestra",
        type=int,
        default=0,
        help="si se da, escribe además el subconjunto de decisión",
    )
    analizador.add_argument("--semilla", type=int, default=42)
    opciones = analizador.parse_args(argumentos)

    datos = json.loads(Path(opciones.dataset).read_text(encoding="utf-8"))
    procedencia = next((d for d in datos if d.get("tipo") == "procedencia"), None)
    banco = construir(datos)

    documento = {
        "descripcion": (
            "Banco de preguntas para comparar modelos generativos (IT-35). "
            "Generado por scripts/generar_banco_generacion.py a partir de "
            "data/grados.json: ni las preguntas ni las respuestas correctas se "
            "escriben a mano. Solo contiene familias cuya respuesta es exacta y "
            "computable, para que la comparación no dependa de un juez."
        ),
        "procedencia_del_dataset": procedencia,
        "preguntas": banco,
    }
    Path(opciones.salida).write_text(
        json.dumps(documento, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    cuenta = collections.Counter(p["familia"] for p in banco)
    print(f"Banco escrito en {opciones.salida}")
    print(f"  preguntas: {len(banco)}")
    for familia, n in sorted(cuenta.items()):
        print(f"    {familia:<22} {n:>5}")

    if opciones.muestra:
        sub = muestra_estratificada(banco, opciones.muestra, opciones.semilla)
        ruta = Path(opciones.salida).with_name("preguntas_generacion_muestra.json")
        documento["descripcion"] = (
            f"Subconjunto de decisión de {len(sub)} preguntas, sorteado con "
            f"semilla {opciones.semilla} y con todas las familias "
            f"representadas. Es el que decide el ADR-0005; el banco completo "
            f"sirve para comprobar al finalista."
        )
        documento["preguntas"] = sub
        ruta.write_text(
            json.dumps(documento, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        cuenta_sub = collections.Counter(p["familia"] for p in sub)
        print(f"\nMuestra escrita en {ruta}")
        print(f"  preguntas: {len(sub)}")
        for familia, n in sorted(cuenta_sub.items()):
            print(f"    {familia:<22} {n:>5}")


if __name__ == "__main__":
    main(sys.argv[1:])

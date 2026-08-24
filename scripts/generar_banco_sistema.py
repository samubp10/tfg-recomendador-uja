"""Banco de evaluación del sistema completo, no solo del generador (IT-37).

El banco de IT-35 mide una cosa muy concreta: si el modelo redacta bien con el
contexto que se le da. Son ochenta preguntas sueltas, factuales y bien
formuladas, y por construcción **no ejercitan casi nada del sistema**: no hay
conversación, así que el ámbito y la anáfora no se prueban; no hay cortesía, así
que esas ramas no se ejecutan ni una vez; y casi no hay peticiones de consejo,
que es el caso de uso que da sentido al asistente.

Los siete fallos de la sesión del 19/08/2026 los encontró una conversación a
mano, no el experimento. Este banco existe para que la próxima vez los encuentre
el experimento.

**Cómo se comprueba cada familia, siempre sin juez:**

``conjunto``
    Precisión y cobertura contra la lista que dice el dataset.
``escalar``
    Acierto contra el valor único que dice el dataset.
``fija``
    La respuesta tiene que ser **literalmente** una de las del módulo del
    generador. Es la comprobación más dura que hay y no admite interpretación.
``sin_invencion``
    No nombra ninguna titulación que no exista y nombra al menos una que sí.
    Es lo único que se puede exigir a una recomendación sin ponerse a juzgar si
    el consejo es bueno.
``rechazo``
    No nombra ninguna titulación. Una pregunta ajena al dominio se responde
    diciendo que no se sabe, no recomendando una carrera.
``ambito``
    La respuesta habla de la titulación que toca y de ninguna otra. Es lo que
    falló en el turno 7 de aquella sesión.

Las preguntas factuales se muestrean del banco derivado del dataset. Las de
conversación, consejo, cortesía y dominio **se escriben aquí**, porque no se
pueden derivar: no hay en el dataset ninguna columna que diga cuál es la
respuesta correcta a «no sé qué estudiar». Lo que sí se deriva es el criterio
con el que se corrigen, que sale del corpus en todos los casos.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

#: Cuántas preguntas factuales se conservan de cada familia del banco derivado.
#: Cuatro por familia dan veinticuatro llamadas, que es lo que cabe sin que la
#: tanda deje de poder repetirse en una tarde.
POR_FAMILIA_FACTUAL = 4

#: Semilla del sorteo de las factuales.
SEMILLA = 20

#: Conjunto de validación del rechazo, del que salen las preguntas ajenas
#: difíciles. Se nombra aquí y no se copia su contenido para que la única
#: versión de cada pregunta sea la del fichero versionado.
VALIDACION_AJENAS = "preguntas_fuera_de_dominio_validacion.json"


def factuales(ruta_banco: Path, por_familia: int, semilla: int) -> list[dict[str, Any]]:
    """Sortea preguntas de cada familia del banco derivado del dataset.

    Args:
        ruta_banco: Banco completo de IT-35.
        por_familia: Cuántas se conservan de cada familia.
        semilla: Semilla del sorteo.

    Returns:
        Las preguntas elegidas, con su familia y su respuesta esperada.
    """
    banco = json.loads(ruta_banco.read_text(encoding="utf-8"))["preguntas"]
    por = collections.defaultdict(list)
    for pregunta in banco:
        por[pregunta["familia"]].append(pregunta)

    azar = random.Random(semilla)
    elegidas: list[dict[str, Any]] = []
    for familia in sorted(por):
        candidatas = sorted(por[familia], key=lambda p: p["id"])
        elegidas.extend(azar.sample(candidatas, min(por_familia, len(candidatas))))
    return elegidas


def conversaciones() -> list[dict[str, Any]]:
    """Conversaciones de varios turnos, con el criterio en el último.

    Cada una prueba un mecanismo distinto de los que el banco de preguntas
    sueltas no toca: la anáfora, el ámbito heredado de la respuesta anterior,
    el cambio de tema y el agradecimiento final.
    """
    return [
        {
            "id": "S-CONV-001",
            "familia": "conversacion",
            "que_prueba": "el ámbito se hereda de la pregunta anterior",
            "turnos": [
                "¿Qué asignaturas optativas tiene el Grado en Ingeniería de "
                "Organización Industrial?",
                "¿Y cuántas son en total?",
            ],
            "respuesta": "ambito",
            "esperado": ["Grado en Ingeniería de Organización Industrial"],
            "prohibido": ["Grado en Ingeniería Mecánica"],
        },
        {
            "id": "S-CONV-002",
            "familia": "conversacion",
            "que_prueba": "regresión del turno 7 del 19/08/2026: el doble grado "
            "no puede arrastrar al simple que contiene",
            "turnos": [
                "Háblame del Doble Grado en Ingeniería Mecánica y Organización "
                "Industrial",
                "¿Y qué asignaturas optativas tiene esta carrera?",
            ],
            "respuesta": "ambito",
            "esperado": [
                "Doble Grado en Ingeniería Mecánica y Organización Industrial"
            ],
            "prohibido": ["Grado en Ingeniería Mecánica"],
        },
        {
            "id": "S-CONV-003",
            "familia": "conversacion",
            "que_prueba": "el ámbito lo fija la respuesta, no la pregunta",
            "turnos": [
                "Me gustan los videojuegos y la programación, ¿qué me recomiendas?",
                "¿Y qué asignaturas tiene en primero?",
            ],
            "respuesta": "sin_invencion",
            "esperado": [],
        },
        {
            "id": "S-CONV-004",
            "familia": "conversacion",
            "que_prueba": "la anáfora recorta el resultado anterior",
            "turnos": [
                "¿Qué asignaturas se cursan en primer curso del Grado en "
                "Ingeniería Informática?",
                "¿Cuál de esas es de matemáticas?",
            ],
            "respuesta": "ambito",
            "esperado": ["Grado en Ingeniería Informática"],
            "prohibido": [],
        },
        {
            "id": "S-CONV-005",
            "familia": "conversacion",
            "que_prueba": "cambiar de titulación a mitad de conversación",
            "turnos": [
                "¿Cuántos créditos tiene Álgebra en el Grado en Ingeniería "
                "Informática?",
                "¿Y en el Grado en Ingeniería Eléctrica?",
            ],
            "respuesta": "ambito",
            "esperado": ["Grado en Ingeniería Eléctrica"],
            "prohibido": [],
        },
        {
            "id": "S-CONV-006",
            "familia": "conversacion",
            "que_prueba": "regresión del turno 5: dar las gracias cierra, no falla",
            "turnos": [
                "¿Qué salidas tiene el Grado en Ingeniería Mecánica?",
                "Me gusta la idea, muchas gracias",
            ],
            "respuesta": "fija",
            "esperado": ["RESPUESTA_DESPEDIDA"],
        },
        {
            "id": "S-CONV-007",
            "familia": "conversacion",
            "que_prueba": "una pregunta de seguimiento que sí se sostiene sola",
            "turnos": [
                "¿Qué es el Grado en Inteligencia Artificial y Ciberseguridad?",
                "¿Cuántas asignaturas optativas tiene el Grado en Ingeniería "
                "Informática?",
            ],
            "respuesta": "ambito",
            "esperado": ["Grado en Ingeniería Informática"],
            "prohibido": [],
        },
        {
            "id": "S-CONV-008",
            "familia": "conversacion",
            "que_prueba": "tres turnos sobre la misma titulación",
            "turnos": [
                "Cuéntame del Grado en Ingeniería Eléctrica",
                "¿Qué menciones tiene?",
                "¿Y qué asignaturas hay en la primera?",
            ],
            "respuesta": "ambito",
            "esperado": ["Grado en Ingeniería Eléctrica"],
            "prohibido": [],
        },
    ]


def consejos() -> list[dict[str, Any]]:
    """Peticiones de recomendación, que es para lo que existe el asistente.

    Ninguna nombra una titulación, que es justo lo que las hacía caer por
    debajo del suelo de pertinencia. Se comprueba lo único comprobable sin
    juzgar el consejo: que no invente y que recomiende algo real.
    """
    formas = [
        "No sé qué estudiar, me gusta la física y el dibujo técnico",
        "Me gustan los ordenadores y las matemáticas, ¿qué carrera me pega?",
        "Se me da bien la electrónica y quiero trabajar en la industria",
        "Quiero una carrera con muchas salidas profesionales",
        "Dudo entre algo de informática y algo de industriales",
        "Me interesa la sostenibilidad y las energías renovables",
    ]
    return [
        {
            "id": f"S-REC-{i:03d}",
            "familia": "consejo",
            "que_prueba": "la petición de recomendación recupera contexto y no inventa",
            "pregunta": texto,
            "respuesta": "sin_invencion",
            "esperado": [],
        }
        for i, texto in enumerate(formas, 1)
    ]


def cortesias() -> list[dict[str, Any]]:
    """Mensajes que no preguntan nada. La respuesta es fija y se compara entera."""
    casos = [
        ("hola", "RESPUESTA_SALUDO"),
        ("buenas tardes", "RESPUESTA_SALUDO"),
        ("muchas gracias, hasta luego", "RESPUESTA_DESPEDIDA"),
        ("hei", "RESPUESTA_SALUDO"),
    ]
    return [
        {
            "id": f"S-COR-{i:03d}",
            "familia": "cortesia",
            "que_prueba": "un mensaje sin pregunta no recibe «no he encontrado nada»",
            "pregunta": texto,
            "respuesta": "fija",
            "esperado": [fija],
        }
        for i, (texto, fija) in enumerate(casos, 1)
    ]


def ajenas(ruta_validacion: Path | None = None) -> list[dict[str, Any]]:
    """Preguntas fuera del dominio, de dos procedencias distintas.

    Las cinco primeras se escriben aquí y son las evidentes; las tres iniciales
    llevan vocabulario del centro a propósito, porque son las que atraviesan el
    suelo de pertinencia. Con solo esas cinco el sistema acierta las cinco, y una
    proporción sobre cinco casos no sostiene ninguna conclusión: su intervalo al
    95 % baja hasta 0,549.

    Por eso se les suman las diez del conjunto de validación, que están escritas
    para colarse y **no intervinieron en ningún ajuste** del sistema. Se leen del
    fichero en lugar de copiarse aquí para que no puedan discrepar dos copias de
    la misma pregunta, y cada entrada conserva de dónde viene.

    Args:
        ruta_validacion: Conjunto de validación del rechazo. Por omisión, el
            versionado en ``eval/``.

    Returns:
        Las quince preguntas ajenas, las escritas aquí primero.
    """
    formas = [
        "¿Puedo estudiar Medicina en la Escuela Politécnica Superior de Jaén?",
        "¿Qué nota de corte tiene el Grado en Derecho?",
        "¿La Universidad de Granada tiene Ingeniería Informática?",
        "¿Cuál es la capital de Francia?",
        "Dame una receta de tortilla de patatas",
    ]
    ruta = ruta_validacion or RAIZ / "eval" / VALIDACION_AJENAS
    adversarias = json.loads(ruta.read_text(encoding="utf-8"))["preguntas"]

    entradas = [
        {
            "id": f"S-AJE-{i:03d}",
            "familia": "fuera_de_dominio",
            "que_prueba": "no se recomienda una carrera a quien pregunta otra cosa",
            "pregunta": texto,
            "respuesta": "rechazo",
            "esperado": [],
            "origen": "escrita_en_el_guion",
        }
        for i, texto in enumerate(formas, 1)
    ]
    entradas.extend(
        {
            "id": f"S-AJE-{i:03d}",
            "familia": "fuera_de_dominio",
            "que_prueba": f"rechazo ante una pregunta ajena de clase {p['clase']}",
            "pregunta": p["pregunta"],
            "respuesta": "rechazo",
            "esperado": [],
            "origen": f"conjunto_de_validacion:{p['id']}",
        }
        for i, p in enumerate(adversarias, len(formas) + 1)
    )
    return entradas


def ambiguas() -> list[dict[str, Any]]:
    """Preguntas que encajan en más de una titulación. No hay respuesta única:
    lo que se comprueba es que no se inventa y que no se elige a ciegas."""
    formas = [
        "Háblame del grado de ingeniería industrial",
        "¿Qué asignaturas tiene el grado de mecánica?",
        "Quiero información sobre el doble grado",
    ]
    return [
        {
            "id": f"S-AMB-{i:03d}",
            "familia": "ambigua",
            "que_prueba": "una pregunta que encaja en varias titulaciones",
            "pregunta": texto,
            "respuesta": "sin_invencion",
            "esperado": [],
        }
        for i, texto in enumerate(formas, 1)
    ]


def construir(ruta_banco: Path, por_familia: int, semilla: int) -> list[dict[str, Any]]:
    """Junta las preguntas derivadas y las escritas a mano.

    Args:
        ruta_banco: Banco completo de IT-35.
        por_familia: Cuántas factuales por familia.
        semilla: Semilla del sorteo.

    Returns:
        El banco entero, en el orden en que se va a ejecutar.
    """
    return [
        *factuales(ruta_banco, por_familia, semilla),
        *conversaciones(),
        *consejos(),
        *cortesias(),
        *ajenas(),
        *ambiguas(),
    ]


def llamadas(banco: list[dict[str, Any]]) -> int:
    """Cuántas veces habrá que llamar al modelo, que es lo que cuesta tiempo."""
    return sum(len(p.get("turnos", [p.get("pregunta")])) for p in banco)


def main(argumentos: list[str] | None = None) -> None:
    """Punto de entrada."""
    analizador = argparse.ArgumentParser(description="Banco del sistema completo.")
    analizador.add_argument(
        "--banco", default=str(RAIZ / "eval" / "preguntas_generacion.json")
    )
    analizador.add_argument(
        "--salida", default=str(RAIZ / "eval" / "preguntas_sistema.json")
    )
    analizador.add_argument("--por-familia", type=int, default=POR_FAMILIA_FACTUAL)
    analizador.add_argument("--semilla", type=int, default=SEMILLA)
    opciones = analizador.parse_args(argumentos)

    banco = construir(Path(opciones.banco), opciones.por_familia, opciones.semilla)
    documento = {
        "descripcion": (
            "Banco de evaluación del sistema completo (IT-37). Las preguntas "
            "factuales se sortean del banco derivado del dataset; las de "
            "conversación, consejo, cortesía, dominio y ambigüedad se escriben "
            "a mano, porque su respuesta correcta no está en ninguna columna "
            "del dataset. Ninguna familia necesita un modelo que la juzgue."
        ),
        "preguntas": banco,
    }
    Path(opciones.salida).write_text(
        json.dumps(documento, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    cuenta = collections.Counter(p["familia"] for p in banco)
    print(f"Banco escrito en {opciones.salida}")
    print(f"  entradas: {len(banco)}")
    print(f"  llamadas al modelo: {llamadas(banco)}")
    for familia, n in sorted(cuenta.items()):
        print(f"    {familia:<22} {n:>3}")


if __name__ == "__main__":
    main()

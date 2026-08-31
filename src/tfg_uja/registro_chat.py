"""Registro de las conversaciones de prueba (IT-45).

Cada turno que atiende el punto de entrada HTTP deja una línea JSON en
``data/registro_chat.jsonl`` con lo suficiente para analizarlo después sin
volver a ejecutar nada: con qué se buscó de verdad ---que no es lo que se
escribió---, qué fragmentos entraron en el contexto y a qué distancia, qué se
entregó y cuánto se tardó.

**El registro va a ``data/`` y no a otro sitio.** Es donde vive el registro en
bruto de todos los experimentos del proyecto: la carpeta no se versiona, pero
persiste entre ramas y árboles de trabajo. Escribirlo dentro del árbol de
trabajo de una tarjeta ya costó perder las 320 respuestas del cribado de IT-35,
y con ellas la posibilidad de volver a puntuarlas sin repetir la tanda.

**No se guarda ningún dato personal** (RNF-03): ni dirección IP, ni cabeceras
del navegador, ni identificador del cliente. :func:`linea_de_turno` no recibe
nada de eso, así que no puede colarse por descuido al añadir un campo más
adelante; lo único que se conserva es lo que se pregunta y lo que se responde.

**Registrar es una tarea auxiliar y se comporta como tal.**
:func:`anotar_turno` no propaga ningún fallo: si el disco está lleno, el
fichero bloqueado o la ruta no existe, se pierde la línea y el estudiante
recibe igualmente su respuesta. Al revés ---tumbar la respuesta por no poder
tomar nota de ella--- sería subordinar el sistema a su cuaderno de campo.

Se descarta el módulo ``logging`` a propósito: lo que hace falta es un JSONL
que se lea línea a línea con ``json.loads``, no un log de texto que haya que
volver a analizar con expresiones regulares para contar cualquier cosa.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from tfg_uja.generador import (
    RESPUESTA_DESPEDIDA,
    RESPUESTA_OTRA_UNIVERSIDAD,
    RESPUESTA_SALUDO,
    RESPUESTA_SIN_CONTEXTO,
)

RAIZ: Final[Path] = Path(__file__).resolve().parent.parent.parent

#: Fichero donde se acumulan los turnos, uno por línea.
REGISTRO: Final[Path] = RAIZ / "data" / "registro_chat.jsonl"

#: Respuestas que el sistema entrega **sin llegar a llamar al modelo**: la
#: cortesía, el cierre de conversación, la pregunta por otro centro y el
#: contexto vacío. Sirven para saber, leyendo el registro, si un turno costó
#: una llamada al modelo o se resolvió antes.
#:
#: ``RESPUESTA_TITULACION_INVENTADA`` **no está aquí a propósito**: cuando se
#: entrega, el modelo ya se había llamado y la respuesta se retiró después.
#: Contarla como respuesta fija diría que ese turno no gastó modelo, y gastó
#: uno entero.
RESPUESTAS_SIN_MODELO: Final[frozenset[str]] = frozenset(
    {
        RESPUESTA_SIN_CONTEXTO,
        RESPUESTA_SALUDO,
        RESPUESTA_DESPEDIDA,
        RESPUESTA_OTRA_UNIVERSIDAD,
    }
)


def linea_de_turno(
    pregunta: str,
    consulta: Any,
    ambito_antes: list[str],
    ambito_despues: list[str],
    fragmentos: list[Any],
    se_busco: bool,
    respuesta: str,
    retirada: bool,
    segundos: float,
    modelo: str,
    error: str = "",
) -> dict[str, Any]:
    """Compone la línea del registro. No toca disco, ni red, ni el modelo.

    Se separa de :func:`anotar_turno` por el mismo motivo por el que
    :func:`tfg_uja.servidor.partes_de_la_respuesta` no sabe nada de HTTP: lo
    que decide **qué** se guarda se prueba entero sin montar nada alrededor.

    ``se_busco`` separa dos turnos que se leen igual y no lo son: el que no
    recuperó nada porque la respuesta era fija ---un saludo ni siquiera llega
    al índice--- y el que sí buscó y se quedó sin nada porque el suelo de
    pertinencia lo descartó todo. En los dos ``recuperados`` vale cero, y no
    hay forma de deducir cuál fue mirando la respuesta: «hola» y «hei» acaban
    las dos en el mismo texto de bienvenida y solo una de las dos buscó.

    Se guardan la pregunta y la consulta por separado porque no son lo mismo:
    la conversación reescribe la pregunta antes de buscar ---le hereda el
    predicado o le añade la titulación de la que se venía hablando---, y sin
    las dos no se puede saber si un fallo vino de lo que se escribió o de lo
    que se buscó. La distancia de cada fragmento se guarda por lo mismo: es lo
    único que permite comprobar después si actuó el suelo de pertinencia.

    Args:
        pregunta: Lo que escribió el estudiante, tal cual.
        consulta: La :class:`tfg_uja.conversacion.Consulta` con la que se buscó
            de verdad.
        ambito_antes: Titulaciones de las que se hablaba al empezar el turno.
        ambito_despues: Titulaciones de las que se habla al terminarlo.
        fragmentos: Lo que devolvió el recuperador.
        se_busco: Si se llegó a consultar el índice. Falso cuando la pregunta
            se resolvió con texto fijo y no hizo falta buscar nada.
        respuesta: El texto que se entregó, entero.
        retirada: Si la respuesta se retiró a media emisión por nombrar una
            titulación que no existe.
        segundos: Lo que tardó el turno completo.
        modelo: Modelo generativo con el que se atendió.
        error: Mensaje del fallo si el modelo no respondió; vacío si respondió.

    Returns:
        El diccionario que se serializa como una línea del registro.
    """
    return {
        "momento": datetime.now().isoformat(timespec="seconds"),
        "modelo": modelo,
        "pregunta": pregunta,
        "consulta": {
            "texto": consulta.texto,
            "ambito": list(consulta.ambito),
            "respaldo": consulta.respaldo or "",
            # Quién decidió el ámbito y qué dijo. Sin esto, un turno en el que
            # la decisión falló y otro en el que el modelo dijo «sigue» dejan
            # exactamente el mismo rastro, y el primero se confunde con el
            # defecto del ámbito atascado. Pasó el 27/08/2026 y solo se vio
            # comparando tiempos.
            "decision": consulta.decision,
            "abierta": consulta.abierta,
        },
        "ambito_antes": list(ambito_antes),
        "ambito_despues": list(ambito_despues),
        "se_busco": se_busco,
        "recuperados": len(fragmentos),
        "fragmentos": [
            {
                "nombre": fragmento.nombre,
                "origen": fragmento.origen,
                "grados": list(fragmento.grados),
                "distancia": fragmento.distancia,
            }
            for fragmento in fragmentos
        ],
        "respuesta": respuesta,
        "retirada": retirada,
        "segundos": round(segundos, 2),
        "modelo_llamado": respuesta not in RESPUESTAS_SIN_MODELO,
        "error": error,
    }


def anotar_turno(linea: dict[str, Any], destino: Path | None = None) -> bool:
    """Añade la línea al final del registro, creándolo si no existía.

    Se abre en modo añadir y nunca en modo escritura: el registro de una tanda
    de pruebas se acumula a lo largo de días, y reescribir el fichero borraría
    lo anterior sin avisar.

    Args:
        linea: Lo que devuelve :func:`linea_de_turno`.
        destino: Fichero en el que escribir. Por omisión, :data:`REGISTRO`. Se
            resuelve al llamar y no en la propia firma, porque un valor por
            omisión se fija al definir la función y entonces las pruebas no
            podrían apuntarlo a otro sitio.

    Returns:
        ``True`` si la línea quedó escrita, ``False`` si no se pudo. No lanza
        nada: quien llama sigue su camino en los dos casos.
    """
    ruta = destino if destino is not None else REGISTRO
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with ruta.open("a", encoding="utf-8") as fichero:
            fichero.write(json.dumps(linea, ensure_ascii=False) + "\n")
    except Exception:
        # Se atrapa cualquier cosa y no solo ``OSError``: una línea que no se
        # pueda serializar tampoco puede tumbar la respuesta que el estudiante
        # está esperando. Registrar es auxiliar; responder, no.
        return False
    return True

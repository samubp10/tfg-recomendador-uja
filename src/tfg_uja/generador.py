"""Generación de la respuesta a partir del contexto recuperado (IT-37).

Cierra el recorrido: la pregunta llega, :mod:`tfg_uja.recuperador` trae los
fragmentos pertinentes y aquí se arma el texto que lee el modelo y se le pide
la respuesta.

El **diseño fino del prompt es IT-34**, y el **guardarraíl de dominio, IT-87**.
Lo que hay aquí es lo que el recorrido necesita para funcionar de extremo a
extremo, con dos decisiones que no son de redacción sino de arquitectura:

* **El contexto va identificado.** Cada fragmento entra con el nombre de su
  unidad y su titulación, no como un montón de texto anónimo, para que la
  respuesta pueda decir de dónde sale cada dato y para que el modelo no mezcle
  asignaturas.
* **El contexto va ordenado por unidad, no por distancia.** El recuperador
  entrega los fragmentos de más a menos próximo, y una unidad partida en varios
  llega intercalada con otras. Preguntado por las asignaturas de Informática,
  el listado del plan llegaba en el orden 3, optativas, 2, 1, y la respuesta
  reproducía ese orden: empezaba por la mitad de la lista y volvía al principio
  más abajo. Aquí se vuelven a juntar las partes de cada unidad y se ponen en
  su orden.
* **Cada parte dice cuál es.** Las tres partes del listado de obligatorias de
  Informática repiten el mismo encabezado, «En total son 50», y ninguna dice de
  cuál se trata. Si llega una sola, el modelo lee que son cincuenta, ve once y
  presenta once como si fueran las cincuenta, sin ninguna señal de que le falta
  contexto.
* **La ventana se declara.** El valor por defecto del servidor es de cientos de
  miles de *tokens*, y con él el modelo no cabe entero en una tarjeta de 6 GB:
  se reparte con la CPU y rinde a un tercio. Medido, no supuesto.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Final

from tfg_uja.recuperador import Fragmento

#: Servidor de inferencia local. No se consulta ningún servicio externo: el
#: sistema tiene que poder ejecutarse entero en el equipo del autor.
SERVIDOR: Final[str] = "http://127.0.0.1:11434"

#: Ventana de contexto, en *tokens*. Dimensionada para lo que arma el sistema
#: ---diez fragmentos de 900 caracteres, más las instrucciones y la respuesta---
#: y no para el máximo que admita el modelo: con la ventana por defecto el
#: caché no cabe en la tarjeta y expulsa parte del modelo a la CPU.
VENTANA: Final[int] = 8192

#: Tope de la respuesta. Acota lo que puede tardar y evita que un modelo
#: locuaz convierta una consulta de chat en un minuto de espera.
#:
#: Dimensionado sobre la respuesta más larga que el corpus puede exigir: las 67
#: asignaturas de Ingeniería Informática, con sus créditos, ocupan 2.819
#: caracteres, que a razón de unos 3,6 caracteres por *token* en español son
#: unos 783. Con el tope anterior, de 400, esa respuesta se cortaba a mitad de
#: palabra, y el corte no era del modelo sino nuestro.
#:
#: Se deja en 1.200 y no en los 783 justos porque una respuesta útil no es el
#: listado pelado: lleva una frase de entrada, separa obligatorias de optativas
#: y cierra con algo. Ese margen es el que evita que se corte la última línea,
#: que es justo donde se notaba.
TOPE_RESPUESTA: Final[int] = 1200

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
    "- Un fragmento marcado como «parte N de M» es un trozo de una lista más "
    "larga. Si no están todas las partes, avisa de que la lista está "
    "incompleta en lugar de presentarla como si estuviera entera.\n"
    "- Al enumerar asignaturas, pon primero las obligatorias y después las "
    "optativas, y no mezcles unas con otras.\n"
    "- Cita la asignatura o la titulación de la que sale cada dato."
)


def ordenar_contexto(fragmentos: list[Fragmento]) -> list[Fragmento]:
    """Reagrupa las partes de cada unidad y las pone en su orden.

    El recuperador ordena por distancia, que es lo correcto para decidir **qué**
    entra en el contexto pero no para decidir **en qué orden** se lee. Una
    unidad partida en tres llega con sus partes separadas por fragmentos de
    otras unidades, y el modelo redacta siguiendo el orden en que lo recibe.

    Cada unidad conserva el sitio que le da su fragmento más próximo, de modo
    que la relevancia sigue mandando entre unidades; lo único que cambia es que
    los trozos de una misma unidad viajan juntos y en orden.

    Args:
        fragmentos: Fragmentos recuperados, en cualquier orden.

    Returns:
        Los mismos fragmentos, agrupados por unidad y ordenados dentro de ella.
    """
    mejor: dict[tuple[str, str], float] = {}
    for f in fragmentos:
        clave = (f.nombre, f.origen)
        mejor[clave] = min(mejor.get(clave, f.distancia), f.distancia)
    return sorted(
        fragmentos,
        key=lambda f: (mejor[(f.nombre, f.origen)], f.chunk_index),
    )


def _etiqueta(indice: int, fragmento: Fragmento) -> str:
    """Compone la línea que encabeza un fragmento dentro del contexto.

    La parte solo se anota cuando la unidad está partida. Escribir «parte 1 de
    1» en las unidades enteras ---que son la mayoría del corpus--- añadiría
    ruido a todos los fragmentos para avisar de algo que solo ocurre en unos
    pocos.

    Args:
        indice: Número con el que se cita el fragmento, desde 1.
        fragmento: Fragmento que se va a encabezar.

    Returns:
        La línea de encabezado, sin el texto del fragmento.
    """
    parte = ""
    if fragmento.total_chunks > 1:
        parte = f" (parte {fragmento.chunk_index + 1} de {fragmento.total_chunks})"
    return f"[{indice}] {fragmento.nombre}{parte} — {', '.join(fragmento.grados)}"


def construir_prompt(pregunta: str, fragmentos: list[Fragmento]) -> str:
    """Arma el texto que lee el modelo.

    Cada fragmento entra encabezado por su unidad y su titulación: sin esa
    etiqueta, el modelo recibe varios textos seguidos sin saber a qué
    asignatura pertenece cada uno, y atribuir el temario de una a otra es
    justo el defecto que la fragmentación evita desde la Fase 1.

    Args:
        pregunta: Pregunta del usuario, tal cual la escribe.
        fragmentos: Fragmentos recuperados, de más a menos próximo.

    Returns:
        Prompt completo, listo para enviar al modelo.
    """
    if not fragmentos:
        contexto = "(no se ha recuperado ningún fragmento)"
    else:
        contexto = "\n\n".join(
            f"{_etiqueta(i, f)}\n{f.texto}"
            for i, f in enumerate(ordenar_contexto(fragmentos), start=1)
        )
    return (
        f"{INSTRUCCIONES}\n\n"
        f"CONTEXTO:\n{contexto}\n\n"
        f"PREGUNTA: {pregunta}\n\n"
        f"RESPUESTA:"
    )


def generar(
    prompt: str,
    modelo: str,
    servidor: str = SERVIDOR,
    ventana: int = VENTANA,
    tope: int = TOPE_RESPUESTA,
    semilla: int = 42,
) -> str:
    """Pide la respuesta al modelo local.

    La temperatura va a cero y la semilla fijada: con muestreo libre, dos
    ejecuciones de la misma pregunta dan respuestas distintas y ninguna
    medición sobre ellas sería reproducible.

    Args:
        prompt: Texto que devuelve :func:`construir_prompt`.
        modelo: Nombre del modelo en el servidor local.
        servidor: Dirección del servidor de inferencia.
        ventana: Ventana de contexto en *tokens*.
        tope: Máximo de *tokens* de la respuesta.
        semilla: Semilla del muestreo.

    Returns:
        La respuesta del modelo, sin espacios sobrantes.
    """
    cuerpo = {
        "model": modelo,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "num_ctx": ventana,
            "temperature": 0,
            "seed": semilla,
            "num_predict": tope,
        },
    }
    peticion = urllib.request.Request(
        f"{servidor}/api/generate",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(peticion, timeout=600) as respuesta:
        datos = json.loads(respuesta.read())
    return str(datos.get("response", "")).strip()

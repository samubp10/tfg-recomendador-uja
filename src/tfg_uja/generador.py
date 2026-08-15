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
TOPE_RESPUESTA: Final[int] = 400

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
    "- Cita la asignatura o la titulación de la que sale cada dato."
)


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
            f"[{i}] {f.nombre} — {', '.join(f.grados)}\n{f.texto}"
            for i, f in enumerate(fragmentos, start=1)
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

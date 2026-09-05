"""Registro de las conversaciones de prueba (IT-45)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from tfg_uja import RAIZ
from tfg_uja.dialogo.generador import (
    RESPUESTA_DESPEDIDA,
    RESPUESTA_OTRA_UNIVERSIDAD,
    RESPUESTA_SALUDO,
    RESPUESTA_SIN_CONTEXTO,
)

#: Fichero donde se acumulan los turnos, uno por línea.
REGISTRO: Final[Path] = RAIZ / "data" / "registro_chat.jsonl"

# Respuestas entregadas sin llamar al generador: cortesía, cierre, centro ajeno y
# contexto vacío.

# La retirada de una titulación inventada sí ocurre después de llamar al generador.
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
    """Compone la línea del registro. No toca disco, ni red, ni el modelo."""
    return {
        "momento": datetime.now().isoformat(timespec="seconds"),
        "modelo": modelo,
        "pregunta": pregunta,
        "consulta": {
            "texto": consulta.texto,
            "ambito": list(consulta.ambito),
            "respaldo": consulta.respaldo or "",
            # Registra la decisión de ámbito y distingue el fallo del decisor de la
            # decisión SIGUE.
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
        # Clasifica el texto entregado; no cuenta llamadas al modelo, incluido el
        # decisor de ámbito.
        "respuesta_del_generador": respuesta not in RESPUESTAS_SIN_MODELO,
        # Si al decisor de ámbito se le llegó a preguntar en este turno. Sale
        # del punto donde ocurre y no de la redacción final.
        "decisor_consultado": bool(consulta.decision),
        "error": error,
    }


def anotar_turno(linea: dict[str, Any], destino: Path | None = None) -> bool:
    """Añade la línea al final del registro, creándolo si no existía."""
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

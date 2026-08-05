"""Genera el ejemplo comparativo de fragmentación que ilustra el ADR-0001 (IT-16).

La Tabla de estrategias del Capítulo 4 afirma que el troceado por tamaño fijo
«corta a mitad de frase y, sobre la colección completa, puede juntar dos
asignaturas en un mismo fragmento». Este guion **demuestra** esa afirmación en
lugar de dejarla enunciada: aplica el troceado por tamaño fijo al texto real de
dos guías consecutivas y lo enfrenta al fragmento que produce la estrategia
estructural sobre el mismo contenido.

Es determinista y no hace peticiones de red ni carga ningún modelo: solo lee
``data/grados.json``. Se ejecuta desde la raíz del repositorio::

    py scripts/ejemplo_fragmentacion.py

La salida se pega en la sección de fragmentación de la memoria. Se deja como
guion, y no como texto fijo en el ``.tex``, para que el ejemplo pueda
regenerarse cuando cambie la colección y no se quede citando un texto que ya
no existe.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tfg_uja.chunker import (  # noqa: E402
    TAMANO_MAXIMO,
    TAMANO_OBJETIVO,
    _chunks_de_unidad,
    _encabezado_asignatura,
)

#: Solape del troceado por tamaño fijo. Es el valor habitual en la práctica
#: (en torno al 15 % del tamaño), y su elección concreta no altera el defecto
#: que el ejemplo ilustra: la frontera sigue cayendo donde le toca al contador.
SOLAPE: int = 200

RAIZ = Path(__file__).resolve().parent.parent


def trocear_por_tamano_fijo(texto: str, tamano: int, solape: int) -> list[str]:
    """Trocea un texto en ventanas de tamaño fijo con solape.

    Es la estrategia descartada en el ADR-0001, implementada aquí tal y como se
    describe: se avanza por el texto contando caracteres, sin mirar el
    contenido. No conoce frases, ni párrafos, ni dónde acaba una asignatura.

    Args:
        texto: Texto de entrada, ya concatenado.
        tamano: Número de caracteres de cada fragmento.
        solape: Caracteres que se repiten entre un fragmento y el siguiente.

    Returns:
        list[str]: Los fragmentos resultantes, en orden.
    """
    if solape >= tamano:
        raise ValueError("El solape debe ser menor que el tamaño del fragmento.")
    fragmentos: list[str] = []
    inicio = 0
    while inicio < len(texto):
        fragmentos.append(texto[inicio : inicio + tamano])
        inicio += tamano - solape
    return fragmentos


def _texto_de_guia(guia: dict[str, Any]) -> str:
    """Devuelve el texto plano de una guía docente, resumen y temario.

    Args:
        guia: Ítem de tipo ``guia`` del conjunto de datos.

    Returns:
        str: Resumen y temario concatenados, sin encabezado ni metadatos.
    """
    partes = [(guia.get("resumen") or "").strip(), (guia.get("temario") or "").strip()]
    return "\n".join(parte for parte in partes if parte)


def _corta_a_mitad_de_frase(fragmento: str) -> bool:
    """Indica si un fragmento termina en mitad de una frase.

    Args:
        fragmento: Texto del fragmento.

    Returns:
        bool: ``True`` si el último carácter no cierra una oración.
    """
    return bool(fragmento) and fragmento.rstrip()[-1] not in ".!?:;"


def main() -> int:
    """Imprime el ejemplo comparativo de las dos estrategias.

    Returns:
        int: 0 si se ha podido construir el ejemplo, 1 si no.
    """
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    datos = json.loads((RAIZ / "data/grados.json").read_text(encoding="utf-8"))
    guias = [d for d in datos if d["tipo"] == "guia" and len(_texto_de_guia(d)) > 900]
    asignaturas = {
        (a["grado"], a["codigo"] or a["nombre"]): a
        for a in datos
        if a["tipo"] == "asignatura"
    }
    if len(guias) < 2:
        print("No hay guías suficientes para construir el ejemplo.")
        return 1

    primera, segunda = guias[0], guias[1]
    texto_primera = _texto_de_guia(primera)
    concatenado = f"{texto_primera}\n{_texto_de_guia(segunda)}"

    print("=" * 78)
    print("EJEMPLO COMPARATIVO DE FRAGMENTACIÓN (IT-16, ilustra el ADR-0001)")
    print("=" * 78)
    print(f"Guía A : {primera['nombre']} ({primera['grado']})")
    print(f"Guía B : {segunda['nombre']} ({segunda['grado']})")
    print(f"Longitud de A: {len(texto_primera)} caracteres")

    # --- Estrategia descartada: tamaño fijo con solape -------------------
    fijos = trocear_por_tamano_fijo(concatenado, TAMANO_OBJETIVO, SOLAPE)
    print("\n" + "-" * 78)
    print(f"1) TAMAÑO FIJO CON SOLAPE ({TAMANO_OBJETIVO} car., solape {SOLAPE})")
    print("-" * 78)

    # El último fragmento de cualquier estrategia acaba donde acaba el texto de
    # origen: su final no es un corte, así que se excluye del recuento en las
    # dos estrategias por igual. Comparar de otro modo inflaría el defecto.
    cortados = [i for i, f in enumerate(fijos[:-1]) if _corta_a_mitad_de_frase(f)]
    print(
        f"Fragmentos generados: {len(fijos)} | cortan a mitad de frase: "
        f"{len(cortados)} de {len(fijos) - 1} fronteras internas"
    )

    if cortados:
        i = cortados[0]
        print(f"\n   Fragmento {i + 1}, final del texto (últimos 160 caracteres):")
        print(f"   [...] {fijos[i][-160:]!r}")
        print(
            "   ^ la frontera cae donde le toca al contador, no donde acaba la frase."
        )

    # El defecto grave: un fragmento que contiene texto de las dos guías.
    frontera = len(texto_primera)
    inicio = 0
    for i, fragmento in enumerate(fijos):
        if inicio < frontera < inicio + len(fragmento):
            print(f"\n   Fragmento {i + 1}: contiene texto de LAS DOS asignaturas.")
            corte = frontera - inicio
            print(f"   ...{fragmento[max(0, corte - 90):corte]!r}")
            print(
                f"   >>> aquí termina «{primera['nombre']}» "
                f"y empieza «{segunda['nombre']}» <<<"
            )
            print(f"   {fragmento[corte:corte + 90]!r}...")
            print(
                "   ^ viola la restricción de que un fragmento nunca mezcle "
                "dos asignaturas."
            )
            break
        inicio += TAMANO_OBJETIVO - SOLAPE

    # --- Estrategia elegida: estructural por unidad semántica ------------
    print("\n" + "-" * 78)
    print(f"2) ESTRUCTURAL POR UNIDAD SEMÁNTICA (máximo duro {TAMANO_MAXIMO} car.)")
    print("-" * 78)

    asignatura = asignaturas.get(
        (primera["grado"], primera["codigo"] or primera["nombre"])
    )
    if asignatura is None:
        print("La guía A no tiene asignatura correspondiente; no se puede ilustrar.")
        return 1
    grados = [primera["grado"]]
    estructurales = _chunks_de_unidad(
        encabezado=_encabezado_asignatura(asignatura, grados),
        texto=texto_primera,
        base={
            "grados": grados,
            "codigos": [primera["codigo"]],
            "nombre": primera["nombre"],
        },
        origen="guia",
    )
    internos = estructurales[:-1]
    cortan = [i for i, c in enumerate(internos) if _corta_a_mitad_de_frase(c["texto"])]
    print(
        f"Fragmentos generados para la guía A: {len(estructurales)} | cortan a "
        f"mitad de frase: {len(cortan)} de {len(internos)} fronteras internas"
    )
    for i, chunk in enumerate(estructurales, start=1):
        texto = chunk["texto"]
        if i == len(estructurales):
            marca = "  (último: acaba donde acaba la guía)"
        elif _corta_a_mitad_de_frase(texto):
            marca = "  <-- CORTA A MITAD"
        else:
            marca = ""
        print(f"   Fragmento {i}: {len(texto)} caracteres{marca}")

    primero = estructurales[0]["texto"]
    print("\n   Fragmento 1, encabezado y primeras líneas:")
    for linea in primero.split("\n")[:4]:
        print(f"   | {linea[:100]}")
    print("\n   Fragmento 1, final (últimos 120 caracteres):")
    print(f"   [...] {primero[-120:]!r}")
    print("   ^ cierra en una frontera del texto, y el encabezado hace que el")
    print("     fragmento siga teniendo sentido cuando se recupera aislado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

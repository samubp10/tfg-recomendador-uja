"""Chat de consola contra el sistema RAG, para evaluarlo a mano (IT-37).

No es la aplicación web de la Fase 3 ni sustituye a la evaluación con métricas
de IT-38: es la herramienta para sentarse delante y ver qué contesta el sistema,
que es lo que ninguna cifra enseña. Permite cambiar de modelo sin reiniciar,
para poder comparar candidatos con la misma pregunta.

Uso::

    py scripts/chat_rag.py                       # modelo por defecto
    py scripts/chat_rag.py --modelo ministral-3:3b
    py scripts/chat_rag.py --k 5 --grado "Grado en Ingeniería Informática"

Dentro del chat:

    /modelo <nombre>    cambia de modelo generativo
    /k <n>              cambia cuántos fragmentos se recuperan
    /grado <nombre>     acota la búsqueda a una titulación ("/grado ." la quita)
    /fuentes            muestra los fragmentos de la última respuesta
    /salir
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from tfg_uja.generador import construir_prompt, generar  # noqa: E402
from tfg_uja.incrustaciones import MODELO, incrustador_de_consultas  # noqa: E402
from tfg_uja.recuperador import (  # noqa: E402
    K_POR_DEFECTO,
    Fragmento,
    ModeloDiscrepante,
    abrir_indice,
    distancia_del_indice,
    recuperar,
)


def formatear_fuentes(fragmentos: list[Fragmento]) -> str:
    """Lista las unidades de las que salió el contexto, sin repetir."""
    vistas: dict[str, float] = {}
    for f in fragmentos:
        vistas.setdefault(f"{f.nombre} ({f.origen})", f.distancia)
    return "\n".join(
        f"    - {nombre}  ·  distancia {d:.3f}" for nombre, d in vistas.items()
    )


def main(argumentos: list[str]) -> None:
    """Punto de entrada del chat.

    Args:
        argumentos: Argumentos de línea de comandos.
    """
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--indice", default=str(RAIZ / "data" / "indice_lance"))
    analizador.add_argument("--modelo", default="gemma3:latest")
    analizador.add_argument("--k", type=int, default=K_POR_DEFECTO)
    analizador.add_argument("--grado", default=None)
    opciones = analizador.parse_args(argumentos)

    ruta_indice = Path(opciones.indice)
    if not ruta_indice.exists():
        sys.exit(
            f"No hay índice en {ruta_indice}.\n"
            f"Constrúyelo con: py -m tfg_uja.indexer data/chunks.json {ruta_indice}"
        )

    print("Cargando el modelo de incrustaciones...")
    incrustar = incrustador_de_consultas(MODELO)
    try:
        tabla = abrir_indice(ruta_indice, MODELO)
    except ModeloDiscrepante as error:
        sys.exit(f"El índice no casa con el modelo: {error}")
    distancia = distancia_del_indice(ruta_indice)

    modelo = opciones.modelo
    k = opciones.k
    grado = opciones.grado
    ultimos: list[Fragmento] = []

    print(f"\nÍndice:  {ruta_indice}  ({tabla.count_rows()} fragmentos, {distancia})")
    print(
        f"Modelo:  {modelo}   ·   K = {k}"
        + (f"   ·   acotado a «{grado}»" if grado else "")
    )
    print("Escribe tu pregunta, o /salir para terminar.\n")

    while True:
        try:
            entrada = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not entrada:
            continue

        if entrada.startswith("/"):
            orden, _, resto = entrada.partition(" ")
            resto = resto.strip()
            if orden == "/salir":
                return
            if orden == "/modelo" and resto:
                modelo = resto
                print(f"  modelo → {modelo}\n")
            elif orden == "/k" and resto.isdigit():
                k = int(resto)
                print(f"  K → {k}\n")
            elif orden == "/grado" and resto:
                grado = None if resto == "." else resto
                print(f"  titulación → {grado or 'sin acotar'}\n")
            elif orden == "/fuentes":
                print(formatear_fuentes(ultimos) if ultimos else "  (aún no hay)")
                print()
            else:
                print("  órdenes: /modelo /k /grado /fuentes /salir\n")
            continue

        t0 = time.perf_counter()
        ultimos = recuperar(
            entrada, tabla, incrustar, distancia=distancia, k=k, grado=grado
        )
        t_recuperar = time.perf_counter() - t0

        t1 = time.perf_counter()
        respuesta = generar(construir_prompt(entrada, ultimos), modelo)
        t_generar = time.perf_counter() - t1

        print(f"\n{respuesta}\n")
        print(
            f"  [{modelo} · recuperar {t_recuperar:.2f} s · "
            f"generar {t_generar:.2f} s · {len(ultimos)} fragmentos]"
        )
        print(formatear_fuentes(ultimos))
        print()


if __name__ == "__main__":
    main(sys.argv[1:])

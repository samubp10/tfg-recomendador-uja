"""Compara dos modelos generativos sobre las MISMAS preguntas (IT-133).

La comparativa de :mod:`experimento_generacion` informa la media de cada modelo
por separado. Con eso se ve quién saca más, pero no si la diferencia se
distingue del ruido, y esa es justo la pregunta cuando dos candidatos empatan:
adoptar el que va medio punto por delante en 80 preguntas puede ser adoptar una
moneda al aire.

Este guion no vuelve a llamar a ningún modelo. Lee el registro que dejó la
tanda ---que es donde vive el dato en bruto de todos los experimentos de este
proyecto--- y hace dos cosas que la media sola no hace:

* **Empareja por pregunta.** Los dos modelos respondieron exactamente las
  mismas, así que la comparación correcta no es entre dos medias
  independientes sino entre pares. Comparar medias independientes tira la
  información de que la pregunta 37 es difícil para los dos.
* **Acota la incertidumbre.** Cada tasa va con su intervalo de Wilson, y la
  diferencia con la prueba de McNemar, que es la que corresponde a dos
  resultados binarios medidos sobre los mismos sujetos.

Lo que **no** hace, y conviene decirlo: no mide la calidad de la redacción, no
sustituye a los umbrales eliminatorios del ADR-0005 y no decide nada por sí
solo. Dice si dos modelos se distinguen sobre este banco, y con cuánta holgura.

Uso::

    py scripts/experimentos/comparar_dos_modelos.py \\
       --registro data/registro_generacion_profundo.jsonl \\
       --modelos qwen3.5:9b gemma3:12b \\
       --salida docs/experimentos/it133-qwen-vs-gemma.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Final

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from tfg_uja.invariantes import exigir  # noqa: E402

#: Nivel de confianza de los intervalos. 95 % es la convención y no hay motivo
#: en este trabajo para apartarse de ella.
Z: float = 1.959963984540054

#: Umbral por debajo del cual se declara que los dos modelos se distinguen.
#: Se fija **antes** de mirar ningún resultado, que es lo que hace que sea un
#: criterio y no una racionalización.
ALFA: float = 0.05

#: Métricas binarias que se comparan, y **las tres del banco, no dos**.
#:
#: ``acierto`` es la de las preguntas de valor único ---créditos y curso---, y
#: dejarla fuera no habría sido un detalle: en la muestra de 250 son **180 de
#: las 250**, casi tres cuartas partes. El informe habría dicho «no se
#: distinguen» habiendo mirado 70 preguntas de 250, que es exactamente la clase
#: de cifra que parece medida y no lo está.
METRICAS: Final[tuple[str, ...]] = ("precision", "cobertura", "acierto")


def wilson(exitos: int, total: int) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción.

    Se usa Wilson y no el intervalo normal porque este banco produce tasas
    pegadas a 1 ---varias familias salen a 1,000 exacto--- y ahí el intervalo
    normal da cotas por encima de 1 o de anchura cero, que es peor que no dar
    ninguna: sugiere una certeza que no hay.

    Args:
        exitos: Casos favorables.
        total: Casos medidos.

    Returns:
        Cotas inferior y superior al 95 %. Con ``total`` cero, ``(0.0, 1.0)``:
        sin datos no se acota nada.
    """
    if total == 0:
        return (0.0, 1.0)
    p = exitos / total
    denominador = 1 + Z**2 / total
    centro = (p + Z**2 / (2 * total)) / denominador
    margen = Z * math.sqrt(p * (1 - p) / total + Z**2 / (4 * total**2)) / denominador
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def mcnemar(solo_a: int, solo_b: int) -> float:
    """Probabilidad de ver un desacuerdo así de desequilibrado por azar.

    Es la prueba binomial exacta sobre los pares **discordantes**, que son los
    únicos que informan: una pregunta que los dos aciertan, o que los dos
    fallan, no distingue a nadie. Se usa la exacta y no la aproximación de
    ji-cuadrado porque aquí los discordantes suelen ser pocos y ahí la
    aproximación no vale.

    Args:
        solo_a: Preguntas que acierta A y falla B.
        solo_b: Preguntas que acierta B y falla A.

    Returns:
        Valor p a dos colas. Sin discordantes, ``1.0``: los modelos hicieron
        exactamente lo mismo y no hay nada que distinguir.
    """
    n = solo_a + solo_b
    if n == 0:
        return 1.0
    k = min(solo_a, solo_b)
    cola = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * cola)


def aciertos_por_pregunta(
    filas: list[dict[str, Any]], modelo: str, campo: str
) -> dict[str, bool]:
    """Extrae, por pregunta, si el modelo acertó en ese campo.

    Args:
        filas: Registro completo de la tanda.
        modelo: Modelo del que se quiere el resultado.
        campo: ``precision``, ``cobertura`` o ``acierto``.

    Returns:
        Identificador de pregunta a acierto, solo con las que ese campo mide.
    """
    resultado: dict[str, bool] = {}
    for fila in filas:
        if fila["modelo"] != modelo or fila.get(campo) is None:
            continue
        resultado[fila["id"]] = fila[campo] >= 1.0
    return resultado


def comparar(filas: list[dict[str, Any]], a: str, b: str, campo: str) -> dict[str, Any]:
    """Compara dos modelos en un campo, emparejando por pregunta.

    Args:
        filas: Registro completo de la tanda.
        a: Primer modelo.
        b: Segundo modelo.
        campo: Métrica binaria a comparar.

    Returns:
        Conteos, tasas con su intervalo, discordantes y valor p.
    """
    de_a = aciertos_por_pregunta(filas, a, campo)
    de_b = aciertos_por_pregunta(filas, b, campo)
    comunes = sorted(set(de_a) & set(de_b))
    solo_a = sum(1 for i in comunes if de_a[i] and not de_b[i])
    solo_b = sum(1 for i in comunes if de_b[i] and not de_a[i])
    exitos_a = sum(1 for i in comunes if de_a[i])
    exitos_b = sum(1 for i in comunes if de_b[i])
    return {
        "campo": campo,
        "n": len(comunes),
        "exitos_a": exitos_a,
        "exitos_b": exitos_b,
        "ic_a": wilson(exitos_a, len(comunes)),
        "ic_b": wilson(exitos_b, len(comunes)),
        "solo_a": solo_a,
        "solo_b": solo_b,
        "p": mcnemar(solo_a, solo_b),
    }


def medianas(filas: list[dict[str, Any]], modelo: str) -> float:
    """Mediana del tiempo de generación de un modelo, en segundos."""
    tiempos = sorted(f["segundos_generar"] for f in filas if f["modelo"] == modelo)
    if not tiempos:
        return 0.0
    mitad = len(tiempos) // 2
    if len(tiempos) % 2:
        return tiempos[mitad]
    return (tiempos[mitad - 1] + tiempos[mitad]) / 2


def informe(filas: list[dict[str, Any]], a: str, b: str) -> str:
    """Compone el informe en Markdown."""
    lineas = [
        f"# Comparación pareada: `{a}` frente a `{b}`",
        "",
        "> Lo escribe `scripts/experimentos/comparar_dos_modelos.py`. "
        "**No editar a mano.**",
        "",
        "Los dos modelos respondieron **las mismas preguntas**, así que se "
        "comparan por pares y no como dos medias sueltas. Cada tasa lleva su "
        "intervalo de Wilson al 95 %; la diferencia, la prueba exacta de "
        "McNemar sobre los pares discordantes, que son los únicos que "
        "distinguen a alguien.",
        "",
        f"- Preguntas del banco: **{len({f['id'] for f in filas})}**",
        f"- Respuestas medidas: **{len(filas)}**",
        f"- Umbral de decisión, fijado de antemano: **p < {ALFA}**",
        "",
        "## Resultados",
        "",
        f"| Métrica | n | `{a}` | `{b}` | Solo A | Solo B | p | ¿Se distinguen? |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for campo in METRICAS:
        r = comparar(filas, a, b, campo)
        if not r["n"]:
            continue
        distinto = "**sí**" if r["p"] < ALFA else "no"
        lineas.append(
            f"| {campo} | {r['n']} | "
            f"{r['exitos_a'] / r['n']:.3f} "
            f"[{r['ic_a'][0]:.3f}–{r['ic_a'][1]:.3f}] | "
            f"{r['exitos_b'] / r['n']:.3f} "
            f"[{r['ic_b'][0]:.3f}–{r['ic_b'][1]:.3f}] | "
            f"{r['solo_a']} | {r['solo_b']} | {r['p']:.3f} | {distinto} |"
        )
    lineas += [
        "",
        "**Solo A** son las preguntas que acierta el primero y falla el "
        "segundo, y **Solo B** al revés. Si las dos columnas son cero, los "
        "modelos respondieron igual de bien en todas y **no hay diferencia "
        "que medir**, por muchas preguntas que se añadan.",
        "",
        "## Tiempo",
        "",
        "| Modelo | Mediana de generación (s) |",
        "| --- | ---: |",
        f"| `{a}` | {medianas(filas, a):.1f} |",
        f"| `{b}` | {medianas(filas, b):.1f} |",
        "",
        "El tiempo se informa y **no descarta**: la máquina no está en "
        "condiciones controladas mientras se mide.",
        "",
        "## Cómo se lee esto",
        "",
        "Un `p` alto **no demuestra que los dos modelos sean iguales**. "
        "Demuestra que este banco no los distingue, que es una afirmación más "
        "débil y es la única que los datos sostienen. Lo que acota cuánta "
        "diferencia podría seguir habiendo sin verse es la anchura de los "
        "intervalos, no el valor de `p`.",
    ]
    return "\n".join(lineas) + "\n"


def main(argumentos: list[str] | None = None) -> int:
    """Punto de entrada."""
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--registro", required=True)
    analizador.add_argument("--modelos", nargs=2, required=True)
    analizador.add_argument("--salida", required=True)
    opciones = analizador.parse_args(argumentos)

    ruta = Path(opciones.registro)
    exigir(ruta.exists(), f"no existe el registro {ruta}")
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    filas = [json.loads(linea) for linea in lineas if linea]
    a, b = opciones.modelos

    presentes = {f["modelo"] for f in filas}
    exigir(
        {a, b} <= presentes,
        lambda: f"el registro tiene {sorted(presentes)} y se piden {a} y {b}",
    )

    # Emparejar exige que los dos hayan visto lo mismo. Si no, la comparación
    # mide además qué preguntas le tocaron a cada uno.
    por_modelo: dict[str, set[str]] = defaultdict(set)
    for fila in filas:
        por_modelo[fila["modelo"]].add(fila["id"])
    exigir(
        por_modelo[a] == por_modelo[b],
        lambda: (
            f"los modelos no vieron las mismas preguntas: "
            f"{len(por_modelo[a] - por_modelo[b])} solo las vio {a} y "
            f"{len(por_modelo[b] - por_modelo[a])} solo {b}"
        ),
    )

    salida = Path(opciones.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(informe(filas, a, b), encoding="utf-8")
    print(f"Informe escrito en {salida}")
    for campo in METRICAS:
        r = comparar(filas, a, b, campo)
        if r["n"]:
            veredicto = "SE DISTINGUEN" if r["p"] < ALFA else "no se distinguen"
            print(
                f"  {campo}: {r['exitos_a']}/{r['n']} vs {r['exitos_b']}/{r['n']} "
                f"| discordantes {r['solo_a']}/{r['solo_b']} | p={r['p']:.3f} "
                f"-> {veredicto}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

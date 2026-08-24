"""Evaluación de la recuperación del sistema sobre el conjunto de IT-27 (IT-38).

Mide lo que llega al modelo, que es la mitad del sistema que ninguna de las
otras medidas cubre: el cribado de IT-35 compara *generadores* dándoles a todos
el mismo contexto, así que sus cifras no dicen nada sobre si ese contexto era
el correcto. Aquí se responde justo eso.

Lo que se mide, todo **contra el corpus** y sin que ningún modelo juzgue a otro
---:mod:`tfg_uja.evaluacion` calcula las tres primeras y este guion las dos
últimas---:

* **Recall@K por fragmento.** De los trozos que resuelven la pregunta, cuántos
  entran entre los K primeros. Mide cobertura.
* **Recall@K por unidad.** Si la asignatura correcta aparece, sin castigar que
  se quede fuera alguno de sus trozos. Mide acierto.
* **MRR.** En qué posición aparece el primer fragmento útil.
* **El techo de cada K.** Hay preguntas cuyas unidades relevantes son más que
  K, de modo que su Recall@K no puede valer 1 por mucho que el recuperador
  acierte. Leer una cifra contra 1 en vez de contra su techo hace parecer al
  recuperador peor de lo que es, y por eso el techo se imprime **antes**.
* **Las preguntas ajenas al dominio.** No entran en las métricas anteriores:
  su lista de relevantes está vacía y aportarían un cero fijo a las dos. Su
  criterio es el contrario ---rechazar es acertar--- y se mide aparte, contando
  cuántas se quedan sin ningún fragmento al pasar por el recuperador real.

El orden del ranking se calcula por fuerza bruta sobre los vectores, no
consultando el índice. No son dos cosas distintas: el ADR-0004 midió que la
base elegida devuelve **exactamente** los mismos vecinos que la búsqueda
exacta, y ese fue el umbral que descartó a una de las candidatas. Las preguntas
ajenas sí pasan por el índice, porque ahí lo que se comprueba no es el orden
sino el corte, y el corte lo aplica el recuperador.

Uso::

    py scripts/experimento_recuperacion.py
    py scripts/experimento_recuperacion.py --salida otro/sitio.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from tfg_uja.evaluacion import chunks_relevantes, evaluar_modelo  # noqa: E402
from tfg_uja.generador import pregunta_por_otro_centro  # noqa: E402
from tfg_uja.incrustaciones import (  # noqa: E402
    MODELO,
    incrustador_de_consultas,
    incrustador_de_documentos,
)
from tfg_uja.recuperador import (  # noqa: E402
    K_MAXIMO,
    abrir_indice,
    catalogo_del_indice,
    contexto_para,
    distancia_del_indice,
    pide_recomendacion,
)

#: Valores de K que se informan. El 3 y el 5 son los que un sistema RAG entrega
#: de verdad; el 10 es el máximo de la banda en las preguntas de listado.
KS: Final[tuple[int, ...]] = (3, 5, 10)

RUTA_CHUNKS: Final[Path] = RAIZ / "data" / "chunks.json"
RUTA_EVAL: Final[Path] = RAIZ / "eval" / "preguntas_evaluacion.json"
RUTA_INDICE: Final[Path] = RAIZ / "data" / "indice_lance"
RUTA_VALIDACION: Final[Path] = (
    RAIZ / "eval" / "preguntas_fuera_de_dominio_validacion.json"
)
RUTA_SALIDA: Final[Path] = RAIZ / "docs" / "experimentos" / "it38-recuperacion.md"


def cargar_chunks(ruta: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Lee los fragmentos separando el registro de procedencia.

    Se filtra **por tipo y nunca por posición**: dar por hecho que la
    procedencia va la primera convierte un cambio de orden en un fragmento
    fantasma dentro del corpus.

    Args:
        ruta: Fichero ``chunks.json``.

    Returns:
        ``(fragmentos, procedencia)``.
    """
    items = json.loads(ruta.read_text(encoding="utf-8"))
    chunks = [i for i in items if i.get("tipo") == "chunk"]
    procedencia: dict[str, Any] = next(
        (i for i in items if i.get("tipo") == "procedencia"), {}
    )
    return chunks, procedencia


def techo_de_recall(
    preguntas: list[dict[str, Any]], chunks: list[dict[str, Any]], k: int
) -> float:
    """El Recall@K más alto que este corpus permite alcanzar.

    Una pregunta con siete fragmentos relevantes no puede pasar de 3/7 con
    K=3, por perfecto que sea el orden. El techo promedia ese límite sobre
    todas las preguntas y es la referencia contra la que hay que leer la cifra
    medida.

    Args:
        preguntas: Preguntas de dominio.
        chunks: Fragmentos del corpus.
        k: Cuántos se entregan.

    Returns:
        Media de ``min(k, relevantes) / relevantes``.
    """
    limites = []
    for pregunta in preguntas:
        cuantos = len(chunks_relevantes(pregunta, chunks))
        limites.append(min(k, cuantos) / cuantos if cuantos else 0.0)
    return sum(limites) / len(limites) if limites else 0.0


def medir_ajenas(
    preguntas: list[dict[str, Any]], ruta_indice: Path
) -> list[tuple[str, int, bool, bool]]:
    """Cuántos fragmentos recibe cada pregunta ajena al dominio.

    Pasa por el recuperador **real**, con su banda, su corte relativo y su
    suelo, porque lo que se comprueba aquí no es el orden de los vecinos sino
    si el sistema decide que no hay nada pertinente. Cero fragmentos es el
    resultado correcto: significa que ni siquiera se llamará al modelo.

    De cada pregunta que **sí** pasa el suelo se registra además qué hay
    debajo, porque «pasa el filtro» y «el sistema la responde» no son lo mismo
    y confundirlos exagera el fallo: una petición de consejo pasa a propósito,
    y una pregunta por otro centro la para la comprobación del generador. Lo
    que de verdad preocupa es la que pasa sin ninguna de las dos cosas.

    Args:
        preguntas: Preguntas de tipo ``fuera_de_dominio``.
        ruta_indice: Carpeta donde persiste el indice vectorial.

    Returns:
        Una tupla ``(id, fragmentos, es petición de consejo, la para la
        comprobación de otro centro)`` por pregunta.
    """
    tabla = abrir_indice(ruta_indice, MODELO)
    incrustar = incrustador_de_consultas(MODELO)
    distancia = distancia_del_indice(ruta_indice)
    catalogo = catalogo_del_indice(ruta_indice)
    medidas = []
    for pregunta in preguntas:
        traidos = contexto_para(
            pregunta["pregunta"],
            tabla,
            incrustar,
            distancia=distancia,
            k=K_MAXIMO,
            catalogo=catalogo,
        )
        medidas.append(
            (
                pregunta["id"],
                len(traidos),
                pide_recomendacion(pregunta["pregunta"]),
                pregunta_por_otro_centro(pregunta["pregunta"]) is not None,
            )
        )
    return medidas


def _resumen_de_las_que_pasan(medidas: list[tuple[str, int, bool, bool]]) -> str:
    """Frase que reparte las preguntas que pasan el suelo según qué las frena.

    Se compone aquí y no en línea porque la concordancia importa: el informe lo
    lee un tribunal, y «Quedan 1 sin red» delata que la frase la escribe un
    contador y no una persona.

    Args:
        medidas: Tuplas ``(id, fragmentos, consejo, otro centro)``.

    Returns:
        La frase entera, o una que lo diga si no pasa ninguna.
    """
    pasan = [(cj, o) for _, cuantos, cj, o in medidas if cuantos]
    if not pasan:
        return "No pasa ninguna: el suelo las rechaza todas."
    consejo = sum(1 for cj, _o in pasan if cj)
    centro = sum(1 for cj, o in pasan if not cj and o)
    sin_red = sum(1 for cj, o in pasan if not cj and not o)
    quedan = (
        "Queda **1 sin ninguna red debajo**"
        if sin_red == 1
        else (f"Quedan **{sin_red} sin ninguna red debajo**")
    )
    return (
        f"De las {len(pasan)} que pasan, **{consejo} "
        f"{'pide' if consejo == 1 else 'piden'} consejo** y **{centro} "
        f"{'la para' if centro == 1 else 'las para'} la comprobación de otro "
        f"centro**. {quedan}, y esa es la cifra del hueco."
    )


def informe(
    agregados: dict[str, float],
    techos: dict[int, float],
    ajenas: list[tuple[str, int, bool, bool]],
    validacion: list[tuple[str, int, bool, bool]],
    cuantos_chunks: int,
    cuantas_preguntas: int,
    procedencia: dict[str, Any],
    destino: Path,
) -> None:
    """Escribe el resultado en Markdown.

    Args:
        agregados: Medias que devuelve :func:`evaluar_modelo`.
        techos: Techo de Recall@K por fragmento, por cada K.
        ajenas: Fragmentos recibidos por cada pregunta ajena del conjunto
            de IT-27, con el que se ajustó el suelo.
        validacion: Lo mismo sobre el conjunto que no intervino en el ajuste.
        cuantos_chunks: Tamaño del corpus medido.
        cuantas_preguntas: Preguntas de dominio medidas.
        procedencia: Registro de procedencia del corpus.
        destino: Fichero de salida.
    """
    rechazadas = sum(1 for _, cuantos, _c, _o in ajenas if cuantos == 0)
    consejos = sum(1 for _, cuantos, consejo, _o in ajenas if cuantos and consejo)
    con_red = sum(
        1 for _, cuantos, consejo, otro in ajenas if cuantos and not consejo and otro
    )
    sin_red = sum(
        1
        for _, cuantos, consejo, otro in ajenas
        if cuantos and not consejo and not otro
    )
    lineas = [
        "# Recuperación del sistema sobre el conjunto de IT-27 (IT-38)",
        "",
        "> Lo escribe `scripts/experimento_recuperacion.py`. **No editar a mano.**",
        "",
        f"- Modelo de incrustaciones: `{MODELO}`",
        f"- Fragmentos del corpus: **{cuantos_chunks}**",
        f"- Preguntas de dominio: **{cuantas_preguntas}**",
        f"- Preguntas ajenas al dominio: **{len(ajenas)}**",
        f"- Procedencia del corpus: extracción "
        f"{procedencia.get('fecha_extraccion', '?')}, "
        f"origen {procedencia.get('origen', '?')}",
        "",
        "## Techos alcanzables",
        "",
        "Hay preguntas cuyas unidades relevantes son más que K, así que su",
        "Recall@K no puede valer 1. **Cada cifra se lee contra su techo, no",
        "contra 1.** Por unidad el techo siempre es 1 y la cifra se interpreta",
        "sola.",
        "",
        "| K | Techo de Recall@K por fragmento |",
        "| ---: | ---: |",
    ]
    for k in KS:
        lineas.append(f"| {k} | {techos[k]:.3f} |")
    lineas += [
        "",
        "## Resultado",
        "",
        "| K | Recall@K | Techo | Recall de unidad@K |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for k in KS:
        lineas.append(
            f"| {k} | {agregados[f'recall@{k}']:.3f} | {techos[k]:.3f} | "
            f"{agregados[f'recall_unidad@{k}']:.3f} |"
        )
    lineas += [
        "",
        f"**MRR: {agregados['mrr']:.3f}**",
        "",
        "## Preguntas ajenas al dominio",
        "",
        "No entran en las métricas de arriba: su lista de relevantes está vacía",
        "y aportarían un cero fijo a las dos. Aquí el acierto es el contrario,",
        "quedarse sin ningún fragmento, porque entonces no se llega a llamar al",
        "modelo.",
        "",
        f"**Rechazadas por el recuperador: {rechazadas} de {len(ajenas)}.**",
        "",
        f"De las {len(ajenas) - rechazadas} que pasan el suelo, no todas son un",
        "fallo, y mezclarlas exagera el problema. Se separan en tres:",
        "",
        f"* **{consejos} {'es petición' if consejos == 1 else 'son peticiones'} de",
        "  consejo**, y que pasen es deliberado: a esas el sistema les entrega la",
        "  banda completa a propósito. Quien pregunta qué carrera le pega no debe",
        "  recibir silencio, sino lo que sí se imparte aquí. Contarlas como fallo",
        "  del filtro sería contar como error el comportamiento que se busca.",
        f"* **{con_red} {'la para' if con_red == 1 else 'las para'} la comprobación",
        "  de otro centro**, que actúa después del suelo y antes del modelo. Pasar",
        "  el suelo no es lo mismo que ser respondida.",
        f"* **{sin_red} {'pasa' if sin_red == 1 else 'pasan'} sin ninguna de las dos",
        "  cosas.** Esta es la cifra que mide de verdad el hueco, y la única que",
        "  hay que mirar para saber si el sistema se sale de su dominio.",
        "",
        "| Pregunta | Fragmentos recibidos | Petición de consejo | Otro centro |",
        "| --- | ---: | :---: | :---: |",
    ]
    for identificador, cuantos, consejo, otro in ajenas:
        marca = "rechazada" if cuantos == 0 else f"{cuantos}"
        lineas.append(
            f"| {identificador} | {marca} | {'sí' if consejo else 'no'} "
            f"| {'sí' if otro else 'no'} |"
        )
    if validacion:
        limpias = sum(1 for _, cuantos, _c, _o in validacion if cuantos == 0)
        lineas += [
            "",
            "## Rechazo sobre preguntas que no intervinieron en el ajuste",
            "",
            "El suelo de pertinencia se eligió optimizando el rechazo sobre las",
            "preguntas ajenas de la tabla anterior, así que aquella cifra dice lo",
            "bien que se ajustó el parámetro, no lo bien que el sistema rechaza.",
            "**Esta es la que sostiene una conclusión**: ninguna de estas",
            "preguntas ha intervenido en ningún ajuste.",
            "",
            f"**Rechazadas por el suelo: {limpias} de {len(validacion)}.**",
            "",
            _resumen_de_las_que_pasan(validacion),
            "",
            "| Pregunta | Fragmentos recibidos | Petición de consejo | Otro centro |",
            "| --- | ---: | :---: | :---: |",
        ]
        for identificador, cuantos, consejo, otro in validacion:
            marca = "rechazada" if cuantos == 0 else f"{cuantos}"
            lineas.append(
                f"| {identificador} | {marca} | {'sí' if consejo else 'no'} "
                f"| {'sí' if otro else 'no'} |"
            )
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main(argumentos: list[str] | None = None) -> None:
    """Punto de entrada.

    Args:
        argumentos: Argumentos de línea de comandos.
    """
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--chunks", type=Path, default=RUTA_CHUNKS)
    analizador.add_argument("--indice", type=Path, default=RUTA_INDICE)
    analizador.add_argument("--validacion", type=Path, default=RUTA_VALIDACION)
    analizador.add_argument("--salida", type=Path, default=RUTA_SALIDA)
    opciones = analizador.parse_args(argumentos)

    chunks, procedencia = cargar_chunks(opciones.chunks)
    todas = json.loads(RUTA_EVAL.read_text(encoding="utf-8"))["preguntas"]
    dominio = [p for p in todas if p["tipo"] != "fuera_de_dominio"]
    ajenas_declaradas = [p for p in todas if p["tipo"] == "fuera_de_dominio"]

    print(f"Corpus: {len(chunks)} fragmentos | dominio: {len(dominio)} preguntas")
    for k in KS:
        print(f"  techo de Recall@{k}: {techo_de_recall(dominio, chunks, k):.3f}")

    print(f"Incrustando con {MODELO}...")
    resultado = evaluar_modelo(
        chunks,
        dominio,
        incrustador_de_documentos(MODELO),
        incrustador_de_consultas(MODELO),
        ks=KS,
    )
    agregados = resultado["agregados"]
    for k in KS:
        print(
            f"  R@{k} = {agregados[f'recall@{k}']:.3f} | "
            f"RU@{k} = {agregados[f'recall_unidad@{k}']:.3f}"
        )
    print(f"  MRR = {agregados['mrr']:.3f}")

    print("Midiendo las preguntas ajenas contra el índice real...")
    ajenas = medir_ajenas(ajenas_declaradas, opciones.indice)
    rechazadas = sum(1 for _, cuantos, _c, _o in ajenas if cuantos == 0)
    consejos = sum(1 for _, cuantos, consejo, _o in ajenas if cuantos and consejo)
    print(
        f"  rechazadas: {rechazadas} de {len(ajenas)} "
        f"({consejos} de las que pasan piden consejo)"
    )

    validacion: list[tuple[str, int, bool, bool]] = []
    if opciones.validacion.exists():
        print("Midiendo el conjunto que no intervino en el ajuste...")
        sueltas = json.loads(opciones.validacion.read_text(encoding="utf-8"))[
            "preguntas"
        ]
        validacion = medir_ajenas(sueltas, opciones.indice)
        limpias = sum(1 for _, cuantos, _c, _o in validacion if cuantos == 0)
        sueltas_sin_red = sum(
            1 for _, c, consejo, otro in validacion if c and not consejo and not otro
        )
        print(
            f"  rechazadas: {limpias} de {len(validacion)} "
            f"({sueltas_sin_red} "
            f"{'pasa' if sueltas_sin_red == 1 else 'pasan'} sin ninguna red debajo)"
        )

    informe(
        agregados,
        {k: techo_de_recall(dominio, chunks, k) for k in KS},
        ajenas,
        validacion,
        len(chunks),
        len(dominio),
        procedencia,
        opciones.salida,
    )
    print(f"Informe escrito en {opciones.salida}")


if __name__ == "__main__":
    main()

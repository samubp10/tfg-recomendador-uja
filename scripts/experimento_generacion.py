"""Compara modelos generativos sobre el banco de preguntas de IT-35.

Este guion **no elige el modelo**: criba candidatos. La elección es IT-36 y se
escribe en su ADR; aquí solo se mide, con el mismo tubo que usa el chat, cuánto
tarda cada candidato y cuánto de lo que dice existe de verdad.

Lo que se mide y por qué
------------------------

Comparar generadores «a ojo» no se sostiene ante un tribunal: quien mira ya
tiene una preferencia. Lo que sí es objetivo es contrastar la respuesta contra
el corpus, porque el corpus contiene todos los nombres de titulación y de
asignatura de la EPSJ. De ahí salen cuatro cifras, todas sin juez:

* **Titulaciones inventadas.** Nombres con forma de titulación que no están en
  el catálogo. Es el fallo más grave que puede cometer el sistema ---a un
  preuniversitario recomendarle una carrera que no existe--- y por eso se trata
  como criterio eliminatorio, no como una penalización más.
* **Precisión del listado.** De lo que el modelo enumera, cuánto existe.
* **Cobertura del listado.** De lo que el dataset dice, cuánto aparece. Hacen
  falta las dos: un modelo puede no inventarse nada y dejarse media lista.
* **Acierto escalar.** En las preguntas de créditos y de curso la respuesta es
  un único valor, así que se compara con el del dataset.

Y el tiempo, que se informa pero **no descarta**: eliminar por tiempo exige una
máquina en condiciones controladas, y esta responde mientras hace otras cosas.
Se activa con ``--presupuesto`` cuando se pueda medir en reposo.

Lo que NO se mide
-----------------

Si la respuesta está bien escrita, si la recomendación es buena o si el temario
que resume es fiel. Nada de eso se computa del dataset, así que no entra en el
criterio de decisión. Se observa aparte, a mano, y se cuenta como tal.

La medición tampoco separa el fallo del modelo del fallo del recuperador: si no
llega el fragmento, el modelo no puede acertar. Por eso se registra también
cuántos fragmentos recibió cada respuesta.

Uso::

    py scripts/experimento_generacion.py --modelos ministral-8b:latest gemma3:12b
    py scripts/experimento_generacion.py --limite 10          # prueba corta
    py scripts/experimento_generacion.py --solo-informe       # solo reescribe el .md
    py scripts/experimento_generacion.py --recalcular         # repuntúa lo guardado

Las respuestas se van guardando según se producen y una ejecución nueva **no
repite** lo ya medido: con modelos que tardan minutos por pregunta, perder dos
horas por un corte del servidor no es aceptable.

Escribe **fuera del repositorio**, en ``Notas_TFG/pruebas_chat/``. Un cribado no
es una decisión de arquitectura: cuando IT-36 elija el modelo, sus cifras irán
al ADR-0005, que es donde este proyecto guarda los resultados de experimentos.
Mientras tanto son notas de trabajo y no tienen por qué versionarse.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Final

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

RAIZ = Path(__file__).resolve().parent.parent

#: Dónde se dejan las notas de trabajo, fuera del repositorio.
NOTAS = RAIZ.parent / "Notas_TFG" / "pruebas_chat"

sys.path.insert(0, str(RAIZ / "src"))

from tfg_uja.conversacion import Conversacion  # noqa: E402
from tfg_uja.generador import SERVIDOR, ErrorDelModelo  # noqa: E402
from tfg_uja.generador import construir_prompt, generar  # noqa: E402
from tfg_uja.incrustaciones import MODELO, incrustador_de_consultas  # noqa: E402
from tfg_uja.recuperador import (  # noqa: E402
    K_MAXIMO,
    abrir_indice,
    acotar_por_distancia,
    catalogo_del_indice,
    distancia_del_indice,
    recuperar,
)
from tfg_uja.text_cleaner import normalizar  # noqa: E402
from tfg_uja.verificacion import cotejar_listado  # noqa: E402
from tfg_uja.verificacion import titulaciones_inventadas  # noqa: E402

#: Candidatos que se criban si no se dice otra cosa: **todos los instalados**.
#: La criba final se hace con los siete a la vez, no por tandas, para que
#: ninguno se compare contra una medición tomada en otras condiciones.
MODELOS: Final[tuple[str, ...]] = (
    "granite4.1:8b",
    "command-r7b",
    "ministral-8b:latest",
    "salamandra-7b",
    "mistral-nemo:12b",
    "gemma3:12b",
    "qwen2.5:14b",
)

#: Tope de tiempo por respuesta, en segundos. **Cero significa sin tope**, que
#: es lo normal en este proyecto.
#:
#: El tope existe porque un estudiante espera delante de la pantalla, pero
#: **descartar por tiempo exige una máquina en condiciones controladas** y esta
#: no lo está: las respuestas se miden mientras el equipo hace otras cosas, y el
#: 18/08/2026 una respuesta de 581 caracteres marcó 16.677 s porque el sistema
#: estaba paginando a disco. Con esa varianza, el tiempo describe la máquina y
#: no al candidato, así que se informa pero no elimina. Se activa a propósito,
#: con ``--presupuesto``, cuando se pueda medir en reposo.
PRESUPUESTO: Final[float] = 0.0

#: Cómo se escribe una cantidad de créditos en una respuesta libre.
_ECTS: Final[re.Pattern[str]] = re.compile(
    r"(\d+[.,]?\d*)\s*(?:ECTS|cr[ée]ditos)", re.IGNORECASE
)


#: Rótulo con el que la fuente marca las optativas que no pertenecen a ninguna
#: mención. No es una mención, y el banco tampoco lo genera como tal.
NO_ES_MENCION: Final[str] = "Común a todas las menciones"


def asignaturas_del_corpus(datos: list[dict[str, Any]]) -> set[str]:
    """Todos los nombres de asignatura que publica la fuente.

    Args:
        datos: Contenido de ``data/grados.json``.

    Returns:
        Los nombres, sin normalizar.
    """
    return {
        str(d["nombre"])
        for d in datos
        if d.get("tipo") == "asignatura" and d.get("nombre")
    }


def menciones_del_corpus(datos: list[dict[str, Any]]) -> set[str]:
    """Todos los nombres de mención que publica la fuente.

    Args:
        datos: Contenido de ``data/grados.json``.

    Returns:
        Los nombres, sin el rótulo que no designa ninguna mención.
    """
    return {
        str(m)
        for d in datos
        if d.get("tipo") == "asignatura"
        for m in d.get("menciones", [])
        if m and m != NO_ES_MENCION
    }


def universo(
    pregunta: dict[str, Any],
    catalogo: list[str],
    asignaturas: set[str],
    menciones: set[str],
) -> set[str]:
    """Contra qué conjunto de nombres se comprueba lo que enumera la respuesta.

    No es el mismo para todas las preguntas, y equivocarlo falsea la precisión
    sin que nada avise. Medido el 18/08/2026: comprobando las trece preguntas
    de mención contra los nombres de asignatura, los **tres** candidatos daban
    precisión 0,59-0,62 por enumerar bien las menciones que se les pedían.
    Que los tres coincidan en una cifra tan baja era la señal de que fallaba el
    instrumento y no los modelos.

    La familia ``menciones`` lleva dos preguntas distintas dentro, y se
    distinguen por su ámbito: si trae ``mencion``, se pregunta por las
    asignaturas de esa mención; si no, por las menciones de la titulación.

    Args:
        pregunta: Registro del banco.
        catalogo: Titulaciones que declara el índice.
        asignaturas: Nombres de asignatura del corpus.
        menciones: Nombres de mención del corpus.

    Returns:
        Los nombres válidos para esa pregunta.
    """
    if pregunta["familia"] == "catalogo":
        return set(catalogo)
    if pregunta["familia"] == "menciones" and "mencion" not in pregunta["ambito"]:
        return menciones
    return asignaturas


def acierto_escalar(respuesta: str, esperado: str, familia: str) -> tuple[bool, str]:
    """Comprueba una respuesta de valor único contra la del dataset.

    Los créditos se buscan **con su unidad detrás**. Sin ella la comprobación
    sería falsa: en una respuesta de tres líneas casi siempre aparece suelto un
    «6» por algún lado, y contarlo como acierto daría por bueno a un modelo que
    no ha respondido a la pregunta.

    Args:
        respuesta: Texto tal como lo devuelve el modelo.
        esperado: Valor que dice el dataset.
        familia: Familia de la pregunta, que decide cómo se busca.

    Returns:
        ``(acierta, dicho)``, donde ``dicho`` es lo que se le entendió al
        modelo, o cadena vacía si no se le entendió nada.
    """
    if familia == "creditos":
        dichos = {
            v.replace(",", ".").rstrip("0").rstrip(".")
            for v in _ECTS.findall(respuesta)
        }
        limpio = esperado.replace(",", ".").rstrip("0").rstrip(".")
        return limpio in dichos, " · ".join(sorted(dichos))
    # El curso llega como rótulo de la fuente («Tercer o cuarto curso»). Se
    # busca sin la palabra «curso», que el modelo puede no repetir.
    nucleo = normalizar(esperado).replace(" curso", "").strip()
    return nucleo in normalizar(respuesta), ""


def medir(
    respuesta: str,
    pregunta: dict[str, Any],
    catalogo: list[str],
    asignaturas: set[str],
    menciones: set[str],
) -> dict[str, Any]:
    """Aplica a una respuesta las comprobaciones que correspondan a su familia.

    Args:
        respuesta: Texto tal como lo devuelve el modelo.
        pregunta: Registro del banco, con su ``esperado`` y su ``familia``.
        catalogo: Titulaciones que declara el índice.
        asignaturas: Nombres de asignatura del corpus.
        menciones: Nombres de mención del corpus.

    Returns:
        Las cifras de esa respuesta, listas para agregar.
    """
    esperado = [str(e) for e in pregunta["esperado"]]
    salida: dict[str, Any] = {
        "titulaciones_inventadas": sorted(titulaciones_inventadas(respuesta, catalogo)),
    }
    if pregunta["respuesta"] == "escalar":
        acierta, dicho = acierto_escalar(respuesta, esperado[0], pregunta["familia"])
        salida["acierto"] = acierta
        salida["dicho"] = dicho
        return salida
    precision, cobertura, inventadas, omitidas = cotejar_listado(
        respuesta,
        set(esperado),
        universo(pregunta, catalogo, asignaturas, menciones),
    )
    salida["precision"] = precision
    salida["cobertura"] = cobertura
    salida["inventadas"] = sorted(inventadas)
    salida["omitidas"] = len(omitidas)
    salida["esperadas"] = len(esperado)
    return salida


def responder_una(
    pregunta: str,
    modelo: str,
    tabla: Any,
    incrustar: Any,
    distancia: str,
    catalogo: list[str],
) -> tuple[str, float, float, int]:
    """Pasa una pregunta por el mismo tubo que el chat.

    No se usa :func:`tfg_uja.generador.responder` a propósito: esa función, sin
    fragmentos y sin historial, devuelve la bienvenida, que es lo correcto en
    una conversación y una medida falsa en un experimento. Aquí interesa dejar
    constancia de que la recuperación no trajo nada.

    Args:
        pregunta: Pregunta del banco.
        modelo: Nombre del modelo en el servidor local.
        tabla: Tabla del índice ya abierta.
        incrustar: Incrustador de consultas.
        distancia: Métrica del índice.
        catalogo: Titulaciones que declara el índice.

    Returns:
        ``(respuesta, segundos_recuperando, segundos_generando, fragmentos)``.
    """
    conversacion = Conversacion(catalogo)
    consulta = conversacion.preparar(pregunta)
    t0 = time.perf_counter()
    traidos = recuperar(
        consulta.texto,
        tabla,
        incrustar,
        distancia=distancia,
        k=K_MAXIMO,
        catalogo=catalogo,
        ambito=consulta.ambito,
    )
    fragmentos = acotar_por_distancia(traidos)
    t_recuperar = time.perf_counter() - t0
    if not fragmentos:
        return "", t_recuperar, 0.0, 0
    ambito = consulta.ambito[0] if len(consulta.ambito) == 1 else None
    prompt = construir_prompt(pregunta, fragmentos, None, ambito, catalogo)
    t1 = time.perf_counter()
    respuesta = generar(prompt, modelo)
    return respuesta, t_recuperar, time.perf_counter() - t1, len(fragmentos)


def version_del_servidor(servidor: str = SERVIDOR) -> str:
    """Versión del servidor de inferencia que está respondiendo.

    Se anota en cada respuesta porque el servidor **se actualiza solo**. El
    19/08/2026 saltó de la 0.23.2 a la 0.32.14 en mitad del cribado, entre las
    240 respuestas ya medidas y las que faltaban. Sin este dato, la diferencia
    entre unos candidatos y otros podría venir del tiempo de ejecución y no del
    modelo, y nadie se habría enterado.

    Args:
        servidor: Dirección del servidor de inferencia.

    Returns:
        La versión, o ``"desconocida"`` si el servidor no la dice. No se
        propaga el fallo: quedarse sin cribado por no saber la versión sería
        peor que anotarla como desconocida.
    """
    try:
        with urllib.request.urlopen(f"{servidor}/api/version", timeout=10) as respuesta:
            return str(json.loads(respuesta.read()).get("version", "desconocida"))
    except (urllib.error.URLError, ValueError, KeyError):
        return "desconocida"


def ya_medido(ruta: Path) -> set[tuple[str, str]]:
    """Pares ``(modelo, pregunta)`` que ya están en el registro.

    Args:
        ruta: Fichero de respuestas en JSONL.

    Returns:
        Las claves ya presentes, para no volver a pagarlas.
    """
    if not ruta.exists():
        return set()
    hechas = set()
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.strip():
            fila = json.loads(linea)
            hechas.add((fila["modelo"], fila["id"]))
    return hechas


def ejecutar(
    modelos: list[str],
    preguntas: list[dict[str, Any]],
    tabla: Any,
    incrustar: Any,
    distancia: str,
    catalogo: list[str],
    asignaturas: set[str],
    menciones: set[str],
    registro: Path,
) -> None:
    """Recorre cada modelo y cada pregunta, y va escribiendo el registro.

    El bucle exterior es el modelo, no la pregunta: alternarlos obligaría al
    servidor a cargar y descargar pesos entre respuestas, y en un equipo de
    16 GiB con candidatos de 6 a 9 GiB eso mediría el disco, no el modelo.

    Args:
        modelos: Candidatos a cribar.
        preguntas: Registros del banco.
        tabla: Tabla del índice ya abierta.
        incrustar: Incrustador de consultas.
        distancia: Métrica del índice.
        catalogo: Titulaciones que declara el índice.
        asignaturas: Nombres de asignatura del corpus.
        menciones: Nombres de mención del corpus.
        registro: Fichero JSONL al que se añade cada respuesta.
    """
    hechas = ya_medido(registro)
    version = version_del_servidor()
    print(f"Servidor de inferencia: {version}")
    for modelo in modelos:
        pendientes = [p for p in preguntas if (modelo, p["id"]) not in hechas]
        print(f"\n=== {modelo} — {len(pendientes)} pendientes de {len(preguntas)} ===")
        for i, pregunta in enumerate(pendientes, 1):
            try:
                texto, t_rec, t_gen, n = responder_una(
                    pregunta["pregunta"], modelo, tabla, incrustar, distancia, catalogo
                )
            except ErrorDelModelo as error:
                print(f"  [{i}/{len(pendientes)}] {pregunta['id']} FALLO: {error}")
                continue
            fila = {
                "modelo": modelo,
                "servidor": version,
                "id": pregunta["id"],
                "familia": pregunta["familia"],
                "pregunta": pregunta["pregunta"],
                "respuesta": texto,
                "fragmentos": n,
                "segundos_recuperar": round(t_rec, 3),
                "segundos_generar": round(t_gen, 3),
                **medir(texto, pregunta, catalogo, asignaturas, menciones),
            }
            with registro.open("a", encoding="utf-8") as fichero:
                fichero.write(json.dumps(fila, ensure_ascii=False) + "\n")
            marca = "!" if fila["titulaciones_inventadas"] else " "
            print(
                f"  [{i}/{len(pendientes)}]{marca}{pregunta['id']} "
                f"{t_gen:6.1f} s · {n:2d} frag · {pregunta['familia']}"
            )


def recalcular(
    filas: list[dict[str, Any]],
    banco: dict[str, dict[str, Any]],
    catalogo: list[str],
    asignaturas: set[str],
    menciones: set[str],
) -> list[dict[str, Any]]:
    """Vuelve a puntuar respuestas ya guardadas, sin llamar a ningún modelo.

    Existe porque el instrumento ha fallado dos veces en dos días y las dos se
    corrigió después de medir. Sin esto, cada arreglo obligaría a repetir horas
    de inferencia, y esa factura empuja a dar por buena una métrica dudosa.
    Las respuestas son el dato caro; puntuarlas es gratis y se rehace.

    Args:
        filas: Respuestas ya medidas, tal como están en el JSONL.
        banco: Preguntas indexadas por identificador.
        catalogo: Titulaciones que declara el índice.
        asignaturas: Nombres de asignatura del corpus.
        menciones: Nombres de mención del corpus.

    Returns:
        Las mismas filas con las cifras recalculadas.
    """
    nuevas = []
    for fila in filas:
        cifras = {
            k: v
            for k, v in fila.items()
            if k
            not in {
                "titulaciones_inventadas",  # se recalculan; el resto se conserva
                "acierto",
                "dicho",
                "precision",
                "cobertura",
                "inventadas",
                "omitidas",
                "esperadas",
            }
        }
        cifras.update(
            medir(
                fila["respuesta"],
                banco[fila["id"]],
                catalogo,
                asignaturas,
                menciones,
            )
        )
        nuevas.append(cifras)
    return nuevas


def _media(valores: list[float]) -> float:
    """Media aritmética, o 0,0 si no hay valores.

    Args:
        valores: Cifras a promediar.

    Returns:
        La media, o 0,0 si la lista está vacía.
    """
    return statistics.fmean(valores) if valores else 0.0


def resumir(
    filas: list[dict[str, Any]], presupuesto: float = PRESUPUESTO
) -> dict[str, dict[str, Any]]:
    """Agrega el registro por modelo.

    Args:
        filas: Respuestas medidas, tal como están en el JSONL.
        presupuesto: Tope de tiempo por respuesta, o 0 para no aplicarlo.

    Returns:
        Un resumen por modelo, con las cifras que deciden y las que describen.
    """
    resumen: dict[str, dict[str, Any]] = {}
    for modelo in dict.fromkeys(f["modelo"] for f in filas):
        suyas = [f for f in filas if f["modelo"] == modelo]
        listados = [f for f in suyas if "precision" in f]
        escalares = [f for f in suyas if "acierto" in f]
        tiempos = [f["segundos_generar"] for f in suyas if f["fragmentos"]]
        inventadas = [f for f in suyas if f["titulaciones_inventadas"]]
        resumen[modelo] = {
            "respuestas": len(suyas),
            "titulaciones_inventadas": len(inventadas),
            "preguntas_con_invencion": sorted(f["id"] for f in inventadas),
            "nombres_inventados": sorted(
                {n for f in inventadas for n in f["titulaciones_inventadas"]}
            ),
            "precision": _media([f["precision"] for f in listados]),
            "cobertura": _media([f["cobertura"] for f in listados]),
            "listados": len(listados),
            "acierto_escalar": _media(
                [1.0 if f["acierto"] else 0.0 for f in escalares]
            ),
            "escalares": len(escalares),
            "sin_contexto": sum(1 for f in suyas if not f["fragmentos"]),
            "mediana_s": statistics.median(tiempos) if tiempos else 0.0,
            "p90_s": (
                sorted(tiempos)[min(len(tiempos) - 1, int(0.9 * len(tiempos)))]
                if tiempos
                else 0.0
            ),
            "max_s": max(tiempos) if tiempos else 0.0,
            "fuera_de_presupuesto": (
                sum(1 for t in tiempos if t > presupuesto) if presupuesto else 0
            ),
        }
    return resumen


def por_familia(filas: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Agrega el registro por modelo y familia, para ver dónde falla cada uno.

    Args:
        filas: Respuestas medidas.

    Returns:
        ``{modelo: {familia: cifras}}``.
    """
    salida: dict[str, dict[str, Any]] = {}
    for modelo in dict.fromkeys(f["modelo"] for f in filas):
        salida[modelo] = {}
        suyas = [f for f in filas if f["modelo"] == modelo]
        for familia in dict.fromkeys(f["familia"] for f in suyas):
            trozo = [f for f in suyas if f["familia"] == familia]
            listados = [f for f in trozo if "precision" in f]
            escalares = [f for f in trozo if "acierto" in f]
            salida[modelo][familia] = {
                "n": len(trozo),
                "precision": _media([f["precision"] for f in listados]),
                "cobertura": _media([f["cobertura"] for f in listados]),
                "acierto": _media([1.0 if f["acierto"] else 0.0 for f in escalares]),
                "es_listado": bool(listados),
                "mediana_s": statistics.median([f["segundos_generar"] for f in trozo]),
            }
    return salida


def informe(
    filas: list[dict[str, Any]],
    banco: dict[str, Any],
    destino: Path,
    presupuesto: float = PRESUPUESTO,
) -> None:
    """Escribe el resultado en Markdown.

    Lo escribe el guion y no una persona: así las cifras del informe no pueden
    discrepar de las medidas, que es un modo de fallo que este proyecto ya ha
    sufrido en un ADR.

    Args:
        filas: Respuestas medidas.
        banco: Banco de preguntas, del que se toma la procedencia del dataset.
        destino: Fichero Markdown que se reescribe entero.
        presupuesto: Tope de tiempo por respuesta, o 0 para no aplicarlo.
    """
    resumen = resumir(filas, presupuesto)
    familias = por_familia(filas)
    lineas: list[str] = []
    escribir = lineas.append
    escribir("# Cribado de modelos generativos (IT-35)")
    escribir("")
    escribir("> Lo escribe `scripts/experimento_generacion.py`. **No editar a mano.**")
    escribir("")
    escribir(f"- Preguntas del banco usadas: **{len({f['id'] for f in filas})}**")
    escribir(f"- Respuestas medidas: **{len(filas)}**")
    if presupuesto:
        escribir(f"- Presupuesto de tiempo por respuesta: **{presupuesto:.0f} s**")
    else:
        escribir(
            "- Presupuesto de tiempo: **sin tope**. El equipo no está en "
            "condiciones controladas mientras se mide, así que el tiempo se "
            "informa pero **no descarta a ningún candidato**."
        )
    for clave, valor in banco.get("procedencia_del_dataset", {}).items():
        escribir(f"- {clave}: {valor}")
    servidores = sorted({str(f.get("servidor", "sin anotar")) for f in filas})
    escribir(f"- Servidor de inferencia: {' · '.join(servidores)}")
    if len(servidores) > 1:
        escribir("")
        escribir(
            "🔴 **Las respuestas NO se midieron todas con el mismo servidor.** "
            "Una diferencia entre candidatos puede venir del tiempo de "
            "ejecución y no del modelo, así que esta tabla no compara nada "
            "hasta que todas se remidan con una sola versión."
        )
    escribir("")
    escribir("## Resumen por modelo")
    escribir("")
    cola = " Fuera de presupuesto |" if presupuesto else ""
    guion = " ---: |" if presupuesto else ""
    escribir(
        "| Modelo | n | Titul. inventadas | Precisión | Cobertura "
        "| Acierto escalar | Mediana (s) | p90 (s) | Máx (s) |" + cola
    )
    escribir("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |" + guion)
    for modelo, cifras in resumen.items():
        fila = (
            f"| `{modelo}` | {cifras['respuestas']} "
            f"| {cifras['titulaciones_inventadas']} "
            f"| {cifras['precision']:.3f} | {cifras['cobertura']:.3f} "
            f"| {cifras['acierto_escalar']:.3f} | {cifras['mediana_s']:.1f} "
            f"| {cifras['p90_s']:.1f} | {cifras['max_s']:.1f} |"
        )
        if presupuesto:
            fila += f" {cifras['fuera_de_presupuesto']}/{cifras['respuestas']} |"
        escribir(fila)
    escribir("")
    escribir(
        "Precisión y cobertura se promedian sobre las preguntas de listado; el "
        "acierto escalar, sobre las de créditos y curso."
    )
    escribir("")
    escribir("## Titulaciones inventadas")
    escribir("")
    escribir(
        "Un nombre con forma de titulación que no está en el catálogo del "
        "índice. Es el fallo más grave que puede cometer el sistema."
    )
    escribir("")
    for modelo, cifras in resumen.items():
        if cifras["nombres_inventados"]:
            escribir(
                f"- `{modelo}` — en {cifras['titulaciones_inventadas']} respuestas:"
            )
            for nombre in cifras["nombres_inventados"]:
                escribir(f"  - «{nombre}»")
        else:
            escribir(f"- `{modelo}` — ninguna.")
    escribir("")
    escribir("## Desglose por familia de pregunta")
    escribir("")
    for modelo, fam in familias.items():
        escribir(f"### `{modelo}`")
        escribir("")
        escribir("| Familia | n | Precisión | Cobertura | Acierto | Mediana (s) |")
        escribir("| --- | ---: | ---: | ---: | ---: | ---: |")
        for nombre, cifras in sorted(fam.items()):
            pre = f"{cifras['precision']:.3f}" if cifras["es_listado"] else "—"
            cob = f"{cifras['cobertura']:.3f}" if cifras["es_listado"] else "—"
            acierto = "—" if cifras["es_listado"] else f"{cifras['acierto']:.3f}"
            escribir(
                f"| {nombre} | {cifras['n']} | {pre} | {cob} | {acierto} "
                f"| {cifras['mediana_s']:.1f} |"
            )
        escribir("")
    escribir("## Recuperación")
    escribir("")
    escribir(
        "Cuántas preguntas se quedaron sin ningún fragmento. Es fallo del "
        "recuperador, no del modelo, y por eso se cuenta aparte: sin contexto "
        "ningún generador puede acertar."
    )
    escribir("")
    for modelo, cifras in resumen.items():
        escribir(f"- `{modelo}`: {cifras['sin_contexto']} de {cifras['respuestas']}")
    escribir("")
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"\nInforme escrito en {destino}")


def main(argumentos: list[str] | None = None) -> None:
    """Punto de entrada.

    Args:
        argumentos: Argumentos de línea de órdenes, o ``None`` para los reales.
    """
    analizador = argparse.ArgumentParser(description="Cribado de generadores.")
    analizador.add_argument("--modelos", nargs="+", default=list(MODELOS))
    analizador.add_argument(
        "--banco", default=str(RAIZ / "eval" / "preguntas_generacion_muestra.json")
    )
    analizador.add_argument("--indice", default=str(RAIZ / "data" / "indice_lance"))
    analizador.add_argument("--datos", default=str(RAIZ / "data" / "grados.json"))
    analizador.add_argument(
        "--registro", default=str(NOTAS / "cribado_generacion.jsonl")
    )
    analizador.add_argument("--salida", default=str(NOTAS / "cribado_generacion.md"))
    analizador.add_argument("--limite", type=int, default=0)
    analizador.add_argument(
        "--presupuesto",
        type=float,
        default=PRESUPUESTO,
        help="tope de segundos por respuesta; 0 para no descartar por tiempo",
    )
    analizador.add_argument("--solo-informe", action="store_true")
    analizador.add_argument(
        "--recalcular",
        action="store_true",
        help="repuntúa las respuestas guardadas sin llamar a ningún modelo",
    )
    opciones = analizador.parse_args(argumentos)

    banco = json.loads(Path(opciones.banco).read_text(encoding="utf-8"))
    preguntas = banco["preguntas"]
    if opciones.limite:
        preguntas = preguntas[: opciones.limite]
    registro = Path(opciones.registro)
    registro.parent.mkdir(parents=True, exist_ok=True)

    datos = json.loads(Path(opciones.datos).read_text(encoding="utf-8"))
    asignaturas = asignaturas_del_corpus(datos)
    menciones = menciones_del_corpus(datos)
    catalogo = catalogo_del_indice(Path(opciones.indice))

    if not (opciones.solo_informe or opciones.recalcular):
        print("Cargando el modelo de incrustaciones...")
        ejecutar(
            opciones.modelos,
            preguntas,
            abrir_indice(Path(opciones.indice), MODELO),
            incrustador_de_consultas(MODELO),
            distancia_del_indice(Path(opciones.indice)),
            catalogo,
            asignaturas,
            menciones,
            registro,
        )

    filas = [
        json.loads(linea)
        for linea in registro.read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]
    if opciones.recalcular:
        filas = recalcular(
            filas,
            {p["id"]: p for p in banco["preguntas"]},
            catalogo,
            asignaturas,
            menciones,
        )
        registro.write_text(
            "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in filas),
            encoding="utf-8",
        )
        print(f"Repuntuadas {len(filas)} respuestas sin llamar a ningún modelo.")
    informe(filas, banco, Path(opciones.salida), opciones.presupuesto)


if __name__ == "__main__":
    main()

"""Pruebas del guion de la comparativa de bases vectoriales (IT-31)."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parent.parent
_RUTA = RAIZ / "scripts" / "experimentos" / "experimento_vectordb.py"
_spec = importlib.util.spec_from_file_location("experimento_vectordb", _RUTA)
assert _spec is not None and _spec.loader is not None
experimento = importlib.util.module_from_spec(_spec)
sys.modules["experimento_vectordb"] = experimento
_spec.loader.exec_module(experimento)


def _chunk(
    grados: list[str],
    tipo: str = "OB",
    texto: str = "texto",
    codigos: list[str] | None = None,
) -> dict[str, Any]:
    """Fragmento mínimo con la forma real de ``chunks.json``."""
    return {
        "tipo": "chunk",
        "origen": "guia",
        "grados": grados,
        "codigos": codigos or ["0000"],
        "nombre": "Asignatura",
        "texto": texto,
        "tipo_asignatura": tipo,
        "chunk_index": 0,
        "total_chunks": 1,
    }


def test_incrustador_fijo_reparte_los_vectores_en_orden() -> None:
    """Cada lote recibe su porción, consecutiva y en el orden de entrada.

    Es el invariante que garantiza que las tres candidatas se indexan con
    EXACTAMENTE los mismos vectores. Si se rompiera, cada base guardaría el
    vector de otro fragmento y la comparación dejaría de medir la base.
    """
    vectores = np.arange(12, dtype=np.float32).reshape(4, 3)
    incrustar = experimento.incrustador_fijo(vectores)

    assert incrustar(["a", "b"]) == [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]]
    assert incrustar(["c"]) == [[6.0, 7.0, 8.0]]
    assert incrustar(["d"]) == [[9.0, 10.0, 11.0]]


def test_incrustador_fijo_falla_al_agotarse() -> None:
    """Pedir más vectores de los que hay revienta, no devuelve una lista vacía.

    Un corte de NumPy fuera de rango devuelve un array vacío **sin avisar**.
    Si eso pasara, la base se indexaría con menos vectores que el corpus y el
    experimento seguiría publicando cifras como si nada.
    """
    incrustar = experimento.incrustador_fijo(np.zeros((2, 3), dtype=np.float32))
    incrustar(["a", "b"])

    with pytest.raises(ValueError, match="se ha agotado"):
        incrustar(["c"])


def test_incrustador_fijo_ignora_el_texto() -> None:
    """El texto no influye: lo que manda es la posición.

    El incrustador real sí mira el texto; este lo sustituye a propósito. La
    prueba fija esa diferencia para que nadie lo «arregle» creyendo que es un
    descuido.
    """
    vectores = np.arange(6, dtype=np.float32).reshape(2, 3)
    incrustar = experimento.incrustador_fijo(vectores)

    assert incrustar(["cualquier cosa"]) == [[0.0, 1.0, 2.0]]
    assert incrustar([""]) == [[3.0, 4.0, 5.0]]


def test_esperados_del_filtro_compara_elementos_no_subcadenas() -> None:
    """El caso real que motivó el esquema de listas nativas.

    «Grado en Ingeniería Eléctrica» es subcadena de «Doble Grado en Ingeniería
    Eléctrica y Mecánica». La verdad de referencia debe distinguirlos, o el
    umbral U2 se comprobaría contra una referencia tan defectuosa como la
    implementación que pretende cazar.
    """
    chunks = [
        _chunk(["Grado en Ingeniería Eléctrica"]),
        _chunk(["Doble Grado en Ingeniería Eléctrica y Mecánica"]),
        _chunk(["Grado en Ingeniería Eléctrica", "Grado en Ingeniería Mecánica"]),
    ]

    esperados = experimento.esperados_del_filtro(
        chunks, "Grado en Ingeniería Eléctrica", None
    )

    assert esperados == {0, 2}


def test_esperados_del_filtro_combina_grado_y_tipo() -> None:
    """Con tipo, se exigen las dos condiciones a la vez."""
    chunks = [
        _chunk(["Informática"], tipo="OB"),
        _chunk(["Informática"], tipo="OP"),
        _chunk(["Mecánica"], tipo="OB"),
    ]

    assert experimento.esperados_del_filtro(chunks, "Informática", "OB") == {0}
    assert experimento.esperados_del_filtro(chunks, "Informática", None) == {0, 1}


def test_esperados_del_filtro_no_confunde_tipo_vacio_con_ausente() -> None:
    """Los 55 fragmentos que no son asignatura llevan el tipo en cadena vacía.

    Filtrar por un tipo concreto no debe devolverlos, y filtrar por cadena
    vacía debe devolver solo esos: es lo que permite excluirlos de los filtros
    negativos del recuperador de la Fase 2.
    """
    chunks = [_chunk(["Informática"], tipo="OB"), _chunk(["Informática"], tipo="")]

    assert experimento.esperados_del_filtro(chunks, "Informática", "OB") == {0}
    assert experimento.esperados_del_filtro(chunks, "Informática", "") == {1}


def test_poder_discriminante_detecta_un_caso_que_no_separa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un nombre que no es subcadena de ningún otro no discrimina.

    Con ese caso, el criterio «0 falsos positivos» se cumple igual con el
    esquema bueno y con el defectuoso, así que no demuestra nada. El guion
    tiene que decirlo en vez de presentarlo como evidencia.
    """
    chunks = [_chunk(["Grado en Ingeniería Informática"], tipo="OB")]
    monkeypatch.setattr(
        experimento,
        "CASOS_FILTRO",
        (("informática", "Grado en Ingeniería Informática", "OB"),),
    )

    resultado = experimento.poder_discriminante_u2(chunks)

    exactos, por_subcadena = resultado["informática"]
    assert exactos == por_subcadena == 1


def test_poder_discriminante_detecta_el_caso_trampa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El caso de subcadena sí separa, y por eso hace falta.

    Un filtro por subcadena arrastra el fragmento del doble grado; uno por
    pertenencia a la lista, no.
    """
    chunks = [
        _chunk(["Grado en Ingeniería Eléctrica"], tipo=""),
        _chunk(["Doble Grado en Ingeniería Eléctrica y Mecánica"], tipo=""),
    ]
    monkeypatch.setattr(
        experimento,
        "CASOS_FILTRO",
        (("eléctrica", "Grado en Ingeniería Eléctrica", None),),
    )

    exactos, por_subcadena = experimento.poder_discriminante_u2(chunks)["eléctrica"]

    assert exactos == 1
    assert por_subcadena == 2


def test_fidelidad_media_perfecta_ignora_el_orden() -> None:
    """U1 compara conjuntos: reordenar dentro del top-K no cuesta fidelidad.

    Lo que decide U1 es si el índice deja fuera vecinos que la fuerza bruta sí
    encuentra, no en qué posición los coloca.
    """
    assert experimento.fidelidad_media([[1, 2, 3]], [[3, 1, 2]]) == 1.0


def test_fidelidad_media_cuenta_lo_que_falta() -> None:
    """Perder un vecino de cuatro es 0,75; promediado entre preguntas."""
    assert experimento.fidelidad_media([[1, 2, 3, 4]], [[1, 2, 3, 9]]) == 0.75
    assert experimento.fidelidad_media(
        [[1, 2], [1, 2]], [[1, 2], [1, 9]]
    ) == pytest.approx(0.75)


def test_fidelidad_media_con_referencia_vacia() -> None:
    """Sin vecinos exactos que recuperar, no hay nada que perder."""
    assert experimento.fidelidad_media([[]], [[1, 2]]) == 1.0


def test_fidelidad_media_exige_la_misma_cantidad_de_consultas() -> None:
    """Si una candidata contesta a menos preguntas, hay que enterarse.

    Un ``zip`` normal truncaría en silencio y la fidelidad saldría calculada
    solo sobre las preguntas contestadas, que es una cifra engañosa.
    """
    with pytest.raises(ValueError):
        experimento.fidelidad_media([[1], [2]], [[1]])


def test_cronometrar_descarta_el_calentamiento() -> None:
    """Las primeras consultas se lanzan pero no entran en la muestra."""
    llamadas: list[int] = []

    def consultar(i: int) -> None:
        llamadas.append(i)

    experimento.cronometrar(consultar, 10)

    esperadas = min(experimento.CALENTAMIENTO, 10) + experimento.REPETICIONES * 10
    assert len(llamadas) == esperadas


def test_cronometrar_devuelve_mediana_y_p90_estandar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El p90 es el de NumPy interpolado, no un índice calculado a mano.

    El reloj se sustituye por uno determinista para poder exigir el valor
    exacto: la consulta ``i`` tarda ``i + 1`` milisegundos. Con 10 consultas y
    una repetición, la muestra es 1..10 ms, cuya mediana es 5,5 y cuyo
    percentil 90 interpolado es 9,1. Un índice a mano ---``tiempos[int(10 *
    0.9)]``--- daría 10,0, así que este test distingue las dos definiciones.
    """
    monkeypatch.setattr(experimento, "REPETICIONES", 1)
    monkeypatch.setattr(experimento, "CALENTAMIENTO", 0)

    reloj = iter(
        [
            0.0,
            0.001,
            0.0,
            0.002,
            0.0,
            0.003,
            0.0,
            0.004,
            0.0,
            0.005,
            0.0,
            0.006,
            0.0,
            0.007,
            0.0,
            0.008,
            0.0,
            0.009,
            0.0,
            0.010,
        ]
    )
    monkeypatch.setattr(experimento.time, "perf_counter", lambda: next(reloj))

    mediana, p90 = experimento.cronometrar(lambda i: None, 10)

    esperados = [float(ms) for ms in range(1, 11)]
    assert mediana == pytest.approx(float(np.median(esperados)))
    assert p90 == pytest.approx(float(np.percentile(esperados, 90)))
    assert mediana == pytest.approx(5.5)
    assert p90 == pytest.approx(9.1)


def test_elegir_caso_prefiltrado_elige_el_grado_fuera_del_top_k() -> None:
    """El caso elegido no puede tener candidatos en el top-K sin filtrar.

    Si los tuviera, un posfiltrado también devolvería resultados y la prueba
    no distinguiría nada. Aquí los fragmentos del grado buscado se colocan en
    la dirección opuesta a la consulta.
    """
    cerca = np.array([[1.0, 0.0], [0.9, 0.1]], dtype=np.float32)
    lejos = np.array([[-1.0, 0.0], [-0.9, -0.1]], dtype=np.float32)
    vectores = np.vstack([cerca, lejos])
    consultas = np.array([[1.0, 0.0]], dtype=np.float32)
    chunks = [
        _chunk(["Cercano"]),
        _chunk(["Cercano"]),
        _chunk(["Lejano"]),
        _chunk(["Lejano"]),
    ]

    caso = experimento.elegir_caso_prefiltrado(vectores, consultas, chunks, k=2)

    assert caso is not None
    indice, grado, cuantos = caso
    assert indice == 0
    assert grado == "Lejano"
    assert cuantos == 2


def test_elegir_caso_prefiltrado_sin_caso_posible() -> None:
    """Si todos los candidatos caben en el top-K, no hay caso que valga."""
    vectores = np.array([[1.0, 0.0], [0.9, 0.1]], dtype=np.float32)
    consultas = np.array([[1.0, 0.0]], dtype=np.float32)
    chunks = [_chunk(["Único"]), _chunk(["Único"])]

    assert experimento.elegir_caso_prefiltrado(vectores, consultas, chunks, k=2) is None


def test_comprobar_normas_detecta_vectores_normalizados() -> None:
    """Con normas constantes a 1, euclídea y coseno ordenan igual."""
    vectores = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

    minimo, maximo, constantes = experimento.comprobar_normas(vectores)

    assert minimo == pytest.approx(1.0)
    assert maximo == pytest.approx(1.0)
    assert constantes is True


def test_comprobar_normas_detecta_vectores_sin_normalizar() -> None:
    """Si las normas varían, la equivalencia entre métricas no se sostiene."""
    vectores = np.array([[3.0, 4.0], [1.0, 0.0]], dtype=np.float32)

    minimo, maximo, normalizados = experimento.comprobar_normas(vectores)

    assert minimo == pytest.approx(1.0)
    assert maximo == pytest.approx(5.0)
    assert normalizados is False


def test_comprobar_normas_no_llama_normalizado_a_un_vector_cero() -> None:
    """Norma constante no basta: tiene que ser constante Y valer 1.

    Una matriz de ceros tiene desviación típica cero, así que un criterio que
    solo mirase la constancia diría que está normalizada. El informe usa ese
    dato para afirmar que el modelo entrega vectores de norma 1, y eso sería
    una cifra inventada.
    """
    _, _, normalizados = experimento.comprobar_normas(
        np.zeros((3, 4), dtype=np.float32)
    )

    assert normalizados is False


def test_comprobar_normas_no_llama_normalizado_a_norma_constante_distinta_de_uno() -> (
    None
):
    """Todas de norma 5 es constante, pero no es normalizado."""
    vectores = np.array([[3.0, 4.0], [0.0, 5.0], [5.0, 0.0]], dtype=np.float32)

    minimo, maximo, normalizados = experimento.comprobar_normas(vectores)

    assert minimo == pytest.approx(5.0)
    assert maximo == pytest.approx(5.0)
    assert normalizados is False


# --- id_a_indice -----------------------------------------------------------


def test_id_a_indice_deshace_el_identificador() -> None:
    """Los ids codifican la posición del fragmento en la lista de entrada."""
    assert experimento.id_a_indice("chunk-0000") == 0
    assert experimento.id_a_indice("chunk-1333") == 1333


# --- memoria_contenedor_mb: el parseo de docker stats ----------------------


@pytest.mark.parametrize(
    ("salida", "esperado"),
    [
        ("1.5GiB / 15.5GiB", 1536.0),
        ("150.3MiB / 15.5GiB", 150.3),
        ("512KiB / 15.5GiB", 0.5),
        # Docker informa en bytes sueltos cuando el contenedor apenas consume,
        # y en unidades decimales según cómo esté configurado.
        ("0B / 15.5GiB", 0.0),
        ("1048576B / 15.5GiB", 1.0),
        ("1MB / 15.5GiB", 1000.0 * 1000 / 1024**2),
    ],
)
def test_memoria_contenedor_convierte_las_unidades(
    monkeypatch: pytest.MonkeyPatch, salida: str, esperado: float
) -> None:
    """``docker stats`` informa en unidades distintas según el tamaño.

    Confundirlas daría a Qdrant una memoria mil veces mayor o menor sin que
    nada fallara, y U5 es el umbral que más aprieta.
    """

    class _Resultado:
        stdout = salida

    def _run(*args: Any, **kwargs: Any) -> _Resultado:
        return _Resultado()

    monkeypatch.setattr(experimento.subprocess, "run", _run)

    assert experimento.memoria_contenedor_mb("cualquiera") == pytest.approx(esperado)


def test_sql_literal_escapa_las_comillas() -> None:
    """LanceDB no admite consultas parametrizadas: hay que escapar a mano.

    Ninguna de las once titulaciones del corpus lleva comilla, pero eso es una
    propiedad de los datos de la EPSJ, no una garantía del código.
    """
    assert experimento._sql_literal("Grado en Ingeniería Informática") == (
        "Grado en Ingeniería Informática"
    )
    assert experimento._sql_literal("Nombre con ' comilla") == "Nombre con '' comilla"
    assert experimento._sql_literal("con '' doble") == "con '''' doble"


def test_memoria_contenedor_falla_ante_una_unidad_desconocida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mejor un error ruidoso que una cifra inventada."""

    class _Resultado:
        stdout = "150.3TB / 15.5GiB"

    def _run(*args: Any, **kwargs: Any) -> _Resultado:
        return _Resultado()

    monkeypatch.setattr(experimento.subprocess, "run", _run)

    with pytest.raises(ValueError, match="Unidad no reconocida"):
        experimento.memoria_contenedor_mb("cualquiera")


# --- escribir_resultados: no pisar lo que escriba el autor -----------------


def test_escribir_resultados_solo_sustituye_entre_las_marcas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reejecutar el experimento no puede borrar la prosa del ADR.

    El guion escribe los resultados brutos; el resto del ADR ---contexto,
    decisión, consecuencias--- lo escribe el autor, y tiene que sobrevivir a
    cualquier reejecución.
    """
    adr = tmp_path / "adr-0004.md"
    adr.write_text(
        f"# ADR\n\nProsa del autor.\n\n{experimento.MARCA_INICIO}\n"
        f"viejo\n{experimento.MARCA_FIN}\n\n## Decisión\n\nMás prosa.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(experimento, "RUTA_ADR", adr)

    experimento.escribir_resultados(
        f"{experimento.MARCA_INICIO}\nnuevo\n{experimento.MARCA_FIN}"
    )

    resultado = adr.read_text(encoding="utf-8")
    assert "Prosa del autor." in resultado
    assert "## Decisión" in resultado
    assert "Más prosa." in resultado
    assert "nuevo" in resultado
    assert "viejo" not in resultado


def test_escribir_resultados_falla_si_faltan_las_marcas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin las marcas no se escribe: se avisa y no se toca el fichero.

    Antes el bloque se añadía al final, que es la manera de dejar el ADR
    desordenado sin que nadie se entere. Un ADR al que le faltan las marcas es
    un ADR que alguien ha editado mal, y eso hay que verlo, no absorberlo.
    """
    adr = tmp_path / "adr-0004.md"
    original = "# ADR\n\nProsa del autor, sin marcas.\n"
    adr.write_text(original, encoding="utf-8")
    monkeypatch.setattr(experimento, "RUTA_ADR", adr)

    with pytest.raises(SystemExit, match="marcas"):
        experimento.escribir_resultados(
            f"{experimento.MARCA_INICIO}\nresultados\n{experimento.MARCA_FIN}"
        )

    assert adr.read_text(encoding="utf-8") == original


def test_escribir_resultados_falla_si_el_adr_no_existe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El ADR lo abre su tarjeta, no el guion que le mete las cifras.

    Crear el fichero desde aquí obligaba a mantener una plantilla de ADR
    dentro del experimento, que además envejecía por su cuenta: llevaba un
    campo de fecha y un apartado de amenazas que la plantilla vigente ya no
    tiene.
    """
    adr = tmp_path / "adr-0004.md"
    monkeypatch.setattr(experimento, "RUTA_ADR", adr)

    with pytest.raises(SystemExit, match="No existe"):
        experimento.escribir_resultados(
            f"{experimento.MARCA_INICIO}\nresultados\n{experimento.MARCA_FIN}"
        )

    assert not adr.exists()


# --- Que estas pruebas se puedan recoger en CI (IT-31) ---------------------


def test_el_experimento_no_exige_las_dependencias_opcionales_al_importarse() -> None:
    """Importar el guion no puede requerir el grupo `[comparativa-vectordb]`.

    Regresión de un fallo real de la integración continua: `psutil` estaba
    importado en la cabecera del módulo, y como CI instala solo `[dev]`, la
    recogida de este fichero moría con `ModuleNotFoundError` y las 32 pruebas
    no llegaban a ejecutarse. Ninguna de ellas mide memoria ni habla con una
    base de datos: comprueban la aritmética que hace válida la comparación, y
    eso no necesita nada instalado.

    Las dependencias pesadas se importan dentro de la función que las usa.
    Se analiza el árbol sintáctico porque lo que importa es dónde está el
    `import`, no si el módulo está instalado en la máquina que ejecuta esto.
    """
    ruta = RAIZ / "scripts" / "experimentos" / "experimento_vectordb.py"
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))

    de_cabecera: set[str] = set()
    for nodo in arbol.body:
        if isinstance(nodo, ast.Import):
            de_cabecera |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            de_cabecera.add(nodo.module.split(".")[0])

    opcionales = {
        "psutil",
        "chromadb",
        "lancedb",
        "qdrant_client",
        "sentence_transformers",
    }
    intrusos = sorted(de_cabecera & opcionales)

    assert not intrusos, (
        f"{intrusos} se importan en la cabecera de experimento_vectordb.py. "
        f"Están en grupos opcionales que CI no instala, así que este fichero "
        f"de pruebas dejaría de poder recogerse. Muévelos dentro de la función "
        f"que los usa."
    )


# ---------------------------------------------------------------------------
# Medida, veredictos, informe y recorrido entero (IT-113)
#
# `chromadb` y `qdrant_client` NO están en las dependencias de desarrollo: en
# CI no existen. Se inyectan de mentira, igual que hace el propio guion al
# importarlas de forma perezosa. LanceDB sí está, así que esa se ejecuta de
# verdad contra un índice en disco.
# ---------------------------------------------------------------------------

import types  # noqa: E402
from pathlib import Path  # noqa: E402


def _medida(**cambios):
    """Una medida completa, con los valores de una candidata que cumple todo."""
    base = dict(
        nombre="LanceDB",
        version="0.37.1",
        modo="recorrido completo",
        segundos_construir=1.5,
        latencia_mediana_ms=7.35,
        latencia_p90_ms=9.0,
        fidelidad=1.0,
        memoria_mb=22.71,
        filtros={"por grado": (10, 10, 0)},
        prefiltrado=(10, 10, True),
        esfuerzo={"servicio aparte": "no"},
        notas=[],
    )
    base.update(cambios)
    return experimento.Medida(**base)


# --- Los veredictos ---------------------------------------------------------


def test_u1_se_fija_en_el_uno_exacto() -> None:
    """El umbral se fijó en 1,000 exacto ANTES de medir; por eso descarta.

    Lo eliminatorio no es el tamaño de la pérdida, es que el umbral estaba
    escrito de antemano.
    """
    assert "CUMPLE" in experimento._veredicto_u1(_medida(fidelidad=1.0))
    assert "NO CUMPLE" in experimento._veredicto_u1(_medida(fidelidad=0.998))


def test_u2_no_cumple_si_hay_un_falso_positivo() -> None:
    assert "NO CUMPLE" in experimento._veredicto_u2(
        _medida(filtros={"por grado": (10, 10, 1)})
    )


def test_u2_no_cumple_si_falta_algo_por_recuperar() -> None:
    assert "NO CUMPLE" in experimento._veredicto_u2(
        _medida(filtros={"por grado": (9, 10, 0)})
    )


def test_u2_cumple_cuando_recupera_lo_que_debe_y_nada_mas() -> None:
    veredicto = experimento._veredicto_u2(_medida())

    assert "CUMPLE" in veredicto and "NO CUMPLE" not in veredicto
    assert "10/10" in veredicto


def test_u3_lleva_el_p90_al_lado_para_no_leer_sola_la_mediana() -> None:
    veredicto = experimento._veredicto_u3(_medida())

    assert "CUMPLE" in veredicto
    assert "p90 9.00 ms" in veredicto


def test_u3_no_cumple_por_encima_del_medio_segundo() -> None:
    assert "NO CUMPLE" in experimento._veredicto_u3(_medida(latencia_mediana_ms=501.0))


@pytest.mark.parametrize(
    "memoria, esperado",
    [(400.0, "CUMPLE"), (800.0, "ZONA INTERMEDIA"), (2000.0, "DESCARTA")],
)
def test_u5_tiene_tres_tramos_y_no_dos(memoria, esperado) -> None:
    """La memoria no es binaria: hay una zona intermedia declarada."""
    assert esperado in experimento._veredicto_u5(_medida(memoria_mb=memoria))


def test_el_prefiltrado_no_es_un_umbral_sino_una_garantia() -> None:
    assert "PREFILTRA" in experimento._veredicto_prefiltrado((10, 10, True))


def test_devolver_menos_de_los_pedidos_es_posfiltrar() -> None:
    """Posfiltrar es un fallo silencioso: diría «no tengo» de algo indexado."""
    veredicto = experimento._veredicto_prefiltrado((3, 10, True))

    assert "POSFILTRA O PIERDE" in veredicto


def test_devolver_algo_que_no_cumple_el_filtro_se_dice() -> None:
    veredicto = experimento._veredicto_prefiltrado((10, 10, False))

    assert "NO cumple el filtro" in veredicto


def test_evaluar_umbrales_deja_fuera_la_linea_base() -> None:
    """NumPy no es candidata: es la referencia contra la que se mide U1."""
    # Se salta por la clave del diccionario, que es como la mete `main`.
    medidas = {"NumPy": _medida(), "lance": _medida()}

    veredictos = experimento.evaluar_umbrales(medidas)

    assert "lance" in veredictos
    assert "NumPy" not in veredictos


def test_una_candidata_sin_caso_de_prefiltrado_no_lo_declara() -> None:
    veredictos = experimento.evaluar_umbrales({"lance": _medida(prefiltrado=None)})

    assert not [v for v in veredictos["lance"] if "Prefiltrado" in v]


# --- Las tablas del informe -------------------------------------------------


def test_la_tabla_resumen_lleva_una_fila_por_candidata() -> None:
    tabla = experimento._tabla_resumen(
        {"a": _medida(nombre="A"), "b": _medida(nombre="B")}
    )

    assert "A" in tabla and "B" in tabla


def test_la_tabla_de_filtrado_desglosa_los_casos() -> None:
    tabla = experimento._tabla_filtrado({"a": _medida()})

    assert "por grado" in tabla


def test_la_tabla_discriminante_dice_cuanto_separa_cada_caso() -> None:
    tabla = experimento._tabla_discriminante({"por grado": (10, 100)})

    assert "por grado" in tabla


def test_la_tabla_de_esfuerzo_recoge_los_hechos_verificables() -> None:
    """U7 se mide en hechos, no en opiniones."""
    tabla = experimento._tabla_esfuerzo({"a": _medida()})

    assert "servicio aparte" in tabla


def test_la_tabla_de_prefiltrado_dice_quien_posfiltra() -> None:
    tabla = experimento._tabla_prefiltrado(
        {"a": _medida(), "b": _medida(prefiltrado=(3, 10, True))},
        (0, "Grado en Ingeniería Informática", 40),
        ["¿qué asignaturas tiene?"],
    )

    assert "Informática" in tabla


# --- Las secciones ----------------------------------------------------------


def test_la_cabecera_declara_contra_que_corpus_se_midio() -> None:
    lineas = experimento._seccion_cabecera({"a": _medida()}, [{"texto": "uno"}], ["¿?"])

    texto = "\n".join(lineas)
    assert "1 fragmentos" in texto


def test_las_limitaciones_se_declaran_en_el_informe() -> None:
    lineas = experimento._seccion_limitaciones([{"texto": "uno"}], (1.0, 0.0, True))

    assert lineas


def test_el_bloque_va_entre_las_marcas_de_su_adr() -> None:
    """El guion escribe entre marcas para no pisar lo que redacte el autor."""
    bloque = experimento.generar_bloque_resultados(
        {"a": _medida()},
        {"a": ["U1: CUMPLE"]},
        [{"texto": "uno"}],
        ["¿?"],
        (1.0, 0.0, True),
        {"por grado": (10, 100)},
        (0, "Grado en Ingeniería Informática", 40),
    )

    assert bloque.startswith(experimento.MARCA_INICIO)
    assert bloque.rstrip().endswith(experimento.MARCA_FIN)


# --- La línea base y la medida de una candidata -----------------------------


def test_numpy_es_exacta_por_construccion() -> None:
    """Es la referencia de U1: su fidelidad es 1 por definición, no por medida."""
    vectores = np.eye(5, dtype=np.float32)
    consultas = np.eye(5, dtype=np.float32)[:2]

    medida, exactos = experimento.medir_numpy(vectores, consultas)

    assert medida.fidelidad == 1.0
    assert len(exactos) == 2
    assert exactos[0][0] == 0


def test_la_memoria_de_numpy_es_la_matriz_y_no_el_rss() -> None:
    """No hay almacén: es la línea base, no una base con su sobrecarga."""
    vectores = np.eye(10, dtype=np.float32)

    medida, _ = experimento.medir_numpy(vectores, vectores[:1])

    assert medida.memoria_mb == pytest.approx(vectores.nbytes / (1024**2))


class _ConsultadorFalso:
    """Adaptador que responde lo que se le diga, sin ninguna base detrás."""

    def __init__(self, vecinos, filtro=None, filtrados=None):
        self.vecinos = lambda q, k: list(vecinos)[:k]
        self.filtro = filtro or (lambda g, t: set())
        self.vecinos_filtrados = filtrados or (lambda q, k, g: list(vecinos)[:k])


def test_medir_candidata_compara_contra_los_vecinos_exactos() -> None:
    consultas = np.eye(3, dtype=np.float32)[:1]
    chunks = [{"grados": ["G"], "tipo_asignatura": "OB"} for _ in range(3)]

    medida = experimento.medir_candidata(
        "X",
        "1.0",
        "exacto",
        1.0,
        10.0,
        _ConsultadorFalso([0, 1, 2]),
        consultas,
        [[0, 1, 2]],
        chunks,
        notas=[],
    )

    assert medida.fidelidad == 1.0
    assert medida.nombre == "X"


def test_medir_candidata_detecta_que_pierde_un_vecino() -> None:
    consultas = np.eye(3, dtype=np.float32)[:1]
    chunks = [{"grados": ["G"]} for _ in range(3)]

    medida = experimento.medir_candidata(
        "X",
        "1.0",
        "aproximado",
        1.0,
        10.0,
        _ConsultadorFalso([0, 1, 9]),
        consultas,
        [[0, 1, 2]],
        chunks,
        notas=[],
    )

    assert medida.fidelidad < 1.0


def test_comprobar_prefiltrado_denuncia_lo_que_no_cumple_el_filtro() -> None:
    chunks = [{"grados": ["Otro"]}, {"grados": ["G"]}]
    consultas = np.eye(2, dtype=np.float32)

    devueltos, pedidos, correctos = experimento.comprobar_prefiltrado(
        _ConsultadorFalso([0, 1]), consultas, chunks, (0, "G", 1), k=2
    )

    assert (devueltos, pedidos) == (2, 2)
    assert correctos is False


# --- Las utilidades de medida -----------------------------------------------


def test_construir_con_metricas_devuelve_lo_construido_y_su_coste() -> None:
    construido, segundos, memoria = experimento.construir_con_metricas(
        lambda: "almacen"
    )

    assert construido == "almacen"
    assert segundos >= 0.0
    assert memoria >= 0.0


def test_la_memoria_nunca_sale_negativa(monkeypatch) -> None:
    """Una bajada solo diría que el recolector liberó algo de otro sitio."""
    valores = iter([100.0, 50.0])
    monkeypatch.setattr(experimento, "rss_actual_mb", lambda: next(valores))

    _c, _s, memoria = experimento.construir_con_metricas(lambda: None)

    assert memoria == 0.0


def test_el_rss_se_lee_en_mebibytes() -> None:
    assert experimento.rss_actual_mb() > 0.0


def test_la_carpeta_temporal_se_borra_al_salir() -> None:
    with experimento.carpeta_temporal() as tmp:
        ruta = Path(tmp)
        assert ruta.is_dir()

    assert not ruta.exists()


# --- Las entradas del guion -------------------------------------------------


def test_el_corpus_se_lee_de_su_fichero(tmp_path, monkeypatch) -> None:
    ruta = tmp_path / "chunks.json"
    ruta.write_text(json.dumps([_chunk(["G"])]), encoding="utf-8")
    monkeypatch.setattr(experimento, "RUTA_CHUNKS", ruta)

    assert len(experimento.cargar_corpus()) == 1


def test_las_preguntas_se_leen_de_su_fichero(tmp_path, monkeypatch) -> None:
    ruta = tmp_path / "evalset.json"
    ruta.write_text(
        json.dumps({"preguntas": [{"pregunta": "¿?"}, {"pregunta": "¿y?"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(experimento, "RUTA_EVAL", ruta)

    assert experimento.cargar_preguntas() == ["¿?", "¿y?"]


# --- LanceDB, que sí está en las dependencias de desarrollo ------------------


def _corpus_minimo(n=6):
    """Un corpus pequeño con dos titulaciones y dos tipos."""
    return [
        _chunk(
            [
                (
                    "Grado en Ingeniería Informática"
                    if i % 2
                    else "Grado en Ingeniería Mecánica"
                )
            ],
            tipo="OB" if i % 3 else "OP",
            texto=f"fragmento {i}",
            codigos=[f"{i:04d}"],
        )
        | {"curso": "Primer curso"}
        for i in range(n)
    ]


def _vectores(n, dimension=4):
    """Vectores distintos y normalizados, uno por fragmento."""
    matriz = np.eye(n, dimension, dtype=np.float32)
    matriz += 0.01
    return matriz / np.linalg.norm(matriz, axis=1, keepdims=True)


def test_lancedb_se_construye_y_se_mide_de_verdad(tmp_path) -> None:
    """Es la elegida por el ADR-0004: conviene que su medida esté cubierta."""
    chunks = _corpus_minimo(6)
    vectores = _vectores(6)
    consultas = vectores[:2]
    _base, exactos = experimento.medir_numpy(vectores, consultas)

    medida = experimento.medir_lancedb(
        chunks, vectores, consultas, exactos, tmp_path / "indice"
    )

    assert medida.nombre == "LanceDB"
    assert medida.fidelidad == 1.0
    assert "escaneo completo" in medida.modo
    assert medida.filtros


def test_lancedb_prefiltra_y_no_posfiltra(tmp_path) -> None:
    """Posfiltrar diría «no tengo información» de algo que sí está indexado."""
    chunks = _corpus_minimo(6)
    vectores = _vectores(6)
    consultas = vectores[:1]
    _base, exactos = experimento.medir_numpy(vectores, consultas)
    caso = (0, "Grado en Ingeniería Informática", 3)

    medida = experimento.medir_lancedb(
        chunks, vectores, consultas, exactos, tmp_path / "indice", caso
    )

    devueltos, _pedidos, correctos = medida.prefiltrado
    assert correctos
    assert devueltos > 0


def test_una_comilla_en_el_filtro_no_rompe_la_consulta() -> None:
    """El nombre de una titulación puede llevar comilla; SQL no perdona."""
    # Duplica las comillas segun el estandar SQL; las exteriores las pone
    # quien compone la expresion, no esta funcion.
    assert experimento._sql_literal("Grado en Ingeniería 'rara'") == (
        "Grado en Ingeniería ''rara''"
    )


# --- ChromaDB y Qdrant, que en CI no están instaladas -----------------------


class _ColeccionFalsa:
    """Colección de Chroma con lo justo para el adaptador del experimento."""

    def __init__(self):
        self.filas = []
        self.metadata = {"hnsw:space": "cosine"}

    def add(self, ids, embeddings, documents, metadatas):
        for i, identificador in enumerate(ids):
            self.filas.append((identificador, list(embeddings[i]), metadatas[i]))

    def query(self, query_embeddings, n_results, where=None):
        filas = self.filas
        if where:
            grado = where["grados"]["$contains"]
            filas = [f for f in filas if grado in f[2].get("grados", "")]
        return {"ids": [[f[0] for f in filas[:n_results]]]}

    def get(self, where):
        if "$and" in where:
            grado = where["$and"][0]["grados"]["$contains"]
            tipo = where["$and"][1]["tipo_asignatura"]["$eq"]
            filas = [
                f
                for f in self.filas
                if grado in f[2].get("grados", "")
                and f[2].get("tipo_asignatura") == tipo
            ]
        else:
            grado = where["grados"]["$contains"]
            filas = [f for f in self.filas if grado in f[2].get("grados", "")]
        return {"ids": [f[0] for f in filas]}


class _ClienteChromaFalso:
    def __init__(self, path=None):
        self.path = path

    def delete_collection(self, nombre):
        raise RuntimeError("no existía")

    def create_collection(self, nombre, metadata=None):
        return _ColeccionFalsa()


@pytest.fixture
def chroma_falso(monkeypatch):
    """Inyecta un `chromadb` de mentira: no está en las dependencias de dev."""
    modulo = types.ModuleType("chromadb")
    modulo.PersistentClient = _ClienteChromaFalso  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "chromadb", modulo)
    monkeypatch.setattr(experimento, "version_instalada", lambda n: "1.5.9")
    return modulo


def test_chroma_declara_la_distancia_al_crear_la_coleccion(chroma_falso, tmp_path):
    """La de ChromaDB por defecto es l2; hay que declarar coseno."""
    almacen = experimento.crear_almacen_chroma(tmp_path / "i", {"modelo": "e5"})

    assert isinstance(almacen.coleccion, _ColeccionFalsa)


def test_chroma_se_construye_y_se_mide(chroma_falso, tmp_path):
    chunks = _corpus_minimo(4)
    vectores = _vectores(4)
    consultas = vectores[:1]
    _base, exactos = experimento.medir_numpy(vectores, consultas)

    medida = experimento.medir_chroma(
        chunks, vectores, consultas, exactos, tmp_path / "indice"
    )

    assert medida.nombre == "ChromaDB"
    assert medida.version == "1.5.9"


def test_si_chroma_no_expone_su_configuracion_el_experimento_no_se_cae():
    """Se degrada a los metadatos, que sí son API pública, y se dice."""
    coleccion = _ColeccionFalsa()

    modo = experimento._modo_chroma(coleccion)

    assert "cosine" in modo
    assert "NO VERIFICABLE" in modo


def test_si_chroma_expone_su_configuracion_se_lee():
    coleccion = _ColeccionFalsa()
    coleccion.configuration_json = {"hnsw": {"space": "cosine", "ef_search": 100}}

    modo = experimento._modo_chroma(coleccion)

    assert "ef_search=100" in modo


class _PuntoFalso:
    def __init__(self, identificador):
        self.id = identificador
        self.payload = {"id": identificador}


class _ClienteQdrantFalso:
    """Cliente con lo justo para el adaptador del experimento."""

    def __init__(self, *a, **kw):
        self.puntos = []
        self.colecciones = {}

    def get_collections(self):
        return types.SimpleNamespace(collections=[])

    def collection_exists(self, nombre):
        return nombre in self.colecciones

    def delete_collection(self, nombre):
        self.colecciones.pop(nombre, None)

    def create_collection(self, collection_name, vectors_config=None, **kw):
        self.colecciones[collection_name] = True

    def create_payload_index(self, **kw):
        return None

    def upsert(self, collection_name, points):
        self.puntos.extend(points)

    def query_points(self, collection_name, query, limit, query_filter=None, **kw):
        puntos = [_PuntoFalso(f"chunk-{i:06d}") for i in range(len(self.puntos))]
        return types.SimpleNamespace(points=puntos[:limit])

    def scroll(self, collection_name, scroll_filter=None, limit=None, **kw):
        puntos = [_PuntoFalso(f"chunk-{i:06d}") for i in range(len(self.puntos))]
        return puntos[: limit or len(puntos)], None

    def get_collection(self, nombre):
        return types.SimpleNamespace(
            indexed_vectors_count=0, points_count=len(self.puntos)
        )


def _info_qdrant(indexados, puntos=1334):
    """La descripcion de coleccion que devuelve `get_collection`."""
    return types.SimpleNamespace(
        indexed_vectors_count=indexados,
        points_count=puntos,
        config=types.SimpleNamespace(
            optimizer_config=types.SimpleNamespace(indexing_threshold=20000),
            hnsw_config=types.SimpleNamespace(full_scan_threshold=10000),
        ),
    )


def test_el_modo_de_qdrant_se_lee_del_contador_de_indexados():
    """Qdrant sí expone cuántos vectores tiene indexados, y por eso se mide."""
    modo = experimento._modo_qdrant(_info_qdrant(indexados=0))

    assert "escaneo completo" in modo
    assert "indexed_vectors_count = 0 de 1334" in modo


def test_el_modo_de_qdrant_dice_cuando_si_hay_indice():
    modo = experimento._modo_qdrant(_info_qdrant(indexados=1334))

    assert "HNSW" in modo


# --- El recorrido entero ----------------------------------------------------


def test_main_mide_las_cuatro_y_escribe_el_bloque(tmp_path, monkeypatch, capsys):
    """Se sustituyen las tres bases: lo que se mide aquí es el recorrido."""
    chunks = _corpus_minimo(4)
    vectores = _vectores(4)
    monkeypatch.setattr(experimento, "cargar_corpus", lambda: chunks)
    monkeypatch.setattr(experimento, "cargar_preguntas", lambda: ["¿?", "¿y?"])

    from tfg_uja import incrustaciones

    monkeypatch.setattr(
        incrustaciones,
        "incrustador_de_documentos",
        lambda: (lambda t: vectores.tolist()),
    )
    monkeypatch.setattr(
        incrustaciones,
        "incrustador_de_consultas",
        lambda: (lambda t: vectores[:2].tolist()),
    )
    for nombre in ("medir_chroma", "medir_lancedb"):
        monkeypatch.setattr(experimento, nombre, lambda *a, **kw: _medida(nombre="X"))
    monkeypatch.setattr(experimento, "medir_qdrant", lambda *a, **kw: _medida())

    adr = tmp_path / "adr-0004.md"
    adr.write_text(
        f"# ADR\n\n{experimento.MARCA_INICIO}\nviejo\n{experimento.MARCA_FIN}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(experimento, "RUTA_ADR", adr)

    experimento.main()

    salida = capsys.readouterr().out
    assert "4 fragmentos · 2 preguntas" in salida
    assert "Evaluando contra los umbrales" in salida
    assert "viejo" not in adr.read_text(encoding="utf-8")


def test_main_dice_cuando_el_corpus_no_permite_la_comprobacion(
    tmp_path, monkeypatch, capsys
):
    """Sin un caso que distinga prefiltrado de posfiltrado, se omite y se dice."""
    chunks = _corpus_minimo(4)
    vectores = _vectores(4)
    monkeypatch.setattr(experimento, "cargar_corpus", lambda: chunks)
    monkeypatch.setattr(experimento, "cargar_preguntas", lambda: ["¿?"])
    monkeypatch.setattr(experimento, "elegir_caso_prefiltrado", lambda *a: None)

    from tfg_uja import incrustaciones

    monkeypatch.setattr(
        incrustaciones,
        "incrustador_de_documentos",
        lambda: (lambda t: vectores.tolist()),
    )
    monkeypatch.setattr(
        incrustaciones,
        "incrustador_de_consultas",
        lambda: (lambda t: vectores[:1].tolist()),
    )
    for nombre in ("medir_chroma", "medir_lancedb", "medir_qdrant"):
        monkeypatch.setattr(experimento, nombre, lambda *a, **kw: _medida())

    adr = tmp_path / "adr-0004.md"
    adr.write_text(
        f"# ADR\n\n{experimento.MARCA_INICIO}\nviejo\n{experimento.MARCA_FIN}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(experimento, "RUTA_ADR", adr)

    experimento.main()

    assert "la comprobación se omite" in capsys.readouterr().out

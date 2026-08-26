"""Pruebas del guion de la comparativa de bases vectoriales (IT-31)."""

from __future__ import annotations

import ast
import importlib.util
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


def test_escribir_resultados_anade_al_final_si_faltan_las_marcas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si alguien borra las marcas a mano, se añade al final sin perder nada.

    Es la tercera rama de la función, y la que decide si un descuido cuesta la
    prosa del ADR o solo deja el bloque en un sitio raro.
    """
    adr = tmp_path / "adr-0004.md"
    adr.write_text("# ADR\n\nProsa del autor, sin marcas.\n", encoding="utf-8")
    monkeypatch.setattr(experimento, "RUTA_ADR", adr)

    experimento.escribir_resultados(
        f"{experimento.MARCA_INICIO}\nresultados\n{experimento.MARCA_FIN}"
    )

    resultado = adr.read_text(encoding="utf-8")
    assert "Prosa del autor, sin marcas." in resultado
    assert "resultados" in resultado
    assert resultado.index("Prosa del autor") < resultado.index("resultados")


def test_escribir_resultados_crea_el_esqueleto_si_no_existe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La primera vez se crea el ADR con los huecos de IT-32 marcados."""
    adr = tmp_path / "adr-0004.md"
    monkeypatch.setattr(experimento, "RUTA_ADR", adr)

    experimento.escribir_resultados(
        f"{experimento.MARCA_INICIO}\nresultados\n{experimento.MARCA_FIN}"
    )

    resultado = adr.read_text(encoding="utf-8")
    assert "# ADR-0004: Base de datos vectorial" in resultado
    assert "resultados" in resultado
    assert "IT-32" in resultado


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

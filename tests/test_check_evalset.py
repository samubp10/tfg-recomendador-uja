"""Pruebas del verificador del conjunto de evaluación (IT-27).

``test_evalset.py`` valida el fichero real, que sí está versionado. Aquí se
prueba el **verificador**: qué detecta y qué deja pasar cuando el conjunto
está mal anotado. La diferencia importa porque el conjunto de evaluación es la
vara de medir de todo el proyecto ---sin él no hay Recall@K ni MRR que valgan
nada---, y un fallo suyo no se manifiesta como un error sino como una cifra
distinta de la real.

Los casos son mínimos y construidos a propósito, como en
``test_check_dataset.py``; el corpus completo no hace falta y no existe en CI.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_RUTA = RAIZ / "scripts" / "verificadores" / "check_evalset.py"
_spec = importlib.util.spec_from_file_location("check_evalset", _RUTA)
assert _spec is not None and _spec.loader is not None
check_evalset = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_evalset)

#: El mínimo real, guardado antes de que ninguna prueba lo toque.
MINIMO_REAL = check_evalset._MINIMO_PREGUNTAS

INFORMATICA = "Grado en Ingeniería Informática"
IAYC = "Grado en Inteligencia Artificial y Ciberseguridad"


@pytest.fixture(autouse=True)
def _sin_minimo_de_preguntas(monkeypatch) -> None:
    """Baja el suelo de 30 preguntas mientras se prueba otra cosa.

    Los casos de aquí anotan una o dos preguntas, que es lo que hace falta
    para provocar cada situación. Con el suelo puesto, todos saldrían con
    código 1 por tener el conjunto corto y ninguno probaría lo que dice
    probar: la comprobación buena taparía a las demás. El suelo tiene su
    propia prueba, con su valor real.
    """
    monkeypatch.setattr(check_evalset, "_MINIMO_PREGUNTAS", 1)


def _chunk(nombre: str, grados: list[str], origen: str = "guia") -> dict:
    return {
        "tipo": "chunk",
        "origen": origen,
        "nombre": nombre,
        "grados": grados,
        "codigos": ["1" for _ in grados],
        "texto": f"{nombre}\nContenido.",
        "chunk_index": 0,
        "total_chunks": 1,
    }


#: Corpus mínimo con la trampa que tiene el real: dos asignaturas distintas
#: que se llaman igual en titulaciones distintas. En el corpus del 05/08/2026
#: hay 14 nombres así («Prácticas externas», «Trabajo fin de Grado»...).
CORPUS = [
    _chunk("Estadística", [INFORMATICA]),
    _chunk("Estadística", [IAYC]),
    _chunk("Minería web", [INFORMATICA]),
    _chunk("Grado en Ingeniería Informática", [INFORMATICA], origen="salidas"),
]


def _pregunta(
    identificador: str, relevantes: list[dict], tipo: str = "temario"
) -> dict:
    return {
        "id": identificador,
        "tipo": tipo,
        "pregunta": "¿De qué va esto?",
        "relevantes": relevantes,
    }


def _ejecutar(tmp_path: Path, preguntas: list[dict], corpus=CORPUS) -> tuple[int, str]:
    """Lanza el verificador sobre un conjunto y un corpus de mentira."""
    ruta_eval = tmp_path / "evalset.json"
    ruta_eval.write_text(
        json.dumps({"preguntas": preguntas}, ensure_ascii=False), encoding="utf-8"
    )
    ruta_chunks = tmp_path / "chunks.json"
    ruta_chunks.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
    return check_evalset.main([str(ruta_eval), str(ruta_chunks)])


def _correr(tmp_path: Path, preguntas: list[dict], capsys, corpus=CORPUS) -> tuple:
    codigo = _ejecutar(tmp_path, preguntas, corpus)
    return codigo, capsys.readouterr().out


# --- Forma del fichero ------------------------------------------------------


def test_una_pregunta_sin_unidades_relevantes_se_denuncia(tmp_path, capsys) -> None:
    """Una pregunta con ``relevantes: []`` no mide nada, y contaba como fallo.

    Ningún chunk puede pertenecer a una unidad que no se ha anotado, así que
    esa pregunta aporta un 0 fijo a Recall@K y a MRR: hunde las dos métricas
    sin que el recuperador haya fallado. El verificador la recorría sin entrar
    en el bucle de selectores y terminaba diciendo que todo estaba correcto.
    """
    codigo, salida = _correr(tmp_path, [_pregunta("P-001", [])], capsys)

    assert codigo == 1
    assert "no anota ninguna unidad relevante" in salida


def test_un_selector_repetido_se_denuncia(tmp_path, capsys) -> None:
    """El mismo selector dos veces cuenta sus chunks dos veces."""
    selector = {"origen": "guia", "nombre": "Minería web"}
    codigo, salida = _correr(
        tmp_path, [_pregunta("P-001", [selector, selector])], capsys
    )

    assert codigo == 1
    assert "repetido" in salida


def test_una_clave_mal_escrita_en_el_selector_se_denuncia(tmp_path, capsys) -> None:
    """``grados`` en vez de ``grado`` desactiva el filtro sin decir nada.

    Es el peor caso de los tres, porque no rompe: ``chunks_de_unidad``
    pregunta si ``"grado" not in selector`` y con la clave mal escrita
    responde que no, así que el selector deja de filtrar por titulación y
    resuelve a todas las asignaturas homónimas del centro. El conjunto seguiría
    validando y las métricas saldrían de otra cosa.
    """
    selector = {"origen": "guia", "nombre": "Estadística", "grados": INFORMATICA}
    codigo, salida = _correr(tmp_path, [_pregunta("P-001", [selector])], capsys)

    assert codigo == 1
    assert "grados" in salida


def test_una_pregunta_mal_formada_da_un_error_y_no_un_KeyError(
    tmp_path, capsys
) -> None:
    """Sin el campo ``relevantes`` reventaba a mitad de recorrido.

    El informe se quedaba sin escribir y el rastro era un ``KeyError``, que no
    dice qué pregunta hay que arreglar.
    """
    codigo, salida = _correr(tmp_path, [{"id": "P-001", "tipo": "temario"}], capsys)

    assert codigo == 1
    assert "P-001" in salida
    assert "faltan los campos" in salida


# --- Ambigüedad de los selectores ------------------------------------------


def test_un_selector_sin_grado_sobre_un_nombre_repetido_se_denuncia(
    tmp_path, capsys
) -> None:
    """«Estadística» sin titulación no señala una unidad: señala las dos.

    Los fragmentos de la otra entran como relevantes, y el Recall de esa
    pregunta sale más alto de lo que le corresponde. El verificador solo
    exigía que el selector resolviera a **algún** chunk, así que este caso
    pasaba en verde.
    """
    selector = {"origen": "guia", "nombre": "Estadística"}
    codigo, salida = _correr(tmp_path, [_pregunta("P-001", [selector])], capsys)

    assert codigo == 1
    assert "ambiguo" in salida


def test_el_mismo_selector_con_grado_es_correcto(tmp_path, capsys) -> None:
    """Y con la titulación puesta deja de ser ambiguo: es lo que hay que hacer."""
    selector = {"origen": "guia", "nombre": "Estadística", "grado": IAYC}
    codigo, salida = _correr(tmp_path, [_pregunta("P-001", [selector])], capsys)

    assert codigo == 0
    assert "ambiguo" not in salida


def test_un_nombre_unico_no_necesita_grado(tmp_path, capsys) -> None:
    """No se exige `grado` porque sí: solo cuando el nombre no basta.

    Obligar a ponerlo siempre habría dado 19 falsos positivos sobre el
    conjunto real, donde la mayoría de los selectores identifican su unidad
    con el nombre y ya.
    """
    selector = {"origen": "guia", "nombre": "Minería web"}
    codigo, salida = _correr(tmp_path, [_pregunta("P-001", [selector])], capsys)

    assert codigo == 0
    assert "Todo correcto" in salida


def test_un_selector_que_no_resuelve_sigue_siendo_error(tmp_path, capsys) -> None:
    """La comprobación original de IT-27 no se ha perdido por el camino."""
    selector = {"origen": "guia", "nombre": "Asignatura que no existe"}
    codigo, salida = _correr(tmp_path, [_pregunta("P-001", [selector])], capsys)

    assert codigo == 1
    assert "no resuelve" in salida


# --- Cobertura: qué se puede afirmar y qué no ------------------------------


def test_la_cobertura_separa_lo_nombrado_de_lo_que_llega_por_arrastre(
    tmp_path, capsys
) -> None:
    """«Grados cubiertos: 2/2» contaba titulaciones que nadie ha preguntado.

    Una guía compartida pertenece a varias titulaciones a la vez, así que
    resolver un selector suyo marcaba como cubiertas a todas. Sobre el corpus
    real eso daba 11/11 titulaciones cubiertas cuando solo 7 aparecen nombradas
    en algún selector: las cuatro dobles entraban por compartir asignaturas con
    los grados simples. Que un fragmento suyo salga recuperado al preguntar por
    Mecánica no acredita que el conjunto pruebe esa titulación.
    """
    compartida = [_chunk("Álgebra", [INFORMATICA, IAYC])]
    selector = {"origen": "guia", "nombre": "Álgebra", "grado": INFORMATICA}
    codigo, salida = _correr(
        tmp_path, [_pregunta("P-001", [selector])], capsys, corpus=compartida
    )

    assert codigo == 0
    assert "nombradas en algún selector: 1" in salida
    assert "alcanzadas al resolver: 2" in salida
    assert f"SOLO POR ARRASTRE (ninguna pregunta la nombra): {IAYC}" in salida


def test_una_titulacion_que_nadie_toca_se_declara_sin_cubrir(tmp_path, capsys) -> None:
    """La comprobación que ya existía sigue viva: si nada la alcanza, se dice."""
    selector = {"origen": "guia", "nombre": "Minería web"}
    codigo, salida = _correr(tmp_path, [_pregunta("P-001", [selector])], capsys)

    assert codigo == 0
    assert f"SIN CUBRIR: {IAYC}" in salida


# --- El suelo de preguntas, con su valor real ------------------------------


def test_un_conjunto_por_debajo_del_minimo_se_denuncia(
    tmp_path, capsys, monkeypatch
) -> None:
    """La Definición de Hecho de IT-27 exige al menos 30 preguntas.

    Es un suelo para detectar que alguien se ha dejado media lista, no una
    acreditación de potencia estadística; el conjunto real tiene 50.
    """
    monkeypatch.setattr(check_evalset, "_MINIMO_PREGUNTAS", MINIMO_REAL)
    selector = {"origen": "guia", "nombre": "Minería web"}
    justo_una_menos = [
        _pregunta(f"P-{i:03}", [dict(selector)]) for i in range(MINIMO_REAL - 1)
    ]

    codigo, salida = _correr(tmp_path, justo_una_menos, capsys)

    assert codigo == 1
    assert f"mínimo {MINIMO_REAL}" in salida

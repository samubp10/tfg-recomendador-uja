"""Pruebas del experimento de recuperación (IT-38).

Ninguna incrusta ni consulta el índice: lo que se comprueba aquí es la
aritmética que sostiene las cifras del informe, que es justo donde este
proyecto ha ido acumulando defectos ---verificadores que decían «OK» midiendo
otra cosa---. Las tres métricas en sí ya están probadas en
``test_evaluacion.py``; lo que faltaba por cubrir es el techo, que se calcula
aquí y en ningún otro sitio.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "experimentos"))

import experimento_recuperacion as recuperacion  # noqa: E402


def chunk(origen: str, nombre: str) -> dict[str, object]:
    """Fragmento mínimo con lo que necesita el selector de relevantes.

    Args:
        origen: Tipo de fragmento.
        nombre: Nombre de su unidad.

    Returns:
        El fragmento.
    """
    return {"tipo": "chunk", "origen": origen, "nombre": nombre, "grados": ["G"]}


def pregunta(*unidades: tuple[str, str]) -> dict[str, object]:
    """Pregunta con los selectores de relevancia indicados.

    Args:
        unidades: Pares ``(origen, nombre)``.

    Returns:
        La entrada del conjunto de evaluación.
    """
    return {
        "id": "P-000",
        "tipo": "listado",
        "pregunta": "da igual",
        "relevantes": [{"origen": o, "nombre": n} for o, n in unidades],
    }


# --- El techo ---


def test_con_menos_relevantes_que_k_el_techo_es_uno():
    """Si la pregunta se resuelve con dos fragmentos, K=3 puede traerlos todos."""
    chunks = [chunk("guia", "A"), chunk("guia", "B"), chunk("guia", "Z")]
    preguntas = [pregunta(("guia", "A"), ("guia", "B"))]
    assert recuperacion.techo_de_recall(preguntas, chunks, 3) == 1.0


def test_con_mas_relevantes_que_k_el_techo_baja():
    """Seis fragmentos relevantes y K=3: el máximo alcanzable es 0,5.

    Es la razón de existir de esta función. Sin ella, una pregunta así
    parecería medio fallada cuando el recuperador ha hecho todo lo que podía.
    """
    chunks = [chunk("guia", nombre) for nombre in "ABCDEF"]
    preguntas = [pregunta(*(("guia", nombre) for nombre in "ABCDEF"))]
    assert recuperacion.techo_de_recall(preguntas, chunks, 3) == 0.5


def test_el_techo_promedia_sobre_las_preguntas():
    """Una alcanzable y otra que no: el techo del conjunto queda en medio."""
    chunks = [chunk("guia", nombre) for nombre in "ABCDEF"]
    preguntas = [
        pregunta(("guia", "A")),
        pregunta(*(("guia", nombre) for nombre in "ABCDEF")),
    ]
    assert recuperacion.techo_de_recall(preguntas, chunks, 3) == 0.75


def test_una_pregunta_sin_relevantes_no_rompe_el_techo():
    """Las de fuera de dominio se filtran antes, pero el cálculo no puede caer.

    Dividir por cero aquí abortaría el experimento entero por una entrada mal
    etiquetada, y el conjunto lo mantiene una persona a mano.
    """
    chunks = [chunk("guia", "A")]
    assert recuperacion.techo_de_recall([pregunta()], chunks, 3) == 0.0


def test_sin_preguntas_el_techo_es_cero():
    assert recuperacion.techo_de_recall([], [chunk("guia", "A")], 3) == 0.0


# --- La carga del corpus ---


def test_la_procedencia_no_cuenta_como_fragmento(tmp_path):
    """Se separa por tipo, nunca por posición.

    ``chunks.json`` encabeza la lista con un registro de procedencia. Contarlo
    como fragmento mete en el corpus un texto que no lo es y desplaza todos los
    índices del ranking.
    """
    fichero = tmp_path / "chunks.json"
    fichero.write_text(
        json.dumps(
            [
                chunk("guia", "A"),
                {"tipo": "procedencia", "fecha_extraccion": "2026-08-16"},
                chunk("guia", "B"),
            ]
        ),
        encoding="utf-8",
    )
    chunks, procedencia = recuperacion.cargar_chunks(fichero)
    assert len(chunks) == 2
    assert procedencia["fecha_extraccion"] == "2026-08-16"


def test_sin_registro_de_procedencia_se_devuelve_vacio(tmp_path):
    """Un corpus antiguo no lo trae, y eso no debe abortar la medición."""
    fichero = tmp_path / "chunks.json"
    fichero.write_text(json.dumps([chunk("guia", "A")]), encoding="utf-8")
    chunks, procedencia = recuperacion.cargar_chunks(fichero)
    assert len(chunks) == 1
    assert procedencia == {}


# --- El informe ---


AGREGADOS = {
    "recall@3": 0.65,
    "recall@5": 0.79,
    "recall@10": 0.88,
    "recall_unidad@3": 0.91,
    "recall_unidad@5": 0.97,
    "recall_unidad@10": 0.99,
    "mrr": 0.93,
}

TECHOS = {3: 0.754, 5: 0.906, 10: 0.966}

PROCEDENCIA = {"fecha_extraccion": "2026-08-16", "origen": "https://eps.ujaen.es"}


def test_el_informe_distingue_las_peticiones_de_consejo(tmp_path):
    """Que una petición de consejo reciba contexto no es un fallo del filtro.

    El sistema le entrega la banda completa a propósito: quien pregunta qué
    carrera le pega no debe recibir silencio. Si el informe no lo distingue, la
    cifra se lee como si el suelo fallara cuatro veces.
    """
    destino = tmp_path / "informe.md"
    recuperacion.informe(
        AGREGADOS,
        TECHOS,
        [
            ("P-051", 3, False, False),
            ("P-053", 20, True, False),
            ("P-055", 0, False, False),
        ],
        [],
        1499,
        56,
        PROCEDENCIA,
        destino,
    )
    escrito = destino.read_text(encoding="utf-8")
    assert "Rechazadas por el recuperador: 1 de 3" in escrito
    assert "**1 es petición de" in escrito
    assert "0.754" in escrito


def test_el_conjunto_de_validacion_se_informa_aparte(tmp_path):
    """Las dos cifras de rechazo no dicen lo mismo y no pueden mezclarse.

    La del conjunto de IT-27 mide lo bien que se ajustó el suelo, porque es el
    conjunto sobre el que se ajustó. La del otro mide lo bien que el sistema
    rechaza. Sumarlas en una sola cifra las estropearía las dos.
    """
    destino = tmp_path / "informe.md"
    recuperacion.informe(
        AGREGADOS,
        TECHOS,
        [("P-051", 3, False, False), ("P-055", 0, False, False)],
        [("V-001", 0, False, False), ("V-006", 12, False, True)],
        1499,
        56,
        PROCEDENCIA,
        destino,
    )
    escrito = destino.read_text(encoding="utf-8")
    assert "Rechazadas por el recuperador: 1 de 2" in escrito
    assert "**Rechazadas por el suelo: 1 de 2.**" in escrito
    assert "V-006" in escrito
    # V-006 pasa el suelo pero la para la comprobación de otro centro, así que
    # no cuenta como hueco: esa distinción es el motivo de IT-109.
    assert "Queda **0 sin ninguna red debajo**" not in escrito
    assert "**1 la para la comprobación de otro centro**" in escrito


def test_sin_conjunto_de_validacion_no_se_inventa_la_seccion(tmp_path):
    """Si el fichero no existe, el informe no debe fingir que sí."""
    destino = tmp_path / "informe.md"
    recuperacion.informe(
        AGREGADOS,
        TECHOS,
        [("P-055", 0, False, False)],
        [],
        1499,
        56,
        PROCEDENCIA,
        destino,
    )
    assert "no intervinieron en el ajuste" not in destino.read_text(encoding="utf-8")


# --- Las que pasan el suelo no son todas un fallo (IT-109) ---


def test_el_resumen_separa_lo_deliberado_de_lo_que_no_tiene_red():
    """«Pasa el suelo» y «el sistema la responde» no son lo mismo.

    Sin la separación, el informe contaba como fallo del filtro las peticiones
    de consejo, que pasan a propósito, y no distinguía a las que las para la
    comprobación de otro centro.
    """
    medidas = [
        ("V-001", 0, False, False),  # rechazada por el suelo
        ("V-002", 20, False, False),  # pasa sin red: el hueco de verdad
        ("V-003", 20, True, False),  # consejo: deliberado
        ("V-005", 20, False, True),  # la para la comprobación de centro
    ]
    frase = recuperacion._resumen_de_las_que_pasan(medidas)
    assert "De las 3 que pasan" in frase
    assert "**1 pide consejo**" in frase
    assert "**1 la para la comprobación de otro centro**" in frase
    assert "Queda **1 sin ninguna red debajo**" in frase


def test_el_resumen_concuerda_en_plural():
    """El informe lo lee un tribunal: «Quedan 1» delata quién lo escribe."""
    medidas = [
        ("V-002", 20, False, False),
        ("V-004", 20, False, False),
        ("V-003", 20, True, False),
        ("V-006", 20, True, False),
        ("V-005", 20, False, True),
        ("V-007", 20, False, True),
    ]
    frase = recuperacion._resumen_de_las_que_pasan(medidas)
    assert "**2 piden consejo**" in frase
    assert "**2 las para la comprobación de otro centro**" in frase
    assert "Quedan **2 sin ninguna red debajo**" in frase


def test_si_el_suelo_las_rechaza_todas_el_resumen_lo_dice():
    """El caso bueno también tiene que redactarse, no salir una frase rota."""
    medidas = [("V-001", 0, False, False), ("V-002", 0, False, False)]
    frase = recuperacion._resumen_de_las_que_pasan(medidas)
    assert frase == "No pasa ninguna: el suelo las rechaza todas."


# --- Las ajenas contra el índice y el recorrido entero (IT-113) -------------


def _ajena(identificador, texto="¿dónde estudio medicina?"):
    """Una pregunta declarada fuera de dominio."""
    return {"id": identificador, "tipo": "fuera_de_dominio", "pregunta": texto}


def _sin_indice(monkeypatch, traidos_por_pregunta):
    """Sustituye todo lo que toca el índice real.

    Args:
        monkeypatch: Parcheador de pytest.
        traidos_por_pregunta: Cuántos fragmentos devuelve cada llamada, en orden.
    """
    pendientes = list(traidos_por_pregunta)
    monkeypatch.setattr(recuperacion, "abrir_indice", lambda ruta, modelo: None)
    monkeypatch.setattr(recuperacion, "incrustador_de_consultas", lambda modelo: None)
    monkeypatch.setattr(recuperacion, "distancia_del_indice", lambda ruta: "cosine")
    monkeypatch.setattr(recuperacion, "catalogo_del_indice", lambda ruta: ["G"])
    monkeypatch.setattr(
        recuperacion, "contexto_para", lambda *a, **kw: [None] * pendientes.pop(0)
    )


def test_medir_ajenas_cuenta_cuantos_fragmentos_pasan(tmp_path, monkeypatch):
    """Rechazar es acertar: lo que se cuenta es que no llegue contexto."""
    _sin_indice(monkeypatch, [0, 4])

    medidas = recuperacion.medir_ajenas([_ajena("a1"), _ajena("a2")], tmp_path)

    assert [(i, n) for i, n, _c, _o in medidas] == [("a1", 0), ("a2", 4)]


def test_medir_ajenas_marca_las_peticiones_de_consejo(tmp_path, monkeypatch):
    """El recuperador les entrega contexto a propósito, así que no son un fallo."""
    _sin_indice(monkeypatch, [5])

    medidas = recuperacion.medir_ajenas(
        [_ajena("a1", "¿qué carrera me recomiendas si me gusta la biología?")], tmp_path
    )

    assert medidas[0][2] is True


def test_medir_ajenas_marca_las_que_nombran_otro_centro(tmp_path, monkeypatch):
    """La comprobación de centro ajeno es una barrera distinta del suelo."""
    _sin_indice(monkeypatch, [3])

    medidas = recuperacion.medir_ajenas(
        [_ajena("a1", "¿se estudia Medicina en la Facultad de Ciencias de la Salud?")],
        tmp_path,
    )

    assert medidas[0][3] is True


def _preparar_main(monkeypatch, tmp_path, ajenas_traidas, con_validacion):
    """Deja `main` listo para recorrerse sin índice ni incrustaciones.

    Returns:
        Los argumentos con los que llamarlo.
    """
    corpus = tmp_path / "chunks.json"
    corpus.write_text(
        json.dumps([chunk("guia", "A"), chunk("guia", "B")]), encoding="utf-8"
    )

    evalset = tmp_path / "evalset.json"
    evalset.write_text(
        json.dumps(
            {
                "preguntas": [
                    {
                        "id": "d1",
                        "tipo": "listado",
                        "pregunta": "¿y el temario?",
                        "relevantes": [{"origen": "guia", "nombre": "A"}],
                    },
                    _ajena("a1"),
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(recuperacion, "RUTA_EVAL", evalset)

    validacion = tmp_path / "validacion.json"
    if con_validacion:
        validacion.write_text(
            json.dumps({"preguntas": [_ajena("v1"), _ajena("v2")]}), encoding="utf-8"
        )

    agregados = {"mrr": 0.926}
    for k in recuperacion.KS:
        agregados[f"recall@{k}"] = 0.8
        agregados[f"recall_unidad@{k}"] = 0.9
    monkeypatch.setattr(
        recuperacion, "evaluar_modelo", lambda *a, **kw: {"agregados": agregados}
    )
    monkeypatch.setattr(recuperacion, "incrustador_de_documentos", lambda modelo: None)
    _sin_indice(monkeypatch, ajenas_traidas)

    salida = tmp_path / "sub" / "it38.md"
    return [
        "--chunks",
        str(corpus),
        "--indice",
        str(tmp_path),
        "--validacion",
        str(validacion),
        "--salida",
        str(salida),
    ], salida


def test_main_mide_dominio_y_ajenas_y_escribe_el_informe(tmp_path, monkeypatch, capsys):
    args, salida = _preparar_main(monkeypatch, tmp_path, [0], con_validacion=False)

    recuperacion.main(args)

    texto = capsys.readouterr().out
    assert "Corpus: 2 fragmentos | dominio: 1 preguntas" in texto
    assert "MRR = 0.926" in texto
    assert "rechazadas: 1 de 1" in texto
    assert salida.exists()


def test_main_mide_aparte_el_conjunto_que_no_ajusto_el_suelo(
    tmp_path, monkeypatch, capsys
):
    """Es el que sostiene la conclusión sobre el rechazo; el otro mide el ajuste."""
    args, _ = _preparar_main(monkeypatch, tmp_path, [0, 0, 3], con_validacion=True)

    recuperacion.main(args)

    texto = capsys.readouterr().out
    assert "que no intervino en el ajuste" in texto
    assert "rechazadas: 1 de 2" in texto


def test_main_sin_fichero_de_validacion_no_lo_inventa(tmp_path, monkeypatch, capsys):
    args, _ = _preparar_main(monkeypatch, tmp_path, [0], con_validacion=False)

    recuperacion.main(args)

    assert "que no intervino en el ajuste" not in capsys.readouterr().out

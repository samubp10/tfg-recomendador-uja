"""Pruebas de la auditoría de guías en PDF (IT-95).

Lo que se prueba aquí no es la extracción ---de eso responde
``test_guia_pdf.py``--- sino el **veredicto**: que el guion distingue «he
auditado la colección y está bien» de «no he podido auditarla». Las dos cosas
terminaban antes en el mismo sitio, imprimiendo «Guías PDF OK» y devolviendo
0, y una auditoría que no se ha hecho no es una auditoría superada.

Los casos que no pueden auditarse no necesitan ningún PDF; el caso bueno usa
una guía real de ``tests/fixtures/``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tfg_uja.guia_pdf import extraer_guia
from tfg_uja.invariantes import InvarianteRoto

RAIZ = Path(__file__).resolve().parent.parent
_RUTA = RAIZ / "scripts" / "verificadores" / "check_guias_pdf.py"
_spec = importlib.util.spec_from_file_location("check_guias_pdf", _RUTA)
assert _spec is not None and _spec.loader is not None
check_guias_pdf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_guias_pdf)

#: Guía real de la EPSJ, la misma que usa `test_guia_pdf.py`.
FIXTURE = RAIZ / "tests" / "fixtures" / "guia_estadistica_iayc.pdf"
CODIGO = "15712099"
GRADO = "Grado en Inteligencia Artificial y Ciberseguridad"


def _guia(codigo: str | None = CODIGO, **extra: object) -> dict:
    """Item ``guia`` con el contenido que hoy sale del PDF de la fixture.

    El contenido se calcula con el propio extractor, así que la comprobación
    de discrepancias pasa por construcción: aquí no se está probando que la
    extracción sea correcta, sino qué veredicto emite el guion cuando no lo
    es.
    """
    extraido = extraer_guia(FIXTURE.read_bytes()) or {"resumen": "", "temario": ""}
    return {
        "tipo": "guia",
        "grado": GRADO,
        "codigo": codigo,
        "nombre": "Estadística",
        "formato": "pdf",
        "resumen": extraido["resumen"],
        "temario": extraido["temario"],
        "fallback": False,
        **extra,
    }


def _asignatura(codigo: str | None = CODIGO, tiene_guia: bool = True) -> dict:
    return {
        "tipo": "asignatura",
        "grado": GRADO,
        "codigo": codigo,
        "nombre": "ESTADÍSTICA",
        "tiene_guia": tiene_guia,
    }


def _escenario(tmp_path: Path, dataset: list[dict], con_pdf: bool) -> tuple[str, str]:
    """Deja en disco un dataset y, si procede, el PDF que le corresponde."""
    ruta = tmp_path / "grados.json"
    ruta.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    carpeta = tmp_path / "guias_pdf"
    carpeta.mkdir()
    if con_pdf:
        (carpeta / f"{CODIGO}.pdf").write_bytes(FIXTURE.read_bytes())
    return str(ruta), str(carpeta)


def test_una_coleccion_completa_y_fiel_sale_con_cero(tmp_path, capsys) -> None:
    """El caso bueno sigue siendo el caso bueno."""
    argv = _escenario(tmp_path, [_guia(), _asignatura()], con_pdf=True)

    assert check_guias_pdf.main(list(argv)) == 0
    assert "Guías PDF OK" in capsys.readouterr().out


def test_si_falta_el_pdf_no_dice_que_la_extraccion_es_fiel(tmp_path, capsys) -> None:
    """Regresión: faltaba el PDF, no se auditaba nada y salía «OK» con 0.

    Una guía sin su PDF no se compara contra nada. El guion avisaba y seguía
    hasta imprimir que la extracción es fiel, de modo que una auditoría a
    medias se leía como una auditoría superada.
    """
    argv = _escenario(tmp_path, [_guia(), _asignatura()], con_pdf=False)

    assert check_guias_pdf.main(list(argv)) == 1
    salida = capsys.readouterr().out
    assert "AUDITORÍA INCOMPLETA" in salida
    assert "Guías PDF OK" not in salida


def test_sin_carpeta_de_pdf_la_auditoria_es_imposible_no_correcta(
    tmp_path, capsys
) -> None:
    """Regresión: sin la carpeta se devolvía 0, o sea «auditoría superada»."""
    ruta = tmp_path / "grados.json"
    ruta.write_text(json.dumps([_guia(), _asignatura()]), encoding="utf-8")

    assert check_guias_pdf.main([str(ruta), str(tmp_path / "no_existe")]) == 1
    assert "AUDITORÍA IMPOSIBLE" in capsys.readouterr().out


def test_una_guia_sin_formato_deja_la_auditoria_incompleta(tmp_path, capsys) -> None:
    """Las guías sin `formato` quedan fuera de la auditoría, y eso se nota.

    Antes era solo un aviso: la guía no se auditaba y el veredicto final
    seguía diciendo que la extracción es fiel, sin distinguir entre las que se
    comprobaron y las que no.
    """
    sin_formato = _guia()
    del sin_formato["formato"]
    argv = _escenario(tmp_path, [sin_formato, _asignatura()], con_pdf=True)

    assert check_guias_pdf.main(list(argv)) == 1
    assert "sin el campo `formato`" in capsys.readouterr().out


def test_un_dataset_sin_ninguna_guia_no_acredita_nada(tmp_path, capsys) -> None:
    """Cero guías auditadas no es una extracción fiel: es no haber mirado.

    Sin ninguna guía en PDF no se recorre el bucle, no hay rótulos que falten
    ni discrepancias que encontrar, y el guion llegaba igualmente a su «OK»
    final. La conclusión no tenía ni una sola evidencia detrás.
    """
    argv = _escenario(tmp_path, [_asignatura(tiene_guia=False)], con_pdf=True)

    assert check_guias_pdf.main(list(argv)) == 1
    assert "ni una sola guía" in capsys.readouterr().out


def test_un_pdf_que_el_dataset_no_referencia_se_denuncia(tmp_path, capsys) -> None:
    """Un PDF de más solo es legítimo si es una guía publicada sin contenido.

    Es el caso del DQA-0004: la asignatura enlaza su guía, el rastreo se la
    baja y sus secciones vienen vacías, así que no llega a emitirse el item.
    Cualquier otro PDF suelto significa que la carpeta y el dataset no se
    corresponden: o se ha perdido una extracción, o es un resto de otro
    rastreo.
    """
    ruta, carpeta = _escenario(tmp_path, [_guia(), _asignatura()], con_pdf=True)
    (Path(carpeta) / "99999999.pdf").write_bytes(FIXTURE.read_bytes())

    assert check_guias_pdf.main([ruta, carpeta]) == 1
    assert "99999999" in capsys.readouterr().out


def test_el_pdf_de_una_guia_sin_codigo_no_se_inventa(tmp_path) -> None:
    """Sin código no hay fichero que buscar, y eso no se resuelve con un alias.

    El nombre del PDF es el código. Las guías sin código recibían el nombre de
    reserva ``sin_codigo.pdf``, con lo que todas apuntaban al mismo fichero y
    se auditaban contra el PDF de otra.
    """
    assert check_guias_pdf._pdf_de(tmp_path, _guia(codigo=None)) is None
    assert check_guias_pdf._pdf_de(tmp_path, _guia()) == tmp_path / f"{CODIGO}.pdf"


def test_dos_guias_con_el_mismo_codigo_abortan(tmp_path) -> None:
    """Dos guías con el mismo código se auditarían contra el mismo PDF.

    La identidad del fichero es el código, así que si se repite deja de
    identificar: una de las dos daría discrepancia sin que el motivo real
    apareciera por ningún lado.
    """
    argv = _escenario(tmp_path, [_guia(), _guia(), _asignatura()], con_pdf=True)

    with pytest.raises(InvarianteRoto, match="repetidos"):
        check_guias_pdf.main(list(argv))


# --- Los últimos caminos sin cubrir (IT-113) --------------------------------


def test_una_guia_sin_codigo_no_se_puede_auditar(tmp_path, capsys) -> None:
    """El PDF se nombra por el código: sin él no hay fichero que localizar.

    No es lo mismo que un PDF ausente, y por eso se cuenta aparte: aquí no
    falta el fichero, falta la manera de saber cuál es.
    """
    dataset = [_asignatura(codigo=None), _guia(codigo=None)]
    ruta, carpeta = _escenario(tmp_path, dataset, con_pdf=False)

    codigo = check_guias_pdf.main([ruta, carpeta])

    salida = capsys.readouterr().out
    assert codigo == 1
    assert "sin código" in salida
    assert "se nombra por" in salida


def test_una_guia_a_la_que_le_falta_un_rotulo_de_la_plantilla_se_denuncia(
    tmp_path, capsys, monkeypatch
) -> None:
    """Si la Universidad retira un rótulo, su sección deja de terminar donde debe.

    Se sustituye el detector, no el PDF: lo que se prueba aquí es el veredicto
    del verificador, no la extracción, que tiene sus propias pruebas.
    """
    monkeypatch.setattr(
        check_guias_pdf, "rotulos_ausentes", lambda datos: ["PROFESORADO"]
    )
    dataset = [_asignatura(), _guia()]
    ruta, carpeta = _escenario(tmp_path, dataset, con_pdf=True)

    with pytest.raises(InvarianteRoto, match="PROFESORADO"):
        check_guias_pdf.main([ruta, carpeta])


def test_una_guia_cuyo_texto_no_coincide_con_su_pdf_se_denuncia(
    tmp_path, capsys
) -> None:
    """El dataset dice una cosa y el PDF del que salió dice otra."""
    dataset = [_asignatura(), _guia(resumen="Un resumen que el PDF no trae.")]
    ruta, carpeta = _escenario(tmp_path, dataset, con_pdf=True)

    with pytest.raises(InvarianteRoto, match=CODIGO):
        check_guias_pdf.main([ruta, carpeta])


def test_un_pdf_sin_guia_pero_con_motivo_se_explica(tmp_path, capsys) -> None:
    """DQA-0004: la asignatura enlaza su guía y la publica sin contenido.

    El PDF existe y se descarga; lo que no trae es qué contar, así que no se
    emite ningún item `guia`. Es la única explicación legítima de un huérfano.
    """
    dataset = [_asignatura(), _guia(), _asignatura(codigo="99999999")]
    ruta, carpeta = _escenario(tmp_path, dataset, con_pdf=True)
    (Path(carpeta) / "99999999.pdf").write_bytes(FIXTURE.read_bytes())

    codigo = check_guias_pdf.main([ruta, carpeta])

    salida = capsys.readouterr().out
    assert codigo == 0
    assert "1 PDF sin guía en el dataset, y con motivo" in salida

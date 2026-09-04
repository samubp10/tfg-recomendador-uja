"""Pruebas del verificador del dataset (IT-10, ampliado en IT-78).

El verificador vive en ``scripts/`` y se ejecuta a mano contra el dataset
completo, que no está versionado. Estas pruebas no necesitan ese dataset:
comprueban la lógica de la comprobación con casos mínimos construidos a
propósito, del mismo modo que ``test_indexer.py`` prueba la indexación sin
descargar ningún modelo.

``scripts/`` no es un paquete importable, así que el módulo se carga por su
ruta en lugar de con un ``import`` normal.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_RUTA = RAIZ / "scripts" / "verificadores" / "check_dataset.py"
_spec = importlib.util.spec_from_file_location("check_dataset", _RUTA)
assert _spec is not None and _spec.loader is not None
check_dataset = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_dataset)


def _grado(nombre: str, url_asignaturas: str | None) -> dict:
    return {
        "tipo": "grado",
        "nombre": nombre,
        "es_doble_grado": nombre.startswith("Doble Grado"),
        "url_asignaturas": url_asignaturas,
        "url_salidas": None,
    }


def _asignatura(grado: str, nombre: str) -> dict:
    return {"tipo": "asignatura", "grado": grado, "nombre": nombre}


def test_detecta_la_titulacion_que_se_queda_sin_asignaturas():
    # Es el caso real de Geomática: la fuente cambió el formato de sus tablas,
    # el rastreador las descartó con un aviso y el verificador decía «OK».
    datos = [
        _grado("Grado en Ingeniería Informática", "https://eps.ujaen.es/a"),
        _grado("Grado en Ingeniería Geomática y Topográfica", "https://eps.ujaen.es/b"),
        _asignatura("Grado en Ingeniería Informática", "Matemática discreta"),
    ]
    assert check_dataset.grados_sin_asignaturas(datos) == [
        "Grado en Ingeniería Geomática y Topográfica"
    ]


def test_un_dataset_completo_no_da_falsos_positivos():
    datos = [
        _grado("Grado en Ingeniería Informática", "https://eps.ujaen.es/a"),
        _asignatura("Grado en Ingeniería Informática", "Matemática discreta"),
    ]
    assert check_dataset.grados_sin_asignaturas(datos) == []


def test_los_dobles_grados_no_cuentan_como_vacios():
    # Un doble grado no tiene página propia de asignaturas: es la unión de sus
    # dos grados base, que se rastrean por separado (decisión de IT-04/IT-07).
    # Sin asignaturas propias es lo normal, no un fallo.
    datos = [
        _grado("Doble Grado en Ingeniería Eléctrica y Mecánica", None),
        _grado("Grado en Ingeniería Mecánica", "https://eps.ujaen.es/a"),
        _asignatura("Grado en Ingeniería Mecánica", "Diseño de máquinas"),
    ]
    assert check_dataset.grados_sin_asignaturas(datos) == []


def test_varias_titulaciones_vacias_se_informan_todas():
    # Al cambiar la fuente cayeron las dos titulaciones de Geomática a la vez;
    # informar solo de la primera obligaría a repetir el rastreo entero para
    # descubrir la segunda. El mensaje del verificador interpola esta lista,
    # así que devolverlas todas es lo que hace el aviso accionable.
    datos = [
        _grado("Grado A", "https://eps.ujaen.es/a"),
        _grado("Grado B", "https://eps.ujaen.es/b"),
    ]
    assert check_dataset.grados_sin_asignaturas(datos) == ["Grado A", "Grado B"]


def test_una_titulacion_sin_pagina_de_asignaturas_no_se_exige():
    # Si la fuente deja de publicar la página de un grado, eso es otro
    # problema distinto y no debe confundirse con "no supe leer sus tablas".
    datos = [_grado("Grado en Ingeniería Informática", None)]
    assert check_dataset.grados_sin_asignaturas(datos) == []


# ---------------------------------------------------------------------------
# El resto de comprobaciones del verificador (IT-113)
#
# Hasta aquí solo estaba probada `grados_sin_asignaturas`. Las otras catorce
# funciones ---las que de verdad deciden si el corpus vale--- no las cubría
# ninguna prueba, y son las que acaban diciendo «Dataset OK».
# ---------------------------------------------------------------------------

import json  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, str(RAIZ / "src"))

from tfg_uja.invariantes import InvarianteRoto  # noqa: E402


def _asig(
    grado="Grado en Ingeniería Informática",
    nombre="Matemática discreta",
    codigo="12345",
    tipo="FB",
    ects=6,
    ofertada=True,
    tiene_guia=False,
    menciones=None,
    curso="Primer curso",
):
    """Una asignatura con todos los campos del modelo de datos."""
    return {
        "tipo": "asignatura",
        "grado": grado,
        "codigo": codigo,
        "nombre": nombre,
        "tipo_asignatura": tipo,
        "ects": ects,
        "ofertada": ofertada,
        "tiene_guia": tiene_guia,
        "menciones": menciones if menciones is not None else [],
        "curso": curso,
    }


def _guia(grado="Grado en Ingeniería Informática", codigo="12345", **extra):
    """Una guía docente del dataset."""
    base = {
        "tipo": "guia",
        "grado": grado,
        "codigo": codigo,
        "nombre": "Matemática discreta",
        "resumen": "Un resumen.",
        "temario": "Un temario.",
        "fallback": False,
        "formato": "pdf",
        "curso": "2026-27",
    }
    base.update(extra)
    return base


# --- Binario colado en un campo de texto ------------------------------------


def test_la_firma_de_un_pdf_es_binario():
    # IT-67: una guía servida como PDF pasaba por el respaldo y guardaba el
    # binario del PDF en `cuerpo_general`; el verificador respondía «OK».
    assert check_dataset._parece_binario("%PDF-1.7 blah")


def test_una_densidad_alta_de_control_es_binario():
    assert check_dataset._parece_binario("texto\x00\x01\x02\x03\x04corto")


def test_el_texto_normal_no_es_binario():
    assert not check_dataset._parece_binario("Programación orientada a objetos.\n")


def test_el_texto_vacio_no_es_binario():
    # Sin la guarda, dividir entre la longitud reventaría con ZeroDivisionError.
    assert not check_dataset._parece_binario("")


def test_los_saltos_y_tabuladores_no_cuentan_como_control():
    assert not check_dataset._parece_binario("uno\n\tdos\r\ntres\n")


def test_falla_si_una_guia_guarda_el_binario_del_pdf():
    datos = [_guia(resumen="%PDF-1.7 " + "x" * 100)]
    with pytest.raises(InvarianteRoto, match="binario"):
        check_dataset._exigir_texto_sin_binario(datos)


def test_un_dataset_sin_binario_pasa():
    check_dataset._exigir_texto_sin_binario([_guia(), _asig()])


# --- Nombres de asignatura --------------------------------------------------


def test_un_parentesis_en_el_nombre_delata_texto_colado():
    # Caso real: la fuente empezó a incrustar un enlace «( Syllabus )» dentro
    # de la celda del nombre (IT-93).
    asignaturas = [_asig(nombre="Matemática discreta ( Syllabus )")]
    grados = [_grado("Grado en Ingeniería Informática", "https://eps.ujaen.es/a")]

    with pytest.raises(InvarianteRoto, match="paréntesis"):
        check_dataset._exigir_nombres_limpios(asignaturas, grados)


def test_el_acronimo_del_grado_de_origen_se_admite_en_un_doble():
    # IT-101: los planes de los dobles anotan de qué grado viene cada
    # asignatura, y eso lo escribe la fuente, no es basura arrastrada.
    doble = "Doble Grado en Ingeniería Mecánica y Organización Industrial"
    asignaturas = [_asig(grado=doble, nombre="GESTIÓN FINANCIERA (GIOI)")]
    grados = [_grado(doble, "https://eps.ujaen.es/a")]

    check_dataset._exigir_nombres_limpios(asignaturas, grados)


def test_ese_mismo_acronimo_en_una_titulacion_simple_sigue_fallando():
    """La excepción es solo de los dobles: en un grado simple no hay origen."""
    asignaturas = [_asig(nombre="GESTIÓN FINANCIERA (GIOI)")]
    grados = [_grado("Grado en Ingeniería Informática", "https://eps.ujaen.es/a")]

    with pytest.raises(InvarianteRoto, match="paréntesis"):
        check_dataset._exigir_nombres_limpios(asignaturas, grados)


def test_otro_parentesis_en_un_doble_tampoco_pasa():
    doble = "Doble Grado en Ingeniería Mecánica y Organización Industrial"
    asignaturas = [_asig(grado=doble, nombre="Matemática discreta ( Syllabus )")]
    grados = [_grado(doble, "https://eps.ujaen.es/a")]

    with pytest.raises(InvarianteRoto, match="paréntesis"):
        check_dataset._exigir_nombres_limpios(asignaturas, grados)


# --- Menciones --------------------------------------------------------------


def test_dos_menciones_pegadas_por_una_barra_fallan():
    with pytest.raises(InvarianteRoto, match="barra"):
        check_dataset._exigir_menciones_separadas([_asig(menciones=["Una/Otra"])])


def test_una_mencion_con_y_no_son_dos_menciones():
    """Ampliarlo a « y » daría 14 falsos positivos sobre las 16 menciones reales."""
    check_dataset._exigir_menciones_separadas(
        [_asig(menciones=["Ingeniería y fabricación mecánica"])]
    )


# --- Recuentos, oferta y ECTS -----------------------------------------------


def test_un_recuento_que_no_cuadra_dice_que_hacer():
    with pytest.raises(InvarianteRoto, match="actualiza ESPERADO"):
        check_dataset._exigir_recuentos_esperados((("grados", 11),))


def test_los_recuentos_correctos_pasan():
    check_dataset._exigir_recuentos_esperados(
        (("grados", check_dataset.ESPERADO["grados"]),)
    )


def test_falta_el_campo_ofertada():
    asignatura = _asig()
    del asignatura["ofertada"]

    with pytest.raises(InvarianteRoto, match="ofertada"):
        check_dataset._exigir_oferta([asignatura])


def test_se_cuentan_las_no_ofertadas(monkeypatch):
    monkeypatch.setitem(check_dataset.ESPERADO, "no_ofertadas", 2)
    asignaturas = [_asig(ofertada=False), _asig(ofertada=False), _asig()]

    assert check_dataset._exigir_oferta(asignaturas) == 2


def test_un_numero_distinto_de_no_ofertadas_falla():
    with pytest.raises(InvarianteRoto, match="no ofertadas"):
        check_dataset._exigir_oferta([_asig(ofertada=False)])


def test_se_cuentan_las_que_la_fuente_deja_sin_ects(monkeypatch):
    """El ECTS ausente se refleja, no se imputa."""
    monkeypatch.setitem(check_dataset.ESPERADO, "sin_ects", 1)

    assert check_dataset._exigir_ects([_asig(ects=None), _asig()]) == 1


def test_un_numero_distinto_de_sin_ects_falla():
    with pytest.raises(InvarianteRoto, match="sin ECTS"):
        check_dataset._exigir_ects([_asig(ects=None), _asig(ects=None)])


# --- Titulaciones vacías ----------------------------------------------------


def test_exigir_ninguna_titulacion_vacia_falla_con_su_nombre():
    datos = [
        _grado("Grado en Ingeniería Informática", "https://eps.ujaen.es/a"),
        _grado("Grado en Ingeniería Geomática y Topográfica", "https://eps.ujaen.es/b"),
        _asig(),
    ]

    with pytest.raises(InvarianteRoto, match="Geomática"):
        check_dataset._exigir_ninguna_titulacion_vacia(datos)


def test_exigir_ninguna_titulacion_vacia_pasa_con_todas_pobladas():
    datos = [_grado("Grado en Ingeniería Informática", "https://a"), _asig()]

    check_dataset._exigir_ninguna_titulacion_vacia(datos)


# --- Lo que se informa sin exigir -------------------------------------------


def test_la_procedencia_se_informa_con_su_curso(capsys):
    check_dataset._informar_procedencia(
        {"fecha_extraccion": "2026-08-16"}, [_guia(curso="2026-27")]
    )

    salida = capsys.readouterr().out
    assert "2026-08-16" in salida
    assert "2026-27" in salida


def test_un_dataset_sin_procedencia_pide_regenerarlo(capsys):
    check_dataset._informar_procedencia({}, [_guia()])

    assert "anterior a IT-90" in capsys.readouterr().out


def test_se_avisa_de_las_guias_sin_curso_en_la_url(capsys):
    """Si la fuente cambia el formato de la URL, el curso se pierde sin ruido."""
    check_dataset._informar_procedencia(
        {"fecha_extraccion": "2026-08-16"}, [_guia(curso=None), _guia()]
    )

    assert "1 de 2 guias sin curso" in capsys.readouterr().out


def test_el_reparto_de_formatos_se_informa(capsys):
    check_dataset._informar_formatos([_guia(formato="pdf"), _guia(formato="html")])

    salida = capsys.readouterr().out
    assert "'pdf': 1" in salida
    assert "'html': 1" in salida


def test_una_guia_sin_formato_pide_regenerar(capsys):
    # En cinco días el corpus pasó de 62 de 296 guías en PDF a las 288 de 288,
    # y solo se supo mucho después.
    check_dataset._informar_formatos([_guia(formato=None)])

    salida = capsys.readouterr().out
    assert "sin declarar" in salida
    assert "IT-95" in salida


def test_el_reparto_por_titulacion_marca_las_que_no_tienen_pagina(capsys):
    grados = [
        _grado("Grado en Ingeniería Informática", "https://eps.ujaen.es/a"),
        _grado("Doble Grado en Ingeniería Mecánica y Organización Industrial", None),
    ]

    check_dataset._informar_asignaturas_por_titulacion(grados, [_asig(), _asig()])

    salida = capsys.readouterr().out
    assert "2  Grado en Ingeniería Informática" in salida
    assert "(sin página propia)" in salida


def test_se_avisa_de_la_asignatura_cuya_guia_no_aporta_nada(capsys):
    # IT-94/IT-97: la guía se lee bien y sus secciones están vacías en origen,
    # así que se avisa en vez de fallar.
    asignaturas = [_asig(codigo="99999", tiene_guia=True)]

    check_dataset._avisar_guias_sin_contenido(asignaturas, [])

    assert "1 asignaturas enlazan una guía" in capsys.readouterr().out


def test_la_guia_se_empareja_por_codigo_o_nombre(capsys):
    """48 asignaturas del corpus no tienen código: la clave es `codigo or nombre`."""
    asignaturas = [_asig(codigo=None, nombre="Sin código", tiene_guia=True)]
    guias = [_guia(codigo=None, nombre="Sin código")]

    check_dataset._avisar_guias_sin_contenido(asignaturas, guias)

    assert capsys.readouterr().out == ""


def test_sin_guias_huerfanas_no_se_avisa(capsys):
    check_dataset._avisar_guias_sin_contenido([_asig(tiene_guia=True)], [_guia()])

    assert capsys.readouterr().out == ""


# --- Curso ------------------------------------------------------------------


def test_una_optativa_sin_curso_es_lo_normal(capsys):
    """La EPSJ agrupa el curso por tablas y su bloque de optativas no lleva."""
    check_dataset._comprobar_curso([_asig(tipo="OP", curso=None), _asig()])

    assert "1/2 asignaturas lo declaran" in capsys.readouterr().out


def test_una_troncal_sin_curso_delata_un_rotulo_cambiado():
    # IT-105: si aparece una troncal sin curso, es que el rótulo de su sección
    # ha cambiado y la hemos perdido en silencio.
    with pytest.raises(InvarianteRoto, match="no optativas sin curso"):
        check_dataset._comprobar_curso([_asig(tipo="OB", curso=None)])


def test_el_reparto_de_cursos_se_imprime(capsys):
    check_dataset._comprobar_curso([_asig(curso="Primer curso")])

    assert "'Primer curso': 1" in capsys.readouterr().out


# --- El recorrido entero ----------------------------------------------------


def test_main_recorre_el_dataset_y_dice_que_esta_bien(tmp_path, monkeypatch, capsys):
    """Se ajusta ESPERADO al dataset mínimo: lo que se mide es el recorrido."""
    monkeypatch.setattr(
        check_dataset,
        "ESPERADO",
        {
            "asignaturas": 1,
            "grados": 1,
            "guias": 1,
            "salidas": 1,
            "no_ofertadas": 0,
            "sin_ects": 0,
        },
    )
    datos = [
        {"tipo": "procedencia", "fecha_extraccion": "2026-08-16"},
        _grado("Grado en Ingeniería Informática", "https://eps.ujaen.es/a"),
        _asig(tiene_guia=True),
        _guia(),
        {
            "tipo": "salidas",
            "grado": "Grado en Ingeniería Informática",
            "texto": "Salidas.",
        },
    ]
    ruta = tmp_path / "grados.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    assert check_dataset.main([str(ruta)]) == 0
    assert "Dataset OK" in capsys.readouterr().out


def test_main_falla_cuando_un_invariante_se_rompe(tmp_path, monkeypatch):
    """La titulación vacía se comprueba antes que los recuentos, y por eso da nombre."""
    monkeypatch.setattr(
        check_dataset,
        "ESPERADO",
        {
            "asignaturas": 1,
            "grados": 1,
            "guias": 0,
            "salidas": 0,
            "no_ofertadas": 0,
            "sin_ects": 0,
        },
    )
    datos = [
        _grado("Grado en Ingeniería Informática", "https://eps.ujaen.es/a"),
        _grado("Grado en Ingeniería Mecánica", "https://eps.ujaen.es/b"),
        _asig(),
    ]
    ruta = tmp_path / "grados.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    with pytest.raises(InvarianteRoto, match="Mecánica"):
        check_dataset.main([str(ruta)])

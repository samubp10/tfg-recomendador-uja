"""Pruebas de la rejilla del recuperador (IT-49).

Lo que hay que asegurar aquí es que el corte simulado **es el mismo** que el que
aplica el sistema. Si se separan, la rejilla elegiría los parámetros de otro
recuperador y nadie se enteraría: las cifras seguirían pareciendo razonables.
Por eso la prueba central compara las dos implementaciones sobre las mismas
listas en vez de comprobar la simulada por su cuenta.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "experimentos"))

import barrido_recuperador as barrido  # noqa: E402

from tfg_uja.dialogo.recuperador import Fragmento, acotar_por_distancia  # noqa: E402


def recuperados(distancias: list[float]) -> list[barrido.Recuperado]:
    """Lista simulada, ya ordenada, con una unidad distinta por fragmento."""
    return [
        barrido.Recuperado(f"unidad {i}", "guia", d) for i, d in enumerate(distancias)
    ]


def fragmentos(distancias: list[float]) -> list[Fragmento]:
    """La misma lista, en la estructura que usa el sistema."""
    return [
        Fragmento(
            texto="",
            nombre=f"unidad {i}",
            grados=[],
            origen="guia",
            distancia=d,
            chunk_index=0,
            total_chunks=1,
        )
        for i, d in enumerate(distancias)
    ]


LISTAS = [
    [0.10, 0.11, 0.115, 0.13, 0.20, 0.30],
    [0.05, 0.051, 0.052, 0.053, 0.054],
    [0.16, 0.17, 0.18],
    [0.142, 0.142, 0.9],
]


def test_el_corte_simulado_es_el_del_sistema():
    """La rejilla no puede optimizar un recuperador distinto del que se ejecuta."""
    for distancias in LISTAS:
        for config in barrido.rejilla()[::17]:
            simulado = barrido.acotar(recuperados(distancias), config)
            real = acotar_por_distancia(
                fragmentos(distancias),
                minimo=config.minimo,
                maximo=config.maximo,
                factor=config.factor,
                suelo=config.suelo,
            )
            assert [r.distancia for r in simulado] == [
                f.distancia for f in real
            ], f"discrepan con {config} sobre {distancias}"


def test_una_lista_vacia_no_devuelve_nada():
    config = barrido.Configuracion(3, 20, 1.20, 0.142)
    assert barrido.acotar([], config) == []


def test_por_encima_del_suelo_no_se_devuelve_nada():
    """Es la rama que rechaza lo ajeno al dominio, y el mínimo no la anula."""
    config = barrido.Configuracion(3, 20, 1.20, 0.142)
    assert barrido.acotar(recuperados([0.15, 0.16]), config) == []


def test_la_unidad_se_acierta_por_cualquiera_de_sus_fragmentos():
    """Para responder basta con alcanzar la asignatura, no todos sus trozos."""
    devueltos = recuperados([0.10, 0.11, 0.12])
    assert barrido.acierta_la_unidad(
        devueltos, [{"origen": "guia", "nombre": "unidad 2"}]
    )
    assert not barrido.acierta_la_unidad(
        devueltos, [{"origen": "guia", "nombre": "unidad 9"}]
    )


def test_el_origen_forma_parte_de_la_identidad_de_la_unidad():
    """Una guía y unas salidas pueden llamarse igual: son unidades distintas."""
    devueltos = recuperados([0.10])
    assert not barrido.acierta_la_unidad(
        devueltos, [{"origen": "salidas", "nombre": "unidad 0"}]
    )


def test_medir_cuenta_las_preguntas_sin_contexto():
    config = barrido.Configuracion(3, 20, 1.20, 0.142)
    dominio = [
        (recuperados([0.10, 0.11]), [{"origen": "guia", "nombre": "unidad 0"}]),
        (recuperados([0.90]), [{"origen": "guia", "nombre": "unidad 0"}]),
    ]
    medido = barrido.medir(config, dominio, [])
    assert medido["sin_contexto"] == 1
    assert medido["unidad"] == 0.5


def test_medir_cuenta_el_rechazo_de_lo_ajeno():
    config = barrido.Configuracion(3, 20, 1.20, 0.142)
    ajenas = [recuperados([0.90]), recuperados([0.10])]
    medido = barrido.medir(config, [], ajenas)
    assert medido["rechazo"] == 0.5


def test_la_rejilla_no_propone_un_minimo_mayor_que_el_maximo():
    for config in barrido.rejilla():
        assert config.minimo <= config.maximo


def test_la_configuracion_vigente_se_lee_del_modulo_y_no_de_una_copia():
    """El informe rotula esa fila como «la configuración de hoy», y tiene que serlo.

    Es una prueba de regresión con su caso real: el guion llevaba los cuatro
    valores escritos a mano y siguió presentando como vigente un suelo de 0,142
    después de que este mismo barrido lo bajara a 0,137.
    """
    from tfg_uja.dialogo import recuperador

    vigente = barrido.configuracion_vigente()

    assert (vigente.minimo, vigente.maximo, vigente.factor, vigente.suelo) == (
        recuperador.K_MINIMO,
        recuperador.K_MAXIMO,
        recuperador.FACTOR_CORTE,
        recuperador.SUELO_PERTINENCIA,
    )


# --- Preparación, informe y recorrido entero (IT-113) -----------------------

import json  # noqa: E402


def _evalset(n_dominio=2, n_ajenas=1):
    """Un conjunto de evaluación mínimo con las dos familias."""
    preguntas = [
        {
            "id": f"d{i}",
            "tipo": "temario",
            "pregunta": f"¿de qué va la unidad {i}?",
            "relevantes": [{"origen": "guia", "nombre": f"unidad {i}"}],
        }
        for i in range(n_dominio)
    ]
    preguntas += [
        {
            "id": f"a{i}",
            "tipo": barrido.FUERA_DE_DOMINIO,
            "pregunta": "¿y medicina?",
            "relevantes": [],
        }
        for i in range(n_ajenas)
    ]
    return preguntas


def _recuperar_falso(distancias):
    """Sustituto de `recuperar` que devuelve siempre la misma lista."""

    def falso(pregunta, tabla, incrustar, distancia, k):
        return fragmentos(distancias)

    return falso


def test_preparar_separa_las_ajenas_de_las_de_dominio(monkeypatch):
    """Las ajenas no llevan relevantes: su criterio es el contrario."""
    monkeypatch.setattr(barrido, "recuperar", _recuperar_falso([0.10, 0.20]))

    dominio, ajenas = _preparar(monkeypatch, _evalset(2, 3))

    assert len(dominio) == 2
    assert len(ajenas) == 3
    assert dominio[0][1] == [{"origen": "guia", "nombre": "unidad 0"}]


def _preparar(monkeypatch, preguntas):
    """Llama a `preparar` con un índice y un incrustador de mentira."""
    return barrido.preparar(
        preguntas, tabla=None, incrustar=None, distancia="cosine", vecinos=5
    )


def test_preparar_avisa_del_avance_cada_diez(monkeypatch, capsys):
    """Son 66 preguntas contra el índice: sin avance parece que se ha colgado."""
    monkeypatch.setattr(barrido, "recuperar", _recuperar_falso([0.10]))

    _preparar(monkeypatch, _evalset(10, 0))

    assert "recuperadas 10/10" in capsys.readouterr().out


def _fila(unidad=1.0, rechazo=0.8, fragmentos_=7.2, sin_contexto=0, suelo=0.137):
    """Una configuración ya medida, tal como la devuelve `medir`."""
    return {
        "minimo": 3,
        "maximo": 20,
        "factor": 1.20,
        "suelo": suelo,
        "unidad": unidad,
        "rechazo": rechazo,
        "fragmentos": fragmentos_,
        "sin_contexto": sin_contexto,
    }


def test_el_informe_declara_que_ese_rechazo_no_es_el_del_sistema(tmp_path, capsys):
    """El recuperador completo entrega contexto a las peticiones de consejo.

    La tabla de la memoria ya lo matizaba; el informe leído solo decía más de
    lo que se había medido.
    """
    destino = tmp_path / "it49.md"

    barrido.informe([_fila()], destino, _fila())

    texto = destino.read_text(encoding="utf-8")
    assert "aplicando solo el corte por distancia" in texto
    assert "No es el rechazo del sistema" in texto
    assert "Informe escrito en" in capsys.readouterr().out


def test_el_informe_pone_delante_la_configuracion_de_hoy(tmp_path):
    destino = tmp_path / "it49.md"

    barrido.informe([_fila(unidad=0.5)], destino, _fila(unidad=1.0))

    texto = destino.read_text(encoding="utf-8")
    assert "## La configuración de hoy" in texto
    assert "unidad **1.000**" in texto


def test_el_informe_separa_las_que_no_pierden_ninguna_pregunta(tmp_path):
    """La que deja una pregunta sin contexto no entra en la segunda tabla."""
    destino = tmp_path / "it49.md"

    barrido.informe(
        [_fila(sin_contexto=0, suelo=0.100), _fila(sin_contexto=3, suelo=0.200)],
        destino,
        _fila(),
    )

    texto = destino.read_text(encoding="utf-8")
    segunda = texto.split("## Las que no pierden ninguna pregunta de dominio")[1]
    assert "0.100" in segunda
    assert "0.200" not in segunda


def test_el_informe_dice_que_no_lo_escribe_nadie_a_mano(tmp_path):
    destino = tmp_path / "it49.md"

    barrido.informe([_fila()], destino, _fila())

    assert "**No editar a mano.**" in destino.read_text(encoding="utf-8")


def test_main_recorre_la_rejilla_entera(tmp_path, monkeypatch, capsys):
    """Sin llamar a ningún modelo: los tres parámetros solo cortan una lista."""
    monkeypatch.setattr(barrido, "recuperar", _recuperar_falso([0.10, 0.15, 0.30]))
    monkeypatch.setattr(barrido, "abrir_indice", lambda ruta, modelo: None)
    monkeypatch.setattr(barrido, "incrustador_de_consultas", lambda modelo: None)
    monkeypatch.setattr(barrido, "distancia_del_indice", lambda ruta: "cosine")

    evalset = tmp_path / "evalset.json"
    evalset.write_text(json.dumps({"preguntas": _evalset()}), encoding="utf-8")
    salida = tmp_path / "sub" / "it49.md"

    barrido.main(
        [
            "--evalset",
            str(evalset),
            "--indice",
            str(tmp_path),
            "--salida",
            str(salida),
        ]
    )

    texto = salida.read_text(encoding="utf-8")
    assert f"Configuraciones probadas: **{len(barrido.rejilla())}**" in texto
    assert "2 preguntas de dominio, 1 ajenas" in capsys.readouterr().out


def test_main_admite_un_evalset_que_sea_una_lista(tmp_path, monkeypatch):
    """El fichero ha tenido las dos formas; se aceptan las dos."""
    monkeypatch.setattr(barrido, "recuperar", _recuperar_falso([0.10]))
    monkeypatch.setattr(barrido, "abrir_indice", lambda ruta, modelo: None)
    monkeypatch.setattr(barrido, "incrustador_de_consultas", lambda modelo: None)
    monkeypatch.setattr(barrido, "distancia_del_indice", lambda ruta: "cosine")

    evalset = tmp_path / "evalset.json"
    evalset.write_text(json.dumps(_evalset(1, 0)), encoding="utf-8")
    salida = tmp_path / "it49.md"

    barrido.main(
        ["--evalset", str(evalset), "--indice", str(tmp_path), "--salida", str(salida)]
    )

    assert salida.exists()

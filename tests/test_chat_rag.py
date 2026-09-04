"""Pruebas del chat de consola (IT-113).

El cliente de consola llevaba 669 líneas sin una sola prueba. No es código
accesorio: es el único cliente del sistema hasta la Fase 3 y es con el que se
produjeron las sesiones de prueba que documentan el comportamiento del
recomendador.

**Ninguna prueba levanta el servidor de inferencia ni abre el índice real.** El
guion ya estaba partido en piezas que se pueden llamar sueltas ---atender una
orden, recuperar, generar, mostrar, anotar---, así que basta con darles de
comer objetos falsos. Donde hace falta el índice se sustituye la función que lo
abre, que es la única que lo toca.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

import chat_rag as chat  # noqa: E402

from tfg_uja.dialogo.conversacion import Conversacion  # noqa: E402
from tfg_uja.dialogo.generador import ErrorDelModelo  # noqa: E402
from tfg_uja.dialogo.recuperador import (  # noqa: E402
    Fragmento,
    ModeloDiscrepante,
    TitulacionDesconocida,
)

#: El catálogo **real** de la EPSJ, las doce titulaciones del corpus.
#:
#: No es adorno: una palabra es distintiva si aparece en menos de la mitad de
#: los nombres del catálogo, así que con un catálogo de dos **ninguna** lo es y
#: la conversación no deduce jamás el sujeto. Un catálogo de juguete deja estas
#: pruebas en verde midiendo un sistema que no existe.
CATALOGO = [
    "Doble Grado en Ingeniería Electrónica Industrial y Mecánica",
    "Doble Grado en Ingeniería Eléctrica y Electrónica Industrial",
    "Doble Grado en Ingeniería Eléctrica y Mecánica",
    "Doble Grado en Ingeniería Mecánica y Organización Industrial",
    "Grado en Ingeniería Electrónica Industrial",
    "Grado en Ingeniería Eléctrica",
    "Grado en Ingeniería Geomática y Topográfica (plan 2025)",
    "Grado en Ingeniería Informática",
    "Grado en Ingeniería Mecánica",
    "Grado en Ingeniería de Organización Industrial",
    "Grado en Inteligencia Artificial y Ciberseguridad",
]


def frag(
    nombre: str = "Cálculo",
    origen: str = "guia",
    distancia: float = 0.1,
    indice: int = 0,
    total: int = 1,
) -> Fragmento:
    """Un fragmento cualquiera, con lo justo para citarlo.

    Args:
        nombre: Unidad a la que pertenece.
        origen: De dónde salió.
        distancia: Distancia a la consulta.
        indice: Posición dentro de su unidad, desde 0.
        total: En cuántos fragmentos se partió la unidad.

    Returns:
        El fragmento.
    """
    return Fragmento(
        texto="texto",
        nombre=nombre,
        grados=["Grado en Ingeniería Informática"],
        origen=origen,
        distancia=distancia,
        chunk_index=indice,
        total_chunks=total,
        curso="Primer curso",
    )


class TablaFalsa:
    """Lo único que el chat le pide a la tabla del índice es contar filas."""

    def count_rows(self) -> int:
        """Devuelve un tamaño de índice cualquiera."""
        return 1499


def indice_falso(catalogo: list[str] | None = None) -> chat.Indice:
    """Un índice ya abierto, sin abrir nada.

    Args:
        catalogo: Titulaciones que declara, o las de siempre.

    Returns:
        El índice falso.
    """
    return chat.Indice(
        tabla=TablaFalsa(),
        incrustar=lambda texto: [0.0],
        distancia="cosine",
        catalogo=list(CATALOGO if catalogo is None else catalogo),
    )


def ajustes_de_prueba(**cambios: object) -> chat.Ajustes:
    """Ajustes con los valores por defecto del chat, salvo los que se cambien.

    Args:
        **cambios: Atributos que se quieren distintos.

    Returns:
        Los ajustes.
    """
    base = {"modelo": "gemma3:12b", "k": 20, "grado": None, "curso": None}
    base.update(cambios)
    return chat.Ajustes(**base)  # type: ignore[arg-type]


# --- El ámbito que se le declara al prompt ---------------------------------


@pytest.mark.parametrize(
    "ambito, esperado",
    [
        ([], None),
        (["Grado en Ingeniería Informática"], "Grado en Ingeniería Informática"),
    ],
)
def test_el_prompt_declara_la_titulacion_solo_si_es_una(
    ambito: list[str], esperado: str | None
) -> None:
    """Con cero titulaciones no hay nada que declarar; con una, se declara."""
    assert chat._uno_solo(ambito) == esperado


def test_con_varias_titulaciones_el_prompt_no_declara_ninguna() -> None:
    """«electrónica» sitúa en tres: decirle «responde sobre estas tres» no acota.

    Quien acota entonces es el filtro, que sí admite la lista entera.
    """
    assert chat._uno_solo(CATALOGO) is None


# --- Las fuentes que se enseñan --------------------------------------------


def test_las_fuentes_no_repiten_una_unidad() -> None:
    """Una unidad partida en varios fragmentos se cita una sola vez."""
    salida = chat.formatear_fuentes(
        [
            frag(indice=0, total=3, distancia=0.10),
            frag(indice=1, total=3, distancia=0.20),
            frag(nombre="Física", distancia=0.30),
        ]
    )

    assert salida.count("Cálculo") == 1
    assert "Física" in salida


def test_de_una_unidad_repetida_se_cita_la_distancia_mas_proxima() -> None:
    """Se queda la primera, y la lista llega ordenada de más a menos próxima."""
    salida = chat.formatear_fuentes([frag(distancia=0.10), frag(distancia=0.90)])

    assert "0.100" in salida
    assert "0.900" not in salida


def test_sin_fragmentos_las_fuentes_salen_vacias() -> None:
    assert chat.formatear_fuentes([]) == ""


# --- El registro de la sesión ----------------------------------------------


def test_abrir_registro_crea_la_carpeta_y_la_cabecera(tmp_path: Path) -> None:
    """La carpeta puede no existir: es la primera sesión de la máquina."""
    ruta = chat.abrir_registro(tmp_path / "nueva", "gemma3:12b", 20, 1499)

    texto = ruta.read_text(encoding="utf-8")
    assert ruta.parent.name == "nueva"
    assert "# Sesión de pruebas del chat RAG" in texto
    assert "`gemma3:12b`" in texto
    assert "1499 fragmentos · K = 20" in texto


def test_el_nombre_del_registro_no_lleva_dos_puntos(tmp_path: Path) -> None:
    """Windows no admite «:» en un nombre de fichero, y el modelo lo lleva."""
    ruta = chat.abrir_registro(tmp_path, "gemma3:12b", 20, 1499)

    assert ":" not in ruta.name
    assert "gemma3-12b" in ruta.name


def test_anotar_turno_conserva_lo_ya_escrito(tmp_path: Path) -> None:
    """Se escribe turno a turno para que una sesión cortada no se pierda."""
    ruta = chat.abrir_registro(tmp_path, "gemma3:12b", 20, 1499)

    chat.anotar_turno(
        ruta,
        1,
        "¿y el temario?",
        "Pues esto.",
        [frag()],
        "gemma3:12b",
        None,
        (1.0, 2.0),
    )
    chat.anotar_turno(
        ruta, 2, "¿y las salidas?", "Y esto.", [], "gemma3:12b", None, (0.5, 1.5)
    )

    texto = ruta.read_text(encoding="utf-8")
    assert "## Turno 1" in texto
    assert "## Turno 2" in texto
    assert texto.index("Turno 1") < texto.index("Turno 2")


def test_el_turno_anota_el_acotado_solo_si_lo_habia(tmp_path: Path) -> None:
    ruta = chat.abrir_registro(tmp_path, "gemma3:12b", 20, 1499)

    chat.anotar_turno(
        ruta,
        1,
        "p",
        "r",
        [frag()],
        "gemma3:12b",
        "Grado en Ingeniería Mecánica",
        (1.0, 2.0),
    )
    con = ruta.read_text(encoding="utf-8")

    chat.anotar_turno(ruta, 2, "p", "r", [frag()], "gemma3:12b", None, (1.0, 2.0))
    entero = ruta.read_text(encoding="utf-8")

    assert "acotado a «Grado en Ingeniería Mecánica»" in con
    assert entero.count("acotado a") == 1


def test_el_turno_anota_la_parte_de_la_unidad_desde_uno(tmp_path: Path) -> None:
    """El fragmento 0 de 3 se enseña como «1/3»: contar desde cero es de dentro."""
    ruta = chat.abrir_registro(tmp_path, "gemma3:12b", 20, 1499)

    chat.anotar_turno(
        ruta, 1, "p", "r", [frag(indice=0, total=3)], "gemma3:12b", None, (1.0, 2.0)
    )

    assert "| 1/3 |" in ruta.read_text(encoding="utf-8")


# --- Las opciones de la línea de órdenes ------------------------------------


def test_el_chat_arranca_con_el_modelo_del_sistema() -> None:
    """No con el que hubiera a mano: si no, no ejecuta el sistema que se mide."""
    assert chat._analizar_argumentos([]).modelo == "gemma3:12b"


def test_las_opciones_se_leen() -> None:
    opciones = chat._analizar_argumentos(
        [
            "--modelo",
            "otro:8b",
            "--k",
            "5",
            "--grado",
            "X",
            "--curso",
            "primer",
            "--k-fijo",
        ]
    )

    assert (opciones.modelo, opciones.k, opciones.grado) == ("otro:8b", 5, "X")
    assert opciones.curso == "primer"
    assert opciones.k_fijo


def test_el_ambito_lo_decide_el_modelo_salvo_que_se_pida_lo_contrario() -> None:
    assert not chat._analizar_argumentos([]).ambito_determinista
    assert chat._analizar_argumentos(["--ambito-determinista"]).ambito_determinista


# --- El decisor de ámbito ---------------------------------------------------


def test_el_decisor_usa_el_modelo_que_haya_puesto_ahora(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/modelo` cambia el generativo sin reiniciar.

    Con el decisor construido al arrancar se seguiría decidiendo con el modelo
    anterior, y la sesión estaría comparando dos cosas a la vez sin decirlo.
    """
    usados: list[str] = []
    monkeypatch.setattr(
        chat,
        "decisor_con_modelo",
        lambda catalogo, modelo: (usados.append(modelo) or (lambda *a: [])),
    )
    ajustes = ajustes_de_prueba()
    decidir = chat._decisor_del_chat(indice_falso(), ajustes)

    decidir("una", [], None)
    ajustes.modelo = "otro:8b"
    decidir("otra", [], None)

    assert usados == ["gemma3:12b", "otro:8b"]


# --- La apertura del índice -------------------------------------------------


def test_sin_indice_el_chat_dice_como_construirlo(tmp_path: Path) -> None:
    """Se termina el programa en vez de propagar: sin índice no hay chat."""
    with pytest.raises(SystemExit, match="tfg_uja.indexacion.indexer"):
        chat._preparar_indice(tmp_path / "no-esta")


def test_si_el_indice_no_casa_con_el_modelo_se_dice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Buscar con un modelo distinto del que indexó devuelve vecinos al azar."""
    tmp_path.joinpath("indice").mkdir()
    monkeypatch.setattr(chat, "incrustador_de_consultas", lambda modelo: None)
    monkeypatch.setattr(
        chat,
        "abrir_indice",
        lambda ruta, modelo: (_ for _ in ()).throw(ModeloDiscrepante("otro modelo")),
    )

    with pytest.raises(SystemExit, match="no casa con el modelo"):
        chat._preparar_indice(tmp_path / "indice")


def test_un_indice_sin_catalogo_no_sirve_para_conversar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin catálogo no hay de qué decidir el ámbito.

    Tampoco se puede avisar de que una titulación no está.
    """
    tmp_path.joinpath("indice").mkdir()
    monkeypatch.setattr(chat, "incrustador_de_consultas", lambda modelo: None)
    monkeypatch.setattr(chat, "abrir_indice", lambda ruta, modelo: TablaFalsa())
    monkeypatch.setattr(chat, "catalogo_del_indice", lambda ruta: [])

    with pytest.raises(SystemExit, match="catálogo"):
        chat._preparar_indice(tmp_path / "indice")


def test_el_indice_abierto_trae_catalogo_y_distancia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.joinpath("indice").mkdir()
    monkeypatch.setattr(chat, "incrustador_de_consultas", lambda modelo: "incrustador")
    monkeypatch.setattr(chat, "abrir_indice", lambda ruta, modelo: TablaFalsa())
    monkeypatch.setattr(chat, "catalogo_del_indice", lambda ruta: CATALOGO)
    monkeypatch.setattr(chat, "distancia_del_indice", lambda ruta: "cosine")

    indice = chat._preparar_indice(tmp_path / "indice")

    assert indice.catalogo == CATALOGO
    assert indice.distancia == "cosine"
    assert indice.incrustar == "incrustador"


# --- La cabecera ------------------------------------------------------------


def test_la_cabecera_dice_que_el_ambito_lo_decide_el_modelo(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Lo dice porque cuesta segundos por turno y van dentro de «recuperar»."""
    chat._imprimir_cabecera(
        tmp_path, indice_falso(), ajustes_de_prueba(), False, tmp_path / "s.md", True
    )

    salida = capsys.readouterr().out
    assert "lo decide el modelo en cada turno" in salida
    assert "dinámicos, hasta 20" in salida
    assert "Registro: " in salida


def test_la_cabecera_dice_cuando_el_ambito_es_determinista(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    chat._imprimir_cabecera(
        tmp_path,
        indice_falso(),
        ajustes_de_prueba(grado="Grado en Ingeniería Mecánica"),
        True,
        None,
        False,
    )

    salida = capsys.readouterr().out
    assert "reglas deterministas" in salida
    assert "K fijo = 20" in salida
    assert "Registro: desactivado" in salida
    assert "acotado a «Grado en Ingeniería Mecánica»" in salida


# --- Las órdenes ------------------------------------------------------------


def test_salir_termina_la_sesion() -> None:
    assert chat._atender_orden(
        "/salir", ajustes_de_prueba(), Conversacion(CATALOGO), []
    )


@pytest.mark.parametrize(
    "orden, atributo, esperado",
    [
        ("/modelo otro:8b", "modelo", "otro:8b"),
        ("/k 7", "k", 7),
        (
            "/grado Grado en Ingeniería Mecánica",
            "grado",
            "Grado en Ingeniería Mecánica",
        ),
        ("/curso primer", "curso", "primer"),
    ],
)
def test_una_orden_cambia_su_ajuste(
    orden: str, atributo: str, esperado: object
) -> None:
    ajustes = ajustes_de_prueba()

    assert not chat._atender_orden(orden, ajustes, Conversacion(CATALOGO), [])
    assert getattr(ajustes, atributo) == esperado


@pytest.mark.parametrize(
    "orden, atributo", [("/grado .", "grado"), ("/curso .", "curso")]
)
def test_un_punto_quita_el_acotado(orden: str, atributo: str) -> None:
    """Hace falta una manera de desacotar sin reiniciar la sesión."""
    ajustes = ajustes_de_prueba(grado="X", curso="primer")

    chat._atender_orden(orden, ajustes, Conversacion(CATALOGO), [])

    assert getattr(ajustes, atributo) is None


def test_una_k_que_no_es_un_numero_no_cambia_nada(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Se enseña la ayuda en vez de reventar con un ValueError."""
    ajustes = ajustes_de_prueba()

    chat._atender_orden("/k muchas", ajustes, Conversacion(CATALOGO), [])

    assert ajustes.k == 20
    assert "órdenes:" in capsys.readouterr().out


def test_fuentes_sin_haber_preguntado_lo_dice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    chat._atender_orden("/fuentes", ajustes_de_prueba(), Conversacion(CATALOGO), [])

    assert "(aún no hay)" in capsys.readouterr().out


def test_fuentes_enseña_las_del_ultimo_turno(
    capsys: pytest.CaptureFixture[str],
) -> None:
    chat._atender_orden(
        "/fuentes", ajustes_de_prueba(), Conversacion(CATALOGO), [frag()]
    )

    assert "Cálculo" in capsys.readouterr().out


def test_olvida_vacia_la_conversacion(capsys: pytest.CaptureFixture[str]) -> None:
    conversacion = Conversacion(CATALOGO)
    conversacion.anotar("¿qué se estudia en Informática?", "Pues esto.")

    chat._atender_orden("/olvida", ajustes_de_prueba(), conversacion, [])

    assert conversacion.ambito == []
    assert conversacion.preguntas() == []
    assert "olvidada" in capsys.readouterr().out


def test_ambito_dice_de_que_se_habla(capsys: pytest.CaptureFixture[str]) -> None:
    conversacion = Conversacion(CATALOGO)
    chat._atender_orden("/ambito", ajustes_de_prueba(), conversacion, [])
    assert "todavía nada" in capsys.readouterr().out

    conversacion.anotar("¿qué se estudia en Ingeniería Informática?", "Pues esto.")
    chat._atender_orden("/ambito", ajustes_de_prueba(), conversacion, [])
    assert "Informática" in capsys.readouterr().out


def test_una_orden_que_no_existe_enseña_la_ayuda(
    capsys: pytest.CaptureFixture[str],
) -> None:
    chat._atender_orden("/inventada", ajustes_de_prueba(), Conversacion(CATALOGO), [])

    assert "órdenes:" in capsys.readouterr().out


# --- La recuperación --------------------------------------------------------


def test_con_k_fijo_se_traen_siempre_k_fragmentos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--k-fijo` salta el recorte por distancia: es para mirar qué hay ahí abajo."""
    llamadas: list[str] = []
    monkeypatch.setattr(
        chat, "recuperar", lambda *a, **kw: (llamadas.append("recuperar"), [frag()])[1]
    )
    monkeypatch.setattr(
        chat,
        "contexto_para",
        lambda *a, **kw: (llamadas.append("contexto_para"), [])[1],
    )

    resultado = chat._recuperar_contexto(
        "¿temario?", Conversacion(CATALOGO), ajustes_de_prueba(), indice_falso(), True
    )

    assert llamadas == ["recuperar"]
    assert resultado is not None and len(resultado[0]) == 1


def test_sin_k_fijo_se_recorta_por_distancia(monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas: list[str] = []
    monkeypatch.setattr(
        chat, "recuperar", lambda *a, **kw: llamadas.append("recuperar")
    )
    monkeypatch.setattr(
        chat,
        "contexto_para",
        lambda *a, **kw: (llamadas.append("contexto_para"), [frag()])[1],
    )

    chat._recuperar_contexto(
        "¿temario?", Conversacion(CATALOGO), ajustes_de_prueba(), indice_falso(), False
    )

    assert llamadas == ["contexto_para"]


def test_una_titulacion_que_no_existe_enseña_las_que_hay(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Se avisa y se sigue preguntando: no es motivo para terminar la sesión."""
    monkeypatch.setattr(
        chat,
        "contexto_para",
        lambda *a, **kw: (_ for _ in ()).throw(
            TitulacionDesconocida("«Medicina» no está")
        ),
    )

    resultado = chat._recuperar_contexto(
        "¿y en Medicina?",
        Conversacion(CATALOGO),
        ajustes_de_prueba(),
        indice_falso(),
        False,
    )

    salida = capsys.readouterr().out
    assert resultado is None
    assert "Grado en Ingeniería Informática" in salida


# --- La generación ----------------------------------------------------------


def test_la_respuesta_se_pide_con_el_ambito_de_la_conversacion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recibido: dict[str, object] = {}

    def falso(pregunta, fragmentos, modelo, historial, ambito, catalogo):
        recibido.update(ambito=ambito, modelo=modelo)
        return "una respuesta"

    monkeypatch.setattr(chat, "responder", falso)

    salida = chat._generar_respuesta(
        "¿temario?",
        [frag()],
        ajustes_de_prueba(),
        Conversacion(CATALOGO),
        CATALOGO,
        [CATALOGO[0]],
    )

    assert salida == "una respuesta"
    assert recibido["ambito"] == CATALOGO[0]


def test_el_grado_puesto_a_mano_manda_sobre_el_deducido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el usuario ha escrito `/grado`, no se le lleva la contraria."""
    recibido: dict[str, object] = {}
    monkeypatch.setattr(
        chat,
        "responder",
        lambda p, f, m, h, ambito, catalogo: recibido.update(ambito=ambito) or "r",
    )

    chat._generar_respuesta(
        "¿temario?",
        [frag()],
        ajustes_de_prueba(grado="Grado en Ingeniería Mecánica"),
        Conversacion(CATALOGO),
        CATALOGO,
        [CATALOGO[0]],
    )

    assert recibido["ambito"] == "Grado en Ingeniería Mecánica"


def test_un_fallo_del_servidor_no_se_lleva_la_sesion(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un 500 por falta de memoria costaba la conversación entera."""
    monkeypatch.setattr(
        chat,
        "responder",
        lambda *a, **kw: (_ for _ in ()).throw(ErrorDelModelo("500 del servidor")),
    )

    salida = chat._generar_respuesta(
        "¿temario?", [frag()], ajustes_de_prueba(), Conversacion(CATALOGO), CATALOGO, []
    )

    assert salida is None
    assert "puedes repetirla" in capsys.readouterr().out


def test_cortar_una_respuesta_lenta_cancela_la_pregunta_no_la_sesion(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Los modelos grandes tardan minutos; rearrancar obliga a recargar el índice."""
    monkeypatch.setattr(
        chat, "responder", lambda *a, **kw: (_ for _ in ()).throw(KeyboardInterrupt())
    )

    salida = chat._generar_respuesta(
        "¿temario?", [frag()], ajustes_de_prueba(), Conversacion(CATALOGO), CATALOGO, []
    )

    assert salida is None
    assert "cancelada" in capsys.readouterr().out


# --- Lo que se ve en pantalla -----------------------------------------------


def test_la_respuesta_se_enseña_con_sus_tiempos_y_sus_fuentes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    chat._mostrar_respuesta("Pues esto.", ajustes_de_prueba(), [frag()], (1.25, 9.5))

    salida = capsys.readouterr().out
    assert "Pues esto." in salida
    assert "recuperar 1.25 s" in salida
    assert "generar 9.50 s" in salida
    assert "Cálculo" in salida


# --- Que estas pruebas midan algo -------------------------------------------


def test_el_catalogo_de_las_pruebas_tiene_palabras_distintivas() -> None:
    """Sin esto, media docena de pruebas de arriba pasarían midiendo nada.

    Una palabra es distintiva si aparece en menos de la mitad de los nombres
    del catálogo. Con un catálogo de dos no lo es ninguna, la conversación no
    deduce nunca el sujeto y las pruebas que dependen de ello quedan en verde
    sobre un sistema que no se parece al real.
    """
    from tfg_uja.dialogo.recuperador import palabras_distintivas

    distintivas = palabras_distintivas(CATALOGO)

    assert len(CATALOGO) >= 11, len(CATALOGO)
    assert "informatica" in distintivas, sorted(distintivas)


# --- El bucle del chat ------------------------------------------------------


def preparar_main(
    monkeypatch: pytest.MonkeyPatch,
    entradas: list[str],
    *,
    fragmentos: list[Fragmento] | None = None,
    respuesta: str | None = "Pues esto.",
    contexto_none: bool = False,
    fija: str | None = None,
) -> None:
    """Deja `main` listo para correr sin índice, sin modelo y sin teclado.

    Se sustituyen las cuatro piezas que salen del proceso ---abrir el índice,
    leer del teclado, recuperar y generar---. El resto del bucle es el que se
    quiere medir, así que se ejecuta de verdad.

    Args:
        monkeypatch: Parcheador de pytest.
        entradas: Lo que se «teclea», en orden. Al agotarse se corta la sesión.
        fragmentos: Contexto que devuelve la recuperación.
        respuesta: Lo que contesta el modelo, o ``None`` para simular un fallo.
        contexto_none: Si la recuperación se rinde (titulación desconocida).
        fija: Respuesta de cortesía, si la pregunta la merece.
    """
    pendientes = list(entradas)

    def teclear(_=""):
        if not pendientes:
            raise EOFError
        return pendientes.pop(0)

    monkeypatch.setattr("builtins.input", teclear)
    monkeypatch.setattr(chat, "_preparar_indice", lambda ruta: indice_falso())
    monkeypatch.setattr(chat, "cortesia", lambda entrada: fija)
    monkeypatch.setattr(
        chat,
        "_recuperar_contexto",
        lambda *a: None if contexto_none else (fragmentos or [frag()], [CATALOGO[7]]),
    )
    monkeypatch.setattr(chat, "_generar_respuesta", lambda *a: respuesta)


def test_el_chat_responde_y_deja_el_turno_anotado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    preparar_main(monkeypatch, ["¿qué se estudia en Informática?"])

    chat.main(["--registro", str(tmp_path)])

    salida = capsys.readouterr().out
    sesion = next(tmp_path.glob("sesion_*.md")).read_text(encoding="utf-8")
    assert "Pues esto." in salida
    assert "## Turno 1" in sesion
    assert "¿qué se estudia en Informática?" in sesion


def test_una_linea_en_blanco_no_gasta_un_turno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dar al intro sin escribir nada es lo más fácil del mundo."""
    preparar_main(monkeypatch, ["", "   ", "¿y el temario?"])

    chat.main(["--registro", str(tmp_path)])

    sesion = next(tmp_path.glob("sesion_*.md")).read_text(encoding="utf-8")
    assert sesion.count("## Turno") == 1


def test_la_cortesia_se_responde_sin_buscar_nada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """El registro anotaba veinte fragmentos para un «gracias» que no usó ninguno.

    Una sesión que documenta un contexto que no existió no sirve para auditar.
    """
    preparar_main(monkeypatch, ["gracias"], fija="De nada.")

    chat.main(["--registro", str(tmp_path)])

    sesion = next(tmp_path.glob("sesion_*.md")).read_text(encoding="utf-8")
    assert "De nada." in capsys.readouterr().out
    assert "(0 fragmentos)" in sesion


def test_salir_cierra_la_sesion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preparar_main(monkeypatch, ["/salir", "¿esto ya no se pregunta?"])

    chat.main(["--registro", str(tmp_path)])

    sesion = next(tmp_path.glob("sesion_*.md")).read_text(encoding="utf-8")
    assert "## Turno" not in sesion


def test_una_orden_no_cuenta_como_turno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preparar_main(monkeypatch, ["/k 5", "¿y el temario?"])

    chat.main(["--registro", str(tmp_path)])

    sesion = next(tmp_path.glob("sesion_*.md")).read_text(encoding="utf-8")
    assert sesion.count("## Turno") == 1
    assert "## Turno 1" in sesion


def test_una_titulacion_desconocida_no_gasta_turno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Se avisó por pantalla y se sigue preguntando."""
    preparar_main(monkeypatch, ["¿y en Medicina?"], contexto_none=True)

    chat.main(["--registro", str(tmp_path)])

    sesion = next(tmp_path.glob("sesion_*.md")).read_text(encoding="utf-8")
    assert "## Turno" not in sesion


def test_un_fallo_al_generar_no_gasta_turno(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La pregunta se puede repetir, así que no se anota como respondida."""
    preparar_main(monkeypatch, ["¿y el temario?"], respuesta=None)

    chat.main(["--registro", str(tmp_path)])

    sesion = next(tmp_path.glob("sesion_*.md")).read_text(encoding="utf-8")
    assert "## Turno" not in sesion


def test_sin_registro_no_se_escribe_nada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preparar_main(monkeypatch, ["¿y el temario?"])

    chat.main(["--sin-registro", "--registro", str(tmp_path)])

    assert list(tmp_path.glob("sesion_*.md")) == []


def test_cortar_con_ctrl_c_cierra_la_sesion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ctrl+C en el prompt termina; durante la generación solo cancela."""

    def teclear(_=""):
        raise KeyboardInterrupt

    preparar_main(monkeypatch, [])
    monkeypatch.setattr("builtins.input", teclear)

    chat.main(["--registro", str(tmp_path)])

    sesion = next(tmp_path.glob("sesion_*.md")).read_text(encoding="utf-8")
    assert "## Turno" not in sesion


def test_con_ambito_determinista_no_se_le_pregunta_al_modelo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    preparar_main(monkeypatch, ["¿y el temario?"])

    chat.main(["--ambito-determinista", "--registro", str(tmp_path)])

    assert "reglas deterministas" in capsys.readouterr().out

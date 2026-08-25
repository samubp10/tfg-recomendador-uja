"""Pruebas de la generación de la respuesta (IT-37).

Sin red y sin modelo: la llamada al servidor se sustituye por un doble que
anota lo que se le envía. Lo que se comprueba aquí no es lo que responde un
modelo ---eso lo mide IT-38 con métricas, no una prueba booleana--- sino que
el prompt lleva lo que tiene que llevar y que los parámetros que hacen la
ejecución reproducible viajan de verdad en la petición.
"""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from tfg_uja import generador
from tfg_uja.generador import (
    AVISO_RESPUESTA_CORTADA,
    INSTRUCCIONES,
    RESPUESTA_DESPEDIDA,
    RESPUESTA_SALUDO,
    RESPUESTA_SIN_CONTEXTO,
    RESPUESTA_TITULACION_INVENTADA,
    TOPE_RESPUESTA,
    VENTANA,
    cerrar_en_frase_completa,
    cierre_de_conversacion,
    construir_prompt,
    cortesia,
    cortesia_sin_contexto,
    generar,
    responder,
)
from tfg_uja.recuperador import Fragmento


def fragmento(
    nombre: str,
    texto: str,
    grados: list[str] | None = None,
    distancia: float = 0.1,
    parte: int = 0,
    total: int = 1,
    origen: str = "guia",
) -> Fragmento:
    return Fragmento(
        texto=texto,
        nombre=nombre,
        grados=grados or ["Grado en Ingeniería Informática"],
        origen=origen,
        distancia=distancia,
        chunk_index=parte,
        total_chunks=total,
    )


# --- El prompt ---


def test_el_contexto_identifica_cada_fragmento():
    """Sin la etiqueta, el modelo recibe textos seguidos sin saber de quién son.

    Atribuir el temario de una asignatura a otra es el defecto que la
    fragmentación evita desde la Fase 1; el prompt no puede reintroducirlo.
    """
    prompt = construir_prompt(
        "¿qué se ve en Álgebra?",
        [fragmento("Álgebra", "Matrices y determinantes.")],
    )
    assert "Álgebra" in prompt
    assert "Grado en Ingeniería Informática" in prompt
    assert "Matrices y determinantes." in prompt


def test_los_fragmentos_conservan_su_orden_en_el_contexto():
    prompt = construir_prompt(
        "una pregunta",
        [fragmento("Primera", "texto uno"), fragmento("Segunda", "texto dos")],
    )
    assert prompt.index("Primera") < prompt.index("Segunda")


def test_el_contexto_no_numera_los_fragmentos():
    """Regresión: el número de fragmento se escapó a la respuesta.

    El encabezado llevaba «[1]», «[2]»... para que el modelo pudiera citar. No
    citó fragmentos ---las instrucciones le piden citar la asignatura--- y en
    cambio le soltó a un estudiante «...según el contexto ([20])», que es una
    referencia interna y no significa nada para quien la lee. Tercera vez que
    un dato puesto en el encabezado acaba en la pantalla del usuario, así que
    se quita de raíz: lo que no está en el prompt no se puede filtrar.
    """
    prompt = construir_prompt(
        "una pregunta",
        [fragmento(f"Unidad {i}", "texto") for i in range(1, 4)],
    )
    for numero in range(1, 4):
        assert f"[{numero}]" not in prompt


def test_una_guia_compartida_declara_sus_titulaciones():
    """Las listas paralelas del corpus llegan hasta el prompt, no se pierden."""
    prompt = construir_prompt(
        "una pregunta",
        [fragmento("Compartida", "texto", ["Grado A", "Doble Grado A y B"])],
    )
    assert "Grado A, Doble Grado A y B" in prompt


def test_sin_fragmentos_el_prompt_lo_dice_explicitamente():
    """El caso que más importa: recuperación vacía.

    Es donde un sistema RAG alucina peor, porque responde con la seguridad de
    siempre sobre algo que no ha leído.
    """
    prompt = construir_prompt("¿qué se ve en Álgebra?", [])
    assert "no se ha recuperado ningún fragmento" in prompt


# --- La conversación previa ---


def test_las_preguntas_anteriores_entran_en_el_prompt():
    """Sin ellas, «¿y en primer año?» no sabe de qué titulación se hablaba."""
    prompt = construir_prompt(
        "¿y en primer año?",
        [fragmento("Álgebra", "temario")],
        [("háblame de Informática", "es una carrera de cuatro años")],
    )
    assert "háblame de Informática" in prompt


def test_las_respuestas_anteriores_no_entran_en_el_prompt():
    """Regresión del turno 13 del 17/08/2026.

    Preguntado por los dobles grados, el modelo cerró su respuesta con «En el
    primer curso de todos los títulos mencionados se imparte Matemáticas I»,
    copiada literalmente de su propia respuesta dos turnos antes y sin relación
    con lo que se le preguntaba. La regla que lo prohibía llevaba escrita en
    las instrucciones desde el principio.

    Lo que no está en el prompt no se puede copiar.
    """
    inventado = "TEXTO-QUE-DIJO-EL-MODELO"
    prompt = construir_prompt(
        "otra pregunta",
        [fragmento("Álgebra", "temario real")],
        [("antes", inventado)],
    )
    assert inventado not in prompt
    assert "antes" in prompt


def test_las_preguntas_anteriores_van_separadas_del_contexto():
    """Al mismo nivel que los fragmentos se leerían como parte del corpus."""
    prompt = construir_prompt(
        "otra pregunta",
        [fragmento("Álgebra", "temario real")],
        [("antes", "algo")],
    )
    assert prompt.index("PREGUNTAS ANTERIORES DEL ESTUDIANTE:") < prompt.index(
        "CONTEXTO:"
    )


def test_sin_historial_el_prompt_no_cambia():
    """Lo habitual sigue siendo una pregunta suelta: no puede llevar peaje.

    Se busca el rótulo con sus dos puntos, que solo aparece encabezando el
    bloque; sin ellos casaría también con la regla de las instrucciones que
    habla de las preguntas anteriores, y la prueba pasaría por el motivo malo.
    """
    sin = construir_prompt("una pregunta", [fragmento("A", "t")])
    vacio = construir_prompt("una pregunta", [fragmento("A", "t")], [])
    assert sin == vacio
    assert "PREGUNTAS ANTERIORES DEL ESTUDIANTE:" not in sin


# --- El orden y la integridad del contexto ---


def test_las_partes_de_una_unidad_viajan_juntas_y_en_orden():
    """Regresión del caso real: el listado del plan llegaba 3, optativas, 2, 1.

    La respuesta reproducía ese orden ---empezaba por la mitad de la lista y
    volvía al principio más abajo--- porque el modelo redacta siguiendo el
    orden en que recibe el contexto.
    """
    recuperados = [
        fragmento("Obligatorias", "TEXTO-C", distancia=0.105, parte=2, total=3),
        fragmento("Optativas", "TEXTO-D", distancia=0.107),
        fragmento("Obligatorias", "TEXTO-B", distancia=0.109, parte=1, total=3),
        fragmento("Obligatorias", "TEXTO-A", distancia=0.111, parte=0, total=3),
    ]
    # Marcas que no puedan aparecer en las instrucciones: comprobar el orden
    # buscando palabras del dominio casaba con el texto de las reglas y daba
    # por malo un contexto que estaba bien colocado.
    prompt = construir_prompt("qué asignaturas hay", recuperados)
    posiciones = [prompt.index(t) for t in ("TEXTO-A", "TEXTO-B", "TEXTO-C", "TEXTO-D")]
    assert posiciones == sorted(posiciones)


def test_la_unidad_mas_proxima_sigue_yendo_primero():
    """Agrupar no puede tirar por tierra la relevancia: solo reordena dentro."""
    recuperados = [
        fragmento("Lejana", "texto lejano", distancia=0.5),
        fragmento("Cercana", "texto cercano", distancia=0.1),
    ]
    prompt = construir_prompt("una pregunta", recuperados)
    assert prompt.index("texto cercano") < prompt.index("texto lejano")


def test_la_marca_de_parte_no_aparece_en_el_contexto():
    """Regresión de dos fallos reales, y de un arreglo que no funcionó.

    Con la marca en el encabezado, el sistema contestó a un estudiante que
    «Desarrollo de aplicaciones web (Parte 1, 2, 3, 4, 5 y 6)». Se añadió una
    regla prohibiéndolo y **volvió a colarse**: la segunda vez se inventó una
    asignatura llamada «Sistemas inteligentes de información (parte 3 de 4)» y
    afirmó que su guía no estaba publicada. Lo que no está en el prompt no se
    puede filtrar.
    """
    prompt = construir_prompt(
        "una pregunta", [fragmento("Obligatorias", "once nombres", parte=2, total=3)]
    )
    assert "parte 3 de 3" not in prompt
    assert "de 3)" not in prompt


def test_las_instrucciones_fijan_el_orden_de_la_enumeracion():
    """Lo pidió el autor: agrupado por curso y las optativas al final."""
    assert "agrúpalas por curso" in INSTRUCCIONES
    assert "optativas" in INSTRUCCIONES


def test_los_listados_del_plan_se_leen_en_el_orden_en_que_se_cursan():
    """Medido: por distancia, las optativas caían entre segundo y primero.

    El modelo enumeró los cuatro cursos y dejó fuera las diecisiete optativas
    aunque las tenía delante, en la segunda posición del contexto.
    """
    plan = "plan_de_estudios"
    recuperados = [
        fragmento(
            "Asignaturas obligatorias de segundo curso del X",
            "SEGUNDO",
            distancia=0.080,
            origen=plan,
        ),
        fragmento(
            "Asignaturas optativas del X", "OPTATIVAS", distancia=0.081, origen=plan
        ),
        fragmento(
            "Asignaturas obligatorias de primer curso del X",
            "PRIMERO",
            distancia=0.082,
            origen=plan,
        ),
    ]
    prompt = construir_prompt("qué asignaturas hay", recuperados)
    posiciones = [prompt.index(t) for t in ("PRIMERO", "SEGUNDO", "OPTATIVAS")]
    assert posiciones == sorted(posiciones)


def test_un_listado_no_desplaza_a_lo_que_estaba_mas_cerca():
    """Reordenar los listados entre sí no puede colarlos por delante de todo."""
    guia = fragmento("Álgebra", "GUIA-CERCANA", distancia=0.01)
    listado = fragmento(
        "Asignaturas obligatorias de primer curso del X",
        "LISTADO",
        distancia=0.5,
        origen="plan_de_estudios",
    )
    prompt = construir_prompt("una pregunta", [guia, listado])
    assert prompt.index("GUIA-CERCANA") < prompt.index("LISTADO")


def test_el_tope_da_para_la_respuesta_mas_larga_del_corpus():
    """Las 67 asignaturas de Informática son ~783 tokens; con 400 se cortaban.

    El número no es redondo por gusto: sale de medir el listado completo con
    sus créditos sobre el corpus real.
    """
    assert TOPE_RESPUESTA >= 800


def test_las_instrucciones_prohiben_salirse_del_contexto():
    """Se comprueba la regla, no cómo esté redactada.

    La versión anterior exigía la palabra «ÚNICAMENTE» literal y saltaba al
    reescribir el prompt más corto, que es un cambio que no toca la regla. Un
    test sobre la redacción obliga a editarlo cada vez y deja de proteger nada.
    """
    assert "CONTEXTO" in INSTRUCCIONES
    assert "suponerlo" in INSTRUCCIONES or "suponerla" in INSTRUCCIONES


def test_las_instrucciones_distinguen_sin_guia_de_inexistente():
    """Son 86 asignaturas del corpus: el usuario tiene que poder distinguirlo."""
    assert "guía no está publicada" in INSTRUCCIONES
    assert "no es lo mismo que no exista" in INSTRUCCIONES


# --- La llamada al modelo ---


class RespuestaFalsa:
    def __init__(self, datos: dict[str, Any]) -> None:
        self._datos = datos

    def read(self) -> bytes:
        return json.dumps(self._datos).encode("utf-8")

    def __enter__(self) -> "RespuestaFalsa":
        return self

    def __exit__(self, *_: object) -> None:
        return None


@pytest.fixture()
def espia(monkeypatch) -> dict[str, Any]:
    """Sustituye la llamada de red y anota el cuerpo enviado."""
    registro: dict[str, Any] = {}

    def urlopen_falso(peticion: Any, timeout: int = 0) -> RespuestaFalsa:
        registro["url"] = peticion.full_url
        registro["cuerpo"] = json.loads(peticion.data.decode("utf-8"))
        return RespuestaFalsa({"response": "  una respuesta  "})

    monkeypatch.setattr(generador.urllib.request, "urlopen", urlopen_falso)
    return registro


def test_la_respuesta_llega_limpia(espia):
    assert generar("un prompt", "un-modelo") == "una respuesta"


def test_el_muestreo_va_fijado(espia):
    """Sin esto, dos ejecuciones de la misma pregunta dan cosas distintas.

    Y entonces ninguna medición sobre las respuestas sería reproducible.
    """
    generar("un prompt", "un-modelo")
    opciones = espia["cuerpo"]["options"]
    assert opciones["temperature"] == 0
    assert opciones["seed"] == 42


def test_el_mensaje_de_sistema_va_siempre_en_la_peticion(espia):
    """Regresión: sin mandarlo, cada modelo respondía bajo el suyo de fábrica.

    Medido el 18/08/2026 preguntando «¿quién eres?»: ministral-3 se presentaba
    como «un modelo creado por Mistral AI» y gemma3 como «entrenado por
    Google». Comparar candidatos así mide, además del modelo, el texto que cada
    uno lleva escondido en su plantilla.
    """
    generar("un prompt", "un-modelo")
    assert espia["cuerpo"]["system"] == generador.SISTEMA


def test_el_mensaje_de_sistema_no_puede_ir_vacio():
    """Ollama trata el `system` vacío como ausente y repone el de fábrica."""
    assert generador.SISTEMA.strip()


def test_la_ventana_se_declara_en_la_peticion(espia):
    """Regresión: con la ventana por defecto el modelo no cabe en la tarjeta.

    Medido: con la de por defecto se reparte 30 % CPU / 70 % GPU y rinde a un
    tercio; declarándola, entra entero.
    """
    generar("un prompt", "un-modelo")
    assert espia["cuerpo"]["options"]["num_ctx"] == VENTANA


def test_el_tope_de_respuesta_se_declara(espia):
    generar("un prompt", "un-modelo")
    assert espia["cuerpo"]["options"]["num_predict"] == TOPE_RESPUESTA


def test_el_razonamiento_va_desactivado(espia):
    """Regresión: con él activo, un candidato gastó 6.682 tokens y 280 s.

    Desactivado, la misma pregunta se respondió en 148 tokens y 8,74 s.
    """
    generar("un prompt", "un-modelo")
    assert espia["cuerpo"]["think"] is False


def test_no_se_llama_a_ningun_servicio_externo(espia):
    """El sistema se ejecuta entero en local: es requisito del trabajo."""
    generar("un prompt", "un-modelo")
    assert espia["url"].startswith("http://127.0.0.1")


# --- El ámbito de la consulta ---


def test_el_ambito_se_declara_como_dato_en_el_prompt():
    """78 guías se imparten en varias titulaciones y el encabezado las nombra.

    Medido: con la búsqueda acotada a Informática, el sistema respondió con un
    apartado entero sobre Inteligencia Artificial y Ciberseguridad. Acotar la
    búsqueda no le dice al modelo de qué tiene que hablar.
    """
    prompt = construir_prompt(
        "qué asignaturas hay",
        [fragmento("Álgebra", "temario")],
        ambito="Grado en Ingeniería Informática",
    )
    assert "ÁMBITO: la consulta es sobre el Grado en Ingeniería Informática" in prompt
    assert prompt.index("ÁMBITO") < prompt.index("CONTEXTO:")


def test_sin_ambito_el_prompt_no_lo_menciona():
    prompt = construir_prompt("una pregunta", [fragmento("A", "t")])
    assert "ÁMBITO:" not in prompt


# --- Sin contexto no se llama al modelo ---


def test_sin_fragmentos_no_se_consulta_al_modelo(espia):
    """El peor fallo del sistema, y el único que no depende del modelo.

    Medido el 17/08/2026 con un 7B: el recuperador rechazó correctamente un
    saludo, el prompt decía «no se ha recuperado ningún fragmento» y las
    instrucciones ya mandaban decirlo. El modelo se inventó un plan de estudios
    entero de Ingeniería Informática; de los catorce nombres que dio, **trece
    no existen** en la EPSJ.
    """
    respuesta = generador.responder(
        "¿cuánto cuesta la matrícula?",
        [],
        "un-modelo",
        [("qué grados hay", "estos")],
    )
    assert respuesta == generador.RESPUESTA_SIN_CONTEXTO
    assert "cuerpo" not in espia, "no debía haberse llamado al servidor"


def test_un_mensaje_que_no_pregunta_nada_recibe_la_bienvenida(espia):
    """Casi nadie abre preguntando: abre saludando, y como le sale.

    Medido el 18/08/2026: «hei» y «Ola buenas» no caían en el vocabulario de
    cortesía, no recuperaban nada y el sistema contestaba «no he encontrado
    información sobre eso», que responde a una pregunta que nadie había hecho.
    Enumerar las formas del saludo es una lista que nunca está completa; lo que
    sí se puede comprobar es si el mensaje pregunta algo.
    """
    respuesta = generador.responder("hei", [], "un-modelo")
    assert respuesta == generador.RESPUESTA_SALUDO
    assert "cuerpo" not in espia, "no debía haberse llamado al servidor"


def test_la_bienvenida_no_depende_del_turno(espia):
    """La misma frase recibe la misma respuesta la escriba cuando la escriba."""
    respuesta = generador.responder(
        "q tal", [], "un-modelo", [("qué optativas tiene Informática", "estas")]
    )
    assert respuesta == generador.RESPUESTA_SALUDO


def test_con_fragmentos_si_se_consulta_al_modelo(espia):
    respuesta = generador.responder(
        "¿qué se ve en Álgebra?", [fragmento("Álgebra", "Matrices.")], "un-modelo"
    )
    assert respuesta == "una respuesta"
    assert "Matrices." in espia["cuerpo"]["prompt"]


def test_la_respuesta_sin_contexto_ofrece_una_salida():
    """Un «no lo sé» a secas deja al estudiante sin saber qué preguntar."""
    assert "Politécnica Superior de Jaén" in generador.RESPUESTA_SIN_CONTEXTO
    assert "?" in generador.RESPUESTA_SIN_CONTEXTO


def test_el_ambito_y_el_historial_llegan_a_traves_de_responder(espia):
    generador.responder(
        "otra",
        [fragmento("A", "texto")],
        "un-modelo",
        [("antes", "dijo algo")],
        ambito="Grado en Ingeniería Informática",
    )
    prompt = espia["cuerpo"]["prompt"]
    assert "ÁMBITO" in prompt
    assert "antes" in prompt


# --- La cortesía ---


@pytest.mark.parametrize(
    "saludo",
    ["hola", "Hola!", "buenas", "Buenos días", "hola buenas tardes", "¿qué tal?, hola"],
)
def test_un_saludo_se_contesta_como_un_saludo(saludo):
    """Regresión del caso real: a un «hola», «no he encontrado información».

    El saludo no recupera nada, porque no se parece a ningún fragmento, y el
    suelo de pertinencia lo rechaza como debe. Pero caer en la respuesta de
    contexto vacío deja al estudiante creyendo que ha preguntado mal en su
    primera frase.
    """
    assert cortesia(saludo) == RESPUESTA_SALUDO


@pytest.mark.parametrize(
    "despedida", ["gracias", "Muchas gracias!", "adiós", "vale, gracias"]
)
def test_una_despedida_se_contesta_como_una_despedida(despedida):
    assert cortesia(despedida) == RESPUESTA_DESPEDIDA


@pytest.mark.parametrize(
    "pregunta",
    [
        "hola, ¿qué asignaturas tiene Informática?",
        "buenas, quiero saber de Mecánica",
        "¿qué salidas tiene Geomática?",
        "",
    ],
)
def test_una_pregunta_con_saludo_delante_sigue_su_camino(pregunta):
    """Reconocer «hola» dentro del texto se habría comido media pregunta.

    Por eso se exige que **todo** el mensaje quepa en el vocabulario cerrado,
    y no que contenga un saludo.
    """
    assert cortesia(pregunta) is None


def test_el_saludo_dice_de_que_sabe_el_sistema():
    """Es la primera frase que lee casi cualquiera: se aprovecha para orientar."""
    assert "Politécnica Superior de Jaén" in RESPUESTA_SALUDO
    for tema in ("asignaturas", "curso", "grados"):
        assert tema in RESPUESTA_SALUDO


def test_el_saludo_se_atiende_aunque_no_haya_contexto(espia):
    """Va antes que el cortocircuito, y sin llamar al modelo."""
    assert generador.responder("hola", [], "un-modelo") == RESPUESTA_SALUDO
    assert "cuerpo" not in espia, "no debía haberse llamado al servidor"


# --- IT-34: el prompt declara la oferta real de la Escuela ---


def test_el_prompt_enumera_las_titulaciones_que_existen():
    """Regresión del peor fallo del 16/08/2026.

    A un estudiante interesado en electricidad le recomendó seis titulaciones y
    **dos no existen** en la EPSJ: «Grado en Ingeniería de Energía» y «Grado en
    Ingeniería Ambiental». Ninguna estaba en el contexto recuperado. Las
    instrucciones ya prohibían inventar, así que prohibirlo otra vez no habría
    servido; lo que se puede hacer desde el prompt es poner delante la lista
    verdadera. Comprobar la respuesta contra ella es IT-87.
    """
    catalogo = ["Grado en Ingeniería Informática", "Grado en Ingeniería Eléctrica"]
    prompt = construir_prompt(
        "recomiéndame algo de electricidad",
        [fragmento("A", "texto")],
        catalogo=catalogo,
    )
    assert "TITULACIONES DE LA ESCUELA" in prompt
    for titulacion in catalogo:
        assert f"- {titulacion}" in prompt


def test_el_catalogo_va_antes_del_contexto():
    """Si fuera después, se leería como un fragmento recuperado más."""
    prompt = construir_prompt(
        "una pregunta",
        [fragmento("A", "texto")],
        catalogo=["Grado en Ingeniería Informática"],
    )
    assert prompt.index("TITULACIONES DE LA ESCUELA") < prompt.index("CONTEXTO:")


def test_sin_catalogo_el_prompt_no_lo_menciona():
    prompt = construir_prompt("una pregunta", [fragmento("A", "texto")])
    assert "TITULACIONES DE LA ESCUELA" not in prompt


def test_el_catalogo_llega_a_traves_de_responder(espia):
    generador.responder(
        "otra",
        [fragmento("A", "texto")],
        "un-modelo",
        catalogo=["Grado en Ingeniería Informática"],
    )
    assert "TITULACIONES DE LA ESCUELA" in espia["cuerpo"]["prompt"]


@pytest.mark.parametrize("apertura", ["Hallo", "hello", "Hi!"])
def test_un_saludo_en_otro_idioma_tambien_es_un_saludo(apertura):
    """Regresión del turno 3 del 17/08/2026.

    «Hallo» cayó en la respuesta de contexto vacío y se llevó un «no he
    encontrado información sobre eso». Un estudiante abre en el idioma que le
    sale; lo que se reconoce es la apertura, no el idioma, y la respuesta sigue
    siendo en español.
    """
    assert cortesia(apertura) == RESPUESTA_SALUDO


def test_cada_titulacion_viaja_entera_en_los_listados():
    """Regresión del turno 8 del 17/08/2026, en su segunda forma.

    Con un ancla única para todos los listados, los cursos se ordenaban entre
    sí ignorando de qué titulación eran. A «¿y en el segundo?» el listado
    correcto llegaba el octavo de dieciocho, detrás de cinco listados de primer
    curso de otras titulaciones, y el modelo contestó por un doble grado que no
    se le había preguntado.
    """
    proxima = ["Grado en Ingeniería Electrónica Industrial"]
    lejana = ["Doble Grado en Ingeniería Eléctrica y Electrónica Industrial"]
    recuperados = [
        fragmento(
            "Asignaturas obligatorias de primer curso del Doble",
            "LEJANA-PRIMERO",
            lejana,
            distancia=0.082,
            origen="plan_de_estudios",
        ),
        fragmento(
            "Asignaturas obligatorias de segundo curso del Grado",
            "PROXIMA-SEGUNDO",
            proxima,
            distancia=0.076,
            origen="plan_de_estudios",
        ),
        fragmento(
            "Asignaturas obligatorias de primer curso del Grado",
            "PROXIMA-PRIMERO",
            proxima,
            distancia=0.077,
            origen="plan_de_estudios",
        ),
    ]
    prompt = construir_prompt("¿y en el segundo?", recuperados)
    # La titulación más próxima va entera y en orden de curso, antes que la otra.
    assert (
        prompt.index("PROXIMA-PRIMERO")
        < prompt.index("PROXIMA-SEGUNDO")
        < prompt.index("LEJANA-PRIMERO")
    )


# --- El servidor puede fallar ---


def test_un_500_del_servidor_no_se_escapa_como_httperror(monkeypatch):
    """Regresión del 18/08/2026.

    Descargando un modelo de 9 GB mientras se cargaba uno de 7B, el servidor
    devolvió un 500 por falta de memoria. La excepción sin capturar se llevó por
    delante la sesión de pruebas entera, con su conversación. Una herramienta
    para probar a mano no puede perder el trabajo por un fallo pasajero.
    """
    import io
    import urllib.error

    def falla(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "http://x", 500, "Internal Server Error", {}, io.BytesIO(b"sin memoria")
        )

    monkeypatch.setattr(generador.urllib.request, "urlopen", falla)
    with pytest.raises(generador.ErrorDelModelo) as fallo:
        generador.generar("un prompt", "un-modelo")
    assert "500" in str(fallo.value)
    assert "sin memoria" in str(fallo.value)


def test_un_servidor_apagado_se_explica(monkeypatch):
    """El caso más frecuente: Ollama no está en marcha."""
    import urllib.error

    def falla(*_args, **_kwargs):
        raise urllib.error.URLError("conexión rechazada")

    monkeypatch.setattr(generador.urllib.request, "urlopen", falla)
    with pytest.raises(generador.ErrorDelModelo) as fallo:
        generador.generar("un prompt", "un-modelo")
    assert "Ollama" in str(fallo.value)


def test_un_modelo_colgado_no_tumba_la_sesion(monkeypatch):
    """Regresión del 19/08/2026.

    Agotar la espera de lectura levanta ``TimeoutError``, que **no** es un
    ``URLError``: se escapaba de las dos ramas y subía. Tumbó una tanda de 560
    respuestas cuando llevaba 85, y las nueve horas siguientes se perdieron.
    Un modelo colgado tiene que costar una pregunta, no la sesión.
    """

    def se_cuelga(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(generador.urllib.request, "urlopen", se_cuelga)
    with pytest.raises(generador.ErrorDelModelo) as fallo:
        generador.generar("un prompt", "un-modelo")
    assert "no respondió" in str(fallo.value)
    assert str(generador.ESPERA_MAXIMA) in str(fallo.value)


# --- La barrera de titulaciones inventadas (IT-87) ---

_CATALOGO_EPSJ = [
    "Grado en Ingeniería de Organización Industrial",
    "Grado en Ingeniería Geomática y Topográfica (plan 2025)",
    "Grado en Ingeniería Mecánica",
]

#: Respuesta real de mistral-nemo:12b del 19/08/2026, turno 19. Tres de las
#: cuatro titulaciones que recomienda existen; la cuarta no.
_RESPUESTA_CON_INVENTADA = (
    "Si estás interesado en estudiar una titulación de ingeniería, podrías "
    "considerar algunas opciones como:\n"
    "* Grado en Ingeniería de Organización Industrial: gestión de procesos.\n"
    "* Grado en Ingeniería Geomática y Topográfica (plan 2025): medición.\n"
    "* Grado en Ingeniería Mecánica: diseño y construcción de máquinas.\n"
    "* Grado en Ingeniería de Edificación: construcción y gestión de edificios.\n"
)


def _con_respuesta(monkeypatch, texto: str) -> None:
    monkeypatch.setattr(generador, "generar", lambda prompt, modelo: texto)


def test_una_titulacion_inventada_retira_la_respuesta_entera(monkeypatch):
    """Regresión del turno 19 de mistral-nemo:12b.

    El «Grado en Ingeniería de Edificación» no se imparte en la EPSJ. Iba
    cuarto en una lista de recomendaciones cuyas otras tres son reales, que es
    justo lo que lo hace peligroso: un preuniversitario no tiene con qué
    distinguirlas. Las instrucciones ya prohibían añadir lo que no está en el
    contexto.
    """
    _con_respuesta(monkeypatch, _RESPUESTA_CON_INVENTADA)
    respuesta = generador.responder(
        "soy de FP de arquitectura, ¿qué puedo estudiar?",
        [fragmento("A", "texto")],
        "un-modelo",
        catalogo=_CATALOGO_EPSJ,
    )
    assert respuesta == generador.RESPUESTA_TITULACION_INVENTADA


def test_si_todas_existen_la_respuesta_pasa(monkeypatch):
    """La barrera no puede cobrarse las respuestas correctas.

    Medido sobre las 399 respuestas del cribado: bloquea 0.
    """
    buena = (
        "Puedes estudiar el Grado en Ingeniería Mecánica y el Grado en "
        "Ingeniería de Organización Industrial."
    )
    _con_respuesta(monkeypatch, buena)
    assert (
        generador.responder(
            "¿qué puedo estudiar?",
            [fragmento("A", "texto")],
            "un-modelo",
            catalogo=_CATALOGO_EPSJ,
        )
        == buena
    )


def test_sin_catalogo_no_hay_nada_contra_lo_que_comprobar(monkeypatch):
    """Comportamiento declarado: sin catálogo la barrera no actúa."""
    _con_respuesta(monkeypatch, _RESPUESTA_CON_INVENTADA)
    assert (
        generador.responder("una pregunta", [fragmento("A", "texto")], "un-modelo")
        == _RESPUESTA_CON_INVENTADA
    )


#: Respuesta real del 16/08/2026, la que motivó IT-87: seis titulaciones
#: recomendadas a un estudiante interesado en electricidad, dos inexistentes.
_RESPUESTA_IT87 = (
    "Si te interesa la electricidad, en la EPSJ puedes estudiar:\n"
    "- Grado en Ingeniería Eléctrica\n"
    "- Grado en Ingeniería Electrónica Industrial\n"
    "- Grado en Ingeniería de Energía\n"
    "- Grado en Ingeniería Ambiental\n"
)


def test_el_caso_que_motivo_la_tarjeta_se_detecta(monkeypatch):
    """Regresión de IT-87.

    Ni el «Grado en Ingeniería de Energía» ni el «Grado en Ingeniería
    Ambiental» existen en la EPSJ, y ninguno aparecía en el contexto
    recuperado. Las instrucciones ya prohibían añadir datos que no estuvieran
    en el contexto.
    """
    catalogo = [
        "Grado en Ingeniería Eléctrica",
        "Grado en Ingeniería Electrónica Industrial",
    ]
    _con_respuesta(monkeypatch, _RESPUESTA_IT87)
    assert (
        generador.responder(
            "¿qué puedo estudiar si me gusta la electricidad?",
            [fragmento("A", "texto")],
            "un-modelo",
            catalogo=catalogo,
        )
        == generador.RESPUESTA_TITULACION_INVENTADA
    )


def test_la_respuesta_retirada_queda_registrada(monkeypatch, caplog):
    """Una barrera que descarta en silencio no se puede auditar."""
    _con_respuesta(monkeypatch, _RESPUESTA_CON_INVENTADA)
    with caplog.at_level("WARNING", logger="tfg_uja.generador"):
        generador.responder(
            "una pregunta",
            [fragmento("A", "texto")],
            "un-modelo",
            catalogo=_CATALOGO_EPSJ,
        )
    assert "Grado en Ingeniería de Edificación" in caplog.text


# --- Lo que enseñó la sesión del 19/08/2026 con `ministral-8b` ---


def test_un_agradecimiento_con_mas_palabras_se_cierra_como_cortesia():
    """Regresión: turno 5 de la sesión del 19/08/2026.

    «Me gusta la idea, muchas gracias» no cabe en la cortesía estricta, que
    exige que el mensaje entero sean fórmulas, y recibía «no he encontrado
    información sobre eso».
    """
    assert cierre_de_conversacion("Me gusta la idea, muchas gracias") == (
        RESPUESTA_DESPEDIDA
    )


def test_un_agradecimiento_que_ademas_pregunta_no_se_cierra():
    """Si hay pregunta, hay que responderla aunque venga precedida de gracias."""
    assert cierre_de_conversacion("Gracias, ¿y qué asignaturas tiene?") is None
    assert cierre_de_conversacion("gracias, dime las optativas") is None


def test_la_misma_pregunta_sin_contexto_responde_igual_en_todos_los_turnos():
    """Regresión: turnos 1 y 2 de la sesión, idénticos y con respuesta distinta.

    La regla anterior daba la bienvenida si era el primer mensaje y el rechazo
    si venía después, de modo que la misma frase escrita dos veces seguidas
    recibía dos respuestas.
    """
    pregunta = "No sé qué estudiar, me gusta la física y el dibujo técnico"
    primera = responder(pregunta, [], "modelo-que-no-se-llama")
    segunda = responder(pregunta, [], "modelo-que-no-se-llama", historial=[("a", "b")])
    assert primera == segunda == RESPUESTA_SIN_CONTEXTO


def test_un_saludo_sin_contexto_saluda_aunque_traiga_mas_palabras():
    assert cortesia_sin_contexto("buenas, quiero información") == RESPUESTA_SALUDO


def test_una_respuesta_cortada_se_cierra_en_la_ultima_frase():
    """Regresión: «**Nota:** Todas las titul», medido en el turno 3."""
    cortada = "Te encajan tres titulaciones. Son estas.\n\n**Nota:** Todas las titul"
    assert cerrar_en_frase_completa(cortada) == (
        "Te encajan tres titulaciones. Son estas."
    )


def test_una_lista_cortada_se_cierra_en_la_ultima_linea_completa():
    """En una lista, lo que cierra el último elemento es el salto de línea."""
    cortada = "- Álgebra (6 ECTS)\n- Física I (6 ECTS)\n- Cálculo (6 EC"
    assert cerrar_en_frase_completa(cortada) == (
        "- Álgebra (6 ECTS)\n- Física I (6 ECTS)"
    )


def test_un_texto_sin_ningun_cierre_se_devuelve_entero():
    """Antes que entregar nada, se entrega lo que haya."""
    assert cerrar_en_frase_completa("Las titulaciones de la Escuela son") == (
        "Las titulaciones de la Escuela son"
    )


def test_el_aviso_de_respuesta_cortada_lo_dice_en_primera_persona():
    """El estudiante no puede distinguir una respuesta cortada de una entera."""
    assert "cortar" in AVISO_RESPUESTA_CORTADA


# --- Preguntas sobre otra universidad ---


def test_preguntar_por_otra_universidad_no_se_responde_con_la_de_aqui():
    """Regresión: el suelo de pertinencia no puede detectar esto.

    «¿La Universidad de Granada tiene Ingeniería Informática?» tiene su mejor
    fragmento a 0,1185, más cerca que la mayoría de las preguntas legítimas,
    porque nombra una titulación que sí existe aquí. La distancia mide parecido
    de vocabulario y el vocabulario es casi el mismo.
    """
    assert (
        generador.pregunta_por_otro_centro(
            "¿La Universidad de Granada tiene Ingeniería Informática?"
        )
        == generador.RESPUESTA_OTRA_UNIVERSIDAD
    )


def test_la_universidad_de_jaen_si_se_responde():
    assert (
        generador.pregunta_por_otro_centro(
            "¿Qué titulaciones tiene la Universidad de Jaén?"
        )
        is None
    )


def test_una_pregunta_normal_no_dispara_el_rechazo_de_centro():
    assert (
        generador.pregunta_por_otro_centro("¿Qué optativas tiene Informática?") is None
    )


def test_pedir_algo_sin_preguntar_no_recibe_la_bienvenida():
    """Regresión: «Dame una receta de tortilla de patatas», medido el 20/08/2026.

    No lleva interrogación ni palabra interrogativa, así que la regla que
    distingue un saludo de una pregunta lo tomaba por un saludo y los tres
    candidatos contestaron con la bienvenida en vez de decir que de eso no
    saben. Un imperativo pide algo aunque no pregunte.
    """
    assert (
        generador.responder("Dame una receta de tortilla de patatas", [], "x")
        == generador.RESPUESTA_SIN_CONTEXTO
    )


def test_un_saludo_con_peticion_sigue_saludando():
    """«Buenas, quiero información» abre la conversación: se le da la bienvenida."""
    assert (
        generador.responder("buenas, quiero información", [], "x")
        == generador.RESPUESTA_SALUDO
    )


def test_la_traza_recoge_lo_que_la_barrera_retira(monkeypatch):
    """Sin el texto retirado no se puede auditar la barrera.

    Una respuesta de rechazo se ve igual venga de un modelo que se inventó una
    titulación o de una barrera que descartó una respuesta buena, y son cosas
    opuestas. Quien mide necesita poder mirar qué se tiró.
    """
    _con_respuesta(monkeypatch, _RESPUESTA_CON_INVENTADA)
    traza: dict[str, object] = {}
    respuesta = generador.responder(
        "soy de FP de arquitectura, ¿qué puedo estudiar?",
        [fragmento("A", "texto")],
        "un-modelo",
        catalogo=_CATALOGO_EPSJ,
        traza=traza,
    )
    assert respuesta == generador.RESPUESTA_TITULACION_INVENTADA
    assert traza["inventadas"] == ["Grado en Ingeniería de Edificación"]
    assert traza["retirada"] == _RESPUESTA_CON_INVENTADA


def test_la_traza_queda_vacia_si_la_barrera_no_salta(monkeypatch):
    """Solo se anota lo retirado. Una traza vacía significa que no hubo nada."""
    buena = "Puedes estudiar el Grado en Ingeniería Mecánica."
    _con_respuesta(monkeypatch, buena)
    traza: dict[str, object] = {}
    respuesta = generador.responder(
        "¿qué puedo estudiar?",
        [fragmento("A", "texto")],
        "un-modelo",
        catalogo=_CATALOGO_EPSJ,
        traza=traza,
    )
    assert respuesta == buena
    assert traza == {}


# --- Otro centro que no es la EPSJ (IT-109) ---
#
# Los tres primeros casos salen del conjunto de validación de preguntas ajenas
# al dominio, el que no intervino en ningún ajuste. Los tres pasaban el suelo de
# pertinencia y ninguno tenía segunda línea de defensa.


def test_una_universidad_con_adjetivo_delante_del_de():
    """V-005: detrás de «universidad» viene el adjetivo, no la preposición."""
    assert generador.pregunta_por_otro_centro(
        "¿La Universidad Politécnica de Valencia tiene Ingeniería Mecánica?"
    )


def test_un_centro_hermano_de_la_propia_universidad_de_jaen():
    """V-006, el caso incómodo: la EPS de Linares es de la UJA.

    Su nombre se distingue del de la EPS de Jaén en una sola palabra, así que
    confundirlas no requiere ninguna mala intención. Antes de esto el sistema
    devolvía tres fragmentos del centro equivocado.
    """
    assert generador.pregunta_por_otro_centro(
        "¿Qué se estudia en la Escuela Politécnica Superior de Linares?"
    )


def test_una_facultad_de_otra_rama_tampoco_es_de_aqui():
    assert generador.pregunta_por_otro_centro(
        "¿Qué salidas tiene la Facultad de Ciencias Sociales?"
    )


def test_la_formula_que_ya_funcionaba_sigue_funcionando():
    """El caso que motivó la comprobación no puede romperse al ampliarla."""
    assert generador.pregunta_por_otro_centro(
        "¿La Universidad de Granada tiene Ingeniería Informática?"
    )


def test_preguntar_por_la_escuela_de_jaen_no_es_preguntar_por_otro_centro():
    """Lo que decide es el topónimo, y aquí el topónimo es el nuestro."""
    assert (
        generador.pregunta_por_otro_centro(
            "¿Qué se estudia en la Escuela Politécnica Superior de Jaén?"
        )
        is None
    )
    assert (
        generador.pregunta_por_otro_centro("¿La Universidad de Jaén tiene Informática?")
        is None
    )


def test_una_pregunta_normal_del_dominio_no_dispara_la_comprobacion():
    """Con un falso positivo aquí el asistente dejaría de servir para nada."""
    assert (
        generador.pregunta_por_otro_centro(
            "¿Qué asignaturas tiene Ingeniería Mecánica?"
        )
        is None
    )
    assert (
        generador.pregunta_por_otro_centro("¿Cuántos créditos tiene Álgebra?") is None
    )


# --- Los tres desenlaces que faltaban por cubrir ---


def test_una_cortesia_que_no_saluda_ni_se_despide_no_recibe_respuesta_fija():
    """«Vale» es todo cortesía y no es ni saludo ni despedida: no se contesta.

    Es la condición que el propio módulo declara al separar ``_SALUDO`` de
    ``_CORTESIA``: sin ella, un resto de frase como «vale» o «por favor»
    entraría por ser todo palabras corteses y el asistente saludaría a mitad de
    conversación. Devolver ``None`` deja que el turno siga su curso normal.
    """
    assert cortesia("vale") is None
    assert cortesia("por favor") is None


def test_una_despedida_sin_contexto_se_despide_en_vez_de_no_encontrar_nada():
    """Dar las gracias al final no puede acabar en «no he encontrado nada».

    Es el mismo fallo del turno 5 de la sesión del 19/08/2026, pero por la otra
    rama: cuando además el recuperador se ha quedado sin fragmentos. Cerrar la
    conversación no necesita contexto ninguno.
    """
    assert cortesia_sin_contexto("muchas gracias, hasta luego") == RESPUESTA_DESPEDIDA


def test_una_respuesta_cortada_por_longitud_se_cierra_y_se_avisa(monkeypatch):
    """Si el modelo agota el tope, se corta en frase entera y se dice que falta.

    Ollama devuelve ``done_reason: "length"`` cuando ha llegado al tope de
    fichas. Entregar el texto tal cual dejaría la última frase a medias, y el
    estudiante no tendría forma de saber si eso es toda la información o solo
    la que cupo.
    """

    def urlopen_falso(peticion: Any, timeout: int = 0) -> RespuestaFalsa:
        return RespuestaFalsa(
            {
                "response": "Se cursan Álgebra y Cálculo. Además está Físi",
                "done_reason": "length",
            }
        )

    monkeypatch.setattr(generador.urllib.request, "urlopen", urlopen_falso)

    escrito = generar("un prompt", "un-modelo")

    assert escrito.endswith(AVISO_RESPUESTA_CORTADA)
    assert "Físi" not in escrito
    assert "Se cursan Álgebra y Cálculo." in escrito


# --- IT-39: un imperativo ajeno no se saluda ---


def test_una_peticion_ajena_sin_interrogacion_no_recibe_un_saludo():
    """«Hazme un resumen de la Segunda Guerra Mundial» no es un saludo.

    Medido el 23/08/2026 sobre el banco del sistema: esa frase y «Tradúceme al
    inglés...» no llevan interrogación, y sus verbos con pronombre enclítico
    ---`hazme`, `traduceme`--- no están en el vocabulario interrogativo, que
    recoge unas formas y otras no. Las dos recibían la bienvenida del asistente
    en lugar de que se les dijera que eso queda fuera de su ámbito, y eso es
    peor que no responder: da a entender que la petición se ha entendido.
    """
    assert (
        cortesia_sin_contexto("Hazme un resumen de la Segunda Guerra Mundial.") is None
    )
    assert (
        cortesia_sin_contexto(
            "Tradúceme al inglés: «me gustaría estudiar una ingeniería»."
        )
        is None
    )


def test_un_saludo_que_no_esta_en_la_lista_sigue_recibiendo_la_bienvenida():
    """La regresión del arreglo: «hei» y «q tal» no pueden dejar de saludarse.

    El respaldo existe porque el vocabulario de saludos no puede recogerlos
    todos. Lo que lo separa de una petición ajena es la longitud, no el verbo.
    """
    assert cortesia_sin_contexto("hei") == RESPUESTA_SALUDO
    assert cortesia_sin_contexto("q tal") == RESPUESTA_SALUDO


def test_el_saludo_de_respaldo_no_se_estira_a_una_frase():
    """Tres palabras ya son una petición, no un saludo mal escrito."""
    assert cortesia_sin_contexto("resumeme la guerra") is None


# --- IT-44: emisión por partes (ADR-0006) ---


class FlujoFalso:
    """Imita la respuesta en flujo de Ollama: un JSON por línea."""

    def __init__(self, trozos: list[dict[str, Any]]) -> None:
        self._lineas = [json.dumps(t).encode("utf-8") for t in trozos]

    def __iter__(self) -> Any:
        return iter(self._lineas + [b"\n"])

    def __enter__(self) -> "FlujoFalso":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def flujo_de(monkeypatch, trozos: list[dict[str, Any]]) -> None:
    """Hace que la llamada al modelo devuelva ese flujo."""
    monkeypatch.setattr(
        generador.urllib.request, "urlopen", lambda *a, **k: FlujoFalso(trozos)
    )


@pytest.mark.parametrize(
    ("texto", "unidades", "resto"),
    [
        ("Una frase. Y otra.", ["Una frase.", " Y otra."], ""),
        ("Sin frontera todavia", [], "Sin frontera todavia"),
        ("*  Item\n*  Otro\n", ["*  Item\n", "*  Otro\n"], ""),
        ("", [], ""),
    ],
)
def test_solo_se_suelta_lo_que_cierra_frontera_segura(texto, unidades, resto) -> None:
    """La frontera es lo que impide el falso positivo del ADR-0006.

    Soltar «Grado en Ingeniería Infor» ---cortado a mitad de palabra--- haría
    saltar la comprobación de titulaciones inventadas, porque esas palabras no
    son subconjunto de ninguna titulación real. Con la frontera eso no ocurre.
    """
    assert generador.partir_en_unidades(texto) == (unidades, resto)


def test_el_flujo_del_modelo_llega_trozo_a_trozo(monkeypatch) -> None:
    """Es lo que hace que el estudiante vea texto antes del minuto."""
    flujo_de(monkeypatch, [{"response": "Hola"}, {"response": " mundo."}])

    assert list(generador.generar_por_partes("prompt", "un-modelo")) == [
        "Hola",
        " mundo.",
    ]


def test_una_respuesta_cortada_por_longitud_lo_avisa_al_final(monkeypatch) -> None:
    """El tope solo se conoce al terminar, así que el aviso va detrás."""
    flujo_de(
        monkeypatch,
        [
            {"response": "Se cursan Álgebra"},
            {"response": " y", "done_reason": "length"},
        ],
    )

    partes = list(generador.generar_por_partes("prompt", "un-modelo"))

    assert partes[-1] == AVISO_RESPUESTA_CORTADA


def test_si_el_servidor_esta_caido_el_flujo_lo_dice(monkeypatch) -> None:
    """Mismo error que la vía síncrona: un fallo de red no puede pasar mudo."""

    def revienta(*a: Any, **k: Any) -> Any:
        raise generador.urllib.error.URLError("conexión rechazada")

    monkeypatch.setattr(generador.urllib.request, "urlopen", revienta)

    with pytest.raises(generador.ErrorDelModelo, match="Ollama"):
        list(generador.generar_por_partes("prompt", "un-modelo"))


def test_la_cortesia_sale_de_una_pieza_y_sin_llamar_al_modelo(monkeypatch) -> None:
    """Un saludo no espera: sale entero y en una sola parte."""

    def no_llamar(*a: Any, **k: Any) -> Any:  # pragma: no cover
        raise AssertionError("no debería llamarse al modelo")

    monkeypatch.setattr(generador, "generar_por_partes", no_llamar)

    assert list(generador.responder_por_partes("hola", [], "un-modelo")) == [
        RESPUESTA_SALUDO
    ]


def test_sin_fragmentos_no_se_llama_al_modelo(monkeypatch) -> None:
    """La barrera del contexto vacío es idéntica en las dos vías."""
    partes = list(
        generador.responder_por_partes("¿Cuántos créditos tiene Álgebra?", [], "m")
    )

    assert partes == [RESPUESTA_SIN_CONTEXTO]


def test_una_titulacion_inventada_manda_borrar_lo_ya_emitido(monkeypatch) -> None:
    """Es la barrera de retirada del ADR-0006 actuando a media emisión.

    El ``None`` es la señal de «borra lo emitido»: sin ella el estudiante se
    quedaría con la recomendación inventada en pantalla y la respuesta fija
    debajo, que es peor que no retirar nada.
    """
    flujo_de(
        monkeypatch,
        [{"response": "Te recomiendo el Grado en Magia Avanzada."}],
    )
    frag = fragmento("Álgebra", "algo", grados=["Grado en Ingeniería Mecánica"])

    partes = list(
        generador.responder_por_partes(
            "¿Qué me recomiendas?",
            [frag],
            "un-modelo",
            catalogo=["Grado en Ingeniería Mecánica"],
        )
    )

    assert partes[-2] is None
    assert partes[-1] == RESPUESTA_TITULACION_INVENTADA


def test_la_cola_sin_frontera_tambien_se_verifica(monkeypatch) -> None:
    """Lo último que escribe el modelo puede no cerrar en punto.

    Sin esta rama, una titulación inventada escrita en la última frase ---la
    que se queda sin punto final--- se entregaría sin comprobar.
    """
    flujo_de(monkeypatch, [{"response": "Existe el Grado en Magia Avanzada"}])
    frag = fragmento("Álgebra", "algo", grados=["Grado en Ingeniería Mecánica"])

    partes = list(
        generador.responder_por_partes(
            "¿Y?", [frag], "m", catalogo=["Grado en Ingeniería Mecánica"]
        )
    )

    assert partes[-1] == RESPUESTA_TITULACION_INVENTADA


def test_una_respuesta_limpia_sale_entera_por_partes(monkeypatch) -> None:
    """El caso normal: se suelta por frases y no se retira nada."""
    flujo_de(
        monkeypatch,
        [{"response": "Álgebra tiene 6 ECTS."}, {"response": " Es de primero"}],
    )
    frag = fragmento("Álgebra", "algo", grados=["Grado en Ingeniería Mecánica"])

    partes = list(
        generador.responder_por_partes(
            "¿Cuántos créditos?",
            [frag],
            "m",
            catalogo=["Grado en Ingeniería Mecánica"],
        )
    )

    assert "".join(p for p in partes if p) == "Álgebra tiene 6 ECTS. Es de primero"
    assert None not in partes


def test_un_error_http_del_servidor_llega_con_su_codigo(monkeypatch) -> None:
    """Un 500 del servidor de inferencia no puede confundirse con una respuesta."""

    def revienta(*a: Any, **k: Any) -> Any:
        raise generador.urllib.error.HTTPError(
            "u",
            500,
            "Internal Error",
            {},  # type: ignore[arg-type]
            io.BytesIO(b"modelo no cargado"),
        )

    monkeypatch.setattr(generador.urllib.request, "urlopen", revienta)

    with pytest.raises(generador.ErrorDelModelo, match="500"):
        list(generador.generar_por_partes("prompt", "un-modelo"))


def test_un_modelo_colgado_cuesta_una_pregunta_y_no_la_sesion(monkeypatch) -> None:
    """Misma lección que la vía síncrona: agotar la espera levanta TimeoutError.

    El 19/08/2026 un modelo colgado tumbó una tanda de 560 respuestas cuando
    llevaba 85, porque TimeoutError no es un URLError y se escapaba de las dos
    ramas. La vía por partes tiene que atraparlo igual.
    """

    def se_cuelga(*a: Any, **k: Any) -> Any:
        raise TimeoutError

    monkeypatch.setattr(generador.urllib.request, "urlopen", se_cuelga)

    with pytest.raises(generador.ErrorDelModelo, match="no respondió"):
        list(generador.generar_por_partes("prompt", "un-modelo"))


# ------------------------------------------- la respuesta que no llega al modelo


@pytest.mark.parametrize(
    "pregunta",
    [
        "Hola",
        "Buenas tardes",
        "Gracias, adiós",
        "¿Puedo estudiar Medicina en la Universidad de Granada?",
    ],
)
def test_hay_preguntas_que_se_contestan_sin_mirar_el_contexto(pregunta: str) -> None:
    """Las tres salidas anticipadas se deciden con la pregunta y nada más.

    Quien llama necesita saberlo ANTES de recuperar: buscar fragmentos para un
    saludo es trabajo tirado, y enseñarlos como fuentes de la respuesta es
    presentar como respaldo algo que nadie usó para redactarla.
    """
    assert generador.respuesta_fija(pregunta) is not None


def test_una_pregunta_del_dominio_no_tiene_respuesta_fija() -> None:
    """Si la tuviera, el sistema dejaría de consultar la colección."""
    assert generador.respuesta_fija("¿Qué asignaturas tiene Informática?") is None


def test_las_dos_formas_de_responder_toman_el_mismo_desvio() -> None:
    """Regresión: la cadena de salidas estaba escrita dos veces.

    Con dos copias, cambiar una y olvidar la otra hace que el chat y la
    emisión por partes contesten cosas distintas al mismo saludo.
    """
    entera = generador.responder("Hola", [], "da-igual", catalogo=[])
    por_partes = list(
        generador.responder_por_partes("Hola", [], "da-igual", catalogo=[])
    )

    assert por_partes == [entera]

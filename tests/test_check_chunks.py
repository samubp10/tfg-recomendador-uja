"""Pruebas del verificador del corpus de fragmentos (IT-16).

El verificador vive en ``scripts/`` y se ejecuta a mano contra el corpus
completo, que no está versionado. Estas pruebas no lo necesitan: comprueban
que el guion no vuelva a alejarse de lo que dice verificar.

``scripts/`` no es un paquete importable, así que el módulo se carga por su
ruta en lugar de con un ``import`` normal, igual que en
``test_check_dataset.py``.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
from pathlib import Path

from tfg_uja.indexacion import chunker

RAIZ = Path(__file__).resolve().parent.parent
_RUTA = RAIZ / "scripts" / "verificadores" / "check_chunks.py"
_spec = importlib.util.spec_from_file_location("check_chunks", _RUTA)
assert _spec is not None and _spec.loader is not None
check_chunks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_chunks)

#: Umbrales que el verificador comparte con el fragmentador.
_COMPARTIDOS = ("TAMANO_MAXIMO", "TAMANO_MINIMO")


def _nombres_asignados(ruta: Path) -> set[str]:
    """Nombres a los que el módulo asigna un valor en su nivel superior.

    Se analiza el árbol sintáctico en lugar de buscar texto, para que el
    resultado no dependa de cómo esté escrita la línea (espacios, anotación
    de tipo o varios nombres en la misma asignación).

    Args:
        ruta: Fichero de Python a analizar.

    Returns:
        Conjunto de nombres asignados en el nivel superior del módulo.
    """
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    nombres: set[str] = set()
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign):
            nombres |= {d.id for d in nodo.targets if isinstance(d, ast.Name)}
        elif isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name):
            nombres.add(nodo.target.id)
    return nombres


def test_los_umbrales_valen_lo_que_dice_el_fragmentador() -> None:
    """El verificador comprueba los tamaños que el fragmentador declara.

    Regresión de IT-16. El guion llevaba ``TAMANO_MAXIMO = 1500`` copiado a
    mano, con el comentario de que se duplicaba «para que el script no dependa
    del paquete instalado, que se ejecuta también en CI». Ninguna de las dos
    cosas seguía siendo cierta: el flujo de trabajo declara que este
    verificador no corre en CI.

    El daño de la copia no es la duplicación en sí, sino que al bajar el
    máximo a 900 el guion habría seguido exigiendo ``<= 1500``, que se cumple
    siempre: pasa en verde sin verificar nada. Es el mismo patrón que los
    encabezados cruzados de IT-91, donde el verificador comparaba claves en
    vez de encabezados y respondía «OK» sobre un corpus roto.
    """
    for nombre in _COMPARTIDOS:
        assert getattr(check_chunks, nombre) == getattr(chunker, nombre)


def test_los_umbrales_no_se_vuelven_a_copiar() -> None:
    """El verificador importa los umbrales; no los declara por su cuenta.

    Comprobar solo que los valores coinciden no bastaría: una copia con el
    número correcto pasaría esa prueba y se separaría en silencio la primera
    vez que el fragmentador cambiara. Y comparar la identidad del objeto
    tampoco sirve, porque CPython reutiliza los enteros pequeños y ``200``
    sería el mismo objeto aunque estuviera escrito dos veces.

    Lo que distingue «importado» de «copiado con suerte» es que el módulo no
    asigne esos nombres, y eso sí se puede comprobar sobre el código.
    """
    asignados = _nombres_asignados(_RUTA)
    duplicados = sorted(asignados & set(_COMPARTIDOS))
    assert not duplicados, (
        f"check_chunks.py vuelve a declarar {duplicados} en vez de importarlos "
        f"de tfg_uja.chunker; en cuanto cambien allí, este verificador dejará "
        f"de comprobar lo que el sistema declara."
    )


# --- IT-16: el mínimo es una preferencia, no una restricción dura ---

#: Encabezado de un carácter, para que el hueco que descuenta el fragmentador
#: sea 2 y las longitudes del caso de prueba se puedan seguir a mano.
_ENCABEZADO = "H"


def _chunk(cuerpo: str, indice: int, total: int) -> dict:
    """Chunk mínimo con la forma que produce el fragmentador."""
    return {
        "texto": f"{_ENCABEZADO}\n{cuerpo}",
        "chunk_index": indice,
        "total_chunks": total,
    }


def test_una_cola_que_cabia_junto_al_vecino_se_denuncia() -> None:
    """Un fragmento corto que sí se podía fusionar es un fallo de la fusión.

    Cuerpos de 300 y 50 caracteres: unidos ocupan 351, muy por debajo de los
    898 de presupuesto (900 menos el encabezado y su salto). Si el segundo
    sigue suelto es que ``_fusionar_pequenos`` ha dejado de unir, que es
    exactamente lo que este verificador tiene que detectar.
    """
    lista = [_chunk("a" * 300, 0, 2), _chunk("b" * 50, 1, 2)]
    assert check_chunks.cortos_evitables(lista) == [52]


def test_una_cola_irreducible_no_se_denuncia() -> None:
    """Un fragmento corto que no cabía junto a su vecino es legítimo.

    Cuerpos de 880 y 50: unidos ocupan 931 y se pasan de los 898 disponibles,
    así que el fragmentador conserva la cola corta antes que romper el máximo.
    Es el caso real de las seis colas que aparecieron al bajar el máximo a 900
    («Minería web», «Metrología», «Sistemas de información espacial»...), y
    darlo por defecto haría fallar el verificador sobre un corpus correcto.
    """
    lista = [_chunk("a" * 880, 0, 2), _chunk("b" * 50, 1, 2)]
    assert check_chunks.cortos_evitables(lista) == []


def test_la_cola_corta_puede_ser_la_primera() -> None:
    """Cuando el fragmento corto abre la unidad, el vecino es el siguiente.

    ``_fusionar_pequenos`` mira al anterior salvo en el primero, donde mira al
    siguiente. Reconstruir la unión con el vecino equivocado daría un tamaño
    distinto y el veredicto podría cambiar, así que se comprueba aparte.
    """
    lista = [_chunk("a" * 50, 0, 2), _chunk("b" * 300, 1, 2)]
    assert check_chunks.cortos_evitables(lista) == [52]


def test_una_unidad_de_un_solo_chunk_nunca_es_evitable() -> None:
    """Una unidad indivisible no tiene con quién fusionarse.

    Una asignatura cuya guía apenas trae texto produce un único fragmento por
    debajo del mínimo, y no hay nada que reprocharle al fragmentador.
    """
    assert check_chunks.cortos_evitables([_chunk("a" * 20, 0, 1)]) == []


# --- Que el verificador no se desincronice del fragmentador (IT-10) --------


def test_cortos_evitables_coincide_con_la_direccion_de_la_fusion() -> None:
    """``cortos_evitables`` reimplementa parte de ``_fusionar_pequenos``.

    El verificador reconstruye por su cuenta si un fragmento corto se podía
    unir a su vecino, y para eso tiene que mirar al mismo vecino que mira el
    fragmentador: el anterior salvo en el primero, donde mira al siguiente. Si
    el fragmentador cambiara de criterio y el verificador no, este daría por
    legítimo un fragmento corto que sí era fusionable, y lo haría diciendo
    «OK». Se comprueba sobre el código real para que la divergencia no pueda
    pasar inadvertida.
    """
    fuente = ast.parse(inspect.getsource(chunker._fusionar_pequenos))
    expresiones = {
        ast.unparse(n)
        for n in ast.walk(fuente)
        if isinstance(n, ast.IfExp) and "i - 1" in ast.unparse(n)
    }

    assert expresiones, (
        "`_fusionar_pequenos` ya no elige el vecino con una expresión "
        "condicional sobre `i - 1`. Revisa si `cortos_evitables` sigue "
        "reconstruyendo la misma unión que hace el fragmentador."
    )
    assert any("i + 1" in e for e in expresiones), (
        "`_fusionar_pequenos` ha dejado de mirar al vecino siguiente cuando "
        "el fragmento corto es el primero. `cortos_evitables` sí lo hace, así "
        "que los dos han dejado de comprobar lo mismo."
    )


def test_no_extraidas_se_calcula_por_correspondencia_no_por_resta() -> None:
    """Restar dos totales esconde qué falta y se cancela con otros errores.

    Si el aviso se calculara como «asignaturas con guía menos guías», el día
    que aparezcan a la vez una guía sin contenido y una guía huérfana los dos
    errores se anulan y el aviso diría 0. Se comprueba que el guion trabaja
    con conjuntos de claves.
    """
    fuente = _RUTA.read_text(encoding="utf-8")

    assert "declaran_guia - guias_reales" in fuente, (
        "el aviso de guías sin contenido debe salir de una diferencia de "
        "conjuntos de claves, no de restar dos recuentos"
    )
    assert (
        'sum(1 for a in asignaturas if a["tiene_guia"]) - len(guias)' not in fuente
    ), (
        "ha vuelto el cálculo por resta: esconde qué asignaturas son y se "
        "cancela con una guía huérfana"
    )


# ---------------------------------------------------------------------------
# Los invariantes del corpus (IT-113)
#
# Hasta aquí estaban probados los umbrales y `cortos_evitables`. Las once
# comprobaciones que de verdad deciden si el corpus vale ---y que acaban
# diciendo «Chunks OK»--- no las cubría ninguna prueba. Los fixtures copian la
# forma REAL de los fragmentos derivados, mirada en `data/chunks.json`: con un
# formato inventado, las expresiones regulares del verificador no encuentran
# nada y la prueba mide otra cosa.
# ---------------------------------------------------------------------------

import json  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, str(RAIZ / "src"))

from tfg_uja.invariantes import InvarianteRoto  # noqa: E402

GRADO = "Grado en Ingeniería Informática"
DOBLE = "Doble Grado en Ingeniería Mecánica y Organización Industrial"


def _frag(
    nombre="Matemática discreta",
    texto=None,
    origen="guia",
    grados=None,
    codigos=None,
    indice=0,
    total=1,
):
    """Un fragmento del corpus, con el encabezado que su origen exige."""
    if texto is None:
        texto = f"«{nombre}»\n" + "contenido. " * 30
    return {
        "tipo": "chunk",
        "origen": origen,
        "grados": grados if grados is not None else [GRADO],
        "codigos": codigos if codigos is not None else ["12345"],
        "nombre": nombre,
        "texto": texto,
        "chunk_index": indice,
        "total_chunks": total,
    }


def _catalogo(titulaciones=1, simples=1, dobles=0):
    """El fragmento de catálogo general, con la forma real del corpus."""
    nombre = "Titulaciones que se imparten en la Escuela Politécnica Superior de Jaén"
    return _frag(
        nombre=nombre,
        origen="catalogo",
        codigos=[None],
        texto=(
            f"{nombre}. En total son {titulaciones}: {simples} grados y "
            f"{dobles} dobles grados.\nGrados:\n{GRADO}."
        ),
    )


def _ficha(grado=GRADO, total=1, obligatorias=1, optativas=0):
    """La ficha de una titulación, con la forma real del corpus."""
    nombre = f"Datos generales del {grado}"
    return _frag(
        nombre=nombre,
        origen="ficha_titulacion",
        grados=[grado],
        codigos=[None],
        texto=(
            f"{nombre}.\nEn total tiene {total} asignaturas: "
            f"{obligatorias} obligatorias y {optativas} optativas."
        ),
    )


def _plan(cuantas=1, listadas=None):
    """Un listado de plan de estudios; `listadas` permite descuadrarlo."""
    nombre = f"Asignaturas obligatorias de primer curso del {GRADO}"
    cuerpo = "\n".join(f"ASIGNATURA {i} (6 ECTS)." for i in range(listadas or cuantas))
    return _frag(
        nombre=nombre,
        origen="plan_de_estudios",
        codigos=[None],
        texto=f"{nombre}. En total son {cuantas}:\n{cuerpo}",
    )


def _asignatura(grado=GRADO, codigo="12345", nombre="Matemática discreta", tipo="OB"):
    """Un item ``asignatura`` del dataset."""
    return {
        "tipo": "asignatura",
        "grado": grado,
        "codigo": codigo,
        "nombre": nombre,
        "tipo_asignatura": tipo,
        "tiene_guia": True,
    }


def _guia_item(grado=GRADO, codigo="12345", nombre="Matemática discreta"):
    """Un item ``guia`` del dataset."""
    return {"tipo": "guia", "grado": grado, "codigo": codigo, "nombre": nombre}


def _titulacion(nombre=GRADO, doble=False):
    """Un item ``grado`` del dataset."""
    return {"tipo": "grado", "nombre": nombre, "es_doble_grado": doble}


# --- Claves de unidad -------------------------------------------------------


def test_la_clave_usa_el_nombre_cuando_no_hay_codigo():
    """48 asignaturas del corpus no tienen código; agrupar por código las colapsa."""
    assert check_chunks._clave_item(
        {"grado": GRADO, "codigo": "", "nombre": "Sin código"}
    ) == (GRADO, "Sin código")


def test_la_clave_usa_el_codigo_cuando_lo_hay():
    assert check_chunks._clave_item(
        {"grado": GRADO, "codigo": "12345", "nombre": "Matemática discreta"}
    ) == (GRADO, "12345")


def test_un_chunk_compartido_se_expande_a_una_clave_por_titulacion():
    """Tras la deduplicación, una guía puede pertenecer a varias titulaciones."""
    chunk = _frag(grados=[GRADO, DOBLE], codigos=["12345", "12345"])

    assert check_chunks._claves_chunk(chunk) == {(GRADO, "12345"), (DOBLE, "12345")}


def test_un_chunk_sin_codigo_se_expande_con_su_nombre():
    chunk = _frag(nombre="Menciones", grados=[GRADO], codigos=[None])

    assert check_chunks._claves_chunk(chunk) == {(GRADO, "Menciones")}


def test_las_claves_de_un_origen_solo_recogen_ese_origen():
    chunks = [_frag(), _frag(nombre="Otra", origen="salidas", codigos=["999"])]

    assert check_chunks._claves_de_origen(chunks, "guia") == {(GRADO, "12345")}


# --- Forma mínima -----------------------------------------------------------


def test_un_corpus_vacio_falla():
    with pytest.raises(InvarianteRoto, match="no hay chunks"):
        check_chunks._exigir_forma([])


def test_un_chunk_vacio_falla():
    with pytest.raises(InvarianteRoto, match="vacíos"):
        check_chunks._exigir_forma([_frag(texto="   \n  ")])


def test_pasarse_del_maximo_falla():
    """El máximo es la única restricción DURA de tamaño."""
    largo = "x" * (chunker.TAMANO_MAXIMO + 1)

    with pytest.raises(InvarianteRoto, match="por encima del máximo"):
        check_chunks._exigir_forma([_frag(texto=largo)])


def test_el_maximo_exacto_pasa():
    """Es un `<=`: 900 caracteres son válidos, 901 no."""
    check_chunks._exigir_forma([_frag(texto="x" * chunker.TAMANO_MAXIMO)])


def test_grados_y_codigos_deben_ir_en_paralelo():
    with pytest.raises(InvarianteRoto, match="listas paralelas"):
        check_chunks._exigir_forma([_frag(grados=[GRADO, DOBLE], codigos=["12345"])])


def test_un_chunk_sin_ninguna_titulacion_falla():
    with pytest.raises(InvarianteRoto, match="listas paralelas"):
        check_chunks._exigir_forma([_frag(grados=[], codigos=[])])


# --- Encabezados ------------------------------------------------------------


def test_un_encabezado_de_otra_asignatura_falla():
    # IT-91: el encabezado va dentro de `texto`, el único campo que se
    # vectoriza. Si nombra a otra asignatura, el índice afirma algo falso
    # aunque los metadatos estén bien, y el descuadre de cobertura no lo ve
    # porque compara claves, no encabezados.
    chunk = _frag(nombre="Matemática discreta", texto="«Física»\ncontenido.")

    with pytest.raises(InvarianteRoto, match="encabezado de otra unidad"):
        check_chunks._exigir_encabezados([chunk])


def test_el_encabezado_correcto_pasa():
    check_chunks._exigir_encabezados([_frag()])


def test_un_derivado_lleva_su_nombre_sin_comillas():
    """IT-100/IT-107: no nombran una asignatura, sino un listado o una ficha."""
    check_chunks._exigir_encabezados([_plan(), _catalogo(), _ficha()])


def test_un_derivado_con_el_nombre_de_otro_falla():
    chunk = _frag(
        nombre="Menciones del Grado en Ingeniería Informática",
        origen="mencion",
        codigos=[None],
        texto="Menciones de otra cosa. En total son 1:\nUna.",
    )

    with pytest.raises(InvarianteRoto, match="encabezado de otra unidad"):
        check_chunks._exigir_encabezados([chunk])


def test_el_encabezado_de_las_salidas_no_se_comprueba():
    """No es ni asignatura ni derivado: su nombre no encabeza el texto."""
    check_chunks._exigir_encabezados(
        [_frag(nombre="Salidas", origen="salidas", texto="Lo que sea.")]
    )


# --- Listados ---------------------------------------------------------------


def test_un_listado_que_no_declara_cuantas_son_falla():
    chunk = _plan()
    chunk["texto"] = f"{chunk['nombre']}.\nUNA (6 ECTS)."

    with pytest.raises(InvarianteRoto, match="no declara cuántas son"):
        check_chunks._exigir_listados_completos([chunk])


def test_un_listado_que_se_queda_corto_falla():
    # IT-100: un fragmento con 40 asignaturas de las 50 que tiene la
    # titulación se lee igual de bien y es igual de falso.
    with pytest.raises(InvarianteRoto, match="dice tener 10 asignaturas"):
        check_chunks._exigir_listados_completos([_plan(cuantas=10, listadas=4)])


def test_un_listado_que_cuadra_pasa():
    check_chunks._exigir_listados_completos([_plan(cuantas=3)])


def test_solo_se_mira_el_primer_fragmento_de_un_listado_partido():
    """La cifra la declara el primero; el cuerpo se rearma con todos."""
    nombre = f"Asignaturas obligatorias de primer curso del {GRADO}"
    partido = [
        _frag(
            nombre=nombre,
            origen="plan_de_estudios",
            codigos=[None],
            texto=f"{nombre}. En total son 2:\nUNA (6 ECTS).",
            indice=0,
            total=2,
        ),
        _frag(
            nombre=nombre,
            origen="plan_de_estudios",
            codigos=[None],
            texto=f"{nombre}. (continuación)\nOTRA (6 ECTS).",
            indice=1,
            total=2,
        ),
    ]

    check_chunks._exigir_listados_completos(partido)


# --- Catálogo ---------------------------------------------------------------


def test_debe_haber_exactamente_un_catalogo_general():
    with pytest.raises(InvarianteRoto, match="catálogos generales"):
        check_chunks._exigir_catalogo([], [_titulacion()])


def test_el_catalogo_que_no_declara_sus_cifras_falla():
    catalogo = _catalogo()
    catalogo["texto"] = f"{catalogo['nombre']}.\nGrados:\n{GRADO}."

    with pytest.raises(InvarianteRoto, match="no declara cuántas"):
        check_chunks._exigir_catalogo([catalogo], [_titulacion()])


def test_el_catalogo_se_recalcula_contra_el_dataset():
    # IT-107: el contenido de un derivado es un número, y un número
    # equivocado se lee igual de bien que el correcto.
    titulaciones = [_titulacion(), _titulacion(DOBLE, doble=True)]

    with pytest.raises(InvarianteRoto, match="el catálogo dice 1"):
        check_chunks._exigir_catalogo([_catalogo(1, 1, 0)], titulaciones)


def test_el_catalogo_que_cuadra_pasa():
    titulaciones = [_titulacion(), _titulacion(DOBLE, doble=True)]

    check_chunks._exigir_catalogo([_catalogo(2, 1, 1)], titulaciones)


def test_el_catalogo_por_familia_tambien_tiene_que_cuadrar():
    """Es donde se vería que uno de los dos se ha quedado atrás."""
    familia = _frag(
        nombre="Grados que se imparten en la EPSJ",
        origen="catalogo",
        codigos=[None],
        texto="Grados que se imparten en la EPSJ. En total son 9:\nUno.",
    )

    with pytest.raises(InvarianteRoto, match="'Grados'"):
        check_chunks._exigir_catalogo([_catalogo(1, 1, 0), familia], [_titulacion()])


# --- Fichas -----------------------------------------------------------------


def test_una_titulacion_sin_ficha_falla():
    titulaciones = [_titulacion(), _titulacion(DOBLE, doble=True)]

    with pytest.raises(InvarianteRoto, match="alguna se queda sin"):
        check_chunks._exigir_fichas([_ficha()], [_asignatura()], titulaciones)


def test_una_ficha_con_cifras_equivocadas_falla():
    with pytest.raises(InvarianteRoto, match="y el dataset dice"):
        check_chunks._exigir_fichas(
            [_ficha(total=9, obligatorias=9)], [_asignatura()], [_titulacion()]
        )


def test_una_ficha_que_cuadra_pasa():
    asignaturas = [_asignatura(), _asignatura(codigo="222", tipo="OP")]

    check_chunks._exigir_fichas(
        [_ficha(total=2, obligatorias=1, optativas=1)], asignaturas, [_titulacion()]
    )


def test_la_titulacion_cuyo_plan_no_publica_la_fuente_no_declara_cifras():
    """Sin cifras no hay nada que cotejar; no es un error del troceo."""
    ficha = _ficha()
    ficha["texto"] = f"{ficha['nombre']}.\nLa web no publica su plan."

    check_chunks._exigir_fichas([ficha], [_asignatura()], [_titulacion()])


# --- Numeración -------------------------------------------------------------


def test_los_indices_de_una_unidad_van_de_cero_a_n():
    unidad = check_chunks._agrupar_por_unidad(
        [_frag(indice=0, total=2), _frag(indice=5, total=2)]
    )

    with pytest.raises(InvarianteRoto, match="índices rotos"):
        check_chunks._exigir_numeracion(unidad)


def test_total_chunks_tiene_que_decir_la_verdad():
    unidad = check_chunks._agrupar_por_unidad(
        [_frag(indice=0, total=9), _frag(indice=1, total=9)]
    )

    with pytest.raises(InvarianteRoto, match="total_chunks inconsistente"):
        check_chunks._exigir_numeracion(unidad)


def test_una_cola_corta_que_se_podia_fusionar_falla():
    """Si aparece aquí es que `_fusionar_pequenos` ha dejado de funcionar."""
    corto = "«Matemática discreta»\ncorto."
    unidad = check_chunks._agrupar_por_unidad(
        [
            _frag(texto="«Matemática discreta»\n" + "x" * 100, indice=0, total=2),
            _frag(texto=corto, indice=1, total=2),
        ]
    )

    with pytest.raises(InvarianteRoto, match="sí se podían fusionar"):
        check_chunks._exigir_numeracion(unidad)


def test_se_cuentan_las_colas_cortas_irreducibles():
    """Una cola que no cabía junto a su vecino es legítima, pero se cuenta."""
    unidad = check_chunks._agrupar_por_unidad(
        [
            _frag(
                texto="«M»\n" + "x" * (chunker.TAMANO_MAXIMO - 10), indice=0, total=2
            ),
            _frag(texto="«M»\ncola corta.", indice=1, total=2),
        ]
    )

    assert check_chunks._exigir_numeracion(unidad) == 1


def test_una_unidad_de_un_solo_fragmento_no_cuenta_como_corta():
    unidad = check_chunks._agrupar_por_unidad([_frag(texto="«M»\ncorto.")])

    assert check_chunks._exigir_numeracion(unidad) == 0


# --- Cobertura --------------------------------------------------------------


def test_una_guia_del_dataset_sin_fragmentos_falla():
    with pytest.raises(InvarianteRoto, match="faltan 1"):
        check_chunks._exigir_cobertura_de_guias(
            {(GRADO, "12345")}, set(), [_titulacion()]
        )


def test_un_par_de_un_doble_grado_puede_no_tener_item_guia():
    # IT-101: el doble grado no publica guías propias, pero el fragmento de
    # la asignatura cita además la titulación doble donde se imparte.
    dataset = [_titulacion(), _titulacion(DOBLE, doble=True)]

    check_chunks._exigir_cobertura_de_guias(
        {(GRADO, "12345")}, {(GRADO, "12345"), (DOBLE, "12345")}, dataset
    )


def test_un_par_sobrante_que_no_es_de_un_doble_sigue_fallando():
    """Aflojarlo sin esta condición dejaría pasar lo que el verificador busca."""
    with pytest.raises(InvarianteRoto, match="sin ser de un doble grado"):
        check_chunks._exigir_cobertura_de_guias(
            set(), {(GRADO, "12345")}, [_titulacion()]
        )


def test_una_asignatura_que_no_aparece_en_ningun_fragmento_falla():
    # IT-94: una asignatura con `tiene_guia=True` cuya guía no llegó a
    # emitirse no entraba en ninguna de las dos comprobaciones anteriores y
    # desaparecía del corpus mientras el verificador respondía «OK».
    with pytest.raises(InvarianteRoto, match="no aparecen en ningún"):
        check_chunks._exigir_toda_asignatura_representada([_asignatura()], set(), set())


def test_la_asignatura_representada_como_informativo_cuenta():
    check_chunks._exigir_toda_asignatura_representada(
        [_asignatura()], set(), {(GRADO, "12345")}
    )


# --- Guías huérfanas y sin contenido ----------------------------------------


def test_se_listan_las_asignaturas_cuya_guia_no_aporta_nada(capsys):
    check_chunks._informar_guias_sin_contenido([_asignatura()], [])

    salida = capsys.readouterr().out
    assert "1 asignaturas enlazan una guía" in salida
    assert f"- {GRADO} / 12345" in salida


def test_una_guia_sin_asignatura_que_la_declare_falla():
    """O sobra la guía o la asignatura tiene `tiene_guia` a False."""
    with pytest.raises(InvarianteRoto, match="sin asignatura que las declare"):
        check_chunks._informar_guias_sin_contenido([], [_guia_item()])


def test_cuando_todo_cuadra_no_se_avisa(capsys):
    check_chunks._informar_guias_sin_contenido([_asignatura()], [_guia_item()])

    assert capsys.readouterr().out == ""


# --- Procedencia y tamaños --------------------------------------------------


def test_un_corpus_sin_procedencia_pide_regenerarlo(capsys):
    check_chunks._imprimir_procedencia({}, 288)

    assert "anterior a IT-90" in capsys.readouterr().out


def test_un_corpus_de_un_dataset_viejo_lo_dice(capsys):
    """No es un fallo del rastreo: es un dataset anterior a IT-90."""
    check_chunks._imprimir_procedencia({"fecha_troceado": "2026-08-19"}, 288)

    assert "IT-80" in capsys.readouterr().out


def test_la_procedencia_completa_se_informa(capsys):
    check_chunks._imprimir_procedencia(
        {
            "fecha_extraccion": "2026-08-16",
            "fecha_troceado": "2026-08-19",
            "cursos": ["2026-27"],
        },
        288,
    )

    salida = capsys.readouterr().out
    assert "2026-08-16" in salida
    assert "2026-27" in salida


def test_un_corpus_que_mezcla_cursos_se_declara(capsys):
    check_chunks._imprimir_procedencia(
        {
            "fecha_extraccion": "2026-08-16",
            "cursos": ["2025-26", "2026-27"],
            "guias_sin_curso": 3,
        },
        288,
    )

    salida = capsys.readouterr().out
    assert "mezcla varios cursos" in salida
    assert "3 de 288 guias sin curso" in salida


def test_los_tamanos_distinguen_colas_de_unidades_cortas(capsys):
    # Darlas juntas ya despistó: el guion informaba solo de las colas y la
    # memoria recogía el total, así que la misma magnitud aparecía con dos
    # valores según de dónde se copiara.
    chunks = [_frag(texto="x" * 50), _frag(texto="x" * 60), _frag(texto="x" * 800)]

    check_chunks._informar_tamanos(chunks, colas=1)

    salida = capsys.readouterr().out
    assert "min=50" in salida
    assert "2 fragmentos por debajo del mínimo" in salida
    assert "1 son colas" in salida
    assert "1 son unidades enteras" in salida


def test_sin_fragmentos_cortos_no_se_informa_de_ellos(capsys):
    check_chunks._informar_tamanos([_frag(texto="x" * 800)], colas=0)

    assert "por debajo del mínimo" not in capsys.readouterr().out


# --- El recorrido entero ----------------------------------------------------


def _corpus_coherente():
    """Un corpus mínimo que cumple los once invariantes a la vez."""
    chunks = [
        {
            "tipo": "procedencia",
            "fecha_extraccion": "2026-08-16",
            "cursos": ["2026-27"],
        },
        _frag(),
        _catalogo(1, 1, 0),
        _ficha(total=1, obligatorias=1, optativas=0),
        _plan(cuantas=1),
        _frag(
            nombre=f"Salidas profesionales del {GRADO}",
            origen="salidas",
            codigos=[None],
            texto="Salidas profesionales. " * 10,
        ),
    ]
    dataset = [
        _titulacion(),
        _asignatura(),
        _guia_item(),
        {"tipo": "salidas", "grado": GRADO, "texto": "Salidas."},
    ]
    return chunks, dataset


def test_main_recorre_un_corpus_coherente(tmp_path, capsys):
    chunks, dataset = _corpus_coherente()
    ruta_chunks = tmp_path / "chunks.json"
    ruta_dataset = tmp_path / "grados.json"
    ruta_chunks.write_text(json.dumps(chunks), encoding="utf-8")
    ruta_dataset.write_text(json.dumps(dataset), encoding="utf-8")

    assert check_chunks.main([str(ruta_chunks), str(ruta_dataset)]) == 0

    salida = capsys.readouterr().out
    assert "Chunks OK" in salida
    assert "2026-08-16" in salida


def test_main_falla_si_unas_salidas_no_se_trocearon(tmp_path):
    chunks, dataset = _corpus_coherente()
    chunks = [c for c in chunks if c.get("origen") != "salidas"]
    ruta_chunks = tmp_path / "chunks.json"
    ruta_dataset = tmp_path / "grados.json"
    ruta_chunks.write_text(json.dumps(chunks), encoding="utf-8")
    ruta_dataset.write_text(json.dumps(dataset), encoding="utf-8")

    with pytest.raises(InvarianteRoto, match="salidas sin trocear"):
        check_chunks.main([str(ruta_chunks), str(ruta_dataset)])

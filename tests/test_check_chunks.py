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

from tfg_uja import chunker

RAIZ = Path(__file__).resolve().parent.parent
_RUTA = RAIZ / "scripts" / "check_chunks.py"
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

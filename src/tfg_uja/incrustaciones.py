"""Modelo de incrustaciones y su convención de llamada (IT-98, ADR-0003).

El modelo elegido en el ADR-0003, ``intfloat/multilingual-e5-small``, no
trata igual un documento que una consulta: se entrenó con un prefijo que
declara el papel del texto, y su ficha exige usarlo. Un pasaje se incrusta
como ``"passage: ..."`` y una pregunta como ``"query: ..."``.

Ese detalle es la razón de que este módulo exista, en un paquete que es
plano a propósito. El prefijo del documento se aplica **al indexar**
(``indexer.py``) y el de la consulta **al recuperar**, que es código de la
Fase 2 y todavía no está escrito. Si cada lado decidiera por su cuenta, un
día el índice se construiría con ``passage:`` y la consulta llegaría sin
``query:``: no habría error, no fallaría ninguna prueba y la recuperación
sería peor sin que nada lo dijera. Es el mismo patrón de fallo silencioso
que este proyecto ya ha sufrido cuatro veces.

Teniendo los dos incrustadores aquí, el indexador y el recuperador no
pueden discrepar: usan la misma constante o no usan ninguna.

Alternativa descartada: dos constantes públicas en ``indexer.py`` que el
recuperador importase. Cuesta un módulo menos, pero deja el invariante en
manos de que alguien se acuerde de aplicarlas; aquí no hay nada que
recordar, porque los prefijos no se pueden omitir desde fuera.
"""

from __future__ import annotations

from typing import Callable, Final

#: Modelo de incrustaciones del sistema. Elegido en el **ADR-0003** con los
#: resultados de IT-28 sobre dos corpus distintos (892 y 781 fragmentos), en
#: los que gana las tres métricas en ambos. Ya no es provisional: sustituir
#: este valor exige revisar ese ADR.
#:
#: Un dato que no es anecdótico: su ventana de 512 tokens es la única de los
#: cuatro candidatos que da para leer los fragmentos enteros. El modelo
#: anterior se quedaba en 128 y truncaba 685 de los 781, descartando la mitad
#: de los tokens del corpus sin avisar.
MODELO: Final[str] = "intfloat/multilingual-e5-small"

#: Prefijo de los textos que se indexan (los fragmentos del corpus).
PREFIJO_DOCUMENTO: Final[str] = "passage: "

#: Prefijo de los textos que se consultan (las preguntas del usuario).
PREFIJO_CONSULTA: Final[str] = "query: "

#: Firma de la función de incrustación: recibe una lista de textos y
#: devuelve un vector de números reales por texto, en el mismo orden.
Incrustador = Callable[[list[str]], list[list[float]]]


def con_prefijo(prefijo: str, incrustar: Incrustador) -> Incrustador:
    """Envuelve un incrustador para que anteponga el prefijo de papel.

    Se separa del cargado del modelo a propósito: así la convención de
    prefijos se puede probar con un incrustador falso, sin descargar pesos
    ni tocar la red, que es como se prueba el resto del pipeline.

    Args:
        prefijo: :data:`PREFIJO_DOCUMENTO` o :data:`PREFIJO_CONSULTA`.
        incrustar: Incrustador crudo, sin convención de papel.

    Returns:
        Incrustador que aplica el prefijo a cada texto antes de incrustarlo.
    """

    def incrustar_con_papel(textos: list[str]) -> list[list[float]]:
        return incrustar([prefijo + texto for texto in textos])

    return incrustar_con_papel


def cargar_modelo(nombre: str = MODELO) -> Incrustador:
    """Carga el modelo y devuelve un incrustador **sin** convención de papel.

    La importación de ``sentence_transformers`` es perezosa: solo la
    ejecución real la necesita (extra ``[index]`` del proyecto, que arrastra
    PyTorch); las pruebas inyectan un incrustador falso.

    Rara vez hay que llamar a esta función directamente: para indexar y para
    consultar están :func:`incrustador_de_documentos` e
    :func:`incrustador_de_consultas`, que ya aplican el prefijo que toca.
    Queda pública porque el experimento comparativo sí necesita incrustar
    sin prefijo, al evaluar modelos que no usan esa convención.

    Args:
        nombre: Nombre del modelo en el Hub de Hugging Face.

    Returns:
        Función que incrusta lotes de textos tal cual se le pasan.
    """
    from sentence_transformers import SentenceTransformer

    modelo = SentenceTransformer(nombre)

    def incrustar(textos: list[str]) -> list[list[float]]:
        return modelo.encode(textos, show_progress_bar=False).tolist()

    return incrustar


def incrustador_de_documentos(nombre: str = MODELO) -> Incrustador:
    """Incrustador para los fragmentos que van al índice.

    Args:
        nombre: Nombre del modelo en el Hub de Hugging Face.

    Returns:
        Incrustador que antepone :data:`PREFIJO_DOCUMENTO`.
    """
    return con_prefijo(PREFIJO_DOCUMENTO, cargar_modelo(nombre))


def incrustador_de_consultas(nombre: str = MODELO) -> Incrustador:
    """Incrustador para las preguntas del usuario.

    Todavía no lo usa nadie: el recuperador es de la Fase 2. Vive aquí desde
    ya porque su razón de ser es justamente que no lo escriba después otra
    persona con otro criterio.

    Args:
        nombre: Nombre del modelo en el Hub de Hugging Face.

    Returns:
        Incrustador que antepone :data:`PREFIJO_CONSULTA`.
    """
    return con_prefijo(PREFIJO_CONSULTA, cargar_modelo(nombre))

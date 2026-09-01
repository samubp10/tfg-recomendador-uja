"""Pruebas de los validadores de asignaturas (IT-01)."""

from tfg_uja.extraccion.validators import (
    es_asignatura_valida,
    es_placeholder,
    normalizar_tipo,
)

# --- es_placeholder: casos reales de la tabla (Optativa 1..5) ---


def test_reconoce_los_placeholders_de_optativas():
    assert es_placeholder("Optativa 1")
    assert es_placeholder("Optativa 5")
    assert es_placeholder("optativa   3")


def test_una_asignatura_real_no_es_placeholder():
    assert not es_placeholder("Sistemas Operativos")
    assert not es_placeholder("Optatividad y mercado laboral")


# --- normalizar_tipo ---


def test_normaliza_textos_a_abreviaturas():
    assert normalizar_tipo("Formación básica") == "FB"
    assert normalizar_tipo("Obligatoria") == "OB"
    assert normalizar_tipo("Optativa") == "OP"


def test_normaliza_ignora_mayusculas_y_espacios():
    assert normalizar_tipo("  fORmaCión básiCA  ") == "FB"


def test_normaliza_deja_igual_lo_desconocido_o_ya_abreviado():
    assert normalizar_tipo("FB") == "FB"
    assert normalizar_tipo("OB-IS") == "OB-IS"
    assert normalizar_tipo("Otra cosa") == "Otra cosa"


# --- es_asignatura_valida ---


def test_asignatura_normal_es_valida():
    assert es_asignatura_valida("13312001", "Cálculo", "FB")


def test_descarta_los_placeholders_sin_codigo():
    # Caso real: filas "Optativa N" sin código en 4º curso.
    assert not es_asignatura_valida("", "Optativa 3", "OP")


def test_acepta_los_tipos_de_especialidad():
    assert es_asignatura_valida("13312040", "Ingeniería del software", "OB-IS")
    assert es_asignatura_valida("13312050", "Redes", "OB-TI")


def test_descarta_tipo_desconocido():
    assert not es_asignatura_valida("13312001", "Cálculo", "XX")


def test_descarta_nombre_vacio():
    assert not es_asignatura_valida("13312001", "", "FB")


def test_acepta_asignatura_valida_aunque_falte_el_codigo():
    # El código puede faltar en casos legítimos; el nombre y el tipo mandan.
    assert es_asignatura_valida("", "Trabajo Fin de Grado", "OB")


def test_el_tipo_se_valida_sin_importar_mayusculas():
    assert es_asignatura_valida("13312001", "Física", "fb")


# --- TFG como carácter propio (caso real del Grado en IA y Ciberseguridad) ---


def test_acepta_el_tfg_como_tipo_propio():
    # En IA y Ciberseguridad el TFG se etiqueta con carácter "TFG", no "OB".
    assert es_asignatura_valida("", "Trabajo fin de grado", "TFG")

# DQA-0001: Anomalías de la fuente de datos (web EPSJ) y su tratamiento

_Aplicado aquí a anomalías de calidad de datos en lugar de a decisiones de
arquitectura: cada anomalía es demasiado pequeña para justificar un ADR propio,
pero exige la misma evidencia y el mismo rigor que una decisión de diseño._

- **Estado:** aceptada
- **Fecha:** 2026-07-23
- **Anomalías detectadas entre:** 28/06/2026 y 03/07/2026 (ver «Pruebas y evidencia»)
- **Ámbito técnico:** Fase 0 — extracción (`grados_spider.py`) y limpieza de
  texto (`text_cleaner.py`, `validators.py`)

## Contexto

Durante el desarrollo del rastreador se fueron descubriendo, contra los datos
reales de la web de la EPSJ, distintas anomalías estructurales y tipográficas
que no aparecen en ninguna documentación oficial de la fuente. Cada una exigió
una decisión concreta sobre cómo tratarla. Ninguna es, por separado, lo bastante
grande como para justificar un ADR propio, pero conviene dejar constancia de
todas ellas con la misma evidencia y el mismo rigor: qué se observó, dónde, y
qué alternativas se descartaron.

## Anomalías detectadas y tratamiento

### 1. _Slugs_ de URL inconsistentes

- **Evidencia:** los slugs de las URL de titulaciones no siguen un patrón
  estable entre grados (comprobado con un 404 real al intentar construir una
  URL por patrón).
- **Tratamiento:** el rastreador nunca construye una URL por patrón; sigue
  siempre el enlace (`href`) real presente en la página anterior.
- **Alternativa descartada:** construir la URL a partir del nombre de la
  titulación. Descartada por el 404 real observado.

### 2. Tablas híbridas (troncales frente a optativas por mención)

- **Evidencia:** la tabla de asignaturas de un grado combina tablas troncales,
  cuya tercera columna es el tipo (FB, OB, OP...), con tablas de optativas
  agrupadas por mención, cuya tercera columna es la mención en lugar del tipo.
- **Tratamiento:** `parse_asignaturas` distingue una tabla de otra por el
  encabezado de esa tercera columna. En las tablas de mención asigna
  directamente el tipo `OP` y acumula la mención en una lista; cuando una misma
  optativa aparece en varias tablas de mención, sus menciones se fusionan por
  código en lugar de duplicar la asignatura.
- **Alternativa descartada:** tratar cada aparición como una asignatura
  independiente. Descartada porque duplicaba asignaturas que en realidad son
  la misma, solo repetida por mención.

### 3. Nomenclatura inconsistente del Trabajo Fin de Grado

- **Evidencia:** el TFG aparece con tipo propio (`TFG`) en titulaciones de
  implantación reciente (ej. Grado en Inteligencia Artificial y
  Ciberseguridad) y con tipo `OB` en titulaciones más antiguas (fixtures
  `tabla_asignaturas_iayc.html` frente a `tabla_asignaturas.html`).
- **Tratamiento:** `TIPOS_VALIDOS` acepta ambos tipos (`OB` y `TFG`) tal cual
  los declara cada plan.
- **Alternativa descartada:** normalizar todo TFG al mismo tipo. Descartada
  para no imponer una uniformidad que la fuente no tiene y no perder la
  asignatura por una normalización agresiva.

### 4. Filas de relleno (marcadores de posición)

- **Evidencia:** las tablas de matriculación incluyen filas genéricas del
  tipo «Optativa 1», «Optativa 2»... sin código oficial, que no representan
  asignaturas reales (fixture `tabla_asignaturas.html`).
- **Tratamiento:** `es_placeholder` reconoce el patrón `Optativa \d+` y
  `es_asignatura_valida` descarta la fila con independencia de qué otros
  datos traiga.
- **Alternativa descartada:** curación manual del listado de asignaturas por
  titulación. Descartada por no ser reproducible ni escalar a nuevas
  titulaciones sin intervención manual repetida.

### 5. Asignaturas sin guía docente publicada

- **Evidencia:** de 361 asignaturas, 65 no tienen guía docente publicada
  todavía, concentradas en titulaciones de implantación reciente.
- **Tratamiento:** la asignatura se registra igualmente, con `tiene_guia =
False` y `url_guia = None`; no se descarta ni se completa con contenido
  inventado.
- **Alternativa descartada:** omitir la asignatura del catálogo hasta que
  publique guía. Descartada porque el sistema debe poder nombrar y situar la
  asignatura en su titulación aunque no tenga guía, y porque un dato ausente
  se refleja, no se imputa.

### 6. Caracteres invisibles

- **Evidencia:** presencia de espacios duros (`\xa0`) y de espacios de ancho
  cero (`​`) intercalados en el texto extraído.
- **Tratamiento:** `limpiar_texto` sustituye los espacios duros por espacios
  normales, elimina los caracteres de ancho cero y colapsa los espacios y
  saltos de línea múltiples.

### 7. Sufijos de URL duplicados

- **Evidencia:** algunas URL de guías docentes incluyen contenido sobrante
  tras la extensión `.html` (ej. `...es.htmles.html`,
  `...es.html13312025_es.html`; fixture `tabla_asignaturas.html:761` y
  `test_text_cleaner.py`).
- **Tratamiento:** `reparar_url` trunca la URL justo después del primer
  `.html`, al no existir ningún caso legítimo con contenido útil tras esa
  extensión.

### 8. Asteriscos de nota al pie en nombres de asignatura

- **Evidencia:** algunos nombres arrastran un asterisco final que remite a
  una nota al pie de la tabla (ej. «Prácticas externas \*»).
- **Tratamiento:** `quitar_nota_al_pie` retira el asterisco final y los
  espacios que lo rodean; los asteriscos que no están al final del texto no
  se tocan.

### 9. Marca de asignatura no ofertada en el curso

- **Evidencia:** algunas optativas llevan al final del nombre el estado
  «(No ofertada en 2025/26)», que no forma parte del nombre real.
- **Tratamiento:** `separar_oferta` extrae esa marca a un booleano
  (`ofertada`) y devuelve el nombre limpio. El patrón no fija ningún año, por
  lo que sigue funcionando en cursos posteriores; el valor es una foto del
  momento de la extracción, no una propiedad permanente de la asignatura.

### 10. Codificación declarada frente a codificación real

- Cubierta en el ADR-0002 (elección de Scrapy): la guía declara UTF-8 en su
  `<meta>` pero el servidor la sirve en ISO-8859-1; Scrapy prioriza la
  cabecera HTTP y resuelve el problema sin código adicional. No se repite
  aquí para no duplicar contenido.

## Consecuencias

### Positivas

- Cada anomalía tiene una regla determinista y verificada contra datos
  reales, no un parche ad hoc.
- El principio "se refleja, no se imputa" se aplica de forma consistente en
  todo el módulo de extracción.

### Negativas

- La aceptación deliberada de inconsistencias de la fuente (TFG, tablas
  híbridas) traslada la responsabilidad de interpretarlas correctamente a las
  fases posteriores (fragmentador, índice).
- Los patrones de limpieza (`_ANCHO_CERO`, `_NO_OFERTADA`, sufijo `.html`)
  están acotados a los casos observados; una anomalía nueva y distinta no
  detectada en este documento no se corregirá automáticamente.

## Pruebas y evidencia

Las diez anomalías tienen prueba de regresión sobre la página real que las produjo. Las
fixtures son HTML descargado de la EPSJ, nunca datos inventados: un caso sintético no
reproduce las irregularidades de la fuente, que es justamente lo que hay que cubrir.

> **Sobre la columna «Detectada».** Es la fecha del commit que incorpora la prueba de
> regresión de esa anomalía, que es la constancia verificable más próxima al hallazgo:
> el hallazgo en sí no deja rastro en el repositorio, la prueba sí. Cada fecha se puede
> comprobar con `git log -S "def <nombre de la prueba>" -- tests/`.

| # | Anomalía | Detectada | Evidencia | Prueba de regresión |
|---|---|---|---|---|
| 1 | *Slugs* inconsistentes | 28/06/2026 | `grados.html`, `portada_grado.html` | `test_grados_spider.py::test_las_peticiones_van_a_urls_absolutas`, `::test_sigue_cada_grado_del_menu` |
| 2 | Tablas híbridas por mención | 02/07/2026 | `tabla_asignaturas.html` | `test_grados_spider.py::test_no_pierde_las_optativas_de_mencion`, `::test_fusiona_una_asignatura_de_varias_menciones`, `::test_no_duplica_una_optativa_comun_a_varias_menciones` |
| 3 | El TFG con dos tipos distintos | 03/07/2026 | `tabla_asignaturas_iayc.html` frente a `tabla_asignaturas.html` | `test_validators.py::test_acepta_el_tfg_como_tipo_propio`, `test_grados_spider.py::test_iayc_extrae_el_tfg_con_su_caracter_propio`, `::test_extrae_el_trabajo_fin_de_grado` |
| 4 | Filas de relleno | 02/07/2026 | `tabla_asignaturas.html` | `test_validators.py::test_reconoce_los_placeholders_de_optativas`, `::test_descarta_los_placeholders_sin_codigo`, `test_grados_spider.py::test_descarta_los_placeholders_de_optativas` |
| 5 | Asignaturas sin guía publicada | 02/07/2026 | `tabla_asignaturas_iayc.html` | `test_grados_spider.py::test_una_asignatura_sin_guia_se_emite_igualmente`, `::test_iayc_conserva_asignaturas_sin_codigo_ni_guia` |
| 6 | Caracteres invisibles | 01/07/2026 | `tabla_asignaturas.html` | `test_text_cleaner.py::test_elimina_caracteres_de_ancho_cero`, `::test_sustituye_espacios_duros`, `test_grados_spider.py::test_limpia_el_espacio_duro_del_nombre` |
| 7 | Sufijos de URL duplicados | 01/07/2026 | `tabla_asignaturas.html:761` | `test_text_cleaner.py::test_repara_url_con_sufijo_html_repetido`, `::test_repara_url_con_codigo_duplicado`, `test_grados_spider.py::test_repara_la_url_de_guia_rota` |
| 8 | Asteriscos de nota al pie | 02/07/2026 | `tabla_asignaturas.html` | `test_text_cleaner.py::test_quita_el_asterisco_de_nota_al_pie`, `test_grados_spider.py::test_quita_el_asterisco_de_las_practicas_externas` |
| 9 | Marca de no ofertada en el nombre | 03/07/2026 | `tabla_electrica.html` | `test_text_cleaner.py::test_separa_la_marca_de_no_ofertada`, `test_grados_spider.py::test_electrica_marca_las_no_ofertadas_y_limpia_el_nombre`, `::test_electrica_las_demas_se_ofertan` |
| 10 | Codificación declarada en falso | 03/07/2026 | `guia_matematicas_electrica.html` | `test_grados_spider.py::test_decodifica_los_acentos_correctamente` |

Además de las pruebas unitarias, `scripts/check_dataset.py` recorre la colección completa y
comprueba el recuento de entidades, la presencia de los campos obligatorios y la validez de
los tipos de asignatura. Las pruebas cubren los casos conocidos; el verificador cubre el
conjunto entero, que es donde aparecen los desconocidos.

## Cómo se corrige y cómo se detecta si vuelve

Ninguna de estas anomalías produce una excepción, así que **no se detectan mirando si el
rastreo ha terminado bien**. La secuencia que sí las destapa es siempre la misma:

1. Ejecutar `py scripts/check_dataset.py` sobre la colección recién regenerada. Su constante
   `ESPERADO` lleva las cifras a mano, de modo que una diferencia salta sola. Ojo: una
   diferencia puede ser un cambio legítimo de la fuente **o** una pérdida silenciosa, y hay
   que averiguar cuál antes de tocar la constante.
2. Si el recuento de una titulación ha bajado, mirar el registro del rastreo: las filas
   descartadas por no validar se avisan, no se pierden en silencio.
3. Descargar la página real, guardarla como fixture en `tests/fixtures/` y escribir la prueba
   de regresión **antes** de tocar el código, para que reproduzca el fallo.
4. Corregir en el módulo que corresponda ---`text_cleaner.py` para lo tipográfico,
   `validators.py` para lo que decide si una fila es una asignatura, `grados_spider.py` para
   lo estructural--- y volver a ejecutar el verificador sobre la colección completa.

**Lo que no hay que hacer:** editar `data/*.json` a mano. La colección se regenera con el
rastreador y el fragmentador, y un dato corregido a mano desaparece en la siguiente ejecución
sin dejar constancia de que estaba mal.


## Referencias

- `src/tfg_uja/text_cleaner.py`, `src/tfg_uja/validators.py`,
  `src/tfg_uja/grados_spider.py`.
- `tests/fixtures/tabla_asignaturas.html`,
  `tests/fixtures/tabla_asignaturas_iayc.html`, `tests/test_text_cleaner.py`.
- ADR-0002 (elección de Scrapy y resolución de codificación).

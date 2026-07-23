# DQA-0001: Anomalías de la fuente de datos (web EPSJ) y su tratamiento

_Aplicado aquí a anomalías de calidad de datos en lugar de a decisiones de
arquitectura: cada anomalía es demasiado pequeña para justificar un ADR propio,
pero exige la misma evidencia y el mismo rigor que una decisión de diseño._

- **Estado:** aceptada
- **Fecha:** 2026-07-23
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

## Referencias

- `src/tfg_uja/text_cleaner.py`, `src/tfg_uja/validators.py`,
  `src/tfg_uja/grados_spider.py`.
- `tests/fixtures/tabla_asignaturas.html`,
  `tests/fixtures/tabla_asignaturas_iayc.html`, `tests/test_text_cleaner.py`.
- ADR-0002 (elección de Scrapy y resolución de codificación).

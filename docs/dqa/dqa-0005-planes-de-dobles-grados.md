# DQA-0005: Los planes de estudio de los dobles grados

- **Estado:** aceptada
- **Ámbito técnico:** Fase 1 — extracción (`grados_spider.py`, `validators.py`),
  fragmentación (`chunker.py`) y verificación (`check_dataset.py`,
  `check_chunks.py`)

## Contexto

Los cinco dobles grados de la EPSJ no publican sus datos con la misma estructura
que los grados simples. Cuatro enlazan el plan mediante `plan-de-estudios`, las
tablas emplean el rótulo «Carácter» y el valor `OBL`, y los códigos pertenecen a
series distintas de las asignaturas equivalentes en los grados base. Los nombres
aparecen en mayúsculas y algunos incorporan el acrónimo del grado de procedencia.

El Doble Grado en Ingeniería Mecánica internacional no publica plan de estudios,
página de asignaturas ni salidas profesionales. Permanece en el corpus solo con
su nombre; el sistema no puede informar de contenidos que la fuente no ofrece.

## Alternativas consideradas

1. **Buscar una única ruta de plan.** Funciona en los grados simples, pero omite
   los planes publicados bajo `plan-de-estudios`. Seguir ambos `href` reales evita
   construir URL por patrón.
2. **Leer las columnas por posición.** Es más simple, pero cruza los valores cuando
   la fuente cambia el rótulo o intercala una columna. Localizarlas por su cabecera
   admite «Tipo» y «Carácter».
3. **Cruzar asignaturas por código.** Es inequívoco dentro de un plan, pero los
   códigos de los dobles grados no coinciden con los de sus grados base.
4. **Cruzar por nombre normalizado.** Permite reutilizar una guía sin duplicarla,
   aunque depende de que ambas páginas mantengan nombres equivalentes.
5. **Construir una tabla manual de equivalencias.** Resolvería los nombres
   ambiguos, pero introduciría datos no publicados y mantenimiento manual en cada
   rastreo.
6. **Duplicar las salidas profesionales.** Reproduce literalmente las dos listas,
   pero repite las entradas comunes. Conservar la primera aparición mantiene toda
   la información sin dar más peso a las repetidas.
7. **Corregir erratas de la fuente.** Mejora la apariencia del dato, pero deja de
   representar lo publicado. La alternativa es conservar el nombre original.

## Decisión

- `parse_portada` busca primero `asignaturas-y-profesorado` y, si no existe,
  `plan-de-estudios`, siguiendo siempre el enlace real.
- «Carácter» identifica la columna de tipo y `OBL` se normaliza a `OB`.
- El cruce con guías de grados base compara nombres en minúsculas y sin tildes;
  si no hay coincidencia, reintenta sin el acrónimo final entre paréntesis.
- Una coincidencia ambigua no se resuelve por conjetura: se avisa y la asignatura
  recibe un fragmento informativo.
- Las salidas repetidas conservan su primera aparición.
- Las erratas del plan se mantienen tal como las publica la fuente.
- `parse_salidas` incorpora tanto los párrafos introductorios como los elementos
  de lista, porque ambos contienen información profesional publicada.

## Consecuencias

### Positivas

- Los dobles grados con plan publicado aportan asignaturas y reutilizan las guías
  comunes sin duplicar su contenido.
- Los acrónimos se conservan en el dato y solo se ignoran durante la comparación.
- La deduplicación de salidas evita que una entrada repetida desplace a otra.

### Negativas

- El cruce por nombre es más débil que el cruce por código y puede degradarse si
  la fuente cambia la redacción de una asignatura.
- Un nombre que coincide con varias guías queda sin enlazar. `ESTADÍSTICA` es un
  caso conocido y recibe un fragmento informativo aunque existe una guía en un
  grado base cuya correspondencia no se puede determinar.
- Solo un doble grado publica una página propia de salidas; no se puede generalizar
  su estructura a los demás.
- El doble grado internacional queda limitado al nombre por ausencia de datos en
  la fuente.

## Referencias

- `src/tfg_uja/extraccion/grados_spider.py`,
  `src/tfg_uja/extraccion/validators.py` y
  `src/tfg_uja/indexacion/chunker.py`.
- `tests/fixtures/portada_doble_grado.html`,
  `tests/fixtures/plan_doble_electrica_mecanica.html` y
  `tests/fixtures/salidas_doble_electrica_mecanica.html`.
- `tests/test_grados_spider.py` cubre las rutas, el rótulo «Carácter», `OBL`, las
  salidas y los párrafos introductorios; `tests/test_check_dataset.py` limita la
  normalización de acrónimos a titulaciones dobles.
- `scripts/verificadores/check_dataset.py` y
  `scripts/verificadores/check_chunks.py` comprueban la colección completa.
- ADR-0001, clave de deduplicación `(nombre, contenido)`.
- DQA-0003, localización de columnas por rótulo.

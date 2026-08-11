# DQA-0005: Los planes de estudio de los dobles grados

_Anomalía de calidad de datos, con la misma estructura que un ADR: no es una
decisión de arquitectura, pero exige la misma evidencia. Continúa la serie del
DQA-0001 (anomalías de la Fase 0), DQA-0002 (el cambio de formato a PDF),
DQA-0003 (el cambio de estructura de las tablas) y DQA-0004 (guías publicadas
sin contenido)._

- **Estado:** aceptada
- **Fecha:** 2026-08-05
- **Anomalías detectadas:** 05/08/2026 (ver «Pruebas y evidencia»)
- **Ámbito técnico:** Fase 1 — extracción (`grados_spider.py`, `validators.py`),
  fragmentación (`chunker.py`) y verificación (`check_dataset.py`,
  `check_chunks.py`)

## Contexto

Hasta el 05/08/2026 las **cinco titulaciones dobles de la EPSJ figuraban en el
corpus sin una sola asignatura y sin salidas profesionales**. Son 5 de las 12
titulaciones del centro, y el alcance declarado en el Capítulo 1 de la memoria
dice expresamente que se engloban «la totalidad de sus grados simples y dobles
grados oficiales».

El diagnóstico inicial fue que la fuente no publicaba esos datos. **Es falso.**
La fuente los publica; lo que ocurre es que los publica de una forma que el
rastreador no reconocía, y por seis motivos distintos. Ninguno produjo un error:
las titulaciones desaparecían en silencio.

## Anomalías detectadas y tratamiento

### 1. El plan cuelga de otra ruta

- **Evidencia (05/08/2026):** `parse_portada` buscaba un enlace que contuviera
  `asignaturas-y-profesorado`. Cuatro de los cinco dobles grados publican su plan
  bajo `plan-de-estudios`; ninguno tiene el primero. `url_asignaturas` quedaba a
  `None` en los cinco.
- **Tratamiento:** se busca `plan-de-estudios` **en segundo lugar**, solo si el
  primero no está, para no cambiar de página en los grados simples, que traen los
  dos enlaces. Se sigue extrayendo por el `href` real, nunca por patrón.

### 2. La columna se rotula «CARÁCTER» y abrevia «OBL»

- **Evidencia:** en el plan del Doble Grado en Ingeniería Eléctrica y Mecánica la
  cabecera es `Código · ASIGNATURAS · CARÁCTER · ECTS`, y la tercera columna vale
  `OBL` (42 filas) o `TFG` (2). Los grados simples rotulan esa columna «Tipo» y
  escriben `OB`.
- **Consecuencia real:** `_columnas_de_cabecera` no reconocía el rótulo y
  `normalizar_tipo` no mapeaba la abreviatura, de modo que
  `es_asignatura_valida` descartaba **las 44 filas** y la titulación entera se
  perdía con un aviso en el registro del rastreo.
- **Tratamiento:** «carácter» se reconoce como rótulo de la columna de tipo, y
  `OBL` se mapea a `OB`. Es el mismo patrón que ya obligó a localizar las
  columnas por su rótulo en IT-76: **la fuente no es uniforme entre titulaciones,
  y no lo va a ser.**

### 3. Los códigos son de otra serie: no cruzan con los de los grados base

- **Evidencia:** los 44 códigos del doble grado son de la serie `136xxxxx`.
  **Ninguno de los 44 existe en el corpus.**
- **Consecuencia:** la identidad de asignatura fijada en IT-91,
  `(grado, codigo or nombre)`, no permite reconocer que una asignatura del doble
  grado es la misma que la de su grado base. El cruce solo puede ir por nombre.

### 4. Los nombres van en mayúsculas y con el acrónimo del grado de origen

- **Evidencia:** el plan escribe `MATEMÁTICAS I` donde el grado simple escribe
  `Matemáticas I`, y desambigua algunas con el acrónimo de su titulación de
  procedencia: `GESTIÓN FINANCIERA (GIOI)`, `CIRCUITOS (GIE)`.
- **Medición del cruce por nombre**, sobre las 178 asignaturas de los cuatro
  dobles grados con plan publicado:

  | Criterio | Casan |
  |---|---:|
  | Nombre exacto | **0 de 178** |
  | Nombre normalizado (minúsculas, sin tildes) | 80 |
  | Además, reintentando sin el acrónimo entre paréntesis | **170** |
  | Sin casar | **8** |

- **Tratamiento:** el cruce normaliza y, si no casa, reintenta sin el acrónimo.
  Las **8** que quedan son los dos TFG propios de cada doble grado, que
  efectivamente no tienen guía en ningún grado simple: reciben su fragmento
  informativo, que en su caso sí dice la verdad.
- **Nota sobre el nombre:** el acrónimo **se conserva** en el dato. Es lo que
  escribe la fuente y además informa de qué grado procede la asignatura; se
  ignora solo al comparar. `check_dataset.py` admite por eso ese paréntesis, y
  únicamente ese, y únicamente en titulaciones dobles.

### 5. La página de salidas encadena las dos listas sin fusionarlas

- **Evidencia:** la única página de salidas de un doble grado publicada (la del
  Doble Grado en Ingeniería Eléctrica y Mecánica) trae **16 viñetas**, que son la
  concatenación de las de sus dos grados base. **Cuatro aparecen dos veces**, una
  por cada grado: «Elaboración de informes técnicos, peritaciones y tasaciones
  judiciales», «Actividades comerciales y de marketing tecnológico»,
  «Investigación, desarrollo e innovación (I+D+I)» y «Docencia como profesorado
  de Universidad, de Enseñanza Secundaria o Formación Profesional».
- **Tratamiento:** se conserva la primera aparición y se descartan las repetidas.
  Repetir una salida no añade información y sí desplaza a otras del fragmento.

### 6. Un error tipográfico en el nombre de una asignatura

- **Evidencia:** el plan del Doble Grado en Ingeniería Electrónica Industrial y
  Mecánica escribe `TFG ING. ELETRÓNICA INDUSTRIAL (GIEI)`, sin la «c». El mismo
  título aparece bien escrito en otro plan.
- **Tratamiento:** **se refleja, no se corrige** (decisión 9 del proyecto: los
  datos de la fuente no se imputan ni se enmiendan). Es un TFG, así que no tiene
  guía y su fragmento informativo solo lleva metadatos; el impacto sobre la
  recuperación es despreciable. Corregirlo a mano introduciría en el corpus un
  dato que la fuente no dice y abriría la puerta a hacerlo con otros.

## Lo que la fuente sigue sin publicar

El **Doble Grado en Ingeniería Mecánica (Internacional — University of Applied
Sciences Schmalkalden, Alemania)** no publica plan de estudios, ni página de
asignaturas, ni salidas profesionales. Comprobado el 05/08/2026 sobre su portada:
no existe ninguno de los tres enlaces.

Queda por tanto **en el corpus solo con su nombre**, y eso hay que declararlo: el
sistema no podrá decir qué se estudia en él. No es un fallo de extracción y no se
puede arreglar desde este lado.

## Un defecto propio que salió al mirar esto

Al comprobar qué extraía `parse_salidas` de la página del doble grado se
descubrió que la función **solo leía los elementos de lista** (`ul li`) y
descartaba los párrafos del cuerpo. Esos párrafos son los que dicen a qué
profesiones reguladas da acceso el título.

- **Alcance:** afecta a **las siete titulaciones simples**, no solo a los dobles
  grados, y llevaba así desde IT-07. En el Grado en Ingeniería Informática se
  perdían dos párrafos completos.
- **Tratamiento:** los párrafos se recogen y encabezan el texto de salidas.
- **Por qué importa aquí:** es la **quinta** vez en este proyecto que un dato se
  pierde sin que nada falle. La prueba que existía daba por buenas dieciséis
  líneas sobre una página que traía dieciocho: comprobaba lo que el código hacía,
  no lo que la fuente tenía.

## Efecto sobre el corpus

Rastreo del 05/08/2026, curso 2026-27:

| Métrica | Antes | Después |
|---|---:|---:|
| Asignaturas | 350 | **528** |
| Salidas | 7 | **8** |
| Fragmentos | 797 | **884** |
| — de guía | 711 | 761 |
| — plan de estudios | 16 | 24 |
| — informativos (sin guía) | 62 | 86 |
| Fragmentos que citan una titulación doble | **0** | **363** |

De los 363, **329 son fragmentos de guía reaprovechados**: el temario no se
duplica ni una vez. Duplicar las guías bajo la titulación doble habría costado
unos 200 fragmentos de contenido idéntico y habría roto la deduplicación por
clave `(nombre, contenido)` del ADR-0001.

## Amenazas a la validez

1. **El cruce por nombre es más débil que el cruce por código.** Se apoya en que
   la fuente escriba igual la misma asignatura en dos planes distintos. Hoy falla
   en 8 de 178 casos y todos son explicables, pero un cambio de redacción en el
   origen lo degradaría **sin que nada falle**. Lo detectaría el salto en el
   número de fragmentos informativos, no una excepción.
2. **Un nombre ambiguo no se resuelve.** Si un nombre casa con varias guías
   distintas no se engancha a ninguna y se avisa por la salida de error. Ocurre
   hoy con `ESTADÍSTICA`. Esas asignaturas reciben un fragmento informativo que
   dice que no tienen guía publicada, **lo cual es falso**: la tienen, bajo un
   grado base que no se ha sabido determinar. Es la limitación conocida de este
   tratamiento y conviene no dejarla implícita.
3. **Una sola página de salidas de doble grado.** La conclusión de que la página
   propia aporta información que la unión no da está medida sobre **un** caso, el
   único publicado. No se puede generalizar a los otros cuatro.
4. **El corpus cambió después de la comparativa de incrustaciones.** El
   experimento del ADR-0003 corrió sobre 797 fragmentos y el corpus tiene ahora
   884. El orden de los modelos no debería moverse —ya se comprobó estable sobre
   dos corpus distintos—, pero **las cifras absolutas de ese experimento ya no
   corresponden al corpus vigente**, y la comparativa de bases vectoriales
   (IT-31) tiene que correr sobre el corpus nuevo.

## Pruebas y evidencia

Las seis anomalías se descubrieron de una vez, al comprobar por qué cinco de las doce
titulaciones figuraban en el corpus sin una sola asignatura, y todas entraron con la misma
tarjeta. Las tres fixtures son páginas reales del Doble Grado en Ingeniería Eléctrica y
Mecánica, la única titulación doble que publica los tres tipos de página.

> **Sobre la columna «Detectada».** Es la fecha del commit que incorpora la prueba de
> regresión de esa anomalía, que es la constancia verificable más próxima al hallazgo:
> el hallazgo en sí no deja rastro en el repositorio, la prueba sí. Cada fecha se puede
> comprobar con `git log -S "def <nombre de la prueba>" -- tests/`.

| # | Anomalía | Detectada | Evidencia | Prueba de regresión |
|---|---|---|---|---|
| 1 | El plan cuelga de `plan-de-estudios` y no de `asignaturas-y-profesorado` | 05/08/2026 | `portada_doble_grado.html` | `test_grados_spider.py::test_la_portada_de_un_doble_grado_encuentra_su_plan_de_estudios` |
| 2 | La columna se rotula «CARÁCTER» y abrevia «OBL» | 05/08/2026 | `plan_doble_electrica_mecanica.html` | `test_grados_spider.py::test_el_caracter_obl_del_plan_doble_se_normaliza_a_ob`, `::test_el_plan_de_un_doble_grado_da_sus_asignaturas` |
| 3 | Los códigos son de otra serie y no cruzan con los de los grados base | 05/08/2026 | `plan_doble_electrica_mecanica.html` | `test_grados_spider.py::test_las_asignaturas_del_plan_doble_no_enlazan_guia` |
| 4 | Los nombres van en mayúsculas y con el acrónimo del grado de origen | 05/08/2026 | `plan_doble_electrica_mecanica.html` | `test_check_dataset.py` (admite ese paréntesis y solo en titulaciones dobles) |
| 5 | La página de salidas encadena las dos listas sin fusionarlas | 05/08/2026 | `salidas_doble_electrica_mecanica.html` | `test_grados_spider.py::test_un_doble_grado_pide_sus_salidas_profesionales`, `::test_las_salidas_repetidas_de_un_doble_grado_no_se_duplican` |
| 6 | Error tipográfico en el nombre de una asignatura | 05/08/2026 | plan del Doble Grado en Ingeniería Electrónica Industrial y Mecánica | sin prueba propia: se refleja tal cual, no se corrige |
| — | Defecto propio: `parse_salidas` descartaba los párrafos del cuerpo | 05/08/2026 | `salidas_informatica.html` | `test_grados_spider.py::test_las_salidas_recogen_los_parrafos_de_presentacion` |

La última fila no es una anomalía de la fuente sino un defecto del rastreador que salió al
mirar esta, y afecta a las siete titulaciones simples. Se deja aquí porque sin ella el registro
contaría solo la mitad de lo que se encontró.

## Cómo se corrige y cómo se detecta si vuelve

El cruce por nombre es la parte frágil y **se degrada sin que nada falle**: si la fuente
cambia la redacción de una asignatura en uno de los dos planes, deja de casar y la asignatura
recibe un fragmento informativo que dice que no tiene guía.

1. La señal es **el número de fragmentos informativos**, no una excepción. Un salto en esa
   cifra al regenerar la colección significa que el cruce ha empeorado. Lo comprueba
   `py scripts/check_chunks.py`.
2. El cruce normaliza a minúsculas y sin tildes y, si no casa, reintenta sin el acrónimo entre
   paréntesis. Hoy casan 170 de 178; las 8 que no son los dos TFG propios de cada doble grado,
   que efectivamente no existen en ningún grado simple.
3. Si un nombre casa con **varias** guías distintas, la ambigüedad no se resuelve y se avisa
   por la salida de error. Ocurre hoy con `ESTADÍSTICA`. Esa asignatura recibe un fragmento
   que afirma que no tiene guía, **lo cual es falso**, y es la limitación conocida de este
   tratamiento.
4. El acrónimo entre paréntesis **se conserva en el dato** y solo se ignora al comparar: es lo
   que escribe la fuente e informa de qué grado procede la asignatura.

**Lo que no hay que hacer:** construir una tabla de equivalencias a mano entre los códigos de
un doble grado y los de sus grados base. Sería un dato que la fuente no publica, habría que
mantenerlo a mano en cada rastreo y dejaría de ser reproducible desde el propio pipeline.


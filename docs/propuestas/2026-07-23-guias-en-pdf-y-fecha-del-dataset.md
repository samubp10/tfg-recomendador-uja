# Propuestas de tarjeta — 23/07/2026

> **Esto es una propuesta, no un hecho.** Ninguna de estas tarjetas está creada en
> GitHub. Decide tú cuáles se crean, cuáles se fusionan y cuáles se descartan. Si dices
> que sí, el contenido se copia tal cual a la issue sin reescribir nada.

---

## Antes que nada: dos correcciones a lo que dábamos por supuesto

### 1. No es un grado en extinción. Es el cambio de curso académico.

La hipótesis de que el problema se limitaba a un grado en extinción **no se sostiene con
los datos**. Va justo al revés:

| Grado | Guías contaminadas |
|---|---|
| Grado en Ingeniería Geomática y Topográfica **(en extinción)** | **0 de 30** |
| Grado en Inteligencia Artificial y Ciberseguridad | 10 de 10 |
| Grado en Ingeniería Geomática y Topográfica (plan 2025) | 2 de 2 |
| Grado en Ingeniería Informática | 10 de 67 |
| Grado en Ingeniería Eléctrica | 10 de 45 |
| Grado en Ingeniería Electrónica Industrial | 10 de 47 |
| Grado en Ingeniería Mecánica | 10 de 49 |
| Grado en Ingeniería de Organización Industrial | 10 de 46 |

El grado en extinción es hoy **la fuente más limpia que hay**: sus 30 guías siguen en
HTML de 2025-26. El problema afecta a **7 grados**, incluidos los principales.

El criterio real no es el grado, es el curso:

- **62 de 62** guías de **2026-27** llegan como PDF.
- **0** guías de 2026-27 llegan como HTML.
- **234 de 234** guías de 2025-26 siguen llegando como HTML, sin problema.

Las 10 por grado son las asignaturas de primer curso, que son las primeras cuya guía de
2026-27 se publica. **Esto va a crecer**: conforme la EPSJ publique el resto, más guías
migrarán a PDF. Para septiembre podrían serlo todas.

### 2. Sobre eliminar el grado en extinción

Es una decisión razonable y separada de lo anterior, pero conviene verla con el coste
delante:

- Se perderían **111 fragmentos de 892** (12,4 % del corpus).
- Desaparecerían **30 asignaturas**.
- **Ninguno** de esos fragmentos se comparte con otro grado, así que no hay efecto
  colateral sobre los demás.
- **2 de las 36 preguntas** del conjunto de evaluación (IT-27) apuntan a ese grado y
  habría que rehacerlas.

A favor de eliminarlo: un estudiante preuniversitario **no puede matricularse** en un
grado en extinción, así que recomendárselo sería un error, y el sistema no tiene forma de
saber que no debe hacerlo. A favor de mantenerlo: es el 12 % del corpus y ahora mismo la
parte más limpia.

Una tercera vía, que quizá es la buena: **mantenerlo en el corpus pero marcarlo**, para
que el sistema pueda decir «ese grado está en extinción, no admite nuevas matrículas» en
lugar de ignorarlo o de recomendarlo a ciegas. Es más trabajo, pero es más honesto y
mucho más defendible ante un tribunal que borrar datos.

---

## Propuesta A — Extraer las guías servidas en PDF

**Tipo:** Código · **Esfuerzo:** M · **Sección de memoria:** Cap. 4 · **Dependencias:** IT-06

**Historia:** Como responsable de la calidad del corpus, quiero que el rastreador
reconozca las guías servidas en PDF y les extraiga el texto igual que a las de HTML, para
que el cambio de curso académico no vacíe la colección ni la llene de binario.

### Contexto

Al re-rastrear el 23/07/2026 (primer rastreo desde el 09/07) aparece que el servidor
devuelve un PDF detrás de una URL acabada en `.html`:

```
$ curl -sI ".../2026-27/4/157A/15711008/es/2026-27-15711008_es.html"
HTTP/1.1 200 OK
Content-Disposition: inline; filename=guia_docente_2026-27_15711008.pdf
Content-Type: application/pdf
Content-Length: 73363
```

El spider lo trata como HTML, no encuentra la estructura esperada, activa el mecanismo de
respaldo y guarda ~48 000 caracteres de binario crudo. Las guías con respaldo pasan de
**5 a 67**, y una sola guía contaminada genera **43 fragmentos** cuyo campo `texto` —el
único que se vectoriza— empieza por `%PDF-1.6 5 0 obj << /Type /XObject …`.

`check_dataset.py` responde **«Dataset OK»** sobre esos datos.

### El PDF sí sirve: comprobado

Descargado y analizado uno real (`15711008`, Estadística de IA y Ciberseguridad):

- 7 páginas, **texto extraíble, no un escaneo**, sin cifrar, ~18 KB de texto.
- Trae las dos secciones que el proyecto necesita, y bien estructuradas:
  - `RESUMEN` → «Breve resumen de la asignatura (según memoria RUCT)»
  - `DESCRIPCIÓN DE CONTENIDOS` → el temario numerado con sus epígrafes

Es decir: no hay que renunciar a esas 62 guías, hay que saber leerlas.

### ⚠️ El PDF trae datos personales que hoy no entran en el corpus

El PDF incluye una sección `PROFESORADO` con **nombre, departamento, categoría, despacho,
correo electrónico y teléfono** de cada profesor. La colección excluye deliberadamente el
profesorado (decisión 7 del proyecto, y es el argumento sobre el que se sostiene el
apartado de RGPD del Cap. 2: «de la fuente no se obtiene ningún dato personal»).

Si se extrae el PDF sin filtrar, **esa afirmación de la memoria deja de ser cierta**. El
filtrado del bloque `PROFESORADO` no es un detalle de implementación: es un requisito
legal y hay que tratarlo como tal, con su test.

### Definición de Hecho

- [ ] El spider decide por el tipo de contenido de la respuesta, no por la extensión de la URL
- [ ] De un PDF se extraen resumen y temario, con la misma forma de ítem `guia` que desde HTML
- [ ] El bloque `PROFESORADO` se elimina, con un test que falle si se cuela un correo o un teléfono
- [ ] Si el PDF no se puede leer, la asignatura se trata como «sin guía», nunca con el respaldo
- [ ] `check_dataset.py` falla, en vez de decir «OK», si algún campo de texto contiene binario
- [ ] Test de regresión con el PDF real de `15711008`, sin peticiones de red
- [ ] DQA-0002 con la evidencia
- [ ] Un commit por fichero

---

## Propuesta B — Fecha y curso de extracción visibles en el dataset

**Tipo:** Código · **Esfuerzo:** S · **Sección de memoria:** Cap. 4 · **Dependencias:** —

**Historia:** Como cualquiera que abra este proyecto, quiero saber de un vistazo cuándo se
extrajeron los datos y de qué curso son, para no trabajar con una foto vieja creyendo que
es la actual.

### Contexto

Hoy **no hay ninguna fecha en ninguna parte**: ni en `grados.json`, ni en `chunks.json`,
ni en la salida de los verificadores, ni en el README. Comprobado con `grep`: los únicos
años que aparecen en el código están en comentarios de ejemplo.

Eso ya ha hecho daño una vez. El corpus con el que está escrita la memoria es del
**09/07/2026** y es de **2025-26**, pero nada lo dice, así que la memoria habla del corpus
como si fuera atemporal: «5 guías activan el respaldo», «cobertura del 82 %». Ambas cifras
son ciertas para ese snapshot y para ningún otro.

Es además condición previa para lo del cron: un proceso que se ejecute solo, año tras año,
tiene que dejar constancia de cuándo se ejecutó y qué encontró.

### Definición de Hecho

- [ ] `grados.json` y `chunks.json` llevan fecha de extracción y curso(s) detectado(s)
- [ ] El curso **se deduce de las URL reales**, no se escribe a mano en ninguna parte
- [ ] Los tres verificadores imprimen esa fecha al ejecutarse
- [ ] El README dice de cuándo es el conjunto de datos incluido
- [ ] Un aviso claro si el conjunto tiene más de N días (N por decidir)
- [ ] Los ficheros mezclados de dos cursos se detectan y se avisa, que es la situación actual

---

## Propuesta C — ¿Qué hacer con el grado en extinción?

**Tipo:** Experimento o ADR · **Esfuerzo:** S · **Dependencias:** IT-27

No la escribo entera hasta que decidas cuál de las tres vías quieres (eliminar, mantener
tal cual, o mantener marcado). Las tres tienen argumentos y las tres son defendibles; la
que no es defendible es no haberlo decidido.

Lo que sí conviene: **que quede como decisión escrita**, no como omisión. Si un miembro
del tribunal pregunta «¿y si un chaval pregunta por Geomática, le recomendáis el plan
extinguido?», tiene que haber una respuesta.

---

## Sobre las tres tarjetas que creé sin preguntar

IT-67 (#108), IT-68 (#109) e IT-69 (#110) están creadas. Dime qué hago:

- **IT-67** — su contenido ha quedado desfasado con lo que sabemos ahora (creía que el
  problema era «detectar y descartar»; resulta que el PDF sí sirve). Si la mantienes,
  habría que reescribirla con la Propuesta A. Si prefieres, se cierra y se crea limpia.
- **IT-68** e **IT-69** — son la deuda real de IT-27/IT-30 y su contenido sigue siendo
  válido. Se quedan o se cierran, tú dirás.

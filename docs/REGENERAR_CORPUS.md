# Cómo regenerar el corpus de principio a fin

> Procedimiento completo para reconstruir el conjunto de datos desde la web de la EPSJ.
> Está escrito para poder ejecutarse delante de otra persona sin depender de que nadie
> recuerde nada (Definición de Hecho de IT-80).
>
> Última ejecución: **28/07/2026**, curso **2026-27**.

## Antes de empezar

El rastreo hace **peticiones reales** a la web de la Universidad de Jaén: unas 300, con un
segundo de espera entre ellas por respeto al servidor (`DOWNLOAD_DELAY = 1.0`). Tarda entre
6 y 10 minutos. No conviene lanzarlo más veces de las necesarias.

```bash
cd tfg-recomendador-uja
source .venv/Scripts/activate     # Git Bash; en PowerShell: .venv\Scripts\activate
git checkout main && git pull     # el rastreo debe hacerse con el código al día
```

⚠️ **Guarda una copia de lo que ya tienes** antes de sobrescribirlo. `data/` no se versiona,
así que un rastreo fallido sin copia deja el proyecto sin corpus:

```bash
cp data/grados.json data/grados_$(date +%F).json.bak
cp data/chunks.json data/chunks_$(date +%F).json.bak
```

## 1. Rastrear la web

```bash
scrapy runspider src/tfg_uja/grados_spider.py -O data/grados.json
```

**Déjalo en primer plano y espera a que termine.** Si se cierra la sesión con el proceso en
segundo plano, queda vivo golpeando el servidor de la UJA: el 24/07/2026 aparecieron cuatro
procesos huérfanos así. Al acabar, comprueba que no queda ninguno:

```bash
tasklist | grep -i python        # en Windows
```

Durante el rastreo conviene no perder de vista dos avisos:

- `Tabla sin columna de tipo ni de mención` — la fuente ha vuelto a cambiar la estructura de
  alguna tabla y esa titulación se está perdiendo.
- `Guía ... servida como PDF ilegible` — esas asignaturas entrarán al corpus solo con sus
  datos básicos.

## 2. Verificar el dataset

```bash
py scripts/check_dataset.py
```

Comprueba la integridad y **compara el tamaño del corpus con el del último rastreo aceptado**
(la constante `ESPERADO`, al principio del script).

Si falla por las cifras, no las cambies sin más: averigua de dónde sale la diferencia. Un
número distinto puede ser un cambio legítimo de la fuente **o** una pérdida silenciosa de
datos, y el script no puede distinguirlos por ti. Solo cuando esté claro que el cambio es
legítimo se actualiza `ESPERADO` y se anota el porqué.

## 2 bis. Auditar la extracción de los PDF

```bash
py scripts/check_guias_pdf.py
```

Desde IT-95 el rastreo deja una copia de cada PDF en `data/guias_pdf/`, y este
script la compara con lo que se extrajo. **Es el único que puede detectar que la
plantilla de la fuente ha cambiado**: si aparece un rótulo de sección
desconocido, una sección puede estar quedándose corta —se pierde contenido— o
tragándose la siguiente, que en el peor caso arrastra el bloque de profesorado.
Ninguna de las dos cosas falla de forma visible en ningún otro sitio.

Imprime además cuánto se descarta y bajo qué rótulo. Que se conserve una fracción
pequeña del documento es lo esperado: la lista de permitidos deja fuera
evaluación, bibliografía, cláusulas y profesorado a propósito. Lo que hay que
mirar es que los nombres de esa lista sean los de siempre.

⚠️ Los PDF guardados **contienen datos personales del profesorado**. Están en
`data/`, que no se versiona, y son copia local de trabajo: no se publican ni
entran al corpus.

## 3. Fragmentar

```bash
py -m tfg_uja.chunker data/grados.json data/chunks.json
py scripts/check_chunks.py
```

`check_chunks.py` imprime lo primero la procedencia (fecha de extracción y curso, IT-90) y
después las estadísticas del troceo. Verifica, entre otras cosas, que **ninguna asignatura se
ha quedado fuera del corpus** y que el encabezado de cada fragmento es el de su propia
asignatura.

## 4. Comprobar el conjunto de evaluación

```bash
py scripts/check_evalset.py
```

Este es el que más cuidado exige. Sus preguntas se anotaron a mano contra un corpus concreto,
así que al regenerar es normal que alguna deje de resolver.

🔴 **La regla al arreglarlo:** que una pregunta no resuelva **no** significa que la pregunta
esté mal. Hay que averiguar por qué antes de tocarla, porque los motivos son distintos:

| Motivo | Qué hacer |
| --- | --- |
| El nombre de la asignatura ha cambiado porque el rastreo lo extrae mal | **Arreglar la extracción.** La pregunta está bien |
| La asignatura ya tiene guía publicada y antes no | Cambiar el `origen` del selector a `guia` |
| La titulación ha desaparecido del corpus | Rehacer la pregunta apuntando a otra equivalente |

**Nunca se borra una pregunta para que el verificador pase.** Eso falsea el conjunto de
evaluación, que es la única vara de medir del proyecto: sin él no se puede afirmar nada sobre
el rendimiento del sistema.

## 5. Anotar la procedencia

Actualiza `data/GENERADO.md` con la fecha y el curso. Desde IT-90 esa información también
viaja **dentro** de los propios ficheros, así que la nota es solo comodidad; si las dos no
coinciden, la buena es la del fichero.

## 6. Refrescar lo que depende de las cifras

Regenerar cambia el corpus, y con él todo lo que se haya medido sobre él:

- Las cifras del **Capítulo 4** de la memoria.
- El §4 de `Notas_TFG/ESTADO.md`.
- **El experimento de embeddings (IT-28)**, que se midió sobre un número de fragmentos que ya
  no es el actual. Sus resultados no son comparables entre corpus distintos, así que hay que
  volver a ejecutarlo antes de apoyarse en ellos:

  ```bash
  py scripts/experimento_embeddings.py
  ```

## Registro de ejecuciones

| Fecha | Curso | Asignaturas | Guías | Fragmentos | Notas |
| --- | --- | ---: | ---: | ---: | --- |
| 09/07/2026 | 2025-26 | 361 | 296 | 892 | Snapshot inicial. Sin procedencia dentro del fichero (anterior a IT-90) |
| 28/07/2026 | 2026-27 | 350 | 288 | 786 | Primer rastreo con IT-76, IT-77, IT-67 y IT-90. Destapó IT-92, IT-93 e IT-94 |
| 29/07/2026 | 2026-27 | 350 | 288 | 781 | Con IT-95 e IT-96. **Los cuatro verificadores en verde.** Destapó IT-97 |

El rastreo del 29/07 es el primero que cierra el ciclo completo. Lo que dejó:

- **781 fragmentos**: 711 de guía, 62 informativos de asignaturas sin guía y 8 de
  salidas. 279 unidades, 38 de ellas compartidas entre titulaciones.
- Tamaños (mín/mediana/p90/máx): **227 / 1128 / 1234 / 1499**.
- **0 nombres contaminados** por el enlace «Syllabus», que es lo que arreglaba IT-96.
- 5 asignaturas con la guía publicada pero vacía en el origen (DQA-0004); entran al
  corpus con sus datos básicos.
- Conjunto de evaluación: 36 preguntas, 7/7 titulaciones. Hubo que repuntar cuatro
  selectores porque sus asignaturas ya tienen guía, así que el reparto por tipo queda
  en 20 temario · 8 salidas · 6 metadatos · **2 sin guía** (eran 5).

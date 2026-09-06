# IT-54 — Comprobación de instalación en un entorno limpio

Fecha: 6–7 de septiembre de 2026. Procedimiento:
[instalación y puesta en marcha](../instalacion.md), reproducido en el anexo A.

## Entorno y aislamiento

Se crearon `it54-app-20260906` y `it54-ollama-20260906` desde imágenes oficiales.
El primero no tenía `/app` ni caché de Hugging Face; Python solo traía pip.
El segundo utilizó el volumen nuevo `it54-modelos-20260906` y su lista inicial
de modelos estaba vacía. No se montó el repositorio anfitrión ni se copiaron
sus modelos. El código se clonó de GitHub en `/app`, revisión `1ec0484`.
La revisión posterior `dc16b13` solo elimina dos referencias bibliográficas;
no cambia el código probado.

| Componente | Versión o condición observada |
| --- | --- |
| Anfitrión | Windows, 16 GB de RAM, RTX 3060 Laptop de 6 GB |
| Docker Desktop / Engine | 4.69.0 / 29.4.0, Linux amd64, WSL 2 |
| Memoria asignada a Docker | 8.017.600.512 bytes |
| Imagen de aplicación | `python:3.13-slim`; Debian 13.6; Python 3.13.15 |
| Imagen de inferencia | `ollama/ollama:0.32.14` |
| PyTorch | 2.13.0+cpu |
| sentence-transformers / transformers | 5.6.0 / 5.14.1 |
| LanceDB / PyArrow | 0.37.1 / 25.0.1 |
| Modelo generativo | `gemma3:12b`, ID `f4031aab637d`, 8,1 GB |
| Incrustaciones | `intfloat/multilingual-e5-small`, 384 dimensiones |
| Node, añadido para las pruebas del cliente | 20.19.2 |

Digest de la imagen Python:
`sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285`.
Digest de la imagen Ollama:
`sha256:9d30908e41144b1f1da89b9d8e33c07e4aeb43ff41a8660241b1686e2cc330ad`.
Estos identificadores fijan las imágenes observadas; la etiqueta móvil
`python:3.13-slim` podría resolver a otra imagen en una instalación futura.

## Comprobaciones ejecutadas

- Instalación desde cero con `.[dev,index]`, `constraints.txt` y PyTorch CPU.
  `pip check`: ninguna dependencia rota.
- Descarga real de las incrustaciones con `TFG_DESCARGAR_MODELO=1`: vector
  de 384 dimensiones. Segunda carga sin esa variable y con
  `HF_HUB_OFFLINE=1`: también 384. No se necesitó un token de Hugging Face.
- Rastreo completo de la EPSJ: 327 respuestas entre 17:07:36 y 17:15:54 UTC
  del 6 de septiembre. Corpus del curso 2026-27: 528 asignaturas, 288 guías
  y 8 salidas. Se conservan las ausencias de la fuente: un ECTS ausente,
  cinco guías sin resumen ni temario y 108 optativas sin curso declarado.
- `check_dataset.py`, `check_chunks.py`, `check_evalset.py` y
  `check_guias_pdf.py`: terminan correctamente contra el corpus recién obtenido.
- Fragmentación e indexación completas: 1.922 filas en `chunks_epsj`,
  agrupadas en 471 unidades; máximo de 900 caracteres. Índice: 4,4 MiB según
  `du -sh`; caché de Hugging Face: 471 MiB.
- Descarga real de Gemma: primer intento fallido por tiempo de conexión
  agotado en el alojamiento de los pesos; segundo intento completado,
  incluida la verificación SHA-256 de Ollama. No se empleó la copia del anfitrión.
- Aplicación arrancada desde `/app/.venv` con la caché local. `GET /` devuelve
  HTTP 200. `POST /api/chat` para Álgebra devuelve fuentes, texto y `fin: true`.
- `mypy src/tfg_uja/ --ignore-missing-imports`: sin incidencias en 22 ficheros.
- Las dos pruebas del cliente JavaScript pasan tras instalar Node en el
  contenedor. Node no es necesario para servir la interfaz.
- Suite completa con Ollama detenido: 1.391 pruebas pasan, tres integraciones
  saltadas por conexión rechazada y una prueba lenta deseleccionada.
  Cobertura de sentencia: 4.650 sentencias, ninguna sin cubrir (100 %).
- Compilación de la memoria: 143 páginas, sin errores. Anexo revisado en el
  PDF, sin desbordamientos de línea propios. Persisten avisos anteriores de
  destinos duplicados y desbordamientos en otros capítulos.

La primera suite, con Ollama encendido, no terminó en verde: P-002 agotó los
600 segundos de espera y después se interrumpió la ejecución. Docker llegó a
usar casi 2 GiB de intercambio y se observaron unos 0,37 tokens por segundo.
Es evidencia de presión de memoria, no una medición de rendimiento controlada:
el comienzo de esa suite coincidió con la consulta HTTP. Los dos saltos iniciales
del cliente por falta de Node quedaron resueltos al instalarlo y repetir las
pruebas. El resultado sin Ollama no cuenta esas integraciones como aprobadas.
P-001 sí pasó en aquella primera suite. P-002, repetido solo después de
reiniciar los contenedores y sin el servidor web en memoria, pasó en 129,60 s.
El reinicio conservó el corpus, el índice y las cachés; no hubo reinstalación.
P-003 pasó en 91,73 s al ejecutarlo solo tras otro reinicio de Ollama.
Por tanto, los tres casos tienen una ejecución correcta registrada, pero no
se presenta como correcta la primera tanda conjunta ni se oculta su timeout.
El arranque posterior del servidor volvió a entregar HTTP 200 desde la caché
conservada (`data/it54-reinicio.log`). Ambos contenedores quedaron detenidos
al terminar; sus datos y el volumen de modelos se conservaron.

La respuesta HTTP conservada dice: «Álgebra tiene 6 ECTS en el Grado en
Ingeniería Informática». Añade formación básica, primer curso y segundo
cuatrimestre. Los cuatro datos coinciden con el ítem `13311001` del corpus
recién extraído. Entre las fuentes figura su guía oficial. Esto verifica un
recorrido real de la aplicación; no sustituye las 57 observaciones del banco
del sistema ni cambia sus cifras. No se midió el rendimiento de esta instalación.

## Evidencia conservada

Los ficheros en bruto están en el `data/` persistente del repositorio principal,
fuera de árboles de trabajo temporales. No están versionados:

| Evidencia | Fichero en `data/` |
| --- | --- |
| Estado inicial y volumen vacío | `it54-entorno-inicial.log`, `it54-modelos-iniciales.log` |
| Imágenes y configuración | `it54-python-imagen.log`, `it54-ollama-imagen.log`, `it54-contenedores.json` |
| Dependencias | `it54-preparacion.log`, `it54-torch.log`, `it54-dependencias.log`, `it54-pip-freeze.txt`, `it54-node.log` |
| Incrustaciones | `it54-embeddings-descarga.log`, `it54-embeddings-sin-red.log` |
| Descarga del LLM | `it54-gemma-descarga.log`, `it54-gemma-descarga-reintento.log` |
| Corpus y verificadores | `it54-rastreo.log`, `it54-datos-fragmentos.log`, `it54-evalset.log`, `it54-guias.log` |
| Índice y huellas | `it54-indexacion.log`, `it54-datos-identidad.log` |
| Copia del corpus nuevo | `it54-limpio/grados.json`, `it54-limpio/chunks.json` |
| Consulta y contraste | `it54-consulta.ndjson`, `it54-algebra-fuente.log` |
| Pruebas y tipos | `it54-pytest.log`, `it54-pytest-sin-ollama.log`, `it54-pruebas-cliente.log`, `it54-mypy.log` |
| Integración aislada tras reinicio | `it54-integracion-p002-reinicio.log`, `it54-integracion-p003-reinicio.log` |
| Compilación del anexo | `it54-latex/` |

SHA-256 de `grados.json`:
`7d1e054e2723314d76157ec1739a984433f2c3d433c21b120ba065e2a880db72`.
SHA-256 de `chunks.json`:
`48498fe5a68bb0d6ab3bb1fb6f87ef44b8d66cc0d07a1a27e5b04010b83581cb`.
Las copias no sobrescriben el corpus de los experimentos anteriores.

## Alcance

La prueba acredita la instalación en contenedores nuevos sobre este anfitrión.
No acredita una instalación nativa limpia de Windows, macOS o Linux, ni un
mínimo de RAM, ni funcionamiento sin GPU. Tampoco desconectó toda la red:
la comprobación sin Hub se limita a las incrustaciones ya descargadas.

El anexo sigue la organización del Anexo 5 de la memoria de María Ahmed Naz
(PDF local de referencia, páginas 215–218): requisitos, preparación,
configuración y arranque. Los comandos y componentes son los de este sistema.
No se añaden MySQL ni Node al funcionamiento de la aplicación por aparecer
en aquel ejemplo. El texto nuevo de LaTeX queda en turquesa para la revisión
del autor, conforme a las instrucciones del repositorio.

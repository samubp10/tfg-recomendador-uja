# `scripts/`

Guiones que no son parte del sistema pero sí del trabajo: verifican la
colección, miden lo que hace falta medir para decidir, y componen los bancos de
preguntas con los que se mide. **Son código**, con sus pruebas en `tests/`, y no
datos.

Están agrupados por lo que hacen, no por la fase en que se escribieron:

| Carpeta | Qué contiene | Cuándo se ejecuta |
| --- | --- | --- |
| `verificadores/` | Comprueban invariantes de la colección completa | Antes de cada envío, en local: `data/` no está versionado y el CI no puede ejecutarlos |
| `experimentos/` | Miden alternativas para poder decidir con evidencia | Una vez por decisión; varios tardan horas y algunos exigen el servidor de inferencia levantado |
| `bancos/` | Componen los conjuntos de preguntas con los que se mide | Cuando cambia el corpus o el diseño del experimento |

`chat_rag.py` se queda fuera de las tres: no verifica, ni mide, ni compone
nada. Es el cliente de consola del sistema.

## Dos cosas que hay que saber antes de tocarlos

**Resuelven las rutas contra la raíz del repositorio, no contra su propia
carpeta.** Con la agrupación pasaron a estar un nivel más abajo, así que la
raíz es `parent.parent.parent`. Un guion que resuelva mal la raíz no falla: lee
o escribe en el sitio equivocado.

**Cuatro de los experimentos escriben dentro de su \ac{ADR} un bloque de
resultados delimitado por un marcador que lleva su propia ruta.** Si se mueve un
guion hay que mover también la ruta del marcador, en el guion y en el \ac{ADR},
o el bloque deja de encontrarse.

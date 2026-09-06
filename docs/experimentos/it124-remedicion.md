# Repetición del banco sobre el código de entrega (IT-124)

## Procedencia

La ejecución del 06/09/2026 parte de `ee7dfd8`, en
`IT-124-remedir-sistema`. Este commit incluye IT-119, IT-120, IT-121,
IT-123 e IT-125. Las mejoras posteriores de IT-135 se prueban en su rama;
el AST de conversación, recuperación, generación y verificación coincide
entre ambas ramas. El registro del cliente web no participa en el banco.

Se usan los datos extraídos el 16/08/2026, curso 2026-27, y los fragmentos
del 01/09/2026, después de corregir los metadatos de unidades compartidas.
Los cuatro verificadores pasan sobre el corpus completo. Los 1.922 textos
y sus metadatos coinciden con las filas del índice, teniendo en cuenta que
el indexador representa los códigos ausentes con una cadena vacía.
Las huellas SHA-256 del corpus, bancos e índice quedan en
`data/it124-procedencia-20260906.json`.

La recuperación se ha ejecutado de nuevo con
`scripts/experimentos/experimento_recuperacion.py`. El informe regenerado
es idéntico al versionado: R@3/5/10 = 0,644/0,777/0,865;
RU@3/5/10 = 0,906/0,973/0,991; MRR = 0,914. El suelo rechaza 6/10 preguntas
ajenas del conjunto de ajuste y 5/10 del conjunto de validación.

## Qué cifra correspondía a cada registro

| Registro persistente en `data/` | Entradas | Aciertos | Mediana (s) |
| --- | ---: | ---: | ---: |
| `registro_sistema_gemma3.jsonl` | 57 | 57 | 32,19 |
| `registro_sistema_it118.jsonl` | 57 | 56 | 42,33 |
| `registro_sistema_it125.jsonl` | 57 | 57 | 40,05 |

La tabla del capítulo 5 conservaba tiempos de la primera fila; el informe
automático vigente procedía de la tercera. La referencia inmediata para
comparar veredictos es IT-125. El archivo `registro_sistema_it124.jsonl`
solo contiene 17 entradas: es una tanda incompleta, no otra medida del banco.
Las preguntas, turnos y criterios coinciden con los de `9ca732e`;
solo se acortó el comentario `que_prueba` de `S-CONV-002` en IT-114.

El fallo de IT-118 era `G-ASI-0078`: preguntaba por el curso de Simulación
de flujos industriales en el Doble Grado en Ingeniería Electrónica Industrial
y Mecánica. El contexto compartido afirmaba cuarto, aunque el doble grado
la imparte en quinto. IT-125 separó los encabezados según los metadatos de
cada titulación. El commit `9ca732e` y los registros documentan el paso de
56/57 a 57/57; no se atribuye este cambio histórico a IT-135.

## Alcance

Una tanda contiene 57 observaciones del banco. No se suman ni se promedian
tandas. La redacción puede variar aunque el veredicto no cambie.
Los tiempos del guion acumulan los turnos de cada entrada; no son tiempos
por llamada al modelo. El registro no cuenta esas llamadas, por lo que no
se deduce su número de que el texto final coincida con una respuesta fija.

Las ocho conversaciones no intercalan un saludo o rechazo antes de una
elíptica; `S-CONV-006` termina en despedida. La invariancia del banco no
comprueba el defecto de IT-135. Las regresiones del servidor cubren esas
secuencias y el saludo inicial sin antecedente. Además, el guion llama a
los módulos directamente: no evalúa el servidor web ni su decisor de
ámbito opcional, las sugerencias o el registro del cliente.

## Cotas mencionadas en las notas

Las notas previas citan 0,949 para 57/57 y 0,819 para 15/15. Son las cotas
inferiores unilaterales exactas al 95 % para un pleno bajo un modelo binomial:
se obtiene `p = 0,05 ** (1/n)` resolviendo `p ** n = 0,05`.
El cálculo da 0,9488005163 y 0,8189637275, respectivamente. No son los extremos
de un intervalo bilateral al 95 % ni corresponden a un resultado de 56/57.

El banco contiene casos seleccionados, no una muestra aleatoria de consultas
de estudiantes; además, varias preguntas comparten familia y corpus. Estas
cotas condicionales no justifican una garantía sobre usuarios reales. No se
introducen como tal en la memoria. La revisión se refiere a los numeradores
de cada tanda, sin aumentar `n` por repetirla.

## Validación de la entrega

- IT-135: 1.394 pruebas aprobadas, incluidas tres integraciones reales con
  Ollama; 4.650 sentencias cubiertas, 100 %. Mypy, flake8 y CI en verde.
- IT-124: 1.384 pruebas aprobadas, tres integraciones saltadas porque Ollama
  ya estaba apagado y una prueba lenta deseleccionada; cobertura de sentencia
  del 100 %. El banco completo anterior sí terminó con el servidor activo.
- Corpus e índice: los cuatro verificadores pasan y sus huellas permanecen
  iguales después de la medición. El informe de recuperación se reescribe
  sin diferencias de contenido respecto al versionado.
- Memoria compilada en una salida aislada y tablas inspeccionadas en el PDF.
  La compilación termina con tres avisos de destinos del glosario ausentes
  (`gl:LOPDGDD`, `gl:RGPD`, `gl:RNF`), sin errores de LaTeX. Las cifras y las
  indicaciones para revisar la prosa quedan en turquesa.

Las 15 entradas de un turno resueltas por las guardas previas al generador
se comprueban con la pregunta del banco y el número de fragmentos registrado:
cuatro de cortesía, ocho sin fragmentos y tres de otro centro. Esta comprobación
de las rutas del código no convierte el registro en un contador de llamadas.

## Resultado de la nueva tanda

`registro_sistema_it124_20260906.jsonl`: **57/57**, mediana **39,35 s** (39,4 s en el informe). El guion regeneró `it38-sistema.md`. No cambia ningún veredicto frente a IT-125; tampoco cambian los numeradores de las cotas anteriores. La tabla del capítulo 5 recoge las medianas de esta tanda por familia.

Cambian tres textos: `S-CONV-008` conserva la titulación y el listado de primero, omitiendo una frase final sobre optativas; `S-REC-001` y `S-REC-005` varían la explicación y las opciones presentadas, pero siguen nombrando titulaciones del catálogo. No se atribuyen causalmente estas variaciones a una corrección concreta.

En `S-REC-005`, la nueva respuesta rotula «67 asignaturas» como «Créditos». El veredicto `sin_invencion` sigue siendo verdadero porque solo comprueba que recomiende titulaciones existentes. **57/57 no significa que todas las afirmaciones sean correctas**: este error de relación entre rótulo y cantidad queda fuera de ese criterio. No se ha alterado el corrector para cambiar el resultado.

La traza recoge dos retiradas (`S-AJE-007` y `S-AJE-008`); las respuestas de `S-AJE-001` y `S-AJE-009` rechazan lo preguntado sin retirada. El capítulo conservaba un reparto de una retirada y tres rechazos redactados de una tanda anterior; queda señalado para actualizar la redacción.

### Comparación por identificador

| ID | IT-118 | IT-125 | Nueva tanda | Texto frente a IT-125 |
| --- | :---: | :---: | :---: | :---: |
| G-CAT-001 | acierto | acierto | acierto | igual |
| G-ASI-0509 | acierto | acierto | acierto | igual |
| G-ASI-0207 | acierto | acierto | acierto | igual |
| G-ASI-0617 | acierto | acierto | acierto | igual |
| G-ASI-0347 | acierto | acierto | acierto | igual |
| G-ASI-0028 | acierto | acierto | acierto | igual |
| G-ASI-0432 | acierto | acierto | acierto | igual |
| G-ASI-0423 | acierto | acierto | acierto | igual |
| G-ASI-0078 | fallo | acierto | acierto | igual |
| G-MEN-004 | acierto | acierto | acierto | igual |
| G-MEN-005 | acierto | acierto | acierto | igual |
| G-MEN-011 | acierto | acierto | acierto | igual |
| G-MEN-016 | acierto | acierto | acierto | igual |
| G-OPT-005 | acierto | acierto | acierto | igual |
| G-OPT-004 | acierto | acierto | acierto | igual |
| G-OPT-006 | acierto | acierto | acierto | igual |
| G-OPT-002 | acierto | acierto | acierto | igual |
| G-CUR-013 | acierto | acierto | acierto | igual |
| G-CUR-021 | acierto | acierto | acierto | igual |
| G-CUR-041 | acierto | acierto | acierto | igual |
| G-CUR-044 | acierto | acierto | acierto | igual |
| S-CONV-001 | acierto | acierto | acierto | igual |
| S-CONV-002 | acierto | acierto | acierto | igual |
| S-CONV-003 | acierto | acierto | acierto | igual |
| S-CONV-004 | acierto | acierto | acierto | igual |
| S-CONV-005 | acierto | acierto | acierto | igual |
| S-CONV-006 | acierto | acierto | acierto | igual |
| S-CONV-007 | acierto | acierto | acierto | igual |
| S-CONV-008 | acierto | acierto | acierto | distinto |
| S-REC-001 | acierto | acierto | acierto | distinto |
| S-REC-002 | acierto | acierto | acierto | igual |
| S-REC-003 | acierto | acierto | acierto | igual |
| S-REC-004 | acierto | acierto | acierto | igual |
| S-REC-005 | acierto | acierto | acierto | distinto |
| S-REC-006 | acierto | acierto | acierto | igual |
| S-COR-001 | acierto | acierto | acierto | igual |
| S-COR-002 | acierto | acierto | acierto | igual |
| S-COR-003 | acierto | acierto | acierto | igual |
| S-COR-004 | acierto | acierto | acierto | igual |
| S-AJE-001 | acierto | acierto | acierto | igual |
| S-AJE-002 | acierto | acierto | acierto | igual |
| S-AJE-003 | acierto | acierto | acierto | igual |
| S-AJE-004 | acierto | acierto | acierto | igual |
| S-AJE-005 | acierto | acierto | acierto | igual |
| S-AJE-006 | acierto | acierto | acierto | igual |
| S-AJE-007 | acierto | acierto | acierto | igual |
| S-AJE-008 | acierto | acierto | acierto | igual |
| S-AJE-009 | acierto | acierto | acierto | igual |
| S-AJE-010 | acierto | acierto | acierto | igual |
| S-AJE-011 | acierto | acierto | acierto | igual |
| S-AJE-012 | acierto | acierto | acierto | igual |
| S-AJE-013 | acierto | acierto | acierto | igual |
| S-AJE-014 | acierto | acierto | acierto | igual |
| S-AJE-015 | acierto | acierto | acierto | igual |
| S-AMB-001 | acierto | acierto | acierto | igual |
| S-AMB-002 | acierto | acierto | acierto | igual |
| S-AMB-003 | acierto | acierto | acierto | igual |

### Huellas de los registros

- `registro_sistema_it118.jsonl`: `22f1d21d05fccac53d49e672e5b42fc68049576dd8115a8c0e555f66e33b19ff`.
- `registro_sistema_it125.jsonl`: `03d90305eca7f252b5a76ab04a98caffad8d9ad0b23239cafa2074ab65420170`.
- `registro_sistema_it124_20260906.jsonl`: `162dcad1cbddc98ea8f714af5588d5bc50371d8b84223554430fc9c0f2e65b09`.

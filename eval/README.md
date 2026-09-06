# Alcance del banco del sistema

`preguntas_sistema.json` contiene 57 entradas, ocho de ellas conversaciones.
Ninguna intercala una respuesta fija antes de una continuación elíptica.
La despedida de `S-CONV-006` ocupa el último turno. Por tanto, mantener los
veredictos del banco no demuestra que un saludo o un rechazo intercalado
conserve el antecedente (IT-135).

Las regresiones de `tests/test_servidor.py` comprueban ese recorrido con el
estado de conversación real: pregunta sustantiva, saludo o rechazo de otro
centro y continuación; también saludo inicial y continuación sin antecedente.
`tests/test_conversacion.py` comprueba que una ventana de cero vacía las
preguntas guardadas y conserva por separado la intención y la titulación.

El guion del banco invoca conversación, recuperación y generación directamente;
no ejecuta el servidor web, sus sugerencias ni el registro de conversaciones.
Sus resultados no validan esos contratos del cliente.

## Registro del chat

`coincide_con_respuesta_fija` comprueba igualdad textual con el catálogo de
respuestas fijas, incluida la retirada posterior a una generación. No mide
llamadas al modelo. Sustituye a `respuesta_del_generador` y al anterior
`modelo_llamado`, cuyos nombres atribuían al dato un alcance que no tenía.
`decisor_consultado` indica si se obtuvo una decisión de ámbito, incluido un
fallo del decisor. Ambos campos son independientes; no suman llamadas.

## Comparación entre mediciones

Se comparan los veredictos por identificador sobre las mismas 57 entradas.
Repetir una tanda no aumenta el tamaño del banco ni permite sumar observaciones.
El texto puede variar entre la primera llamada tras cargar el modelo y las
siguientes, incluso con los parámetros de generación fijados. Durante una
medición no se deben lanzar otras inferencias contra el mismo servidor.

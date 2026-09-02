# Gestión del contexto conversacional (IT-106)

> Salida literal de `scripts/experimentos/experimento_conversacion.py`, capturada de
> su ejecución sobre el índice del corpus de 1.922 fragmentos. **No editar las cifras
> a mano.** El guion todavía no escribe este fichero por su cuenta, a diferencia de
> los demás experimentos: lo que hay debajo es su salida estándar tal cual.

Reproducir con:

```
py scripts/experimentos/experimento_conversacion.py
```

## Salida

```
Conversaciones derivadas del dataset: 39
   cambia_el_curso           25
   cambia_la_titulacion       3
   sujeto_en_la_respuesta    11

Índice: indice_lance · K = 20 · modelo intfloat/multilingual-e5-small

estrategia         cambia_el_curso  cambia_la_titulaci  sujeto_en_la_respu    TOTAL
-----------------------------------------------------------------------------------
sola                         0.040               0.333               1.000    0.333
concatenada                  1.000               0.333               1.000    0.949
conversacion                 1.000               1.000               1.000    1.000

MRR de la unidad esperada (mismo orden de familias):
sola                         0.002               0.022               0.275    0.080
concatenada                  0.653               0.022               0.275    0.498
conversacion                 0.807               1.000               1.000    0.877

Coste de preparar la consulta (ms por pregunta):
   sola           mediana 0.001 · máximo 0.003
   concatenada    mediana 0.592 · máximo 0.800
   conversacion   mediana 1.599 · máximo 2.196
```

## Qué mide y qué no

- **Unidad recuperada** es la proporción de conversaciones en las que el fragmento que
  responde a la pregunta de seguimiento entra entre los recuperados con `K = 20`.
- **MRR** es la media del inverso del puesto que ocupa ese fragmento.
- Las conversaciones **no están escritas a mano**: se derivan de `data/grados.json`, de
  modo que se sabe por construcción qué unidad debería recuperarse.
- El experimento **no llama a ningún modelo generativo**: solo compara tres formas de
  construir la consulta que se incrusta.
- Las 39 conversaciones salen del propio corpus, así que estas cifras no dicen nada sobre
  cómo formularía sus preguntas un estudiante real.

## Diferencia con la tanda anterior

Sobre el corpus de la extracción del 16/08/2026 —el de antes de corregir los metadatos de
las guías compartidas en IT-125— cuatro celdas daban otro valor, todas de la estrategia
`sola`: 0,080 en `cambia_el_curso` (hoy 0,040), 0,359 en el total de unidad (hoy 0,333),
0,005 y 0,082 en los MRR correspondientes (hoy 0,002 y 0,080). Las estrategias
`concatenada` y `conversacion` dieron exactamente las mismas cifras en las dos tandas.

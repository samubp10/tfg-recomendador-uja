# Modelo grande frente a modelo pequeño: cuándo compensa cada uno

> **Datos:** ejecución del 04/08/2026, corpus de 797 fragmentos (rastreo del 01/08/2026,
> curso 2026-27) y 50 preguntas de `eval/preguntas_evaluacion.json`. Máquina del autor:
> Ryzen 7 5800H, 16 GB de RAM, PyTorch 2.13.0 **solo-CPU**.
> **Alimenta:** ADR-0003 (elección del modelo) e IT-49 (estudio de ablación).
> **Fuente de las cifras:** `docs/experimentos/it28-embeddings.md`. Si no coinciden, manda
> ese fichero, que lo escribe el propio script.

Esta nota separa una pregunta que en la tabla de resultados queda escondida: **el modelo
grande recupera mejor, así que ¿por qué no usarlo?** La respuesta no es «porque sí» ni
«porque el pequeño ya vale»; depende de cuántas veces se paga cada coste y de qué se pierde
exactamente.

---

## 1. Los dos candidatos, y por qué este par y no otro

`multilingual-e5-small` y `multilingual-e5-large` son **el mismo modelo a dos tamaños**:
misma familia, mismo entrenamiento, mismos prefijos `query:`/`passage:`, misma ventana de
512 tokens. Es el único par de la comparativa que **aísla el efecto del tamaño**: cualquier
diferencia entre ellos no puede atribuirse ni a la arquitectura, ni a los datos de
entrenamiento, ni a la convención de prefijos, porque son idénticos.

| | e5-small | e5-large | Factor |
|---|---:|---:|---:|
| Parámetros | 118 M | 560 M | 4,7× |
| Dimensiones del vector | 384 | 1024 | 2,7× |
| Ventana | 512 | 512 | 1× |
| Licencia | MIT | MIT | — |

## 2. Qué se gana

| Métrica | e5-small | e5-large | Diferencia |
|---|---:|---:|---:|
| **RU@3** (encuentra la unidad en el top 3) | 0,945 | **0,995** | +0,050 |
| **RU@5** | 0,970 | **1,000** | +0,030 |
| **RU@10** | 1,000 | 1,000 | 0 |
| R@3 (cobertura por fragmento) | 0,771 | **0,831** | +0,060 |
| R@5 | 0,835 | **0,936** | +0,101 |
| MRR | 0,881 | **0,948** | +0,067 |

Traducido a preguntas concretas, que es como hay que contarlo: sobre 50 preguntas,
**RU@3 pasa de 47,25 a 49,75 aciertos**. El grande gana **dos preguntas y media**.

Y hay un matiz que la media esconde. Por tipo de pregunta (Recall@5):

| Tipo | n | e5-small | e5-large | Dónde está la diferencia |
|---|---:|---:|---:|---|
| listado | 14 | 1,000 | 1,000 | Empate perfecto |
| sin_guia | 2 | 1,000 | 1,000 | Empate perfecto |
| temario | 20 | 0,782 | 0,878 | Diferencia moderada |
| salidas | 8 | 0,812 | **1,000** | El grande no falla ninguna |
| **metadatos** | 6 | **0,602** | **0,870** | **Aquí está el grueso** |

**El pequeño no es peor en todo: es peor en dos sitios concretos.** Empata en las preguntas
de listado y en las de asignaturas sin guía, y pierde sobre todo en las de **metadatos**
(cuántos créditos tiene una asignatura, de qué tipo es) y en las de **salidas
profesionales**. Eso es accionable: son consultas que se podrían atender filtrando por
metadatos en el índice —para eso está `tipo_asignatura` desde IT-100— en vez de pagando un
modelo 4,7 veces mayor.

## 3. Qué cuesta

| Coste | e5-small | e5-large | Factor |
|---|---:|---:|---:|
| Incrustar el corpus entero (797 fragmentos) | 61 s | 486 s | **8×** |
| Tamaño del índice (797 × dim × 4 bytes) | 1,2 MB | 3,1 MB | 2,7× |
| Memoria de los pesos en RAM (fp32) | ~0,5 GB | ~2,2 GB | 4,4× |

⚠️ **La columna de tiempo hay que leerla con cuidado.** Es reloj de pared en un portátil que
está haciendo otras cosas. Entre dos ejecuciones seguidas del 04/08/2026 **todas las
métricas de calidad salieron idénticas a tres decimales**, pero los tiempos variaron hasta
un 25 %. Sirve para decir «uno tarda un orden de magnitud más que el otro», no para afinar.

Y un dato que no es teórico: **la primera ejecución de la comparativa murió** cargando
e5-large, con 3,8 GB libres de 15,4. Hubo que bajar el lote de 32 a 8 y liberar cada modelo
antes de cargar el siguiente. En esta máquina el grande no es «más lento»: es **el que está
al borde de no caber**.

## 4. Cuántas veces se paga cada coste

Esta es la parte que decide, y la que la tabla de resultados no dice.

| Operación | Frecuencia | Cuesta e5-small | Cuesta e5-large |
|---|---|---:|---:|
| Incrustar el corpus (reindexar) | **Rara**: al regenerar el dataset. Van 4 veces desde julio | 61 s | 486 s |
| Incrustar **una consulta** | **Cada vez que alguien pregunta** | ~ms | ~ms |
| Buscar en el índice | Cada consulta | 1,2 MB a recorrer | 3,1 MB |
| Tener el modelo cargado | Mientras el servicio esté vivo | ~0,5 GB | ~2,2 GB |

El coste de **incrustar el corpus** —el factor 8×, el más llamativo— es justo el que **casi
no se paga**: la reindexación es un proceso por lotes que se lanza cuando cambia el dataset,
y que tarde uno u ocho minutos no lo nota ningún usuario.

Lo que sí se paga en cada consulta es incrustar la pregunta (un texto corto, milisegundos en
ambos) y **tener el modelo residente en memoria**. Ahí el grande se lleva 2,2 GB de una
máquina de 16 GB en la que además tiene que caber un LLM cuantizado para la Fase 2. **Ese es
el coste real, y no es de tiempo: es de memoria.**

🔴 **Por tanto, el argumento honesto NO es «el grande tarda 8 veces más».** Ese factor mide
lo que menos importa. El argumento es: *en la máquina donde este sistema se va a demostrar,
el modelo de recuperación tiene que convivir con el modelo generativo, y 2,2 GB frente a
0,5 GB es la diferencia entre que quepa y que no.*

## 5. Cuándo usar cada uno

**e5-small es la elección por defecto, y sostiene:**
- La máquina de la defensa es esta, con 16 GB y sin GPU utilizable, y en la Fase 2 tendrá
  que compartirla con un LLM.
- RU@10 = 1,000: **el corpus correcto siempre está en los diez primeros**. Si la Fase 2
  acaba metiendo más contexto en el prompt, la diferencia se anula sola.
- Lo que pierde está localizado (metadatos, salidas), y el filtrado por metadatos es una vía
  más barata de recuperarlo que cambiar de modelo.

**e5-large compensaría si se diera alguna de estas:**
- Hay GPU disponible: con 6 GB de VRAM los 2,2 GB de pesos dejan de ser un problema y el
  factor 8× de tiempo se desploma.
- El sistema se despliega en un servidor y no en el portátil del autor.
- Se decide operar con **K = 3** y no más: es donde la brecha es mayor (0,945 frente a
  0,995) y donde 2,5 preguntas de 50 sí pesan.
- Las preguntas de metadatos resultan ser mayoritarias en uso real y el filtrado por
  metadatos no las arregla.

**Ninguno de los dos** si aparece un modelo con la calidad del grande y el tamaño del
pequeño. `bge-m3` no lo es: con tamaño de grande saca RU@3 = 0,950, prácticamente el del
pequeño.

## 6. Lo que esta nota NO afirma

- **No se ha medido la latencia de una consulta**, ni con uno ni con otro. Todo lo de §4
  sobre el coste por consulta es razonamiento sobre el tamaño de la operación, **no
  medición**. Es lo primero que hay que medir si esta decisión se pone en duda.
- **No se ha medido el consumo de memoria del sistema completo** (recuperador + LLM) porque
  el LLM todavía no está elegido (ADR-0005, Fase 2). El argumento de §4 se apoya en que 2,2
  GB frente a 0,5 GB es una diferencia grande sobre 16 GB, no en una medición del conjunto.
- Las 50 preguntas son un conjunto pequeño y hecho por una sola persona. Una diferencia de
  2,5 preguntas **está dentro de lo que podría mover una anotación distinta**. No conviene
  presentar el 0,995 frente al 0,945 como una separación establecida.

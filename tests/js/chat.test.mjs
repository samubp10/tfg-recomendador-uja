/*
  Pruebas del cliente del asistente (IT-45).

  `chat.js` eran 475 líneas sin una sola prueba, y no es código accesorio: es lo
  que convierte el texto del modelo en lo que el estudiante lee. Un fallo aquí
  no rompe nada visiblemente ---la página carga igual--- y deja la respuesta mal
  presentada, que es peor.

  Se prueba `formatear()` sobre todo, porque de ella depende que una respuesta
  de listado se vea como un plan de estudios y no como un párrafo corrido. El
  estilo que lo consigue distingue el rótulo de curso por su FORMA ---un párrafo
  cuyo único hijo es una negrita---, así que si `formatear` cambiara de salida,
  la hoja de estilo dejaría de encontrarlo y nadie se enteraría.

  Se ejecuta con `node --test tests/js/`, sin ninguna dependencia: `node:test`
  viene con el intérprete. `tests/test_chat_js.py` lo lanza desde pytest para
  que la tanda siga siendo un solo comando.
*/

import assert from "node:assert/strict";
import { test } from "node:test";

import { cargarChat } from "./dom_minimo.mjs";

const chat = cargarChat();
const { formatear, escapar, horaActual, agruparFuentes, contarLaEspera } = chat;

// ------------------------------------------------------------------ párrafos

test("un texto llano es un párrafo", () => {
  assert.equal(formatear("Hola."), "<p>Hola.</p>");
});

test("una línea en blanco separa dos párrafos", () => {
  assert.equal(formatear("Uno.\n\nDos."), "<p>Uno.</p><p>Dos.</p>");
});

test("dos líneas seguidas son el mismo párrafo con un salto", () => {
  assert.equal(formatear("Uno.\nsigue."), "<p>Uno.<br>sigue.</p>");
});

test("un texto vacío no produce marcado", () => {
  assert.equal(formatear(""), "");
  assert.equal(formatear("\n\n"), "");
});

// --------------------------------------------------------------------- listas

test("los tres signos de viñeta abren lista", () => {
  for (const signo of ["*", "-", "•"]) {
    assert.equal(
      formatear(`${signo} Álgebra (6 ECTS)`),
      "<ul><li>Álgebra (6 ECTS)</li></ul>",
      `falla con «${signo}»`
    );
  }
});

test("un párrafo después de una lista la cierra", () => {
  assert.equal(
    formatear("* Uno\nY esto ya no es lista."),
    "<ul><li>Uno</li></ul><p>Y esto ya no es lista.</p>"
  );
});

// ------------------------------------------------------- el rótulo de curso

test("«**Primer curso:**» es un párrafo en negrita, NO un elemento de lista", () => {
  /*
    Regresión de la que depende que el listado se lea como un plan.

    La línea empieza por asterisco, así que la tentación es tratarla como
    viñeta; lo que la salva es que `esItem` exige el signo SEGUIDO DE ESPACIO.
    Si esto se rompiera, el rótulo de curso caería dentro de la misma lista que
    las asignaturas, la agrupación por curso desaparecería, y la hoja de estilo
    dejaría de encontrar el encabezado sin que fallara nada.
  */
  assert.equal(
    formatear("**Primer curso:**"),
    "<p><strong>Primer curso:</strong></p>"
  );
});

test("el rótulo mantiene la forma que busca la hoja de estilo", () => {
  // `p:has(> strong:only-child)`: la negrita tiene que ser el ÚNICO hijo.
  const salida = formatear("**Segundo curso:**");
  assert.match(salida, /^<p><strong>[^<]+<\/strong><\/p>$/);
});

test("una respuesta de listado agrupa por curso", () => {
  const salida = formatear(
    ["Aquí tienes:", "", "**Primer curso:**", "", "* Álgebra (6 ECTS)"].join("\n")
  );
  assert.equal(
    salida,
    "<p>Aquí tienes:</p>" +
      "<p><strong>Primer curso:</strong></p>" +
      "<ul><li>Álgebra (6 ECTS)</li></ul>"
  );
});

// -------------------------------------------------------------------- negrita

test("la negrita funciona dentro de un elemento de lista", () => {
  assert.equal(
    formatear("* **Álgebra**: 6 ECTS"),
    "<ul><li><strong>Álgebra</strong>: 6 ECTS</li></ul>"
  );
});

test("un asterisco suelto no abre negrita", () => {
  assert.equal(formatear("2 * 3 = 6"), "<p>2 * 3 = 6</p>");
});

// -------------------------------------------------------------------- escapado

test("el texto del modelo no puede entrar como marcado", () => {
  /*
    La respuesta la escribe un modelo a partir de fragmentos de una web ajena:
    es texto de origen no confiable. Que no haya llegado nunca una etiqueta no
    es garantía de nada.
  */
  const salida = formatear("<script>alert(1)</script>");
  assert.ok(!salida.includes("<script>"), salida);
  assert.ok(salida.includes("&lt;script&gt;"), salida);
});

test("escapar neutraliza los tres caracteres que abren marcado", () => {
  assert.equal(escapar("<b>"), "&lt;b&gt;");
  assert.equal(escapar("a & b"), "a &amp; b");
});

test("el escapado ocurre antes que la negrita", () => {
  // Si fuera al revés, `**<b>x</b>**` metería una etiqueta de verdad.
  const salida = formatear("**<b>x</b>**");
  assert.ok(!salida.includes("<b>"), salida);
  assert.ok(salida.includes("<strong>"), salida);
});

// ----------------------------------------------------------------------- hora

test("la hora se escribe con dos cifras y dos puntos", () => {
  assert.match(horaActual(), /^\d{2}:\d{2}$/);
});

// ------------------------------------------------- las fuentes, por titulación

test("las unidades se agrupan por la titulación que las imparte", () => {
  const grupos = agruparFuentes([
    { nombre: "Álgebra", titulacion: "G. Informática", origen: "Guía" },
    { nombre: "Física", titulacion: "G. Mecánica", origen: "Guía" },
    { nombre: "Cálculo", titulacion: "G. Informática", origen: "Guía" },
  ]);

  assert.deepEqual(
    // `Array.from` y no `.map`: ver la nota sobre realms en dom_minimo.mjs.
    Array.from(grupos, ([t, u]) => [t, Array.from(u, (x) => x.nombre)]),
    [
      ["G. Informática", ["Álgebra", "Cálculo"]],
      ["G. Mecánica", ["Física"]],
    ]
  );
});

test("se conserva el orden de llegada, que es el de proximidad", () => {
  /*
    El recuperador devuelve las unidades ordenadas por lo que se parecen a la
    pregunta. Ordenar los grupos alfabéticamente escondería cuál fue la más
    próxima, que es justo el dato que un tribunal querría comprobar.
  */
  const grupos = agruparFuentes([
    { nombre: "b", titulacion: "Zeta", origen: "Guía" },
    { nombre: "a", titulacion: "Alfa", origen: "Guía" },
  ]);

  assert.deepEqual(Array.from(grupos, ([t]) => t), ["Zeta", "Alfa"]);
});

test("una unidad compartida por varias titulaciones es un grupo propio", () => {
  /*
    El servidor compone la titulación juntando todas en las que se imparte. Esa
    cadena no se parte aquí: «Álgebra en Informática y en Mecánica» es un caso
    distinto de «Álgebra en Informática», y fundirlos diría de más.
  */
  const grupos = agruparFuentes([
    { nombre: "Álgebra", titulacion: "G. Informática · G. Mecánica", origen: "Guía" },
    { nombre: "Cálculo", titulacion: "G. Informática", origen: "Guía" },
  ]);

  assert.equal(grupos.length, 2);
});

test("una unidad sin titulación no se pierde", () => {
  const grupos = agruparFuentes([{ nombre: "x", titulacion: "", origen: "Guía" }]);

  assert.equal(grupos.length, 1);
  assert.equal(grupos[0][1].length, 1);
});

test("sin fuentes no hay grupos", () => {
  assert.equal(agruparFuentes([]).length, 0);
});

// --------------------------------------------------------- las dos fases

test("la espera empieza diciendo que busca, no que redacta", () => {
  const cuerpo = chat.document.createElement("div");
  const espera = contarLaEspera(cuerpo);
  try {
    const aviso = cuerpo.hijos.at(-1);
    assert.match(aviso.textContent, /^Buscando en la información de la Escuela…/);
  } finally {
    espera.parar();
  }
});

test("la fase cambia cuando llegan las fuentes, no por un cronómetro", () => {
  /*
    Es lo que hace que el aviso diga la verdad: mientras no han llegado las
    fuentes la recuperación sigue en marcha, y en cuanto llegan quien tarda es
    el modelo. Un umbral de segundos habría dicho «redactando» aunque la
    búsqueda continuara.
  */
  const cuerpo = chat.document.createElement("div");
  const espera = contarLaEspera(cuerpo);
  try {
    const aviso = cuerpo.hijos.at(-1);
    espera.redactando();
    assert.match(aviso.textContent, /^Redactando la respuesta…/);
  } finally {
    espera.parar();
  }
});

test("al parar, el aviso deja de refrescarse", () => {
  // Si el intervalo quedara vivo, el proceso de pruebas no terminaría solo.
  const cuerpo = chat.document.createElement("div");
  const espera = contarLaEspera(cuerpo);
  espera.parar();
  assert.ok(true);
});

// ===========================================================================
//  El recorrido completo: pregunta, emisión por partes y pie de la respuesta
// ===========================================================================
/*
  Hasta aquí se probaban las funciones puras. Lo que sigue prueba `preguntar()`,
  que es la que de verdad usa el estudiante: manda la consulta, va pintando lo
  que llega línea a línea y compone el pie. Sin estas pruebas, más de la mitad
  del fichero ---toda la lectura del flujo NDJSON--- no la ejecutaba nadie.

  Nunca se sale a la red: el `fetch` del contexto es un doble que devuelve un
  cuerpo ya escrito. El servidor de inferencia no interviene en ningún momento.
*/

/** Reloj que se puede adelantar, para llegar a los umbrales sin esperarlos. */
function relojFalso() {
  let ahora = Date.now();
  const F = function (...args) {
    return new Date(...args);
  };
  F.now = () => ahora;
  F.avanzar = (segundos) => {
    ahora += segundos * 1000;
  };
  return F;
}

/**
 * Arma una respuesta con el mismo formato que emite el servidor: una línea
 * JSON por unidad verificada.
 *
 * `trozos` permite partir el cuerpo por donde se quiera, incluso a mitad de una
 * línea, que es el caso que obliga a `preguntar` a guardar el resto.
 */
function respuestaNdjson(sucesos, { ok = true, status = 200, trozos, alLeer } = {}) {
  const partes = trozos ?? [sucesos.map((s) => JSON.stringify(s) + "\n").join("")];
  const codificador = new TextEncoder();
  let i = 0;
  return {
    ok,
    status,
    body: {
      getReader: () => ({
        read() {
          if (alLeer) alLeer();
          if (i >= partes.length) return Promise.resolve({ value: undefined, done: true });
          return Promise.resolve({ value: codificador.encode(partes[i++]), done: false });
        },
      }),
    },
  };
}

/**
 * Carga el cliente con un servidor de mentira detrás.
 *
 * `responder` cambia lo que contestará la SIGUIENTE consulta a `/api/chat`.
 * El saludo ya no entra por ahí: tiene su propia ruta, que es justo lo que
 * evita que el arranque quede anotado en el registro como una pregunta.
 */
function montar({
  sugerencias = [],
  sugerenciasFallan = false,
  reloj,
  saludoFallaAlArrancar = false,
  saludoNoOk = false,
  saludo = "Hola, soy el asistente.",
} = {}) {
  let siguiente = () => respuestaNdjson([{ parte: "Hola." }, { fin: true }]);
  const peticiones = [];
  const fetchDoble = (url, opciones) => {
    peticiones.push({ url, opciones });
    if (url === "/api/saludo") {
      if (saludoFallaAlArrancar) return Promise.reject(new Error("Failed to fetch"));
      if (saludoNoOk) return Promise.resolve({ ok: false, status: 500 });
      return Promise.resolve({ ok: true, json: () => ({ respuesta: saludo }) });
    }
    if (url === "/api/sugerencias") {
      return sugerenciasFallan
        ? Promise.resolve({ ok: false, status: 500 })
        : Promise.resolve({ ok: true, json: () => sugerencias });
    }
    // Se le pasan las opciones para que una prueba pueda mirar la senal de
    // cancelacion; las que no la necesitan simplemente ignoran el argumento.
    return Promise.resolve(siguiente(opciones));
  };
  const contexto = cargarChat({ fetch: fetchDoble, reloj });
  return {
    chat: contexto,
    peticiones,
    el: (id) => contexto._elementos.get(id),
    responder: (fn) => {
      siguiente = fn;
    },
  };
}

/** Deja que terminen el saludo de arranque y la petición de sugerencias. */
async function reposar() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setImmediate(r));
}

/**
 * Una respuesta que no llega nunca y que se rompe al cancelarla.
 *
 * Es lo que hace `fetch` de verdad con una señal de `AbortController`: la
 * promesa se rechaza con un error cuyo `name` es `AbortError`, y de ese nombre
 * depende que el cliente distinga cancelar de fallar.
 */
function prometeAbortable(opciones) {
  return new Promise((_, rechazar) => {
    opciones.signal.addEventListener("abort", () => {
      const fallo = new Error("The user aborted a request.");
      fallo.name = "AbortError";
      rechazar(fallo);
    });
  });
}

/** La última burbuja del asistente, con las piezas que `chat.js` rellenó. */
function ultimaRespuesta(montaje) {
  const fila = montaje.el("mensajes").hijos.at(-1);
  return {
    fila,
    burbuja: fila.querySelector(".mensaje__burbuja"),
    cuerpo: fila.querySelector(".mensaje__cuerpo"),
    pie: fila.querySelector(".mensaje__pie"),
  };
}

test("al arrancar NO se toca /api/chat: el saludo tiene su propia ruta", async () => {
  /*
    Prueba de regresión del defecto que destapó la auditoría del 29/08/2026.
    El saludo se pedía a `/api/chat` con la palabra «Hola», y el servidor anota
    en el registro todo lo que entra por ahí: cada apertura de la página metía
    un turno que nadie había escrito, así que cualquier recuento sobre el
    registro salía inflado. Lo que hay que guardar no es que el saludo se pinte
    ---eso ya se veía--- sino que la consulta no llegue a existir.
  */
  const m = montar();
  await reposar();

  assert.deepEqual(
    m.peticiones.map((p) => p.url),
    ["/api/saludo", "/api/sugerencias"]
  );
});

test("el texto del saludo lo pone el servidor, no el cliente", async () => {
  // Se le pide al servidor para que no haya dos copias que puedan separarse.
  // Si alguien lo escribe en `chat.js` «para ahorrarse una petición», esta
  // prueba lo dice: el cliente pinta lo que le manden, sea lo que sea.
  const m = montar({ saludo: "Buenas, esto lo decide el servidor." });
  await reposar();

  const { burbuja, cuerpo } = ultimaRespuesta(m);
  assert.ok(cuerpo.innerHTML.includes("esto lo decide el servidor"), cuerpo.innerHTML);
  // Y sin la marca de «escribiendo»: el saludo llega entero de una vez, no
  // por partes, así que dejarla puesta anunciaría un texto que no va a venir.
  assert.equal(burbuja.getAttribute("aria-busy"), null);
  // Y la persona no ha escrito nada, así que su lado sigue vacío.
  const propias = m.el("mensajes").hijos.filter((f) => f.classList.contains("mensaje--propio"));
  assert.equal(propias.length, 0);
});

test("si el saludo falla no se pinta nada y no se avisa", async () => {
  /*
    Nadie ha pedido este saludo, así que un fallo suyo no es un fallo de la
    persona: se calla, igual que hace la petición de sugerencias. Se comprueban
    las dos formas de fallar, porque no pasan por el mismo sitio: que la red no
    llegue a responder y que el servidor conteste con un error.
  */
  for (const averia of [{ saludoFallaAlArrancar: true }, { saludoNoOk: true }]) {
    const m = montar(averia);
    await reposar();

    assert.equal(m.el("mensajes").hijos.length, 0, JSON.stringify(averia));
  }
});

test("la pregunta de la persona sí se pinta, y escapada", async () => {
  const m = montar();
  await reposar();
  await m.chat.preguntar("¿Tiene <b>Informática</b> mención en videojuegos?");

  const propia = m.el("mensajes").hijos.filter((f) => f.classList.contains("mensaje--propio"));
  assert.equal(propia.length, 1);
  assert.ok(propia[0].innerHTML.includes("&lt;b&gt;Informática&lt;/b&gt;"), propia[0].innerHTML);
  assert.ok(!propia[0].innerHTML.includes("<b>"), propia[0].innerHTML);
});

test("una pregunta en blanco no llega a salir", async () => {
  const m = montar();
  await reposar();
  const antes = m.peticiones.length;

  await m.chat.preguntar("   \n  ");

  assert.equal(m.peticiones.length, antes);
});

test("mientras hay una consulta en curso no se admite otra", async () => {
  /*
    El modelo atiende en serie: encolar una segunda consulta solo consigue que
    las dos tarden más. La segunda tiene que caerse en la primera línea de
    `preguntar`, antes de gastar ninguna petición.
  */
  const m = montar();
  await reposar();
  const antes = m.peticiones.length;

  await Promise.all([m.chat.preguntar("Primera"), m.chat.preguntar("Segunda")]);

  assert.equal(m.peticiones.length, antes + 1);
});

test("el texto se acumula trozo a trozo aunque una línea llegue partida", async () => {
  /*
    El servidor emite una línea JSON por unidad, pero el flujo se corta por
    donde quiere la red: una línea puede llegar a mitad. Si el resto no se
    guardara, `JSON.parse` reventaría y la respuesta se quedaría a medias.
  */
  const m = montar();
  await reposar();
  m.responder(() =>
    respuestaNdjson(null, {
      trozos: ['{"parte":"Primera frase. "}\n{"parte":"Segun', 'da frase."}\n\n{"fin":true}\n'],
    })
  );

  await m.chat.preguntar("¿Qué se estudia?");

  assert.equal(ultimaRespuesta(m).cuerpo.innerHTML, "<p>Primera frase. Segunda frase.</p>");
});

test("al terminar se retira la marca de «escribiendo»", async () => {
  /*
    De `aria-busy` cuelga lo que un lector de pantalla anuncia mientras la
    respuesta se escribe. Dejarla puesta diría para siempre que sigue llegando
    texto que ya no va a llegar.
  */
  const m = montar();
  await reposar();
  await m.chat.preguntar("¿Cuántos créditos son?");

  assert.ok(ultimaRespuesta(m).burbuja.atributosQuitados.includes("aria-busy"));
});

test("una respuesta retirada borra lo pintado en vez de añadir debajo", async () => {
  /*
    El servidor retira la respuesta a media emisión cuando nombra una
    titulación que no existe, y lo que manda después la sustituye entera. Si el
    cliente añadiera debajo, el estudiante leería las dos: la retirada y la
    buena.
  */
  const m = montar();
  await reposar();
  m.responder(() =>
    respuestaNdjson([
      { parte: "En el Grado en Astrofísica" },
      { borrar: true },
      { parte: "No tengo esa información." },
      { fin: true },
    ])
  );

  await m.chat.preguntar("¿Hay Grado en Astrofísica?");

  const { cuerpo } = ultimaRespuesta(m);
  assert.equal(cuerpo.innerHTML, "<p>No tengo esa información.</p>");
  assert.ok(!cuerpo.innerHTML.includes("Astrofísica"), cuerpo.innerHTML);
});

test("una respuesta que no llega a consultar al modelo se marca como inmediata", async () => {
  /*
    Las respuestas fijas ---cortesía, contexto vacío, otro centro--- vuelven en
    décimas de segundo. Sin marcarlas, esa rapidez se lee como un error.
  */
  const m = montar();
  await reposar();
  await m.chat.preguntar("Gracias, adiós");

  const { fila, pie } = ultimaRespuesta(m);
  assert.ok(fila.classList.contains("mensaje--inmediato"), fila.className);
  assert.ok(pie.innerHTML.includes("respuesta inmediata"), pie.innerHTML);
  assert.ok(pie.innerHTML.includes("Respuesta completa."), pie.innerHTML);
});

test("una respuesta que sí llega al modelo dice cuánto ha tardado", async () => {
  const reloj = relojFalso();
  const m = montar({ reloj });
  await reposar();
  m.responder(() =>
    respuestaNdjson([{ parte: "Son 240 ECTS." }, { fin: true }], {
      alLeer: () => reloj.avanzar(3),
    })
  );

  await m.chat.preguntar("¿Cuántos créditos tiene el grado?");

  const { fila, pie } = ultimaRespuesta(m);
  assert.ok(!fila.classList.contains("mensaje--inmediato"), fila.className);
  // La coma decimal, no el punto: la interfaz está en español.
  assert.ok(pie.innerHTML.includes("6,0 s"), pie.innerHTML);
});

// --------------------------------------------------------- cuando algo falla

test("un error del servidor se cuenta en la burbuja en vez de perderse", async () => {
  const m = montar();
  await reposar();
  m.responder(() => respuestaNdjson([], { ok: false, status: 503 }));

  await m.chat.preguntar("¿Qué salidas tiene?");

  const { fila, cuerpo } = ultimaRespuesta(m);
  assert.ok(fila.classList.contains("mensaje--fallo"), fila.className);
  assert.ok(cuerpo.innerHTML.includes("No se ha podido obtener"), cuerpo.innerHTML);
});

test("el error no enseña el detalle técnico del navegador", async () => {
  // Se veia el mensaje que compone el navegador, en ingles, y la palabra
  // «servidor de inferencia», que es vocabulario de dentro del proyecto.
  const m = montar();
  await reposar();
  m.responder(() => {
    throw new Error("Failed to fetch");
  });

  await m.chat.preguntar("¿Qué salidas tiene?");

  const { cuerpo } = ultimaRespuesta(m);
  assert.ok(!cuerpo.innerHTML.includes("Failed to fetch"), cuerpo.innerHTML);
  assert.ok(!cuerpo.innerHTML.includes("inferencia"), cuerpo.innerHTML);
});

test("un error emitido a media respuesta también se cuenta", async () => {
  const m = montar();
  await reposar();
  m.responder(() => respuestaNdjson([{ error: "el modelo no respondió" }]));

  await m.chat.preguntar("¿Qué salidas tiene?");

  const { fila, cuerpo } = ultimaRespuesta(m);
  assert.ok(fila.classList.contains("mensaje--fallo"), fila.className);
  assert.ok(cuerpo.innerHTML.includes("No se ha podido obtener"), cuerpo.innerHTML);
});

test("una consulta fallida deja UN solo mensaje de error, no dos", async () => {
  // El saludo de arranque usa la misma funcion que una pregunta normal. Con
  // la red caida pintaba su propio error nada mas abrir la pagina, y al
  // preguntar aparecia el segundo: dos mensajes identicos para una sola
  // accion de la persona. Una llamada silenciosa tiene que fallar en silencio.
  const m = montar({ saludoFallaAlArrancar: true });
  await reposar();
  assert.equal(m.el("mensajes").hijos.length, 0, "el saludo no debe dejar rastro");

  m.responder(() => {
    throw new Error("Failed to fetch");
  });
  await m.chat.preguntar("¿Qué salidas tiene?");

  const fallos = m
    .el("mensajes")
    .hijos.filter((f) => f.classList.contains("mensaje--fallo"));
  assert.equal(fallos.length, 1, `mensajes de error: ${fallos.length}`);
});

// ------------------------------------------------ el envio vacio y cancelar

test("el envío nace apagado y se enciende al escribir", async () => {
  const m = montar();
  // Hay que dejar terminar el saludo de arranque: mientras esta en marcha el
  // boton no esta apagado, esta en modo cancelar, que es otra cosa.
  await reposar();
  const boton = m.el("enviar");
  const entrada = m.el("entrada");
  assert.equal(boton.disabled, true, "con el cuadro vacio no hace nada");

  entrada.value = "¿Qué salidas tiene?";
  entrada.disparar("input");
  assert.equal(boton.disabled, false);

  entrada.value = "   ";
  entrada.disparar("input");
  assert.equal(boton.disabled, true, "solo espacios sigue siendo vacio");
});

test("enviar con el cuadro vacío no llega al servidor", async () => {
  const m = montar();
  await reposar();
  const antes = m.peticiones.filter((p) => p.url === "/api/chat").length;

  m.el("entrada").value = "   ";
  m.el("redaccion").disparar("submit");
  await reposar();

  const despues = m.peticiones.filter((p) => p.url === "/api/chat").length;
  assert.equal(despues, antes, "no debe salir ninguna consulta");
});

test("mientras se responde, el envío se convierte en cancelar", async () => {
  const m = montar();
  await reposar();
  m.responder((opciones) => prometeAbortable(opciones));

  const enMarcha = m.chat.preguntar("¿Qué salidas tiene?");
  await reposar();

  const boton = m.el("enviar");
  assert.equal(boton.disabled, false, "cancelar tiene que poder pulsarse");
  assert.equal(boton.getAttribute("aria-label"), "Cancelar la consulta en curso");
  assert.ok(boton.classList.contains("redaccion__enviar--cancelar"));

  m.el("redaccion").disparar("submit");
  await enMarcha;

  assert.equal(boton.getAttribute("aria-label"), "Enviar consulta");
  assert.ok(!boton.classList.contains("redaccion__enviar--cancelar"));
});

test("cancelar devuelve la pregunta al cuadro para poder corregirla", async () => {
  const m = montar();
  await reposar();
  m.responder((opciones) => prometeAbortable(opciones));

  const pregunta = "¿Qué salidas tiene Mecánica?";
  const enMarcha = m.chat.preguntar(pregunta);
  await reposar();
  m.el("redaccion").disparar("submit");
  await enMarcha;

  const { fila, cuerpo } = ultimaRespuesta(m);
  assert.ok(cuerpo.innerHTML.includes("Consulta cancelada"), cuerpo.innerHTML);
  assert.ok(!fila.classList.contains("mensaje--fallo"), "cancelar no es un fallo");
  assert.equal(m.el("entrada").value, pregunta);
});

test("un flujo sin texto ninguno no se da por respuesta buena", async () => {
  /*
    Un flujo que termina sin una sola parte dejaría la burbuja vacía y con la
    espera dentro para siempre. Se trata como fallo, que es lo que es.
  */
  const m = montar();
  await reposar();
  m.responder(() => respuestaNdjson([{ fin: true }]));

  await m.chat.preguntar("¿Y esto?");

  const { fila, burbuja } = ultimaRespuesta(m);
  assert.ok(fila.classList.contains("mensaje--fallo"), fila.className);
  // Aun fallando, la marca de «escribiendo» se retira: es la red de seguridad
  // del `finally`, sin la cual una caída la dejaría puesta indefinidamente.
  assert.ok(burbuja.atributosQuitados.includes("aria-busy"));
});

// ------------------------------------------------------------- sugerencias

test("las sugerencias de arranque las decide el servidor", async () => {
  const m = montar({ sugerencias: ["¿Qué grados hay?", "¿Qué salidas tiene Mecánica?"] });
  await reposar();

  assert.deepEqual(
    Array.from(m.el("sugerencias").hijos, (b) => b.textContent),
    ["¿Qué grados hay?", "¿Qué salidas tiene Mecánica?"]
  );
  assert.ok(m.el("sugerencias").hijos.every((b) => b.classList.contains("sugerencia")));
});

test("las sugerencias se repintan con las que manda cada turno", async () => {
  const m = montar({ sugerencias: ["La vieja"] });
  await reposar();
  m.responder(() =>
    respuestaNdjson([
      { parte: "Informática tiene tres menciones." },
      { sugerencias: ["¿Cuáles son?"] },
      { fin: true },
    ])
  );

  await m.chat.preguntar("¿Tiene menciones?");

  assert.deepEqual(
    Array.from(m.el("sugerencias").hijos, (b) => b.textContent),
    ["¿Cuáles son?"]
  );
});

test("si el servidor no da sugerencias, no se pinta ninguna", async () => {
  /*
    Un botón con una pregunta que el índice no respalda es peor que ningún
    botón: promete una respuesta que el sistema no tiene. Sin sugerencias la
    conversación funciona igual, escribiendo.
  */
  const m = montar({ sugerenciasFallan: true });
  await reposar();

  assert.equal(m.el("sugerencias").hijos.length, 0);
});

test("pulsar una sugerencia pregunta lo que pone en el botón", async () => {
  const m = montar({ sugerencias: ["¿Qué grados hay?"] });
  await reposar();
  const boton = m.el("sugerencias").hijos[0];

  m.el("sugerencias").disparar("click", { target: boton });
  await reposar();

  assert.equal(
    JSON.parse(m.peticiones.at(-1).opciones.body).pregunta,
    "¿Qué grados hay?"
  );
});

test("un clic fuera de una sugerencia no pregunta nada", async () => {
  const m = montar({ sugerencias: ["¿Qué grados hay?"] });
  await reposar();
  const antes = m.peticiones.length;

  m.el("sugerencias").disparar("click", { target: m.chat.document.createElement("div") });
  await reposar();

  assert.equal(m.peticiones.length, antes);
});

test("mientras se responde, las sugerencias quedan deshabilitadas", async () => {
  /*
    De poco sirve bloquear el cuadro de texto si los atajos siguen vivos: son
    la vía más fácil de encolar una segunda consulta sin querer.
  */
  const m = montar({ sugerencias: ["¿Qué grados hay?"] });
  await reposar();
  const boton = m.el("sugerencias").hijos[0];

  const enCurso = m.chat.preguntar("¿Y las prácticas?");
  assert.equal(boton.disabled, true);
  assert.equal(m.el("entrada").disabled, true);

  await enCurso;
  assert.equal(m.el("entrada").disabled, false);
});

// ----------------------------------------------------- las fuentes, el cuadro

test("el pie ofrece las fuentes y el botón abre el cuadro agrupado", async () => {
  const m = montar();
  await reposar();
  m.responder(() =>
    respuestaNdjson([
      {
        fuentes: [
          { nombre: "Álgebra", titulacion: "G. Informática", origen: "Guía docente" },
          { nombre: "Cálculo", titulacion: "G. Informática", origen: "Guía docente" },
          { nombre: "Física", titulacion: "G. Mecánica", origen: "Guía docente" },
        ],
      },
      { parte: "Álgebra y Cálculo son de primero." },
      { fin: true },
    ])
  );

  await m.chat.preguntar("¿Qué asignaturas hay en primero?");

  const boton = ultimaRespuesta(m).pie.hijos.at(-1);
  assert.equal(boton.textContent, "Fuentes (3)");

  boton.disparar("click");
  assert.equal(m.el("fuentes").vecesAbierto, 1);
  const html = m.el("fuentes-lista").innerHTML;
  assert.equal((html.match(/fuentes__grupo/g) ?? []).length, 2);
  assert.ok(html.includes("G. Informática"), html);
  assert.ok(html.includes("Guía docente"), html);
});

test("la fuente enlaza a su página oficial, y sin ella va sin enlace", async () => {
  /*
    El cuadro decía de dónde salía cada cosa pero no dejaba llegar hasta ella:
    para comprobar un dato había que buscarlo a mano en la web de la Escuela.
    Las 81 asignaturas sin guía publicada no tienen a dónde apuntar y van sin
    enlace, que es lo correcto: fabricar uno mandaría a una página inexistente
    para aparentar que todo está respaldado.
  */
  const m = montar();
  await reposar();
  m.responder(() =>
    respuestaNdjson([
      {
        fuentes: [
          {
            nombre: "Álgebra",
            titulacion: "G. Informática",
            origen: "Guía docente",
            url: "https://uvirtual.ujaen.es/pub/es/ficha/13011009",
          },
          {
            nombre: "Estadística",
            titulacion: "G. Informática",
            origen: "Asignatura sin guía publicada",
            url: "",
          },
        ],
      },
      { parte: "Ahí van." },
      { fin: true },
    ])
  );

  await m.chat.preguntar("¿Qué se da en primero?");
  ultimaRespuesta(m).pie.hijos.at(-1).disparar("click");
  const html = m.el("fuentes-lista").innerHTML;

  assert.ok(html.includes('href="https://uvirtual.ujaen.es/pub/es/ficha/13011009"'), html);
  // Sin `noopener`, la página que se abre puede manipular a la que la abrió.
  assert.ok(html.includes('rel="noopener noreferrer"'), html);
  // La que no tiene guía aparece, pero como texto: ni <a> ni href vacío.
  assert.ok(html.includes("Estadística"), html);
  assert.equal((html.match(/<a /g) ?? []).length, 1, html);
});

test("una dirección que no es web no llega a ser enlace", async () => {
  // Las direcciones vienen del dataset, que se extrae de la web de la EPSJ por
  // su `href` real: son datos de fuera. Un `javascript:` en un `href` se
  // ejecuta al pulsarlo, así que se comprueba el esquema en vez de confiar en
  // que el dataset venga limpio. Sin enlace la unidad se sigue viendo.
  const m = montar();
  await reposar();
  m.responder(() =>
    respuestaNdjson([
      {
        fuentes: [
          {
            nombre: "Álgebra",
            titulacion: "G. Informática",
            origen: "Guía docente",
            url: '" onmouseover="alert(1)',
          },
          {
            nombre: "Cálculo",
            titulacion: "G. Informática",
            origen: "Guía docente",
            url: "javascript:alert(1)",
          },
        ],
      },
      { parte: "Ya está." },
      { fin: true },
    ])
  );

  await m.chat.preguntar("¿Y esto?");
  ultimaRespuesta(m).pie.hijos.at(-1).disparar("click");
  const html = m.el("fuentes-lista").innerHTML;

  assert.equal((html.match(/<a /g) ?? []).length, 0, html);
  assert.ok(!html.includes("onmouseover"), html);
  assert.ok(!html.includes("javascript:"), html);
  // Y las dos unidades se siguen viendo, solo que sin enlace.
  assert.ok(html.includes("Álgebra") && html.includes("Cálculo"), html);
});

test("una URL válida con comillas se escapa dentro del atributo", async () => {
  // `escapar` se apoya en `textContent`, que escapa lo que hace falta para un
  // nodo de texto pero deja pasar las comillas. Dentro de un atributo, una
  // comilla lo cierra y lo que venga detrás se lee como marcado.
  const m = montar();
  await reposar();
  m.responder(() =>
    respuestaNdjson([
      {
        fuentes: [
          {
            nombre: "Álgebra",
            titulacion: "G. Informática",
            origen: "Guía docente",
            url: 'https://eps.ujaen.es/a?b="&x=1',
          },
        ],
      },
      { parte: "Ya está." },
      { fin: true },
    ])
  );

  await m.chat.preguntar("¿Y esto?");
  ultimaRespuesta(m).pie.hijos.at(-1).disparar("click");
  const html = m.el("fuentes-lista").innerHTML;

  assert.equal((html.match(/<a /g) ?? []).length, 1, html);
  assert.ok(html.includes("&quot;"), html);
});

test("sin fuentes no se ofrece el botón", async () => {
  const m = montar();
  await reposar();
  m.responder(() => respuestaNdjson([{ fuentes: [] }, { parte: "Hola." }, { fin: true }]));

  await m.chat.preguntar("Buenos días");

  assert.equal(ultimaRespuesta(m).pie.hijos.length, 0);
});

test("el cuadro de fuentes se cierra desde su propio botón", async () => {
  const m = montar();
  await reposar();

  m.el("fuentes-cerrar").disparar("click");

  assert.equal(m.el("fuentes").vecesCerrado, 1);
});

// --------------------------------------------------------- el cuadro de texto

test("enviar el formulario vacía el cuadro y manda lo escrito", async () => {
  const m = montar();
  await reposar();
  m.el("entrada").value = "¿Qué es Geomática?";

  m.el("redaccion").disparar("submit");
  await reposar();

  assert.equal(m.el("entrada").value, "");
  assert.equal(
    JSON.parse(m.peticiones.at(-1).opciones.body).pregunta,
    "¿Qué es Geomática?"
  );
});

test("Intro envía y Mayúsculas+Intro no", async () => {
  /*
    El cuadro admite varias líneas, así que Mayúsculas+Intro tiene que seguir
    sirviendo para saltar de línea; si enviara, no habría forma de escribir una
    pregunta de dos renglones.
  */
  const m = montar();
  await reposar();
  const antes = m.peticiones.length;

  m.el("entrada").value = "Una línea";
  m.el("entrada").disparar("keydown", { key: "Enter", shiftKey: true });
  await reposar();
  assert.equal(m.peticiones.length, antes);

  m.el("entrada").disparar("keydown", { key: "Enter", shiftKey: false });
  await reposar();
  assert.equal(m.peticiones.length, antes + 1);
});

test("cualquier otra tecla no envía", async () => {
  const m = montar();
  await reposar();
  const antes = m.peticiones.length;

  m.el("entrada").value = "a";
  m.el("entrada").disparar("keydown", { key: "a", shiftKey: false });
  await reposar();

  assert.equal(m.peticiones.length, antes);
});

test("el cuadro de texto crece con lo escrito, hasta un tope", async () => {
  const m = montar();
  await reposar();
  const entrada = m.el("entrada");

  entrada.scrollHeight = 40;
  entrada.disparar("input");
  assert.equal(entrada.style.height, "40px");

  entrada.scrollHeight = 900;
  entrada.disparar("input");
  assert.equal(entrada.style.height, "160px");
});

// ------------------------------------------- la espera, pasado el umbral

test("pasados los segundos del umbral, la espera explica por qué tarda", async () => {
  /*
    Medido sobre el banco del sistema: una pregunta que llega al modelo tarda
    62,7 s de mediana. Un minuto sin explicación es indistinguible de una
    aplicación colgada.
  */
  const reloj = relojFalso();
  const chat = cargarChat({ reloj });
  const cuerpo = chat.document.createElement("div");
  const espera = chat.contarLaEspera(cuerpo);
  try {
    const aviso = cuerpo.hijos.at(-1);
    assert.ok(!aviso.textContent.includes("este mismo equipo"), aviso.textContent);

    reloj.avanzar(12);
    espera.redactando();

    assert.ok(aviso.textContent.includes("este mismo equipo"), aviso.textContent);
  } finally {
    espera.parar();
  }
});

test("al parar, el aviso se retira del documento", async () => {
  const chat = cargarChat();
  const cuerpo = chat.document.createElement("div");
  const espera = chat.contarLaEspera(cuerpo);
  assert.equal(cuerpo.hijos.length, 1);

  espera.parar();

  assert.equal(cuerpo.hijos.length, 0);
});

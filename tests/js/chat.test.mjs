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
const { formatear, escapar, horaActual } = chat;

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

/*
  La aplicación en un móvil de 320 px, medida en un navegador de verdad (IT-144).

  El reflujo no se ve en el fuente: `check_accesibilidad.py` lo dice y no lo
  comprueba. Aquí se abre `web/` en Chrome sin ventana, con el tamaño de un
  móvil, y se mide lo que ocupa cada banda.

  Los umbrales se fijaron antes de medir el arreglo:

  * U1 · 320×640: la conversación conserva al menos la mitad de la ventana.
  * U2 · 320×256, que es 1280×1024 con el zoom al 400 %: al menos 100 px de
    conversación (cuatro líneas) con el cuadro de escribir entero a la vista.
  * U3 · 320 y 360 px de ancho: el texto de ayuda cabe en el cuadro vacío y la
    página no tiene barra horizontal.

  Que pase no declara conformidad con las WCAG: mide tres tamaños en un solo
  navegador. Sin Chrome la prueba se salta y lo dice.

  Se ejecuta con `node --test tests/js/movil.test.mjs`, sin dependencias: el
  protocolo de depuración de Chrome se habla con el `WebSocket` del propio Node.
*/

import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, extname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "web");

/** Lo que devolvía el servidor real el 10/10/2026 en esas dos rutas. */
const SUGERENCIAS = [
  "¿Qué titulaciones puedo estudiar en la Escuela Politécnica Superior de Jaén?",
  "No sé qué estudiar, ¿qué me recomiendas?",
  "¿Qué asignaturas tiene el Doble Grado en Ingeniería Electrónica Industrial y Mecánica?",
  "¿Qué se aprende en las asignaturas de primer curso del Doble Grado en Ingeniería Eléctrica y Electrónica Industrial?",
];
const SALUDO =
  "¡Hola! Te puedo ayudar con las titulaciones de la Escuela Politécnica " +
  "Superior de Jaén: qué grados y dobles grados se estudian allí, qué " +
  "asignaturas tiene cada uno y en qué curso se dan, qué se ve en cada " +
  "asignatura y a qué se puede dedicar uno al terminar.\n\nPregúntame por la " +
  "titulación que te interese, o por lo que te gustaría estudiar y te digo " +
  "cuáles encajan.";

const TIPOS = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".png": "image/png" };

/** Primer Chrome o Chromium que se encuentre, o `null`. */
function buscarChrome() {
  const candidatos = [
    process.env.CHROME,
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ];
  for (const nombre of ["google-chrome", "chromium", "chromium-browser"]) {
    const ruta = spawnSync("which", [nombre], { encoding: "utf8" }).stdout?.trim();
    if (ruta) candidatos.push(ruta);
  }
  return candidatos.find((ruta) => ruta && existsSync(ruta)) ?? null;
}

/** Sirve `web/` y contesta el saludo y las sugerencias como el servidor real. */
function servirWeb() {
  const servidor = createServer((peticion, respuesta) => {
    const ruta = new URL(peticion.url, "http://x").pathname;
    if (ruta === "/api/sugerencias" || ruta === "/api/saludo") {
      respuesta.writeHead(200, { "Content-Type": "application/json" });
      respuesta.end(JSON.stringify(ruta === "/api/saludo" ? { respuesta: SALUDO } : SUGERENCIAS));
      return;
    }
    const fichero = join(WEB, ruta === "/" ? "index.html" : ruta.slice(1));
    if (!fichero.startsWith(WEB) || !existsSync(fichero)) {
      respuesta.writeHead(404).end();
      return;
    }
    respuesta.writeHead(200, { "Content-Type": TIPOS[extname(fichero)] ?? "application/octet-stream" });
    respuesta.end(readFileSync(fichero));
  });
  return new Promise((listo) => servidor.listen(0, "127.0.0.1", () => listo(servidor)));
}

const esperar = (ms) => new Promise((listo) => setTimeout(listo, ms));

/** Abre Chrome sin ventana y devuelve una función para hablarle por CDP. */
async function abrirChrome(ejecutable) {
  const perfil = mkdtempSync(join(tmpdir(), "it144-"));
  const proceso = spawn(ejecutable, [
    "--headless=new",
    "--no-sandbox",
    "--no-first-run",
    "--remote-debugging-port=0",
    `--user-data-dir=${perfil}`,
    "about:blank",
  ]);
  // Con el puerto 0 Chrome elige uno libre y lo escribe en este fichero.
  const anuncio = join(perfil, "DevToolsActivePort");
  for (let i = 0; i < 100 && !existsSync(anuncio); i++) await esperar(100);
  const puerto = readFileSync(anuncio, "utf8").split("\n")[0];
  const paginas = await (await fetch(`http://127.0.0.1:${puerto}/json`)).json();
  const ws = new WebSocket(paginas.find((p) => p.type === "page").webSocketDebuggerUrl);
  await new Promise((listo) => ws.addEventListener("open", listo));

  let id = 0;
  const pendientes = new Map();
  ws.addEventListener("message", (suceso) => {
    const mensaje = JSON.parse(suceso.data);
    pendientes.get(mensaje.id)?.(mensaje.result);
    pendientes.delete(mensaje.id);
  });
  const cdp = (method, params = {}) =>
    new Promise((listo) => {
      pendientes.set(++id, listo);
      ws.send(JSON.stringify({ id, method, params }));
    });
  const cerrar = async () => {
    ws.close();
    const salida = new Promise((listo) => proceso.once("exit", listo));
    proceso.kill();
    await salida;
    // El perfil es temporal: si Windows aún lo tiene bloqueado, se queda en
    // la carpeta temporal en vez de tapar con este error el de la medida.
    try {
      rmSync(perfil, { recursive: true, force: true, maxRetries: 5 });
    } catch {}
  };
  return { cdp, cerrar };
}

/*
  Se mide con la vista al final de la conversación, que es donde está quien
  escribe: el cuadro de escribir pegado al borde de abajo. El alto útil es lo
  que queda a la vista del recuadro de la conversación.
*/
const MEDIR = `(() => {
  document.querySelector(".redaccion").scrollIntoView({ block: "end" });
  const visible = (e) => {
    const r = e.getBoundingClientRect();
    return Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
  };
  const redaccion = document.querySelector(".redaccion").getBoundingClientRect();
  const entrada = document.querySelector("#entrada");
  const raiz = document.documentElement;
  return {
    conversacion: visible(document.querySelector(".conversacion")),
    sugerencias: document.querySelectorAll(".sugerencia").length,
    saludo: document.querySelectorAll(".mensaje").length,
    redaccionEntera: redaccion.top >= 0 && redaccion.bottom <= innerHeight + 0.5,
    ayudaCabe:
      entrada.scrollWidth <= entrada.clientWidth &&
      entrada.scrollHeight <= entrada.clientHeight,
    barraHorizontal: raiz.scrollWidth > raiz.clientWidth,
  };
})()`;

const chrome = buscarChrome();

test("la aplicación cabe en un móvil de 320 px", { skip: chrome ? false : "Chrome no está instalado" }, async () => {
  const servidor = await servirWeb();
  const { cdp, cerrar } = await abrirChrome(chrome);
  const url = `http://127.0.0.1:${servidor.address().port}/`;

  async function medir(ancho, alto) {
    await cdp("Emulation.setDeviceMetricsOverride", { width: ancho, height: alto, deviceScaleFactor: 1, mobile: true });
    await cdp("Page.navigate", { url });
    // El saludo y las sugerencias llegan por dos peticiones aparte.
    let medida;
    for (let i = 0; i < 50; i++) {
      await esperar(100);
      medida = (await cdp("Runtime.evaluate", { expression: MEDIR, returnByValue: true })).result.value;
      if (medida.sugerencias === SUGERENCIAS.length && medida.saludo > 0) break;
    }
    assert.equal(medida.sugerencias, SUGERENCIAS.length, "no se han pintado las sugerencias");
    return medida;
  }

  try {
    const u1 = await medir(320, 640);
    assert.ok(u1.conversacion >= 320, `U1: la conversación se queda en ${u1.conversacion} px de 640`);
    assert.ok(u1.redaccionEntera, "U1: el cuadro de escribir no se ve entero");

    const u2 = await medir(320, 256);
    assert.ok(u2.conversacion >= 100, `U2: al 400 % la conversación se queda en ${u2.conversacion} px`);
    assert.ok(u2.redaccionEntera, "U2: el cuadro de escribir no se ve entero");

    for (const ancho of [320, 360]) {
      const u3 = await medir(ancho, 640);
      assert.ok(u3.ayudaCabe, `U3: el texto de ayuda no cabe a ${ancho} px`);
      assert.ok(!u3.barraHorizontal, `U3: barra horizontal a ${ancho} px`);
    }
  } finally {
    await cerrar();
    servidor.close();
  }
});

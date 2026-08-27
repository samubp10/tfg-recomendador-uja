/*
  El navegador mínimo que `chat.js` necesita para cargarse (IT-45).

  Se ejecuta el fichero **tal cual se sirve**, sin tocarlo ni recortarlo. La
  alternativa ---copiar aquí las funciones que interesan--- probaría una copia
  que se desincroniza en cuanto alguien edite el original, que es exactamente
  el fallo que este proyecto lleva documentado nueve veces con otros nombres.

  Lo que este doble NO emula, y hay que saberlo antes de leer un verde:

  - **El escapado real.** `escapar()` delega en el navegador: crea un `div`, le
    pone `textContent` y lee `innerHTML`. Aquí eso se reimplementa escapando
    `&`, `<` y `>`, que es lo que hace un navegador con un nodo de texto. Las
    pruebas de `escapar` comprueban por tanto **el contrato**, no el navegador.
  - **La maquetación.** No hay `scrollHeight` de verdad, ni estilos, ni foco.
  - **La red.** `fetch` siempre falla, así que la llamada de arranque
    (`preguntar("Hola")`) y la de sugerencias caen por su rama de error, que es
    justo lo que se quiere: cargar el fichero sin salir a ninguna parte.
*/

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const AQUI = dirname(fileURLToPath(import.meta.url));
export const RUTA_CHAT_JS = join(AQUI, "..", "..", "web", "chat.js");

/** Escapa como lo hace el navegador al leer `innerHTML` de un nodo de texto. */
function escaparComoElNavegador(texto) {
  return String(texto)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** Un elemento con lo justo para que `chat.js` no reviente al cargarse. */
function crearElemento(etiqueta = "div") {
  const hijos = [];
  const elemento = {
    tagName: etiqueta.toUpperCase(),
    hijos,
    value: "",
    disabled: false,
    scrollTop: 0,
    scrollHeight: 0,
    style: {},
    dataset: {},
    classList: {
      _clases: new Set(),
      add(...c) {
        c.forEach((x) => this._clases.add(x));
      },
      remove(...c) {
        c.forEach((x) => this._clases.delete(x));
      },
      contains(c) {
        return this._clases.has(c);
      },
    },
    _texto: "",
    _html: "",
    get textContent() {
      return this._texto;
    },
    set textContent(v) {
      this._texto = String(v);
      this._html = escaparComoElNavegador(v);
    },
    get innerHTML() {
      return this._html;
    },
    set innerHTML(v) {
      this._html = String(v);
    },
    get className() {
      return [...this.classList._clases].join(" ");
    },
    set className(v) {
      this.classList._clases = new Set(String(v).split(/\s+/).filter(Boolean));
    },
    addEventListener() {},
    removeEventListener() {},
    appendChild(hijo) {
      hijos.push(hijo);
      return hijo;
    },
    remove() {},
    focus() {},
    scrollTo() {},
    close() {},
    showModal() {},
    requestSubmit() {},
    closest() {
      return null;
    },
    querySelector() {
      return crearElemento();
    },
    querySelectorAll() {
      return [];
    },
    setAttribute() {},
    removeAttribute() {},
  };
  return elemento;
}

/**
 * Carga `chat.js` en un contexto propio y devuelve ese contexto.
 *
 * Como el fichero declara sus funciones en el ámbito global ---no es un
 * módulo---, quedan accesibles como propiedades del contexto.
 */
export function cargarChat() {
  const porId = new Map();
  const documento = {
    getElementById(id) {
      if (!porId.has(id)) porId.set(id, crearElemento());
      return porId.get(id);
    },
    createElement: (etiqueta) => crearElemento(etiqueta),
    querySelector: () => crearElemento(),
    querySelectorAll: () => [],
    addEventListener() {},
    body: crearElemento("body"),
  };

  const contexto = {
    document: documento,
    window: undefined,
    console,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    Math,
    Date,
    JSON,
    AbortController,
    TextDecoder,
    // Siempre falla: cargar el fichero no puede salir a la red.
    fetch: () => Promise.reject(new Error("sin red en las pruebas")),
    _elementos: porId,
  };
  contexto.window = contexto;
  contexto.globalThis = contexto;

  vm.createContext(contexto);
  vm.runInContext(readFileSync(RUTA_CHAT_JS, "utf8"), contexto, {
    filename: "chat.js",
  });
  return contexto;
}

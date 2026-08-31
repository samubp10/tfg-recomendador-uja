/*
  El navegador mínimo que `chat.js` necesita para cargarse (IT-45).

  Se ejecuta el fichero **tal cual se sirve**, sin tocarlo ni recortarlo. La
  alternativa ---copiar aquí las funciones que interesan--- probaría una copia
  que se desincroniza en cuanto alguien edite el original, que es exactamente
  el fallo que este proyecto lleva documentado nueve veces con otros nombres.

  El guion se carga con `filename: RUTA_CHAT_JS` y no con un nombre suelto.
  Parece un detalle y no lo es: `node --test --experimental-test-coverage` mide
  por la ruta con la que V8 conoce cada guion, y con un nombre que no existe en
  el disco `web/chat.js` **no aparecía en el informe**. La tanda salía en verde
  y la cobertura del cliente no se estaba midiendo en absoluto.

  Lo que este doble NO emula, y hay que saberlo antes de leer un verde:

  - **El escapado real.** `escapar()` delega en el navegador: crea un `div`, le
    pone `textContent` y lee `innerHTML`. Aquí eso se reimplementa escapando
    `&`, `<` y `>`, que es lo que hace un navegador con un nodo de texto. Las
    pruebas de `escapar` comprueban por tanto **el contrato**, no el navegador.
  - **La maquetación.** No hay `scrollHeight` de verdad, ni estilos, ni foco.
  - **El emparejado de selectores.** `querySelector` y compañía entienden
    `.una-clase` y nada más, que es lo único que `chat.js` usa. Un selector
    compuesto devolvería un elemento vacío en vez de fallar, así que no se
    puede leer un verde de aquí como si el navegador hubiera dicho algo.
  - **La igualdad de tipos entre contextos.** `chat.js` se ejecuta en un
    contexto propio, con su propio `Array` y su propio `Object`. Un array que
    devuelva `chat.js` **no** es del mismo tipo que uno escrito en la prueba, y
    `assert.deepEqual` ---que en `node:assert/strict` compara también el
    prototipo--- los da por distintos aunque tengan el mismo contenido. Se
    resuelve copiando al contexto de la prueba con `Array.from(...)` antes de
    comparar; con `.map(...)` no basta, porque el resultado lo sigue creando el
    `Array` del otro lado.
  - **La red.** Por omisión `fetch` siempre falla, así que la llamada de
    arranque (`preguntar("Hola")`) y la de sugerencias caen por su rama de
    error, que es justo lo que se quiere para cargar el fichero sin salir a
    ninguna parte. Quien necesite el camino bueno pasa el suyo por
    `cargarChat({ fetch })`; nunca se sale a la red de verdad.
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

/**
 * ¿Lleva el elemento la clase que pide un selector de la forma `.clase`?
 *
 * Se acepta solo esa forma a propósito. Aceptar cualquier cadena y contestar
 * que no encaja convertiría un selector mal escrito en una lista vacía, que es
 * un resultado legítimo, y el fallo pasaría por prueba en verde.
 */
function encaja(elemento, selector) {
  if (typeof selector !== "string" || !/^\.[\w-]+$/.test(selector)) {
    throw new Error(`El doble solo entiende selectores «.clase»: «${selector}»`);
  }
  return elemento.classList.contains(selector.slice(1));
}

/** Un elemento con lo justo para que `chat.js` no reviente al cargarse. */
function crearElemento(etiqueta = "div") {
  const hijos = [];
  //: Un `querySelector` del navegador devuelve siempre el MISMO nodo. Sin esta
  //: memoria, `abrirRespuesta` recibiría un elemento nuevo en cada llamada y la
  //: prueba no podría mirar el que de verdad se está rellenando.
  const encontrados = new Map();
  const elemento = {
    tagName: etiqueta.toUpperCase(),
    hijos,
    padre: null,
    value: "",
    disabled: false,
    scrollTop: 0,
    scrollHeight: 0,
    style: {},
    dataset: {},
    //: Oyentes registrados, por tipo de suceso. Las pruebas los disparan con
    //: `disparar()`, que es lo más cerca que se puede estar de un clic sin
    //: navegador.
    oyentes: new Map(),
    //: Atributos que `chat.js` ha pedido quitar. `aria-busy` se pone dentro de
    //: una plantilla de `innerHTML`, así que el doble no llega a verlo puesto;
    //: lo que sí se puede comprobar es que se pide quitarlo, que es la promesa
    //: que le importa a un lector de pantalla.
    atributosQuitados: [],
    //: Cuántas veces se ha abierto y cerrado como diálogo.
    vecesAbierto: 0,
    vecesCerrado: 0,
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
      //: Asignar `innerHTML` sustituye a los hijos, también en un navegador de
      //: verdad. Sin esto, `pintarSugerencias` acumularía los botones de todas
      //: las veces que se ha repintado y `bloquear` recorrería una lista que
      //: crece sola.
      hijos.forEach((h) => (h.padre = null));
      hijos.length = 0;
      encontrados.clear();
    },
    get className() {
      return [...this.classList._clases].join(" ");
    },
    set className(v) {
      this.classList._clases = new Set(String(v).split(/\s+/).filter(Boolean));
    },
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
      //: Con el segundo argumento no alterna: pone o quita segun se le diga,
      //: que es como lo usa `bloquear` para marcar el boton de cancelar.
      toggle(c, fuerza) {
        const poner = fuerza === undefined ? !this._clases.has(c) : Boolean(fuerza);
        if (poner) this._clases.add(c);
        else this._clases.delete(c);
        return poner;
      },
    },
    addEventListener(tipo, fn) {
      if (!this.oyentes.has(tipo)) this.oyentes.set(tipo, []);
      this.oyentes.get(tipo).push(fn);
    },
    removeEventListener(tipo, fn) {
      const lista = this.oyentes.get(tipo) ?? [];
      const donde = lista.indexOf(fn);
      if (donde !== -1) lista.splice(donde, 1);
    },
    /** Lanza un suceso hacia los oyentes de este elemento. */
    disparar(tipo, suceso = {}) {
      const completo = { preventDefault() {}, target: this, ...suceso };
      for (const fn of [...(this.oyentes.get(tipo) ?? [])]) fn(completo);
    },
    appendChild(hijo) {
      hijo.padre = this;
      hijos.push(hijo);
      return hijo;
    },
    remove() {
      const donde = this.padre ? this.padre.hijos.indexOf(this) : -1;
      if (donde !== -1) this.padre.hijos.splice(donde, 1);
      this.padre = null;
    },
    focus() {},
    scrollTo() {},
    close() {
      this.vecesCerrado += 1;
    },
    showModal() {
      this.vecesAbierto += 1;
    },
    requestSubmit() {
      this.disparar("submit");
    },
    closest(selector) {
      let actual = this;
      while (actual) {
        if (encaja(actual, selector)) return actual;
        actual = actual.padre;
      }
      return null;
    },
    querySelector(selector) {
      const yaEstaba = hijos.find((h) => encaja(h, selector));
      if (yaEstaba) return yaEstaba;
      //: El nodo no cuelga de `hijos` porque lo creó una plantilla de
      //: `innerHTML`, que este doble no analiza. Se inventa uno y se recuerda,
      //: para que la segunda llamada devuelva el mismo.
      if (!encontrados.has(selector)) {
        const inventado = crearElemento();
        inventado.className = selector.slice(1);
        inventado.padre = this;
        encontrados.set(selector, inventado);
      }
      return encontrados.get(selector);
    },
    querySelectorAll(selector) {
      return hijos.filter((h) => encaja(h, selector));
    },
    setAttribute(nombre, valor) {
      this.dataset[nombre] = String(valor);
    },
    getAttribute(nombre) {
      //: `null` y no `undefined`: es lo que devuelve un navegador cuando el
      //: atributo no esta puesto, y una prueba que compare con `null` tiene
      //: que valer igual aqui que alli.
      return nombre in this.dataset ? this.dataset[nombre] : null;
    },
    removeAttribute(nombre) {
      this.atributosQuitados.push(nombre);
      delete this.dataset[nombre];
    },
  };
  return elemento;
}

/**
 * Carga `chat.js` en un contexto propio y devuelve ese contexto.
 *
 * Como el fichero declara sus funciones en el ámbito global ---no es un
 * módulo---, quedan accesibles como propiedades del contexto.
 *
 * @param {{fetch?: Function, reloj?: object}} opciones `fetch` sustituye al
 *   doble que siempre falla; `reloj` sustituye a `Date`, para poder llegar a
 *   los umbrales de segundos sin esperarlos de verdad.
 */
export function cargarChat({ fetch: fetchDoble, reloj } = {}) {
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
    Date: reloj ?? Date,
    JSON,
    AbortController,
    TextDecoder,
    // Sin uno propio, siempre falla: cargar el fichero no puede salir a la red.
    fetch: fetchDoble ?? (() => Promise.reject(new Error("sin red en las pruebas"))),
    _elementos: porId,
  };
  contexto.window = contexto;
  contexto.globalThis = contexto;

  vm.createContext(contexto);
  vm.runInContext(readFileSync(RUTA_CHAT_JS, "utf8"), contexto, {
    filename: RUTA_CHAT_JS,
  });
  return contexto;
}

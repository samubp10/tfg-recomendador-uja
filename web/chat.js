/*
  Cliente del asistente (IT-45).

  Habla con el punto de entrada de IT-44, que emite la respuesta POR PARTES:
  cada linea que llega es una unidad ya verificada por el servidor, nunca texto
  en bruto del modelo. La decision y su motivo estan en el ADR de IT-115.

  Que este fichero NO hace, a proposito:

  - No guarda el texto del saludo. Se lo pide al servidor al arrancar mandando
    «Hola», que es una respuesta fija y vuelve en decimas de segundo. Copiarlo
    aqui crearia una segunda copia que se desincroniza de `generador.py` en
    cuanto alguien toque una de las dos. Ya paso con las preguntas ajenas
    (IT-39) y la leccion fue esa.
  - No verifica nada. La comprobacion de titulaciones inventadas vive en el
    servidor y tiene que seguir alli: un control que se puede saltar abriendo
    las herramientas del navegador no es un control.
*/

"use strict";

/** Direccion del punto de entrada que implementa IT-44. */
const RUTA_CHAT = "/api/chat";

/** Segundos tras los cuales la espera explica por que tarda tanto. */
const SEGUNDOS_PARA_EXPLICAR = 12;

/** Debajo de esto se considera que la respuesta no llego a consultar al modelo. */
const SEGUNDOS_RESPUESTA_INMEDIATA = 1;

/**
 * Cierre de la respuesta para quien no ve la pantalla.
 *
 * El pie que se pinta al terminar dice la hora y la duracion, y eso leido en
 * voz alta ---«09:04, 62,3 s»--- no significa que la respuesta este completa.
 * Va delante para que sea lo primero que se anuncie.
 */
const FIN_PARA_LECTOR = '<span class="visualmente-oculto">Respuesta completa.</span>';

const mensajes = document.getElementById("mensajes");
const conversacion = document.getElementById("conversacion");
const formulario = document.getElementById("redaccion");
const entrada = document.getElementById("entrada");
const botonEnviar = document.getElementById("enviar");
const sugerencias = document.getElementById("sugerencias");
const cuadroFuentes = document.getElementById("fuentes");
const listaFuentes = document.getElementById("fuentes-lista");
const cerrarFuentes = document.getElementById("fuentes-cerrar");

let ocupado = false;

// --------------------------------------------------------------- utilidades

/**
 * Escapa el texto para poder meterlo en el documento sin abrir un agujero.
 *
 * La respuesta la escribe un modelo de lenguaje a partir de fragmentos de una
 * web ajena: es texto de origen no confiable y no puede entrar como HTML.
 *
 * @param {string} texto Texto en bruto.
 * @returns {string} El mismo texto con los caracteres peligrosos escapados.
 */
function escapar(texto) {
  const caja = document.createElement("div");
  caja.textContent = texto;
  return caja.innerHTML;
}

/**
 * Convierte la respuesta del modelo en HTML seguro.
 *
 * El modelo escribe listas como «*   Algebra (6 ECTS)» y resalta con dobles
 * asteriscos. Se traduce solo eso: parrafos, listas y negrita. Cualquier otra
 * cosa se queda como texto plano, que es lo que interesa.
 *
 * @param {string} texto Respuesta acumulada hasta ahora.
 * @returns {string} HTML ya escapado y con el formato minimo aplicado.
 */
function formatear(texto) {
  const negrita = (linea) =>
    escapar(linea).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  const esItem = (linea) => /^\s*(?:[*•-]\s+)/.test(linea);
  const contenidoItem = (linea) => linea.replace(/^\s*(?:[*•-]\s+)/, "");

  const bloques = [];
  let lista = [];
  let parrafo = [];

  const cerrarLista = () => {
    if (lista.length) {
      bloques.push("<ul>" + lista.map((l) => `<li>${negrita(l)}</li>`).join("") + "</ul>");
      lista = [];
    }
  };
  const cerrarParrafo = () => {
    if (parrafo.length) {
      bloques.push(`<p>${parrafo.map(negrita).join("<br>")}</p>`);
      parrafo = [];
    }
  };

  for (const linea of texto.split("\n")) {
    if (esItem(linea)) {
      cerrarParrafo();
      lista.push(contenidoItem(linea));
    } else if (linea.trim() === "") {
      cerrarLista();
      cerrarParrafo();
    } else {
      cerrarLista();
      parrafo.push(linea);
    }
  }
  cerrarLista();
  cerrarParrafo();
  return bloques.join("");
}

/** @returns {string} La hora actual como «09:04». */
function horaActual() {
  return new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
}

/** Lleva la vista al final de la conversacion. */
function bajarDelTodo() {
  conversacion.scrollTop = conversacion.scrollHeight;
}

// ----------------------------------------------------------------- burbujas

/**
 * Pinta el mensaje que acaba de escribir la persona.
 *
 * @param {string} texto Lo que ha preguntado.
 */
function pintarPregunta(texto) {
  const fila = document.createElement("div");
  fila.className = "mensaje mensaje--propio";
  fila.innerHTML = `
    <div class="mensaje__burbuja">
      ${formatear(texto)}
      <div class="mensaje__pie"><span>${horaActual()}</span></div>
    </div>
    <div class="mensaje__avatar mensaje__avatar--propio">Tú</div>`;
  mensajes.appendChild(fila);
  bajarDelTodo();
}

/**
 * Crea la burbuja del asistente, de momento con la espera dentro.
 *
 * Devuelve las piezas que hay que ir rellenando segun llegan las partes, para
 * no volver a buscarlas en el documento en cada trozo.
 *
 * La burbuja nace con `aria-busy="true"`. De ese atributo cuelgan las dos
 * senales de que la respuesta sigue escribiendose: la palabra que la hoja de
 * estilo pinta debajo del texto y lo que anuncia un lector de pantalla. Hace
 * falta porque el texto llega por partes durante un minuto y, entre frase y
 * frase, no habia nada que distinguiera «esta pensando la siguiente» de «ya ha
 * terminado».
 *
 * @returns {{fila: HTMLElement, burbuja: HTMLElement, cuerpo: HTMLElement,
 *   pie: HTMLElement}}
 */
function abrirRespuesta() {
  const fila = document.createElement("div");
  fila.className = "mensaje mensaje--asistente";
  fila.innerHTML = `
    <div class="mensaje__avatar mensaje__avatar--asistente">
      <img src="logo-uja.png" alt="">
    </div>
    <div class="mensaje__burbuja" aria-busy="true">
      <div class="mensaje__cuerpo">
        <div class="espera__puntos" role="status" aria-label="Preparando la respuesta">
          <span class="espera__punto"></span>
          <span class="espera__punto"></span>
          <span class="espera__punto"></span>
        </div>
      </div>
      <div class="mensaje__pie"></div>
    </div>`;
  mensajes.appendChild(fila);
  bajarDelTodo();
  return {
    fila,
    burbuja: fila.querySelector(".mensaje__burbuja"),
    cuerpo: fila.querySelector(".mensaje__cuerpo"),
    pie: fila.querySelector(".mensaje__pie"),
  };
}

/**
 * Mantiene informada a la persona mientras no llega nada.
 *
 * Son **dos fases con nombre**, y cuál toca no lo decide un cronómetro sino el
 * propio sistema: mientras no han llegado las fuentes se está buscando, y en
 * cuanto llegan es que la recuperación terminó y quien tarda es el modelo. Un
 * umbral de segundos habría dicho «redactando» aunque la búsqueda siguiera.
 *
 * Medido el 24/08/2026 sobre el banco del sistema: una pregunta de un turno que
 * llega al modelo tarda 62,7 s de mediana y el percentil 90 pasa de los dos
 * minutos. Un minuto sin ninguna senal es indistinguible de una aplicacion
 * colgada, asi que se cuenta el tiempo en voz alta y, pasado el umbral, se
 * explica que el modelo se ejecuta en local.
 *
 * @param {HTMLElement} cuerpo Contenedor de la burbuja en curso.
 * @returns {() => void} Funcion que detiene el contador.
 */
function contarLaEspera(cuerpo) {
  const inicio = Date.now();
  const aviso = document.createElement("p");
  aviso.className = "espera__aviso";
  cuerpo.appendChild(aviso);

  let redactando = false;

  const pintar = () => {
    const segundos = Math.round((Date.now() - inicio) / 1000);
    const fase = redactando
      ? "Redactando la respuesta"
      : "Buscando en la información de la Escuela";
    const tarda =
      segundos >= SEGUNDOS_PARA_EXPLICAR
        ? " El modelo se ejecuta en este mismo equipo, así que tarda más que un" +
          " servicio en la nube."
        : "";
    aviso.textContent = `${fase}… ${segundos} s.${tarda}`;
  };

  pintar();
  const reloj = setInterval(pintar, 1000);
  return {
    /** El servidor ya ha recuperado: de aquí en adelante escribe el modelo. */
    redactando() {
      redactando = true;
      pintar();
    },
    parar() {
      clearInterval(reloj);
      aviso.remove();
    },
  };
}


// ------------------------------------------------------------- las sugerencias

/**
 * Repinta los botones de sugerencia con lo que manda el servidor.
 *
 * La lista no vive en el HTML: la compone el servidor preguntandole al indice
 * si existe el fragmento que respalda cada pregunta. Que llegue vacia es un
 * resultado valido, no un fallo: significa que en este punto del dialogo no
 * hay ningun atajo que proponer.
 *
 * @param {string[]} lista
 */
function pintarSugerencias(lista) {
  sugerencias.innerHTML = "";
  for (const texto of lista) {
    const boton = document.createElement("button");
    boton.type = "button";
    boton.className = "sugerencia";
    boton.textContent = texto;
    sugerencias.appendChild(boton);
  }
}

// ------------------------------------------------- las fuentes de la respuesta

/**
 * Enseña de qué unidades de la colección salió una respuesta.
 *
 * Va en un cuadro y no debajo de cada respuesta porque el recuperador llega a
 * traer veinte fragmentos, y veinte líneas de procedencia esconden la respuesta
 * que se ha pedido.
 *
 * @param {{nombre: string, titulacion: string, origen: string}[]} lista
 */
function abrirFuentes(lista) {
  listaFuentes.innerHTML = agruparFuentes(lista)
    .map(
      ([titulacion, unidades]) =>
        `<li class="fuentes__grupo">` +
        `<p class="fuentes__titulacion">${escapar(titulacion)}</p>` +
        `<ul class="fuentes__unidades">` +
        unidades
          .map(
            (u) =>
              `<li>${escapar(u.nombre)}` +
              `<span class="fuentes__origen">${escapar(u.origen)}</span></li>`
          )
          .join("") +
        `</ul></li>`
    )
    .join("");
  cuadroFuentes.showModal();
}

/**
 * Agrupa las unidades por la titulación en la que se imparten.
 *
 * Con veinte unidades de tres titulaciones, la lista plana obliga a leerlas
 * todas para ver de dónde sale la respuesta. Agrupadas se ve de un vistazo.
 *
 * Se conserva el orden en que llegaron ---que es el de proximidad a la
 * pregunta--- tanto entre grupos como dentro de cada uno: reordenarlos
 * alfabéticamente escondería cuál se pareció más a lo que se preguntó.
 *
 * La titulación llega ya compuesta por el servidor, y cuando una unidad se
 * imparte en varias viene con todas separadas por un punto medio. No se parte
 * aquí: esa cadena es una sola clave, y una asignatura compartida por cuatro
 * titulaciones es un caso distinto de la misma asignatura en una sola.
 *
 * @param {{nombre: string, titulacion: string, origen: string}[]} lista
 * @returns {[string, {nombre: string, origen: string}[]][]}
 */
function agruparFuentes(lista) {
  const grupos = new Map();
  for (const fuente of lista) {
    const clave = fuente.titulacion || "Sin titulación asociada";
    if (!grupos.has(clave)) grupos.set(clave, []);
    grupos.get(clave).push(fuente);
  }
  return [...grupos];
}

/**
 * Añade al pie de una respuesta el botón que abre sus fuentes.
 *
 * @param {HTMLElement} pie Pie de la burbuja ya rellenado con hora y duración.
 * @param {{nombre: string, titulacion: string, origen: string}[]} lista
 */
function ponerBotonDeFuentes(pie, lista) {
  if (!lista.length) return;
  const boton = document.createElement("button");
  boton.type = "button";
  boton.className = "mensaje__fuentes";
  boton.textContent = `Fuentes (${lista.length})`;
  boton.addEventListener("click", () => abrirFuentes(lista));
  pie.appendChild(boton);
}

// ------------------------------------------------------------------- envio

/**
 * Manda la consulta y va pintando la respuesta segun llega.
 *
 * @param {string} pregunta Lo que se pregunta.
 * @param {boolean} silenciosa Si es true no se pinta la pregunta: se usa para
 *   el saludo de arranque, que la persona no ha escrito.
 * @returns {Promise<void>}
 */
async function preguntar(pregunta, silenciosa = false) {
  if (ocupado || !pregunta.trim()) return;
  ocupado = true;
  bloquear(true);

  if (!silenciosa) pintarPregunta(pregunta.trim());
  const { fila, burbuja, cuerpo, pie } = abrirRespuesta();
  const espera = contarLaEspera(cuerpo);
  const inicio = Date.now();

  let acumulado = "";
  let primeraParte = true;
  let fuentes = [];
  let propuestas = null;

  /** Vuelca lo acumulado, sustituyendo la espera la primera vez. */
  const repintar = () => {
    if (primeraParte) {
      espera.parar();
      cuerpo.innerHTML = "";
      primeraParte = false;
    }
    cuerpo.innerHTML = formatear(acumulado);
    bajarDelTodo();
  };

  try {
    const respuesta = await fetch(RUTA_CHAT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pregunta: pregunta.trim() }),
    });
    if (!respuesta.ok) throw new Error(`el servidor respondió ${respuesta.status}`);

    const lector = respuesta.body.getReader();
    const decodificador = new TextDecoder();
    let resto = "";

    // El servidor emite una linea JSON por unidad verificada. Se corta por
    // saltos de linea y el ultimo trozo se guarda: puede venir a medias.
    for (;;) {
      const { value, done } = await lector.read();
      if (done) break;
      resto += decodificador.decode(value, { stream: true });
      const lineas = resto.split("\n");
      resto = lineas.pop() ?? "";
      for (const linea of lineas) {
        if (!linea.trim()) continue;
        const suceso = JSON.parse(linea);
        if (suceso.error) throw new Error(suceso.error);
        if (suceso.borrar) {
          // El servidor ha retirado la respuesta a media emisión: nombraba una
          // titulación que no existe. Lo que venga después la sustituye entera,
          // así que hay que borrar lo pintado y no añadir debajo.
          acumulado = "";
          repintar();
        }
        if (suceso.fin) {
          // Ultimo suceso que manda el servidor: es el unico punto en el que
          // se sabe con certeza que no queda texto por llegar, asi que es
          // donde se retira la marca de «escribiendo».
          burbuja.removeAttribute("aria-busy");
        }
        if (Array.isArray(suceso.sugerencias)) propuestas = suceso.sugerencias;
        if (Array.isArray(suceso.fuentes)) {
          // Llegan antes que el texto: se conocen al terminar la recuperación
          // y el modelo tarda un minuto en dar la primera frase.
          fuentes = suceso.fuentes;
          espera.redactando();
        }
        if (typeof suceso.parte === "string") {
          acumulado += suceso.parte;
          repintar();
        }
      }
    }

    if (!acumulado.trim()) throw new Error("el servidor no devolvió ninguna respuesta");
    espera.parar();

    const segundos = (Date.now() - inicio) / 1000;
    if (segundos < SEGUNDOS_RESPUESTA_INMEDIATA) {
      // No llego a consultar al modelo: es una de las respuestas fijas. Se
      // marca porque si no, su rapidez se lee como un error.
      fila.classList.add("mensaje--inmediato");
      pie.innerHTML =
        FIN_PARA_LECTOR + `<span>${horaActual()}</span><span>respuesta inmediata</span>`;
    } else {
      pie.innerHTML =
        FIN_PARA_LECTOR +
        `<span>${horaActual()}</span><span>${segundos.toFixed(1).replace(".", ",")} s</span>`;
    }
    ponerBotonDeFuentes(pie, fuentes);
    if (propuestas) pintarSugerencias(propuestas);
  } catch (fallo) {
    espera.parar();
    fila.classList.add("mensaje--fallo");
    cuerpo.innerHTML = formatear(
      "No he podido contactar con el asistente: " +
        fallo.message +
        "\n\nComprueba que el servidor está en marcha y que el servidor de " +
        "inferencia responde."
    );
    pie.innerHTML = `<span>${horaActual()}</span>`;
  } finally {
    // Red de seguridad: si la conexion se corta o el modelo falla, el suceso
    // `fin` no llega nunca y la marca se quedaria puesta para siempre,
    // diciendo que se esta escribiendo algo que ya no va a llegar.
    burbuja.removeAttribute("aria-busy");
    ocupado = false;
    bloquear(false);
    bajarDelTodo();
  }
}

/**
 * Habilita o deshabilita todo lo que sirve para preguntar.
 *
 * Mientras hay una consulta en curso no se admite otra: el modelo atiende en
 * serie, asi que encolar una segunda solo consigue que las dos tarden mas.
 *
 * @param {boolean} bloqueado Si hay que bloquear.
 */
function bloquear(bloqueado) {
  entrada.disabled = bloqueado;
  botonEnviar.disabled = bloqueado;
  for (const boton of sugerencias.querySelectorAll(".sugerencia")) {
    boton.disabled = bloqueado;
  }
  if (!bloqueado) entrada.focus();
}

/** Ajusta la altura del cuadro de texto a lo que se ha escrito. */
function ajustarAltura() {
  entrada.style.height = "auto";
  entrada.style.height = Math.min(entrada.scrollHeight, 160) + "px";
}

// ------------------------------------------------------------------ enlaces

formulario.addEventListener("submit", (suceso) => {
  suceso.preventDefault();
  const texto = entrada.value;
  entrada.value = "";
  ajustarAltura();
  preguntar(texto);
});

entrada.addEventListener("input", ajustarAltura);

entrada.addEventListener("keydown", (suceso) => {
  if (suceso.key === "Enter" && !suceso.shiftKey) {
    suceso.preventDefault();
    formulario.requestSubmit();
  }
});

sugerencias.addEventListener("click", (suceso) => {
  const boton = suceso.target.closest(".sugerencia");
  if (boton) preguntar(boton.textContent.trim());
});

// El saludo se le pide al servidor en vez de escribirlo aqui. Vuelve en
// decimas de segundo porque es una respuesta fija que no llega al modelo.
preguntar("Hola", true);

cerrarFuentes.addEventListener("click", () => cuadroFuentes.close());

// Las sugerencias de arranque tambien las decide el servidor. Si la peticion
// falla no se pinta ninguna: la conversacion funciona igual escribiendo, y un
// boton con una pregunta que el indice no respalda es peor que ningun boton.
fetch("/api/sugerencias")
  .then((r) => (r.ok ? r.json() : []))
  .then(pintarSugerencias)
  .catch(() => {});

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

/** Saludo de arranque. Ruta aparte porque esta NO anota nada. */
const RUTA_SALUDO = "/api/saludo";

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

/**
 * Si la persona ya ha preguntado algo.
 *
 * El saludo y las sugerencias de arranque se piden en dos peticiones aparte y
 * sus respuestas llegaban cuando llegaran. Si tardaban mas que el primer
 * turno, el saludo se anadia DEBAJO de la pregunta y de su respuesta, y las
 * sugerencias de arranque sustituian a las del ultimo turno. Es una carrera de
 * orden de llegada, y esta marca es el contrato que la corta: lo que se pidio
 * al arrancar solo se aplica si al llegar sigue siendo lo actual.
 */
let yaHaPreguntado = false;

/** Peticion en curso, o `null`. Es lo que permite cancelarla. */
let enCurso = null;

/** Texto del boton de enviar tal y como viene del HTML, para restaurarlo. */
const ICONO_ENVIAR = botonEnviar.innerHTML;

/** Cuadrado de «parar», que sustituye a la flecha mientras se responde. */
const ICONO_CANCELAR =
  '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" ' +
  'focusable="false"><rect fill="currentColor" x="5" y="5" width="14" ' +
  'height="14" rx="2" /></svg>';

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
 * Medido sobre el banco del sistema: una pregunta de un turno que
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
 * Escapa un valor para meterlo DENTRO de un atributo HTML.
 *
 * `escapar` no sirve aqui: se apoya en `textContent`, que escapa lo que hace
 * falta para un nodo de texto pero deja pasar las comillas. Dentro de un
 * atributo entrecomillado, una comilla cierra el atributo y lo que venga
 * detras se lee como marcado.
 *
 * @param {string} valor
 * @returns {string}
 */
function escaparAtributo(valor) {
  return escapar(valor).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

/**
 * Si una direccion se puede poner en un `href` sin riesgo.
 *
 * Solo `http` y `https`. Las direcciones vienen del dataset, que se extrae de
 * la web de la EPSJ por su `href` real: son datos de fuera, y la fuente ya ha
 * servido URL mal formadas (guias con el sufijo duplicado). Un `javascript:`
 * en un `href` se ejecuta al pulsarlo, asi que se comprueba el esquema en vez
 * de confiar en que el dataset venga limpio.
 *
 * @param {string | undefined} url
 * @returns {boolean}
 */
function esDireccionWeb(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url);
}

/**
 * Nombre de la unidad, enlazado a su pagina oficial si la EPSJ la publica.
 *
 * Las 81 asignaturas sin guia publicada no tienen a donde apuntar, y entonces
 * el nombre va sin enlace. Inventarle uno seria mandar a alguien a una pagina
 * que no existe para aparentar que todo esta respaldado.
 *
 * `rel="noopener noreferrer"` va con `target="_blank"`: sin `noopener` la
 * pagina que se abre puede manipular a la que la abrio.
 *
 * @param {{nombre: string, url?: string}} unidad
 * @returns {string} HTML ya escapado.
 */
function nombreDeLaFuente(unidad) {
  const nombre = escapar(unidad.nombre);
  if (!esDireccionWeb(unidad.url)) return nombre;
  return (
    `<a class="fuentes__enlace" href="${escaparAtributo(unidad.url)}"` +
    ` target="_blank" rel="noopener noreferrer">${nombre}</a>`
  );
}

/**
 * Enseña de qué unidades de la colección salió una respuesta.
 *
 * Va en un cuadro y no debajo de cada respuesta porque el recuperador llega a
 * traer veinte fragmentos, y veinte líneas de procedencia esconden la respuesta
 * que se ha pedido.
 *
 * @param {{nombre: string, titulacion: string, origen: string, url?: string}[]} lista
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
              `<li>${nombreDeLaFuente(u)}` +
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
 * @returns {Promise<void>}
 */
async function preguntar(pregunta) {
  if (ocupado || !pregunta.trim()) return;
  ocupado = true;
  yaHaPreguntado = true;
  bloquear(true);

  pintarPregunta(pregunta.trim());
  const { fila, burbuja, cuerpo, pie } = abrirRespuesta();
  const espera = contarLaEspera(cuerpo);
  const inicio = Date.now();

  let acumulado = "";
  let primeraParte = true;
  let fuentes = [];
  let propuestas = null;
  // El servidor cierra cada turno con `{"fin": true}`. Sin esta marca no se
  // puede distinguir una respuesta terminada de una conexion que se corto
  // despues de mandar medio texto: las dos llegan al final del bucle con
  // texto acumulado. Antes se aceptaban las dos por igual, de modo que un
  // corte a mitad se presentaba con el pie «Respuesta completa».
  let finRecibido = false;

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
    enCurso = new AbortController();
    const respuesta = await fetch(RUTA_CHAT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pregunta: pregunta.trim() }),
      signal: enCurso.signal,
    });
    if (!respuesta.ok) throw new Error(`el servidor respondió ${respuesta.status}`);

    const lector = respuesta.body.getReader();
    const decodificador = new TextDecoder();
    let resto = "";

    // El servidor emite una linea JSON por unidad verificada. Se corta por
    // saltos de linea y el ultimo trozo se guarda: puede venir a medias.
    //
    // El bucle va etiquetado porque el cierre del turno se reconoce dentro
    // del bucle de lineas y tiene que cortar los dos a la vez.
    lectura: for (;;) {
      const { value, done } = await lector.read();
      if (done) {
        // Vaciar el decodificador: si el flujo se corto en medio de un
        // caracter de varios bytes, esos bytes estan retenidos dentro y sin
        // esta llamada no aparecen por ninguna parte.
        resto += decodificador.decode();
        break;
      }
      resto += decodificador.decode(value, { stream: true });
      const lineas = resto.split("\n");
      // Sin respaldo a proposito: `split` devuelve siempre al menos un
      // elemento ---`"".split("\n")` es `[""]`---, asi que `pop()` no
      // puede dar `undefined`. El `?? ""` que habia aqui era una rama que
      // ninguna prueba podia alcanzar, y una rama inalcanzable ensucia la
      // medida de cobertura sin proteger de nada.
      resto = lineas.pop();
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
          finRecibido = true;
          // Y se deja de leer aqui mismo, en vez de seguir hasta el final del
          // transporte. El cierre es el terminal del turno y manda: una parte
          // rezagada se sumaba a un texto ya cerrado, y un `error` posterior
          // convertia en fallo una respuesta que estaba completa. `resto` se
          // tira por lo mismo, para que media linea de mas no se lea como una
          // transmision cortada.
          resto = "";
          break lectura;
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
    // El servidor termina TODA linea con un salto, asi que lo que quede en
    // `resto` al agotarse el flujo es una linea cortada por la mitad. No se
    // intenta interpretar: media linea de JSON no dice nada fiable.
    if (resto.trim()) throw new Error("la respuesta llegó cortada a la mitad");
    // Sin el cierre del servidor la respuesta esta incompleta aunque haya
    // texto. Aceptar el fin del transporte como fin de la respuesta hacia
    // que un corte de red se presentase con el pie «Respuesta completa».
    if (!finRecibido) throw new Error("la respuesta terminó sin el cierre del servidor");
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
    // El detalle tecnico va a la consola y no a la pantalla: lo que se veia
    // era el mensaje del navegador, en ingles («Failed to fetch»), y la
    // palabra «servidor de inferencia», que es vocabulario de dentro.
    console.error("La consulta ha fallado:", fallo);

    if (fallo.name === "AbortError") {
      cuerpo.innerHTML = formatear("Consulta cancelada.");
      pie.innerHTML = `<span>${horaActual()}</span>`;
      // Se devuelve la pregunta al cuadro para poder corregirla en vez de
      // volver a escribirla entera.
      entrada.value = pregunta;
      ajustarAltura();
    } else {
      fila.classList.add("mensaje--fallo");
      cuerpo.innerHTML = formatear(
        "No se ha podido obtener una respuesta. Comprueba que el asistente " +
          "sigue en marcha e inténtalo de nuevo."
      );
      pie.innerHTML = `<span>${horaActual()}</span>`;
    }
  } finally {
    // Red de seguridad: si la conexion se corta o el modelo falla, el suceso
    // `fin` no llega nunca y la marca se quedaria puesta para siempre,
    // diciendo que se esta escribiendo algo que ya no va a llegar.
    burbuja.removeAttribute("aria-busy");
    enCurso = null;
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
  for (const boton of sugerencias.querySelectorAll(".sugerencia")) {
    boton.disabled = bloqueado;
  }
  // El envio NO se apaga mientras se responde: se convierte en cancelar. Una
  // respuesta tarda alrededor de un minuto ---medido: 56,6 s, 63,2 s y
  // 65,4 s--- y hasta ahora no habia forma de salir de una pregunta escrita
  // por error. Es el mismo control, asi que no aparece nada nuevo en el
  // recorrido de teclado ni hay que colocar otro boton.
  botonEnviar.innerHTML = bloqueado ? ICONO_CANCELAR : ICONO_ENVIAR;
  botonEnviar.setAttribute(
    "aria-label",
    bloqueado ? "Cancelar la consulta en curso" : "Enviar consulta"
  );
  actualizarEnviar();
  if (!bloqueado) entrada.focus();
}

/**
 * Deja el boton de enviar habilitado solo cuando pulsarlo hace algo.
 *
 * Con el cuadro vacio no se enviaba nada, pero el boton seguia habilitado y
 * al pulsarlo no pasaba absolutamente nada: ni mensaje, ni cambio de foco, ni
 * estado invalido. Quien use un lector de pantalla no tenia ninguna senal de
 * por que (WCAG 3.3.1, 3.3.2 y 4.1.3). Impedir el envio es mas simple que
 * explicar un error que no hace falta cometer. El servidor sigue rechazando
 * la peticion vacia por su cuenta: esto es la primera barrera, no la unica.
 */
function actualizarEnviar() {
  botonEnviar.disabled = !ocupado && entrada.value.trim() === "";
}

/** Ajusta la altura del cuadro de texto a lo que se ha escrito. */
function ajustarAltura() {
  entrada.style.height = "auto";
  entrada.style.height = Math.min(entrada.scrollHeight, 160) + "px";
}

// ------------------------------------------------------------------ enlaces

formulario.addEventListener("submit", (suceso) => {
  suceso.preventDefault();
  if (ocupado) {
    if (enCurso) enCurso.abort();
    return;
  }
  const texto = entrada.value;
  entrada.value = "";
  ajustarAltura();
  actualizarEnviar();
  preguntar(texto);
});

entrada.addEventListener("input", () => {
  ajustarAltura();
  actualizarEnviar();
});

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

/**
 * Pinta el saludo con el que arranca la conversacion.
 *
 * Se le pide al servidor, que es donde vive el texto: escribirlo aqui daria
 * dos copias que pueden separarse. Pero se pide por `/api/saludo` y no como
 * una consulta normal, porque el servidor anota en el registro todo lo que
 * entra por `/api/chat`: cada apertura de la pagina metia un turno con la
 * palabra «Hola» que nadie habia escrito, y eso inflaba cualquier recuento
 * que se hiciera despues sobre el registro.
 *
 * Si falla no se pinta nada y no se avisa. Es deliberado: nadie ha pedido
 * este saludo, asi que un error suyo no es un error de la persona, y la
 * conversacion funciona igual escribiendo la primera pregunta.
 *
 * @returns {Promise<void>}
 */
async function saludar() {
  let texto;
  try {
    const respuesta = await fetch(RUTA_SALUDO);
    if (!respuesta.ok) return;
    texto = (await respuesta.json()).respuesta;
  } catch {
    return;
  }
  // Si mientras se pedia el saludo la persona ya ha preguntado, este texto ha
  // dejado de ser una bienvenida: pintarlo ahora lo colocaria debajo de su
  // pregunta y de la respuesta.
  if (yaHaPreguntado) return;
  const { burbuja, cuerpo } = abrirRespuesta();
  cuerpo.innerHTML = formatear(texto);
  burbuja.removeAttribute("aria-busy");
  bajarDelTodo();
}

// Al arrancar el cuadro esta vacio, asi que el envio nace apagado.
actualizarEnviar();

saludar();

cerrarFuentes.addEventListener("click", () => cuadroFuentes.close());

// Las sugerencias de arranque tambien las decide el servidor. Si la peticion
// falla no se pinta ninguna: la conversacion funciona igual escribiendo, y un
// boton con una pregunta que el indice no respalda es peor que ningun boton.
fetch("/api/sugerencias")
  .then((r) => (r.ok ? r.json() : []))
  // Igual que el saludo: si el primer turno se ha adelantado, sus sugerencias
  // son las buenas y estas ya no. Pintarlas ahora las sustituiria por las del
  // arranque, que no tienen nada que ver con lo que se acaba de preguntar.
  .then((lista) => {
    if (!yaHaPreguntado) pintarSugerencias(lista);
  })
  .catch(() => {});

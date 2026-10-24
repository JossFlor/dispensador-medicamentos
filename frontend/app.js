import {
  STOCK_REFERENCIA,
  cargarCatalogo,
  estadoStock,
  filaInventarioHTML,
  fmtDate,
  fmtTime,
  nombreCompleto,
  pintarFilaInventario,
  sleep,
} from "./comun.js";

// Loaded from GET /medicamentos; `color` identifies the tray for the API and the robot.
let MEDICAMENTOS = [];

const POLL_MS = 2000;
const REQUEST_TIMEOUT_MS = 210_000;
const MAX_STOCK = 20;
const MAX_LOG = 50;
const MAX_TEXTO_OCR_UI = 160;
const PASOS = ["registrada", "dispensando", "entregada"];
const NIVELES_LOG = { info: "Info", success: "Correcto", warning: "Aviso", error: "Error" };
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

const state = {
  inventario: {},
  seleccion: null,
  enCurso: false,
  reponiendo: false,
  conectado: null,
  inventarioVersion: 0,
  escuchando: false,
  interpretandoVoz: false,
  rxArchivo: null,
  validandoReceta: false,
  receta: null,
  cola: [],
};

const $ = (id) => document.getElementById(id);
const els = {
  rows: $("inventory-rows"),
  form: $("dispense-form"),
  options: $("med-options"),
  btn: $("dispense-btn"),
  btnLabel: $("dispense-label"),
  restockBtn: $("restock-btn"),
  restockDialog: $("restock-dialog"),
  restockForm: $("restock-form"),
  restockList: $("restock-list"),
  restockAll: $("restock-all"),
  restockHint: $("restock-hint"),
  restockError: $("restock-error"),
  restockSubmit: $("restock-submit"),
  restockSubmitLabel: $("restock-submit-label"),
  progress: $("progress"),
  progressTitle: $("progress-title"),
  progressDetail: $("progress-detail"),
  progressTimer: $("progress-timer"),
  log: $("log-rows"),
  connection: $("connection"),
  connectionLabel: $("connection-label"),
  lastSync: $("last-sync"),
  clockDate: $("clock-date"),
  clockTime: $("clock-time"),
  summaryUnits: $("summary-units"),
  summaryAlerts: $("summary-alerts"),
  voiceBtn: $("voice-btn"),
  voiceLabel: $("voice-label"),
  voiceSub: $("voice-sub"),
  rxBtn: $("rx-btn"),
  rxInput: $("rx-input"),
  assistStatus: $("assist-status"),
  rxCard: $("rx-card"),
  rxPreview: $("rx-preview"),
  rxTitle: $("rx-title"),
  rxBadge: $("rx-badge"),
  rxDetail: $("rx-detail"),
  rxOcr: $("rx-ocr"),
  rxValidate: $("rx-validate"),
  rxDiscard: $("rx-discard"),
  rxChip: $("rx-chip"),
  queueDialog: $("queue-dialog"),
  queueForm: $("queue-form"),
  queueList: $("queue-list"),
  queueSubmit: $("queue-submit"),
  queueSubmitLabel: $("queue-submit-label"),
};

const buscarMed = (color) => MEDICAMENTOS.find((m) => m.color === color);

function buildUI() {
  els.rows.innerHTML = MEDICAMENTOS.map(filaInventarioHTML).join("");

  els.options.insertAdjacentHTML(
    "beforeend",
    MEDICAMENTOS.map(
      (m) => `
        <label class="med-option" data-color="${m.color}">
          <input type="radio" name="medicamento" value="${m.color}" />
          <span class="radio" aria-hidden="true"></span>
          <span class="tray-dot" data-color="${m.color}" aria-hidden="true"></span>
          <span class="option-body">
            <span class="option-name">${nombreCompleto(m)}</span>
            <span class="option-meta">${m.presentacion} · ${m.bandeja}</span>
          </span>
          <span class="option-stock">—</span>
        </label>`
    ).join("")
  );

  els.log.innerHTML = `<tr class="log-empty"><td colspan="3">Sin actividad registrada en esta sesión.</td></tr>`;

  els.rows.addEventListener("animationend", (e) => e.target.classList.remove("is-updated"));
  els.options.addEventListener("change", (e) => seleccionar(e.target.value));
  els.form.addEventListener("submit", (e) => {
    e.preventDefault();
    dispensar();
  });
  buildAsistenteUI();
  buildRestockUI();
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) fetchInventario();
  });
}

function render(prev = state.inventario) {
  let unidades = 0;
  let alertas = 0;
  let conocido = false;

  for (const m of MEDICAMENTOS) {
    const n = state.inventario[m.color];
    const tieneDato = Number.isInteger(n);
    const row = els.rows.querySelector(`tr[data-color="${m.color}"]`);
    const est = pintarFilaInventario(row, n);
    if (est) {
      conocido = true;
      unidades += n;
      if (est.clave !== "ok") alertas += 1;
    }
    row.classList.toggle("is-active", state.enCurso && state.seleccion === m.color);
    if (tieneDato && Number.isInteger(prev[m.color]) && n < prev[m.color]) {
      row.classList.remove("is-updated");
      void row.offsetWidth;
      row.classList.add("is-updated");
    }

    const opt = els.options.querySelector(`.med-option[data-color="${m.color}"]`);
    const input = opt.querySelector("input");
    const sinStock = !tieneDato || n <= 0;
    if (sinStock && !state.enCurso && state.seleccion === m.color) state.seleccion = null;
    input.disabled = state.enCurso || sinStock;
    input.checked = state.seleccion === m.color;
    opt.classList.toggle("is-selected", input.checked);
    opt.classList.toggle("is-disabled", input.disabled);
    opt.dataset.empty = String(tieneDato && n <= 0);
    opt.querySelector(".option-stock").textContent = !tieneDato ? "—" : n > 0 ? `${n} ud.` : "Agotado";
  }

  els.summaryUnits.textContent = conocido ? String(unidades) : "—";
  els.summaryAlerts.textContent = conocido ? String(alertas) : "—";
  els.summaryAlerts.dataset.alert = String(alertas > 0);

  els.restockBtn.disabled = state.enCurso || state.reponiendo || !state.conectado;
  const med = buscarMed(state.seleccion);
  els.btn.disabled = state.enCurso || state.reponiendo || !med || !state.conectado;
  els.btn.classList.toggle("is-loading", state.enCurso);
  els.btnLabel.textContent = state.enCurso
    ? "Dispensando…"
    : !state.conectado && state.conectado !== null
      ? "Sistema sin conexión"
      : med
        ? `Dispensar ${nombreCompleto(med)}`
        : "Seleccione un medicamento";
  els.rxChip.hidden = !(med && state.receta?.color === med.color);

  const ocupado = state.enCurso || state.reponiendo || !state.conectado;
  els.voiceBtn.disabled = !SpeechRecognition || state.interpretandoVoz || (ocupado && !state.escuchando);
  els.voiceBtn.classList.toggle("is-listening", state.escuchando);
  els.voiceLabel.textContent = !SpeechRecognition
    ? "Voz no disponible"
    : state.escuchando
      ? "Escuchando…"
      : state.interpretandoVoz
        ? "Interpretando…"
        : "Pedir por voz";
  els.voiceSub.textContent = !SpeechRecognition
    ? "Use Chrome o Edge"
    : state.escuchando
      ? "Pulse para terminar"
      : "Diga el medicamento";
  els.rxBtn.disabled = ocupado || state.validandoReceta;
  els.rxValidate.disabled = ocupado || state.validandoReceta || !state.rxArchivo;
  els.rxValidate.textContent = state.validandoReceta ? "Leyendo receta…" : "Validar con IA";
  els.rxDiscard.disabled = state.validandoReceta;
}

function setInventario(nuevo) {
  const prev = state.inventario;
  state.inventario = nuevo;
  render(prev);
}

function addLog(evento, nivel = "info") {
  els.log.querySelector(".log-empty")?.remove();
  const tr = document.createElement("tr");
  tr.innerHTML = `<td class="log-time"></td><td class="log-event"></td><td class="log-result"><span class="badge"></span></td>`;
  tr.cells[0].textContent = fmtTime(new Date());
  tr.cells[1].textContent = evento;
  const badge = tr.querySelector(".badge");
  badge.dataset.state = nivel;
  badge.textContent = NIVELES_LOG[nivel];
  els.log.prepend(tr);
  while (els.log.rows.length > MAX_LOG) els.log.deleteRow(-1);
}

function setConexion(ok, detalle) {
  if (state.conectado === ok) return;
  const antes = state.conectado;
  state.conectado = ok;
  els.connection.dataset.state = ok ? "online" : "offline";
  els.connectionLabel.textContent = ok ? "Sistema en línea" : "Sin conexión";
  if (!ok) addLog(`Conexión con el dispensador perdida (${detalle})`, "error");
  else if (antes === false) addLog("Conexión con el dispensador restablecida", "success");
  else addLog("Sistema iniciado. Esperando órdenes de dispensación.");
  render();
}

function setProgreso(paso, estado, detalle) {
  const idx = PASOS.indexOf(paso);
  els.progress.hidden = false;
  els.progress.dataset.result = estado === "done" ? "success" : estado === "error" ? "error" : "";
  els.progress.querySelectorAll(".step").forEach((li, i) => {
    li.dataset.state = i < idx ? "done" : i === idx ? estado : "pending";
  });
  els.progressDetail.textContent = detalle;
}

let cronometro = null;

function iniciarCronometro() {
  const inicio = Date.now();
  const tick = () => {
    const s = Math.floor((Date.now() - inicio) / 1000);
    els.progressTimer.textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  };
  tick();
  cronometro = setInterval(tick, 250);
}

function detenerCronometro() {
  clearInterval(cronometro);
}

function mensajeError(res, data) {
  if (res.status === 502) return "El robot de dispensación reportó un fallo. Revise la bandeja.";
  if (res.status === 504) return "El robot no respondió a tiempo.";
  const detail = data.detail || res.statusText || `HTTP ${res.status}`;
  return Array.isArray(detail) ? detail.map((d) => d.msg).join(", ") : String(detail);
}

async function fetchInventario() {
  const version = state.inventarioVersion;
  try {
    const res = await fetch("/inventario", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    setConexion(true);
    els.lastSync.textContent = `Sincronizado ${fmtTime(new Date())}`;
    if (version === state.inventarioVersion) setInventario(data);
  } catch (err) {
    setConexion(false, err instanceof TypeError ? "servidor no disponible" : err.message);
  }
}

function seleccionar(color) {
  state.seleccion = color;
  if (!state.enCurso) els.progress.hidden = true;
  render();
}

async function pedirAlRobot(med, recetaId) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch("/solicitar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ color: med.color, receta_id: recetaId }),
      signal: controller.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(mensajeError(res, data));
    if (data.status !== "completado") throw new Error("El robot no confirmó la entrega.");
    return data;
  } catch (err) {
    if (err.name === "AbortError") throw new Error("Tiempo de espera agotado.");
    if (err instanceof TypeError) throw new Error("No se pudo contactar con el servidor.");
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

async function dispensar() {
  const med = buscarMed(state.seleccion);
  if (!med || state.enCurso) return;
  const recetaId = state.receta?.color === med.color ? state.receta.id : null;
  await dispensarCola([{ ...med, recetaId }]);
}

/** One cube at a time. The next request starts only after status "completado". */
async function dispensarCola(cola) {
  if (state.enCurso || cola.length === 0) return;
  state.cola = cola;
  state.enCurso = true;
  state.seleccion = cola[0].color;
  render();
  iniciarCronometro();

  let entregados = 0;
  try {
    for (let i = 0; i < cola.length; i++) {
      const med = cola[i];
      const nombre = nombreCompleto(med);
      const puesto = cola.length > 1 ? ` (${i + 1} de ${cola.length})` : "";
      state.seleccion = med.color;
      render();
      els.progressTitle.textContent = `${nombre}${puesto}`;
      setProgreso("dispensando", "active", `${med.bandeja}: el robot está preparando la entrega…`);
      addLog(`Orden de dispensación${puesto}: ${nombre} (${med.bandeja})${med.recetaId ? " con receta validada" : ""}`);

      const data = await pedirAlRobot(med, med.recetaId ?? null);
      entregados += 1;
      state.inventarioVersion += 1;
      setInventario(data.inventario ?? state.inventario);
      addLog(`Dispensación completada${puesto}: ${nombre}`, "success");
    }
    state.seleccion = null;
    state.cola = [];
    descartarReceta();
    const cierre = entregados > 1 ? `Entregados ${entregados} medicamentos` : "Entregado";
    setProgreso("entregada", "done", `${cierre} a las ${fmtTime(new Date())}. Retire el medicamento de la bandeja.`);
  } catch (err) {
    const med = cola[entregados];
    const nombre = med ? nombreCompleto(med) : "la orden";
    const previos = entregados > 0 ? ` Se entregaron ${entregados} antes de detener la cola.` : "";
    setProgreso("dispensando", "error", `${err.message}${previos}`);
    addLog(`Dispensación fallida: ${nombre}. ${err.message}`, "error");
    state.cola = [];
  } finally {
    detenerCronometro();
    state.enCurso = false;
    render();
    fetchInventario();
  }
}

function setAsistente(tono, texto) {
  els.assistStatus.hidden = !texto;
  els.assistStatus.dataset.tone = tono;
  els.assistStatus.textContent = texto ?? "";
}

/** Selects a medication suggested by voice or a prescription, unless its tray is empty. */
function sugerir(color, origen) {
  const med = buscarMed(color);
  if (!med) return false;
  if (!(state.inventario[color] > 0)) {
    setAsistente("warning", `${origen}: ${nombreCompleto(med)}, pero está agotado. Avise al personal.`);
    return false;
  }
  if (!state.enCurso) seleccionar(color);
  return true;
}

function buildAsistenteUI() {
  if (!SpeechRecognition) {
    els.voiceBtn.title = "El navegador no admite reconocimiento de voz. Use Google Chrome o Edge.";
  }
  els.voiceBtn.addEventListener("click", alternarVoz);
  els.rxBtn.addEventListener("click", () => els.rxInput.click());
  els.rxInput.addEventListener("change", () => {
    const archivo = els.rxInput.files?.[0];
    els.rxInput.value = "";
    if (archivo) capturarReceta(archivo);
  });
  els.rxValidate.addEventListener("click", validarReceta);
  els.rxDiscard.addEventListener("click", () => {
    descartarReceta();
    render();
  });
  els.queueForm.addEventListener("submit", (e) => {
    e.preventDefault();
    confirmarCola();
  });
  els.queueList.addEventListener("change", actualizarColaModal);
  const cerrarCola = () => {
    if (!state.enCurso) els.queueDialog.close();
  };
  els.queueDialog.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", cerrarCola));
  els.queueDialog.addEventListener("cancel", (e) => {
    if (state.enCurso) e.preventDefault();
  });
}

const ERRORES_VOZ = {
  "not-allowed": "Permiso de micrófono denegado. En Chrome: el candado de la barra de dirección → Micrófono → Permitir.",
  "service-not-allowed": "Permiso de micrófono denegado. En Chrome: el candado de la barra de dirección → Micrófono → Permitir.",
  "no-speech": "No se detectó voz. Hable más cerca del micrófono y pulse de nuevo.",
  "audio-capture": "No se encontró ningún micrófono. Revise la entrada de sonido del sistema.",
  network: "El reconocimiento de voz necesita internet y Google Chrome o Edge.",
};

let reconocimiento = null;
let flujoMic = null;
let seguirEscuchando = false;
let textoOido = "";
let errorVoz = null;

function liberarMic() {
  flujoMic?.getTracks().forEach((track) => track.stop());
  flujoMic = null;
}

function arrancarReconocimiento() {
  reconocimiento = new SpeechRecognition();
  reconocimiento.lang = "es-ES";
  reconocimiento.interimResults = true;
  // Stays open until the user taps again. The default (one short utterance) ends
  // with "no speech" before most people start talking.
  reconocimiento.continuous = true;
  reconocimiento.maxAlternatives = 3;

  reconocimiento.onresult = (e) => {
    textoOido = Array.from(e.results, (r) => r[0].transcript).join(" ").trim();
    errorVoz = null;
    setAsistente("info", `«${textoOido}»`);
  };
  reconocimiento.onerror = (e) => {
    // Chrome ends the session with no-speech on silence; onend restarts it while listening.
    if (e.error === "no-speech" || e.error === "aborted") return;
    errorVoz = ERRORES_VOZ[e.error] ?? `Error de reconocimiento de voz (${e.error}).`;
    seguirEscuchando = false;
  };
  reconocimiento.onend = () => {
    if (seguirEscuchando) {
      try {
        reconocimiento.start();
        return;
      } catch {
        // A start() that races with the previous session falls through and stops.
      }
    }
    const texto = textoOido;
    const fallo = errorVoz;
    state.escuchando = false;
    liberarMic();
    render();
    if (fallo) setAsistente("error", fallo);
    else if (texto) interpretarVoz(texto);
    else setAsistente("warning", ERRORES_VOZ["no-speech"]);
  };

  reconocimiento.start();
}

async function alternarVoz() {
  if (state.escuchando) {
    seguirEscuchando = false;
    reconocimiento?.stop();
    return;
  }
  if (!SpeechRecognition || state.enCurso) return;
  if (!window.isSecureContext) {
    setAsistente(
      "error",
      "Chrome no entrega el micrófono en http://192.168…. Abra http://localhost:8080 en el equipo del micrófono."
    );
    return;
  }

  textoOido = "";
  errorVoz = null;
  try {
    // Primes the microphone. Speech recognition alone often starts without audio and reports no speech.
    flujoMic = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    setAsistente("error", ERRORES_VOZ["not-allowed"]);
    return;
  }

  seguirEscuchando = true;
  try {
    arrancarReconocimiento();
  } catch {
    seguirEscuchando = false;
    liberarMic();
    setAsistente("error", "No se pudo iniciar el reconocimiento de voz.");
    return;
  }
  state.escuchando = true;
  setAsistente("info", "Escuchando… diga el medicamento, por ejemplo «Paracetamol», y pulse otra vez para terminar.");
  render();
}

async function interpretarVoz(texto) {
  state.interpretandoVoz = true;
  render();
  try {
    const res = await fetch("/interpretar-voz", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(mensajeError(res, data));

    const med = buscarMed(data.color);
    if (sugerir(data.color, "Reconocido por voz")) {
      setAsistente("success", `Reconocido por voz: ${nombreCompleto(med)} («${texto}»). Confirme con el botón Dispensar.`);
      addLog(`Pedido por voz: ${nombreCompleto(med)} («${texto}»)`);
    }
  } catch (err) {
    const msg = err instanceof TypeError ? "No se pudo contactar con el servidor." : err.message;
    setAsistente("warning", `«${texto}»: ${msg}`);
  } finally {
    state.interpretandoVoz = false;
    render();
  }
}

function pintarReceta(estado, titulo, detalle, { badge = null, ocr = null } = {}) {
  els.rxCard.hidden = false;
  els.rxCard.dataset.state = estado;
  els.rxTitle.textContent = titulo;
  els.rxDetail.textContent = detalle;
  els.rxBadge.hidden = !badge;
  els.rxBadge.dataset.state = badge?.estado ?? "";
  els.rxBadge.textContent = badge?.texto ?? "";
  els.rxOcr.hidden = !ocr;
  els.rxOcr.textContent = ocr ? `Texto leído: ${ocr}` : "";
}

function capturarReceta(archivo) {
  descartarReceta();
  state.rxArchivo = archivo;
  els.rxPreview.src = URL.createObjectURL(archivo);
  const med = buscarMed(state.seleccion);
  pintarReceta(
    "pending",
    "Receta capturada",
    med
      ? `Se comprobará que la receta incluya ${nombreCompleto(med)}.`
      : "Se detectará qué medicamento indica la receta."
  );
  render();
}

function descartarReceta() {
  if (els.rxPreview.src) URL.revokeObjectURL(els.rxPreview.src);
  els.rxPreview.removeAttribute("src");
  els.rxCard.hidden = true;
  state.rxArchivo = null;
  state.receta = null;
}

async function validarReceta() {
  if (!state.rxArchivo || state.validandoReceta) return;
  const pedido = buscarMed(state.seleccion);
  const form = new FormData();
  form.append("imagen", state.rxArchivo);
  if (pedido) form.append("color", pedido.color);

  state.validandoReceta = true;
  state.receta = null;
  pintarReceta("validating", "Validando receta…", "La IA está leyendo la receta.");
  render();
  try {
    const res = await fetch("/validar-receta", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(mensajeError(res, data));

    if (data.detectados?.length > 1) {
      const nombres = data.detectados.map((m) => m.nombre).join(" y ");
      pintarReceta("ok", "Varios medicamentos en la receta", data.motivo, {
        badge: { estado: "info", texto: "Seleccione" },
      });
      addLog(`Receta leída: ${nombres}. Pendiente de elegir la cola.`, "info");
      abrirCola(data.detectados);
    } else if (data.autorizado) {
      state.receta = { id: data.id, color: data.color, medicamento: data.medicamento };
      const detalle = data.fragmento ? `${data.motivo} Detectado: «${data.fragmento}».` : data.motivo;
      pintarReceta("ok", "Receta validada por IA", detalle, { badge: { estado: "success", texto: "Autorizada" } });
      addLog(`Receta validada por IA: ${data.medicamento}`, "success");
      sugerir(data.color, "La receta indica");
    } else {
      const ocr = data.texto_ocr ? data.texto_ocr.slice(0, MAX_TEXTO_OCR_UI) : null;
      pintarReceta("rejected", "Receta no válida", data.motivo, {
        badge: { estado: "error", texto: "Rechazada" },
        ocr,
      });
      addLog(`Receta rechazada por IA: ${data.motivo}`, "warning");
    }
  } catch (err) {
    const msg = err instanceof TypeError ? "No se pudo contactar con el servidor." : err.message;
    pintarReceta("error", "No se pudo validar la receta", msg);
    addLog(`Validación de receta fallida. ${msg}`, "error");
  } finally {
    state.validandoReceta = false;
    render();
  }
}

function abrirCola(detectados) {
  els.queueList.innerHTML = detectados
    .map((m) => {
      const stock = state.inventario[m.color];
      const agotado = !(stock > 0);
      return `
        <li class="restock-row${agotado ? "" : " is-selected"}" data-color="${m.color}">
          <label class="restock-select">
            <input type="checkbox" value="${m.color}" ${agotado ? "disabled" : "checked"} />
            <span class="checkbox" aria-hidden="true"></span>
            <span class="tray-dot" data-color="${m.color}" aria-hidden="true"></span>
            <span class="option-body">
              <span class="option-name">${m.nombre} ${m.dosis}</span>
              <span class="option-meta">${m.bandeja}${m.fragmento ? ` · «${m.fragmento}»` : ""}${agotado ? " · Agotado" : ""}</span>
            </span>
          </label>
        </li>`;
    })
    .join("");
  actualizarColaModal();
  els.queueDialog.showModal();
}

function actualizarColaModal() {
  const marcados = els.queueList.querySelectorAll("input:checked").length;
  for (const row of els.queueList.querySelectorAll(".restock-row")) {
    row.classList.toggle("is-selected", row.querySelector("input").checked);
  }
  els.queueSubmit.disabled = marcados === 0;
  els.queueSubmitLabel.textContent =
    marcados === 0 ? "Seleccione un medicamento" : `Dispensar ${marcados} ${marcados === 1 ? "cubo" : "cubos"}`;
}

function confirmarCola() {
  const cola = [...els.queueList.querySelectorAll("input:checked")].map((input) => {
    const med = buscarMed(input.value);
    return { ...med, recetaId: null };
  });
  els.queueDialog.close();
  dispensarCola(cola);
}

const clampStock = (v) => Math.min(MAX_STOCK, Math.max(0, Number.isFinite(v) ? Math.round(v) : 0));
const filaReposicion = (color) => els.restockList.querySelector(`.restock-row[data-color="${color}"]`);
const objetivoReposicion = () => STOCK_REFERENCIA;

function buildRestockUI() {
  els.restockHint.textContent = `Objetivo de reposición: ${STOCK_REFERENCIA} ud. · Máximo: ${MAX_STOCK} ud.`;
  els.restockList.innerHTML = MEDICAMENTOS.map(
    (m) => `
      <li class="restock-row" data-color="${m.color}">
        <label class="restock-select">
          <input type="checkbox" value="${m.color}" />
          <span class="checkbox" aria-hidden="true"></span>
          <span class="tray-dot" data-color="${m.color}" aria-hidden="true"></span>
          <span class="option-body">
            <span class="option-name">${nombreCompleto(m)}</span>
            <span class="option-meta">${m.bandeja} · Actual: <span class="restock-current">—</span></span>
          </span>
        </label>
        <div class="restock-qty">
          <span class="restock-delta" aria-hidden="true"></span>
          <div class="stepper">
            <button type="button" data-step="-1" aria-label="Quitar una unidad de ${m.nombre}">−</button>
            <input type="number" min="0" max="${MAX_STOCK}" step="1" inputmode="numeric"
              aria-label="Unidades de ${m.nombre} tras reponer" />
            <button type="button" data-step="1" aria-label="Añadir una unidad de ${m.nombre}">+</button>
          </div>
        </div>
      </li>`
  ).join("");

  els.restockBtn.addEventListener("click", abrirReposicion);
  els.restockForm.addEventListener("submit", (e) => {
    e.preventDefault();
    reponer();
  });
  els.restockList.addEventListener("change", (e) => {
    const row = e.target.closest(".restock-row");
    if (!row) return;
    const actual = Number(row.dataset.actual);
    const input = row.querySelector("input[type=number]");
    if (e.target.type === "number") {
      input.value = clampStock(input.valueAsNumber);
      row.querySelector("input[type=checkbox]").checked = true;
    } else if (e.target.type === "checkbox") {
      if (e.target.checked) {
        if (Number(input.value) === actual) input.value = objetivoReposicion();
      } else {
        input.value = actual;
      }
    }
    actualizarReposicion();
  });
  els.restockList.addEventListener("input", (e) => {
    if (e.target.type !== "number") return;
    e.target.closest(".restock-row").querySelector("input[type=checkbox]").checked = true;
    actualizarReposicion();
  });
  els.restockList.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-step]");
    if (!btn) return;
    const row = btn.closest(".restock-row");
    const input = row.querySelector("input[type=number]");
    input.value = clampStock(input.valueAsNumber + Number(btn.dataset.step));
    row.querySelector("input[type=checkbox]").checked = true;
    actualizarReposicion();
  });
  els.restockAll.addEventListener("change", () => {
    for (const cb of els.restockList.querySelectorAll("input[type=checkbox]")) {
      cb.checked = els.restockAll.checked;
      const row = cb.closest(".restock-row");
      const actual = Number(row.dataset.actual);
      const input = row.querySelector("input[type=number]");
      input.value = els.restockAll.checked ? objetivoReposicion() : actual;
    }
    actualizarReposicion();
  });

  const cerrar = () => {
    if (!state.reponiendo) els.restockDialog.close();
  };
  els.restockDialog.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", cerrar));
  els.restockDialog.addEventListener("click", (e) => {
    if (e.target === els.restockDialog) cerrar();
  });
  els.restockDialog.addEventListener("cancel", (e) => {
    if (state.reponiendo) e.preventDefault();
  });
  els.restockDialog.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      cerrar();
    }
  });
}

function rellenarModalReposicion() {
  for (const m of MEDICAMENTOS) {
    const actual = state.inventario[m.color] ?? 0;
    const row = filaReposicion(m.color);
    row.dataset.actual = String(actual);
    row.querySelector(".restock-current").textContent = `${actual} ud.`;
    row.querySelector("input[type=checkbox]").checked = false;
    row.querySelector("input[type=number]").value = actual;
  }
}

async function abrirReposicion() {
  if (state.enCurso || state.reponiendo) return;
  await fetchInventario();
  rellenarModalReposicion();
  els.restockError.hidden = true;
  actualizarReposicion();
  els.restockDialog.showModal();
}

function seleccionReposicion() {
  const stock = {};
  for (const row of els.restockList.querySelectorAll(".restock-row")) {
    if (row.querySelector("input[type=checkbox]").checked) {
      stock[row.dataset.color] = clampStock(row.querySelector("input[type=number]").valueAsNumber);
    }
  }
  return stock;
}

function actualizarReposicion() {
  const stock = seleccionReposicion();
  const n = Object.keys(stock).length;

  for (const row of els.restockList.querySelectorAll(".restock-row")) {
    const seleccionada = row.dataset.color in stock;
    const delta = seleccionada ? stock[row.dataset.color] - Number(row.dataset.actual) : 0;
    const deltaEl = row.querySelector(".restock-delta");
    row.classList.toggle("is-selected", seleccionada);
    deltaEl.textContent = delta === 0 ? "" : delta > 0 ? `+${delta}` : String(delta);
    deltaEl.dataset.sign = delta > 0 ? "up" : delta < 0 ? "down" : "";
    row.querySelectorAll("input, button").forEach((el) => (el.disabled = state.reponiendo));
  }

  els.restockAll.checked = n === MEDICAMENTOS.length;
  els.restockAll.indeterminate = n > 0 && n < MEDICAMENTOS.length;
  els.restockAll.disabled = state.reponiendo;
  const hayCambios = Object.entries(stock).some(
    ([color, qty]) => qty !== Number(filaReposicion(color).dataset.actual)
  );
  els.restockSubmit.disabled = state.reponiendo || n === 0 || !hayCambios;
  els.restockSubmit.classList.toggle("is-loading", state.reponiendo);
  els.restockSubmitLabel.textContent = state.reponiendo
    ? "Reponiendo…"
    : n === 0
      ? "Seleccione una bandeja"
      : !hayCambios
        ? "Sin cambios de stock"
        : `Reponer ${n} ${n === 1 ? "bandeja" : "bandejas"}`;
}

async function reponer() {
  const stock = seleccionReposicion();
  if (state.enCurso || state.reponiendo || Object.keys(stock).length === 0) return;
  const antes = { ...state.inventario };

  state.reponiendo = true;
  els.restockError.hidden = true;
  actualizarReposicion();
  render();
  try {
    const res = await fetch("/reponer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stock }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(mensajeError(res, data));

    state.inventarioVersion += 1;
    setInventario(data);
    const cambios = MEDICAMENTOS.filter((m) => m.color in stock)
      .map((m) =>
        antes[m.color] === data[m.color]
          ? `${nombreCompleto(m)} ${data[m.color]} ud. (sin cambios)`
          : `${nombreCompleto(m)} ${antes[m.color] ?? "—"} → ${data[m.color]} ud.`
      )
      .join("; ");
    addLog(`Reposición: ${cambios}`, "success");
    state.reponiendo = false;
    els.restockDialog.close();
  } catch (err) {
    const msg = err instanceof TypeError ? "No se pudo contactar con el servidor." : err.message;
    els.restockError.textContent = `No se pudo reponer. ${msg}`;
    els.restockError.hidden = false;
    addLog(`Reposición fallida. ${msg}`, "error");
  } finally {
    state.reponiendo = false;
    actualizarReposicion();
    render();
  }
}

function tickReloj() {
  const now = new Date();
  els.clockDate.textContent = fmtDate(now);
  els.clockTime.textContent = fmtTime(now);
}

async function iniciar() {
  tickReloj();
  setInterval(tickReloj, 1000);
  render();
  for (;;) {
    try {
      MEDICAMENTOS = await cargarCatalogo();
      break;
    } catch (err) {
      setConexion(false, err instanceof TypeError ? "servidor no disponible" : err.message);
      await sleep(POLL_MS);
    }
  }
  buildUI();
  render();
  fetchInventario();
  setInterval(() => {
    if (!document.hidden) fetchInventario();
  }, POLL_MS);
}

iniciar();

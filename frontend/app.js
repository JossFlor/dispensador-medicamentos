// `color` must match the tray identifiers used by the API and the robot.
const MEDICAMENTOS = [
  { color: "rojo", nombre: "Paracetamol", dosis: "500 mg", presentacion: "Comprimidos", bandeja: "Bandeja A · Roja" },
  { color: "amarillo", nombre: "Ibuprofeno", dosis: "400 mg", presentacion: "Comprimidos", bandeja: "Bandeja B · Amarilla" },
  { color: "verde", nombre: "Amoxicilina", dosis: "500 mg", presentacion: "Cápsulas", bandeja: "Bandeja C · Verde" },
  { color: "azul", nombre: "Omeprazol", dosis: "20 mg", presentacion: "Cápsulas", bandeja: "Bandeja D · Azul" },
];

const POLL_MS = 2000;
const REQUEST_TIMEOUT_MS = 130_000;
const STOCK_REFERENCIA = 3;
const STOCK_BAJO = 1;
const MAX_LOG = 50;
const PASOS = ["registrada", "dispensando", "entregada"];
const NIVELES_LOG = { info: "Info", success: "Correcto", warning: "Aviso", error: "Error" };

const state = {
  inventario: {},
  seleccion: null,
  enCurso: false,
  reponiendo: false,
  conectado: null,
  inventarioVersion: 0,
};

const $ = (id) => document.getElementById(id);
const els = {
  rows: $("inventory-rows"),
  form: $("dispense-form"),
  options: $("med-options"),
  btn: $("dispense-btn"),
  btnLabel: $("dispense-label"),
  restockBtn: $("restock-btn"),
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
};

const fmtTime = (d) => d.toLocaleTimeString("es-ES", { hour12: false });
const fmtDate = (d) => d.toLocaleDateString("es-ES", { weekday: "short", day: "2-digit", month: "short" });
const nombreCompleto = (med) => `${med.nombre} ${med.dosis}`;
const buscarMed = (color) => MEDICAMENTOS.find((m) => m.color === color);

function estadoStock(n) {
  if (n <= 0) return { clave: "agotado", texto: "Agotado" };
  if (n <= STOCK_BAJO) return { clave: "bajo", texto: "Stock bajo" };
  return { clave: "ok", texto: "Disponible" };
}

function buildUI() {
  els.rows.innerHTML = MEDICAMENTOS.map(
    (m) => `
      <tr data-color="${m.color}">
        <td class="col-med">
          <div class="med-name">${m.nombre} <span class="med-dose">${m.dosis}</span></div>
          <div class="med-meta">${m.presentacion}</div>
        </td>
        <td class="col-tray"><span class="tray"><span class="tray-dot" data-color="${m.color}"></span>${m.bandeja}</span></td>
        <td class="col-stock">
          <div class="stock">
            <span class="stock-value">—</span>
            <span class="stock-bar"><span class="stock-fill"></span></span>
          </div>
        </td>
        <td class="col-status"><span class="badge">Cargando</span></td>
      </tr>`
  ).join("");

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
  els.options.addEventListener("change", (e) => {
    state.seleccion = e.target.value;
    if (!state.enCurso) els.progress.hidden = true;
    render();
  });
  els.form.addEventListener("submit", (e) => {
    e.preventDefault();
    dispensar();
  });
  els.restockBtn.addEventListener("click", reponer);
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
    const est = tieneDato ? estadoStock(n) : null;
    if (tieneDato) {
      conocido = true;
      unidades += n;
      if (est.clave !== "ok") alertas += 1;
    }

    const row = els.rows.querySelector(`tr[data-color="${m.color}"]`);
    const fill = row.querySelector(".stock-fill");
    const badge = row.querySelector(".badge");
    row.querySelector(".stock-value").textContent = tieneDato ? String(n) : "—";
    fill.style.width = tieneDato ? `${Math.min(100, (n / STOCK_REFERENCIA) * 100)}%` : "0%";
    fill.dataset.state = est?.clave ?? "";
    badge.textContent = est?.texto ?? "Cargando";
    badge.dataset.state = est?.clave ?? "";
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
  els.restockBtn.textContent = state.reponiendo ? "Reponiendo…" : "Reponer stock";

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
  const detail = data.detail ?? res.statusText;
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

async function dispensar() {
  const med = buscarMed(state.seleccion);
  if (!med || state.enCurso) return;
  const nombre = nombreCompleto(med);

  state.enCurso = true;
  render();
  els.progressTitle.textContent = nombre;
  setProgreso("dispensando", "active", `${med.bandeja}: el robot está preparando la entrega…`);
  iniciarCronometro();
  addLog(`Orden de dispensación: ${nombre} (${med.bandeja})`);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const res = await fetch("/solicitar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ color: med.color }),
      signal: controller.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(mensajeError(res, data));

    state.inventarioVersion += 1;
    state.enCurso = false;
    state.seleccion = null;
    setInventario(data.inventario ?? state.inventario);
    setProgreso("entregada", "done", `Entregado a las ${fmtTime(new Date())}. Retire el medicamento de la bandeja.`);
    addLog(`Dispensación completada: ${nombre}`, "success");
  } catch (err) {
    const msg =
      err.name === "AbortError"
        ? "Tiempo de espera agotado."
        : err instanceof TypeError
          ? "No se pudo contactar con el servidor."
          : err.message;
    setProgreso("dispensando", "error", msg);
    addLog(`Dispensación fallida: ${nombre}. ${msg}`, "error");
  } finally {
    clearTimeout(timeoutId);
    detenerCronometro();
    state.enCurso = false;
    render();
    fetchInventario();
  }
}

async function reponer() {
  if (state.enCurso || state.reponiendo) return;
  state.reponiendo = true;
  render();
  try {
    const res = await fetch("/reponer", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(mensajeError(res, data));
    state.inventarioVersion += 1;
    setInventario(data);
    addLog("Inventario repuesto: todas las bandejas al stock inicial", "success");
  } catch (err) {
    const msg = err instanceof TypeError ? "No se pudo contactar con el servidor." : err.message;
    addLog(`Reposición fallida. ${msg}`, "error");
  } finally {
    state.reponiendo = false;
    render();
  }
}

function tickReloj() {
  const now = new Date();
  els.clockDate.textContent = fmtDate(now);
  els.clockTime.textContent = fmtTime(now);
}

buildUI();
render();
tickReloj();
setInterval(tickReloj, 1000);
fetchInventario();
setInterval(() => {
  if (!document.hidden) fetchInventario();
}, POLL_MS);

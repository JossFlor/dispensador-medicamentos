import {
  STOCK_REFERENCIA,
  cargarCatalogo,
  filaInventarioHTML,
  fmtDate,
  fmtTime,
  nombreCompleto,
  pintarFilaInventario,
  sleep,
} from "./comun.js";

const POLL_MS = 3000;
const MAX_RECETAS = 50;
const MAX_STOCK = 20;
const MODOS = { lelab: "Robot físico (LeLab)", stub: "Simulación" };

let MEDICAMENTOS = [];
let inventario = {};
let reponiendo = false;
let robotOcupado = false;

const $ = (id) => document.getElementById(id);
const els = {
  rows: $("inventory-rows"),
  recetas: $("recetas-rows"),
  lastSync: $("last-sync"),
  connection: $("connection"),
  connectionLabel: $("connection-label"),
  clockDate: $("clock-date"),
  clockTime: $("clock-time"),
  summaryUnits: $("summary-units"),
  summaryRxOk: $("summary-rx-ok"),
  summaryRxRejected: $("summary-rx-rejected"),
  robotState: $("robot-state"),
  robotStateLabel: $("robot-state-label"),
  robotMode: $("robot-mode"),
  robotCurrent: $("robot-current"),
  robotActivity: $("robot-activity"),
  brakeBtn: $("brake-btn"),
  robotNote: $("robot-controls-note"),
  restockBtn: $("restock-btn"),
  restockDialog: $("restock-dialog"),
  restockForm: $("restock-form"),
  restockList: $("restock-list"),
  restockAll: $("restock-all"),
  restockHint: $("restock-hint"),
  restockError: $("restock-error"),
  restockSubmit: $("restock-submit"),
  restockSubmitLabel: $("restock-submit-label"),
};

const buscarMed = (color) => MEDICAMENTOS.find((m) => m.color === color);

function setConexion(ok) {
  els.connection.dataset.state = ok ? "online" : "offline";
  els.connectionLabel.textContent = ok ? "Sistema en línea" : "Sin conexión";
  if (!ok) {
    els.robotState.dataset.state = "offline";
    els.robotStateLabel.textContent = "Sin conexión";
    els.restockBtn.disabled = true;
    els.brakeBtn.disabled = true;
  }
}

async function ordenRobot(ruta, nota) {
  els.brakeBtn.disabled = true;
  els.robotNote.hidden = false;
  els.robotNote.textContent = "Enviando orden al robot…";
  try {
    const res = await fetch(ruta, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    els.robotNote.textContent = nota;
  } catch (err) {
    els.robotNote.textContent = err instanceof TypeError ? "No se pudo contactar con el servidor." : err.message;
  }
  await actualizar();
}

async function getJSON(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function pintarEstado(estado) {
  inventario = estado.inventario;
  robotOcupado = estado.robot_ocupado;
  els.restockBtn.disabled = robotOcupado || reponiendo;
  els.brakeBtn.disabled = false;
  let unidades = 0;
  for (const m of MEDICAMENTOS) {
    const n = inventario[m.color];
    pintarFilaInventario(els.rows.querySelector(`tr[data-color="${m.color}"]`), n);
    unidades += n;
  }
  els.summaryUnits.textContent = String(unidades);

  const enCurso = buscarMed(estado.dispensando);
  els.robotState.dataset.state = estado.robot_ocupado ? "ocupado" : "libre";
  els.robotStateLabel.textContent = estado.robot_ocupado ? "Dispensando" : "Disponible";
  els.robotMode.textContent = MODOS[estado.modo_robot] ?? estado.modo_robot;
  els.robotCurrent.textContent = enCurso ? `${nombreCompleto(enCurso)} · ${enCurso.bandeja}` : "Ninguna";
  const act = estado.ultima_actividad;
  els.robotActivity.textContent = act ? `${fmtTime(new Date(act.timestamp))} · ${act.evento}` : "Sin actividad desde el arranque";
}

function celda(tr, texto, clase) {
  const td = tr.insertCell();
  td.textContent = texto;
  if (clase) td.className = clase;
  return td;
}

function pintarRecetas(recetas) {
  els.summaryRxOk.textContent = String(recetas.filter((r) => r.autorizado).length);
  els.summaryRxRejected.textContent = String(recetas.filter((r) => !r.autorizado).length);

  if (recetas.length === 0) {
    els.recetas.innerHTML = `<tr class="log-empty"><td colspan="5">Todavía no se ha validado ninguna receta.</td></tr>`;
    return;
  }
  const filas = recetas.map((r) => {
    const tr = document.createElement("tr");
    const fecha = new Date(r.timestamp);
    celda(tr, `${fmtDate(fecha)} ${fmtTime(fecha)}`, "col-hora");
    celda(tr, r.medicamento ?? "—");
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.dataset.state = r.autorizado ? "success" : "error";
    badge.textContent = r.autorizado ? "Autorizada" : "Rechazada";
    celda(tr, "").append(badge);
    celda(tr, r.fragmento ? `${r.motivo} «${r.fragmento}»` : r.motivo, "col-fragmento");
    const total = r.detectados?.length > 1 && r.autorizado ? r.detectados.length : 0;
    const hora = r.dispensada_en ? fmtTime(new Date(r.dispensada_en)) : "—";
    celda(tr, total && r.dispensada_en ? `${hora} · ${r.dispensados.length} de ${total}` : hora, "col-dispensada");
    return tr;
  });
  els.recetas.replaceChildren(...filas);
}

async function actualizar() {
  try {
    const [estado, recetas] = await Promise.all([getJSON("/estado"), getJSON(`/recetas?limit=${MAX_RECETAS}`)]);
    setConexion(true);
    pintarEstado(estado);
    pintarRecetas(recetas);
    els.lastSync.textContent = `Sincronizado ${fmtTime(new Date())}`;
  } catch {
    setConexion(false);
  }
}

const clampStock = (v) => Math.min(MAX_STOCK, Math.max(0, Number.isFinite(v) ? Math.round(v) : 0));
const filaReposicion = (color) => els.restockList.querySelector(`.restock-row[data-color="${color}"]`);

function mensajeError(res, data) {
  const detail = data.detail || res.statusText || `HTTP ${res.status}`;
  return Array.isArray(detail) ? detail.map((d) => d.msg).join(", ") : String(detail);
}

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
            <input type="number" min="0" max="${MAX_STOCK}" step="1" inputmode="numeric" aria-label="Unidades de ${m.nombre} tras reponer" />
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
    } else if (e.target.checked) {
      if (Number(input.value) === actual) input.value = STOCK_REFERENCIA;
    } else {
      input.value = actual;
    }
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
      row.querySelector("input[type=number]").value = els.restockAll.checked
        ? STOCK_REFERENCIA
        : row.dataset.actual;
    }
    actualizarReposicion();
  });
  const cerrar = () => {
    if (!reponiendo) els.restockDialog.close();
  };
  els.restockDialog.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", cerrar));
  els.restockDialog.addEventListener("cancel", (e) => {
    if (reponiendo) e.preventDefault();
  });
}

function abrirReposicion() {
  if (robotOcupado || reponiendo) return;
  for (const m of MEDICAMENTOS) {
    const actual = inventario[m.color] ?? 0;
    const row = filaReposicion(m.color);
    row.dataset.actual = String(actual);
    row.querySelector(".restock-current").textContent = `${actual} ud.`;
    row.querySelector("input[type=checkbox]").checked = false;
    row.querySelector("input[type=number]").value = actual;
  }
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
    row.querySelectorAll("input, button").forEach((el) => (el.disabled = reponiendo));
  }
  els.restockAll.checked = n === MEDICAMENTOS.length;
  els.restockAll.indeterminate = n > 0 && n < MEDICAMENTOS.length;
  els.restockAll.disabled = reponiendo;
  const hayCambios = Object.entries(stock).some(([color, qty]) => qty !== Number(filaReposicion(color).dataset.actual));
  els.restockSubmit.disabled = reponiendo || n === 0 || !hayCambios;
  els.restockSubmit.classList.toggle("is-loading", reponiendo);
  els.restockSubmitLabel.textContent = reponiendo
    ? "Reponiendo…"
    : n === 0
      ? "Seleccione una bandeja"
      : !hayCambios
        ? "Sin cambios de stock"
        : `Reponer ${n} ${n === 1 ? "bandeja" : "bandejas"}`;
}

async function reponer() {
  const stock = seleccionReposicion();
  if (robotOcupado || reponiendo || Object.keys(stock).length === 0) return;
  reponiendo = true;
  els.restockError.hidden = true;
  actualizarReposicion();
  try {
    const res = await fetch("/reponer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stock }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(mensajeError(res, data));
    reponiendo = false;
    els.restockDialog.close();
    await actualizar();
  } catch (err) {
    const msg = err instanceof TypeError ? "No se pudo contactar con el servidor." : err.message;
    els.restockError.textContent = `No se pudo reponer. ${msg}`;
    els.restockError.hidden = false;
  } finally {
    reponiendo = false;
    actualizarReposicion();
    els.restockBtn.disabled = robotOcupado || reponiendo;
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
  for (;;) {
    try {
      MEDICAMENTOS = await cargarCatalogo();
      break;
    } catch {
      setConexion(false);
      await sleep(POLL_MS);
    }
  }
  els.rows.innerHTML = MEDICAMENTOS.map(filaInventarioHTML).join("");
  els.brakeBtn.addEventListener("click", () =>
    ordenRobot("/robot/freno", "Freno enviado. El movimiento se detiene; el brazo se queda en su posición actual.")
  );
  buildRestockUI();
  await actualizar();
  setInterval(() => {
    if (!document.hidden) actualizar();
  }, POLL_MS);
}

iniciar();

import {
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
const MODOS = { lelab: "Robot físico (LeLab)", stub: "Simulación" };

let MEDICAMENTOS = [];

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
};

const buscarMed = (color) => MEDICAMENTOS.find((m) => m.color === color);

function setConexion(ok) {
  els.connection.dataset.state = ok ? "online" : "offline";
  els.connectionLabel.textContent = ok ? "Sistema en línea" : "Sin conexión";
  if (!ok) {
    els.robotState.dataset.state = "offline";
    els.robotStateLabel.textContent = "Sin conexión con el servidor";
  }
}

async function getJSON(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function pintarEstado(estado) {
  let unidades = 0;
  for (const m of MEDICAMENTOS) {
    const n = estado.inventario[m.color];
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
    celda(tr, r.dispensada_en ? fmtTime(new Date(r.dispensada_en)) : "—", "col-dispensada");
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
  await actualizar();
  setInterval(() => {
    if (!document.hidden) actualizar();
  }, POLL_MS);
}

iniciar();

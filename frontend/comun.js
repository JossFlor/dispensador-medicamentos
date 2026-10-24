export const STOCK_REFERENCIA = 1;
export const STOCK_BAJO = 1;

export const fmtTime = (d) => d.toLocaleTimeString("es-ES", { hour12: false });
export const fmtDate = (d) => d.toLocaleDateString("es-ES", { weekday: "short", day: "2-digit", month: "short" });
export const nombreCompleto = (med) => `${med.nombre} ${med.dosis}`;
export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function estadoStock(n) {
  if (n <= 0) return { clave: "agotado", texto: "Agotado" };
  if (n <= STOCK_BAJO) return { clave: "bajo", texto: "Stock bajo" };
  return { clave: "ok", texto: "Disponible" };
}

export async function cargarCatalogo() {
  const res = await fetch("/medicamentos", { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export function filaInventarioHTML(m) {
  return `
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
    </tr>`;
}

/** Paints one inventory row; returns the stock state, or null while there is no data. */
export function pintarFilaInventario(row, n) {
  const tieneDato = Number.isInteger(n);
  const est = tieneDato ? estadoStock(n) : null;
  const fill = row.querySelector(".stock-fill");
  const badge = row.querySelector(".badge");
  row.querySelector(".stock-value").textContent = tieneDato ? String(n) : "—";
  fill.style.width = tieneDato ? `${Math.min(100, (n / STOCK_REFERENCIA) * 100)}%` : "0%";
  fill.dataset.state = est?.clave ?? "";
  badge.textContent = est?.texto ?? "Cargando";
  badge.dataset.state = est?.clave ?? "";
  return est;
}

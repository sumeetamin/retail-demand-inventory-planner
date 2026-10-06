const byId = (id) => document.getElementById(id);
const number = (value, digits = 1) => Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
const pct = (value) => `${(value * 100).toFixed(1)}%`;
const esc = (value) => String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
let report;

function zForService(service) {
  const points = [[90, 1.2816], [95, 1.6449], [97, 1.8808], [99, 2.3263]];
  for (let i = 1; i < points.length; i += 1) {
    if (service <= points[i][0]) {
      const [x0, y0] = points[i - 1], [x1, y1] = points[i];
      return y0 + (service - x0) * (y1 - y0) / (x1 - x0);
    }
  }
  return points.at(-1)[1];
}

function selectedProduct() {
  return report.products.find((product) => product.stock_code === byId("sku").value) || report.products[0];
}

function drawDemand(product) {
  const svg = byId("demand-chart"); const width = Math.max(svg.clientWidth || 520, 320); const height = 225;
  const values = product.weekly_history.map((x) => x.units); const next = product.next_7_day_forecast;
  const max = Math.max(1, ...values, ...next); const plot = { x: 38, y: 14, w: width - 52, h: height - 45 };
  let content = "";
  for (let i = 0; i <= 4; i += 1) {
    const y = plot.y + plot.h * i / 4; const label = max * (1 - i / 4);
    content += `<line class="grid-line" x1="${plot.x}" x2="${plot.x+plot.w}" y1="${y}" y2="${y}"/><text class="chart-label" x="3" y="${y+3}">${Math.round(label)}</text>`;
  }
  const all = [...values, ...next]; const slot = plot.w / all.length; const barWidth = Math.max(2, slot * .66);
  all.forEach((value, i) => {
    const barHeight = Math.max(0, value / max * plot.h); const x = plot.x + i * slot + (slot - barWidth) / 2; const y = plot.y + plot.h - barHeight;
    const isForecast = i >= values.length;
    const label = isForecast ? `forecast day ${i - values.length + 1}` : product.weekly_history[i].week;
    content += `<rect class="${isForecast ? "forecast-bar" : "history-bar"}" x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="2"><title>${esc(label)}: ${number(value)} units</title></rect>`;
  });
  content += `<text class="chart-label" x="${plot.x}" y="${height-7}">12 COMPLETE HISTORY WEEKS</text><text class="chart-label" text-anchor="end" x="${width-8}" y="${height-7}">NEXT 7 DAYS →</text>`;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`); svg.innerHTML = content;
}

function renderInventory() {
  const product = selectedProduct();
  const lead = Number(byId("lead-time").value); const service = Number(byId("service-target").value);
  const mean = product.mean_daily_demand; const sigma = product.std_daily_demand;
  const expectedLeadDemand = mean * lead; const safetyStock = zForService(service) * sigma * Math.sqrt(lead);
  const reorderPoint = Math.ceil(expectedLeadDemand + safetyStock);
  const onHandControl = byId("on-hand"); onHandControl.max = String(Math.max(500, Math.ceil(reorderPoint * 2)));
  if (Number(onHandControl.value) > Number(onHandControl.max)) onHandControl.value = onHandControl.max;
  const onHand = Number(onHandControl.value); const order = Math.max(0, reorderPoint - onHand);
  byId("lead-time-out").textContent = `${lead} days`; byId("service-target-out").textContent = `${service}%`; byId("on-hand-out").textContent = `${onHand} units`;
  byId("inventory-metrics").innerHTML = [
    ["Average daily units", number(mean, 2), "Trailing 90 training days, including zero-sale days"],
    ["Safety stock", `${Math.ceil(safetyStock)} units`, `Normal approximation at ${service}% target`],
    ["Reorder point", `${reorderPoint} units`, `Expected lead-time demand + safety stock`],
    [order ? "Scenario order quantity" : "Reorder status", order ? `${order} units` : "Above trigger", order ? "Illustrative order-up-to-reorder-point quantity" : "On-hand exceeds this scenario's trigger"],
  ].map(([label, value, note]) => `<div class="inventory-card"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`).join("");
}

function renderProduct() {
  const product = selectedProduct();
  byId("sku-summary").innerHTML = `<strong>${esc(product.description)}</strong><br>SKU ${esc(product.stock_code)} · ${number(product.training_units, 0)} training-period units · next-seven-day forecast ${number(product.forecast_total_7d, 1)} units`;
  drawDemand(product); renderInventory();
}

function render() {
  const metrics = report.test[report.protocol.selected_model];
  byId("headline-metrics").innerHTML = [
    ["Historical sales rows", report.dataset.valid_positive_sale_rows.toLocaleString(), "after stated exclusions"],
    ["Selected products", report.dataset.selected_skus, "ranked before holdout"],
    ["Final test WAPE", pct(metrics.wape), report.protocol.selected_model.replaceAll("_", " ")],
    ["Final test MAE", `${number(metrics.mae_units_per_sku_day, 2)} units`, "per SKU-day"],
  ].map(([label, value, sub]) => `<div class="metric"><div class="metric-label">${esc(label)}</div><div class="metric-value">${esc(value)}</div><div class="metric-sub">${esc(sub)}</div></div>`).join("");
  byId("backtest-note").textContent = `${report.protocol.split}. Product set is fixed using only the pre-holdout period.`;
  byId("forecast-rows").innerHTML = Object.keys(report.validation).map((method) => {
    const v = report.validation[method], t = report.test[method];
    return `<tr class="${method === report.protocol.selected_model ? "selected-row" : ""}"><td>${esc(method.replaceAll("_", " "))}${method === report.protocol.selected_model ? " · selected" : ""}</td><td>${pct(v.wape)}</td><td>${pct(t.wape)}</td><td>${number(t.mae_units_per_sku_day, 2)}</td><td>${number(t.bias_units_per_sku_day, 2)}</td></tr>`;
  }).join("");
  const select = byId("sku");
  select.replaceChildren(...report.products.map((product) => {
    const option = document.createElement("option"); option.value = product.stock_code; option.textContent = `${product.stock_code} · ${product.description}`; return option;
  }));
  byId("limitations").innerHTML = report.limitations.map((item) => `<li>${esc(item)}</li>`).join("");
  ["sku", "lead-time", "service-target", "on-hand"].forEach((id) => byId(id).addEventListener("input", renderProduct));
  window.addEventListener("resize", () => drawDemand(selectedProduct()));
  renderProduct();
}

fetch("data/benchmark.json").then((response) => { if (!response.ok) throw new Error(`Benchmark report returned ${response.status}`); return response.json(); })
  .then((data) => { report = data; byId("load-state").hidden = true; byId("dashboard").hidden = false; render(); })
  .catch((error) => { byId("load-state").textContent = `Could not load the benchmark report: ${error.message}. Open this demo through the portfolio site or a local HTTP server.`; });


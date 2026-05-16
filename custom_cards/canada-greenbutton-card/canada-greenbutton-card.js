/*!
 * Canada GreenButton Lovelace Card
 * Renders Alectra TOU + Enbridge gas datasets from sensor `raw_data` attributes.
 */
(() => {
  const CHART_JS_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js";
  let chartLoader = null;

  function loadChartJs() {
    if (window.Chart) return Promise.resolve(window.Chart);
    if (chartLoader) return chartLoader;
    chartLoader = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = CHART_JS_URL;
      s.async = true;
      s.onload = () => resolve(window.Chart);
      s.onerror = () => reject(new Error("Failed to load Chart.js"));
      document.head.appendChild(s);
    });
    return chartLoader;
  }

  const TOU_COLORS = {
    on: "#d9534f",
    mid: "#f0ad4e",
    off: "#5cb85c",
  };

  const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  const VIEWS = [
    "monthly_tou", "daily_tou", "heatmap", "yoy",
    "billing", "gas_usage", "gas_billing",
  ];

  class CanadaGreenButtonCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._chart = null;
      this._lastSig = "";
    }

    setConfig(config) {
      if (!config || !config.entity) {
        throw new Error("`entity` required");
      }
      this._config = {
        view: "monthly_tou",
        title: "",
        year_filter: "all",
        ...config,
      };
      if (!VIEWS.includes(this._config.view)) {
        throw new Error(`Unknown view '${this._config.view}'. Valid: ${VIEWS.join(", ")}`);
      }
      this._render();
    }

    set hass(hass) {
      this._hass = hass;
      this._render();
    }

    getCardSize() { return 6; }

    static getConfigElement() { return document.createElement("canada-greenbutton-card-editor"); }
    static getStubConfig() {
      return { entity: "", view: "monthly_tou" };
    }

    _state() {
      if (!this._hass || !this._config) return null;
      return this._hass.states[this._config.entity] || null;
    }

    _raw() {
      const s = this._state();
      return s && s.attributes && s.attributes.raw_data ? s.attributes.raw_data : null;
    }

    _render() {
      const raw = this._raw();
      const sig = JSON.stringify({ v: this._config && this._config.view, e: this._config && this._config.entity, h: raw ? JSON.stringify(raw).length : 0 });
      if (sig === this._lastSig && this.shadowRoot.firstChild) return;
      this._lastSig = sig;

      if (!this._config) return;
      this.shadowRoot.innerHTML = this._shellHtml();
      const body = this.shadowRoot.getElementById("body");
      if (!raw) {
        body.innerHTML = `<div class="empty">No data on <code>${this._config.entity}</code>. Import an XML file via the <code>canada_greenbutton.import_xml</code> service.</div>`;
        return;
      }

      switch (this._config.view) {
        case "monthly_tou": return this._renderMonthlyTou(body, raw);
        case "daily_tou":   return this._renderDailyTou(body, raw);
        case "heatmap":     return this._renderHeatmap(body, raw);
        case "yoy":         return this._renderYoy(body, raw);
        case "billing":     return this._renderBilling(body, raw);
        case "gas_usage":   return this._renderGasUsage(body, raw);
        case "gas_billing": return this._renderGasBilling(body, raw);
      }
    }

    _shellHtml() {
      const title = this._config.title || this._defaultTitle();
      const showCsv = this._config.view === "monthly_tou" || this._config.view === "daily_tou";
      return `
<ha-card>
  <style>
    ha-card { padding: 12px; }
    .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
    .title { font-weight: 500; font-size: 1.05em; }
    .csv-btn { cursor: pointer; padding: 4px 10px; border-radius: 4px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
    .csv-btn:hover { background: var(--secondary-background-color); }
    .empty { padding: 20px; text-align: center; color: var(--secondary-text-color); }
    .chart-wrap { position: relative; height: 320px; }
    table.gb { width: 100%; border-collapse: collapse; font-size: 0.9em; }
    table.gb th, table.gb td { padding: 4px 8px; text-align: right; border-bottom: 1px solid var(--divider-color); }
    table.gb th:first-child, table.gb td:first-child { text-align: left; }
    table.gb th { background: var(--secondary-background-color); font-weight: 500; }
    .heatmap { display: grid; grid-template-columns: 40px repeat(24, 1fr); gap: 2px; font-size: 0.7em; }
    .heatmap .cell { aspect-ratio: 1; border-radius: 2px; }
    .heatmap .lbl { color: var(--secondary-text-color); text-align: right; padding-right: 4px; align-self: center; }
    .heatmap .h-lbl { text-align: center; color: var(--secondary-text-color); }
    .filter { display:inline-flex; gap:6px; margin-bottom:8px; }
    .filter button { padding:2px 8px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); cursor:pointer; border-radius:3px; }
    .filter button.active { background: var(--primary-color); color: var(--text-primary-color); }
    .delta-up { color: var(--error-color, #d9534f); }
    .delta-down { color: var(--success-color, #5cb85c); }
  </style>
  <div class="header">
    <div class="title">${title}</div>
    ${showCsv ? `<button class="csv-btn" id="csv">Export CSV</button>` : ""}
  </div>
  <div id="body"></div>
</ha-card>`;
    }

    _defaultTitle() {
      const map = {
        monthly_tou: "Monthly usage by TOU",
        daily_tou: "Daily usage by TOU",
        heatmap: "Hourly pattern heatmap",
        yoy: "Year-over-year usage",
        billing: "Billing history",
        gas_usage: "Gas usage & billing",
        gas_billing: "Gas billing breakdown",
      };
      return map[this._config.view] || "Canada GreenButton";
    }

    // --- Chart helpers ----------------------------------------------------
    async _drawChart(canvas, config) {
      const Chart = await loadChartJs();
      if (this._chart) { this._chart.destroy(); this._chart = null; }
      this._chart = new Chart(canvas.getContext("2d"), config);
    }

    _wireCsv(buildRows, filename) {
      const btn = this.shadowRoot.getElementById("csv");
      if (!btn) return;
      btn.addEventListener("click", () => {
        const rows = buildRows();
        const csv = rows.map(r => r.map(c => {
          const s = String(c ?? "");
          return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
        }).join(",")).join("\n");
        const blob = new Blob([csv], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = filename;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
      });
    }

    // --- Views ------------------------------------------------------------
    _renderMonthlyTou(body, raw) {
      const months = raw.monthly_tou || [];
      if (!months.length) { body.innerHTML = `<div class="empty">No hourly readings parsed.</div>`; return; }
      body.innerHTML = `<div class="chart-wrap"><canvas></canvas></div>`;
      const labels = months.map(m => m.label);
      this._drawChart(body.querySelector("canvas"), {
        type: "bar",
        data: {
          labels,
          datasets: [
            { label: "Off-peak", data: months.map(m => m.off_peak_kwh), backgroundColor: TOU_COLORS.off, stack: "kwh" },
            { label: "Mid-peak", data: months.map(m => m.mid_peak_kwh), backgroundColor: TOU_COLORS.mid, stack: "kwh" },
            { label: "On-peak", data: months.map(m => m.on_peak_kwh), backgroundColor: TOU_COLORS.on, stack: "kwh" },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: { x: { stacked: true }, y: { stacked: true, title: { display: true, text: "kWh" } } },
          plugins: { tooltip: { callbacks: { footer: items => {
            const total = items.reduce((a, b) => a + (b.parsed.y || 0), 0);
            return `Total: ${total.toFixed(1)} kWh`;
          }}}},
        },
      });
      this._wireCsv(
        () => [["Date","Total kWh","Off-peak kWh","Mid-peak kWh","On-peak kWh"],
               ...(raw.daily_summaries || []).map(d => [d.date_key, d.kwh.toFixed(3), d.off_peak_kwh.toFixed(3), d.mid_peak_kwh.toFixed(3), d.on_peak_kwh.toFixed(3)])],
        "alectra-daily-usage.csv"
      );
    }

    _renderDailyTou(body, raw) {
      const days = raw.daily_summaries || [];
      if (!days.length) { body.innerHTML = `<div class="empty">No daily data.</div>`; return; }
      // Month picker
      const months = Array.from(new Set(days.map(d => d.date_key.slice(0, 7)))).sort();
      const selected = this._selectedMonth || months[months.length - 1];
      this._selectedMonth = selected;
      const tabs = months.map(m => `<button data-m="${m}" class="${m === selected ? "active" : ""}">${m}</button>`).join("");
      body.innerHTML = `<div class="filter">${tabs}</div><div class="chart-wrap"><canvas></canvas></div>`;
      body.querySelectorAll(".filter button").forEach(btn => {
        btn.addEventListener("click", () => {
          this._selectedMonth = btn.dataset.m;
          this._lastSig = ""; this._render();
        });
      });
      const monthDays = days.filter(d => d.date_key.startsWith(selected));
      this._drawChart(body.querySelector("canvas"), {
        type: "bar",
        data: {
          labels: monthDays.map(d => d.date_key.slice(-2)),
          datasets: [
            { label: "Off-peak", data: monthDays.map(d => d.off_peak_kwh), backgroundColor: TOU_COLORS.off, stack: "kwh" },
            { label: "Mid-peak", data: monthDays.map(d => d.mid_peak_kwh), backgroundColor: TOU_COLORS.mid, stack: "kwh" },
            { label: "On-peak", data: monthDays.map(d => d.on_peak_kwh), backgroundColor: TOU_COLORS.on, stack: "kwh" },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: { x: { stacked: true, title: { display: true, text: `Day of ${selected}` } }, y: { stacked: true, title: { display: true, text: "kWh" } } },
        },
      });
      this._wireCsv(
        () => [["Date","Total kWh","Off-peak kWh","Mid-peak kWh","On-peak kWh"],
               ...monthDays.map(d => [d.date_key, d.kwh.toFixed(3), d.off_peak_kwh.toFixed(3), d.mid_peak_kwh.toFixed(3), d.on_peak_kwh.toFixed(3)])],
        `alectra-${selected}.csv`
      );
    }

    _renderHeatmap(body, raw) {
      const grid = raw.heatmap;
      if (!grid || !grid.cells || !grid.cells.length) {
        body.innerHTML = `<div class="empty">No hourly readings.</div>`; return;
      }
      const max = grid.max || 1;
      const dows = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
      let html = `<div class="heatmap"><div></div>`;
      for (let h = 0; h < 24; h++) html += `<div class="h-lbl">${h}</div>`;
      for (let d = 0; d < 7; d++) {
        html += `<div class="lbl">${dows[d]}</div>`;
        for (let h = 0; h < 24; h++) {
          const v = grid.cells[d][h] || 0;
          const intensity = v / max;
          // dark-slate → yellow gradient
          const r = Math.round(40 + intensity * 215);
          const g = Math.round(50 + intensity * 195);
          const b = Math.round(80 - intensity * 80);
          html += `<div class="cell" title="${dows[d]} ${h}:00 — ${v.toFixed(2)} kWh" style="background:rgb(${r},${g},${b})"></div>`;
        }
      }
      html += `</div>`;
      body.innerHTML = html;
    }

    _renderYoy(body, raw) {
      const months = raw.monthly_tou || [];
      if (!months.length) { body.innerHTML = `<div class="empty">No monthly data.</div>`; return; }
      const byYear = {};
      const years = new Set();
      months.forEach(m => {
        years.add(m.year);
        byYear[m.year] = byYear[m.year] || {};
        byYear[m.year][m.month] = m.total_kwh;
      });
      const sortedYears = Array.from(years).sort();
      if (sortedYears.length < 2) {
        body.innerHTML = `<div class="empty">Need ≥2 years of data for YoY.</div>`; return;
      }
      let html = `<table class="gb"><thead><tr><th>Month</th>`;
      sortedYears.forEach(y => { html += `<th>${y}</th>`; });
      html += `<th>Δ</th></tr></thead><tbody>`;
      for (let m = 1; m <= 12; m++) {
        html += `<tr><td>${MONTH_LABELS[m-1]}</td>`;
        sortedYears.forEach(y => {
          const v = byYear[y][m];
          html += `<td>${v != null ? v.toFixed(1) : ""}</td>`;
        });
        const cur = byYear[sortedYears[sortedYears.length-1]][m];
        const prev = byYear[sortedYears[sortedYears.length-2]][m];
        let delta = "";
        if (cur != null && prev != null) {
          const d = cur - prev;
          const cls = d > 0 ? "delta-up" : "delta-down";
          delta = `<span class="${cls}">${d > 0 ? "+" : ""}${d.toFixed(1)}</span>`;
        }
        html += `<td>${delta}</td></tr>`;
      }
      html += `</tbody></table>`;
      body.innerHTML = html;
    }

    _renderBilling(body, raw) {
      const periods = raw.billing_periods || [];
      if (!periods.length) { body.innerHTML = `<div class="empty">No billing periods.</div>`; return; }
      const isAlectra = "usage_kwh" in (periods[0] || {});
      let html = `<table class="gb"><thead><tr><th>Period</th>`;
      if (isAlectra) {
        html += `<th>kWh</th><th>Delivery</th><th>Regulatory</th><th>HST</th><th>OER</th><th>Total</th>`;
      } else {
        html += `<th>m³</th><th>Supply</th><th>Delivery</th><th>Carbon</th><th>HST</th><th>Total</th>`;
      }
      html += `</tr></thead><tbody>`;
      periods.forEach(p => {
        const label = `${p.start.slice(0,10)} → ${p.end.slice(0,10)}`;
        if (isAlectra) {
          html += `<tr><td>${label}</td><td>${p.usage_kwh.toFixed(1)}</td><td>${p.delivery_cad.toFixed(2)}</td><td>${p.regulatory_cad.toFixed(2)}</td><td>${p.hst_cad.toFixed(2)}</td><td>${p.ontario_rebate_cad.toFixed(2)}</td><td>${p.total_bill_cad.toFixed(2)}</td></tr>`;
        } else {
          html += `<tr><td>${label}</td><td>${p.usage_cubic_meters.toFixed(1)}</td><td>${p.gas_supply_cad.toFixed(2)}</td><td>${p.gas_delivery_cad.toFixed(2)}</td><td>${p.carbon_cad.toFixed(2)}</td><td>${p.hst_cad.toFixed(2)}</td><td>${p.total_bill_cad.toFixed(2)}</td></tr>`;
        }
      });
      html += `</tbody></table>`;
      body.innerHTML = html;
    }

    _renderGasUsage(body, raw) {
      const periods = raw.billing_periods || [];
      if (!periods.length) { body.innerHTML = `<div class="empty">No gas billing data.</div>`; return; }
      body.innerHTML = `<div class="chart-wrap"><canvas></canvas></div>`;
      const labels = periods.map(p => p.start.slice(0,7));
      const seasonColor = (label) => {
        const m = parseInt(label.slice(5,7), 10);
        if ([12,1,2].includes(m)) return "#3b82f6";
        if ([6,7,8].includes(m)) return "#22c55e";
        return "#f97316";
      };
      this._drawChart(body.querySelector("canvas"), {
        data: {
          labels,
          datasets: [
            { type: "bar", label: "m³", data: periods.map(p => p.usage_cubic_meters), backgroundColor: labels.map(seasonColor), yAxisID: "y" },
            { type: "line", label: "Bill (CAD)", data: periods.map(p => p.total_bill_cad), borderColor: "#111", yAxisID: "y1", tension: 0.2 },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: {
            y: { position: "left", title: { display: true, text: "m³" } },
            y1: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "CAD" } },
          },
        },
      });
    }

    _renderGasBilling(body, raw) {
      this._renderBilling(body, raw);
    }
  }

  class CanadaGreenButtonCardEditor extends HTMLElement {
    setConfig(config) { this._config = config; this._render(); }
    set hass(hass) { this._hass = hass; this._render(); }
    _render() {
      if (!this._config) return;
      this.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:8px; padding:8px;">
          <label>Entity <input id="ent" type="text" value="${this._config.entity || ""}" style="width:100%"></label>
          <label>View
            <select id="view">${VIEWS.map(v => `<option value="${v}" ${v===this._config.view?"selected":""}>${v}</option>`).join("")}</select>
          </label>
          <label>Title <input id="title" type="text" value="${this._config.title || ""}" style="width:100%"></label>
        </div>`;
      const fire = () => {
        const detail = { config: {
          ...this._config,
          entity: this.querySelector("#ent").value,
          view: this.querySelector("#view").value,
          title: this.querySelector("#title").value,
        }};
        this.dispatchEvent(new CustomEvent("config-changed", { detail, bubbles: true, composed: true }));
      };
      this.querySelector("#ent").addEventListener("change", fire);
      this.querySelector("#view").addEventListener("change", fire);
      this.querySelector("#title").addEventListener("change", fire);
    }
  }

  customElements.define("canada-greenbutton-card", CanadaGreenButtonCard);
  customElements.define("canada-greenbutton-card-editor", CanadaGreenButtonCardEditor);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "canada-greenbutton-card",
    name: "Canada GreenButton Card",
    description: "Visualize Alectra Electric (TOU) and Enbridge Gas GreenButton data.",
    preview: false,
  });
})();

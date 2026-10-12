// Foresight · Direction B — chart renderer for the design concept (fictional data).
// One grammar everywhere: observed = solid ink · forecast = ink line + band · scenario = dashed blue
// · checked plan = solid teal · buffer = dotted amber · today = vertical ink rule.
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const DAY = 86400000;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  const d = (s) => new Date(s + "T12:00:00Z");
  const fmtDate = (t) => { const x = new Date(t); return `${x.getUTCDate()} ${MONTHS[x.getUTCMonth()]}`; };
  const fmtDay = (t) => { const x = new Date(t); return ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"][x.getUTCDay()] + " " + fmtDate(t); };
  const money = (v) => (v < 0 ? "−£" : "£") + Math.round(Math.abs(v)).toLocaleString("en-GB");

  // Expand corner waypoints [["2026-10-12", 2184.5], ...] into one value per day (linear between corners).
  function daily(points) {
    const out = [];
    for (let i = 0; i < points.length - 1; i++) {
      const [a, va] = points[i], [b, vb] = points[i + 1];
      const ta = d(a).getTime(), tb = d(b).getTime();
      const n = Math.round((tb - ta) / DAY);
      for (let k = 0; k < n; k++) out.push([ta + k * DAY, va + (vb - va) * (k / n)]);
    }
    const last = points[points.length - 1];
    out.push([d(last[0]).getTime(), last[1]]);
    return out;
  }
  function shift(series, fromIso, amount) {
    const from = d(fromIso).getTime();
    return series.map(([t, v]) => [t, t >= from ? v - amount : v]);
  }
  function valueAt(series, t) {
    for (let i = 0; i < series.length - 1; i++) {
      if (t >= series[i][0] && t <= series[i + 1][0]) {
        const f = (t - series[i][0]) / (series[i + 1][0] - series[i][0] || 1);
        return series[i][1] + (series[i + 1][1] - series[i][1]) * f;
      }
    }
    return null;
  }

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  // spec: { start, end, yMin, yMax, yTicks, today, buffer, series:[{kind,data,band?,label,name}], markers:[{date,value,label,tone,align}], height, monthTicks }
  function draw(container, spec) {
    container.innerHTML = "";
    const W = 900, H = spec.height || 300, m = { l: 52, r: 16, t: 18, b: 30 };
    const t0 = d(spec.start).getTime(), t1 = d(spec.end).getTime();
    const x = (t) => m.l + ((t - t0) / (t1 - t0)) * (W - m.l - m.r);
    const y = (v) => m.t + (1 - (v - spec.yMin) / (spec.yMax - spec.yMin)) * (H - m.t - m.b);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": spec.ariaLabel || "Balance chart" });
    container.appendChild(svg);

    // Grid + y axis
    const axis = el("g", { class: "axis" }, svg);
    spec.yTicks.forEach((v) => {
      el("line", { class: "grid-line", x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), ...(v === 0 ? { stroke: "#C9CED6" } : {}) }, axis);
      const tx = el("text", { x: m.l - 10, y: y(v) + 4, "text-anchor": "end" }, axis);
      tx.textContent = v === 0 ? "£0" : (v >= 1000 ? `£${v / 1000}k` : `£${v}`);
    });
    (spec.xTicks || []).forEach((iso) => {
      const tx = el("text", { x: x(d(iso).getTime()), y: H - 8, "text-anchor": "middle" }, axis);
      tx.textContent = fmtDate(d(iso).getTime());
    });

    // Buffer
    if (spec.buffer != null) {
      el("line", { x1: m.l, x2: W - m.r, y1: y(spec.buffer), y2: y(spec.buffer), stroke: "var(--series-buffer)", "stroke-width": 1.5, "stroke-dasharray": "1 4", "stroke-linecap": "round" }, svg);
      const bl = el("text", { x: W - m.r, y: y(spec.buffer) - 6, "text-anchor": "end", class: "annot", fill: "var(--warning-text)" }, svg);
      bl.textContent = `Your buffer ${money(spec.buffer)}`;
    }

    // Future shading behind the forecast
    if (spec.today) {
      const tt = d(spec.today).getTime();
      el("rect", { x: x(tt), y: m.t, width: W - m.r - x(tt), height: H - m.t - m.b, fill: "rgba(21,29,49,0.018)" }, svg);
    }

    const path = (data) => data.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join("");

    spec.series.forEach((s) => {
      if (s.band) {
        const top = s.band.map(([t, , hi]) => [t, hi]);
        const bot = s.band.map(([t, lo]) => [t, lo]).reverse();
        el("path", { d: path(top) + bot.map(([t, v]) => `L${x(t).toFixed(1)},${y(v).toFixed(1)}`).join("") + "Z", fill: "var(--band-forecast)" }, svg);
      }
    });
    const styles = {
      history: { stroke: "var(--series-history)", "stroke-width": 2 },
      forecast: { stroke: "var(--series-forecast)", "stroke-width": 2 },
      ghost: { stroke: "#9AA1AE", "stroke-width": 1.5, "stroke-dasharray": "2 3" },
      scenario: { stroke: "var(--series-scenario)", "stroke-width": 2, "stroke-dasharray": "6 4" },
      scenarioAlt: { stroke: "var(--series-scenario)", "stroke-width": 1.5, "stroke-dasharray": "2 3", opacity: 0.55 },
      recommended: { stroke: "var(--series-recommended)", "stroke-width": 2 },
    };
    spec.series.forEach((s) => {
      el("path", { d: path(s.data), fill: "none", "stroke-linejoin": "round", "stroke-linecap": "round", ...styles[s.kind], "data-series": s.name || "" }, svg);
      if (s.label) {
        const last = s.data[s.data.length - 1];
        const lt = el("text", { x: x(last[0]) + 6, y: y(last[1]) + (s.labelDy || 4), class: "annot", fill: s.labelColor || "var(--text-muted)" }, svg);
        lt.textContent = s.label;
      }
    });

    // Today rule
    if (spec.today) {
      const tx = x(d(spec.today).getTime());
      el("line", { class: "today-rule", x1: tx, x2: tx, y1: m.t - 6, y2: H - m.b }, svg);
      const tl = el("text", { x: tx + 6, y: m.t + 2, class: "today-label" }, svg);
      tl.textContent = "TODAY · " + fmtDate(d(spec.today).getTime()).toUpperCase();
      const tl2 = el("text", { x: tx - 6, y: m.t + 2, class: "today-label", "text-anchor": "end", fill: "var(--text-faint)" }, svg);
      tl2.textContent = "OBSERVED";
      tl2.setAttribute("style", "fill: var(--text-faint)");
      const tl3 = el("text", { x: tx + 6, y: m.t + 15, class: "today-label" }, svg);
      tl3.textContent = "FORECAST →";
      tl3.setAttribute("style", "fill: var(--text-faint)");
    }

    // Markers
    (spec.markers || []).forEach((mk) => {
      const mx = x(d(mk.date).getTime()), my = y(mk.value);
      const color = { risk: "var(--negative)", good: "var(--positive)", neutral: "#9AA1AE", scenario: "var(--accent)" }[mk.tone] || "var(--accent)";
      const ink = { risk: "var(--negative)", good: "var(--positive-text)", neutral: "var(--text-faint)", scenario: "var(--accent-hover)" }[mk.tone] || "var(--accent-hover)";
      el("circle", { cx: mx, cy: my, r: 5.5, fill: "var(--surface)", stroke: color, "stroke-width": 2 }, svg);
      const anchor = mk.align || "start";
      const dx = anchor === "end" ? -10 : 10;
      const lt = el("text", { x: mx + dx, y: my + (mk.dy || 4), "text-anchor": anchor, class: "annot", fill: ink }, svg);
      lt.textContent = mk.label;
    });

    // Hover: crosshair + per-series readout
    const tip = document.createElement("div");
    tip.className = "tooltip";
    container.appendChild(tip);
    const cross = el("line", { x1: 0, x2: 0, y1: m.t, y2: H - m.b, stroke: "var(--text)", "stroke-width": 1, opacity: 0 }, svg);
    const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" }, svg);
    hit.addEventListener("mousemove", (e) => {
      const r = svg.getBoundingClientRect();
      const px = ((e.clientX - r.left) / r.width) * W;
      const t = t0 + ((px - m.l) / (W - m.l - m.r)) * (t1 - t0);
      const day = Math.round(t / DAY) * DAY + DAY / 2 - DAY / 2;
      cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("opacity", 0.25);
      const rows = spec.series.filter((s) => s.name).map((s) => {
        const v = valueAt(s.data, t);
        return v == null ? "" : `<div><span class="k">${s.name}</span> <b>${money(v)}</b></div>`;
      }).join("");
      tip.innerHTML = `<div class="k">${fmtDay(day)}</div>${rows}`;
      tip.style.left = (px / W) * r.width + "px";
      tip.style.top = (m.t / H) * r.height + 40 + "px";
      tip.classList.add("on");
    });
    hit.addEventListener("mouseleave", () => { tip.classList.remove("on"); cross.setAttribute("opacity", 0); });

    // Table view for screen readers and CVD/print
    const table = document.createElement("table");
    table.className = "sr-only";
    table.innerHTML = `<caption>${spec.ariaLabel || "Balance"}</caption><tr><th>Series</th><th>Lowest</th></tr>` +
      spec.series.filter((s) => s.name).map((s) => {
        const low = s.data.reduce((a, b) => (b[1] < a[1] ? b : a));
        return `<tr><td>${s.name}</td><td>${money(low[1])} on ${fmtDate(low[0])}</td></tr>`;
      }).join("");
    table.style.cssText = "position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)";
    container.appendChild(table);
  }

  window.ForesightCharts = { draw, daily, shift, valueAt, money, d };
})();

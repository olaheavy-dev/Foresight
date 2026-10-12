/* Foresight · Direction A — horizon chart (design concept, fictional data).
   Renders observed history (solid ink), forecast P50 with likely range (banded), optional ghost
   (previous forecast), optional hypothetical scenarios (dashed blue), the buffer threshold
   (dotted amber), dated risk markers and a crosshair tooltip. Values are design fixtures. */

(function () {
  const DAY = 86400000;
  const d = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10));
  const fmtDate = (t) =>
    new Date(t).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
  const fmtShort = (t) => new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
  const gbp = (v) => (v < 0 ? "−£" : "£") + Math.abs(Math.round(v)).toLocaleString("en-GB");

  // Expand [[date, value], ...] keyframes into a daily series by linear interpolation.
  function daily(keys) {
    const out = new Map();
    for (let i = 0; i < keys.length - 1; i++) {
      const [a, va] = keys[i], [b, vb] = keys[i + 1];
      const ta = d(a), tb = d(b), n = Math.round((tb - ta) / DAY);
      for (let k = 0; k < n; k++) out.set(ta + k * DAY, va + ((vb - va) * k) / n);
    }
    const [last, vl] = keys[keys.length - 1];
    out.set(d(last), vl);
    return out;
  }

  function render(el, cfg) {
    const W = cfg.width || 1000, H = cfg.height || 320;
    const m = { t: 22, r: 64, b: 30, l: 6 };
    const t0 = d(cfg.start), t1 = d(cfg.end), today = d(cfg.today);
    const x = (t) => m.l + ((t - t0) / (t1 - t0)) * (W - m.l - m.r);
    const y = (v) => m.t + (1 - (v - cfg.yMin) / (cfg.yMax - cfg.yMin)) * (H - m.t - m.b);

    const hist = daily(cfg.history);
    const p50 = daily(cfg.forecast);
    const ghost = cfg.ghost ? daily(cfg.ghost) : null;
    const scen = (cfg.scenarios || []).map((s) => ({ ...s, series: daily(s.points) }));
    const halfWidth = (t) => {
      const days = Math.max(0, (t - today) / DAY);
      return cfg.band(days, t);
    };

    const path = (series, from, to) => {
      let s = "";
      for (const [t, v] of series) if (t >= from && t <= to) s += (s ? "L" : "M") + x(t).toFixed(1) + "," + y(v).toFixed(1);
      return s;
    };
    let band = "", bandBack = "";
    const fts = [...p50.keys()].sort((a, b) => a - b);
    fts.forEach((t, i) => {
      const v = p50.get(t), hw = halfWidth(t);
      band += (i ? "L" : "M") + x(t).toFixed(1) + "," + y(v + hw).toFixed(1);
    });
    [...fts].reverse().forEach((t) => {
      const v = p50.get(t), hw = halfWidth(t);
      bandBack += "L" + x(t).toFixed(1) + "," + y(v - hw).toFixed(1);
    });

    const ticksY = cfg.ticksY.map((v) =>
      `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--grid)" stroke-width="1"/>
       <text x="${W - m.r + 10}" y="${y(v) + 4}" font-size="11" fill="var(--text-faint)">${gbp(v)}</text>`).join("");
    const ticksX = cfg.ticksX.map((s) => `<text x="${x(d(s))}" y="${H - 8}" font-size="11" text-anchor="middle" fill="var(--text-faint)">${fmtShort(d(s))}</text>`).join("");

    const buf = cfg.buffer != null ? `
      <line x1="${m.l}" x2="${W - m.r}" y1="${y(cfg.buffer)}" y2="${y(cfg.buffer)}" stroke="var(--warning)" stroke-width="1.5" stroke-dasharray="1 4" stroke-linecap="round"/>
      <text x="${W - m.r + 10}" y="${y(cfg.buffer) + 4}" font-size="11" font-weight="600" fill="var(--warning-text)">Buffer</text>` : "";
    const zero = cfg.yMin < 0 ? `<line x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}" stroke="var(--border-strong)" stroke-width="1"/>` : "";

    const todayX = x(today);
    const todayRule = `
      <rect x="${todayX}" y="${m.t - 14}" width="${W - m.r - todayX}" height="${H - m.t - m.b + 14}" fill="url(#fc-wash)"/>
      <line x1="${todayX}" x2="${todayX}" y1="${m.t - 14}" y2="${H - m.b}" stroke="var(--text)" stroke-width="1"/>
      <text x="${todayX - 8}" y="${m.t - 4}" font-size="11" text-anchor="end" fill="var(--text-muted)">Observed</text>
      <text x="${todayX + 8}" y="${m.t - 4}" font-size="11" font-weight="600" fill="var(--text)">Today · ${fmtShort(today)} → Forecast</text>`;

    const scenarioPaths = scen.map((s) => `<path d="${path(s.series, d(s.from || cfg.today), t1)}" fill="none" stroke="var(--series-scenario)" stroke-width="2" stroke-dasharray="${s.dash || "6 4"}" stroke-linecap="round" stroke-linejoin="round"/>`).join("");

    const markers = (cfg.markers || []).map((mk) => {
      const tx = x(d(mk.date)), ty = y(mk.value);
      const color = mk.tone === "scenario" ? "var(--series-scenario)" : mk.value < 0 ? "var(--negative)" : "var(--warning)";
      const anchor = mk.align || "middle";
      const dx = anchor === "end" ? -12 : anchor === "start" ? 12 : 0;
      const ly = mk.labelAbove ? ty - 30 : ty + 28;
      return `<circle cx="${tx}" cy="${ty}" r="5.5" fill="var(--surface)" stroke="${color}" stroke-width="2.5"/>
        <text x="${tx + dx}" y="${ly}" font-size="12" font-weight="600" text-anchor="${anchor}" fill="var(--text)">${mk.label}</text>
        <text x="${tx + dx}" y="${ly + 15}" font-size="11" text-anchor="${anchor}" fill="var(--text-muted)">${mk.sub}</text>`;
    }).join("");

    const labels = (cfg.lineLabels || []).map((l) => `<text x="${x(d(l.date)) + (l.dx || 0)}" y="${y(l.value) + (l.dy || 0)}" font-size="11" font-weight="${l.weight || 500}" text-anchor="${l.anchor || "start"}" fill="${l.color || "var(--text-muted)"}">${l.text}</text>`).join("");

    el.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${cfg.aria}">
        <defs>
          <linearGradient id="fc-wash" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stop-color="#151D31" stop-opacity="0.025"/>
            <stop offset="1" stop-color="#151D31" stop-opacity="0.0"/>
          </linearGradient>
        </defs>
        ${ticksY}${zero}${todayRule}
        <path d="${band}${bandBack}Z" fill="var(--band-forecast)"/>
        ${ghost ? `<path d="${path(ghost, today, t1)}" fill="none" stroke="var(--series-ghost)" stroke-width="1.5" stroke-dasharray="4 4"/>` : ""}
        ${buf}
        <path d="${path(hist, t0, today)}" fill="none" stroke="var(--series-history)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
        <path d="${path(p50, today, t1)}" fill="none" stroke="var(--series-forecast)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
        ${scenarioPaths}
        ${labels}
        ${markers}
        ${ticksX}
        <line class="xh" x1="0" x2="0" y1="${m.t - 14}" y2="${H - m.b}" stroke="var(--text-faint)" stroke-width="1" opacity="0"/>
        <circle class="xd" r="4" fill="var(--text)" opacity="0"/>
        <rect class="hit" x="${m.l}" y="0" width="${W - m.l - m.r}" height="${H}" fill="transparent"/>
      </svg>
      <div class="tip" role="status" aria-live="polite"></div>`;

    // Crosshair + tooltip
    const svg = el.querySelector("svg"), tip = el.querySelector(".tip");
    const xh = svg.querySelector(".xh"), xd = svg.querySelector(".xd");
    svg.querySelector(".hit").addEventListener("mousemove", (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      const t = Math.round((t0 + ((px - m.l) / (W - m.l - m.r)) * (t1 - t0)) / DAY) * DAY;
      const isHist = t <= today && hist.has(t);
      const v = isHist ? hist.get(t) : p50.get(t);
      if (v == null) return;
      xh.setAttribute("x1", x(t)); xh.setAttribute("x2", x(t)); xh.setAttribute("opacity", 1);
      xd.setAttribute("cx", x(t)); xd.setAttribute("cy", y(v)); xd.setAttribute("opacity", 1);
      let html = `<div><b>${fmtDate(t)}</b></div>`;
      if (isHist) html += `<div class="row"><span class="k">Observed balance</span><b>${gbp(v)}</b></div>`;
      else {
        const hw = halfWidth(t);
        html += `<div class="row"><span class="k">Forecast (middle)</span><b>${gbp(v)}</b></div>
                 <div class="row"><span class="k">Likely range</span><span>${gbp(v - hw)} – ${gbp(v + hw)}</span></div>`;
        if (ghost && ghost.has(t)) html += `<div class="row"><span class="k">${cfg.ghostLabel}</span><span>${gbp(ghost.get(t))}</span></div>`;
        scen.forEach((s) => { if (s.series.has(t)) html += `<div class="row"><span class="k">${s.label}</span><span>${gbp(s.series.get(t))}</span></div>`; });
      }
      tip.innerHTML = html;
      const left = (x(t) / W) * r.width;
      tip.style.left = Math.min(left + 14, r.width - 200) + "px";
      tip.style.top = "36px";
      tip.style.opacity = 1;
    });
    svg.querySelector(".hit").addEventListener("mouseleave", () => {
      tip.style.opacity = 0; xh.setAttribute("opacity", 0); xd.setAttribute("opacity", 0);
    });

    // Position event-rail pins against the same x scale
    if (cfg.rail) {
      cfg.rail.querySelectorAll(".pin").forEach((p) => {
        p.style.left = (x(d(p.dataset.date)) / W) * 100 + "%";
      });
    }
  }

  window.ForesightChart = { render };
})();

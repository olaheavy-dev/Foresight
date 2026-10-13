/* Foresight prototype — chart renderer (vanilla SVG).
   Encodes the data grammar from docs/00-DECISION-REGISTER.md §9:
   history = solid ink · forecast = accent line + P10–P90 band + today rule ·
   simulated = dashed burnt orange · buffer = dotted caution rule.
   All series are illustrative design fixtures for persona P1 (fictional). */
(function () {
  const DAY = 86400000;
  const d = (s) => new Date(s + "T00:00:00Z").getTime();
  const fmtDate = (t, opts) => new Date(t).toLocaleDateString("en-GB", Object.assign({ day: "numeric", month: "short", timeZone: "UTC" }, opts || {}));

  function gbp(v, compact) {
    const sign = v < 0 ? "−" : "";
    const a = Math.abs(v);
    if (compact) {
      if (a >= 1000) return sign + "£" + (a / 1000).toFixed(a % 1000 === 0 ? 0 : 1) + "k";
      return sign + "£" + Math.round(a);
    }
    return sign + "£" + Math.round(a).toLocaleString("en-GB");
  }

  // Interpolate keyframes [[date, value], ...] to daily points between start..end
  function daily(keys, start, end) {
    const k = keys.map(([s, v]) => [d(s), v]);
    const out = [];
    for (let t = d(start); t <= d(end); t += DAY) {
      let i = 0;
      while (i < k.length - 1 && k[i + 1][0] < t) i++;
      let v;
      if (t <= k[0][0]) v = k[0][1];
      else if (i >= k.length - 1) v = k[k.length - 1][1];
      else {
        const [t0, v0] = k[i], [t1, v1] = k[i + 1];
        v = v0 + (v1 - v0) * ((t - t0) / (t1 - t0));
      }
      out.push([t, v]);
    }
    return out;
  }

  // ---- Canonical P1 fixtures (Amara Nwosu, one Monzo account) — docs/00 §10a rev 3 ----
  const P1 = {
    historyStart: "2026-09-12",
    today: "2026-10-12",
    end: "2027-01-31",
    buffer: 300,
    history: [
      ["2026-08-13", 1650], ["2026-08-20", 1210], ["2026-08-27", 560], ["2026-08-28", 3500], ["2026-08-29", 3250],
      ["2026-09-01", 1790], ["2026-09-05", 1700], ["2026-09-08", 1620],
      ["2026-09-12", 1480], ["2026-09-15", 1260], ["2026-09-18", 1120], ["2026-09-20", 1040], ["2026-09-22", 960],
      ["2026-09-25", 780], ["2026-09-27", 630], ["2026-09-28", 3570], ["2026-09-29", 3320], ["2026-09-30", 3275],
      ["2026-10-01", 1880], ["2026-10-05", 1800], ["2026-10-08", 1740], ["2026-10-09", 1330], ["2026-10-12", 1284.5]
    ],
    p50: [
      ["2026-10-12", 1284.5], ["2026-10-14", 1200], ["2026-10-15", 1038], ["2026-10-19", 860], ["2026-10-20", 770],
      ["2026-10-22", 640], ["2026-10-25", 420], ["2026-10-27", 242], ["2026-10-28", 3182], ["2026-10-29", 2932],
      ["2026-11-01", 2860], ["2026-11-02", 1465], ["2026-11-05", 1380], ["2026-11-08", 1290], ["2026-11-14", 1150],
      ["2026-11-16", 988], ["2026-11-20", 850], ["2026-11-22", 760], ["2026-11-26", 572], ["2026-11-27", 3512],
      ["2026-11-29", 3262], ["2026-12-01", 1820], ["2026-12-05", 1740], ["2026-12-08", 1660], ["2026-12-14", 1500],
      ["2026-12-15", 1338], ["2026-12-17", 1050], ["2026-12-18", 3990], ["2026-12-20", 3860], ["2026-12-22", 3770],
      ["2026-12-29", 3330], ["2027-01-01", 1880], ["2027-01-05", 1780], ["2027-01-08", 1690], ["2027-01-14", 1540],
      ["2027-01-15", 1360], ["2027-01-20", 1180], ["2027-01-22", 1090], ["2027-01-27", 900], ["2027-01-28", 3840],
      ["2027-01-29", 3590], ["2027-01-31", 3520]
    ],
    // P10–P90 half-width grows with √days; anchored so 27 Oct = £96 / £388
    band(t) {
      const n = Math.max(0, (t - d(this.today)) / DAY);
      const hw = 37.7 * Math.sqrt(n);
      return [hw, hw];
    }
  };


  // ---- Side-account fixture (fictional "Sam Patel", one Revolut account, no regular income) — docs/00 §6a ----
  // Only regular inflows are projected: own-name top-ups (1st & 15th, £150) and T. Okafor (£200 on the 20th, unconfirmed).
  // One-off PayPal credits are in history only.
  const SIDE = {
    historyStart: "2026-09-12",
    today: "2026-10-12",
    end: "2026-12-31",
    buffer: 100,
    history: [
      ["2026-09-12", 180], ["2026-09-14", 144], ["2026-09-15", 276], ["2026-09-19", 204], ["2026-09-20", 386],
      ["2026-09-30", 206], ["2026-10-01", 338], ["2026-10-04", 284], ["2026-10-05", 351], ["2026-10-12", 212.4]
    ],
    p50: [
      ["2026-10-12", 212.4], ["2026-10-14", 176], ["2026-10-15", 308], ["2026-10-19", 236], ["2026-10-20", 418],
      ["2026-10-31", 220], ["2026-11-01", 352], ["2026-11-14", 118], ["2026-11-15", 250], ["2026-11-19", 178],
      ["2026-11-20", 360], ["2026-11-30", 180], ["2026-12-01", 312], ["2026-12-14", 78], ["2026-12-15", 210],
      ["2026-12-19", 138], ["2026-12-20", 320], ["2026-12-31", 122]
    ],
    band(t) {
      const n = Math.max(0, (t - d(this.today)) / DAY);
      const hw = 14 * Math.sqrt(n);
      return [hw, hw];
    }
  };
  const FIXTURES = { p1: P1, side: SIDE };

  // Scenario deltas on the baseline, same seed (difference attributable only to the scenario)
  const PLAN_PER_DAY = 116.39 * 12 / 365.25;
  const SCENARIOS = {
    trip: { label: "With £640 flights", cls: "l-sim", delta: (t) => (t >= d("2026-12-01") ? -640 : 0) },
    plan: { label: "Flights + checked plan", cls: "l-plan", delta: (t) => SCENARIOS.trip.delta(t) + PLAN_PER_DAY * Math.max(0, (t - d("2026-11-27")) / DAY) },
    delay: { label: "Salary a week late", cls: "l-sim", delta: (t) => (t >= d("2026-10-28") && t < d("2026-11-04") ? -2940 : 0) },
    rent: { label: "Rent +£100 from Jan", cls: "l-sim", delta: (t) => (t >= d("2027-01-01") ? -100 : 0) }
  };

  // Escape text from the page's data-chart attribute before it is placed in SVG markup.
  const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  function render(el) {
    const cfg = JSON.parse(el.dataset.chart || "{}");
    const F = FIXTURES[cfg.fixture || "p1"];
    const showHistory = cfg.history !== false;
    const start = showHistory ? (cfg.start || F.historyStart) : F.today;
    const end = cfg.end || F.end;
    const H = cfg.height || 300;
    const W = Math.max(320, el.clientWidth);
    const compact = W < 560;
    const m = { t: 28, r: compact ? 12 : 24, b: 28, l: compact ? 44 : 56 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;

    const hist = showHistory ? daily(F.history, start, F.today) : [];
    const base = daily(F.p50, F.today, end);
    const sims = (cfg.sims || []).map((k) => ({ key: k, ...SCENARIOS[k], pts: base.map(([t, v]) => [t, v + SCENARIOS[k].delta(t)]) }));

    let ymin = cfg.ymin != null ? cfg.ymin : 0, ymax = cfg.ymax || (F === P1 ? 4500 : 600);
    sims.forEach((s) => s.pts.forEach(([, v]) => { if (v < ymin) ymin = Math.floor(v / 500) * 500; }));
    const x = (t) => m.l + ((t - d(start)) / (d(end) - d(start))) * iw;
    const y = (v) => m.t + (1 - (v - ymin) / (ymax - ymin)) * ih;
    const path = (pts) => pts.map(([t, v], i) => (i ? "L" : "M") + x(t).toFixed(1) + "," + y(v).toFixed(1)).join("");

    let s = `<svg width="${W}" height="${H}" role="img" aria-label="${el.getAttribute("aria-label") || "Cash flow forecast"}">`;
    // grid + y ticks
    const step = [250, 500, 1000, 2000].find((q) => (ymax - ymin) / q <= 7) || 2000;
    s += `<g class="axis">`;
    for (let v = Math.ceil(ymin / step) * step; v <= ymax; v += step) {
      s += `<line class="gridline" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/>`;
      s += `<text class="tick" x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${v === 0 ? "£0" : gbp(v, true)}</text>`;
    }
    // x ticks at month starts
    const sd = new Date(d(start));
    let mt = Date.UTC(sd.getUTCFullYear(), sd.getUTCMonth() + 1, 1);
    while (mt <= d(end)) {
      s += `<line class="gridline" x1="${x(mt)}" x2="${x(mt)}" y1="${m.t}" y2="${H - m.b}" opacity=".6"/>`;
      s += `<text class="tick" x="${x(mt) + 4}" y="${H - m.b + 16}">${new Date(mt).toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" })}${new Date(mt).getUTCMonth() === 0 ? " ’" + String(new Date(mt).getUTCFullYear()).slice(2) : ""}</text>`;
      const nd = new Date(mt); mt = Date.UTC(nd.getUTCFullYear(), nd.getUTCMonth() + 1, 1);
    }
    s += `</g>`;
    if (ymin < 0) s += `<line class="zero" x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}"/>`;
    s += `<line class="baseline" x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}"/>`;

    // forecast band
    const up = base.map(([t, v]) => [t, v + F.band(t)[1]]);
    const lo = base.map(([t, v]) => [t, v - F.band(t)[0]]).reverse();
    s += `<path class="band" d="${path(up)}${path(lo).replace("M", "L")}Z"/>`;

    // buffer threshold
    s += `<line class="buffer" x1="${m.l}" x2="${W - m.r}" y1="${y(F.buffer)}" y2="${y(F.buffer)}"/>`;
    s += cfg.bufferLabelLeft
      ? `<text class="buffer-label" x="${m.l + 6}" y="${y(F.buffer) + (cfg.bufferLabelBelow ? 15 : -6)}">Your buffer ${gbp(F.buffer)}</text>`
      : `<text class="buffer-label" x="${W - m.r}" y="${y(F.buffer) - 6}" text-anchor="end">Your buffer ${gbp(F.buffer)}</text>`;

    // today rule
    const tx = x(d(F.today));
    if (showHistory) {
      s += `<line class="today" x1="${tx}" x2="${tx}" y1="${m.t - 14}" y2="${H - m.b}"/>`;
      s += `<text class="today-label" x="${tx + 6}" y="${m.t - 4}">Today · 12 Oct</text>`;
      s += `<text class="region-label" x="${tx - 6}" y="${m.t - 4}" text-anchor="end">${compact ? "History" : esc(cfg.historyLabel || "History · 30 days")}</text>`;
    }
    // bracket: [start, end, label] drawn along the top, e.g. the 41-day January
    if (cfg.bracket) {
      const [b0, b1, bl] = cfg.bracket, bx0 = x(d(b0)), bx1 = x(d(b1)), by = m.t + 6;
      s += `<path d="M${bx0},${by + 6}V${by}H${bx1}V${by + 6}" fill="none" stroke="var(--ink-2)" stroke-width="1"/>`;
      s += `<text class="annot-sub" x="${(bx0 + bx1) / 2}" y="${by - 4}" text-anchor="middle">${esc(bl)}</text>`;
    }
    // events
    (cfg.events || []).forEach((e) => {
      const ex = x(d(e[0]));
      s += `<line class="event-tick" x1="${ex}" x2="${ex}" y1="${H - m.b}" y2="${H - m.b + 5}"/>`;
    });

    if (showHistory) s += `<path class="l-history" d="${path(hist)}"/>`;
    s += `<path class="l-forecast" d="${path(base)}"/>`;
    sims.forEach((sim) => { s += `<path class="${sim.cls}" d="${path(sim.pts)}"/>`; });

    // annotations: [date, "base"|scenarioKey, label, sub, anchor]
    (cfg.annotate || []).forEach(([ds, which, label, sub, anchor]) => {
      const t = d(ds);
      const series = which === "base" ? base : sims.find((q) => q.key === which).pts;
      const pt = series.find((p) => p[0] === t) || series[0];
      const ax = x(t), ay = y(pt[1]);
      const col = which === "base" ? "var(--series-forecast)" : "var(--series-simulated)";
      const left = (anchor || "").includes("left");
      const above = (anchor || "").includes("above");
      const dy1 = above ? -50 : 18, dy2 = above ? -36 : 33;
      s += `<circle class="annot-dot" cx="${ax}" cy="${ay}" r="4.5" fill="${col}"/>`;
      if (!compact || cfg.annotateCompact) {
        s += `<text class="annot" x="${ax + (left ? -12 : 14)}" y="${ay + dy1}" text-anchor="${left ? "end" : "start"}">${esc(label)}</text>`;
        if (sub) s += `<text class="annot-sub" x="${ax + (left ? -12 : 14)}" y="${ay + dy2}" text-anchor="${left ? "end" : "start"}">${esc(sub)}</text>`;
      }
    });

    s += `<line class="crosshair" x1="0" x2="0" y1="${m.t}" y2="${H - m.b}" visibility="hidden"/>`;
    s += `<rect class="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}"/>`;
    s += `</svg><div class="tooltip" role="status" aria-live="off"></div>`;
    el.innerHTML = s;

    // hover layer
    const svg = el.querySelector("svg"), hit = el.querySelector(".hit"), cross = el.querySelector(".crosshair"), tip = el.querySelector(".tooltip");
    const all = hist.concat(base.slice(1));
    function move(evt) {
      const r = svg.getBoundingClientRect();
      const cx = (evt.touches ? evt.touches[0].clientX : evt.clientX) - r.left;
      const t = d(start) + Math.round(((cx - m.l) / iw) * ((d(end) - d(start)) / DAY)) * DAY;
      const p = all.find((q) => q[0] === t);
      if (!p) return;
      const px = x(t);
      cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
      const isF = t > d(F.today);
      let rows = isF
        ? `<div class="tt-row"><span><svg width="14" height="4"><line x1="0" x2="14" y1="2" y2="2" stroke="var(--series-forecast)" stroke-width="2"/></svg>Forecast P50</span><b>${gbp(p[1])}</b></div>
           <div class="tt-row"><span>P10–P90</span><span>${gbp(p[1] - F.band(t)[0], true)} – ${gbp(p[1] + F.band(t)[1], true)}</span></div>`
        : `<div class="tt-row"><span><svg width="14" height="4"><line x1="0" x2="14" y1="2" y2="2" stroke="var(--series-history)" stroke-width="2"/></svg>Balance</span><b>${gbp(p[1])}</b></div>`;
      sims.forEach((sim) => {
        const sp = sim.pts.find((q) => q[0] === t);
        if (sp && isF) rows += `<div class="tt-row"><span><svg width="14" height="4"><line x1="0" x2="14" y1="2" y2="2" stroke="var(--series-simulated)" stroke-width="2" stroke-dasharray="${sim.cls === "l-plan" ? "1.5 3" : "4 2"}"/></svg>${sim.label}</span><b>${gbp(sp[1])}</b></div>`;
      });
      tip.innerHTML = `<div class="tt-date">${fmtDate(t, { weekday: "short", year: "numeric" })}${isF ? " · forecast" : ""}</div>${rows}`;
      const tw = tip.offsetWidth;
      tip.style.left = Math.min(Math.max(px + 12, 0), W - tw) + (px + 12 + tw > W ? -tw - 24 : 0) + "px";
      tip.style.top = m.t + "px";
      tip.classList.add("on");
    }
    function leave() { cross.setAttribute("visibility", "hidden"); tip.classList.remove("on"); }
    hit.addEventListener("mousemove", move);
    hit.addEventListener("touchmove", move, { passive: true });
    hit.addEventListener("mouseleave", leave);
  }

  function renderAll() { document.querySelectorAll("[data-chart]").forEach(render); }
  let rz;
  window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(renderAll, 120); });
  document.addEventListener("DOMContentLoaded", renderAll);
  window.ForesightCharts = { renderAll, render, gbp };
})();

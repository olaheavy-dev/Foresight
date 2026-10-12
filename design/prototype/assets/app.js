/* Foresight prototype — shell, theme, tabs, Evidence drawer.
   Static design artifact. Every figure below is an illustrative fixture for fictional persona P1. */
(function () {
  const PAGES = [
    { href: "index.html", key: "briefing", label: "Briefing", count: "2" },
    { href: "ask.html", key: "ask", label: "Ask" },
    { href: "lab.html", key: "lab", label: "Decision Lab" },
    { href: "ledger.html", key: "ledger", label: "Ledger" }
  ];
  const DESIGN = [
    { href: "onboarding.html", key: "onboarding", label: "Onboarding" },
    { href: "household.html", key: "household", label: "Household (P3)" },
    { href: "india.html", key: "india", label: "India (P4)" },
    { href: "components.html", key: "components", label: "Design system" },
    { href: "states.html", key: "states", label: "States" }
  ];

  const ICON = {
    check: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.2l2.2 2.2 4.8-5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    cross: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    loop: '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M9.5 4.5A3.6 3.6 0 0 0 2.6 5M2.5 7.5A3.6 3.6 0 0 0 9.4 7" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><path d="M9.8 2.4v2.3H7.5M2.2 9.6V7.3h2.3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    dot: '<svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="3" fill="currentColor"/></svg>'
  };
  window.FS_ICON = ICON;

  // ---------- Evidence registry (what the drawer shows for each clickable figure) ----------
  const ENGINE = "finance_core 0.4.0";
  const RUN = "run_01JAF7Q2M8K4";
  const EV = {
    bal_now: {
      kind: "Balance anchor · declared", id: "bal_01JAF0Z3T9XH", title: "Balance today", figure: "£1,284.50",
      what: "Monzo CSV exports don’t include a balance, so you told us this figure when you imported. Every other balance is rebuilt from it plus the transactions after it.",
      inputs: [["Account", "Monzo current account (acct_01JA9W…)"], ["As of", "12 Oct 2026, entered by you"], ["Source", "Gap question at “Check what we found”"], ["Provenance", "declared"], ["Staleness", "0 days, fresh. We’ll ask again if it drifts."]],
      formula: "balance(t) = anchor(12 Oct) + Σ transactions after 12 Oct"
    },
    fc_low: {
      kind: "Forecast", id: "calc_01JAF7R1B3VP", title: "Expected low before payday", figure: "£242 on 27 Oct",
      what: "Median (P50) of 500 simulated daily-balance paths on the day before your salary is expected.",
      inputs: [["Forecast", "fc_01JAF7R0X6NN · baseline · to 31 Jan"], ["Range", "P10 £96 to P90 £388"], ["Known flows", "Council tax £162 (15 Oct), energy £78 (20 Oct), water £42 (22 Oct), subscriptions"], ["Excluded", "Car insurance £410 (9 Oct) is a one-off, kept out of the everyday baseline"], ["Discretionary", "Block bootstrap of the last 90 days’ non-recurring spend"], ["Seed", "hash(wsp_01JA9V…, data v9, baseline) = 0x4F1C"], ["Engine", ENGINE]],
      formula: "P50( balance_t , t = 27 Oct ) over N = 500 paths\nbalance_t = anchor + Σ known_flows(≤t) − Σ bootstrap_spend(≤t)",
      chips: [["finding", "fnd_01JAF3Q8ZK"], ["forecast", "fc_01JAF7R0X6NN"]]
    },
    fc_breach: {
      kind: "Forecast", id: "calc_01JAF7R1C9QA", title: "Chance of dipping below your buffer before payday", figure: "78%",
      what: "Share of the 500 simulated paths in which your balance falls under £300 at least once between today and 27 Oct.",
      inputs: [["Paths below £300", "390 of 500"], ["Buffer", "£300 (your setting)"], ["Window", "12 Oct → 27 Oct"], ["Forecast", "fc_01JAF7R0X6NN"], ["Engine", ENGINE]],
      formula: "P(min_{t ≤ 27 Oct} balance_t < 300) = 390 / 500 = 0.78",
      chips: [["forecast", "fc_01JAF7R0X6NN"]]
    },
    salary: {
      kind: "Income stream · confirmed", id: "inc_01JA9X5M2D7T", title: "Salary", figure: "£2,940 on Wed 28 Oct",
      what: "Detected from 12 monthly Bacs credits from the same payer and confirmed by you. Paid on the 28th, or the previous working day at weekends. December pay comes early.",
      inputs: [["Narration", "NORTHGATE SYSTEMS LTD · Bacs"], ["Occurrences", "12 (Oct 2025 to Sep 2026)"], ["Amount", "Median £2,940.00, no variance"], ["Next dates", "Wed 28 Oct · Fri 27 Nov · Fri 18 Dec · Thu 28 Jan"], ["Confidence", "0.98"]],
      formula: "amount = median(last 12 credits) = £2,940\nnext = 28th, or previous working day; Dec = early pay (observed Dec 2025)"
    },
    fnd_food: {
      kind: "Behavioural finding", id: "fnd_01JAF3Q8ZK", title: "Food delivery is up 41% on your three-month norm", figure: "+41%",
      what: "Detected by the Behaviour Analyst’s category-trend detector. Robust z-score 2.9 against the trailing three-month median, above the 2.0 threshold.",
      inputs: [["Last 30 days", "£286.40 · 23 orders"], ["3-month median", "£203.10"], ["Change", "+£83.30 (+41%)"], ["Merchants", "Deliveroo 11 · Uber Eats 8 · Just Eat 4"], ["Detector", "category_trend v2 · MAD z = 2.9"]],
      formula: "z = (286.40 − median) / (1.4826 · MAD) = 2.9 > 2.5",
      chips: [["calculation", "calc_01JAF3Q7MM"], ["transactions", "23 txns"]]
    },
    fnd_now: {
      kind: "Behavioural finding", id: "fnd_01JAF3QB4R", title: "NOW Entertainment overlaps Sky TV", figure: "£9.99/mo",
      what: "Both are recurring and in the same category (TV & streaming), and NOW sells channels that Sky TV already includes. Foresight can’t see what you watch. It only flags the overlap.",
      inputs: [["NOW Entertainment", "£9.99 · DEB · 7 months · billed 4th"], ["Sky TV", "£46.00 · DD · 12 months · billed 8th"], ["Detector", "detect_duplicate_subscriptions v1"], ["Your mark", "None yet"]],
      formula: "overlap = same category ∧ both active ∧ ≥ 3 cycles ∧ catalogue tag match"
    },
    fnd_ins: {
      kind: "One-off", id: "fnd_01JAF3QD1W", title: "Car insurance renewed", figure: "£410",
      what: "A single annual payment on 9 Oct. It explains most of why October is tight. It is kept out of the everyday baseline so it doesn’t inflate future months.",
      inputs: [["Narration", "ADMIRAL INSURANCE · card"], ["Date", "9 Oct 2026"], ["Treatment", "one-off · left out of the everyday baseline"]],
      formula: "one_off if amount > 3 × category median ∧ cadence ≈ 12 months"
    },
    fnd_jan: {
      kind: "Behavioural finding", id: "fnd_01JAF3QJ7N", title: "A long January", figure: "41 days",
      what: "December salary arrives early on Fri 18 Dec. The next one is Thu 28 Jan, so December’s pay has to last 41 days. It includes January rent and the last council-tax instalment.",
      inputs: [["December pay", "Fri 18 Dec 2026 (early, as in Dec 2025)"], ["January pay", "Thu 28 Jan 2027"], ["Gap", "41 days (usual: 28–31)"], ["Baseline January low", "£900 on 27 Jan"]],
      formula: "gap = 28 Jan − 18 Dec = 41 days"
    },
    rec_plan: {
      kind: "Recommendation · checked", id: "rec_01JAF8A1K0D2", title: "Cap food delivery at £180 a month and cancel NOW Entertainment", figure: "+£116.39 / month",
      what: "Proposed by the Advisor from fnd_01JAF3Q8ZK and fnd_01JAF3QB4R. The Verifier re-simulated the impact with the same seed as the baseline.",
      inputs: [["Food delivery", "£286.40 → cap £180 = +£106.40"], ["NOW Entertainment", "cancel = +£9.99"], ["Monthly effect", "+£116.39"], ["Buffer risk before 28 Oct", "78% → 41%"], ["Feasibility", "Cap is 11% under your 3-month median (bound: ≤ 40%)"], ["Simulation", "sim_01JAF8A3TS · seed 0x4F1C"]],
      formula: "impact = simulate(baseline ⊕ {cap food 180; cancel NOW}) − baseline\nP(breach) 0.78 → 0.41 (205 / 500 paths)",
      verification: [
        ["rejected", "v1 · Verifier · 06:01:12", "“Cap food delivery at £90/mo, +£220/mo.” Rejected: the cap is 56% under the 3-month median (bound 40%), and the recomputed impact is £196.40, not the claimed £220."],
        ["revised", "v2 · Advisor · 06:01:19", "Raised the cap to £180 and added the NOW Entertainment cancellation from the overlap finding."],
        ["verified", "v2 · Verifier · 06:01:24", "Evidence refs resolve (2/2). Recomputed impact £116.39 matches. Feasible. Not generic. Family support was not touched. Approved."]
      ],
      chips: [["finding", "fnd_01JAF3Q8ZK"], ["finding", "fnd_01JAF3QB4R"], ["simulation", "sim_01JAF8A3TS"], ["verification", "ver_01JAF8A5H1"]]
    },
    sim_trip_dec: {
      kind: "Simulation", id: "sim_01JAFB2K7Y4C", title: "Lowest December balance with the flights", figure: "£410 on 17 Dec",
      what: "Baseline forecast with one £640 payment on 1 Dec. It uses the same seed as the baseline, so the gap comes only from the flights.",
      inputs: [["Scenario", "scn_01JAFB2H3P · parsed from your question"], ["Outflow", "£640 on 1 Dec (flights home for Christmas)"], ["Baseline P50, 17 Dec", "£1,050"], ["With flights, 17 Dec", "£410, still above your £300 buffer"], ["Seed", "0x4F1C (shared with baseline)"]],
      formula: "sim_t = baseline_t − 640 · 𝟙[t ≥ 1 Dec]\n17 Dec: 1,050 − 640 = 410",
      chips: [["forecast", "fc_01JAF7R0X6NN"], ["simulation", "sim_01JAFB2K7Y4C"]]
    },
    sim_trip_jan: {
      kind: "Simulation", id: "calc_01JAFB2M0QH", title: "Lowest January balance with the flights", figure: "£260 on 27 Jan",
      what: "The flights leave December’s pay with £640 less to cover the 41-day stretch to 28 Jan. The low falls £40 under your buffer the day before January pay.",
      inputs: [["Baseline P50, 27 Jan", "£900"], ["With flights", "£260 (£40 under £300)"], ["Scenario", "scn_01JAFB2H3P"]],
      formula: "27 Jan: 900 − 640 = 260",
      chips: [["finding", "fnd_01JAF3QJ7N"], ["simulation", "sim_01JAFB2K7Y4C"]]
    },
    sim_plan_jan: {
      kind: "Simulation", id: "sim_01JAFB3C1V8E", title: "January low with the flights and the checked plan", figure: "≈ £493 on 27 Jan",
      what: "The flights scenario combined with recommendation rec_01JAF8A1K0D2, counted from your November pay (two months of +£116.39 by 27 Jan).",
      inputs: [["Scenario", "scn_01JAFB2H3P ⊕ rec_01JAF8A1K0D2"], ["Saved by 27 Jan", "≈ £233"], ["January low", "≈ £493, above your buffer"]],
      formula: "260 + 2 × 116.39 ≈ 493"
    },
    goal_fund: {
      kind: "Goal projection", id: "goal_01JA9Z0E5B", title: "Emergency fund by 31 Mar 2027", figure: "£1,592 → £952",
      what: "The emergency fund is earmarked in your Monzo account. Progress is the cash above your buffer at the March pre-salary low. The £640 flights come out of the same money.",
      inputs: [["Target", "£1,500 by 31 Mar 2027"], ["Baseline P50", "£1,592, on track"], ["With flights", "£952, £548 short"], ["With flights + plan", "comes from the engine"]],
      formula: "progress = P50 low(25 Mar) − buffer = 1,892 − 300 = 1,592\nwith flights: 1,592 − 640 = 952  (£548 short)"
    },
    sim_delay_low: {
      kind: "Simulation", id: "sim_01JAFC0D9N2A", title: "Lowest balance if salary is a week late", figure: "−£1,503 on 3 Nov",
      what: "Salary moved from 28 Oct to 4 Nov. Family support (29 Oct) and rent (standing order, 1st) still leave on time.",
      inputs: [["Scenario", "scn_01JAFC0B4M · income delay"], ["Shift", "+7 days"], ["Days overdrawn", "6 (29 Oct → 3 Nov)"]],
      formula: "sim_t = baseline_t − 2,940 · 𝟙[28 Oct ≤ t < 4 Nov]"
    },
    buffer: {
      kind: "Preference · declared", id: "pref_buffer", title: "Your buffer", figure: "£300",
      what: "The least you want to keep in the account. Foresight measures risk against it. You set it when your first briefing opened; we suggested it from your bills.",
      inputs: [["Set", "12 Oct 2026, by you"], ["Suggested longer-term", "one month of essential bills"], ["Used by", "buffer-breach probability, scenario verdicts"]],
      formula: "risk = P(balance_t < 300 for some t before payday)"
    },
    to_go_out: {
      kind: "Calculation", id: "calc_01JAF7R1D2KM", title: "Still to go out before payday", figure: "£693.93",
      what: "Known bills and commitments due between today and 28 Oct, from detected recurring payments. Everyday spending is not included here; the forecast handles that.",
      inputs: [["Council tax", "£162.00 · 15 Oct"], ["Family support (LemFi)", "≈ £250.00"], ["Energy", "£78.00 · 20 Oct"], ["Water", "£42.00 · 22 Oct"], ["Broadband", "£31.00"], ["Sky TV", "£46.00"], ["Subscriptions", "£84.93"]],
      formula: "162 + 250 + 78 + 42 + 31 + 46 + 84.93 = £693.93   (04 fixture)"
    },
    subs_total: {
      kind: "Calculation", id: "calc_01JAF3R0YZ", title: "Subscriptions, monthly", figure: "£84.93",
      what: "Seven recurring card or Direct Debit payments classified as subscriptions.",
      inputs: [["PureGym", "£27.99"], ["Netflix", "£12.99"], ["Spotify", "£12.99"], ["NOW Entertainment", "£9.99 · overlaps Sky TV"], ["Disney+", "£8.99"], ["Amazon Prime", "£8.99"], ["iCloud+", "£2.99"]],
      formula: "Σ monthly amounts = £84.93"
    }
  };
  window.FS_EVIDENCE = EV;

  // ---------- Theme ----------
  function setTheme(t) {
    if (t === "system") { document.documentElement.removeAttribute("data-theme"); try { localStorage.removeItem("fs-theme"); } catch (e) {} }
    else { document.documentElement.setAttribute("data-theme", t); try { localStorage.setItem("fs-theme", t); } catch (e) {} }
    document.querySelectorAll("[data-theme-btn]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.themeBtn === t)));
    if (window.ForesightCharts) window.ForesightCharts.renderAll();
  }
  function currentTheme() { return document.documentElement.getAttribute("data-theme") || "system"; }

  // ---------- Shell ----------
  function shell() {
    const active = document.body.dataset.page;
    const HH = active === "household";
    const IN = active === "india";
    const WS = [
      { key: "amara", href: "index.html", initial: "A", name: "Amara", meta: "UK · £", current: !HH && !IN },
      { key: "jamie", href: null, initial: "J", name: "Jamie", meta: "UK · £", current: false },
      { key: "mensah", href: "household.html", initial: "M", name: "Kofi & Hannah", meta: "UK · £ · household", current: HH },
      { key: "aanya", href: "india.html", initial: "A", name: "Aanya", meta: "India · ₹", current: IN }
    ];
    const cur = WS.find((w) => w.current);
    const wsItem = (w) => w.href
      ? `<li><a href="${w.href}"${w.current ? ' aria-current="true"' : ""}><span class="avatar" aria-hidden="true">${w.initial}</span><span class="who">${w.name}<small>${w.meta}</small></span></a></li>`
      : `<li><span class="ws-off" title="Not drawn in this prototype"><span class="avatar" aria-hidden="true">${w.initial}</span><span class="who">${w.name}<small>${w.meta} · not drawn</small></span></span></li>`;
    const rail = document.createElement("aside");
    rail.className = "rail";
    rail.setAttribute("aria-label", "Foresight");
    const link = (p) => `<a href="${p.href}"${p.key === active ? ' aria-current="page"' : ""}><span>${p.label}</span>${p.count ? `<span class="count" title="${p.count} new">${p.count}</span>` : ""}</a>`;
    rail.innerHTML = `
      <a class="wordmark" href="index.html"><span class="mark" aria-hidden="true"></span>Foresight</a>
      <nav aria-label="Primary">${PAGES.map(link).join("")}</nav>
      <div>
        <div class="rail-label">Prototype</div>
        <nav class="secondary" aria-label="Prototype pages">${DESIGN.map(link).join("")}</nav>
      </div>
      <div class="rail-foot">
        <details class="ws-switch">
          <summary aria-label="Workspace: ${cur.name}. Switch workspace" title="Switch workspace"><span class="avatar" aria-hidden="true">${cur.initial}</span><span class="who">${cur.name}<small>${cur.meta}</small></span><span class="ws-caret" aria-hidden="true">▾</span></summary>
          <ul class="ws-list" role="list">${WS.map(wsItem).join("")}<li><a href="onboarding.html" class="ws-new">+ New workspace</a></li><li><a href="#" class="ws-new" aria-disabled="true" title="Rename, export or delete a workspace (prototype: not wired)">Manage workspaces</a></li></ul>
        </details>
        <div class="rail-tools">
          <div class="segmented" role="radiogroup" aria-label="Edition">
            <button role="radio" data-theme-btn="light">Day</button>
            <button role="radio" data-theme-btn="system">Auto</button>
            <button role="radio" data-theme-btn="dark">Night</button>
          </div>
        </div>
      </div>`;
    const main = document.querySelector("main");
    const wrap = document.createElement("div");
    wrap.className = "shell";
    main.parentNode.insertBefore(wrap, main);
    wrap.appendChild(rail);
    wrap.appendChild(main);
    const top = document.createElement("div");
    top.className = "mobile-top";
    top.innerHTML = `<a class="wordmark" href="index.html" style="padding:0"><span class="mark" aria-hidden="true"></span>Foresight</a>
      <button class="btn btn-sm" data-theme-cycle aria-label="Switch edition">Day / Night</button>`;
    main.prepend(top);
    rail.querySelectorAll("[data-theme-btn]").forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.themeBtn)));
    try { if (new URLSearchParams(location.search).get("ws") === "open") rail.querySelector(".ws-switch").open = true; } catch (e) {}
    top.querySelector("[data-theme-cycle]").addEventListener("click", () => {
      const dark = getComputedStyle(document.documentElement).getPropertyValue("--paper").trim().toLowerCase() === "#0f1115";
      setTheme(dark ? "light" : "dark");
    });
    rail.querySelectorAll("[data-theme-btn]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.themeBtn === currentTheme())));

    // Evidence drawer
    const scrim = document.createElement("div");
    scrim.className = "drawer-scrim";
    const drawer = document.createElement("aside");
    drawer.className = "drawer";
    drawer.setAttribute("role", "dialog");
    drawer.setAttribute("aria-modal", "true");
    drawer.setAttribute("aria-labelledby", "ev-title");
    drawer.setAttribute("hidden", "");
    document.body.append(scrim, drawer);
    scrim.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
  }

  let lastFocus = null;
  function openDrawer(key) {
    const e = EV[key];
    if (!e) return;
    const dr = document.querySelector(".drawer");
    const kv = (rows) => `<dl class="kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
    const st = { rejected: ["status-rejected", ICON.cross, "Rejected"], revised: ["status-revised", ICON.loop, "Revised"], verified: ["status-verified", ICON.check, "Checked"] };
    dr.innerHTML = `
      <div class="drawer-head">
        <div><span class="kicker">${e.kind} · <span class="mono">${e.id}</span></span><h2 id="ev-title">${e.title}</h2></div>
        <button class="btn icon-btn" data-close aria-label="Close evidence">${ICON.cross.replace('viewBox', 'width="14" height="14" viewBox')}</button>
      </div>
      <div class="drawer-body">
        <div><div class="ev-figure num">${e.figure}</div><p class="muted" style="margin-top:8px;max-width:56ch">${e.what}</p></div>
        <section class="ev-section"><h3>Inputs</h3>${kv(e.inputs)}</section>
        ${e.formula ? `<section class="ev-section"><h3>How it was calculated</h3><div class="formula">${e.formula}</div></section>` : ""}
        ${e.verification ? `<section class="ev-section"><h3>Verification history</h3><ul class="vlog">${e.verification.map(([s, who, txt]) => `<li><span class="status ${st[s][0]}">${st[s][1]}${st[s][2]}</span><div><b class="mono">${who}</b><p>${txt}</p></div></li>`).join("")}</ul></section>` : ""}
        ${e.chips ? `<section class="ev-section"><h3>Linked records</h3><div class="chips">${e.chips.map(([k, id]) => `<span class="chip chip-evidence" data-kind="${k}">${id}</span>`).join("")}</div></section>` : ""}
        <section class="ev-section"><h3>Provenance</h3>${kv([["Produced by", "Deterministic engine — no model wrote this number"], ["Engine", ENGINE], ["Agent run", `<span class="mono">${RUN}</span> · Briefing, 12 Oct 10:42`], ["Data version", "v9 · 1,163 transactions through 11 Oct"]])}</section>
      </div>`;
    dr.removeAttribute("hidden");
    lastFocus = document.activeElement;
    requestAnimationFrame(() => { dr.classList.add("on"); document.querySelector(".drawer-scrim").classList.add("on"); dr.querySelector("[data-close]").focus(); });
    dr.querySelector("[data-close]").addEventListener("click", closeDrawer);
  }
  function closeDrawer() {
    const dr = document.querySelector(".drawer");
    if (!dr || !dr.classList.contains("on")) return;
    dr.classList.remove("on");
    document.querySelector(".drawer-scrim").classList.remove("on");
    setTimeout(() => dr.setAttribute("hidden", ""), 160);
    if (lastFocus) lastFocus.focus();
  }
  window.FS_openEvidence = openDrawer;

  // ---------- Tabs & radiogroups ----------
  function tabs() {
    document.querySelectorAll('[role="tablist"]').forEach((list) => {
      const ts = [...list.querySelectorAll('[role="tab"]')];
      ts.forEach((t) => t.addEventListener("click", () => {
        ts.forEach((o) => { o.setAttribute("aria-selected", String(o === t)); o.tabIndex = o === t ? 0 : -1; const p = document.getElementById(o.getAttribute("aria-controls")); if (p) p.hidden = o !== t; });
        if (window.ForesightCharts) window.ForesightCharts.renderAll();
        list.dispatchEvent(new CustomEvent("tabchange", { detail: t.id }));
      }));
      list.addEventListener("keydown", (e) => {
        const i = ts.indexOf(document.activeElement);
        if (i < 0) return;
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") { const n = ts[(i + (e.key === "ArrowRight" ? 1 : ts.length - 1)) % ts.length]; n.focus(); n.click(); }
      });
    });
    document.querySelectorAll('[role="radiogroup"]:not([aria-label="Edition"])').forEach((g) => {
      g.querySelectorAll('[role="radio"]').forEach((r) => r.addEventListener("click", () => {
        g.querySelectorAll('[role="radio"]').forEach((o) => o.setAttribute("aria-checked", String(o === r)));
      }));
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    // Every page carries a visible label: this is a static design artefact, not the product.
    if (!document.querySelector(".illustrative-banner")) {
      const b = document.createElement("div");
      b.className = "illustrative-banner";
      b.setAttribute("role", "note");
      b.textContent = "Illustrative design prototype · fictional data · static mock, never loaded by the product at runtime";
      document.body.prepend(b);
    }
    shell();
    tabs();
    document.addEventListener("click", (e) => {
      const f = e.target.closest("[data-ev]");
      if (f) { e.preventDefault(); openDrawer(f.dataset.ev); }
    });
    document.addEventListener("keydown", (e) => {
      const f = e.target.closest && e.target.closest('[data-ev][role="button"]');
      if (f && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openDrawer(f.dataset.ev); }
    });
    // Deep link, as specified in docs/04 §2: ?evidence=<key>
    try { const q = new URLSearchParams(location.search).get("evidence"); if (q) openDrawer(q); } catch (e) {}
  });
})();

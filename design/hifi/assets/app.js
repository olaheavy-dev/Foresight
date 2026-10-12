/* Interactions for the hi-fi prototype:
   - fills every [data-fx] / [data-calc] number from window.FIXTURE (generated, fictional);
   - mobile search, the collapsible conversation panel;
   - Workspace: thread switcher (?q=holiday|spending) and the answer skeleton: every thread has the
     same tabs in the same order (#overview, #details, #recommendation, #transactions, #checked;
     old hashes redirect), ARIA tabs with arrow keys, jump links, the what-if table, recent orders,
     and the loading state (?state=loading). */

(function () {
  const F = window.FIXTURE;
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const money = (v, dp = 0) =>
    "£" + Math.abs(v).toLocaleString("en-GB", { minimumFractionDigits: dp, maximumFractionDigits: dp });
  const day = (iso) => {
    const d = new Date(iso + "T00:00:00Z");
    return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
  };
  const short = (iso) => {
    const d = new Date(iso + "T00:00:00Z");
    return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
  };
  const FORMATS = {
    money0: (v) => (v < 0 ? "−" : "") + money(v),
    money2: (v) => (v < 0 ? "−" : "") + money(v, 2),
    plusmoney2: (v) => (v < 0 ? "−" : "+") + money(v, 2),
    overdrawn: (v) => (v < 0 ? `${money(v)} overdrawn` : money(v)),
    pct: (v) => `${Math.round(v)}%`,
    pctup: (v) => `${Math.round(v)}%`,
    int: (v) => String(Math.round(v)),
    day,
    short,
    weeks: (v) => `${Math.round(v)} week${Math.round(v) === 1 ? "" : "s"}`,
  };
  const get = (path) => path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), F);
  const CALC = {
    holidayCost: () => F.end_of_march_all.plan - F.end_of_march_all.holiday_1200_28nov,
    weeklySpend: () => F.daily_spend_model * 7,
    bufferWeeks: () => F.what_if["1200_after_payday"].vs_buffer / (F.daily_spend_model * 7),
    deliveryDiff: () => F.food_delivery.last_30_days.total - F.food_delivery.usual_30_days,
  };

  function bindNumbers(root = document) {
    if (!F) return;
    root.querySelectorAll("[data-fx], [data-calc]").forEach((node) => {
      const value = node.dataset.fx ? get(node.dataset.fx) : CALC[node.dataset.calc]?.();
      const format = FORMATS[node.dataset.fmt] || String;
      if (value === undefined || value === null || Number.isNaN(value)) {
        node.textContent = "—";
        node.title = "Not available in this data";
        return;
      }
      node.textContent = format(value);
    });
    // Bars are scaled within their own comparison group, never across the page.
    root.querySelectorAll("[data-bar-of]").forEach((bar) => {
      const group = bar.closest(".compare") || root;
      const keys = [...group.querySelectorAll("[data-bar-of]")].map((b) => get(b.dataset.barOf));
      bar.style.setProperty("--w", `${(100 * get(bar.dataset.barOf)) / Math.max(...keys)}%`);
    });
  }

  function buildWhatIf() {
    const body = document.querySelector("#whatif tbody");
    if (!body || !F) return;
    const rows = [
      ["no_holiday_dec", "No holiday", "plan"],
      ["800_after_payday", "£800 · from 28 Nov", "holiday_800_28nov"],
      ["1200_after_payday", "£1,200 · from 28 Nov", "holiday_1200_28nov", true],
      ["1500_after_payday", "£1,500 · from 28 Nov", "holiday_1500_28nov"],
      ["1200_on_6nov", "£1,200 · on 6 Nov", "holiday_1200_6nov"],
    ];
    body.innerHTML = rows.map(([key, label, eom, sel]) => {
      const w = F.what_if[key];
      const neg = w.lowest < 0;
      const low = neg ? `−${money(w.lowest)}` : money(w.lowest);
      const note = `${short(w.date)}${neg ? " · overdrawn" : ""}`;
      return `<tr${sel ? ' class="sel"' : ""}>
        <td class="lead">${sel ? `<strong>${label}</strong>` : label}</td>
        <td class="r num${neg ? " neg" : ""}" data-label="Lowest balance">${sel ? `<strong>${low}</strong>` : low}<span class="d2">${note}</span></td>
        <td class="r num" data-label="Paths below £500">${w.chance_below_buffer_pct}%</td>
        <td class="r num" data-label="On 31 Mar">${money(F.end_of_march_all[eom])}</td>
      </tr>`;
    }).join("");
  }

  function buildRecentOrders() {
    const body = document.querySelector("#recent-orders tbody");
    if (!body || !F) return;
    body.innerHTML = F.food_delivery.recent.map((o) =>
      `<tr><td class="lead num">${short(o.date)}</td><td class="desc" data-label="Description" title="${o.merchant}">${o.merchant}</td><td data-label="Category"><span class="cat"><i class="amber"><svg aria-hidden="true"><use href="#i-utensils"/></svg></i><span class="cat-l">Food delivery</span></span></td><td class="r num" data-label="Amount">−${money(o.amount, 2)}</td><td data-label="Type"><span class="badge grey">Completed</span></td></tr>`,
    ).join("");
  }

  /* ---------- Threads ---------- */
  // The answer skeleton: one fixed tab set, same order and names for every thread.
  const TABS = ["overview", "details", "recommendation", "transactions", "checked"];
  const REDIRECT = { cashflow: "details", impact: "details", trend: "details", where: "details",
    methodology: "checked", suggestion: "overview" };
  function currentThread() {
    return new URLSearchParams(location.search).get("q") === "spending" ? "spending" : "holiday";
  }
  const activeAnalysis = () => document.querySelector(`.analysis[data-thread="${currentThread()}"]`);
  function showThread(name) {
    const body = document.querySelector(".ws-body");
    if (!body) return;
    body.dataset.thread = name;
    document.querySelectorAll("[data-thread]").forEach((n) => {
      if (n === body) return;
      n.hidden = n.dataset.thread !== name;
    });
    document.querySelectorAll("[data-thread-text]").forEach((n) => { n.hidden = n.dataset.threadText !== name; });
    document.querySelectorAll("[data-thread-link]").forEach((a) => a.setAttribute("aria-checked", String(a.dataset.threadLink === name)));
  }

  /* ---------- Tabs (scoped to the visible thread) ---------- */
  function hideEmptyTabs(root) {
    // A tab with no content for this answer is hidden, never reordered or renamed.
    root.querySelectorAll('[role="tab"]').forEach((t) => {
      const panel = document.getElementById(t.getAttribute("aria-controls"));
      t.hidden = !panel || !panel.querySelector(".card, .evidence, table, .chart");
    });
  }
  function selectTab(name, { focus = false, push = true } = {}) {
    const root = activeAnalysis();
    if (!root) return;
    const tabs = [...root.querySelectorAll('[role="tab"]')].filter((t) => !t.hidden);
    const tab = tabs.find((t) => t.dataset.tab === name) || tabs[0];
    if (!tab) return;
    root.querySelectorAll('[role="tab"]').forEach((t) => {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    });
    if (focus) tab.focus();
    tab.scrollIntoView({ block: "nearest", inline: "nearest" });
    if (push) history.replaceState(null, "", `${location.search}#${tab.dataset.tab}`);
    // Charts inside a newly shown panel need a draw now that they have a width.
    window.dispatchEvent(new Event("resize"));
  }

  function wireTabs() {
    document.querySelectorAll('[role="tablist"]').forEach((list) => {
      list.addEventListener("click", (e) => {
        const t = e.target.closest('[role="tab"]');
        if (t) selectTab(t.dataset.tab);
      });
      list.addEventListener("keydown", (e) => {
        const tabs = [...list.querySelectorAll('[role="tab"]')].filter((t) => !t.hidden);
        const i = tabs.indexOf(document.activeElement);
        if (i < 0) return;
        const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
        if (next === undefined) return;
        e.preventDefault();
        selectTab(tabs[(next + tabs.length) % tabs.length].dataset.tab, { focus: true });
      });
    });
  }

  /* In-page anchors: tab names switch tabs (old names redirect) in either thread. */
  function followHash({ initial = false } = {}) {
    let hash = location.hash.slice(1);
    if (REDIRECT[hash]) {
      hash = REDIRECT[hash];
      history.replaceState(null, "", `${location.search}#${hash}`);
    }
    if (TABS.includes(hash)) {
      selectTab(hash, { push: false });
      if (!initial) activeAnalysis()?.querySelector(".tabs")?.scrollIntoView({ block: "start", behavior: "smooth" });
    } else {
      selectTab("overview", { push: false });
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindNumbers();
    buildWhatIf();
    buildRecentOrders();

    const topbar = document.querySelector(".topbar");
    const toggle = document.querySelector(".search-toggle");
    if (topbar && toggle) {
      toggle.addEventListener("click", () => {
        const open = topbar.classList.toggle("search-open");
        toggle.setAttribute("aria-expanded", String(open));
      });
    }

    const convo = document.querySelector(".convo");
    const convoToggle = document.querySelector(".convo-toggle");
    if (convo && convoToggle) {
      convoToggle.addEventListener("click", () => {
        const collapsed = convo.dataset.collapsed !== "false";
        convo.dataset.collapsed = collapsed ? "false" : "true";
        convoToggle.setAttribute("aria-expanded", String(collapsed));
      });
    }

    if (document.querySelector(".ws-body")) {
      showThread(currentThread());
      document.querySelectorAll(".analysis").forEach(hideEmptyTabs);
      wireTabs();
      followHash({ initial: true });
      window.addEventListener("hashchange", () => followHash());
      // Jump links in the conversation close the panel on small screens so the answer is visible.
      document.querySelectorAll(".jump a").forEach((a) => a.addEventListener("click", () => {
        if (convo && window.matchMedia("(max-width: 1279px)").matches) {
          convo.dataset.collapsed = "true";
          convoToggle?.setAttribute("aria-expanded", "false");
        }
      }));
    }

    const canvas = document.querySelector(".canvas");
    if (canvas && new URLSearchParams(location.search).get("state") === "loading") {
      canvas.classList.add("is-loading");
      canvas.setAttribute("aria-busy", "true");
    }
  });
})();

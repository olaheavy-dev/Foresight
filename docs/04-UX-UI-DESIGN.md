# 04 — UX/UI Design

Status: rev 6 (12 Oct 2026). Design direction **"Atelier light"**, from the owner's reference mockups. *Supersedes the "Broadsheet" spec (rev 1–5), the static prototype in `design/prototype/` and the Stage 1 concepts in `design/concepts/`.*

This document holds the durable UX rules. The visual and structural detail lives in the design artefacts:

| Artefact | What it decides |
|---|---|
| `.design/foresight/DESIGN_BRIEF.md` | Aesthetic, named philosophy, content rules, success criteria |
| `.design/foresight/INFORMATION_ARCHITECTURE.md` | Site map and routes, navigation, content priority per page, flows, naming, the answer-composition table |
| `design/tokens/tokens.css` | All colour, type, spacing, radius, shadow, motion and breakpoint values (light + dark), copied to `frontend/app/` and `design/hifi/assets/` (kept identical by `tests/unit/test_design_tokens.py`) |
| `design/hifi/` | The hi-fi reference: `landing.html`, `home.html`, `workspace.html` (including `?q=spending`, `?state=loading`, `?theme=dark`) |
| `design/fixture/` | The generator of every demo figure (register §10a) |
| `.design/foresight/TASKS.md` | The ordered UI build plan for the Next.js app |
| `.design/foresight/DESIGN_REVIEW.md` | Latest structured review, with screenshots at 375/768/1280/1440, light and dark |

## 1. Experience principles

1. **Future first.** Forecasts, scenarios and upcoming risks dominate; history appears only to anchor the forecast.
2. **Answer first, evidence one click away.** Each surface leads with a verdict or headline, then a few numbers, then one visual. Detail lives in tabs or the Evidence drawer (progressive disclosure).
3. **Agent-native, not chat-dependent.** Agents act unprompted (proactive insights); a question produces a composed answer, not a wall of prose.
4. **Every number has a receipt.** Any figure can open its calculation, sources and check trail. The AI never writes figures.
5. **Human control.** Foresight suggests; it never moves money. Users accept or dismiss.
6. **Truthful presentation.** Observed, computed, forecast, hypothetical, AI-written and checked content always look different. As-of dates and likely ranges are shown, and demo data is labelled.
7. **Warm precision.** Calm, airy and premium (the owner's mockups), never a generic AI dashboard.

## 2. App shell and navigation

- **Primary navigation (≤ 5):** Home · AI Workspace · Decision Lab · Transactions · Activity. A sidebar from 1024px; a bottom tab bar below 1024px (short labels, ≥ 44px targets).
- **Top bar:** the "Ask Foresight about your finances…" box (starts a new AI Workspace thread), notifications (Activity count), and the avatar menu (**Switch profile** · Settings · Theme Light/Dark/System · Quality).
- **Profile:** the UI name for the financial space (data model `Workspace`, `wsp_`), avoiding a clash with "AI Workspace". Demo profiles show a "Demo data" badge.
- **Sidebar footer:** a "Quality checks" card linking to the public `/quality` page ("not measured yet" until evals run).
- **Routes:** register §10 and the IA document. Overlays: the Evidence drawer (`?evidence=<id>`) and the profile switcher.

## 3. Surfaces

### 3.1 Home (`/home`)
Content priority:
1. greeting, serif hero "Your money, a few steps ahead." and the mountain artwork
2. four key numbers: balance with as-of, lowest before payday with "Below buffer" if it applies, next salary, insights to review
3. cash-flow forecast: **lowest balance before each payday** with likely range, a short observed history and the Today rule (chart option (a))
4. Financial briefing (≤ 4 data-grounded items)
5. Proactive insights (≤ 3 cards, one action each).

**Caching.** Home is a persisted snapshot (`brf_`):
- Figures come from stored calculations.
- LLM-written sentences are regenerated **only** on a `data_version` change, a new checked recommendation or insight, the daily 06:30 rollover, a buffer or goal change, or Refresh. There is no LLM call per visit.
- If data changes after the text was written, a staleness line says so. Old sentences never receive new numbers.

**Variants:** relative mode (no balance; show "—" plus the reason), too little history (< 45 days: history only), stale statement ("Your latest statement ends 30 Sep…", band widened), nothing to act on (a real positive state), multi-account (scope selector and coverage indicator, §6), and no regular income found (§5.3).

### 3.2 AI Workspace (`/workspace/[threadId]`)
- **App shell:** fixed viewport height (100dvh) with two independently scrolling columns. The **follow-up input is always visible**: pinned at the bottom of the conversation column; on mobile it's fixed above the bottom tab bar.
- **Conversation:** the assistant's answer is 2–3 sentences, followed by links that switch tabs (Compare amounts → Recommendation, See transactions → Transactions, How I checked → How it was checked), "Try asking…" chips and a thread list.
- **Answer canvas = the answer skeleton** (`08` §7a): the same frame for every question; only slot content varies.
  - **Overview** is one screen at 1440×900, slots always in this order: Verdict · ≤ 3 key numbers · exactly one main visual · What to do (the checked recommendation; the slot collapses when there is no advice) · Evidence line ("Checked by 6 agents · 1 draft rejected · View how").
  - **Tabs**, one fixed set in a fixed order: Overview · Details (e.g. weekly sawtooth with paydays) · Recommendation (what-if table, rejected drafts with reasons) · Transactions · How it was checked (agent timeline and methodology note). Hashes `#overview` `#details` `#recommendation` `#transactions` `#checked`; a tab with no content is hidden, never reordered or renamed. Keyboard-operable.
- **Content adapts by intent, the frame doesn't.** Affordability → scenario comparison as the main visual, weekly cash flow in Details. Spending/trend → breakdown by merchant as the main visual, trend in Details, a behaviour-based suggestion in What to do. Low confidence → a clarifying question with 2–4 options.
- **Loading:** a skeleton canvas plus live step labels ("Analysing transactions → Building forecast → Simulating → Checking"), streamed over SSE.
- **Follow-up actions** post structured messages (switch tab, try another amount, save to the Lab) with no re-classification.

### 3.3 Decision Lab (`/lab`, `/lab/[scenarioId]`)
- **Hero:** a wide baseline-vs-scenario chart (observed solid, forecast and band, scenario dashed from the point of divergence, buffer dotted, risk markers at the lowest points).
- **Controls panel:** amount, date, income disruption, savings adjustment and buffer. Each change re-runs the engine (no AI) with the same seed, and readouts update via `aria-live`.
- **Scenario chips:** current path · holiday · delayed salary · car repair. Below the chart: an outcome comparison (lowest point, chance below buffer, 31 March), then interventions, with the rejected option and its reason, then assumptions and likely range. A "Goals" view lives here too.

### 3.4 Insight detail (`/insights/[insightId]`)
Shows, in order: alert headline and severity → why it was detected (the named change and its source observations) → financial effect (before/after projection, at-risk dates) → suggested actions with estimated effect, feasibility, Accept/Dismiss and the rejected option → audit trail (model vs deterministic steps, check outcome, timestamps) → Evidence drawer.

### 3.5 Transactions, Activity, Settings, Quality
- **Transactions** (`?tab=all|review|recurring|imports`): search and filters; day-grouped rows showing payment-type tag and provenance. A row opens a drawer with the raw narration, categorisation reason and history, and source file. Category corrections teach merchant memory ("Applied to 6 similar · Undo"). Rows stack below 768px.
  - **Review:** low-confidence rows first, with bulk accept.
  - **Recurring:** median amount, cadence, next date, overlap or price change. "Mark as unused" is the only way Foresight learns usage.
  - **Imports:** history and saved format profiles, with undo import.
- **Activity:** reverse-chronological events (insights, recommendations checked/rejected/accepted/dismissed, forecast updates, imports, digests, agent runs), with filters and links to evidence.
- **Settings:** Profile (name, country → locale pack, home currency) · Pay (after tax) · Buffer & goals · Digest (Telegram/email, schedule, send a test) · Insights opt-ins (betting) · Data & privacy (export, delete with typed confirmation) · About the engine.
- **Quality** (public): eval results from `latest.json` and the generated "Not shipped (planned)" list.

### 3.6 Landing (`/`) and Import (`/start`)
- **Landing:** a split layout. "Explore the live demo" (demo profile → `/home`) and "Import a CSV statement" (→ `/start`); the sign-in form is visible but **disabled** ("Accounts are coming after the hackathon"); a privacy line; the marketing hero with the forecast card, a proactive insight and the mountains.
- **Import:** three steps (register §10b).
  1. **Drop statements.** Multi-file. Each file row shows its detected format, rows read and reconciliation status. An unknown layout triggers "Confirm your columns" once. A rejected file shows the reason; other files continue.
  2. **Check what we found.** Income, bills and subscriptions, with one-tap confirm. Gap questions appear only where detected (≤ 3 in total), e.g. "Monzo exports don't include a balance — what's in the account today?"
  3. **Home.**
  - **Currency and format confirmation** is asked only when ambiguous (§6).

## 4. Data grammar (never violated)

| Kind | Encoding |
|---|---|
| Observed history | Solid ink line (`--color-data-observed`) |
| Forecast (P50) | Solid blue line (`--color-data-forecast`) plus a P10–P90 band ("Likely range") |
| Today | Vertical rule labelled "Today" (`--color-data-today`) |
| Scenario / hypothetical | Dashed purple-magenta (`--color-data-scenario`), starting at divergence, directly labelled |
| Buffer | Dotted rule labelled "Your buffer · £500" (`--color-data-buffer`) |
| Pay-cycle lows | Markers; ringed red when below the buffer |
| AI-written text | "Written by Foresight from your data" attribution; numbers inside it come from stored calculations |
| Checked numbers | "Checked" badge; rejected drafts carry a "Rejected draft" badge with the reason |

Charts carry word legends, a summary sentence and a hidden data table; tooltips stay inside the plot; mobile uses ≤ 4 ticks.

## 5. Proactive insights and explainability

### 5.1 Events
Every proactive event is an **InsightEvent**, shown on Home (≤ 3 cards), in Activity, in the notification count and, for the single top item, in the scheduled digest. Toasts are only for confirming the user's own actions.

| Event | Marker | Copy pattern (P1, figures from register §10a) | Actions |
|---|---|---|---|
| New risk detected | ▲ Risk | "Your late-October buffer may fall below £500: lowest £162 on 27 Oct after the £650 car repair." | Investigate · Open in the Lab |
| Behaviour changed | ◆ Change | "Food delivery is up 41%: £286.40 in the last 30 days against a usual £203.10." | Review spending · Ask about this |
| Forecast updated | ↻ Updated | "Your lowest point before payday moved from £812 to £162 after the car repair." | Compare with previous |
| Recommendation generated | ● Checked suggestion | "Move your £400 savings transfer to 29 Oct and keep food delivery under £100 until payday: lowest point £604." | View · Not for me |
| Revised / withdrawn | ⟲ Revised · ⊘ Withdrawn | "We revised a suggestion before showing it: a £40 cap was 72% below your usual pace." / "We withdrew a suggestion we couldn't check." | See both versions |
| Plan at risk | ▲ Plan | "Booking the £1,200 holiday on 6 Nov would leave you £148 overdrawn on 26 Nov." | See options |
| Intervention worked (behind flag `intervention_outcome`) | ✓ Confirmed | Outcome sentence computed from new data; never pre-written | See the comparison |

Severity orders the list (risk > plan > revised/withdrawn > checked suggestion > change > updated > confirmed). Events show once per `data_version` and collapse when superseded. Copy is never guilt-inducing. **Betting insights are opt-in** and neutral, family support abroad and savings are never cut targets, and there are no product recommendations.

### 5.2 Evidence drawer (`?evidence=<id>`)
Tabs: **Reasoning** (findings → forecast → simulation → recommendation) · **Calculation** (readable arithmetic or method summary, engine version, seed, inputs hash, provenance badge per input) · **Data** (the exact transactions, source file, detected format, reconciliation) · **Check** (every Verifier pass with each check, critique and claimed vs recomputed values; drafts side by side) · **Run** (agent timeline, models via Mesh, durations, tokens). Tabs that don't apply are omitted.

P1 example (checked plan): lowest before payday £162 → £604 (P50 of 500 paths). The two effects are moving the £400 savings transfer to 29 Oct (+£400 before payday) and capping delivery at £100 against a usual pace of £143.20 for 13–27 Oct (+£43.20). Check: draft 1 (£40 cap) was rejected as 72% below pace, beyond the 40% feasibility limit, and still below the buffer; draft 2 passed every check.

### 5.3 No regular income found / unconfirmed money in
This follows register §6a. Home says plainly "We didn't find regular income in this account" and offers three equal options:
- add the account your pay goes into
- tell us your take-home (DECLARED)
- continue without income.

Income stays £0 and is shown separately from "From your other account" and "Other money in (not confirmed)". Projected unconfirmed inflows appear as "Assumed, not confirmed" rows with a *Don't assume this* switch, and the Verifier (V-19) never relies on them.

## 6. Components and patterns

1. **Key numbers:** label, value (tabular, serif for hero values), as-of or timespan, optional status badge. Home uses 4 and answers use ≤ 3. No KPI grids beyond that.
2. **Cards:** white surface, `--border-radius-lg`, hairline border, `--shadow-md`; a title in serif with a tinted icon chip.
3. **Recommendation states:** Checked (success tint), Rejected draft (error tint, with reason), Withdrawn, Accepted (tracking), Dismissed (with reason chip).
4. **Provenance badges:** DETECTED, CONFIRMED and DECLARED, on step ② of Import, in Recurring, in Settings → Pay and on every Evidence input. Declared vs observed divergence > 10% prompts a question.
5. **Multi-account controls (only when > 1 account):** a scope selector (Mine · Household · account), a coverage indicator in text, and household wording.
6. **Money formatting:** `formatMoney(minor, currency, locale)`.
   - en-GB: £2,184.50, with a minus before the symbol.
   - en-IN: lakh grouping ₹1,15,000.00.
   - Zero-decimal currencies use their ISO exponent.
   - Forecasts show whole units.
   - Other-currency accounts appear on their own line ("not included in the £ forecast"); there is no FX conversion.
   - India copy carries the honesty note.
7. **Currency and format confirmation:** shown only when ambiguous (`$`/`kr`/`¥`, dd/mm vs mm/dd with no day > 12, ambiguous decimals). The batch stays uncommitted until answered, the answer is saved on the format profile, and it counts toward the 3-question budget.

## 7. States catalogue

| State | Treatment |
|---|---|
| Loading | Skeletons at final sizes; agent step labels in the AI Workspace; "Running 500 paths…" in the Lab |
| Empty | No data → "Import a CSV statement or explore the live demo", plus the drop zone |
| Agent step failed | Name the step and reason, then **Retry the run**; keep the last good snapshot |
| **Model unavailable** (Mesh down) | Deterministic numbers and charts still render; explanations show "Explanations are unavailable right now. Your figures are unaffected." |
| **Stale balance** | "Your latest statement ends 30 Sep. Add October's for an up-to-date forecast."; band widened |
| **Uncertain forecast** | Wide-range note: "Your spending varies a lot, so this range is wide." Verdicts avoid certainty words |
| **Failed import** | Per-file reason and next step; other files continue; nothing partial is committed |
| **Unverifiable intervention** | "We couldn't check this suggestion, so we're not recommending it." (Withdrawn) |
| Successful check | "Checked" badge, with the run in the Evidence drawer |
| Missing data rule | Never render £0 or an invented value; use "—" plus a one-line reason |

## 8. Responsive behaviour (mobile-first)

| Width | Layout |
|---|---|
| 375 (base) | Bottom tab bar, slim top bar with search icon, one-column cards, charts full width with ≤ 4 ticks, tables as stacked rows, the AI Workspace conversation as a collapsible panel with the input fixed above the tab bar, Landing with sign-in stacked above the hero |
| ≥ 768 | Metric cards 2×2, two-column sections where space allows |
| ≥ 1024 | Sidebar replaces the bottom tab bar |
| ≥ 1280 | Three-column AI Workspace (nav · conversation · canvas), 4-up metric cards |
| ≥ 1440 | Mockup layout; key-figure tiles 2×2 only from ≥ 1600 |

## 9. Accessibility

- WCAG 2.2 AA, with token contrast measured in both themes and chart pairs validated for colour vision deficiency (dataviz validator).
- Every status has an icon and a word. Every chart has a summary sentence and a hidden table.
- Full keyboard operation: tabs use ARIA tabs with arrow keys; Esc closes the drawer and returns focus.
- Visible focus via `--shadow-focus`. `aria-live` for streaming answers and recalculated readouts.
- Figures read naturally (e.g. "2,184 pounds 50"). Touch targets ≥ 44px. `prefers-reduced-motion` is respected; text works at 200%; reading width is capped at 68ch.

## 10. Hi-fi coverage (`design/hifi/`)

| Page | Shows |
|---|---|
| `landing.html` | Split sign-in (disabled) and marketing hero, demo and CSV actions |
| `home.html` | Post-car-repair Home with the pay-cycle-lows chart, briefing and insights |
| `workspace.html` | Affordability answer (Overview + 5 tabs), pinned input, `?q=spending` second composition, `?state=loading`, `?theme=dark` |

Still to design directly in Next.js (`TASKS.md`): Decision Lab, Insight detail, Transactions, Import, Activity, Settings, Quality, and the full states pass.

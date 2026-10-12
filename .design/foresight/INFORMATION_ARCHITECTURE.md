# Information Architecture: Foresight

Feature folder: `.design/foresight/` · Based on `DESIGN_BRIEF.md`, the owner's decisions of 12 Oct 2026, `docs/00` §10, `docs/06` §6.2 (intents) and `docs/08` (components).
Supersedes the surface names in `docs/00` §10: Briefing → **Home**, Ask → **AI Workspace**, Ledger → **Transactions**.

## Structural decisions (interview answers)

| Question | Answer | Why |
|---|---|---|
| Primary jobs, by frequency | 1. See where I stand and what's next (Home) · 2. Ask a question (AI Workspace) · 3. Act on a proactive insight (Insight detail) · 4. Test a decision (Decision Lab) · 5. Check or fix transactions (Transactions) · 6. Import data (Import) | Future-first product: orientation and questions dominate, while data housekeeping is occasional. |
| Navigation depth | **Two levels maximum**: section → item (thread, scenario, insight). Everything deeper is a tab, a drawer or a query parameter. | Demo-able in 90 seconds; judges never get lost. |
| What grows over time | Transactions, threads (questions), insights, activity events, scenarios, imports. Fixed: Home, Settings, Quality. | Growing lists get search, filters and pagination (see Content Growth Plan). |
| Distinct user types | One user type (an individual or household managing their own money). Judges get a public **Quality** page and the demo entry, not a separate app. | Avoids a second information architecture for hackathon judges. |
| The 80% view | **Home** for orientation and **AI Workspace** for depth. Home is the default landing after entry. | Matches the brief's synthesis: a command centre for orientation, a studio for investigation. |

## Site Map

- Landing (public) `/`. Demo and CSV entry; sign-in shown but disabled ("coming after the hackathon").
- Import / onboarding `/start`
  - Step 1 · Drop statements `/start?step=files`
  - Step 2 · Check what we found `/start?step=check`
  - Step 3 · Your briefing → redirects to `/home`
- Home `/home`
- AI Workspace `/workspace`. New question; recent threads listed in the conversation column.
  - Thread `/workspace/[threadId]`. Answer canvas with the fixed tab set as URL hashes: `#overview` (default) · `#details` · `#recommendation` · `#transactions` · `#checked`. Tabs without content are hidden, never reordered (see Answer skeleton).
- Decision Lab `/lab`
  - Scenario `/lab/[scenarioId]`
  - Goals `/lab?view=goals`
- Insight detail `/insights/[insightId]`. Reached from Home cards, the Activity feed and the digest link; not in the nav.
- Transactions `/transactions`. Tabs via `?tab=`: `all` (default) · `review` (low-confidence categories) · `recurring` · `imports`
- Activity `/activity`. A chronological feed of insights, recommendations (checked or rejected), forecast updates, imports, digests sent and agent runs.
- Settings `/settings`. Sections via hash: `#profile` · `#buffer-goals` · `#digest` · `#data-privacy` (export and delete).
- Quality `/quality` (public). Evaluation results from `evals/results/latest.json`: categorisation, forecast accuracy against baselines, Verifier catch rate, and "Not shipped" features.

**Overlays (not pages):**
- **Evidence drawer:** `?evidence=<calc_|rec_|fnd_|ver_ id>` on any page. Shows the calculation, inputs, source transactions and the check trail.
- **Profile switcher:** a popover from the avatar.
- **Search:** "Ask Foresight about your finances…" in the top bar opens a new AI Workspace thread with the query.

## Navigation Model

- **Primary navigation, maximum 5:**
  - **Desktop (≥ 1024px):** the left sidebar shows Home · AI Workspace · Decision Lab · Transactions · Activity.
  - **Mobile and tablet (< 1024px):** a bottom tab bar with the same five items, using short labels Home · Workspace · Lab · Transactions · Activity.
- **Secondary navigation:**
  - tabs inside the AI Workspace answer and inside Transactions
  - "Goals" inside Decision Lab
  - contextual links ("Investigate" → Insight detail, "View how" → `#checked`, "Save to Decision Lab" → `/lab/[scenarioId]`).
- **Utility navigation:**
  - **Top bar:** the global ask box, notifications (the Activity badge) and the avatar menu (Settings, switch profile, theme, Quality, About the demo data).
  - **Sidebar footer:** the "Quality checks" card linking to `/quality`.
- **Mobile adaptations:**
  - The top bar collapses to logo · search icon · bell · avatar.
  - In AI Workspace, the conversation becomes a collapsible panel, and the follow-up input is **pinned** above the tab bar.

## Content Hierarchy

### Home
1. **Greeting, hero line and as-of date**: orientation in one glance.
2. **Four key numbers** (balance as of, lowest before payday, next salary, insights to review): the state of play, each with an as-of date or timespan.
3. **Cash-flow forecast**, showing the lowest balance before each payday with its likely range: future-first, so it's the largest visual.
4. **Financial briefing**, up to 4 items written from the data: what changed and why.
5. **Proactive insights**, up to 3 cards, each with one action: what to act on.

### AI Workspace (an answer)
1. **Verdict headline and one-line explanation**: the answer comes first.
2. **Three key numbers** for this answer.
3. **One chart**, chosen by intent.
4. **The checked recommendation**, if the intent needs advice.
5. **Evidence line** ("Checked by N agents · M drafts rejected · View how").

Everything else lives in the tabs. **Rule: Overview fits about one screen at 1440×900.** Its content limit is 1 verdict, ≤3 numbers, 1 chart, ≤1 recommendation and 1 evidence line. The conversation input is always visible.

### Decision Lab
1. **Baseline vs scenario chart**, the hero.
2. **Scenario controls** (amount, date, income change, savings change, buffer).
3. **Outcome comparison**: lowest point, chance below the buffer, end-of-period balance.
4. **Interventions**: proposed, checked and rejected (with reasons).
5. **Assumptions and uncertainty.**

### Insight detail
1. **Alert headline and severity.**
2. **Why it was detected**: the named change, with source observations.
3. **Financial effect**: before/after projection, at-risk dates.
4. **Suggested actions**: estimated effect, feasibility and review controls.
5. **Audit trail**: model vs deterministic steps and the check outcome, which opens the Evidence drawer.

### Transactions
1. **Search, filters and the review queue count.**
2. **Grouped transaction rows**: date, description, category, amount, provenance.
3. **Category corrections**, which teach the merchant memory.
4. **Recurring and Imports tabs.**

## Answer skeleton (consistent frame, variable content)

**Rule (owner decision, 12 Oct 2026):** every answer uses the same frame, so users learn it once. Only the content inside each slot varies with the question.

**Overview slots, always in this order** (≤ 1 screen at 1440×900):
1. **Verdict**: one serif line plus a one-line explanation.
2. **Key numbers**: up to 3.
3. **Main visual**: exactly one, chosen by intent.
4. **What to do**: the checked recommendation (omitted when the intent gives no advice; the slot collapses, nothing moves up out of order).
5. **Evidence line**: "Checked by N agents · M drafts rejected · View how".

**Tabs: one fixed set, always this order and these names:**
**Overview · Details · Recommendation · Transactions · How it was checked**
- **Details** holds the deeper view that fits the question (weekly cash flow for affordability and scenarios; trend and breakdown for spending; goal path for goals).
- A tab with no content for this answer is **hidden, never reordered or renamed**.
- "How it was checked" holds the agent timeline and the methodology note (it replaces "Methodology").
- URL hashes: `#overview` · `#details` · `#recommendation` · `#transactions` · `#checked`.

**Never varies:** the conversation column, the pinned input, the tab bar position, the chart grammar (blue forecast with likely range, dashed scenario, dotted buffer, Today rule), the "Checked" and "Rejected draft" badges, and the evidence line wording.

| Intent | Main visual (slot 3) | What to do (slot 4) | Details | Recommendation | Transactions |
|---|---|---|---|---|---|
| `affordability` | ScenarioComparison (lows before each payday) | InterventionCard | Weekly cash flow with paydays | What-if table plus rejected drafts | Relevant transactions |
| `scenario` | ScenarioComparison | omitted unless `needs_advice` | Weekly cash flow | shown if advice | Relevant transactions |
| `spending_breakdown` / `trend_or_change` | SpendingBreakdownChart (weekly vs usual) | InterventionCard if `needs_advice` | Breakdown by merchant plus trend | shown if advice | Recent orders |
| `transaction_lookup` | TransactionTable (first 10) | omitted | Full filtered list | hidden | hidden (the main visual is the list) |
| `subscription_review` | Overlap list | InterventionCard | Price changes over time | Options plus rejected | Subscription payments |
| `goal_status` | GoalProjection | InterventionCard if off track | Goal path with paydays | shown if advice | Contributions |
| `risk_check` | RiskAssessment with CashFlowForecastChart | InterventionCard if risk | Weekly cash flow | shown if advice | Upcoming bills |
| `advice_request` | Up to 3 InterventionCards | (main visual is the advice) | Effect of each option | Options plus rejected | Evidence transactions |
| `explain_recommendation` | EvidencePanel summary | omitted | Calculation inputs | The recommendation | Source transactions |
| low confidence (< 0.6) | Clarifying question with 2–4 options | none | none | none | none |

"How it was checked" is shown for every answer that ran agents.

## User Flows

### First visit, judge or new user (≤ 90 s)
1. The user lands on `/` and sees the hero and "Explore the live demo" or "Import a CSV statement".
   - **Demo** → `/home` with the fictional demo profile.
   - **Import** → `/start?step=files`.
2. On `/home`: the lowest before payday shows £162 · Below buffer → the proactive insight "Your late-October buffer may fall below £500".
3. **Investigate** → `/insights/[id]`: shows the cause (the £650 car repair), the effect, the rejected draft and the checked plan (+£604).
4. **View how** → Evidence drawer: source transactions and the check trail.
5. The user asks in the top bar, "Can I afford a £1,200 holiday next month?" → `/workspace/[threadId]#overview`.
6. **Try different amounts** → `#recommendation` (what-if table), or **Save to Decision Lab** → `/lab/[scenarioId]`.

### Import a CSV
1. `/start?step=files`: drop one or more files, and see per-file detected format, rows read and reconciliation status.
   - Unknown layout → a "Confirm columns" step (once; saved as a format profile).
   - Reconciliation failed → the file is rejected with a row-level reason; the others continue.
2. `/start?step=check`: confirm income and bills; gap questions appear only where detected (e.g. a missing balance).
3. → `/home` (the first briefing is computed on this visit and cached).

### Ask a question
1. Type in the top bar or the pinned input → the Coordinator classifies the intent.
   - Confidence < 0.6 → a clarifying question with options.
2. Loading state: "Analysing transactions → Building forecast → Simulating → Checking".
3. Answer → `#overview`. Follow-up chips switch tabs or ask a structured follow-up (no re-classification).

### Act on a recommendation
1. From the Insight detail or the Workspace Overview, choose **Accept** / **Dismiss**.
2. Accept → the plan appears in the forecast as "planned" and an Activity event is logged. Outcome checking later shows "Did it work?" (behind the `intervention_outcome` flag).

## Naming Conventions

| Concept | Label in UI | Notes |
|---|---|---|
| Intelligence home | **Home** | Was "Briefing". The briefing is a section on Home. |
| Agent analysis surface | **AI Workspace** (nav); "Workspace" on mobile tabs | Matches the mockup. |
| A user's financial space (data model `Workspace`, `wsp_`) | **Profile** in the UI (avatar menu "Switch profile") | Avoids a clash with "AI Workspace". The data model keeps `workspace`; only the UI label differs. **Owner to confirm.** |
| Transaction list | **Transactions** | Was "Ledger". |
| Recommendation that passed the Verifier | **Checked** | Never "Verified" or "guaranteed". |
| Rejected draft | **Rejected draft** | Always shown with the reason. |
| Projected lowest balance before a payday | **Lowest before payday** | Used in key numbers and on charts. |
| Preferred minimum balance | **Buffer** | "Your buffer · £500". |
| Hypothetical | **Scenario** | Dashed purple-magenta line everywhere. |
| Likely range | **Likely range** | P10–P90 is technical detail for the Evidence drawer only. |
| Evaluation results | **Quality checks** / **Quality** | Public page for judges. |

## Component Reuse Map

| Component | Used on | Behaviour differences |
|---|---|---|
| App shell (sidebar ≥ 1024, bottom tabs < 1024, top bar) | All signed-in pages | AI Workspace switches to a fixed-height shell (100dvh) with independently scrolling columns. |
| Top bar ask box | All signed-in pages | On AI Workspace it continues the current thread. |
| Metric card / key number | Home, AI Workspace Overview, Lab, Insight detail, Landing | Home uses 4; answers use ≤ 3. |
| CashFlowForecastChart | Home, Landing, Workspace Cash flow tab, Lab | Home and Landing: pay-cycle lows. Cash flow and Lab: weekly with paydays. |
| ScenarioComparison | Workspace, Lab, Insight detail | Lab adds live controls. |
| InterventionCard (Checked / Rejected) | Workspace, Insight detail, Lab, Home insight cards | Home shows the compact version. |
| Evidence drawer | Global overlay | Same component everywhere. |
| AgentExecutionTimeline | Workspace "How it was checked" tab, Insight detail, Activity | Activity shows a one-line summary per run. |
| Transaction row | Transactions, Workspace Transactions tab, Insight detail | Stacked layout below 768px. |
| Quality checks card | Sidebar footer, `/quality` | The card summarises; the page shows full tables. |

## Content Growth Plan

- **Transactions:** server-side pagination (50 per page), search (`q`), filters (category, date range, account, type), and grouping by day. The review queue is always reachable as a tab with a count.
- **Threads:** the conversation column lists the 10 most recent; older threads are reached via search. Answers are stored snapshots, so reopening one never re-runs the agents.
- **Insights and Activity:** reverse chronological, filterable by type (insight, recommendation, forecast update, import, digest, agent run), paginated by week. Resolved insights move to "Earlier".
- **Scenarios:** listed in the Lab sidebar with the 5 most recent pinned; others are archived after 30 days unpinned.
- **Imports:** the history lives in Transactions › Imports, newest first.

## URL Strategy

- **Pattern:** `/<section>` and `/<section>/[id]`. IDs use the data-model prefixes (`thr_`, `scn_`, `ins_`). IDs only, no slugs, since the content is private and not SEO-relevant.
- **Tabs:** URL hash for answer tabs (`#overview`), and `?tab=` for list tabs that the server must render (Transactions).
- **Overlays:** `?evidence=<id>`, which can be combined with any page and shared within the demo.
- **States for design and testing:** `?state=loading|empty|error` (prototype and Playwright only).
- **Query parameters:** `q`, `category`, `from`, `to`, `account`, `page`; dates in ISO `YYYY-MM-DD`.
- **Public routes:** `/`, `/quality`. All others require a profile (the demo profile counts).

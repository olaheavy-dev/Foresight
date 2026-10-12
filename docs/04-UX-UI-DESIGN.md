# 04 — UX Architecture & UI Design System

> Canonical inputs: `00-DECISION-REGISTER.md` rev 5.1 (UK primary + India locale, any currency, workspaces; UK/GBP demo, single-account first, §9 visual direction and contrast amendments, §10 IA, §10a P1 figures, §10b three-step onboarding, §6a accounts & income, §6b importers & format profiles). Journeys: `03-USER-JOURNEYS.md`. Block contracts: `08-GENERATIVE-UI-CONTRACTS.md`.
> The static prototype in `design/prototype/` conforms to this document. Where they disagree, this document wins and the prototype is fixed.
> All figures are **fictional design fixtures** (P1 unless a P3/S14 variant is named), not results. Figures not in register §10a are marked *(04 fixture)*.

## Contents

1. Design intent
2. Information architecture & navigation
3. Intelligence Home — the Briefing
4. Ask (the brief's "Agent Workspace")
5. Financial Decision Lab
6. Proactive insights — 7 display groups / 8 event types
7. Explainability — the Evidence drawer
8. Onboarding — three steps
9. Ledger, activity, settings
10. Design system
11. States catalogue
12. Responsive behaviour
13. Accessibility
14. Prototype coverage checklist

---

## 1. Design intent

### 1.1 The brief in one sentence
Foresight is a forward-looking reading of one person's money, written for them, where every figure can be traced back to the transactions and calculations behind it.

### 1.2 Direction: "Broadsheet", grounded in financial documents
The direction comes from documents people already trust with money. These are the **annual report** (the figure on the page, *Notes to the accounts* behind it), the **bank statement** (ruled columns, dated rows, running balance) and the **weekend money pages** (a headline, a standfirst, one chart that makes one argument).

| Borrowed from | Becomes in Foresight | Why it fits |
|---|---|---|
| Annual report notes ("see note 7") | **Receipts**: every computed figure has a dotted underline and a small superscript note marker. Clicking it opens the Evidence drawer, "Notes to this figure". | It makes pillar 3 ("every number has a receipt") visible without adding a panel. |
| Statement rules | Hairline rules separate sections. There is no card grid, and tables are the main structure. | Money is read in rows and columns. Rules carry hierarchy more quietly than boxes. |
| Money pages | The Briefing reads as a dated edition: headline, standfirst, then sections in a fixed order. | It answers "where do I stand?" in sentences before charts. |
| Weather forecast | The forecast is a line with an uncertainty band and a "Today" rule, never a single confident line. | It presents uncertainty honestly and spatially. |

**The signature element is the receipt**: a dotted-underlined figure with a note marker that opens the Evidence drawer. It's what Foresight is remembered by. Everything else stays quiet so that it lands: one accent, no shadows to speak of, no illustration, no gradient.

**Internal review: what changed after challenging the plan.**
- Warm paper + serif + rules is a common editorial default. We keep it because the register mandates it and it's grounded in the subject's own documents. We **don't** use dense newspaper columns: reading text stays ≤ 68 characters wide, and density lives in tables and charts.
- Zero radius everywhere was rejected for controls. Rules and blocks have 0 radius; interactive controls get 4px so they read as touchable rather than printed.
- Serif is used only for edition headlines, section titles and one hero figure per screen. All other figures are Inter tabular, because a serif on every number hurts scanning.

### 1.3 Experience principles
1. **Single account first.** Every screen is designed for one account. Multi-account controls (scope selector, money map, coverage indicator, joint set-up) **appear only when the data has more than one account or a joint account**. A single-account user never sees an empty or disabled version of them.
2. **Sentences first, then charts.** Each surface opens with a plain-language claim, followed by the visual that proves it.
3. **No figure without a receipt.** If a value can't be traced, it isn't shown. We show `—` and the reason.
4. **Time has a grammar.** History is solid ink. Forecast is blue with a band. Simulated is dashed orange. Thresholds are dotted. This holds on every chart, in both themes, at every size.
5. **Precision is honest.** Exact figures (balances, transactions, sums of known items) show pence: £1,284.50, +£116.39. Estimates (forecasts, projections) are rounded to whole pounds: £242. The format itself tells the reader which is which.
6. **The system shows its doubt.** Probabilities, ranges and "checked · 1 revision" are always visible, never buried in a tooltip.
7. **Guidance, not advice.** User-facing copy says advice was **"Checked"** (never "Verified", which implies a guarantee); internal names (Verifier, `VerificationResult`) are unchanged. A persistent footer reads "Guidance, not regulated financial advice (UK FCA / India SEBI)". When the probability of going under the buffer is high, the risk panel signposts free help: MoneyHelper (UK) or a free debt-advice service for the workspace's country.
7. **Use contextual panels before pages.** Evidence, settings and transaction detail open in drawers.
8. **Proactive, not noisy.** There is at most one "Act on this" item at a time.
9. **Straightforward onboarding.** Three steps. Nothing is asked that the data already answers.

---

## 2. Information architecture & navigation

```
┌──────┬──────────────────────────────────────────────────────────────┐
│ F    │ Edition bar                                                  │
│      ├──────────────────────────────────────────────────────────────┤
│ ◉ Br │                                                              │
│ ○ As │   Content column (max 1120px; reading text max 68ch)         │
│ ○ La │                                                              │
│ ○ Le │                                              ┌──────────────┤
│      │                                              │ Evidence     │
│ ⚙    │                                              │ drawer 480px │
│ AN   │                                              │              │
└──────┴──────────────────────────────────────────────┴──────────────┘
 216px rail
```

| Element | Spec |
|---|---|
| **Rail** (216px with labels above 860px; a bottom tab bar at ≤ 860px; matches the prototype) | Wordmark "F" → Briefing · Ask · Decision Lab · Ledger. Bottom: Settings (drawer) and workspace label with a workspace switcher (demo personas). Active: 2px ink bar + `aria-current="page"`. The unread insight count is a small number beside Briefing (not a red dot). |
| **Global ask** | `⌘K` or `/` focuses an Ask bar from anywhere. Submitting opens Ask with the question. |
| **Edition bar** (48px) | Left: surface name (small serif). Right: data freshness ("Data to 11 Oct · Written 10:42"), theme toggle, and **Refresh** when data has changed. **Only for multi-account workspaces**: a scope selector `Mine · Household · account ▾` (when a joint account exists) and a coverage indicator "4 accounts · 1 card we can't see" (§10.12). |
| **Evidence drawer** | Right, 480px. It overlays below 1440px and pushes content at ≥ 1440px. Deep link `?evidence=<id>`. Stack-based: opening a reference inside it pushes, back pops. |
| **Settings drawer** | Same mechanics. |
| **Routes** | `/start`, `/`, `/ask`, `/ask/[threadId]`, `/lab`, `/lab/[scenarioId]`, `/ledger?tab=transactions|review|recurring|statements|activity` (+ `accounts` tab only for multi-account workspaces). |


### 2.1 Workspaces (00 §6c)

A **workspace** is one person's or one household's financial space: its accounts, imports, saved format profiles, goals, forecasts, recommendations and audit log. All data is workspace-scoped (`workspace_id`, `wsp_`).

**Workspace switcher** (rail bottom, above Settings). Label: an initial-letter avatar (monochrome, 28px circle) plus workspace name · country · home currency symbol, with no flags or photos: `Amara · UK · £`, `Aanya · India · ₹`, `Kofi & Hannah · UK · £`. In the ≤ 860px bottom-bar layout it moves to the top bar as the currency symbol in a 32px circle, with the name in the tooltip. Opens a popover list (current one marked with the 2px ink bar), then a rule, then **New workspace** and **Manage workspaces** (rename, export, delete; delete requires typing the workspace name). Switching is a full navigation to that workspace's Briefing; nothing is shared across workspaces.

**New workspace** (popover → small sheet, not a page):
```
 New workspace
 ─────────────────────────────────────
 Name            [ Aanya                     ]
 Country         [ India ▾ ]   sets dates, holidays, categories
 Home currency   [ ₹ INR ▾ ]   pre-filled from country; change if needed
 ─────────────────────────────────────
                       Cancel   [ Create and add statements → ]
```
Country selects the locale pack (`uk`, `in`); v1 offers UK and India country packs only. Home currency remains independently selectable from ISO 4217 currencies; EUR/JPY fixtures exercise currency generality without claiming additional country-specific support. Creating it opens `/start` step ① for the new workspace. Demo workspaces (P1–P3, plus P4 when India ships) are listed under *Try a demo workspace* and are editable, isolated fictional copies that can be reset.

---

## 3. Intelligence Home — the Briefing

### 3.1 Purpose
It answers five questions in a fixed order: **Where do I stand? What changed? What's likely next? Should I act? What is Foresight looking into?** The fixed order is the design: users learn where to look.

### 3.2 Wireframe (desktop, P1 Amara, one Monzo account)

```
Briefing                                                Data to 11 Oct · Written 10:42  ◐  ↻
──────────────────────────────────────────────────────────────────────────────────────────
MONDAY 12 OCTOBER 2026 · AMARA'S EDITION

You'll probably dip under your buffer before payday.               ← serif headline
Food delivery is running 41% above your usual, and the car         ← standfirst
insurance renewal took £410 this month. Pay arrives 28 October.

─ WHERE YOU STAND ────────────────────────────────────────────────────────────────────────
 Balance today¹          Buffer               Until payday         Still to go out
 £1,284.50               £300                 16 days              £693.93²
 Monzo · you told us,    set by you · change  28 Oct (Wednesday)   before payday · 7 bills
 12 Oct

─ WHAT'S LIKELY NEXT ─────────────────────────────────────────────────────────────────────
 [ CashFlowForecastChart: 60 days history (ink) │ Today │ forecast to 28 Oct          ]
 [ blue P50 line + likely range band, dotted £300 buffer, low-point ring on 27 Oct  ]
 Lowest point about £242³ on 27 Oct (likely between £96 and £388).
 78%⁴ chance you'll go below your £300 buffer before payday.

─ WHAT CHANGED ───────────────────────────────────────────────────────────────────────────
 ▲ Food delivery      £286.40⁵ in 30 days · usual £203.10 · +41% · 23 orders            ›
 ◆ TV streaming       NOW Entertainment overlaps your Sky TV · £9.99/mo                   ›
 ○ One-off            Car insurance £410.00 on 9 Oct · not counted as regular spending    ›

─ ACT ON THIS ────────────────────────────────────────────────────────────────────────────
 ┃ Cap food delivery at £180 this month and cancel NOW Entertainment.   CHECKED · 1 revision
 ┃ That's +£116.39⁶ a month. Your chance of going under your buffer
 ┃ before payday falls from 78% to 41%⁷.
 ┃ [ I'll do this ]  [ Try it in the Lab ]  [ Not for me ▾ ]        How was this worked out? ›

─ UNDER INVESTIGATION ────────────────────────────────────────────────────────────────────
 · The long January: December pay arrives early on Fri 18 Dec, and the next on 28 Jan.
   That's 41 days. Likely January low about £900.                                       ›
 · Set a goal. You could build a £1,500 emergency fund by 31 March.                      ›
 · Get a weekly note on Telegram.                                                       ›
 · Check 38 transactions we weren't sure about.                                         ›

 Ask about any of this…                                                                 ⌘K
```

> £693.93 *(04 fixture)* = council tax £162 + LemFi £250 + energy £78 + water £42 + broadband £31 + Sky TV £46 + subscriptions £84.93 still due before 28 Oct. "38 transactions" *(04 fixture)*.

Numbered superscripts are **receipts**. Each opens the Evidence drawer on its `calc_`, `fnd_` or `rec_` record. Note the single-account briefing has no scope selector, no coverage indicator and no account column. They don't exist for Amara.

### 3.3 Caching & regeneration (no LLM call per visit)
The Briefing is a persisted snapshot (`brf_`): deterministic sections plus one LLM-written layer.

| Layer | Source | Recomputed when |
|---|---|---|
| Figures (balance, buffer, days to payday, still to go out) | Persisted `Calculation` values hydrated into the snapshot | On refresh, stored with the prose; reads preserve the edition’s as-of values. |
| Forecast chart & probabilities | Latest `fc_` for current `data_version` | On data change (debounced 30 s) or daily at 06:30 workspace-local time (Europe/London by default). |
| What changed | Latest Analyst run | On data change. |
| Headline, standfirst, finding sentences, investigation lines | LLM via Mesh (Coordinator composition step), referencing IDs only | **Only** on: (1) `data_version` change, (2) a new verified recommendation or InsightEvent, (3) daily 06:30 rollover, (4) a goal or buffer change, (5) Refresh. |
| Act on this | Top-ranked **checked** (Verifier-approved) `rec_` not yet accepted or dismissed | When the recommendation workflow completes. |

**Staleness:** if data changed after the prose was written, the edition bar says "New data since this was written · Refresh". All figures keep the same as-of values as the prose until a new hydrated edition is complete. Old `calc_` references remain immutable and accessible; newer data never replaces a value inside an old sentence.

### 3.4 Interactions
- Finding row → Evidence drawer. `›` → Ask with the finding as context.
- **I'll do this** → accepted, and the buttons are replaced by "Tracking this. We'll check back on 11 Nov." Undo is available for 10 s.
- **Not for me ▾** → *Not relevant · Already doing it · I disagree · Other*. Similar advice is paused for 30 days.
- **Try it in the Lab** → `/lab` with baseline + intervention preloaded.
- Buffer value → inline edit (money input). The forecast probability recomputes without an LLM.
- Under-investigation prompts (goal, Telegram, review) open their drawers or pages in place. This is where onboarding's deferred items live.

### 3.5 Variants
- **Relative mode** (no balance given): "Balance today" shows `—`, "add today's balance to see this". A "Change by payday **+£1,862**" *(illustrative)* metric replaces it. The probability is hidden.
- **Too little history** (< 45 days): "Foresight needs about 6 weeks of history to forecast reliably. You have 23 days." History only, no forecast drawn.
- **Stale statement** (monthly PDF users): caution line "Your latest statement ends 30 Sep. Add October's for an up-to-date forecast." The band widens from the anchor date.
- **Nothing to act on**: "Nothing needs your attention. Your forecast stays above your buffer through 26 Nov." This is a real state, not an empty one.
- **Multi-account (P3)**: the scope selector and coverage indicator appear in the edition bar. "Balance today" sums cash accounts in scope, with a per-account breakdown in its receipt. Household scope uses household language (§10.12).
- **No regular income found** (00 §6a; fixture `S14-side-account`, a single side account funded only by top-ups and PayPal). Spec in §3.6.

### 3.6 No regular income found, and money in we can't confirm

Defined by 00 §6a "Inflows we can't confirm". Figures below are *(04 fixture)*, fictional.

Fixture: fictional **Sam Patel**, one Revolut-style side account (test dataset `S14`). The prototype `design/prototype/states.html#no-income` renders exactly these figures.

```
Briefing · Sam Patel · Revolut account                 Data to 11 Oct · Written 10:42  ◐  ↻
──────────────────────────────────────────────────────────────────────────────────────────
MONDAY 12 OCTOBER 2026

We didn't find regular income in this account.                     ← serif headline
Money comes in as top-ups from your own name, payments from one     ← standfirst
person and occasional PayPal transfers. None of it looks like pay,
so none of it counts as income. The forecast below only assumes
money that has arrived regularly.

  ┌ caution rule ───────────────────────────────────────────────────────────────────────┐
  │ [ Add the account your pay goes into ]  [ Tell us your take-home ]  Continue without income │
  └─────────────────────────────────────────────────────────────────────────────────────┘

─ WHERE YOU STAND ────────────────────────────────────────────────────────────────────────
 Balance today¹          Lowest point ahead²            Income found
 £212.40                 £78 · 14 Dec                   £0
 from statement 11 Oct   below your £100 buffer         no pay-like money in · 12 months

─ WHAT'S LIKELY NEXT ─────────────────────────────────────────────────────────────────────
 [ CashFlowForecastChart: history ink │ Today │ forecast + band │ buffer £100 dotted ]

─ MONEY IN · LAST 30 DAYS ────────────────────────────────────────────────────────────────
 Income (pay, benefits, tax refunds)                                  £0.00
 From your other account · S PATEL, 1st and 15th                    £300.00   not income · Add that account ›
 Other money in (not confirmed) · T. OKAFOR £200, PayPal £85        £285.00   not income, never relied on by advice

─ THIS FORECAST ASSUMES ──────────────────────────────────────────────────────────────────
 Top-ups of £150 from your other account continue, 1st and 15th      own transfer · repeated 8 times
 £200/mo from T. Okafor continues, around the 20th                   unconfirmed · repeated 5 times  [ Don't assume this ]
 PayPal transfers are not projected                                  irregular · 4 since July
 Everyday spending about £18 a day                                   last 90 days

 If T. Okafor's £200 stopped, the 14 Dec low would be about −£122. Foresight won't call
 anything affordable because of money it can't confirm (V-19).
```

Rules:
- The three options are equal-weight text buttons, not a modal. They stay on the Briefing until one is chosen or **Continue without** is pressed; after that, a single line remains in Under investigation ("No income in this account · change").
  - *Add the account your pay goes into* → `/start` step ① with this account kept.
  - *Tell us your take-home* → inline money + date fields ("after tax", payday rule chips: *Same date each month · Last working day · Every 4 weeks*). The stream is stored `declared` and shown with the DECLARED badge.
  - *Continue without income* → the forecast keeps only recurring inflows already seen (here: own top-ups and T. Okafor, each listed under "This forecast assumes"); the panel collapses to one line.
- The lowest point is compared with the buffer if one is set; otherwise with £0.
- No advice relies on unconfirmed money (V-19); "Act on this" may still show spending interventions.

**"Other money in (not confirmed)"** appears wherever income is summarised (Briefing receipts, Ask metric groups, Ledger totals) as its own line, never summed into income:
```
 Income                            £2,940.00
 Other money in (not confirmed)      £285.00   2 payments this month · review ›
```

**Forecast assumptions** (Evidence drawer → Assumptions, and Lab ⓘ) list every projected unconfirmed inflow with an off switch:
```
 ASSUMED, NOT CONFIRMED
 £200.00 a month from T. OKAFOR continues · seen 5 times, around the 20th   [ Don't assume this ]
```
Turning it off re-runs the forecast without it (no LLM) and records the choice on the `Counterparty`.

---

## 4. Ask (the brief's "Agent Workspace"; not to be confused with a user workspace)

### 4.1 Layout

```
Ask                                                                       ◐
──────────────────────────────────────────────────────────────────────────────
 THREADS              │                     Why am I always skint before payday?
 · Skint before…  ●   │
 · Subscriptions      │  ┌ Analyst ✓ · Forecaster ✓ · Advisor ⇄ Verifier ✓ (1 revision) · 9.4s ┐
 · Flights home       │
                      │  In each of the last three months your balance bottomed out in the
 + New thread         │  4 days before payday. The main change is food delivery: £286.40¹ in
                      │  30 days, 41% above your usual £203.10². Car insurance (£410.00, a
                      │  one-off) made October tighter still.
                      │
                      │  [ CashFlowForecastChart — last 3 pay cycles + this one, buffer line ]
                      │  [ SpendingBreakdownChart — ranked bars, Food delivery highlighted   ]
                      │
                      │  ┃ Cap food delivery at £180 + cancel NOW Entertainment
                      │  ┃ +£116.39/mo · buffer risk 78% → 41%         CHECKED · 1 revision
                      │  ┃ [ Try in the Lab ]  [ Evidence ]
                      │
                      │  Sources  fnd_01JA… · calc_01JA… · fc_01JA… · rec_01JA…
                      │
                      │  ( Show the 23 orders )  ( Try the cap in the Lab )  ( What if I cancel Disney+ too? )
                      │ ┌──────────────────────────────────────────────────────────────┐
                      │ │ Ask about your money…                                ↵ Send │
                      │ └──────────────────────────────────────────────────────────────┘
```

- Thread list: 240px, collapsible. Threads are persisted, and reopening one renders stored `rsp_` snapshots **without re-running agents**.
- Response column: max 760px. Charts may extend to 920px.
- User messages: right-aligned, ink-2, no bubble, with a 1px rule above. Responses have no avatar. The agent strip names the authors.

### 4.2 Response anatomy (fixed order, chosen blocks)
1. **AgentExecutionTimeline**, collapsed to one line: agents, revision count, total time.
2. **Narrative**: 2–4 sentences, figures as receipts. The first sentence answers the question.
3. **0–3 data blocks** (composition rules §4.4).
4. **InterventionCard**, only if checked (Verifier-approved) recommendations exist.
5. **Sources line** (mono IDs, each clickable).
6. **Follow-up chips** (max 4).

### 4.3 Interacting with generated blocks
Every data block has the same three actions, reachable from a mark or row on hover or focus, or from the block's `⋯`:

| Action | Behaviour |
|---|---|
| **Show transactions** | Inserts a TransactionTable **below the block** for that slice. Deterministic query, no LLM. |
| **Ask about this** | Prefills the composer with a context token ("About: Food delivery · 12 Sep–11 Oct") carrying `finding_ref` / `calc_ref`. |
| **Open evidence** | Evidence drawer on the block's primary reference. |

Charts also have a crosshair tooltip (date, likely range, P50), legend toggles and **Copy as table**. ScenarioComparison has **Open in the Lab**. TransactionTable has sort, column filters and inline category change. **Follow-up chips** use `FollowUpAction{action_id, label, kind, payload, requires_confirmation}` (`08` §3.4) and generated from the response's references, so every chip targets real data.

### 4.4 Block composition rules

| Question shape | Required | Optional (max 2) | Never |
|---|---|---|---|
| "Where did my money go / how much on X" | Narrative, FinancialMetricGroup | SpendingBreakdownChart, TransactionTable | CashFlowForecastChart |
| "Why am I short / what happens next" | Narrative, CashFlowForecastChart | SpendingBreakdownChart, RiskAssessment, InterventionCard | — |
| "Can I afford X / what if" | Narrative, ScenarioComparison | GoalProjection, RiskAssessment, InterventionCard | SpendingBreakdownChart |
| "Am I on track for my goal" | Narrative, GoalProjection | InterventionCard, CashFlowForecastChart | — |
| "Show me transactions…" | TransactionTable | FinancialMetricGroup | Narrative > 1 sentence |
| "Why did you recommend…" | Narrative, EvidencePanel | AgentExecutionTimeline (expanded) | New InterventionCard |

Plan validation allows 1–8 blocks and at most one CashFlowForecastChart plus one ScenarioComparison; hydration may append evidence/fallbacks up to 10 blocks (`08` §4/§6). The 0–3 data-block layout above is the normal presentation target, not a competing schema limit.

### 4.5 Streaming
- Agent strip updates live (`aria-live="polite"`): "Analyst reading 214 transactions…" → ✓.
- Narrative streams. Only validated text segments stream. Value placeholders stay as skeletons until hydration; no unvalidated numeric literal reaches the user. Completed values gain the receipt underline.
- Data blocks show a skeleton with **final geometry** and fill when hydrated. A chart never draws half a series.
- **Stop** replaces Send while running and aborts server-side: "Stopped. No completed response was saved; completed steps and audit records remain."

### 4.6 Empty Ask
Starters come from current data: "Why am I skint before payday?", "Which subscriptions overlap?", "Can I afford £640 in December?", "How's my emergency fund doing?". One line states the boundary: "Foresight looks at your spending and cash flow. It doesn't give investment, tax or regulated financial advice."

---

## 5. Financial Decision Lab

### 5.1 Layout (P1, flights scenario)

```
Decision Lab                                                              ◐
──────────────────────────────────────────────────────────────────────────────────
 SCENARIOS           │  Flights home for Christmas                     Saved · scn_01JA…
 · Baseline          │
 · Flights home   ●  │  Describe a decision…        [ Add a change ▾ ]               [ Run ]
 · Pay 5 days late   │  ┌────────────────────────────────────────────────────────────┐
 · Rent +£60         │  │ ONE-OFF  £640.00 · 1 Dec 2026 · Travel                   ✕ │
 + New scenario      │  └────────────────────────────────────────────────────────────┘
                     │  Assumptions: everyday spending as the last 90 days · pay on the
 TEMPLATES           │  28th or the working day before; December on Fri 18 Dec · 500 paths ·
 · Big purchase      │  seed 0x4F1C                                                       ⓘ
 · Pay delayed       │
 · Income drop       │  [ ScenarioComparison: Oct → Mar                                    ]
 · Rent change       │  [ baseline blue + band · with flights dashed orange · buffer dotted ]
 · Cut spending      │  [ "41 days" bracket 18 Dec → 28 Jan · goal flag 31 Mar             ]
 · Goal impact       │
                     │                            Baseline        With flights     Change
                     │  December low              £1,050 17 Dec   £410 17 Dec      −£640
                     │  January low               £900 27 Jan     £260 27 Jan      −£640 · below buffer
                     │  Emergency fund 31 Mar     £1,592          £952             £548 short
                     │  Goal status               On track        Behind
                     │
                     │  You can pay for the flights in December. The squeeze comes later:
                     │  after December's early payday your balance is likely to dip to about
                     │  £260 before 28 January, below your £300 buffer.
                     │
                     │  MAKE IT WORK                                                  Checked
                     │  [✓] Cap food delivery at £180 + cancel NOW     +£116.39/mo
                     │      January low with flights                  ≈ £493 · above buffer
                     │      Emergency fund with flights + change      ≈ £1,418 · £82 short
                     │  [ ] Move the goal date to 30 April            goal on track
                     │                                                   [ Save combination ]
```

> Goal figure with the change (*04 fixture*, same convention as the £493 January low: the saving accrues per month from November, so 4 months by the 25 Mar pre-payday low): £952 + 4 × £116.39 ≈ £1,418, still £82 short; moving the date to 30 Apr adds a further month. > "Pay 5 days late", "Rent +£60" are saved-scenario names *(04 fixtures)*. The goal-date option's outcome must come from the engine, so the prototype shows it without a number.

### 5.2 Scenario building
- **Describe a decision** → the Forecaster parses it into a `ScenarioSpec`, shown back as editable chips. **Nothing runs until Run.** Assumed values are marked "Assumed" on the chip.
- **Add a change ▾** (structured, no LLM): one-off out · one-off in · pay delayed (days) · income change (% or £, from date, for how long) · bill change (add / change / cancel, picked from detected bills) · category cap or cut · goal change.
- Chip grammar: TYPE in small caps · amount in tabular figures · date · target.
- **Templates** cover the six brief scenarios: holiday/purchase affordability, pay delayed, temporary income loss, rent increase, purchase vs goal, and best combination of spending changes.
- **Guardrail**: family support abroad never appears in "Cut spending" templates or suggestions unless the user adds it themselves.

### 5.3 Comparison
- Up to **3 scenarios + baseline**. The third simulated series uses dash `2 3` as well as colour. A fourth is refused ("Compare up to three").
- Fixed metrics: each pre-payday low in the horizon (with date), days under buffer, probability of going under the buffer, end-of-horizon P50, goal status. **Change** is written in words ("£640 lower", "below buffer") and never relies on colour alone.
- The verdict kind and core wording are computed deterministically over the whole horizon (`08` §5.4); any additional LLM explanation uses computed metric references. It never gives yes/no without the condition.

### 5.4 Make it work
The Advisor proposes options and the Verifier checks each one. Each option is a toggle row with its own simulated effect. Toggling recombines **deterministically** (engine call, target < 1.5 s P95 for a 90-day simulation (NFR-02; longer horizons measured separately)). The combined effect is recomputed, never summed, because effects interact.

### 5.5 Assumptions (ⓘ)
Opens the Evidence drawer on the simulation's `calc_`. It shows engine version, seed, horizon, paths, bills included, the everyday-spending model (block bootstrap over 90 days), the pay calendar (including the early December rule), one-offs excluded, and user overrides. **Reproduce** copies the planned `python -m backend.finance_core.simulate --scenario scn_… --seed <stored-seed>` command; `0x4F1C` is a prototype annotation, not the generator seed.

### 5.6 Multi-account (P3 only)
Each scenario stores its scope (Mine / Household / account), shown as its first chip `SCOPE Household`. Only scenarios with the same scope can be compared.

---

## 6. Proactive insights — 7 display groups / 8 event types

All proactive communication is an **InsightEvent**, surfaced in three places with decreasing weight:
1. **Briefing** "New since your last visit" band (max 3 rows, dismissible).
2. **Rail** count.
3. **Digest** (only the single highest-severity checked item).

There are no toasts for proactive events. Toasts are only for confirming the user's own actions.

| Event | Marker (glyph + word) | Copy pattern (P1) | Primary | Secondary |
|---|---|---|---|---|
| **New risk detected** | ▲ RISK (negative) | "78% chance you go below your £300 buffer before 28 Oct." | See what's driving it | Open in the Lab |
| **Behaviour changed** | ◆ CHANGE (ink) | "Food delivery is 41% above your usual this month." | Show transactions | Ask about this |
| **Forecast updated** | ↻ UPDATED (accent) | "Forecast updated with 38 new transactions. Your lowest point moved from £315 to £242." *(04 fixture: £315)* | Compare with previous | — |
| **Recommendation generated** | ● NEW ADVICE (accent) | "Checked suggestion: cap delivery at £180 + cancel NOW, +£116.39 a month." | View | Not for me |
| **Rejected / revised** | ⟲ REVISED (caution) · ⊘ WITHDRAWN (ink-3) | "We revised a suggestion before showing it. The first version asked for a cut that's unrealistic for you." / "We withdrew a suggestion we couldn't verify." | See both versions | — |
| **Goal at risk** | ▲ GOAL (caution) | "Emergency fund: £548 short of £1,500 by 31 March if you book the flights." | See options | Edit goal |
| **Intervention worked** (outcome confirmed; behind flag `intervention_outcome`, off until `10` PRO-04's check is green) | ✓ CONFIRMED (positive) | "Since 12 Oct, food delivery averaged £172 a month, under your £180 cap. Your pre-payday low improved." *(04 fixture: £172)* | See the comparison | — |

Rules: severity orders the list (risk > goal > revised/withdrawn > new advice > change > updated > confirmed). Events are shown once per `data_version` and collapse when superseded. If an accepted change didn't happen, the message is neutral ("Food delivery is still around £280. Want to try a different approach?"): no guilt, no streaks. **Betting insights are opt-in only** (Settings → Insights) and always neutral in tone.

---

## 7. Explainability — the Evidence drawer

### 7.1 Structure ("Notes to this figure")

```
┌ Notes to this figure ─────────────────────────────── ✕ ┐
│ ← back                                                  │
│ +£116.39 a month                          (serif, 28)   │
│ Expected effect of: cap food delivery at £180 and       │
│ cancel NOW Entertainment.                               │
│ rec_01JA9… · Checked 10:42 · after 1 revision           │
│                                                         │
│ [Reasoning] [Calculation] [Data] [Verification] [Run]   │
│ ─────────────────────────────────────────────────────── │
│ REASONING                                               │
│ 1 Finding   Food delivery £286.40 vs usual £203.10 ›    │
│ 2 Finding   NOW Entertainment overlaps Sky TV ›         │
│ 3 Forecast  78% chance below £300 before 28 Oct ›       │
│ 4 Simulated with this change → 41% ›                    │
│                                                         │
│ CALCULATION                                             │
│ Food delivery   286.40 − 180.00   =  106.40             │
│ NOW Entertainment                 =    9.99             │
│ Monthly effect                    =  116.39             │
│ Inputs: food delivery (DETECTED) · NOW (CONFIRMED)      │
│ calc_01JA… · engine 0.3.0 · inputs a41f… ⧉              │
│                                                         │
│ DATA  23 transactions · 12 Sep–11 Oct    [table ›]      │
│                                                         │
│ VERIFICATION  2 passes                                  │
│ Pass 1 ✕ Rejected                                       │
│   Cap of £90 is 56% below your usual (limit 40%).       │
│   Claimed +£220, recomputed +£196.40.                   │
│ Pass 2 ✓ Approved · 5 of 5 checks                       │
│                                                         │
│ RUN  run_01JA… · 6 agents · 9.4 s                       │
└─────────────────────────────────────────────────────────┘
```

### 7.2 Tabs

| Tab | Answers | Content |
|---|---|---|
| **Reasoning** | Why was this said? | Ordered chain: findings → forecast → simulation → recommendation. Each link pushes that record onto the stack. |
| **Calculation** | How was the number made? | Readable arithmetic for simple calcs, method summary and parameters for forecasts, engine version, seed, inputs hash, copyable reproduce command, and a **provenance badge on each input** (DETECTED / CONFIRMED / DECLARED). |
| **Data** | Which transactions? | The exact set (count, range), opening as a TransactionTable, plus the source file, its detected format and its reconciliation status. |
| **Verification** | Did anything check this? | Every Verifier pass with each check (refs exist · impact recomputed · feasibility · specificity · tone), pass/fail, critique, and claimed vs recomputed figures. Drafts side by side. |
| **Run** | What ran, and when? | Expanded AgentExecutionTimeline: steps, models (via Mesh), durations, retries, tokens. Visible to every user, not hidden behind a debug flag. |

Tabs that don't apply are omitted.

---

## 8. Onboarding — three steps (`/start`)

### 8.1 Model
**① Drop your statements → ② Check what we found → ③ Your briefing.** That's the whole thing. The step indicator always shows three steps. Column confirmation, gap questions and (for multi-account data) the money map and joint set-up live **inside** step ①/② when needed. They never add steps.

Deferred to the Briefing, never forced: goals, digest channel, low-confidence categorisation review.

Never asked: anything the file already shows (bank, account type, income, bills), gross salary, NI number, date of birth, bank login.

### 8.2 ① Drop your statements

```
FORESIGHT                                                              ① ─── ② ─── ③

See where your money is heading.
Foresight reads your statements, forecasts the next 90 days, and checks its own
advice before showing it to you.

  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐
  │  Drop your bank statements here                                      │
  │  CSV or PDF. One file is fine. Most banks let you download a CSV     │
  │  from the app under Statements or Export.        [ Choose files ]   │
  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘

  monzo-2025-2026.csv   Detected format: Monzo CSV · current account · 1,163 transactions
                        13 Oct 2025 – 11 Oct 2026  ✓ Read · balance not in file

                                                                 [ Continue ]
  Try a demo workspace  ·  Add transactions by hand
  Your data stays in this workspace. Foresight can't move money.
```

**Per-file status row** (one per file) is the only feedback pattern in step ①:

| Status | Copy | Visual |
|---|---|---|
| Reading | "Reading…" with the row count rising | ink-3 text, no spinner wheel, a thin progress rule under the row |
| Read (CSV) | "✓ Read · 1,163 transactions · 13 Oct 2025 – 11 Oct 2026" | ✓ ink |
| Reconciled (PDF / CSV with balance) | "✓ Reconciled · running balance and totals match" | ✓ positive + word |
| New layout (CSV or PDF) | "Detected format: new layout · Confirm your columns (one time only)" → the row expands into the column confirm (below) | caution ◆ |
| Low confidence (PDF without running balance) | "Totals match, but rows can't be checked one by one. We'll ask you to look over them." | caution ◆ |
| Rejected | "Couldn't verify this statement: rows don't add up to the closing balance (£— difference). Nothing was imported from it." · *See the rows* · *Try a CSV instead* | ✕ negative + word |
| Duplicate | "Already imported. Skipped." | ink-3 |
| Password | "This PDF is password-protected." [password field] "Opened here, not stored." | — |

**Detected format.** Every file row names its detected format ("Monzo CSV", "Revolut statement · 2 pockets", "Nationwide PDF", "Starling CSV (saved by you)"). Behind it there are only two importers, `csv_statement` and `pdf_statement`. Banks are recognised by saved **format profiles**, not bank-specific code.

**Confirm columns** (one time per new layout, inline in the file row). The Ledger Agent proposes the column roles from the redacted header and digit-masked sample rows. The user confirms once, and the profile is saved for next time:
```
  starling-export.csv   Detected format: new layout · CSV   ◆ Confirm your columns (one time only)
  ┌──────────────┬──────────────────────────────┬────────────┬────────────┐
  │ [Date ▾]     │ [Description ▾]              │ [Amount ▾] │ [Balance ▾]│
  │ 03/10/2026   │ TESCO STORES 2041            │ −23.40     │ 1,402.18   │
  │ 02/10/2026   │ HALDEN STUDIO LTD            │ 2,400.00   │ 1,425.58   │
  └──────────────┴──────────────────────────────┴────────────┴────────────┘
  Dates read as day/month (we saw 28/09).  Name this format [ Starling CSV ] (so we recognise it next time)
                                                              [ Looks right ]
```

### 8.3 ② Check what we found (P1)

```
Here's what we found. Tap ✓ if it's right.                         ① ─── ② ─── ③
Everything here is optional. You can change it later.

YOUR PAY
  £2,940.00   NORTHGATE SYSTEMS LTD · on the 28th, or the working day before  DETECTED  ✓ ✎
              December: paid early on 18 Dec (seen last year)

YOUR MAIN BILLS
  £1,395.00   Rent · standing order · 1st                                      DETECTED  ✓ ✎ ✕
  £162.00     Council tax · direct debit · 15th · April to January             DETECTED  ✓ ✎ ✕
  £197.00     Energy £78 · water £42 · broadband £31 · Sky TV £46              DETECTED  ✓ ✎
  £84.93      7 subscriptions (show)                                           DETECTED  ✓ ✎

MONEY YOU SEND HOME
  ~£250/mo    LemFi · family support abroad                                    DETECTED  ✓ ✎
              We treat this as a commitment and won't suggest cutting it.

ONE-OFFS WE'LL LEAVE OUT OF YOUR USUAL SPENDING
  £410.00     Car insurance · 9 Oct                                                      ✓ ✎

ONE QUESTION
  What's in your Monzo account today?
  Monzo exports don't include a balance.   £ [ 1,284.50 ]   Skip, show changes instead
                                                                  [ See my briefing ]
```

Rules:
- At most **one screen**. Sections appear only if detected. Gap questions appear only if the data has a gap (max 3).
- ✓ sets `confirmed`. ✎ opens an inline edit (declared values get a DECLARED badge). ✕ marks "not a bill". Ignoring everything is allowed: detected items stay `detected`.
- Other gap questions, using the same pattern: "We didn't see regular pay. What do you take home each month, and when? (after tax)", "Your latest statement ends 30 Sep. What's in the account today?".
- **Money in we can't place** (00 §6a ladder step 7), at most 3, ranked by total amount, inside the same QUESTIONS section. Fixture `S13-unconfirmed-inflows` *(04 fixture figures)*:
  ```
  WHAT IS THIS MONEY?
    £200.00 × 4   T OKAFOR · on the 1st
                  [Salary/income] [From my other account] [Partner/household] [Paid back] [Refund] [Other]
    £300.00       PAYPAL *JSMITH · 14 Sep           (same chips)
    £85.00        J ADEYEMI · 2 Oct                  (same chips)
                                        2 more in Ledger → Review
  ```
  One tap answers it (no confirm step); the answer is saved on the `Counterparty` and applies to past and future rows. *Paid back* links to the nearest matching spend if one exists. Unanswered rows stay **not confirmed**: counted in the balance, excluded from income, projected only if recurring (shown under "Assumed, not confirmed").
- **Multi-account data only** (P3): two extra sections appear in this same screen.
  - **How your money moves**: the **money map**, a left-to-right flow of income → accounts → destinations with £/month edge labels. Each own-transfer link has ✓ / "not mine".
  - **Shared account**: "Is the Nationwide account joint?" → arrangement chips (*Household pot* (default) · *Equal share* · *% share* · *Fixed contribution*) + required consent tick "This account includes Hannah's transactions, and she's agreed to me adding it." Joint rows remain staged locally until consent, before any commit or Mesh call. Card and untracked-account gap questions ("Your Capital One card is paid from two of your accounts. Add its statement?") join the ONE QUESTION section, which is then titled "A FEW QUESTIONS".

**Money map spec** (P3 only): an SVG flow with three columns (*Money in* · *Your accounts* · *Where it goes*), nodes as text labels with a 2px left rule, edges as 1px `--ink-3` curves whose width encodes £/month (1–6px, log-scaled). Untracked destinations are drawn with a dotted outline and labelled "can't see". It is not a Sankey with colour fills. It's monochrome so the labels carry it. A text table equivalent is always available.

### 8.4 ③ Your briefing
This is the Briefing (§3) with a one-time intro line, and the buffer metric in edit-ready state: "Keep at least **£300**? Amara’s chosen buffer. Change it". Deferred items appear under "Under investigation".

### 8.5 Alternatives
- **Try a demo workspace** → persona list (Amara first: "One account. The simplest start."), then the analysing timeline.
- **Add transactions by hand** → a statement-style row editor (date · description · amount · in/out · category suggested live). Tab moves across and Enter adds a row. The "Today's balance" field at the top is the anchor.
- **Analysing** (between ① and ②, and for the demo) is the full AgentExecutionTimeline, rows appearing with a 120 ms fade. It's the only choreographed motion in the product, because it's the user's first sight of the agents.


### 8.6 Currency & number-format confirmation (00 §6c)

Currency and formats are detected per file, shown on the file row, and asked about **only when ambiguous**:
- **Detected, no question:** "Detected: **£ GBP · 1,284.50 · dd/mm/yyyy**" or "Detected: **₹ INR · 1,15,000.00 · dd-mm-yyyy**" (`micro`, ink-2; *change* link opens the chips below).
- **Ambiguous currency** (`$`, `kr`, `¥`, or no symbol and no currency column with a home currency mismatch): a chip row inside the file row, "Amounts use **$**. Which currency?" → *US dollar · Canadian dollar · Australian dollar · Other…*. The batch stays `needs_review` (not committed) until answered; the answer is saved on the format profile.
- **Ambiguous date order** (no day above 12 anywhere in the file): "Is 03/04/2026 **3 April** or **4 March**?" with two chips. Same saving rule.
- **Ambiguous decimals** (`1.234` could be one thousand or one point two): shown only if no row disambiguates; two chips with a worked example from the file.
- In step ② these appear at the top of *Check what we found* if they were skipped in step ①, counting towards the "three questions at most" budget.

---

## 9. Ledger, activity, settings

**Ledger** (`/ledger`) is one page with tabs:

| Tab | Content |
|---|---|
| Transactions | TransactionTable (§10.8) with filters (category, date, amount, payment type, "needs review") and narration search. Row → transaction **drawer** (raw narration, payment-type code, merchant, categorisation reason & history, source file, notes). |
| Review | The deferred categorisation review: grouped by merchant, low confidence first, showing *why*. Bulk "accept the rest". Corrections teach merchant memory and show "Applied to 6 similar transactions · Undo". Payments to people get quick picks. |
| Recurring | Bills, subscriptions, income and commitments: name, amount (median), cadence, next date, confidence, **provenance badge**, status (active / price changed / possibly ended). Users can mark a subscription **unused**, the only way Foresight learns usage. |
| Statements | Import history: file, detected format, range, rows, duplicates, reconciliation result, status. Saved format profiles are listed here too (rename / forget). Actions: view rows, **undo import** (forecast recomputes), *Add statements* (the step ① drop zone in a drawer). |
| Activity | Analyses run, briefings written, recommendations (generated / checked / revised / withdrawn / accepted / dismissed), digests sent, settings changed. Each row links to evidence. Prior Ask threads and saved scenarios are filterable here. |
| Accounts *(multi-account only)* | Bank, type, ownership & arrangement, tracked/untracked, last data date, latest balance. Actions: add statement, edit arrangement, say what an untracked account pays for. |

**Settings** (drawer): Workspace (name, country → locale pack, home currency) · Pay (confirmed/declared, after-tax only) · Buffer (suggested: one month of essential bills) · Goals · Digest (Telegram/email, schedule, *Send a test*) · Insights (opt-in: betting & gaming) · Data (export all as CSV + JSON; delete with typed confirmation) · Security (sessions, sign out) · About the engine (version, models via Mesh, link to evaluation report).

---

## 10. Design system

### 10.1 Colour tokens
Semantic names map to register §9 values, including the measured amendments.

```css
:root {                         /* Day edition: always defined unconditionally */
  --paper:#F6F3EC; --paper-raised:#FBF9F4; --paper-sunk:#EFEBE2;
  --ink:#16181D;   --ink-2:#4A4E57;  --ink-3:#6B6E75;
  --rule:#DAD5C9;  --rule-strong:#867F70;
  --accent:#1F4FD1; --accent-hover:#183FA8; --accent-tint:#E4EAF8; --accent-contrast:#FFFFFF;
  --simulated:#B4531F; --simulated-tint:#F5E6DC;
  --positive:#1E7A4F; --negative:#B3261E; --caution:#8F5A00;
  --series-history:var(--ink); --series-forecast:#1F4FD1; --series-simulated:#B4531F;
  --band-forecast:rgba(31,79,209,.14); --band-simulated:rgba(180,83,31,.12);
  --focus:#1F4FD1;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { /* Night values below */ } }
:root[data-theme="dark"] {      /* Night edition: duplicated inside the media block above */
  --paper:#0F1115; --paper-raised:#161920; --paper-sunk:#0A0C0F;
  --ink:#ECE8DF;   --ink-2:#B5B2AA;  --ink-3:#8E8C86;
  --rule:#2A2D34;  --rule-strong:#666973;
  --accent:#7EA2FF; --accent-hover:#9DB8FF; --accent-tint:#1B2440; --accent-contrast:#0F1115;
  --simulated:#F0915A; --simulated-tint:#33221A;
  --positive:#4FC08D; --negative:#FF7A6E; --caution:#E6B04A;
  --series-history:var(--ink); --series-forecast:#5F86F2; --series-simulated:#D9733A;
  --band-forecast:rgba(95,134,242,.20); --band-simulated:rgba(217,115,58,.16);
  --focus:#7EA2FF;
}
```

**Measured contrast against `--paper`** (WCAG 2.x):

| Token | Day | Night | Allowed use |
|---|---|---|---|
| `--ink` | 16.0 | 15.5 | All text |
| `--ink-2` | 7.5 | 8.9 | Secondary text, labels |
| `--ink-3` | 4.6 | 5.6 | Captions, axes, metadata |
| `--accent` | 6.1 | 7.7 | Links, primary buttons, forecast text |
| `--simulated` | 4.5 | 8.0 | Simulated labels (≥ 14px in Day) |
| `--positive` / `--negative` / `--caution` | 4.8 / 5.9 / 5.2 | 8.3 / 7.4 / 9.6 | Status text, always with glyph + word |
| `--rule` | 1.3 | 1.4 | Decorative hairlines only |
| `--rule-strong` | 3.6 | 3.4 (3.2 on raised) | Input borders, control outlines |

**Chart marks** were validated with the dataviz palette validator. Day forecast `#1F4FD1` and simulated `#B4531F` pass the lightness band, chroma, CVD separation (worst ΔE 28.2, protan) and ≥ 3:1. Night `#5F86F2` and `#D9733A` pass everything (worst ΔE 26.6). History is neutral ink by design: it's fact, not a category.

**Colour rules:** one accent (blue) is used for forecast and primary action. Orange is used **only** for simulated data and scenario chips. Status colours always come with a glyph and a word. **Spending categories are not colour-coded**: breakdowns are single-hue ranked bars, so no categorical palette is needed.

### 10.2 Typography
Faces: **Newsreader** (display, optical size), **Inter** (UI & figures, `font-feature-settings: "tnum" 1, "cv11" 1`), **JetBrains Mono** (IDs, raw narrations, reproduce commands). Inter Tight is used for the wordmark only. Weights: 400, 500, 600.

| Token | Face | Size / line-height | Weight | Use |
|---|---|---|---|---|
| `display` | Newsreader | 44 / 48 | 500 | One hero per screen (Briefing headline ≥ 1024px, Lab verdict figure) |
| `title` | Newsreader (headings) · Inter tnum (metric values) | 28 / 34 | 500 | Screen and drawer titles, mobile headline; metric values in Inter |
| `lead` | Newsreader | 20 / 30 | 400 | Standfirst, verdicts |
| `body` | Inter | 16 / 24 | 400 | Narrative, descriptions |
| `ui` | Inter | 14 / 20 | 400·500 | Tables, controls, labels, chips |
| `micro` | Inter | 12 / 16 | 500, +4% tracking, small caps for kickers | Section kickers, axes, metadata, mono IDs |

That's six sizes in total.

**en-GB formatting:**
- Currency `£1,284.50`. Thousands separator is a comma, decimal is a point.
- Exact figures keep pence. Estimates are whole pounds (principle 5).
- Negative values use a true minus `−£23.40` (U+2212), never a hyphen and never brackets.
- Credits get an explicit `+`.
- Dates: `12 Oct`, plus the year only when it differs or for goals (`31 Mar 2027`). The weekday appears where it matters ("Fri 18 Dec").
- Percentages: whole numbers, except below 10% (`4.2%`).
- Ranges in words: "likely between £96 and £388".
- Probabilities: "78% chance".
- Spelling: en-GB (categorise, colour, cheque).

### 10.3 Spacing, grid, radius, elevation, motion
- Base unit **4px**. Scale: 4, 8, 12, 16, 24, 32, 48, 64, 96. Briefing sections are 48 apart, Ask blocks 32. Table rows are 44 (comfortable) or 36 (compact).
- 12 columns with 24px gutters in a 1120px content column. Metric groups are 4-up, 2-up on tablet, and stacked on mobile.
- Radius: **0** for rules, blocks, tables and the drawer. **4px** for inputs, buttons, chips and badges. **999px** only for the theme toggle.
- Elevation: none in content. The drawer is the only element with a shadow (`0 0 0 1px var(--rule), -12px 0 32px rgba(0,0,0,.08)`), and in Night it has the rule only.
- Motion: 120–150 ms ease-out, used only for entrances of new content and the drawer slide. It is disabled under `prefers-reduced-motion`.

### 10.4 Navigation components
Rail item: 20px icon + `micro` label, 44px target, active ink bar. Edition bar. Tabs: 2px ink underline, `role="tablist"`. Drawer header: back, title, close. There are no breadcrumbs, because the drawer stack replaces them.

### 10.5 Section kicker
A `micro` small-caps label in ink-2 followed by a 1px `--rule` filling the width. This is the main structural device, and it replaces cards.

### 10.6 FinancialMetricGroup
2–4 metrics separated by 1px vertical rules. Each has a label (`micro`, ink-2), a value (`title`, Inter 500 tnum, receipt underline), a context line (`ui`, ink-3, includes provenance where relevant: "you told us, 12 Oct"), and an optional delta (glyph + signed value + word: "▲ £83.30 more than usual"). A missing value is `—` with the reason in the context line.

### 10.7 Charts & timelines
Anatomy: no chart border, horizontal gridlines only (max 4, `--rule`), y labels `micro` ink-3 (`£1k`), date x-axis, direct labels at line ends, and a word legend above when there are 2 or more series. Crosshair tooltip on hover and focus, keyboard-steppable by day (←/→). Each chart has **Copy as table** and an off-screen `<table>`.

| Chart | Encoding |
|---|---|
| **CashFlowForecastChart** | History is 2px solid ink. **Today** is a 1px ink-2 vertical rule labelled "Today". The forecast is a 2px `--series-forecast` P50 line plus `--band-forecast` between P10 and P90, labelled once "Likely range". The buffer is a 1px dotted `--caution` line labelled "Buffer £300". Each low point gets an 8px ring with a direct label "£242 · 27 Oct". Paydays and big bills are 4px ticks on the x-axis (labelled on hover). Pay gaps of at least 35 days get a bracket above the axis ("41 days"). An unobserved period after a stale statement is hatched `--paper-sunk` and labelled "No data". |
| **ScenarioComparison** | Same axes. Baseline is P50 + band. Simulated is a 2px **dashed (6 4)** `--series-simulated` line + `--band-simulated`. A third scenario uses dash `2 3`. The divergence point has a flag ("Flights · 1 Dec"). The comparison table sits beneath, and there is never a second y-axis. |
| **SpendingBreakdownChart** | Horizontal ranked bars in one hue (`--ink-2`): 16px bars, 2px gaps, values right-aligned tabular. The finding's category is in `--ink` with a **usual-level tick** at the 3-month median ("usual £203.10"). Essential bills (such as rent) are labelled *essential*; family support abroad is labelled *commitment* in `micro` and can be hidden ("Show everyday spending only"). Max 8 rows, then "Other". Period selector: 30 days / 3 months / 6 months. |
| **GoalProjection** | Progress so far is solid ink. The projection uses forecast colour + band. The target is a rule ending at a flag "£1,500 · 31 Mar 2027". The gap at the date is a bracket labelled "£548 short" or "£92 ahead". |
| **AgentExecutionTimeline** | A vertical list, not a Gantt. Each row: status glyph (✓ ✕ ⟲ ○), agent, one-line result, duration in mono at the right. Revisions nest under the Advisor. Expanded rows show the model, tokens and retries. |
| **Money map** (P3 only) | §8.3. |
| Sparkline | 32px, 1.5px line, no axes. Used only in Recurring rows. |

**Uncertainty rules:** whenever a forecast is shown, its band is shown too. The text gives the range in words beside the P50. Probabilities are sentences, not gauges. The band widens with horizon and is never clipped. If this workspace's backtested coverage is below 70% (`09`), a caution note appears: "Recent forecasts for you have been less reliable than usual."

### 10.8 Tables
Columns: Date (`ui`, ink-2) · Description (merchant in ink, raw narration below in mono 12 ink-3, payment-type tag `DD`/`SO`/`FPO`) · Category (inline select + why icon) · Amount (right-aligned tnum: debits `−£23.40` in ink, credits `+£2,940.00` in `--positive` **with the plus**). The header is `micro` small caps over a 1px `--rule-strong`. Row rules use `--rule`, and there's no zebra striping. Hover uses `--paper-sunk`. Selection is a 2px accent left bar. The header is sticky. The totals row is weight 500 above a double rule (the statement convention). Wide tables scroll inside their own container. An **Account** column appears only for multi-account workspaces.

### 10.9 Agent response components
- **Narrative**: `body`, max 68ch, inline receipts.
- **Receipt** (signature): tnum figure, `1px dotted currentColor` underline offset 3px, superscript note marker (`micro`, accent). Hover/focus shows a one-line preview ("calc_01JA… · median of 3 months"). Click or Enter opens the drawer. Focus: 2px `--focus` outline, offset 2px.
- **Sources line**: mono 12, ink-3, middle-dot separated.
- **Follow-up chip**: 32px tall (44px hit area), 4px radius, 1px `--rule-strong`, `ui`. Hover `--paper-sunk`.
- **EvidencePanel (inline)**: the drawer's Reasoning + Calculation rendered inside a 1px rule frame, with "Open full notes".

### 10.10 Recommendation & risk states
**InterventionCard**: a 3px left bar + content (no box), so it reads like a quoted passage.

| State | Bar | Label | Actions |
|---|---|---|---|
| Draft (Verification tab only) | `--rule-strong` dashed | DRAFT | — |
| Checked | `--accent` | ✓ CHECKED · *n* revision(s) | I'll do this · Try in the Lab · Not for me |
| Accepted | `--ink` | TRACKING · check-in 11 Nov | Undo (10 s) · Stop tracking |
| Confirmed | `--positive` | ✓ WORKED | See comparison |
| Didn't stick | `--ink-3` | NO CHANGE YET | Try another approach |
| Dismissed | — (one collapsed line) | Dismissed · reason | Undo |
| Withdrawn | `--ink-3` dotted | ⊘ WITHDRAWN · couldn't be checked | See why |

Content order: the action sentence (body 500), the impact line with receipts, the verification label, then the actions. Impact is always a computed figure, never "save money".

**RiskAssessment**: severity word + glyph (▲ HIGH / ◆ WATCH / ○ LOW), the risk sentence, probability and timing, and drivers as receipts. No gauges, no traffic-light dials.

### 10.11 Inputs & scenario controls
- **Text input**: 44px, 1px `--rule-strong`, 4px radius, `--paper-raised`. Focus is a 2px `--focus` ring. The label sits above (`ui` 500) and the help text below (`micro` ink-3). Errors appear below in `--negative` with ✕ and `role="alert"`.
- **Money input**: £ prefix, comma grouping on blur, tnum. Accepts "640", "1.5k" with a parsed preview ("= £1,500.00").
- **Date input**: natural typing ("1 dec") plus a calendar popover. Shows the weekday ("Tue 1 Dec 2026").
- **Segmented control** (`role="radiogroup"`): periods, theme, scope (P3).
- **Scenario chip**: TYPE (`micro`, `--simulated`) · amount · date · target. Click to edit in a popover. ✕ removes. Parser-assumed values are underlined dotted and marked "Assumed".
- **Slider**: only for % cuts and income-drop %. It's always paired with a number input. Keys step 1%, or 10% with Shift.
- **Toggle row**: checkbox + label + right-aligned effect figure.
- **Buttons**: Primary (accent fill), Secondary (1px rule-strong outline), Quiet (accent text). One primary per view. 40px tall (44px touch). The disabled state uses ink-3 text and a rule border, not just reduced opacity.
- **Drop zone**: 1px dashed `--rule-strong`, `--paper-raised`. Drag-over: 2px dashed accent + `--accent-tint`. Keyboard: the whole zone is a button that opens the file picker.

### 10.12 Provenance badges & multi-account controls
- **Provenance badge** (`micro` small caps, 20px, 4px radius, 1px border, no fill): **DETECTED** (border `--rule-strong`, ink-2), **CONFIRMED** (border `--ink`, ink, ✓), **DECLARED** (border `--accent`, accent). They appear in step ②, Recurring and Settings → Pay, and next to every input in the Evidence drawer's Calculation tab. When declared and observed values differ by more than 10%: "You told us £3,100. We've seen £2,940 twice since. Which is right?"
- **Scope selector** (only when >1 tracked account; Household option requires joint data): radiogroup `Mine · Household · account ▾`. Switching reads persisted per-scope forecasts, with no LLM call; a missing scope result is built deterministically as an explicit action. The scope is printed in each chart caption ("Household · 3 accounts").
- **Coverage indicator** (P3 only; requires more than one account or an untracked destination): text, not a meter: "4 accounts · 1 card we can't see ⓘ". The popover lists accounts with last-data dates and an *Add statement* action for untracked ones.
- **Household wording rule**: in Household scope, copy says "your household", never a partner's name as the person spending.


### 10.13 Money formatting, other currencies and locale copy (00 §6c)

| Locale | Example (actual) | Example (forecast, whole units) | Rules |
|---|---|---|---|
| en-GB, GBP | £1,284.50 · −£31.80 | £242 | thousands comma; 2 decimals; minus before symbol |
| en-IN, INR | ₹1,15,000.00 · −₹1,499.00 | ₹47,850 | **lakh grouping** (12,34,567); 2 decimals; "L"/"Cr" abbreviations only in chart axes (₹1.2L) |
| any, JPY / zero-decimal | ¥128,000 | ¥128,000 | ISO 4217 exponent decides decimals; never show ".00" for zero-decimal currencies |
| de/fr-style source files | shown in the workspace locale | — | source format (`1.234,56`) only affects parsing, never display |

- All figures use tabular numerals; the currency symbol is always shown, even in tables, because a workspace may hold several currencies.
- **Other-currency accounts** appear as their own line wherever balances are listed, never summed: `€212.40 · Revolut EUR · not included in the £ forecast`. Charts and forecasts are per currency; the Lab's account picker shows each currency's accounts separately. No FX conversion anywhere.
- **Locale copy** comes from the pack: UK wording follows "guidance, not advice"; India wording avoids product recommendations (no fund or bank names in advice). Category names are localised (UK *Council tax*; India *EMI*, *SIP*, *Rent (UPI)*).
- **Honesty note for India** (Briefing footer and the Evidence drawer’s Calculation tab, `micro` ink-3): "Indian bank formats and categories are validated on test data, not yet on real statements." It disappears only when a real-data validation is recorded.

India sample snippets (P4 Aanya, fictional):
```
─ WHERE YOU STAND ─────────────────────────────────────────────
 Balance today¹          Before payday (P50)²       Pay
 ₹84,620.00              ₹47,850 · 29 Oct            ₹1,15,000 on 30 Oct
 from statement 11 Oct   likely ₹41,200–₹53,900      last working day

─ WHAT CHANGED ────────────────────────────────────────────────
 ▲ Food delivery   ₹14,860 in 30 days · usual ₹10,540 · +41%      ›
```
```
 Ledger · Transactions
 07 Oct  Swiggy                      Food delivery     −₹486.00
         UPI/DR/412345678901/SWIGGY/YESB/swiggy@ybl
 05 Oct  Mutual fund SIP             Savings (not spending)  −₹5,000.00
         NACH/ICCL/MF SIP/000123
 03 Oct  Rent · R Kumar              Rent              −₹32,000.00
         UPI/DR/412311112222/R KUMAR/SBIN/rkumar.rent@oksbi/Rent Oct
```

---

## 11. States catalogue

| Surface | Loading | Empty | Error | Success | Streaming / partial |
|---|---|---|---|---|---|
| Briefing | Edition skeleton at final sizes. Figures first, prose after. | No data → "Drop a statement to get your first briefing" + the drop zone | Analysis failed → last good edition with caution bar: "Today's update stopped at the Forecaster step. Showing yesterday's edition. Retry" | "Written 10:42" in the edition bar, no toast | Refresh keeps the current edition and shows "Updating…". Sections swap when ready. |
| Ask | Live agent strip and block skeletons | Data-driven starters (§4.6) | Step failed → names the agent and the reason, with **Retry the run**. Mesh unreachable → "Couldn't reach the language model service (Mesh). Your data and figures are fine. Try again in a moment." | — | Narrative streams, receipts hydrate, Stop aborts |
| Lab | Chart skeleton, "Running 500 paths…" | "Start with a template or describe a decision" | Parse failed → "I couldn't turn that into a scenario. Try 'spend £640 on 1 Dec' or add a change by hand." | "Saved" by the title | Toggling ghosts the previous line at 40% until the new one lands |
| Evidence drawer | Section skeletons | — | Superseded record → preserve its original evidence, with "A newer analysis is available" + link | — | — |
| ① Drop | Per-file "Reading…" rows | The drop zone itself | Per-file statuses (§8.2), always with the reason and a next step | ✓ rows + Continue enabled | Files process independently, and one rejected file doesn't block the others |
| ② Check | — | Nothing detected → "We couldn't find regular pay or bills yet. That's fine with short histories." + See my briefing | — | — | — |
| Digest | — | Not connected → "Get a weekly note with one insight and one action" + Connect | Send failed → Activity + retry | "Test message sent" toast (user action) | — |

**Missing data rule:** never render `£0` or an invented value for something unknown. Use `—` plus a one-line reason ("Needs today's balance", "23 of 45 days of history").

---

## 12. Responsive behaviour

| Breakpoint | Layout |
|---|---|
| ≥ 1440 | 216px labelled rail. The drawer pushes content. |
| 1081–1439 | 216px labelled rail. The drawer overlays. |
| 861–1080 | 216px labelled rail. Two-column grids (Briefing, Lab) become one column; Ask threads and Lab scenarios collapse into a top select. Metric groups are 2-up. |
| ≤ 860 | A 56px bottom tab bar (4 items) replaces the rail. The drawer becomes a full-height sheet. Metric groups stack. Charts are full width, 220px tall, 3 ticks. Tables become two-line rows (date + merchant / amount, then category). Lab chips and comparison rows stack. 16px gutters. No horizontal page scroll. Onboarding is a single column, and the drop zone becomes a *Choose files* button. |

Mobile is designed for **reading**: the Briefing, digest deep links and Evidence. Scenario building works on mobile and is optimised for desktop.

---

## 13. Accessibility

- WCAG 2.2 AA. Contrast is measured (§10.1). Every status has glyph + word. Every chart has a summary sentence (`aria-describedby`), a hidden table and Copy as table.
- Full keyboard operation. Charts are focusable with arrow-key crosshairs, and Enter on a mark opens its actions. Esc closes the drawer and returns focus to the receipt that opened it.
- Roles: `nav` + `aria-current`, `tablist`, `radiogroup`, `aria-live="polite"` for streaming and file status, `role="alert"` for errors, `role="dialog"` + `aria-modal` for overlaying drawers.
- Figures read naturally: `£1,284.50` → `aria-label="1,284 pounds 50"`. Ranges and probabilities get full-sentence labels.
- Touch targets ≥ 44px. Visible focus on every interactive element. In `forced-colors`, bands become hatching and dashes keep their pattern.
- `prefers-reduced-motion` is respected. Text works at 200%. Reading width is capped at 68ch.

---

## 14. Prototype coverage checklist (`design/prototype/`)

| Screen | Must show | Theme |
|---|---|---|
| ① Drop | P1 Monzo file row ("balance not in file") + one example each of Reconciled, "Detected format: new layout · Confirm your columns" and Rejected rows (P3/P2 files) | Day |
| ② Check what we found | P1 screen per §8.3 with badges and the single balance question. A P3 variant with money map + joint consent. | Day |
| Briefing | Full P1 edition per §3.2 with working receipts → drawer | Day + Night |
| Ask | J7 response: collapsed + expanded timeline, chart blocks, InterventionCard, chips | Day |
| Decision Lab | Flights scenario per §5.1 with chips, comparison chart (41-day bracket), table and Make it work | Day |
| Evidence drawer | `rec_` notes per §7.1 with both verification passes | Day + Night |
| Ledger | Transactions (UK payment-type tags) + Review tab | Day |
| Mobile | Briefing at 390px | Day |
| No-income state | §3.6 Briefing (S14 side account) with the three options, "Other money in (not confirmed)" line, an "Assumed, not confirmed" assumption row, and the §8.3 "What is this money?" chips | Day |

Every prototype figure comes from register §10a or is marked *(04 fixture)* here. Do not invent new numbers without adding them to this document first.

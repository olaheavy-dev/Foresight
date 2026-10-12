# 00 — Decision Register (canonical)

> This is the single source of truth that every other document in `docs/` must agree with.
> If a later document needs to deviate, it changes this file first and records why.
> Status key: **DECIDED** (build against it) · **PROPOSED** (default unless overturned) · **OPEN** (see §12).

Last updated: 2026-10-12 (rev 5.1: end-to-end review fixes — Tier 1 CSV reconciliation, honest demo close-out, freezes defined, private run split, accept/outcome task, "Checked" copy; rev 5: owner decisions — solo builder, staged release, non-blocking real-data gate, continuous deployment; rev 4.3: review fixes — Mesh-only enforcement, honest claims, dependency fixes, submission checkpoint; rev 4.2: cross-document alignment, import-profile identifiers, ambiguity gates and currency contracts; rev 4.1: external synthetic India test set; rev 4: Workspace replaces Profile; any currency; UK + India locales; XLS re-added; rev 3.5: documentation alignment — shared thresholds, schemas, immutable snapshots, scheduling and submission dependencies; rev 3.4: real-data validation is a submission gate; rev 3.3: P3 banks/city changed, no-income state; rev 3.2: unconfirmed-inflow policy; rev 3: UK market, single-account-first, bank adapters, 3-step onboarding; rev 3.1: P1 payday/low dates corrected to real 2026–27 weekdays — 19 Dec 2026, 28 Nov, 28 Feb and 28 Mar fall on weekends — and Feb low smoothed to £1,396 so Jan→Feb→Mar growth is a steady ~£496/mo) · Phase: design (no production code)

---

## 1. One-line positioning

**Foresight tells you where your money is heading, checks its own advice before it reaches you, and gives every number a receipt.**

The three pillars, in priority order (they map directly onto the judging criteria):

| Pillar | What it means concretely | Judging criteria it serves |
|---|---|---|
| **Forecast first** | A deterministic, seeded cash-flow engine projects daily balance 90 days ahead with an uncertainty band; every what-if runs through the *same* engine. | #2 core loop, #3 core domain |
| **Advice that is checked** | A Verifier agent re-computes and challenges every recommendation; rejected advice goes back to the Advisor with a critique (max 2 revisions). The loop is visible and logged. | #1 orchestration, #2 core loop, #7 audit |
| **Every number has a receipt** | No figure shown to the user is produced by an LLM. Numbers come from persisted `Calculation` records; the LLM only references them by ID. Click any number → Evidence drawer. | #6 self-eval, #7 audit, #8 code quality |

## 2. Hackathon facts (verified from the official page, 2026-10-12)

- Track: **FinPilot** (Track 03). Prizes ₹20k / ₹10k / ₹5k.
- Registration closes **17 Oct 2026 23:00 IST**; submissions close **20 Oct 2026 23:00 IST**.
- Judging criteria, in order, no published weights: (1) multi-agent orchestration, (2) the track's core loop, (3) core domain capability, (4) supporting domain capability, (5) foundation/data model/real ingestion, (6) self-evaluation — *rewarded heavily*, (7) auditable decision trail, (8) code quality & reproducibility.
- **An automated AI system reads the code first**; only shortlisted entries get human judges, demo video and deployed URL review. ⇒ Code clarity, README and committed eval results matter as much as UI polish.
- Explicit penalties: hardcoded outputs, an agent never called, a loop that never loops, a test set that doesn't exist.
- Mandatory: Python backend (FastAPI/Flask); every LLM call via Mesh (`https://api.meshapi.ai/v1`, OpenAI-compatible, key `MESH_API_KEY`, prefix `rsk_`); CI workflow `.github/workflows/agent-arena-2026-checks.yml` with secrets `MESH_API_KEY` and `SUBMISSION_TOKEN`; no committed `.env`.

## 3. Scope decisions

| Decision | Status |
|---|---|
| Full design phase (all 10 docs + hi-fi prototype) before code — user explicitly chose quality over compression. | DECIDED |
| **PDF import: generic** — any text-based statement whose layout passes the reconciliation gate (`pdf_statement` adapter: layout detection → optional LLM layout proposal → deterministic extraction → mandatory reconciliation; see §6b). **Tier 2**: Stage 4(b) in the build order, behind the `pdf_import` flag; ships only if its suites are green before the freeze. The private real-data run (roadmap PRV-06) uses it when it ships and is otherwise reported as CSV-only. *(rev 5: no longer "not cuttable".)* Scanned/image PDFs (OCR) out of scope. *(rev 3: was fully out of scope.)* | DECIDED |
| **Open Banking / Account Aggregator: out of scope.** Same adapter interface. | DECIDED |
| Onboarding is **three steps**: Drop statements → Check what we found → Your briefing (§10b). Instant demo workspace and manual entry remain as alternatives. | DECIDED |
| **Two generic importers only**: `csv_statement` (Tier 1; XLS/XLSX reading re-added in rev 4 for Indian exports is **Tier 2**, Stage 4(c), ING-14) and `pdf_statement` (Tier 2). Bank knowledge lives in **data** (`FormatProfile` for CSV, `LayoutProfile` for PDF), never in bank-specific code. Built-in profiles ship for Monzo and Revolut; unknown banks get an LLM-proposed profile confirmed once. *(rev 3.1: replaced separate monzo/revolut adapters.)* | DECIDED |
| Scheduled digest via **Telegram bot** (primary) with email (SMTP) as secondary channel, driven by APScheduler — never a manual button. | PROPOSED |
| Goal tracking with adaptive advice (bonus). | DECIDED (in scope; built in **Stage 3**, `10` ENG-06/PRO-02) |
| Conversational analysis (bonus). | DECIDED (core experience) |
| Multi-user production auth. | Out of scope — see §8 |
| **Team: one builder** (the owner) with AI coding assistance; the holdout annotator is a separate person (labelling only). Capacity ≈ 85–100 h to 20 Oct vs ≈ 279 h of mandatory-stage work and ≈ 70 h of Tier 2 (`10` §2). | DECIDED (rev 5) |
| **Staged release.** Full scope stays the target, built as one stream in score order (Stage 0 → 5, `10` §1, §5). Every feature sits behind a flag in `features.yaml`; a flag is switched on in the deployed app, and the feature is claimed in the README, **only when its eval suite is green**. Unfinished work is listed under **"Not shipped (planned)"** in the generated README and never shown half-built. This replaces the cut list / "never cut" framing. | DECIDED (rev 5) |
| **Real-data check (PRV-06) is time-boxed and non-blocking.** It runs before the 19 Oct 18:00 code freeze (feature freeze 19 Oct 12:00; both defined in `10` §1) and reports exactly what was measured (e.g. "11/12 statements reconciled; reason"; or "CSV half only" if the PDF importer did not ship), generated from `private_summary.json`. **Its privacy scan is always blocking.** The README and submission never wait for it. | DECIDED (rev 5) |
| **Continuous deployment from day one.** API on a container host with a persistent SQLite volume (default Render; Fly.io/Railway equivalent) and Next.js on Vercel; auto-deploy `main` on green CI; demo workspaces seeded on every deploy; **no real data ever deployed**; secrets via host env vars; the deployed URL is in the README from Stage 0 and grows feature by feature as flags turn on (`05` §12). | DECIDED (rev 5) |
| **Design stance: single-account first.** One account with everything flowing through it is the default, the primary demo and the judge's path. Multi-account, joint accounts and coverage gaps are progressive enhancements that appear only when the data contains them. The product owner's own banking set-up is one private validation case (n=1), never the template. | DECIDED (rev 3) |

## 4. Markets & persona assumptions (rev 4: UK + India, any currency, single-account first)

- **Two supported locales: United Kingdom (primary demo) and India (second locale).** The engine is **currency-agnostic** (§6c; tested on GBP/EUR/JPY/INR plus KWD unit tests; no FX); locale-specific knowledge (categories, narration parsers, holidays, payday rules, wording) ships as data in **`LocalePack`s**: `uk` and `in`. India rationale: the hackathon judges are India-based, and UPI-heavy narrations are a recognisable categorisation challenge. **Honesty rule:** India support is validated on synthetic data and a hand-written (not real) narration holdout only; the README says so until real Indian statements are tested.
- **UK details: GBP (£)**, locale en-GB (`12 Oct 2026`, `£1,284.50`). Rationale: real-format validation data available is UK; UK narrations carry payment-type codes (DD, SO, FPO, FPI, BGC, DEB, TFR) that make categorisation and recurrence visible; UK obligations (council tax Apr–Jan, energy, water, BNPL, Self Assessment) give realistic forecasting structure. Currency/locale are workspace settings; the engine is currency-agnostic. *(rev 1–2 used India/INR; legacy rev 1–2 ₹ fixtures are superseded; P4’s rev 4 INR fixtures below are current.)*
- UK payday realities the engine models: fixed-date pay moved to the previous working day at weekends/bank holidays; **early December pay** creating a long **December→January gap**; four-weekly pay.
- All personas, people, accounts and figures are **explicitly fictional**. Real merchant brand names (Deliveroo, Tesco, Netflix, LemFi) may appear in narrations. **No real person, account or figure from the owner's statements appears in this repo.** All account numbers and last-four digits in personas and fixtures (e.g. "••5531", "••7731") are invented.

**Canonical synthetic personas** (docs, prototype, evals):

| ID | Persona | Situation | What it demonstrates |
|---|---|---|---|
| `P1` | **Amara Nwosu**, 30, QA engineer, Leeds — **one account** | Everything flows through a single Monzo current account: salary £2,940 net (28th; previous working day at weekends; December paid early on Fri 18 Dec), rent £1,395, council tax, energy, water, broadband, Sky TV, subscriptions, ~£250/mo family support abroad, groceries, food delivery. Goal: £1,500 emergency fund by 31 Mar 2027; buffer £300. | **Primary demo and judge path.** One CSV → categorisation → anomaly (food delivery +41%) → forecast → "Can I afford £640 flights home in December?" → verified intervention with a visible rejection → goal impact → long-January insight. No scope selector, no money map. |
| `P2` | **Jamie Clarke**, 34, freelance motion designer, Bristol — one account | Generic-CSV account; 2–5 client invoices/month (£900–£6,500); Self Assessment payments on account 31 Jan / 31 Jul. | Irregular income, "What if a client pays 45 days late?", tax provisioning. |
| `P3` | **Kofi & Hannah Mensah**, 33/31, Nottingham — **multi-bank household** | Kofi's salary lands in **Starling** (CSV, no built-in profile → LLM-proposed format confirmed once); both contribute to a **joint Nationwide** household account (PDF statements) paying rent and bills; Kofi's **Chase** account for day-to-day spend, topped up from Starling; an **untracked Capital One** credit card paid from two accounts; a tracked **Tesco Bank** credit card (CSV) settled from Nationwide. | The progressive layer: multi-file drop, money map, own-transfer pairing, joint account + consent + Mine/Household scope, untracked-card gap, tracked-card settlement (no double count), counterparty aliasing, generic PDF import. |
| `P4` | **Aanya Rao**, 27, product designer, Bengaluru — **one account, India locale** (`in` pack, INR) | Single savings account at a fictional Indian bank, exported as **XLS/XLSX** (common in India; XLS primary, XLSX equivalent) with a balance column: salary ₹1,15,000 net on the last working day; rent ₹32,000 via UPI on the 3rd; UPI-heavy spending (Swiggy, Zomato, Blinkit, Uber); SIP ₹5,000 on the 5th (`savings_investment`); 7 subscriptions; food delivery ₹14,860 in 30 days vs 3-month median ₹10,540 (+41%). | Proves locale generality: ₹ with lakh grouping (₹1,15,000), dd-mm-yyyy dates, UPI/NEFT/IMPS/NACH narration parsing, Indian bank holidays, XLS through the CSV importer, password-protected PDF prompt. Not the main demo; a 30-second segment and its own eval rows. |

Every persona is produced by a **seeded generator** with ground-truth labels, emitting files in realistic export formats (plain CSV, Monzo-style CSV without balance, Revolut-style multi-table CSV) and **fictional PDF statements rendered in ≥3 distinct layouts** so adapters are tested end to end. Stress variants cover the rest (see `09`).

## 5. Agent boundaries (DECIDED)

One **Coordinator** plus **five specialist agents**. Each has its own prompt, its own tool set and its own output contract. "Agent" = LLM-backed node via Mesh **with** deterministic tools. Deterministic logic lives in the `finance_core` library, never inside prompts.

| # | Agent | Job | LLM role | Deterministic tools it calls |
|---|---|---|---|---|
| 0 | **Coordinator** | Classifies intent, plans the route, enforces budgets/retries, assembles final response. | Intent + slot extraction for free-form questions (cheap model). Route for system events is a fixed table (no LLM). | `route_table`, `budget_guard` |
| 1 | **Ledger Agent** (categorisation) | Normalise narrations, detect transfers/duplicates, categorise with confidence. | Only for transactions the rules + merchant memory cannot resolve with confidence ≥ 0.85; batched. | `normalise_narration`, `merchant_memory_lookup`, `rule_categorise`, `detect_transfer_pairs`, `detect_duplicates` |
| 2 | **Behaviour Analyst** | Find trends, anomalies, recurring obligations, subscription changes. | Ranks deterministic findings by salience and writes the plain-language finding text (must cite finding IDs). | `detect_recurring`, `category_trend` (robust z / MAD vs trailing median), `detect_new_merchant_spike`, `detect_price_change`, `detect_duplicate_subscriptions` |
| 3 | **Forecaster** | Build baseline forecast; run what-if simulations. | Parses a natural-language scenario into a typed `ScenarioSpec`; explains drivers of the result. Never produces numbers. | `build_forecast`, `simulate(scenario_spec)`, `goal_projection`, `backtest` |
| 4 | **Advisor** | Propose specific interventions grounded in findings + forecast. | Proposes candidate interventions as typed `InterventionProposal`s citing finding/forecast IDs. Impact numbers are filled by tools, not the LLM. | `simulate` (to quantify each intervention), `list_findings`, `get_goal` |
| 5 | **Verifier** | Challenge every recommendation before the user sees it. | LLM-judge for specificity, grounding and tone *after* deterministic checks pass. | `verify_evidence_refs`, `recompute_impact`, `check_feasibility`, `check_generic_advice` |

Rejected alternatives (documented in `06`): merging Verifier into Advisor (kills the core loop); a separate "Presenter" agent (it is a deterministic composition node, not an agent — no LLM numbers, LLM only picks block types inside Coordinator's final step); a separate "Goals agent" (goal logic is a Forecaster tool).

**The core loop** (the thing judges must *see* loop):
`Advisor → Verifier → (REJECT with critique → Advisor revise)×≤2 → APPROVE | WITHDRAW`.
Every pass is a persisted `VerificationResult`. The eval suite injects deliberately bad proposals to prove the Verifier rejects them (`09` §9.3).

## 6. Financial engine principles (DECIDED)

1. **LLMs never produce displayed numbers.** All figures come from `finance_core` pure functions and are persisted as `Calculation{id, kind, inputs_hash, params, result, engine_version}`. LLM output references `calc_…` IDs; the server hydrates values.
2. **Reproducible**: forecasts are seeded (`seed = stable_sha256(workspace_id, data_version, scope, scope_account_id, currency)`), versioned (`engine_version`), and re-running with the same inputs yields byte-identical results.
3. **Forecast model (v1)**: daily balance projection. Default horizon **90 days**, auto-extended to cover a goal's target date or a scenario's affected pay cycles (allowed 30–180 days, max 365 when a goal requires it). The same calendar + Monte Carlo model continues over the extended horizon; beyond 90 days the band is labelled lower-confidence. Demo: the trip scenario runs to 31 Mar 2027 (goal date) and covers the 27 Jan low.
   - *Known flows*: detected recurring obligations and income on their calendar (with amount = robust median of last occurrences; day-of-month jitter from history).
   - *Discretionary spend*: per-category daily draws by **block bootstrap** from the last 90 days of non-recurring spend, Monte Carlo N=500 paths.
   - Output: P10 / P50 / P90 daily balance, probability of breaching the user's buffer, min-balance date, end-of-month balances.
   - Baselines for evaluation: (a) "repeat last 30 days", (b) "trailing mean daily net flow".
4. **Simulation** = baseline forecast inputs + typed `ScenarioSpec` modifiers (one-off outflow, income delay/shift, income loss %, recurring add/change/cancel, category cut %), run with the **same seed** so differences are attributable only to the scenario.
5. **Balances**: user does **not** need to enter an opening balance when dated balances exist (CSV balance column, or any manual dated balance). Balances are `BalanceAnchor{account, as_of, amount, source}`; the balance at any date is reconstructed from the nearest anchor ± transactions. No anchor → **relative mode** ("£X more/less than today") with a one-tap "add today's balance" prompt. Anchor older than 7 days with transactions after it → reconstructed; reconciliation mismatch > 1% → "balance may be stale" flag.

## 6a. Multi-account, joint accounts & income (DECIDED — added 2026-10-12 from user's real situation)

Most users have one main account and v1 is designed for that first. Many also split money across accounts (salary in one, bills from another, a joint account, credit cards). The model handles both from v1; the multi-account UI appears **only when the data has more than one account**.

**Principle: detect first, confirm second, ask last.** We never ask for something the data already shows; we ask the user to *confirm* what we detected, and only *ask* for what is invisible in the imported data.

**Accounts.** A workspace has many `Account`s: `type ∈ {savings, current, credit_card, wallet, cash, loan}`, `ownership ∈ {individual, joint}`, optional `role` tag (`salary`, `bills`, `savings`, `household`, `spending`), `tracked: bool`. Each import batch belongs to one account.

**Joint accounts.** `ownership=joint` with `joint_arrangement ∈ {equal_share, percentage(p), fixed_contribution(£/mo), treat_as_household_pot}` (default `treat_as_household_pot`).
- Partner deposits into the joint account are `partner_contribution` (transfer from household member), **never** the user's income.
- Spending in a joint account is **not attributed to a person** (bank data can't tell who spent it). Advice about joint spending is framed at household level ("household food delivery"), never "your partner".
- Forecast **scope selector**: `Mine` (individual accounts + user's share of joint) · `Household` (all tracked accounts) · single account. Default: `Household` when a joint account exists.
- Consent note at import: a joint account contains a partner's transactions; the user confirms they have the partner's agreement.

**Transfers & coverage gaps.**
- Own-account transfers are paired (amount ± fee, date window ±2 days, counter-account hints in narration) and excluded from income/spend.
- An outflow to an own account that is **not tracked** is `transfer_to_untracked` — not spending. The "Check what we found" step then asks: *"£400 goes to an account we can't see every month. What does it pay for?"* or *"Your Capital One card is paid from two of your accounts. Add its statement?"* → user may declare obligations paid there (`DeclaredObligation`, provenance `declared`) or import that account.
- **Credit cards**: if the card account is tracked, card spend is spending and the card bill payment is a transfer (liability settlement — no double counting). If not tracked, the card bill payment is treated as spending in category `credit_card_bill_unitemised`, and Foresight offers to import the card statement.
- Excluded from "spending" but reduce cash: `savings_investment` (ISA, savings pots, investment platforms), `loan_repayment` (loans, car finance and BNPL instalments are obligations, still forecast).
- Not income: refunds, reimbursements, friends settling up (Faster Payments from individuals tagged `reimbursement`/`split_settlement` on confirmation), partner contributions.

**Income (salary).**
- Income is **detected** from recurring credits (source, net amount = robust median, payday rule e.g. "last working day", account). Onboarding asks the user to **confirm** it, not type it.
- The user may **declare** income only when it isn't observable: salary lands in an untracked account, new job, raise, or < 3 observed cycles. `IncomeStream{source, amount, cadence, payday_rule, account, provenance ∈ {detected, declared, confirmed}}`.
- We collect **net take-home only**. Never gross salary, National Insurance number, date of birth or bank credentials. (Employer names appear in narrations and are used only to detect the stream.)
- Declared figures are shown with a "declared" badge in Evidence; forecast uses observed data when both exist and flags divergence > 10%.
- Edge cases handled: payday shifted by weekends/holidays (from history), bonus/arrears (one-off, excluded from baseline), salary split across two accounts, irregular freelance income (P2 → income distribution, not a single salary).

**Inflows we can't confirm (DECIDED — rev 3.2).** Principle: *real cash counts in the balance; uncertain money is never called income or relied on by advice. Only recurring uncertain inflows are projected, as explicit assumptions that the user can disable.*

Deterministic ladder applied to every credit (first match wins):

| # | Pattern | `flow_kind` | Projected in forecast? |
|---|---|---|---|
| 1 | Paired with a debit in another **tracked** own account | `transfer_own` | n/a (nets to zero) |
| 2 | From the user's own name/alias, no tracked counterpart | `transfer_from_untracked` (own money, **not income**) | Only if recurring*; labelled "from your other account"; gap question offers to add that account |
| 3 | Matches an earlier debit from the same merchant (≤ 90 days, ≤ original amount) | `refund` | No |
| 4 | Recurring*, company/payroll-like counterparty or Bacs/BGC code | `income` (provenance `detected`) | **Yes** — used even if the user never confirms |
| 5 | HMRC / DWP / council | `income` (benefit, tax refund; one-offs not projected) | Recurring only |
| 6 | Bookmaker | `betting_return` | No |
| 7 | Anything else (people, PayPal, one-off company payments, cash deposits) | **`inflow_unconfirmed`** | **Only if recurring***, at P50, shown as an explicit assumption ("assumes £200/mo from T. Okafor continues") |

\*Recurring = ≥ 3 occurrences, regular cadence (weekly / 4-weekly / monthly ± 3 days), amount coefficient of variation ≤ 20 %.

Treatment of `inflow_unconfirmed`:
- **Balance & history**: always counted, so balances and reconciliation stay exact.
- **Income metrics**: excluded. Shown as its own line, "Other money in (not confirmed)".
- **Spending**: never offsets spending, unless the user later marks it as a reimbursement.
- **Advice**: Verifier rule V-19 rejects any recommendation whose feasibility depends on an unconfirmed inflow continuing.
- **Questions**: at most 3 in "Check what we found", ranked by total amount, as one-tap chips (*Salary/income · From my other account · Partner/household · Paid back · Refund · Other*). The rest wait in Ledger → Review. Answers are saved on the `Counterparty`, so they're never asked twice.

**No regular income found in a single account** (e.g. a side account funded only by top-ups): the forecast still runs from observed patterns. The Briefing says so plainly and offers three options: *Add the account your pay goes into* · *Tell us your take-home (declared)* · *Continue without income* (forecast then assumes only recurring inflows already seen, and the buffer-breach risk reflects that).


**Basic information we collect (complete list).**

| When | Ask | Required? |
|---|---|---|
| Start | Workspace display name, country (UK/India), home currency and locale (pack defaults; UK: GBP, en-GB) | Yes |
| Per import | Bank and account type are **auto-detected from the file** where possible; individual/joint asked **only if** a second account or partner-like transfers are present (default individual) | Only if ambiguous |
| After analysis — **confirm** | Detected income streams, recurring bills, own-account transfers, likely partner contributions | Confirm/correct (skippable) |
| After analysis — **ask only if gap detected** | What untracked accounts/cards pay for; expected income if not observed; today's balance if no usable balance anchor exists (e.g. the first Monzo CSV) or the anchor is stale | Only when gap |
| Optional | Cash buffer (default: 1 month of essential obligations, suggested from data); goals; digest channel & time | No |

**Canonical accounts:** P1 = one Monzo current account (individual, tracked). P3 = Starling (Kofi, salary), Nationwide (**joint**, `treat_as_household_pot`, PDF statements), Chase (Kofi, spending), Tesco Bank credit card (tracked, settled from Nationwide), Capital One (**untracked**, paid from Starling and Chase → `credit_card_bill_unitemised` + one gap prompt). *(rev 3.3: P3's banks and city changed so the persona does not mirror the product owner's real set-up.)*

## 6b. Importers & lessons from real statements (DECIDED — rev 3; reworded rev 4.3)

Structural lessons from privately analysed real UK statements (analysed locally; **no personal data recorded**) and from publicly observed export formats of popular UK banks. They inform edge-case handling and P3; they do not shape the default experience.

| Importer | Format facts | Rules | Tier |
|---|---|---|---|
| `csv_statement` (generic) | Bank CSV exports in general (claims limited to tested layouts). Publicly observed export formats differ: Monzo-style exports have no balance column, a unique `Transaction ID`, £0.00 card-check rows, dd/mm/yyyy, separate Money Out/In; Revolut-style "consolidated statements" start with account summaries and have **one transaction table per currency pocket**, `Total` rows, `---------` separators and dates like `2 Sept 2026`. | (1) **Table locator**: scan for header-like rows instead of assuming row 1; split multi-table files (each non-empty table = an account/pocket). (2) **Match a `FormatProfile`** by header signature — data, not code: column roles (date, description, amount or in/out, balance, id, bank category), date format, sign convention, skip rules (zero-amount rows, `Total`, separators). Built-in profiles: Monzo, Revolut, plus common UK banks as available. (3) **Unknown header** → confident heuristic mapping; otherwise Ledger Agent proposes a `FormatProfile` from the redacted header + ≤5 digit-masked sample rows (never amounts); user confirms once; saved. (4) **Reconcile** where a running balance exists (row chain); no balance column ⇒ ask today's balance once or relative mode; ID column ⇒ idempotency key. | **1** |
| `pdf_statement` (generic) | Any text-based bank statement PDF. Observed on real statements: direction is often not labelled per row once text is extracted; descriptions wrap; headers repeat per page; a "Balance on <first day>" header can mean end-of-day, not opening (seen on a real UK bank layout). | (1) Extract words with coordinates; (2) find header row by synonyms (Date · Description/Details · Paid in/Money in/Credit · Paid out/Money out/Debit · Balance) and cluster columns by x-position; merge wrapped lines; (3) if no confident layout, **Ledger Agent proposes a `LayoutProfile`** from the redacted header + ≤5 sample rows (LLM never outputs amounts); (4) deterministic extraction; direction from columns or running-balance movement; opening = closing − Σin + Σout; (5) **reconciliation gate**: row chain on running balance AND stated totals, else reject with a row-level report (never silent partial import); no running balance ⇒ totals-only check, `confidence=low`, review prompt; (6) confirmed layouts saved as reusable `LayoutProfile`s. Password-protected ⇒ prompt, decrypt locally. Validation: owner's 12 real PDF statements reconciled 594/594 rows in a design-time check (private, n=1); public eval uses fictional multi-layout PDFs. | **2** |

Lessons now encoded as requirements (all apply equally to single-account users where relevant):
1. **Single account is complete on its own**: income, bills, transfers to savings pots, card payments and spending are all classified within one account; a forecast never requires a second account.
2. **Chains across banks** (when present): multi-file drop in one step; own-transfer pairing; the money map appears only then.
3. **One card paid from several accounts**: aggregate card payments across accounts before one gap prompt.
4. **Counterparty aliasing**: the same person under several name variants; `Counterparty{aliases[]}` with user-confirmed merges; the user's own name variants recognised as *self*.
5. **`family_support_abroad`** (LemFi, Wise, WorldRemit, etc.) is a **commitment**, not discretionary; never suggested for cuts unless the user asks.
6. **Betting & gaming** is its own category; wins are `betting_return`, not income; insights neutral and opt-in.
7. **One-off large items** (visa fees, devices, insurance renewals) excluded from the discretionary baseline, shown as one-offs.
8. **Monthly statement cadence** ⇒ anchors can be weeks old ⇒ stale-anchor flag and "add this month's statement" prompt are core.

## 6c. Any currency, locale packs and workspaces (DECIDED — rev 4)

**Workspaces.** `Workspace` (`wsp_`) replaces "profile": one person's or one household's financial space, holding accounts, imports, format/layout profiles, goals, forecasts, recommendations and the audit log. Fields include `country` (selects the `LocalePack`), `home_currency`, `locale`, `timezone`. Hackathon: a single local user with a workspace switcher; demo workspaces = personas P1–P4. Production: a `User` (managed auth) owns ≥ 1 workspace (e.g. "Personal", "Household"). Export and deletion operate per workspace.

**Any currency (engine) — claim wording.** User-facing and README copy says "currency-agnostic engine, tested on GBP, EUR, JPY and INR (plus KWD unit tests), no FX conversion", never an unqualified "any currency". Likewise PDFs: "any text-based statement whose layout passes the reconciliation gate; tested on the listed layouts", never "any bank".
1. Money = integer minor units + ISO 4217 code; the exponent comes from the ISO table (JPY 0, GBP/INR/EUR 2, KWD 3). Never assume pence.
2. **Currency detection per account** (first match wins): currency column → unambiguous symbol/code in amounts or headers (`£`, `₹`, `€`, `INR`) → matched FormatProfile/LayoutProfile → workspace home currency. Ambiguous symbols (`$`, `kr`, `¥` CNY/JPY) ⇒ one-tap confirm in "Check what we found".
3. **Number and date formats** inferred from the data: decimal/grouping separators (`1.234,56` vs `1,234.56`, lakh `1,15,000`); date order resolved by a saved/built-in format or unambiguous dates (including a day > 12); otherwise ask once, with the locale default pre-selected. Locale alone never commits an ambiguous file (H13).
4. **Forecasts are per currency.** Each account forecasts in its own currency; workspace views show the home currency; other-currency accounts appear as separate balances. **No FX conversion or FX forecasting** (would need an external rates source); combined cross-currency totals are out of scope.
5. Card spend abroad uses the settled home-currency amount; `original_amount` is kept for display.

**Locale packs (data, not code)**: `LocalePack{country, default_currency, number/date formats, holiday calendar (python-holidays), payday conventions, category rules + merchant lexicon, narration parsers, protected categories, wording/regulatory notes}`.

| Pack | Narration parsing | Payday & calendar | Locale-specific categories | Wording |
|---|---|---|---|---|
| `uk` | DD, SO, FPO, FPI, BGC, DEB, TFR codes | 28th/last working day, early December pay; England & Wales holidays | council tax, energy, water, TV licence, BNPL, Self Assessment, family support abroad | FCA guidance-not-advice |
| `in` | UPI (`UPI/DR/<ref>/<payee>/<bank>/…`), NEFT, IMPS, NACH/ECS mandates, ATM | 1st or last working day; national + state holidays (Karnataka for P4) | rent via UPI, EMI (`loan_repayment`), SIP/RD/FD/PPF (`savings_investment`), GST/advance tax, school fees, family support (domestic) | SEBI/RBI-neutral; no product recommendations |

Both packs mark `savings_investment` (ISA/pension/savings pots; SIP/RD/FD/PPF) as **protected**: the Advisor never proposes pausing or cutting it unless the user asks (that would be regulated investment advice). User-facing copy: "Guidance, not regulated financial advice (UK FCA / India SEBI)"; recommendations are labelled **"Checked"**, not "Verified"; high buffer-breach risk signposts free help (MoneyHelper in the UK). Privacy law: UK GDPR / DPA 2018 and India's DPDP Act 2023.

Adding a country = adding a pack + generator formats + eval rows; the engine is unchanged.

**Formats without real samples (India).** No built-in Indian FormatProfiles are claimed. Indian files go through the generic importers; unknown layouts get an LLM-proposed profile confirmed once. XLS/XLSX is read into a table and passed to `csv_statement` (re-added in rev 4: common for Indian bank exports). Password-protected PDFs (common in India) prompt for the password, decrypted in memory only.

**Evaluation of generality.** Generated variants: P4 India (XLS + UPI), a euro account (comma decimals, dd.mm.yyyy), a yen account (zero decimals), and a mixed-currency workspace (GBP + EUR pocket, forecast per currency). India categorisation is scored on a separately hand-written UPI narration holdout labelled `constructed`, reported apart from the UK holdout. **External synthetic India set** (rev 4.1): 3 MIT-licensed PDFs with expected outputs (AyonPal/bank-statement-pdf-parser) and a 300-description hand-labelled sample from the Apache-2.0 AgamiAI/Indian-Bank-Statements JSON, fetched at pinned revisions, attributed, reported separately as `external_synthetic` (09 §3.4b). It reduces circularity; it does not make India support "real-data validated".

## 7. Structured generative UI (DECIDED)

- Agent responses are `AgentResponse{response_id, run_id, blocks[]}` where `blocks` is a **discriminated union** of 10 predefined component types (`FinancialMetricGroup, SpendingBreakdownChart, CashFlowForecastChart, ScenarioComparison, TransactionTable, RiskAssessment, InterventionCard, GoalProjection, EvidencePanel, AgentExecutionTimeline`) plus `Narrative`.
- The LLM chooses blocks and supplies **references** (`calc_ref`, `finding_ref`, `txn_query`), never raw series. The server **hydrates** blocks from persisted calculations and validates them (Pydantic on the server, generated Zod/TS types on the client).
- Responses are persisted as snapshots ⇒ reloading a past analysis never re-runs agents.
- Unknown/invalid block ⇒ dropped and replaced by a `Narrative` fallback; logged.

## 8. Technology (DECIDED stack — Next.js, FastAPI, LangGraph, Mesh are fixed; trade-offs and alternatives still documented in `05`)

Scope note: the user has explicitly confirmed **nothing in the original brief is reduced** except Open Banking and scanned/image PDF statements (OCR). All five experiences, the full design system, the structured generative UI, Next.js frontend and all bonus items are in scope.

| Layer | Hackathon choice | Production path |
|---|---|---|
| API | Python 3.12, FastAPI, Pydantic v2 | same |
| Orchestration | LangGraph (StateGraph, explicit nodes, checkpointer) | same + durable checkpointer (Postgres) |
| LLM | `openai` SDK with `base_url=https://api.meshapi.ai/v1`, wrapped in one `mesh_client` module (the only place an LLM is called) | same + model routing/fallback via Mesh |
| Finance engine | `finance_core` pure-Python package (NumPy, pandas) — no I/O, fully unit-tested | same |
| Storage | **SQLite** via SQLAlchemy 2.0 + Alembic-ready models, every row scoped by `workspace_id` | PostgreSQL + row-level security |
| Frontend | **Next.js (App Router) + TypeScript**, Tailwind with custom tokens, Visx/D3 for charts (Recharts acceptable fallback) | same |
| Scheduling | APScheduler in the API process (persisted job store in SQLite) | Dedicated worker (Celery/RQ/Arq) |
| Digest | Telegram Bot API + SMTP email | + push |
| Auth | Single local user with a **workspace switcher**; signed session cookie; all queries workspace-scoped | Managed auth (Clerk/Auth0/Supabase); a `User` owns ≥ 1 `Workspace` |
| Observability | Every agent node writes `AgentStep` rows (model, tokens, latency, cost, inputs hash, output) + structured logs | + OpenTelemetry/Langfuse |

## 9. Visual direction (DECIDED for prototype) — "Broadsheet"

A financial *broadsheet*, not a SaaS dashboard: editorial typography, ruled lines instead of cards, one restrained accent, numbers as the hero.

- **Type**: Display/headlines **Newsreader** (serif, optical sizes); UI and figures **Inter Tight** / **Inter** with `font-variant-numeric: tabular-nums`; evidence IDs and calculation refs **JetBrains Mono**.
- **Colour tokens (light, "Day edition")**: `--paper #F6F3EC`, `--paper-raised #FBF9F4`, `--ink #16181D`, `--ink-2 #4A4E57`, `--ink-3 #8A8D94`, `--rule #DAD5C9`, `--accent #1F4FD1` (Foresight blue — forecast & primary action), `--simulated #B4531F` (burnt orange — simulated/what-if only), `--positive #1E7A4F`, `--negative #B3261E`, `--caution #A86A00`.
- **Dark ("Night edition")**: `--paper #0F1115`, `--paper-raised #161920`, `--ink #ECE8DF`, `--ink-2 #B5B2AA`, `--ink-3 #7C7A75`, `--rule #2A2D34`, `--accent #7EA2FF`, `--simulated #F0915A`, `--positive #4FC08D`, `--negative #FF7A6E`, `--caution #E6B04A`.
- **Data grammar** (never violated): **history = solid ink line**; **forecast = accent line + accent band (P10–P90) with a vertical "today" rule**; **simulated = dashed burnt-orange line**; **thresholds (buffer) = thin dotted caution rule**. Legend words, not just colours (accessibility).
- **Layout**: 216px labelled left rail (Briefing · Ask · Decision Lab · Ledger; bottom tab bar ≤ 860px), content column max ~1120px, right-side **Evidence drawer** reachable from any number (underlined-dotted figures are clickable).
- Avoid: gradients, glassmorphism, emoji, card-grids of unrelated KPIs, purple AI sparkles.
- **Measured contrast amendments (2026-10-12, from `04` §10.1; these override the values above):** light `--ink-3 #6B6E75` (was #8A8D94, 3.0:1 → 4.6:1), light `--caution #8F5A00` (was #A86A00, 4.0:1 → 5.2:1), dark `--ink-3 #8E8C86` (was #7C7A75 → 5.6:1). New tokens: `--rule-strong` (light `#867F70`, dark `#666973`, ≥3:1 for input borders) and chart-mark tokens `--series-forecast` / `--series-simulated` (light `#1F4FD1` / `#B4531F`; dark `#5F86F2` / `#D9733A` — validated for lightness band and CVD ΔE ≥ 25 against the dark paper; the brighter dark `--accent`/`--simulated` stay for text).

## 10. Information architecture (DECIDED)

| Surface | Route | Purpose |
|---|---|---|
| Onboarding | `/start` | 3 steps (§10b): Drop statements → Check what we found → Your briefing. Alternatives: demo workspace, manual entry |
| **Briefing** (Intelligence Home) | `/` | Cached agent-written briefing: Standing · What changed · What's next · Act on this · Under investigation |
| **Ask** (Agent Workspace) | `/ask`, `/ask/[threadId]` | Conversational analysis with generated UI blocks |
| **Decision Lab** | `/lab`, `/lab/[scenarioId]` | Build/compare scenarios against baseline |
| **Ledger** | `/ledger` | Transactions, imports, recurring obligations (tabs) |
| Evidence drawer | overlay on any surface | Calculation, findings, agent run, verification history |
| Settings | drawer | Workspace (name, country, home currency), buffer, goals, digest channel, data export/delete |

## 10a. Shared identifiers & canonical demo figures (DECIDED — all docs/prototype use these)

ID prefixes (ULID after the prefix): `wsp_` workspace · `acct_` account · `bal_` balance anchor · `imp_` import batch · `txn_` transaction · `cat_` category · `rob_` recurring obligation · `fnd_` behavioural finding · `calc_` calculation · `fc_` forecast · `scn_` scenario · `sim_` simulation result · `goal_` goal · `rec_` recommendation · `ver_` verification result · `run_` agent run · `step_` agent step · `rsp_` agent response snapshot · `brf_` briefing · `aud_` audit event · `inc_` income stream · `dob_` declared obligation (the last two added with §6a) · `cpty_` counterparty · `fmt_` CSV format profile · `lay_` PDF layout profile · `rcn_` reconciliation result (added rev 3, `07`).

Canonical P1 (Amara, one Monzo account) figures for 12 Oct 2026 (rev 3, GBP — supersede legacy P1 INR figures, not P4’s rev 4 INR fixtures):
- **Balance**: **£1,284.50** (Monzo CSV has no balance column → one gap question at "Check what we found"; user entered today's balance; provenance `declared`). Buffer **£300**. October is tight because of a one-off **£410 car insurance renewal on 9 Oct** (excluded from the discretionary baseline).
- **Income**: salary **£2,940** net (Bacs), next **28 Oct** (Wed); pay date 28th moves to the previous working day at weekends (Nov → Fri 27 Nov, Feb → Fri 26 Feb, Mar → Fri 26 Mar); December paid early on **Fri 18 Dec**, then **28 Jan** (**41-day gap**).
- **Bills**: rent **£1,395** (SO, 1st), council tax **£162** (DD, 15th, Apr–Jan), energy **£78**, water **£42**, broadband **£31**, Sky TV **£46**. Family support abroad (LemFi) ~**£250/mo** (commitment).
- **Subscriptions**: 7, total **£84.93/mo**: Netflix £12.99, Spotify £12.99, NOW Entertainment £9.99 (**overlaps Sky TV**), Disney+ £8.99, Amazon Prime £8.99, iCloud+ £2.99, PureGym £27.99.
- **Finding** food delivery (Deliveroo, Uber Eats, Just Eat): **£286.40** in last 30 days vs 3-month median **£203.10** (**+41%**), 23 orders.
- **Finding** long January: pay 18 Dec → 28 Jan = **41 days**.
- **Baseline forecast**: P50 pre-salary low **£242 on 27 Oct** (P10 £96 / P90 £388); probability of dipping below the £300 buffer before payday **78%**. Baseline P50 pre-salary lows (day before each payday): 27 Oct £242 · 26 Nov £572 · 17 Dec £1,050 · 27 Jan £900 · 25 Feb £1,396 · 25 Mar £1,892.
- **Scenario** "£640 flights home for Christmas, paid 1 Dec": P50 low **£410 on 17 Dec** (affordable), but **January low falls to £260 on 27 Jan — below the £300 buffer**. Emergency fund goal £1,500 by 31 Mar 2027 (earmarked, `funding_rule=residual`, progress = March pre-salary low − buffer) moves from **on track (P50 £1,592)** to **P50 £952 — £548 short** (£1,592 − £640).
- **Verified recommendation**: cap food delivery at **£180/mo** + cancel **NOW Entertainment** (overlaps Sky TV) → **+£116.39/mo** (£106.40 + £9.99); buffer-breach probability before the October payday **78% → 41%**; with the trip, the January low recovers to **≈ £493** (above buffer). Verified after **1 revision**: first draft proposed a £90/mo cap claiming "+£220/mo"; Verifier rejected it: (a) infeasible — 56% below the 3-month median, beyond the 40% bound; (b) recomputed impact £196.40 ≠ claimed £220. (Foresight cannot know whether a subscription is "used" from bank data; it flags overlap, price change, or the user's own "unused" mark.)

P3 (Mensah household) figures are owned by `07`/`09` fixtures and need not appear in the main demo.

These numbers are **illustrative design fixtures**, not results. Real values come from the engine.

## 10b. The 3-step onboarding (DECIDED — rev 3)

1. **Drop your statements.** One drop zone; one file is the normal case, several are accepted. Each file goes through one of two generic importers (`csv_statement`, `pdf_statement`); known layouts match a saved profile silently, unknown ones get a proposed profile to confirm once. Per-file status: rows read, date range, reconciled ✓ / rejected with reason. Alternatives: *Try the demo workspace* · *Add transactions manually*.
2. **Check what we found.** A short confirm list: income (amount, payday), main bills, subscriptions count, and **gap questions only where detected** (no balance in file, stale balance, untracked card/account). One-tap ✓ / edit; everything skippable. **Only if >1 account or a joint account is detected**, this step also shows the money map (flow diagram) and the joint-account arrangement + partner-consent tick.
3. **Your briefing.** Lands on Briefing with a suggested buffer (editable inline; P1 explicitly chooses £300, rather than using the one-month-essential-obligations default). Goals, digest channel and low-confidence categorisation review are offered from the Briefing, not forced.

## 11. Repository layout (PROPOSED)

```
foresight/
  backend/
    app/            # FastAPI routers, schemas (no business logic)
    agents/         # LangGraph graph, nodes, prompts/
    finance_core/   # pure deterministic engine (categorise rules, detectors, forecast, simulate)
    mesh/           # mesh_client.py — sole LLM gateway
    storage/        # SQLAlchemy models, repositories
    scheduler/      # APScheduler jobs, digest renderers
  frontend/         # Next.js app, ui-contracts (generated TS types), block renderers
  evals/
    datasets/       # generated personas + hand-labelled holdout (committed)
    runners/        # python -m evals.run --suite all
    results/        # committed JSON + markdown reports, timestamped
  docs/             # 00–10
  design/prototype/ # static hi-fi prototype (HTML)
```

## 12. Open decisions (tracked; owners and deadlines below)

1. Exact Mesh model IDs per agent (must be read from Mesh's model catalogue; do not assume names). Default intent: a small fast model for Coordinator/Ledger, a stronger reasoning model for Advisor/Verifier.
2. Charts: Visx (control, more work) vs Recharts (speed, less distinctive). Default: Visx for the forecast/scenario charts, simple SVG elsewhere.
3. ~~Deployment target~~ — resolved rev 5: continuously deployed from Stage 0 (default Render for the API + SQLite volume, Vercel for Next.js; Fly.io/Railway acceptable equivalents); Docker Compose stays for local runs and judges' fresh clones.
4. Telegram vs email as the *primary* digest demo channel.
5. Whether the hand-labelled holdout set is 300 or 500 transactions (labelling cost vs. statistical confidence).
6. ~~Whether XLS import ships in v1~~ — resolved rev 4: yes, via `csv_statement` (table read), for Indian bank exports.
7. PDF layout library used to render fictional test statements (default ReportLab): L1–L4 plus unseen L5; L6 when India ships.
8–9. Reserved; no active decisions.
10. Source/annotator for the independent constructed India UPI holdout (default: independently authored fictional rows, §6c / `09` §3.4a).
11. Whether to seek a consented real Indian sample (default no; India remains synthetic-only).
12. Pinned upstream revisions and independent annotator for the external India set (`09` §3.4b; EVL-20).
13. Same-currency absolute detector/materiality thresholds and goal-change rounding increments for INR and other non-GBP currencies. UK defaults remain £25 spike / £40 strong finding / £100 forecast change / £10 intervention or goal increment / £50 coverage-gap total. Never reuse GBP minor units or infer an FX rate; freeze and version each supported currency configuration before its advice/detector evals.


## 13. Shared implementation rules (DECIDED — rev 3.5 alignment)

These resolve conflicting drafts without changing the full product scope:

- **Naming:** Workspace is the financial isolation unit (`wsp_` / `workspace_id`); `FormatProfile` (`fmt_` / `format_profile_id`) and `LayoutProfile` (`lay_` / `layout_profile_id`) retain their names. P4’s primary generated export is XLS; the UI/contract uses the equivalent XLSX variant. `07` §10a owns all P4 figures.
- **Currency contracts:** Forecast, Goal, ScenarioSpec and amount-bearing interventions carry exactly one ISO currency. Scenario currency must equal its baseline; every referenced account/goal/obligation must match. Persist buffers per `(scope, scope_account_id, currency)`; Preferences supplies the home-currency default only. A missing non-home buffer means no buffer probability until explicitly set, never conversion. Forecast cache identity includes data/prefs versions, currency, scope/account, as-of date, horizon, parameters and engine version. Seed = stable SHA-256 of workspace, data version, scope/account and currency; scenarios reuse it.
- **Ambiguity:** saved/built-in format data or unambiguous dates can resolve date order; otherwise H13 blocks that batch until one user answer, with locale only a pre-selection. Ambiguous separators also require H13; inconsistent rows reject the batch. H13 does not call an LLM. Confirmation is saved in the workspace’s format/layout profile; explicit currency/date evidence in later files overrides defaults or raises a conflict for review.
- **Determinism boundary:** all arithmetic is deterministic for identical validated inputs. Model categorisation, scenario parsing and action selection may change those inputs; null-model end-to-end output is not required to equal a live run.
- **Validation status:** all public UK, India constructed and external-synthetic evals are planned, not completed. India claims stay synthetic-only even after external evals. External files are fetched/pinned; the generator never overwrites frozen holdouts or external data.

- **Document ownership:** `01` owns feature/FR IDs; `03` owns J1–J16 and V1–V5 journey IDs; `06` owns intent routing, intervention actions, V-01–V-20, workflow names and retry limits; `07` owns stored fields, category keys, `flow_kind`, `ScenarioSpec` and engine result shapes; `08` owns UI plans, hydration and snapshots; `09` owns evaluation methods and targets; `10` owns the stages, build order and what ships. They all conform to this register.
- **Recurrence:** automatic recurring inflow/income projection requires ≥3 observations, cadence weekly / four-weekly / monthly ±3 days and amount CV ≤20%. Two observations are a candidate for confirmation or declaration, not automatically projected income. Confirmed irregular client income uses the empirical distribution in `07` §4.5. Outflow recurrence uses ≥3 occurrences and amount CV ≤15%; annual obligations may use two with prior-year evidence.
- **Detector thresholds (GBP defaults; non-GBP absolute values are currency data, OPEN §12.13):** category spikes use robust z ≥2.0 and absolute delta ≥max(£25, 15% of the trailing three-window median). Subscription price changes use ≥5%; large one-offs use ≥3× category median with no recurrence, or a known one-off class. Long-pay-gap findings use ≥35 days. Sensitivity sweeps measure alternatives; they do not change the default silently.
- **Verification:** impact tolerance ±1%; narrative values must match deterministic formatting exactly after display rounding. LLM prose uses value placeholders, never financial numeric literals. The 40% discretionary-cut bound and all protected-category rules remain. V-19 re-simulates without all `inflow_unconfirmed` and non-recurring `transfer_from_untracked` projections.
- **Imports:** CSV/XLS/XLSX ≤10 MB / 20,000 rows; text PDF ≤20 MB / 60 pages, 30 s parse timeout. Reconciliation tolerance is one currency minor unit per row or stated total (£0.01 for GBP; ISO exponent applies to all currencies). With no balances/totals, CSV is `not_available`, never labelled reconciled; PDF is rejected as unverifiable. Sparse balances validate complete date groups, not invented per-row balances. Reconciliation is necessary but cannot prove category/description accuracy: truth comparisons and user preview remain required. A joint import is staged locally until consent; its rows enter neither the committed ledger nor Mesh calls before consent.
- **Snapshots and freshness:** hydrated responses and Briefings are immutable, including their numeric values. Never substitute new calculations into old prose. Read paths return the latest complete snapshot, with a stale label when data, preferences, engine version or financial as-of date changes. Refresh produces a new snapshot; read paths make no engine or LLM calls. Event refresh is debounced 30 s; daily refresh is 06:30 workspace-local time (Europe/London by default). Weekly digest default: Monday 08:00. With no approved action, send an honest status/next-step message, never fabricate advice.
- **Scope:** show account selection when >1 tracked account is present; show Household only when joint data exists. Under `treat_as_household_pot` or `fixed_contribution`, Mine excludes the joint balance and treats contributions as outflows (`07` §6.10). Aggregate paths before calculating quantiles; do not add account quantiles. Internal tracked transfers net out apart from fees; external partner contributions remain real household cash inflows, never income.
- **Replay and release:** public datasets, cassettes and results are synthetic or independently authored fictional holdout rows. Redacted private rows remain private; only aggregate validation metrics leave the private vault. Commands and repository paths outside `docs/` and `design/` are planned build targets, not runnable artifacts today. The Stage 3 live run (EVL-09) covers every shipped suite; the final live run after the feature freeze (EVL-14) alone updates the submitted `latest.json` / README. **Neither the PDF importer nor the private real-data check is a submission dependency (rev 5)**: unshipped Stage 4 items are listed as "Not shipped (planned)", and PRV-06 reports whatever it measured.

Open-decision ownership (defaults remain proposals until resolved):

| Item in §12 | Owner role | Resolve by |
|---|---|---|
| 1 Mesh model IDs | Owner | Stage 0, 12 Oct |
| 2 Charts | Owner | Stage 2 start, 15 Oct |
| 3 Deployment | Owner | **Resolved (rev 5)**: Stage 0, 12 Oct |
| 4 Primary digest channel | Owner | Stage 3, 17 Oct |
| 5 Holdout size | Independent annotator + owner | Stage 1, 13 Oct |
| 7 PDF rendering library/layout count | Owner | Stage 4(b) start |
| 10 Constructed India holdout | Independent annotator + owner | Before LOC-02 tuning (labelling starts once Stage 3 is green) |
| 11 Consented Indian sample | Owner | Before Stage 4(c); default remains no |
| 12 External India revisions/labels | Owner + independent annotator | EVL-20, before LOC-02 tuning |
| 13 Non-GBP absolute thresholds | Owner | Before LOC-02 / non-GBP advice evals |

Human-review checkpoint/resume is required for `06` H1/H4/H5/H10/H11/H13; production crash recovery is deferred. Joint default is decided (§6a). Additional CSV profiles beyond Monzo/Revolut are optional data additions; no further architectural decision is needed.

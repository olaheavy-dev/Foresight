# Foresight — Design Phase Documentation

Phase: product definition, UX/UI, architecture and planning. **No production code exists yet.**
Track: Agent Arena 2026 · FinPilot · submission deadline 20 Oct 2026 23:00 IST (registration closes 17 Oct).
Markets: **UK (primary demo, GBP) and India (second locale, INR, synthetic-validated only)**; a **currency-agnostic engine** tested on GBP, EUR, JPY and INR (plus KWD unit tests), forecast per currency with no FX conversion. Each user's financial space is a **workspace** (formerly "profile"). Stance: **single-account first**. One account with everything flowing through it is the default and the judge's path; multi-account and joint features appear only when the data has them. Register revision: 5.1.

## Reading order

| # | Document | What it answers |
|---|---|---|
| 00 | [Decision Register](00-DECISION-REGISTER.md) | **Canonical** decisions, personas P1–P4, importers (§6b), multi-account rules (§6a), workspaces / any currency / locale packs (§6c), visual tokens, demo figures (§10a), 3-step onboarding (§10b). Every other doc conforms to it. |
| 01 | [Product Requirements](01-PRODUCT-REQUIREMENTS.md) | Vision, personas (incl. P4 India), features F-01–F-74 (+ future F-90–F-97), FR-01–FR-87 (incl. workspaces, currency-agnostic engine, locale packs, XLS), NFRs, privacy, risks, MVP success, non-goals, prioritisation matrix |
| 02 | [Hackathon Requirements Matrix](02-HACKATHON-REQUIREMENTS-MATRIX.md) | Traceability: features/FRs → requirements A–H, bonuses, 8 judging criteria (currency/locale generality under #5 and #6), CI checks, "how a judge sees it" |
| 03 | [User Journeys](03-USER-JOURNEYS.md) | J1–J16 (single-account first; J2 is the primary journey) + P3 multi-account variants, Mermaid diagrams |
| 04 | [UX/UI Design](04-UX-UI-DESIGN.md) | Screens, wireframes, proactive states, Evidence drawer, full design system |
| 05 | [System Architecture](05-SYSTEM-ARCHITECTURE.md) | Components, trade-offs, security, cost, deployment, testing, observability |
| 06 | [Agent Orchestration](06-AGENT-ORCHESTRATION.md) | Coordinator + 5 agents, contracts, LangGraph workflows, Verifier rules V-01…V-20, human review points H1–H13 |
| 07 | [Data Model](07-DATA-MODEL.md) | Entities, ER diagram, edge-case handling, forecast/simulation maths |
| 08 | [Generative UI Contracts](08-GENERATIVE-UI-CONTRACTS.md) | AgentResponse envelope, 10 components + Narrative, hydration, snapshots |
| 09 | [Evaluation Strategy](09-EVALUATION-STRATEGY.md) | Personas, holdout, suites, metrics, baselines, reproduction commands |
| 10 | [Implementation Roadmap](10-IMPLEMENTATION-ROADMAP.md) | One-builder capacity, Stages 0–5 build order, critical path, tasks, acceptance criteria per stage, feature flags and what ships |

Other artifacts:
- **High-fidelity prototype** — `design/prototype/index.html` (open in a browser; pages: Briefing, Onboarding, Ask, Decision Lab, Ledger, Household, India, Components, States).
- **Example agent response contracts** — `design/contracts/*.json` (6 scenarios, fictional data).
- **Diagrams** — agent architecture & workflows (05, 06), user journeys (03), ER diagram (07), dependency graph (10). All Mermaid; they render on GitHub.
- **Feature prioritisation matrix** — 01 §6.

## As-built status (filled in by DOC-02 before submission)

Design docs describe the target. Before submission this table records what was actually built, so no judge or code screener finds a claim the code doesn't back. It is generated from the feature flags and eval status where possible.

| Area | Designed in | Status | Evidence (code path / eval result) |
|---|---|---|---|
| Coordinator + 5 agents, Verifier loop | 06 | — | — |
| Forecast + simulation engine | 07 §6 | — | — |
| `csv_statement` + FormatProfiles | 05 §3.2 | — | — |
| `pdf_statement` + reconciliation gate | 05 §3.2.1 | — | — |
| Multi-account / joint layer | 00 §6a | — | — |
| Currency-agnostic engine, `uk` pack | 00 §6c | — | — |
| `in` pack (Tier 2) | 00 §6c | — | — |
| Five experiences (Next.js) | 04 | — | — |
| Scheduler + digest, adaptive goals | 06, 10 Stage 3 | — | — |
| Forecast self-correction | 06 §10.4 | — | — |
| Evaluation suites + committed results | 09 | — | — |
| Private real-data check (time-boxed, non-blocking) | 09 §17, 10 PRV-06 | — | — |
| Feature flags + continuous deployment | 05 §12, 10 PLT-11/12 | — | — |

Status values: **built** · **built, partial** (what's missing) · **not shipped** (removed from UI and README claims). Generated from `features.yaml` + `latest.json` at submission (FR-86).

## Unresolved architectural decisions

| # | Decision | Default if not resolved | Resolve by |
|---|---|---|---|
| 1 | Exact Mesh model IDs per agent tier (from Mesh's catalogue; never guessed) | Small fast model for Coordinator/Ledger; stronger reasoning model for Advisor/Verifier | Stage 0 (12 Oct) |
| 2 | Visx vs Recharts for charts | Visx for forecast/scenario charts, plain SVG elsewhere | Stage 2 start (15 Oct) |
| 3 | ~~Deployment target~~ | **Resolved (rev 5):** continuously deployed from Stage 0 — Render (always-on + persistent disk) for the API, Vercel for Next.js; auto-deploy on green CI; demo data only (05 §12) | Resolved |
| 4 | Telegram vs email as primary digest channel | Telegram primary, SMTP secondary | Stage 3 (17 Oct) |
| 5 | Holdout size (300 vs 500 rows; ≥150 double-labelled by end of Stage 1) | 300 | Stage 1 (13 Oct) |
| 7 | Library for rendering fictional test PDFs, and number of layouts (≥3) | ReportLab, 4 layouts plus 1 unseen | Stage 4(b) start |
| 10 | Source of the India UPI narration holdout (we have no real Indian statements) | Hand-written by someone who has not seen the `in` pack rules, from publicly documented UPI/NEFT/IMPS narration formats; labelled `constructed` and reported separately | Before LOC-02 tuning (labelling starts once Stage 3 is green) |
| 11 | Whether to seek one real Indian statement sample (with the account holder's explicit consent, redacted, private-only like the owner's UK data) | No; India stays synthetic-validated and the README says so. If a consented sample appears, add it to the private track and build a built-in format profile only from it | Before Stage 4(c) |
| 12 | Pinned upstream revisions for the external India set (AyonPal PDFs, AgamiAI JSON) and who labels the 300-description sample | Pin at fetch time (commit SHA / HF revision + sha256); labelled under the §3.4a annotator rules | EVL-20 |
| 13 | Non-GBP absolute detector/materiality thresholds and goal rounding | No GBP-unit reuse or implied FX; freeze per-currency data before non-GBP advice evals | Before LOC-02 / non-GBP advice evals |
Human-review checkpoint/resume is required; production crash recovery is deferred. The joint default is already decided (`treat_as_household_pot`, Household scope). Additional bank profiles are optional data additions. Owners/dates for the actual open items are in `00` §13.

## Design review

**Strongest product differentiator — "advice that is checked, and every number has a receipt."**
Every FinPilot entry will categorise, forecast and advise; the brief itself describes that product. Foresight's edge is that an LLM never produces a displayed number. Figures are hydrated from persisted, seeded, reproducible `Calculation` records. Every recommendation also passes a Verifier that re-computes its impact and can reject it. The rejection → revision loop is logged, visible in the UI, and proven by an adversarial eval set. This hits the core loop (#2), audit trail (#7) and self-evaluation (#6) criteria at once, and it is legible to an AI code screener.

**Generality without overclaiming.** The engine is currency-agnostic (ISO 4217 minor units, currency detection, separator/date inference, per-currency forecasts) and country knowledge lives in data (`uk` and `in` locale packs). The UK path is validated on real statement structure (private, n=1) and synthetic data. India is demonstrated with persona P4 (XLS + UPI) but is **validated only on synthetic data and a constructed narration holdout**, and the README says exactly that. Currency generality is proven by EUR, JPY and mixed-currency fixtures. India is additionally tested on an **external synthetic set** from two independent open-source projects (09 §3.4b, reported as `external_synthetic`), which reduces circularity but is still not real data.

**Most important user journey — one CSV to "Can I afford £640 flights home for Christmas?"** (03, J2 → J7/J8 → J10 / prototype `onboarding.html` → `ask.html` → `lab.html`).
The fictional prototype depicts one Monzo CSV imported in three steps. Its design forecast shows a 78% chance of dipping below Amara's £300 buffer before payday. It answers that the flights are affordable in December, but the long 41-day January then drops below the buffer. The goal moves from on track to £548 short. The Verifier rejects a first draft (£90 cap, wrong impact) and approves a revised plan (+£116.39/mo) that keeps January above the buffer. The demo then accepts the plan, re-forecasts and shows the resulting goal status exactly as the engine computes it (fixture ≈ £1,418, still £82 short), plus the Lab option that would put it on track (move the date to 30 Apr); the next digest is fired by the scheduler (03 §0.1a). In one flow it demonstrates orchestration, the deterministic forecast, simulation, goal impact, grounded advice, the core loop and the evidence trail. If a judge sees only one thing, it should be this.

**Highest-risk architectural decision — the deterministic engine / LLM boundary, specifically the forecast model's quality.**
Making all numbers deterministic is the right call, but it makes forecast accuracy fully exposed: block-bootstrap Monte Carlo on 3–12 months of data may not beat naive baselines, especially for irregular income (P2). Mitigations: baselines B0–B3 and honest reporting (09), P2 reported separately, and Stage 1 puts the engine and backtest first, so any weakness surfaces on day 1, not day 7. Close second: **ingestion generality**. The claim "works with any text-based statement whose layout passes the reconciliation gate (tested on the listed layouts)" rests on the table locator, FormatProfiles/LayoutProfiles and the reconciliation gate. It is tested on unseen fictional layouts (09 `E-ING`), and the codebase must contain no bank-specific importer, but real-world variety will exceed what we test. The same applies to **currency and locale detection**: a separator or exponent mistake scales every amount ×100, so the ISO table, the detection ladder with a confirm on ambiguity, and the reconciliation gate are all on the critical path. India formats are reconstructed, not observed. The README must claim only what is measured.

**Build order (rev 5 — replaces the cut list).** One builder, one stream, in score order; every feature behind a flag that turns on (in the deployed app and the README) only when its eval suite is green; unfinished work listed under "Not shipped (planned)" (10 §11). Capacity is ≈ 85–100 h against ≈ 279 h of mandatory-stage work and ≈ 70 h of Tier 2 (10 §2), so the order — not hope — decides what ships.

**Recommended implementation sequence:**
0. **Stage 0 (12 Oct)**: register (closes 17 Oct), public repo, organiser CI + secrets green, Mesh catalogue + fallback model per agent, holdout annotator named, `features.yaml`, **deployment pipeline live** (Render API + Vercel web, auto-deploy on green CI, demo data only).
1. **Stage 1 (13–14 Oct): deterministic single-account spine.** Generator P1/P2, `csv_statement` + Monzo profile + generic mapper, `uk` pack + any-currency core, income/recurring, forecast + simulation, first committed eval numbers, persistence + calc store, thin engine-only API **deployed**. No LLM calls.
2. **Stage 2 (15–16 Oct)**: LangGraph Coordinator + 5 agents through Mesh, Advisor⇄Verifier loop with mandatory claimed impact, audit chain, cassettes, LLM suites, Ask **deployed** → **`submittable-1` by Fri 16 Oct 23:00**.
3. **Stage 3 (17–18 Oct)**: Onboarding, Briefing, scheduler + Telegram digest, Decision Lab, adaptive goals, live eval, Ledger, Evidence drawer, states — each **deployed** when green; `submittable-N` moves forward daily.
4. **Stage 4 (only after Stage 3, in order)**: (a) multi-account/joint → (b) generic `pdf_statement` + private real-data run → (c) India pack + P4 + external India set → (d) currency variants → (e) polish.
5. **Feature freeze 19 Oct 12:00; Stage 5 (19–20 Oct)**: final eval, generated README (with "Not shipped (planned)" and a private section reflecting what actually ran), video, submit by 18:00 IST. The real-data check (PRV-06) is time-boxed and non-blocking; its privacy scan always blocks.

## Real personal data (private validation track)

The owner's real UK bank statements (12 months of text-based PDFs plus two banks' CSV exports) are used **only** privately. They calibrate generator realism, support a separate private redacted holdout, test the generic importers, and feed an n=1 forecast backtest that reports aggregate metrics only. They are never committed (planned `.gitignore` and privacy hooks will block real files; neither guard exists yet) and never sent to Mesh unredacted. Their structural lessons are recorded in 00 §6b; they do **not** shape the default product. See 09 §17.


## Alignment review — 12 Oct 2026

[Review findings and validation](ALIGNMENT-REVIEW.md) records the rev 4.2 corrections and remaining implementation decisions.

Reviewed all 00–10 documents, this index, the prototype README and the six example response payloads. Register rev 4.2 §13 records the shared rules and document owners. The review aligned recurrence/detector thresholds, scenario and intent contracts, category/flow names, retry and verification rules, immutable briefing snapshots, scheduling, import limits/consent, privacy, eval targets and the PDF/private-validation release dependencies.

This remains a design specification: backend, frontend, eval harness, CI, privacy hooks and result files referenced here are planned artifacts. The static prototype and contract JSON are illustrative fixtures. Open choices remain labelled and assigned to the stage that resolves them; no product test or real-data gate has been run by this documentation review.

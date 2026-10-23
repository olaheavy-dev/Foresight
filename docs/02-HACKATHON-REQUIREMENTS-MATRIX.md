# 02 — Hackathon Requirements Traceability Matrix

> Source of truth for requirements: the official Agent Arena 2026 page (FinPilot track), as summarised in [`00`](00-DECISION-REGISTER.md) §2 (register rev 4).
> **Status, 23 Oct 2026: a record.** Foresight left the hackathon (20 Oct 2026), so requirement H (every call through Mesh) no longer applies: model calls go to OpenAI directly (`00` §12 item 14) and the Mesh route was removed on 23 Oct. The rows below are kept as they were written.
> Feature (`F-xx`) and functional requirement (`FR-xx`) IDs refer to [`01`](01-PRODUCT-REQUIREMENTS.md).
> "How a judge sees it" names the concrete artefact: a repo path, a screen, an eval output or a log/DB record. Paths follow the proposed layout (`00` §11) and are build targets, not existing files.
> **Judge path = single account.** Every mandatory requirement is demonstrable from one P1 Monzo CSV. The multi-account and PDF layers (Stage 4, flag-gated) strengthen B, C and #5 when they ship; the private real-data check (PRV-06) is time-boxed and non-blocking. The public judge path remains single-account CSV. Rev 4 adds **any-currency** handling (Tier 1) and an **India locale pack** with persona P4 (T2, synthetic-validated only); both strengthen B, D, #5 and #6 without changing the judge path.

---

## 1. Mandatory requirements A–H

| Req | Official wording (condensed) | Features | Functional reqs | How a judge sees it |
|---|---|---|---|---|
| **A. Multi-agent orchestration** | A coordinator routes work to ≥ 3 distinct agents, each with its own job and its own prompt/tools. | Coordinator + Ledger, Behaviour Analyst, Forecaster, Advisor, Verifier; F-46, F-62 | FR-56, FR-58, FR-59, FR-60 | **Code:** `backend/agents/graph.py` (StateGraph with named nodes), `backend/agents/prompts/<agent>.md` (one per agent), `backend/agents/tools/` (per-agent tool registry). **Screen:** AgentExecutionTimeline in Ask and the Evidence drawer. **DB:** `agent_steps` with ≥ 5 distinct `agent` values per P1 run. **Eval:** `evals/results/orchestration.json` (expected node-visit set per workflow). |
| **B. Ingestion & real categorisation** | CSV upload or manual logging; categories depend on the transaction (no hardcoding or randomness). | F-01–F-13, F-15–F-19, F-30, F-64–F-67, F-69 (uk); T2: F-14, F-20–F-24, F-70, F-71 | FR-01–FR-12, FR-18–FR-34, FR-73–FR-78, FR-81; T2: FR-13–FR-17, FR-82, FR-83 | **Any currency:** an EUR (comma-decimal) or JPY file imports with exact minor units; an ambiguous `$` file asks once. **India (T2):** P4 XLS with UPI narrations categorised, shown in ₹ with lakh grouping. **Screen:** `/start` step 1 (drop zone; per-file importer, matched profile and reconciliation status; one-time confirm when a format profile is LLM-proposed for an unknown bank) → step 2 "Check what we found" (confirm income, bills, subscriptions; gap questions only where detected). `/ledger` shows `method` (rule/memory/llm/user), confidence and `bank_category` per transaction. **Code:** `backend/finance_core/importers/` (`csv_statement`, `pdf_statement` — the only two importers, no bank-specific code), `backend/finance_core/importers/profiles/` (built-in Monzo and Revolut `FormatProfile`s as data), `backend/finance_core/reconcile.py`, `backend/finance_core/categorise/`, `backend/agents/nodes/ledger.py`. **Eval:** `evals/results/categorisation.json` (generated + hand-labelled holdout, vs rules-only and LLM-only), `evals/results/importers.json` (parse and reconciliation pass rate per format profile, built-in and LLM-proposed; profile-proposal accuracy on unknown-bank fixtures; corrupted fixtures rejected). **DB:** `transactions.source_row_id` → `SourceRow` → `ImportBatch` (incl. profile ID/version), `imports`, `format_profiles`, `layout_profiles`, `reconciliation_results`, `accounts`, `income_streams`. |
| **C. Behaviour & anomaly detection** | Real patterns in the user's own data, not generic observations. | F-25–F-32, F-17, F-18 | FR-29, FR-31, FR-37–FR-42 | **Screen:** Home Financial briefing (food delivery +41%; Netflix/Sky TV overlap; long January); RiskAssessment block; every finding links to supporting `txn_` rows. **Code:** `backend/finance_core/detectors/` (recurring incl. seasonal council tax, anomaly, one-off, subscription overlap, long-January). **Eval:** `evals/results/anomaly.json` (precision/recall on injected anomalies per persona), income-stream detection accuracy, one-off exclusion accuracy. Commitments, non-spend classes and one-offs are excluded from anomalies, so findings reflect real behaviour. |
| **D. Forecasting & simulation (core)** | Project the trajectory; simulate a what-if (planned purchase/savings goal) and report its effect. | F-33–F-40, F-68; T2: F-22 | FR-43–FR-48, FR-79, FR-80; T2: FR-36 | **Screen:** CashFlowForecastChart (P10–P90 band) on Home (pay-cycle lows); "Can I afford a £1,200 holiday?" in the AI Workspace → ScenarioComparison (paid 6 Nov: −£148 on 26 Nov; paid after 27 Nov: December low £1,086, £586 above the £500 buffer) + what-if rows; Decision Lab. **Code:** `backend/finance_core/forecast/`, `simulate/`, `calendar_uk.py` (payday shifts, bank holidays). **Tests:** property tests (reproducibility, empty-scenario identity, monotonicity). **Eval:** `evals/results/forecast_backtest.json` (MAE, MAPE, P10–P90 coverage, pinball loss vs 2 naive baselines), `evals/results/simulation.json`. |
| **E. Proactive grounded advice** | Specific, tied to detected patterns and forecast; generic tips score nothing. | F-41, F-42, F-48, F-52, F-57 | FR-49–FR-53, FR-64, FR-65 | **Screen:** InterventionCard ("move the £400 savings transfer to 29 Oct + keep delivery under £100 until payday → lowest balance £162 → £604; chance below buffer 100% → 2%") with cited findings, the `calc_` impact and the Checked badge. **Code:** `backend/agents/nodes/advisor.py`, `backend/finance_core/verify/` (incl. `generic_advice.py`, commitment protection). **Eval:** `evals/results/grounding.json` (evidence-ref validity, numeral-match rate, generic-tip rejection rate, commitment-protection violations = 0 expected, actual reported). |
| **F. Auditable decision trail** | Every recommendation records the pattern/forecast that triggered it. | F-44, F-45, F-46, F-11 | FR-52, FR-53, FR-58, FR-70, FR-71 | **Screen:** Evidence drawer → Why (findings and forecast) → How it was checked (every `ver_` pass, incl. the rejected £40-cap draft) → Data (supporting transactions with import provenance and reconciliation result) → Run (agent steps). **DB:** `RecommendationVersion` → `EvidenceLink`, `verification_results`, `reconciliation_results`, `audit_events` (append-only). **Eval:** `evals/results/audit_completeness.json`. |
| **G. Self-evaluation (rewarded heavily)** | Test data and measured accuracy of categorisation and forecasts, recorded in the repo. | F-58–F-61 | FR-26, FR-42, FR-48, FR-55, FR-05, FR-16 (gate eval) | **Repo:** `evals/datasets/` (generated personas in real export formats, fictional PDFs in ≥ 3 layouts, the hand-labelled holdout — all committed), `evals/runners/`, `evals/results/*.json` + `report.md` (timestamped, with model IDs, prompt versions, seeds). **README:** results table copied from the latest report. **Command:** `python -m evals.run --suite all`; deterministic suites need no key. |
| **H. Mesh API** | Every LLM/AI call routes through Mesh; otherwise invalid. | F-62 | FR-57 | **Code:** `backend/mesh/mesh_client.py` (the only module constructing an LLM client; `base_url="https://api.meshapi.ai/v1"`, key from `MESH_API_KEY`), including the `FormatProfile`/`LayoutProfile` proposal calls. **Test:** `tests/test_mesh_only.py` fails if any other module imports an LLM SDK. **CI:** critical Mesh checks green. **DB:** `provider="mesh"` on LLM `AgentStep` rows; deterministic/control rows have no provider or model. |

## 2. Bonus items

| Bonus | Features | FRs | How a judge sees it |
|---|---|---|---|
| Structured framework with an explicit analyse → forecast → advise flow (e.g. LangGraph) | Coordinator graph, F-46 | FR-56 | `backend/agents/graph.py`; graph image generated from LangGraph `get_graph()` at `docs/assets/agent-graph.png`; diagrams in `06`. |
| Goal tracking with adaptive advice | F-39, F-55 | FR-48, FR-69 | GoalProjection block when the user sets a goal (the P1 fixture has none; the demo shows the March outlook instead: £8,388 with the plan vs £8,345 with no action); "goal at risk" / "plan at risk" event; Advisor run with `target_metric=goal`. |
| Conversational layer over real data | F-49, F-50 | FR-56, FR-61–FR-63 | AI Workspace (`/workspace`) with blocks hydrated from `calc_` records; `evals/results/conversation.json` (intent routing accuracy, refusal correctness, clarifying-question rate on ambiguous scenarios). |
| Scheduled proactive delivery via a real scheduler (not a button) | F-56, F-57 | FR-64–FR-67 | `backend/scheduler/jobs.py` (APScheduler, persisted job store); `audit_events` with `actor=system, action=digest.sent`; Telegram/email screenshot in the README. |

## 3. The 8 judging criteria

| # | Criterion | Primary features | Evidence path for the AI code screener | Evidence for human judges |
|---|---|---|---|---|
| 1 | Multi-agent orchestration | Coordinator + 5 agents | `backend/agents/`, one prompt file per agent, typed contracts in `backend/agents/contracts.py` | AgentExecutionTimeline in the AI Workspace "How it was checked" tab; `06` diagrams |
| 2 | The track's core loop (checking/improving its own work) | Forecast → simulate → advise → **verify → revise** (F-33–F-42); plus the **import reconciliation gate** (F-13 CSV, Tier 1; F-14 PDF, T2): the system checks its own extraction and rejects what doesn't reconcile | `graph.py` conditional edge `verifier → advisor` (`max_revisions=2`); `verification_results`; `finance_core/reconcile.py` and `reconciliation_results` | P1 demo: £40-cap draft rejected (infeasible, still below the buffer), revised to "move the £400 savings transfer to 29 Oct + £100 cap until payday", approved; a corrupted CSV (Tier 1, `CSV-CORRUPT`, ING-15) rejected with a row-level report; corrupted PDFs only if Stage 4(b) shipped |
| 3 | Core domain capability | Forecast engine, UK payday calendar, simulation, Decision Lab | `finance_core/forecast/`, `calendar_uk.py`, property tests | Flights scenario showing the long-January dip; backtest report |
| 4 | Supporting domain capability | Categorisation, detectors, commitment/sensitive categories, advice, aliasing | `finance_core/categorise/`, `detectors/` | Home briefing findings; Transactions review queue; counterparty merge |
| 5 | Foundation, data model, real ingestion | Two generic importers (`csv_statement`; T2: XLS/XLSX through `csv_statement`, `pdf_statement`) driven by `FormatProfile`/`LayoutProfile` data, reconciliation gate, balance anchors, income detect → confirm, transfers, card handling, multi-account (T2); **workspace model; any currency** (ISO exponents, detection ladder, separator/date inference, per-currency forecasts; F-64–F-68, FR-74–FR-80); **locale packs as data** (`uk`; T2 `in`, F-69–F-71, FR-81–FR-83) | `finance_core/importers/` + `profiles/`, `finance_core/money.py` (ISO 4217 table), `finance_core/locale_packs/{uk,in}/`, `storage/models.py` (`workspaces`), `07` | 3-step onboarding; per-file reconciliation status; P3 multi-file drop and money map (T2); workspace switcher incl. P4 in ₹ with lakh grouping (T2); currency-confirm chip for an ambiguous `$` file |
| 6 | Self-evaluation | F-58–F-61; **generality variants** F-72 (EUR comma decimals, JPY zero decimals, mixed-currency workspace; T2 India P4 + constructed UPI holdout, FR-84) | `evals/` (datasets, runners, committed results); `evals/results/currency.json`; India rows in `evals/results/categorisation.json` labelled `constructed` | README results table with UK and India reported **separately** and the India synthetic-only caveat; reproducible command |
| 7 | Auditable decision trail | F-44–F-46, F-11 | `audit_events`, `verification_results`, `calculations`, `reconciliation_results` | Evidence drawer from any recommendation (≤ 2 clicks) |
| 8 | Code quality & reproducibility | NFR-05, NFR-06, NFR-12, NFR-13 | `pyproject.toml`, ruff/mypy, tests, `Makefile`, `docker-compose.yml`, `.env.example` | One-command run; CI green |

## 4. Submission and CI checks

| Check | Type | How we satisfy it | Where |
|---|---|---|---|
| All Python files compile | Critical | `python -m compileall backend evals` in our own CI job and pre-commit | `.github/workflows/ci.yml` |
| Requirements list a web framework + LLM client | Critical | `fastapi` and `openai` (used only with the Mesh base URL) in `pyproject.toml` **and** an exported `requirements.txt` | repo root |
| LLM calls route through Mesh | Critical | Sole gateway `backend/mesh/mesh_client.py` with literal `https://api.meshapi.ai/v1` | FR-57 |
| `MESH_API_KEY` valid (metadata call) | Critical | GitHub secret set in Stage 0 (`10`) | repo settings |
| `SUBMISSION_TOKEN` secret | Required | From the dashboard after registration (before 17 Oct 23:00 IST) | repo settings |
| Official workflow file | Required | Saved unmodified as `.github/workflows/agent-arena-2026-checks.yml` | repo |
| No committed `.env` | Advisory | `.gitignore` + `.env.example` | repo root |
| README present | Advisory | What we built, how agents cooperate, how to run, design decisions, self-evaluation results | `README.md` |
| `.gitignore` ignores `.env` | Advisory | Yes, plus all statement files (`*.pdf`, `*.csv`, `*.xls`, `*.xlsx`) except under `evals/datasets/**` and `evals/external/datasets/**` (explicit negations; canonical rule in 09 §17.1) to prevent real statements being committed (TSP-14) | `.gitignore` |
| Public GitHub repo | Required | Made public in Stage 0 (PLT-08), not at the end | — |
| Python backend (FastAPI/Flask) | Rule | FastAPI | `backend/app/` |
| Deployed URL (reviewed for shortlisted entries) | Optional (judging); no host is prescribed | Continuously deployed from Stage 0 on the owner's VPS (Docker Compose with PostgreSQL, Caddy TLS, images published only on green CI, Watchtower rollout); demo workspaces only; deploy SHA in the footer and `/healthz` (FR-87, `05` §12) | README link, app footer |
| Database (suggested stack: SQLite or PostgreSQL) | Suggested | PostgreSQL 16 everywhere: CI service container, `docker compose up` for judges, the deployed app (`05` §5.4) | `docker-compose.yml`, `alembic/` |

## 5. "Faked or stubbed features" penalty: how each is avoided

| Penalised pattern (official examples) | Where it could creep in for us | Guard | Verifiable proof |
|---|---|---|---|
| **Hardcoded outputs** | The `00` §10a P1 figures copied into UI or code | Fixtures are design-only. UI reads the API; a test greps `backend/` and `frontend/src` for fixture literals (e.g. `2,184.50`, `286.40`) outside `evals/`, `design/` and tests (`design/` is exempt only because every file there carries a visible "illustrative design artefact, never loaded at runtime" label) | `tests/test_no_fixture_literals.py`; values change when P2/P3 or another seed is loaded |
| Hardcoded categories | The rules table mistaken for hardcoding; Monzo's own category copied through | Categories come from the pipeline; Monzo's category is only a feature (FR-19); the holdout set is unseen by rule authors | `method` distribution per import; holdout accuracy vs rules-only |
| **An agent never called** | Verifier skipped when the output "looks fine"; Ledger Agent unused because rules cover the demo | Unconditional verification edge; the P1 fixture contains descriptions the rules don't resolve, so the Ledger LLM path is exercised; orchestration eval asserts node visits | `evals/results/orchestration.json`; `agent_steps` per run |
| **A loop that never loops** | Verifier always approves | Deterministic rejection rules (FR-50) and the adversarial set (FR-55); any naturally flawed P1 proposal is rejected from its computed data; injected adversarial cases independently prove the loop without scripting a normal run | `evals/results/verifier.json`; `verification_results` with `round > 1` |
| **A test set that does not exist** | Numbers only quoted in the README | Datasets and results committed; README table generated from `report.md`; seeds and model IDs recorded | `evals/datasets/`, `evals/results/` |
| Fake scheduler | "Send digest" button as the only trigger | APScheduler job; the test button is labelled and logged as `actor=user` | `audit_events` with `actor=system, action=digest.sent` |
| Fake forecast (LLM-guessed numbers) | Narrative states balances | Numbers only from `calculations`; numeral post-check (FR-42, FR-49) | `calc_` IDs on every block; reproducibility tests |
| Fake import support (LLM transcribes statements; "any bank" claimed but only hardcoded banks work) | LLM asked to "read the file"; bank-specific code paths | The LLM proposes only a `FormatProfile`/`LayoutProfile` from redacted rows; no bank names in importer code (FR-03 test); extraction is deterministic; the reconciliation gate rejects anything that doesn't balance | `evals/results/importers.json` per-format-profile/layout pass rate; `reconciliation_results` |
| Fake locale/currency support ("any currency" or "India supported" claimed but untested) | README claims beyond the evals; amounts silently assumed to have 2 decimals | Claims limited to measured variants; ISO exponent round-trip property tests (FR-75); India results labelled constructed/synthetic-only (FR-84); no built-in Indian profiles claimed | `evals/results/currency.json`; India holdout rows tagged `constructed`; README caveat text |
| **Half-built features shown to judges** (rev 5) | UI surfaces or README claims for work that ran out of time | Every feature behind a flag in `features.yaml`; a flag can be on only when its eval suites are green (CI-enforced); unfinished work hidden in the UI and listed under "Not shipped (planned)" in the generated README (FR-86) | `features.yaml`, CI flag check, README "Not shipped" section |
| Fake "real data" analysis | Generic insights ("people often overspend on takeaways") | Findings must cite detector output and `txn_` IDs; generic-advice check | `evals/results/grounding.json` |

## 6. Feature → requirement coverage (reverse index)

Columns A–H are the mandatory requirements; "Bonus" names the bonus served. **T2** features are Stage 4 items: flag-gated, attempted in order after Stage 3, and listed as "Not shipped (planned)" if unfinished.

| Feature | A | B | C | D | E | F | G | H | Bonus |
|---|---|---|---|---|---|---|---|---|---|
| F-01 Demo workspaces | | ● | | | | | ● | | |
| F-02 `csv_statement` importer | | ● | | | | | | | |
| F-03 `FormatProfile` library (built-in + LLM-proposed) | ● | ● | | | | ● | | ● | |
| F-04 Manual entry | | ● | | | | | | | |
| F-05 Description normalisation | | ● | | | | | | | |
| F-06 Hybrid categorisation | ● | ● | | | | | | ● | |
| F-07 Categorisation review | | ● | | | | ● | | | |
| F-08 Own-transfer pairing | | ● | ● | | | | ● | | |
| F-09 Duplicate detection | | ● | | | | | ● | | |
| F-10 Balance anchors | | ● | | ● | | | | | |
| F-11 Import history/undo | | ● | | | | ● | | | |
| F-12 `ImportSource` interface | | ● | | | | | | | |
| F-13 Reconciliation gate | | ● | | | | ● | ● | | |
| F-14 `pdf_statement` importer (T2) | ● | ● | | | | ● | ● | ● | |
| F-15 Drop zone + per-file status | | ● | | | | ● | | | |
| F-16 Account model | | ● | | ● | | | | | |
| F-17 Income detect → confirm | | ● | ● | ● | | ● | ● | | |
| F-18 Non-spend outflow classes | | ● | ● | ● | | | | | |
| F-19 Credit-card handling | | ● | ● | ● | | | ● | | |
| F-20 Coverage-gap prompts (T2) | | ● | ● | ● | | ● | | | |
| F-21 Joint accounts (T2) | | ● | ● | | ● | ● | | | |
| F-22 Scope selector (T2) | | | | ● | | | | | |
| F-23 Money map (T2) | | ● | | | | | | | |
| F-24 Counterparty aliasing | | ● | ● | | | ● | | | |
| F-25 Recurring detection | | | ● | ● | | | ● | | |
| F-26 Category anomaly | | | ● | | | | ● | | |
| F-27 Subscription detectors | | | ● | | ● | | | | |
| F-28 One-off detection | | | ● | ● | | | ● | | |
| F-29 Long-January insight | | | ● | ● | ● | | | | |
| F-30 Commitment/sensitive categories | | ● | ● | | ● | | | | |
| F-31 Agent-written findings | ● | | ● | | ● | ● | | ● | |
| F-32 Finding feedback | | | ● | | | ● | | | |
| F-33 Baseline forecast | | | | ● | | | ● | | |
| F-34 UK payday calendar | | | | ● | | | ● | | |
| F-35 Forecast versioning | | | | ● | | ● | | | |
| F-36 `ScenarioSpec` | | | | ● | | | ● | | |
| F-37 NL scenario parsing | ● | | | ● | | | ● | ● | Conv. |
| F-38 Decision Lab | | | | ● | | | | | |
| F-39 Goal projection | | | | ● | ● | | | | Goals |
| F-40 Backtesting | | | | ● | | | ● | | |
| F-41 Advisor | ● | | | | ● | ● | | ● | |
| F-42 Verifier loop | ● | | | | ● | ● | ● | ● | LangGraph |
| F-43 Rec. lifecycle/outcome | | | | | ● | ● | | | Goals |
| F-44 Evidence drawer | | | | | | ● | | | |
| F-45 Audit events | | | | | | ● | | | |
| F-46 Agent observability | ● | | | | | ● | | ● | LangGraph |
| F-47 3-step onboarding | | ● | | | | | | | |
| F-48 Home | | | ● | ● | ● | | | | Sched. |
| F-49 AI Workspace | ● | | ● | ● | ● | | | ● | Conv. |
| F-50 Generative UI | ● | | | ● | ● | ● | | | Conv. |
| F-51 Transactions | | ● | | | | ● | | | |
| F-52 Insight feed | | | ● | ● | ● | ● | | | |
| F-53 Settings/data rights | | ● | | | | | | | Sched. |
| F-54 Themes/responsive | | | | | | | | | |
| F-55 Goals | | | | ● | ● | | | | Goals |
| F-56 Digest | | | | | ● | ● | | ● | Sched. |
| F-57 Proactive job | ● | | ● | ● | ● | ● | | ● | Sched. |
| F-58 Persona generator (CSV; PDF T2) | | ● | | | | | ● | | |
| F-59 Holdout set | | | | | | | ● | | |
| F-60 Eval runner | | | | | | | ● | | |
| F-61 Baselines | | | | | | | ● | | |
| F-62 Mesh gateway | ● | | | | | | | ● | |
| F-63 One-command run | | | | | | | ● | | |
| F-64 Workspace model | | ● | | | | ● | | | |
| F-65 Any-currency minor units | | ● | | ● | | | ● | | |
| F-66 Currency detection | | ● | | | | | ● | | |
| F-67 Number/date inference | | ● | | | | | ● | | |
| F-68 Per-currency forecasts | | | | ● | | | ● | | |
| F-69 Locale packs (`uk`; T2 `in`) | | ● | ● | ● | ● | | | | |
| F-70 India pack + P4 (T2) | | ● | ● | ● | ● | | ● | | |
| F-71 XLS via `csv_statement` (T2) | | ● | | | | | | | |
| F-72 Generality eval variants | | ● | | ● | | | ● | | |
| F-73 Feature flags + generated release notes | | | | | | ● | ● | | judging #8 (release integrity) |
| F-74 Continuous deployment | | | | | | | | | human round (deployed URL), judging #8 |

F-54 maps to no requirement on purpose. It serves human judges and the demo video only, so it sits late in the build order (`01` §6, `10` §11).

## 7. FR → requirement index

| Requirement | FRs |
|---|---|
| A. Orchestration | FR-56, FR-58, FR-59, FR-60 |
| B. Ingestion & categorisation | FR-01–FR-12, FR-18–FR-34, FR-73, FR-74–FR-78, FR-81; T2: FR-13–FR-17, FR-82, FR-83 |
| C. Behaviour & anomalies | FR-29, FR-31, FR-37–FR-42 |
| D. Forecast & simulation | FR-43–FR-48, FR-79, FR-80; T2: FR-36 |
| E. Proactive grounded advice | FR-22, FR-23, FR-35, FR-49–FR-54, FR-64–FR-69, FR-85 |
| F. Audit trail | FR-05, FR-52, FR-53, FR-58, FR-70, FR-71 |
| G. Self-evaluation | FR-05, FR-16, FR-26, FR-42, FR-48, FR-55, FR-75–FR-77, FR-84 (+ eval suites in `09`) |
| H. Mesh | FR-04, FR-14, FR-57 |
| Bonus: conversation | FR-48, FR-61–FR-63 |
| Bonus: scheduling | FR-64, FR-67 |
| Bonus: goals | FR-48, FR-69 |
| Release integrity & deployment (judging #8; human round) | FR-86, FR-87 |
| Trust & data rights | FR-34, FR-35, FR-70–FR-73, TSP-01–TSP-15 |

# Eval run evalrun_20261013T230650Z_adfe612

- Commit `adfe612` · 2026-10-13T23:06:50Z · mode deterministic
- Engine fc-1.3.0 · generator gen-1.0.0 · seed 1729
- Deterministic suites only; LLM arms are Stage 2+ and shown as —.

## Headline

| Metric | Value | Comparison |
|---|---|---|
| Categorisation accuracy · macro-F1 (rules-only, P1+P2 test split, n=498) | 0.942 · 0.807 | majority class 0.205 |
| Forecast MAE @30 d, P1 (£) | 536.59 | best baseline B0 765.73 (skill 0.299) |
| Forecast P10–P90 coverage, P1 | 0.811 | nominal 0.80 |
| CSV reconciliation: corrupted files caught | 20/20 | clean tables rejected: 0 |

## Gates

| Suite | Gate | Rule applied | Failed targets | Not measured |
|---|---|---|---|---|
| E-ANOM | **fail** | docs/09 targets (4 measured) | ANOM-precision, ANOM-fp | — |
| E-AUD | **pass** | docs/09 targets (5 measured) | — | — |
| E-CAT | **pass** | docs/09 targets (1 measured) | — | CAT-hybrid-acc, CAT-hybrid-f1, CAT-hybrid-flow, CAT-selective |
| E-CTX | **fail** | docs/09 targets (5 measured) | CTX-2, CTX-3 | — |
| E-EFF | **pass** | docs/09 targets (4 measured) | — | EFF-5, EFF-6, EFF-7 |
| E-FC | **pass** | docs/09 targets (6 measured) | — | — |
| E-GRD | **pass** | docs/09 targets (5 measured) | — | — |
| E-INC | **pass** | docs/09 targets (5 measured) | — | — |
| E-ING | **pass** | docs/09 targets (12 measured) | — | ING-heuristic+llm |
| E-LOC | **pass** | docs/09 targets (6 measured) | — | — |
| E-ORC | **pass** | docs/09 targets (4 measured) | — | — |
| E-REC | **pass** | docs/09 targets (5 measured) | — | — |
| E-SCN | **pass** | docs/09 targets (4 measured) | — | — |
| E-SEC | **pass** | docs/09 targets (6 measured) | — | — |
| E-SIM | **pass** | docs/09 targets (1 measured) | — | — |
| E-UI | **pass** | docs/09 targets (8 measured) | — | — |
| E-VER | **pass** | docs/09 targets (3 measured) | — | — |

Not run (gate `fail` until they exist): E-ALIAS, E-XFER, E-ACCT.

Gate rule: a suite errors → fail; else if any docs/09 target that applies to Stage 1 was measured, every measured one must be met; else the suite passes if it ran without errors. A null target is never counted as met.

## Targets

### E-ING (ingestion) · 0.73 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| ING-format-unseen-llm | FormatProfile success, unseen layouts (heuristic + Ledger Agent) | C1–C4 | 1.000 | >= 0.85 | ✓ | yes |
| ING-locator-P | Table locator precision (built-in + common) | P1-base, P2-base, S14-side-account, S8-salary-split, G1-eur | 1.000 | >= 1.0 | ✓ | yes |
| ING-locator-R | Table locator recall (built-in + common) | P1-base, P2-base, S14-side-account, S8-salary-split, G1-eur | 1.000 | >= 1.0 | ✓ | yes |
| ING-locator-unseen | Table locator recall (C1–C4) | C1–C4 | 1.000 | >= 0.95 | ✓ | yes |
| ING-junk | Junk rows parsed as transactions | all | 0.000 | == 0 | ✓ | yes |
| ING-builtin-match | Built-in profile match rate | Monzo, Revolut | 1.000 | >= 1.0 | ✓ | yes |
| ING-false-match | Built-in false match rate | generic, C1–C4 | 0.000 | <= 0.0 | ✓ | yes |
| ING-parse-P | Row precision (built-in formats) | Monzo, Revolut | 1.000 | >= 1.0 | ✓ | yes |
| ING-parse-R | Row recall (built-in formats) | Monzo, Revolut | 1.000 | >= 1.0 | ✓ | yes |
| ING-corrupt | CSV-CORRUPT defects detected | CSV-CORRUPT (20) | 1.000 | >= 1.0 | ✓ | yes |
| ING-clean-rejected | Clean tables rejected | P1-base, P2-base, S14-side-account, S8-salary-split, G1-eur | 0.000 | == 0 | ✓ | yes |
| ING-honest | Balance-free files labelled reconciled | P1-base, P2-base, S14-side-account, S8-salary-split, G1-eur | 0.000 | == 0 | ✓ | yes |
| ING-heuristic+llm | FormatProfile success, heuristic+LLM | C1–C4 | — | >= 0.85 | — | yes |

- C1–C4 also run heuristic+llm: the Ledger Agent's proposed FormatProfile, replayed from recorded Mesh responses, with the user's confirmation simulated (§4.1.3).
- CSV-CORRUPT files that raise a blocking question are re-imported with the locale default answer, as a user accepting the pre-selected option would.
- Truth row match = equal date and signed amount to the penny (multiset).

### E-LOC (locales) · 0.33 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| E-LOC-1 | Currency detection | P1-base, G1-eur, S14-side-account | 1.000 | >= 1.0 | ✓ | yes |
| E-LOC-2 | Ambiguous $ asked, nothing committed | G3 | 1.000 | == 1 | ✓ | yes |
| E-LOC-3 | Number format inference | P1-base, P2-base, G1-eur, S14-side-account | 1.000 | >= 1.0 | ✓ | yes |
| E-LOC-4 | Date order inference (files with day > 12) | P1-base, P2-base, G1-eur, S14-side-account | 1.000 | >= 1.0 | ✓ | yes |
| E-LOC-5 | Minor units exact | P1-base, P2-base, G1-eur, S14-side-account | 1.000 | == 1 | ✓ | yes |
| E-LOC-13 | H13: uncommitted until answered · 0 LLM calls · 0 repeat questions | G3, G5 | 1.000 | == 1 | ✓ | yes |

- E-LOC-6 and E-LOC-7 are null: G4 and the XLS/XLSX exports are not generated yet.
- E-LOC-13 answers with the truth value (USD for G3, the file's real date order for G5).
- LLM calls are 0 by construction: finance_core has no model client.

### E-CAT (categorisation) · 0.53 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| CAT-hybrid-acc-generated | Accuracy, hybrid (generated test split) | P1, P2 test split | 0.942 | >= 0.93 | ✓ | yes |
| CAT-hybrid-acc | Accuracy, hybrid (holdout) | UK holdout | — | >= 0.85 | — | yes |
| CAT-hybrid-f1 | Macro-F1, hybrid (holdout) | UK holdout | — | >= 0.8 | — | yes |
| CAT-hybrid-flow | Flow-class accuracy, hybrid (holdout) | UK holdout | — | >= 0.95 | — | yes |
| CAT-selective | Selective accuracy@0.85 (holdout) | UK holdout | — | >= 0.95 | — | yes |

- Hybrid and LLM-only arms replay recorded Mesh responses (evals/cassettes); the holdout targets stay null until the UK hand-labelled holdout exists.
- Majority-class baseline predicts 'groceries' (most frequent dev-split label).

### E-INC (income) · 0.81 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| INC-1-P | Salaried stream precision | P1-base, P2-base, S8-salary-split, S11-fourweekly | 1.000 | >= 0.95 | ✓ | yes |
| INC-1-R | Salaried stream recall | P1-base, P2-base, S8-salary-split, S11-fourweekly | 1.000 | >= 0.95 | ✓ | yes |
| INC-2 | Amount within ±2% (matched salaried) | P1-base, P2-base, S8-salary-split, S11-fourweekly | 1.000 | >= 1.0 | ✓ | yes |
| INC-3 | Payday rule and next payday exact (monthly) | P1-base, P2-base, S8-salary-split | 1.000 | >= 1.0 | ✓ | yes |
| INC-4 | Four-weekly pay detected as 28-day cadence | S11 | 1.000 | == 1 | ✓ | yes |

- Detected streams are matched to truth by the majority truth `income` key of their member transactions; a truth stream counts as found when ≥ 50% of its rows are members (of regular streams, for salaried truth streams).
- INC-3 compares the detected rule's paydays over the history with the truth rule's paydays (a payer's late or missed credit is not a wrong rule), and the predicted next payday after as_of with the truth rule's next payday. paydays_equal_credit_dates reports how often the rule also matches every actual credit date (P2's client paid June late).
- S8 split salary: amounts of the streams matched to one truth source are summed (INC-7).

### E-REC (recurring) · 0.43 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| REC-P | Obligation precision | P1-base, P2-base | 1.000 | >= 0.9 | ✓ | yes |
| REC-R | Obligation recall | P1-base, P2-base | 0.920 | >= 0.9 | ✓ | yes |
| REC-amount | Median amount error | P1-base, P2-base | 0.000 | <= 0.02 | ✓ | yes |
| REC-next-date | Median next-date error (days) | P1-base, P2-base | 0 | <= 2 | ✓ | yes |
| REC-council-tax | Council tax active Apr–Jan only | P1-base, P2-base | 1.000 | == 1 | ✓ | yes |

- A detected obligation matches a truth obligation when most of its member transactions carry that truth `recurring` key and the cadence agrees.
- Per-dataset medians are combined by taking the worst dataset.
- Next-date error: predicted first occurrence after as_of (finance_core obligation calendar) vs the truth anchor day and day rule.
- Price rise: detection replayed with the ledger cut one billing cycle (31 days) after the rise. Overlap: the truth pair must sit inside one detected subscription family. Both are reported, not gated (docs/09 §6.5 sets no numeric target for them).

### E-ANOM (anomalies) · 0.82 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| ANOM-recall | Recall (category trends) | P1-base, P2-base | 1.000 | >= 0.85 | ✓ | yes |
| ANOM-precision | Precision (category trends) | P1-base, P2-base | 0.500 | >= 0.75 | ✗ | yes |
| ANOM-fp | False positives per persona-month (clean) | P1-clean, P2-clean | 1.000 | <= 0.5 | ✗ | yes |
| ANOM-magnitude | Surge magnitude error (pp) | P1-base, P2-base | 0.000 | <= 5 | ✓ | yes |

- Trend part only: one 30-day window at as_of per persona, so one persona-month each.
- A spike matches an injected anomaly when its category equals the anomaly subject.

### E-FC (forecast) · 10.32 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| FC-skill-B1 | Skill vs B1-repeat30, MAE(30) | P1 | 0.572 | >= 0.2 | ✓ | yes |
| FC-skill-B2 | Skill vs B2-meanflow, MAE(30) | P1 | 0.572 | >= 0.15 | ✓ | yes |
| FC-mase | MASE(30) | P1 | 0.533 | < 1.0 | ✓ | yes |
| FC-mase-vs-best | MASE(30) ÷ best naive baseline MASE(30) | P1 | 0.689 | < 1.0 | ✓ | yes |
| FC-coverage-P1 | P10–P90 coverage (all h) | P1-base | 0.811 | 0.72–0.88 | ✓ | yes |
| FC-coverage-P2 | P10–P90 coverage (all h) | P2-base | 0.875 | 0.72–0.88 | ✓ | yes |

- Inputs are built from detected data with finance_core only; truth is used for the anchor balance at each origin and for scoring.
- Discretionary history passed to the engine covers up to 365 days before each origin and every unscheduled outflow (not only spending); the engine bootstraps everyday outflows from the last 90 days and models one-offs over the span.
- Headline numbers simulate the user confirming detected income at onboarding (06 H8): the top 3 unconfirmed payers at each origin are answered from the truth labels. The no-confirmation arm (detection only) is reported alongside in forecast.arms.
- S4-shock coverage after the shift is expected to miss (docs/09 §7.4) and is not gated.
- Every forecast carries the ONS FYE 2025 irregular-expense prior (docs/07 §6.2b) and is calibrated from the engine's own earlier forecasts, scored only up to the origin (docs/07 §6.8a). Dev/test splits are in forecast.by_split.
- MAPE is reported but no longer a target (owner decision 13 Oct 2026): it divides by a balance that is near £0 at the pre-payday lows. FC-mase replaces FC-mape.
- Breach Brier and the long-January check are not computed yet.

### E-SIM (simulation) · 15.95 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| SIM | Properties passed (SIM-1/2/3/6) | P1-base | 1.000 | >= 1.0 | ✓ | yes |

- 200 seeded cases per property; one-off amounts £0.01–£3,000 on a random horizon day; income delays of 1–10 days on the first payday in the horizon.
- SIM-6 checks that only a contiguous window starting at the payday changes, that it spans at least the delay, and that the end balance is unchanged when the pay lands in horizon.

### E-SEC (security) · 0.28 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| SEC-1 | Chat attacks reaching the specialists after Understand (upper bound) | 40 chat | 0.000 | == 0 | ✓ | yes |
| SEC-2 | Data-plane attacks reaching a model verbatim | 40 data-plane | 0.000 | == 0 | ✓ | yes |
| SEC-3 | suspicious_text rows never sent verbatim | 40 data-plane | 1.000 | >= 1.0 | ✓ | yes |
| SEC-4 | Canary leaks reaching the UI (simulated outputs) | 2 canary outputs | 0.000 | == 0 | ✓ | yes |
| SEC-5 | False refusals on benign questions | 346 questions | 0.000 | <= 0.02 | ✓ | yes |
| SEC-6 | False suspicious_text flags on benign imported text | 20348 narrations/headers/filenames | 0.000 | <= 0.005 | ✓ | yes |

- Rule pack guard-1.3.0+e14b963e. Deterministic layers only; the injection and dev sets were written together with the first rule pack, and the pack may be tuned on the dev set only.
- First run (guard-1.0.0, before any tuning) on this test set: 34/40 chat attacks blocked at the screen, 37/40 data-plane attacks flagged (3 would have reached a model verbatim: two filenames and one PDF line), 1/60 benign questions refused, 0/20,348 benign texts flagged. guard-1.1.0 then refused one legitimate what-if from the E-SCN set ('set the buffer to zero'); guard-1.2.0 limits that rule to imported data.
- Simulated model outputs (canary, URL, numerals, product advice) test the output screen without a model call.

### E-SCN (scenarios) · 0.28 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| SCN-exact | Exact match of the ScenarioSpec | 80 prompts | 0.857 | >= 0.85 | ✓ | yes |
| SCN-amount | Amount field accuracy | 80 prompts | 0.984 | >= 0.95 | ✓ | yes |
| SCN-date | Date field accuracy | 80 prompts | 0.986 | >= 0.95 | ✓ | yes |
| SCN-clarify-R | Clarification recall | 10 ambiguous prompts | 1.000 | >= 0.8 | ✓ | yes |

- mode: replay

### E-VER (verifier) · 18.47 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| VER-catch | Bad proposals caught | 62 bad | 1.000 | >= 0.95 | ✓ | yes |
| VER-catch-det | Caught, deterministic defect types | deterministic defect types | 1.000 | == 1.0 | ✓ | yes |
| VER-false-rej | Good proposals falsely rejected | 34 good | 0.000 | <= 0.1 | ✓ | yes |

- mode: replay

### E-GRD (grounding) · 7.24 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| GRD-refs | Evidence refs resolve | approved | 1.000 | == 1.0 | ✓ | yes |
| GRD-numbers | No model-written numbers | approved | 1.000 | >= 0.98 | ✓ | yes |
| GRD-generic | Generic advice among approved | approved | 0.000 | == 0.0 | ✓ | yes |
| GRD-commitment | Unrequested cuts to protected categories | approved | 0.000 | == 0.0 | ✓ | yes |
| GRD-swap | Swap test: other persona's advice fails | approved | 1.000 | == 1.0 | ✓ | yes |

- mode: replay

### E-CTX (conversation) · 0.56 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| CTX-1 | Follow-up intent accuracy (turn ≥ 2) | 45 follow-up turns | 0.956 | >= 0.9 | ✓ | yes |
| CTX-2 | Follow-up slot exact match | 45 follow-up turns | 0.644 | >= 0.85 | ✗ | yes |
| CTX-3 | Standalone rewrite adequacy | 45 rewrites | 0.889 | >= 0.9 | ✗ | yes |
| CTX-4 | Cache hit rate, paraphrase pairs | 20 pairs | 0.900 | >= 0.9 | ✓ | yes |
| CTX-5 | False cache hits, near-miss pairs | 20 pairs | 0.000 | == 0 | ✓ | yes |

- Real Understand prompt and schema through the product's Mesh client, replay mode; every request recorded.
- Targets are Stage 2: reported, not gating the Stage 1 build (stage1=false).

### E-UI (ui) · 85.66 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| UI-8 | Intent accuracy (Understand) | 60 questions | 0.947 | >= 0.9 | ✓ | yes |
| UI-8b | Low-confidence questions clarified | clarify rows | 1.000 | >= 1.0 | ✓ | yes |
| UI-1 | Schema validity | 60 answers | 1.000 | >= 0.98 | ✓ | yes |
| UI-2 | Block-selection precision | 60 answers | 0.953 | >= 0.85 | ✓ | yes |
| UI-2b | Block-selection recall | 60 answers | 0.842 | >= 0.8 | ✓ | yes |
| UI-7 | Overview budget respected | 60 answers | 1.000 | >= 1.0 | ✓ | yes |
| UI-9 | Tab placement | 60 answers | 1.000 | >= 1.0 | ✓ | yes |
| UI-10 | Answer skeleton followed | 60 answers | 1.000 | >= 1.0 | ✓ | yes |

- replay mode; 0 Understand requests not recorded.
- Composition scores depend on the specialist nodes present when they were recorded (compose's value catalogue follows their outputs); re-record after specialist changes.

### E-EFF (efficiency) · 0.0 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| EFF-1 | Mean cost per answer (USD) | 60 E-UI answers | 0.011 | <= 0.03 | ✓ | yes |
| EFF-2 | Mean cost per advice answer (USD) | 13 advice answers | 0.049 | <= 0.05 | ✓ | yes |
| EFF-3 | p95 cost per answer (USD) | 60 E-UI answers | 0.069 | <= 0.1 | ✓ | yes |
| EFF-4 | Time to first progress step, p95 (s) | 60 E-UI answers | 0.020 | <= 2.0 | ✓ | yes |
| EFF-5 | Simple answer latency p50 (s) | 47 simple answers | — | <= 10.0 | — | yes |
| EFF-6 | Advice answer latency p50 (s) | 13 advice answers | — | <= 35.0 | — | yes |
| EFF-7 | Advice answer latency p95 (s) | 13 advice answers | — | <= 60.0 | — | yes |

- replay mode. Latency is measured only in replay, from the live latency each cassette stores; an answer with an older recording (no latency) leaves its group's latency not measured. Latency measured on 3 of 60 answers. 0 answers with a failed or unrecorded model step are left out of every statistic.
- Where latency is not measured, `latency_estimated_*` counts each unmeasured call at its tier's measured median call latency; it is an estimate and decides no target.
- End-to-end = local time in replay + each step's model wait (concurrent judge calls overlap) − the Understand/prefetch overlap. Network and server time outside Mesh calls are not included.

### E-ORC (orchestration) · 67.65 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| ORC-pass | Case pass rate (all 30; not recorded or not built count as unmet) | 30 cases | 0.933 | >= 1.0 | ✗ | no (opted out) |
| ORC-pass-built | Case pass rate (cases whose feature is built; not recorded counts as unmet) | 28 cases | 1.000 | >= 1.0 | ✓ | yes |
| ORC-pass-measured | Case pass rate (cases that ran) | 28 cases | 1.000 | >= 1.0 | ✓ | yes |
| ORC-2 | All six node types reached | coverage table | 1 | == 1 | ✓ | yes |
| ORC-3 | Agents distinct (prompts, tool allow-lists) | all runs | 1 | == 1 | ✓ | yes |

- replay mode; 0 case(s) not recorded, 2 not measured (feature not built).
- ORC-4/5 stub only the Advisor (steps carry the model `stub/advisor`); the Verifier, its judge and everything else are real. ORC-6/7 run on a scripted transport.
- Ingestion cases run on the seeded demo (the export named in the case is already imported); the Home briefing slot is reached but the briefing is PRO-01 (not built).
- `daily_0630` is the 06:30 cron slot, routed as the `daily_refresh` system event.
- ORC-10 (budget, ORC-C024) is asserted as docs/09 defines it: the run stops gracefully with run_budget_exceeded, a partial flag and a deterministic answer. The case also lists all five agents, which a 3-call budget cannot always reach (a node may need a repair call); that list is not asserted, and the case file is unchanged.

### E-AUD (audit) · 11.57 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| AUD-complete | Audit completeness (unbroken chains) | 9 recommendations | 1.000 | >= 1.0 | ✓ | yes |
| AUD-hashchain | Audit event hash chain intact | P1, P2 audit log | 1.000 | >= 1.0 | ✓ | yes |
| AUD-recompute | Recomputability (identical result hash) | 11 calculations | 1.000 | >= 1.0 | ✓ | yes |
| AUD-rejected | Rejected/withdrawn traceability | 12 rejections | 1.000 | >= 1.0 | ✓ | yes |
| AUD-provenance | Provenance labels on chain calculations | 8 calculations | 1.000 | >= 1.0 | ✓ | yes |

- replay mode. Advisor drafts and judge verdicts are scripted (stub/advisor, stub/judge in the step rows); the chain under test is written by the product's code.
- The P1 canonical live traces are not re-walked: their recorded model requests depend on wall-clock deadlines, so a replay would take a different path.

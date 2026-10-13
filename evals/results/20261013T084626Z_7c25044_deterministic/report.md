# Eval run evalrun_20261013T084626Z_7c25044

- Commit `7c25044` · 2026-10-13T08:46:26Z · mode deterministic
- Engine fc-1.2.0 · generator gen-1.0.0 · seed 1729
- Deterministic suites only; LLM arms are Stage 2+ and shown as —.

## Headline

| Metric | Value | Comparison |
|---|---|---|
| Categorisation accuracy · macro-F1 (rules-only, P1+P2 test split, n=498) | 0.861 · 0.765 | majority class 0.205 |
| Forecast MAE @30 d, P1 (£) | 552.54 | best baseline B0 765.73 (skill 0.278) |
| Forecast P10–P90 coverage, P1 | 0.584 | nominal 0.80 |
| CSV reconciliation: corrupted files caught | 20/20 | clean tables rejected: 0 |

## Gates

| Suite | Gate | Rule applied | Failed targets | Not measured |
|---|---|---|---|---|
| E-ANOM | **fail** | docs/09 targets (4 measured) | ANOM-precision, ANOM-fp | — |
| E-CAT | **pass** | ran without errors | — | — |
| E-FC | **fail** | docs/09 targets (5 measured) | FC-mape, FC-coverage-P1 | — |
| E-INC | **pass** | docs/09 targets (5 measured) | — | — |
| E-ING | **pass** | docs/09 targets (11 measured) | — | — |
| E-LOC | **pass** | docs/09 targets (6 measured) | — | — |
| E-REC | **pass** | docs/09 targets (5 measured) | — | — |
| E-SIM | **pass** | docs/09 targets (1 measured) | — | — |

Not run (gate `fail` until they exist): E-ALIAS, E-XFER, E-ACCT, E-SCN, E-GRD, E-VER, E-ORC, E-UI, E-AUD.

Gate rule: a suite errors → fail; else if any docs/09 target that applies to Stage 1 was measured, every measured one must be met; else the suite passes if it ran without errors. A null target is never counted as met.

## Targets

### E-ING (ingestion) · 0.4 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
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
| ING-heuristic+llm | FormatProfile success, heuristic+LLM | C1–C4 | — | >= 0.85 | — | no (later stage) |

- C1–C4 run heuristic-only: the LLM FormatProfile proposal (§4.1.3) is Stage 2.
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

### E-CAT (categorisation) · 0.38 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| CAT-hybrid-acc-generated | Accuracy, hybrid (generated test split) | P1, P2 test split | — | >= 0.93 | — | no (later stage) |
| CAT-hybrid-acc | Accuracy, hybrid (holdout) | UK holdout | — | >= 0.85 | — | no (later stage) |
| CAT-hybrid-f1 | Macro-F1, hybrid (holdout) | UK holdout | — | >= 0.8 | — | no (later stage) |
| CAT-hybrid-flow | Flow-class accuracy, hybrid (holdout) | UK holdout | — | >= 0.95 | — | no (later stage) |
| CAT-selective | Selective accuracy@0.85 (holdout) | UK holdout | — | >= 0.95 | — | no (later stage) |

- Every docs/09 §5.3 target is for the hybrid arm or the UK holdout; neither exists in Stage 1, so they are listed unmet-unknown (null) and the gate uses 'ran without errors'.
- Majority-class baseline predicts 'groceries' (most frequent dev-split label).

### E-INC (income) · 0.8 s

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

### E-REC (recurring) · 0.38 s

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

### E-ANOM (anomalies) · 0.74 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| ANOM-recall | Recall (category trends) | P1-base, P2-base | 1.000 | >= 0.85 | ✓ | yes |
| ANOM-precision | Precision (category trends) | P1-base, P2-base | 0.200 | >= 0.75 | ✗ | yes |
| ANOM-fp | False positives per persona-month (clean) | P1-clean, P2-clean | 2.000 | <= 0.5 | ✗ | yes |
| ANOM-magnitude | Surge magnitude error (pp) | P1-base, P2-base | 0.000 | <= 5 | ✓ | yes |

- Trend part only: one 30-day window at as_of per persona, so one persona-month each.
- A spike matches an injected anomaly when its category equals the anomaly subject.

### E-FC (forecast) · 5.55 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| FC-skill-B1 | Skill vs B1-repeat30, MAE(30) | P1 | 0.559 | >= 0.2 | ✓ | yes |
| FC-skill-B2 | Skill vs B2-meanflow, MAE(30) | P1 | 0.559 | >= 0.15 | ✓ | yes |
| FC-mape | MAPE(30) | P1 | 0.498 | <= 0.12 | ✗ | yes |
| FC-coverage-P1 | P10–P90 coverage (all h) | P1-base | 0.584 | 0.72–0.88 | ✗ | yes |
| FC-coverage-P2 | P10–P90 coverage (all h) | P2-base | 0.834 | 0.72–0.88 | ✓ | yes |

- Inputs are built from detected data with finance_core only; truth is used for the anchor balance at each origin and for scoring.
- Discretionary history passed to the engine covers up to 365 days before each origin and every unscheduled outflow (not only spending); the engine bootstraps everyday outflows from the last 90 days and models one-offs over the span.
- Headline numbers simulate the user confirming detected income at onboarding (06 H8): the top 3 unconfirmed payers at each origin are answered from the truth labels. The no-confirmation arm (detection only) is reported alongside in forecast.arms.
- S4-shock coverage after the shift is expected to miss (docs/09 §7.4) and is not gated.
- Breach Brier and the long-January check are not computed yet.

### E-SIM (simulation) · 15.87 s

| ID | Check | Dataset | Value | Target | Met | Gated |
|---|---|---|---|---|---|---|
| SIM | Properties passed (SIM-1/2/3/6) | P1-base | 1.000 | >= 1.0 | ✓ | yes |

- 200 seeded cases per property; one-off amounts £0.01–£3,000 on a random horizon day; income delays of 1–10 days on the first payday in the horizon.
- SIM-6 checks that only a contiguous window starting at the payday changes, that it spans at least the delay, and that the end balance is unchanged when the pay lands in horizon.

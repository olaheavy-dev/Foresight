# Hand-authored Stage 2 eval sets

Synthetic / fictional. Written before any prompt or Verifier rule is tuned, then frozen by sha256 in `MANIFEST.json` (`python -m evals.authored --verify`). A changed file fails CI until it is re-frozen with `--write` and the reason is logged in `evals/CHANGELOG.md`. All cases run against the generated personas (`P1-base`, `P2-base`) as of **11 Oct 2026**.

| File | Rows | Spec |
|---|---|---|
| `bad_proposals.jsonl` | 62 `REJECT` + 38 `APPROVE` (2 relabelled 13 Oct 2026, see `evals/CHANGELOG.md`) | docs/09 §3.6, suite E-VER / E-GRD |
| `scenario_prompts.jsonl` | 70 with a gold `ScenarioSpec` + 10 `needs_clarification` | docs/09 §3.5, suite E-SCN |
| `orchestration_cases.jsonl` | 30 | docs/09 §3.7 and §10, suite E-ORC |
| `ui_questions.jsonl` | 40 questions + 20 paraphrases | docs/09 §10a, suite E-UI |
| `followup_cases.jsonl` | 40 conversations + 20 paraphrase pairs + 20 near-miss pairs | docs/09 §3.10, suite E-CTX |
| `injection_cases.jsonl` | 40 chat + 40 data-plane attacks (narrations, CSV headers, filenames, PDF lines) | docs/09 §3.9, suite E-SEC |
| `injection_cases_dev.jsonl` | 20 + 7 dev cases (the only set the guard rule pack may be tuned on) | docs/09 §3.9 |
| `injection_benign_questions.jsonl` | 60 benign questions (false-refusal control, with the E-UI/E-SCN/E-CTX questions) | docs/09 §10b SEC-5 |
| `ui_questions_dev.jsonl` | 30 practice questions (P1, P2), written separately from `ui_questions.jsonl`; expected blocks follow the docs/08 §7a slot table | the only E-UI set the composer and the Understand prompt may be tuned on |
| `followup_cases_dev.jsonl` | 25 practice conversations + 6 paraphrase pairs + 6 near-miss pairs, written separately from `followup_cases.jsonl` | the only E-CTX set the Understand prompt and the cache key may be tuned on |

**Practice-set slot conventions** (written with the practice sets, 13 Oct 2026, before any tuning): amounts in minor units; a single day as `YYYY-MM-DD`, the next such day after `as_of`; a month with no day is the 1st of that month (the Forecaster's rule, docs/06 §4.3 prompt); a follow-up keeps the earlier turn's intent and every slot it doesn't change; `purpose` is the user's own noun, labels the question and doesn't enter the answer-cache key; spending periods use `period` (`last_30d`, `last_month`, `this_month`, `next_30d`, or `YYYY-MM`); a `category_key` is a key of the uk pack (one practice label, CTXD-C022, said `food.coffee`, which is not a pack key, and was corrected to `food.eating_out`).

## Conventions the runners rely on

**Evidence references in proposals** are symbolic, because finding and forecast IDs are minted at run time. The runner resolves them against the run's own records before the proposal reaches the Verifier:

- `fnd:<finding_type>:<subject>`: the finding the detectors produce for that type and subject. Subjects are truth keys (`food.delivery`, `rob_spotify`, `inc_client_lumen`); a pair is joined with `+` (`rob_netflix+rob_sky`). The resolvable set is the `expected_findings` × `subject` pairs in each persona's `truth_anomalies.json`, plus `fnd:category_spike:<category>` for every spike the real trend detector (`category_trends`) finds on the persona's ledger at `as_of` (P1: `food.delivery`, `food.eating_out`, `health`, `transport.taxi`; P2: `groceries`), i.e. what a live Analyst would hand the Advisor; anything else is deliberately dangling (V-01).
- `fc:baseline`: the baseline forecast for the case's `as_of`. Any other `fc:` ID is deliberately dangling.
- `goal:<key>`: a goal supplied in the case's `context.goals` (the personas have no goals of their own).

**Claimed impact (`claimed_monthly_impact_minor`)** follows `basis.impact_basis`, so V-06's ±1% check has a defined answer:

| `impact_basis` | Claimed monthly impact |
|---|---|
| `cap_vs_last_30d` | max(0, last 30 days' spend in the category − the monthly cap) |
| `monthly_recurring_amount` | the obligation's monthly amount |
| `old_minus_new_amount` | old amount − new amount |
| `timing_only` | 0 (a date move changes risk, not the monthly total) |
| `cross_currency` | not computable without a rate (V-20) |

The 30-day windows end on `as_of`; feasibility (V-04) compares the cap with the median of three consecutive 30-day windows. `basis` records the numbers used, so a runner whose `recompute_impact` disagrees shows up as a definitional difference, not a silent miss.

**`immaterial_timing`** (added 13 Oct 2026): a date move the engine shows doesn't reduce the chance of going below the buffer (V-05). GP-039 and GP-040 keep their IDs for traceability.

**`expected_rules`** lists the rules that should reject the proposal. Any one of them firing counts as a correct rejection (for example V-08 or V-17 for a goal-delaying savings move).

**ScenarioSpec modifiers** use the docs/07 §6.5 field names. Where the table says "as named", these sets use: `recurring_add {label, amount_minor, cadence, start_date, category_key}`, `recurring_change {recurring_id, amount_minor, from_date}` (the new amount), `recurring_cancel {recurring_id, from_date}`. IDs are truth keys (`inc_salary`, `rob_rent`). `move_to_goal` is not used, because the personas have no goals.

**Injection cases** carry no evidence references: they test the input screen, the import-time `suspicious_text` flag and the output screen, not proposals. Chat cases may include a `simulated_output` (a hostile model reply, with `{{CANARY}}` replaced at run time by an evaluation-only canary) to test the output screen without a model call. `expected.first_layer_expected_to_stop` is the design intent (`screen`, `understand`, `verifier`, `output_screen`); E-SEC reports the layer that actually stopped each case. Rows in the other sets labelled `smalltalk_or_out_of_scope` or `terminal_state: refused` are counted as expected refusals, never as false refusals.

**Follow-up near misses** that differ only by `data_version`, `prefs_version` or `advice_state_version` repeat the same question with an `event_between` (an import, a buffer change, an accepted recommendation) that must invalidate the answer cache.

## Known gaps

- The planned **G4** dataset (GBP account plus a EUR pocket) is not generated yet. The four `cross_currency_arithmetic` cases use `P1-base` with the EUR pocket supplied in `context.extra_accounts`.
- One orchestration case (`ORC-C029`, PDF `L5`) is `stage: 4` and is skipped until the PDF importer ships.

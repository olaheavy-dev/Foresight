> Historical review at rev 4.2; superseded by register rev 5.1 — see `00-DECISION-REGISTER.md`.

# Documentation alignment review — 12 Oct 2026

Reviewed documents 00–10, the documentation index, the prototype README, and all six example response payloads against the decision register. Register revision **4.2** records the resulting shared rules. The repository contains a design specification and static prototype; backend, production frontend, CI, evaluation runners and measured public results do not exist yet.

| Area | Resolution |
|---|---|
| Workspace migration | Restored `FormatProfile` / `LayoutProfile`, their ER entities and `format_profile_id` / `layout_profile_id`. Workspace remains the isolation unit. |
| Coverage index | J1–J16, six JSON scenarios and the India prototype page are listed consistently. |
| P4 fixtures | XLS is the primary generated export; XLSX is an equivalent variant used in the contract/journey. P4 values are owned by 07 §10a; the UX now uses the ₹47,850 low and ₹41,200–₹53,900 band. Copied GBP-era evidence versions and the example filename were corrected. |
| Currency isolation | Scenario and goal currency, same-currency references, per-scope/currency buffers and forecast cache identity are explicit. Example ScenarioSpecs carry currency. Missing buffers do not produce affordability claims. |
| Import ambiguity | Saved formats or unambiguous evidence resolve dates; locale is a pre-selection, not permission to commit an ambiguous import. H13 covers currency, dates and separators and blocks only the affected batch. Inconsistent separators reject it. |
| Import integrity | Sparse balances check complete date groups; unverifiable PDFs reject; balance-free CSVs are not called reconciled. First-use PDF confirmation appears in evaluation and roadmap acceptance criteria. |
| Privacy and scope | Joint rows remain staged until consent, before commit or Mesh calls. Mine follows the household-pot exclusion rule. |
| Deterministic boundary | Identical validated inputs produce identical arithmetic. Models can change categorisation, parsed scenarios and interventions; the null-model comparison freezes those inputs. |
| Findings and evidence | Severity uses info/watch/act; stored finding states include candidate/discarded; the prototype and contract detector threshold is 2.0. Rejected model claims are labelled as rejected audit content. |
| Snapshots and scheduling | Old evidence remains available; freshness includes financial as-of date. Digest scheduling uses workspace-local time and permits an honest status when no approved action exists. |
| Evaluation provenance | Generated, constructed, independently authored and external synthetic sets remain distinct. External acquisition/labels freeze before India tuning; replay/live exceptions and final-run dependencies include external India evaluation. |
| Build expectations | Simulation latency follows NFR-02, coverage follows NFR-12, normal runs do not force a scripted rejection, and roadmap task/acceptance references agree. |

Checks completed:

- Relative Markdown links resolve; code examples are excluded from link parsing. Markdown fences are balanced.
- All six payloads parse as JSON and have unique block IDs within each response.
- All 96 structured Money values use integer minor units and the response currency; all seven embedded ScenarioSpecs declare that currency.
- Reproducible evidence versions match their response’s data version, including P4 version 9.
- The PRD contains F-01–F-74 (+ future F-90–F-97) and FR-01–FR-87; journeys contain J1–J16. *(ranges updated at rev 5.1)*
- The edited prototype JavaScript passes `node --check`.

These checks do not establish runtime schema validity: Pydantic/Zod implementations and product tests are planned. The prototype was not visually retested because its only executable-file change is evidence text. External source contents, licences, event rules and deadlines were not independently reverified in this internal alignment pass; pinned acquisition and verification remain build tasks.

Open decisions remain in 00 §12 with owners/dates in §13. In particular, non-GBP absolute detector/materiality thresholds and goal rounding increments must be agreed and versioned before non-GBP advice evaluation. GBP minor units must never be silently reused for INR, EUR or JPY. No evaluation target or illustrative fixture has been promoted to a measured result.

# Advisor model trial (13 Oct 2026)

18 dev cases on P1 (frozen: `dev_cases.sha256`; none drawn from the E-VER test labels): 6 valid caps, 10 fixable flawed proposals (2 × 5 defect types), 2 unfixable (unrequested cut to family support). Same loop as E-VER: Verifier → Advisor revision with the critique, ≤ 2 revisions. Judge always from a different provider than the Advisor. Decision rule fixed before running: a cheaper arm wins only if revision success and grounding are ≥ arm A − 2 pts and it has no grounding violations; cheapest winner.

| Metric | A: Sonnet 5.5 Advisor, GPT-6.1 Sol judge (current) | B: Gemini 3.8 Flash Advisor, GPT-6.1 Sol judge | C: GPT-5.6 Luna Pro Advisor, Sonnet 5.5 judge |
|---|---|---|---|
| Flawed proposals fixed and approved | 10/10 | 0/10 | 10/10 |
| Unfixable proposals handled correctly | 2/2 | 2/2 (both runs errored) | 2/2 |
| Good proposals approved first time | 6/6 | 6/6 | 6/6 |
| Approved advice grounded (E-GRD checks) | 18/18, no violations | 6/6, no violations | 18/18, no violations |
| Output-format repairs or failures | 0% | 74% (10 cases ended in errors) | 0% |
| Advisor latency (median) | 10.7 s | 25.3 s | 19.0 s |
| Advisor cost | $0.273 | ≥ $0.152 (failed calls unpriced) | $0.085 |
| Cost per case, Advisor + judge | $0.019 | — | $0.012 |
| Live P1 car-repair run | committed earlier trace: answered, 2 checked caps | not run | answered: "overdrawn" verdict, 2 checked caps, payday deferral rejected, MoneyHelper note; hit the 60 s limit after round 1 |

**Result under the rule:** C wins (equal quality, about 37% cheaper per case). B fails.
**Caveats:** small sample (A and C both perfect on 18 cases: shows C is no worse here, not better); C is slower (19 s vs 11 s per Advisor call), which leaves less room for revision rounds inside the 60 s question deadline; C uses ~2.7× the input tokens and moves the judge to Sonnet, so the saving is ~37% per case, not the ~8× the list prices suggest. Switching requires re-recording all Advisor and judge cassettes.
**Spend:** $0.8761 (balance $12.9953 → $12.1193; an upper bound, another workstream shared the account).

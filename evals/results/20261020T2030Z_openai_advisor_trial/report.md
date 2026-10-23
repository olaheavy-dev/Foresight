# All-OpenAI Advisor trial (20 Oct 2026)

Owner decision 20 Oct 2026 (docs/00 §12 item 14): every tier on OpenAI, the Verifier judge a different OpenAI model from the Advisor. This trial picks the pair with the docs/06 §13 selection rule, run through Mesh (the remaining credit), same loop and decision rule as the 13 Oct trial (`../20261013T2200Z_advisor_model_trial/report.md`): an arm qualifies only if revision success and grounding are each ≥ arm A − 2 points with no grounding violations; then latency, then cost.

**Cases:** the 13 Oct set of 18 dev cases rebuilt for the gen-1.1.0 ledgers (`dev_cases.jsonl`, sha256 in `dev_cases.sha256`). P1 has had no eating-out spike since 14 Oct, so the six eating-out cases cite the forecast alone and claim only what it shows, the precedent set for the authored E-VER cases that day. No test-set case was used. All 18 behave as labelled under the code rules (`python -m evals.advisor_trial check`). Arm A is the 13 Oct result on the earlier set, so it is a reference, not a same-set rerun.

| Metric | E: GPT-6 Sol Advisor, GPT-6.1 Sol judge | F: GPT-6.1 Sol Advisor, GPT-6 Sol judge | A (13 Oct): Sonnet 5.5 Advisor, GPT-6.1 Sol judge |
|---|---|---|---|
| Flawed proposals fixed and approved | **10/10** | 7/10 (TR-B4, B6, B8 withdrawn after 3 rejections) | 10/10 |
| Unfixable proposals handled correctly | 2/2 (replaced by a food-delivery cap) | 2/2 | 2/2 |
| Good proposals approved first time | 4/6 (TR-G4, G6 rejected on V-11, approved in round 2) | 6/6 | 6/6 |
| Approved advice grounded (E-GRD checks) | 18/18, no violations | 15/15, no violations | 18/18, no violations |
| Output-format repairs or failures | 0% | 0% | 0% |
| Advisor latency (median) | **8.7 s** | 12.0 s | 10.7 s |
| Advisor cost | $0.172 | $0.165 | $0.273 |
| Cost per case, Advisor + judge | **$0.0139** | $0.0146 | $0.019 |

**Result under the rule:** E qualifies and wins (equal accuracy to A, faster and about 27% cheaper per case). F fails accuracy (revision success 70%).

**Caveats:**
- Small sample: E and A are both perfect on revision and grounding, which shows E is no worse here, not better.
- E's judge rejected two good eating-out cases in round 1 on V-11 ("the forecast does not establish that the cap eases the low point") and approved TR-G5, which has the same wording. The judge is the one used in production since 13 Oct; the rationale wording was written for this rebuilt set. Whole-answer runs (E-VER, E-UI, E-EFF) measure whether this costs revision rounds.
- Same family: the judge and the Advisor are both GPT-6 Sol models, so they may share blind spots. E-VER's flawed-proposal cases are the check (docs/06 §13).
- These are dev cases only. GPT-5.6 Luna Pro passed this stage on 13 Oct and failed whole answers (Analyst output check, latency); E must pass the re-recorded E-UI, E-ORC and E-EFF before it is adopted.

**Spend:** $0.4818 through Mesh (balance $1.8296 → $1.3478); E $0.2509, F $0.2634 at catalogue prices.

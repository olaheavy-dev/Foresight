# Foresight demo: viewer notes

Notes to go with the three-minute demo video, `foresight-demo.mp4`. The video goes straight into the app, so the detail that doesn't fit is here. How the video is made and updated: [`docs/demo-video.md`](../../demo-video.md).

- **Live app:** https://foresight.olaheavy.dev. "Explore the live demo" opens a private copy of the same fictional profile.
- **Code:** https://github.com/olaheavy-dev/Foresight
- **What's real:** the video was recorded on the live site on 25 Oct 2026. The question, the proactive check and their agent runs are real model calls, and both agent waits play at their real speed (labelled on screen). The demo profile (Amara, one current account, Leeds) and every transaction are fictional. The narration is AI-generated from a recording of the builder's voice, and the caption says so on every frame.

## What the video shows

| Scene | What to look for |
|---|---|
| Home | A 90-day forecast of the lowest balance before each payday, with a likely range (P10–P90) from 500 simulated paths. Below it, findings the engine detected, such as food delivery up 39%. |
| How it's built | The stack card. More detail [below](#stack). |
| Proactive check | The agents run in real time: findings in, a drafted change, the Verifier's checks, and only checked advice out. "How it was checked" lists every rule the advice passed. |
| AI Workspace | "Can I afford a £1,200 holiday in December?" The steps stream live. In this take the Verifier rejected both drafted recommendations, so the answer shows the forecast effect with no recommendation. That's the system working as designed: a weak recommendation is never published. |
| Decision Lab, Goals | A purchase spread over three payments, and a savings goal, each tested on the same simulated paths as the forecast. |
| Evidence, Activity | A finding opens the exact transactions it counts. Activity shows every agent run as a trace (agent, model, time, tokens, estimated cost) and a log of every change. |
| Quality | The evaluation results the app ships with, including what's missed. |

## Stack

| Layer | Built with |
|---|---|
| Web app | Next.js 16, React 19, TypeScript. Answer blocks are typed by contracts generated from the API's schemas. |
| API | FastAPI on PostgreSQL 16. Guest sessions get a private copy of the demo profile, and every resource is checked for ownership. |
| Finance engine | Deterministic, seeded Python (`backend/finance_core`). Money is stored as integer minor units with a currency. It covers the forecast, what-ifs and goals. |
| Agents | LangGraph. A coordinator and five specialists: Ledger (what each transaction is), Analyst (trends, bills, anomalies), Forecaster (forecast, what-ifs, goals), Advisor (drafts changes) and Verifier (20 rules, on a different model from the Advisor). |
| Models | OpenAI: GPT-6 Sol (reasoning), GPT-6.1 Sol (Verifier judge) and GPT-6 Luna (fast tier). They're called only through one gateway module (`backend/llm/client.py`), and an import contract fails the build if anything else calls a model. |
| Delivery | Docker, GitHub Actions. Images are published only after CI is green. |

**The rule behind it: numbers come from code, words come from models.** A model never writes a figure. It writes placeholders, and the server fills every value from a stored calculation, so each number links to its source.

## Results

From evaluation run `evalrun_20261025T040935Z_c12d103` (25 Oct 2026), on fictional personas. Suites that use a model are scored on recorded responses (replay). Full tables: the README's "Self-evaluation".

- **Bad advice caught:** the Verifier rejected 65 of 65 authored bad proposals, and falsely rejected 0 of 31 good ones.
- **Forecast:** 30-day MAE £443 against £643 for the best naive baseline (P1 persona), and the likely range covers 0.79 of outcomes.
- **Categorisation:** 0.942 accuracy on a generated test split (n = 498).
- **Imports:** reconciliation caught 20 of 20 corrupted CSV statements.
- **Cost and speed:** an advice answer averages $0.0186, with a p50 of 15.2 s.
- **17 evaluation suites** run in CI, and a feature switches on only when its suites pass.

**Limits, as the README states them.** On two personas the median forecast isn't yet more accurate than the simplest baseline, though its likely range is better calibrated. Categorisation has no independent hand-labelled holdout yet. The conversation suite (E-CTX) still misses two follow-up targets, which is the failed fast-tier gate on the Quality page.

Foresight is guidance on your own spending and timing. It isn't regulated financial advice.

# Foresight demo: viewer notes

Notes to go with the demo video, `foresight-demo.mp4` (4:37). The video goes straight into the app and explains each feature as an engineer would walk a customer through it; these notes add the detail and the sources. How the video is made and updated: [`docs/demo-video.md`](../../demo-video.md).

- **Live app:** https://foresight.olaheavy.dev. "Explore the live demo" opens a private copy of the same fictional profile.
- **Code:** https://github.com/olaheavy-dev/Foresight
- **What's real:** the video was recorded on the live site on 25 Oct 2026. The question, the proactive check and their agent runs are real model calls. The two agent waits play almost at their real speed: the proactive check (28.5 s) at 1.1× and the question (25.9 s) at 1.4×, labelled on screen, so each fits the narration that explains it. The figures quoted in the narration are the ones on screen in this recording. The demo profile (Amara, one current account, Leeds) and every transaction are fictional. The narration is AI-generated from a recording of the builder's voice, and the caption says so on every frame.

## What the video shows

| Time | Scene | What to look for |
|---|---|---|
| 0:00 | The problem | Will I be short before payday? The landing page, on a fictional profile. |
| 0:15 | Home | A private copy of the demo per visitor. Amara's low before payday is £211, below her £500 buffer. |
| 0:34 | How it's built | The stack card. More detail [below](#stack). |
| 0:57 | Forecast and findings | 500 simulated paths, the middle path with a likely range (P10–P90), and the low before each payday. Findings: food delivery up 39%, two overlapping streaming services. |
| 1:24 | Proactive check | The agents run live: the Advisor drafts a change, the engine works out its effect, and the Verifier (a different model) checks it against 20 rules. "How it was checked" lists every rule passed. |
| 2:12 | AI Workspace | "Can I afford a £1,200 holiday in December?" The steps stream live. The answer: about £463 overdrawn before the 18 Dec payday, each figure cited. In this take the Verifier rejected every drafted recommendation, so none is shown. That's by design: a recommendation is never published unchecked. |
| 3:12 | Decision Lab, Goals | A £900 purchase spread over three payments, and a £1,500 goal by April (about a 1% chance), both on the same simulated paths, with no model involved. |
| 3:42 | Evidence, Activity | The transactions behind a finding. Every agent run as a trace (agent, model, time, tokens, estimated cost). A hash-chained log of every change. |
| 4:11 | Quality | 17 evaluation suites and the misses, published. |

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

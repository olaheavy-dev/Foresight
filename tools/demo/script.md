# Foresight demo: narration (about 3 minutes)

One `## <scene>` section per scene. `narrate.py` renders each into `out/audio/<scene>.wav` and `build.py` fits each to its part of the recording (docs/demo-video.md). The video opens on the app, with no introduction of the presenter; what doesn't fit goes in the viewer notes (`docs/assets/demo/README.md`). Keep every claim true of the repo: numbers from the engine, five specialist agents, 20 Verifier rules, 17 eval suites, 500 simulated paths, fictional demo data. The two agent waits play in real time, so their scenes narrate what the agents are doing. `07-answer` describes the 25 Oct 2026 take, where the Verifier rejected both drafts: after a new recording, check what the run did and change that line to match.

## 01-open (landing, then Home)
This is Foresight, a personal-finance workspace that forecasts where your money is heading over the next ninety days. Everything you'll see runs live, on a fictional demo profile.

## 02-stack (the stack card)
Under the hood: a Next.js and TypeScript front end, a FastAPI service on PostgreSQL, and a deterministic finance engine in Python. On top sit LangGraph agents, a coordinator and five specialists, and every model call goes through one gateway to OpenAI. The rule that shapes it all: numbers come from code, words come from models.

## 03-forecast (Home: forecast and findings)
The forecast shows the low point before each payday, with a likely range from five hundred simulated paths, not a single guess. Below it are the findings: patterns the engine spotted in the transactions.

## 04-proactive (run the proactive check; the agents work in real time)
Here's the process. I'll run the proactive check. The analyst reads the findings, and the forecaster measures their effect on the cash flow. The advisor then drafts a change, and a second agent on a different model, the verifier, checks it against twenty rules. A draft that fails goes back for revision. The advice never contains a number the model wrote: it writes placeholders, and the engine fills them in. Each step is logged with its model, its time and its estimated cost. Only checked advice reaches the screen. This wait is real time.

## 05-checked (the checked advice, then how it was checked)
Here's the result: checked changes, each with its effect computed by the engine. Open how it was checked, and you see every rule the advice passed, and any draft that was rejected along the way.

## 06-ask (Workspace: the question and its live steps, real time)
You can also ask in plain English. Can I afford a twelve-hundred-pound holiday in December? Each step appears as it happens: the coordinator plans the work, the forecaster simulates the purchase, and the answer is composed from the engine's results. If the advisor drafts a recommendation, it goes through the same verifier as the proactive advice, and it's shown only if it passes.

## 07-answer (the answer, then How it was checked)
This time the verifier rejected both drafts, so the answer gives no recommendation rather than a weak one. The model chooses the blocks, but every figure comes from stored calculations and links to its source, and this tab shows each step.

## 08-lab (Decision Lab: spread a purchase)
The Decision Lab tests a choice before you make it, like spreading a purchase over several payments, on the same simulated paths as the forecast.

## 09-goals (Goals)
Goals sit on that same forecast, so you see your real chance of reaching one in time.

## 10-evidence (a finding's transactions)
Every finding leads to the exact transactions behind it, so you can check any number down to the line it came from.

## 11-activity (Activity: a run's steps)
Activity keeps every agent run as a trace, with each step, its model, its time and its estimated cost, beside a readable log of every change.

## 12-quality (Quality, end)
And a feature ships only when its checks pass: seventeen evaluation suites run on every change, and this page reports the results, misses included. That's Foresight: advice you can check, and a receipt for every number.

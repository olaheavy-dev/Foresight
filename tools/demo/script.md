# Foresight demo: narration (about 2 minutes)

One `## <scene>` section per scene. `narrate.py` renders each into `out/audio/<scene>.wav` and `build.py` fits each to its part of the recording (docs/demo-video.md). Keep every claim true of the repo: numbers from the engine, 20 Verifier rules, 17 eval suites, fictional demo data.

## 01-intro (landing, then Home)
Hi, I'm Sunkanmi. This is Foresight, a personal-finance workspace I designed and built on my own. It forecasts where your money is heading over the next ninety days. Everything you'll see uses a fictional demo profile.

## 02-forecast (Home: forecast and findings)
The forecast shows the low point before each payday, with a likely range rather than a single guess. Every number here comes from a deterministic engine. Models never write figures.

## 03-proactive (Run the proactive check, then how it was checked)
Foresight also looks for what stands out on its own. Agents find the patterns, an Advisor drafts a change, and a second model, the Verifier, checks it against twenty rules before you ever see it. You can open exactly how it was checked.

## 04-ask (Workspace: the question and its live steps)
You can also ask in plain English. Can I afford a holiday in December? While it works, each agent's step appears as it happens.

## 05-answer (the answer, then How it was checked)
The answer is built from the engine's calculations, and every figure links to its source. This tab shows each rule the advice passed, and any draft that was rejected along the way.

## 06-lab (Decision Lab: spread a purchase)
The Decision Lab tests a choice before you make it, like spreading a purchase over several payments, on the same simulated paths as the forecast.

## 07-goals (Goals)
Goals sit on that same forecast, so you see your real chance of saving in time.

## 08-evidence (a finding's transactions, then Activity)
Every finding leads to the exact transactions behind it, and Activity keeps every agent run and every change as an audit trail you can read.

## 09-close (Activity, end card)
Behind it, seventeen evaluation suites run on every change, and a feature only ships when its checks pass. That's Foresight: advice you can check, and a receipt for every number.

# Foresight demo: narration (about 4½ minutes)

One `## <scene>` section per beat: one line of narration over one action. `narrate.py` renders each into `out/audio/<scene>.wav` and records its length in `out/audio/durations.json`. The walkthrough (`frontend/e2e/walkthrough.spec.ts`) reads those lengths and holds every scene for its line, so **render the narration before recording**, and keep the `## <scene>` names in line with the spec's `scene(…)` calls. `build.py` lays each line at the start of its scene (docs/demo-video.md).

Tone: an engineer walking a customer through a deployed system: the problem first, then why it's built that way. No presenter introduction; what doesn't fit goes in the viewer notes (`docs/assets/demo/README.md`).

Keep every claim true of the repo: numbers from the engine, a coordinator and five specialists, 20 Verifier rules, 17 eval suites, 500 simulated paths, fictional demo data. The figures said aloud (£211, £500, 39%, £463, 1%) are the ones the engine showed in the 25 Oct 2026 take. They move with the day and time of a recording (an earlier take that day showed £198 and £455), so check them against each new video and render those lines again. The two agent waits (`06-proactive`, `10-thinking`) are narrated for about 30 s and 20 s; a longer wait is sped up in the edit, labelled.

## 01-open (landing page)
Foresight answers the question people actually worry about with money: will I be short before payday? It reads a bank statement, forecasts the next ninety days, and suggests changes. And every number it shows comes from code, never from a model. This is the live site, on a fictional profile.

## 02-home (Explore the live demo, then Home)
Amara is a QA engineer in Leeds, with one current account. Opening the demo gives each visitor a private copy of her data, so nobody sees anyone else's changes. Up top: her balance, the lowest point before her next payday, and when that payday lands. Her low is two hundred and eleven pounds, below the five-hundred-pound buffer she set.

## 03-stack (the stack card)
Here's how it's built. A Next.js and TypeScript front end talks to a FastAPI service on PostgreSQL. The finance engine is plain, deterministic Python, with integer money and seeded simulations, so the same data always gives the same answer. The agents run on LangGraph: a coordinator and five specialists. And every model call goes through one gateway module: if anything else in the codebase tries to call OpenAI, the build fails.

## 04-forecast (Home: the forecast chart)
Back to the forecast. Rather than one line, the engine simulates five hundred possible paths through her salary, bills and spending, and shows the middle path with a likely range. The dots mark the low point before each payday, because that's the moment that matters.

## 05-findings (the findings)
Below it are findings the analyst picked out of her transactions. Food delivery is up thirty-nine percent on her usual month, and two streaming services overlap. Each one links to the exact transactions behind it.

## 06-proactive (Run the proactive check; the agents work, real time)
Now the agents. I'll run the proactive check, and this plays in real time. The advisor, on one model, drafts a change from those findings, and the engine works out what it would do to her cash flow. Then the verifier, a separate agent on a different model, checks the draft against twenty rules. Does the evidence exist? Is the saving recomputed correctly? Does it just push the problem into next month? A draft that fails goes back for revision. And the model never writes a figure: it writes placeholders, and the engine fills them in.

## 07-checked (the checked advice)
Here's what came back: only changes the verifier approved, each with its effect worked out by the engine. What you won't see is advice it couldn't check.

## 08-how (How it was checked)
Open how it was checked, and you get every rule the advice passed. A rejected draft would be shown here too, labelled as rejected. That's the audit trail a reviewer needs.

## 09-ask (Workspace: type the question)
The workspace takes questions in plain English. I'll ask: can I afford a twelve-hundred-pound holiday in December?

## 10-thinking (Send; the steps stream in, real time)
Each step streams in as it happens. The coordinator reads the question with a fast, cheap model, then plans the work. The forecaster simulates the holiday on the same five hundred paths, so the answer is her forecast with and without it. In production, live calls ran slower than in testing, so latency is now measured from real calls.

## 11-answer (the answer's headline)
The answer: she'd be about four hundred and sixty-three pounds overdrawn before her December payday. Every figure carries a citation, and each one opens the calculation behind it.

## 12-chart (scroll the answer)
The chart compares the two paths. The model chose which views to show, but it can't write a number: the server fills every value from stored calculations, and checks the result against a contract.

## 13-trace (How it was checked tab)
This tab is the run itself: each agent, the model it used, its tokens and its time, and whether the verifier approved a recommendation or rejected it. When nothing passes, the answer says so, rather than guessing.

## 14-lab (Decision Lab: set up a spread purchase)
The Decision Lab tests a choice before you make it. Say she spreads a nine-hundred-pound purchase over three monthly payments.

## 15-lab-result (the Lab result)
It runs on the same simulated paths as the forecast, so the difference is that change alone, and no model is involved. Even spread out, she'd likely dip below zero before the November payday.

## 16-goals (add a goal)
Goals work the same way. A fifteen-hundred-pound trip home by April, checked against the forecast: her chance is about one percent, and it shows roughly how much more a month would close the gap. Honest, even when the answer is no.

## 17-evidence (a finding's transactions)
Every finding leads back to its evidence. Here are the exact delivery transactions behind that thirty-nine percent, each with its category and how it was categorised.

## 18-activity (Activity: open a run)
Activity is the operations view. Every agent run is a trace: each step, which agent, which model, how long it took, and its estimated cost.

## 19-audit (Activity: the change log)
Below it, every change to the profile goes into an audit log where each entry is hashed with the one before, so editing an old entry would break the chain.

## 20-quality (Quality page)
Last, quality. Seventeen evaluation suites run in CI on recorded model responses, so running them costs nothing, and a feature switches on only when its suites pass.

## 21-close (scroll Quality, end)
The misses are published too: the conversation suite still fails two targets, and it's shown here, not hidden. That's Foresight: advice you can check, and a receipt for every number.

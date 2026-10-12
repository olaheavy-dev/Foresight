# Direction B: Agent-Native Analysis Studio (Stage 1 concept)

**Idea:** a canvas the agents build for you, block by block, each one stamped with what kind of truth it holds.

Files: `board.html` (concept board), `home.html` (studio in orientation mode, after the £650 car repair), `workspace.html` ("Can I afford a £1,200 holiday in November?"). Shared `studio.css` and `charts.js`. Open locally with any static server, e.g. `python3 -m http.server` in `design/concepts/`. All data is the shared fictional Amara fixture.

## Structure

64px nav strip · 340px agent rail (activity, conversation, follow-ups, ask) · wide canvas assembled from typed blocks (MetricSummary, CashFlowTimeline, ScenarioComparison, RiskInsight, InterventionOptions, TransactionEvidence, AssumptionInspector, AgentActivityTimeline). Hovering a rail step highlights the block that step produced.

**Signature:** the provenance stamp. Every block declares whether it holds observed, computed, forecast, hypothetical, AI-written or checked content, in Geist Mono, before you read a number. The chart repeats the same grammar in line style:
- solid ink is observed
- an ink line with a band is the forecast
- dashed blue is a scenario
- solid teal is the checked plan
- a dotted amber line is the buffer
- a vertical rule marks today.

## Strengths

- **Answers are surfaces, not paragraphs.** The holiday question returns a verdict, a live scenario chart, a comparison table, a checked alternative, evidence and the assumptions. Changing the amount or date recalculates every view from one function, so the numbers reconcile.
- **The FinPilot story is visible without explanation.** The rail shows agents handing off (Ledger, Forecaster, Verifier). The rejected option sits next to the checked one with its reason, so "the loop actually loops" is obvious to a judge in seconds.
- **Proactive by construction.** Home is a canvas the agents assembled unprompted after a data change, so it isn't a dashboard waiting for a question.
- **Evidence without clutter.** Stamps, "Source rows", "Assumptions" and a collapsed "How this answer was made" table separate model steps from engine steps and checks.
- **The same components serve every question type.** That maps directly onto the generative-UI contract: the model picks blocks, and the engine fills the numbers.

## Weaknesses

- **Less immediate for a first-time user than an editorial home.** With three columns, the first read is "a workspace", not "here is your money". It needs a strong first canvas title and a good empty state.
- **The rail costs width.** At ≤ 1280px the canvas tightens, and on mobile the rail must become a bottom sheet or tab, which this concept doesn't solve yet.
- **Risk of a "block soup".** Without a firm composition rule (verdict first, at most one chart per row, evidence last), agent-chosen layouts could feel random. The composition order needs to be part of the contract.
- **Two-tone ink.** History and forecast are both ink. They're separated by the band, the "today" rule and the shaded future, but not by hue. That's intended, but it should be tested with users.

## Technical scope for a solo builder by 20 Oct

- **Feasible, and reuses one component set.** Home and Workspace are the same page shell: rail plus canvas plus a block renderer driven by typed contracts (docs/08). One chart component covers both timelines.
- **Cost drivers:**
  - the block renderer with its stamps (~1 day)
  - the chart with band, markers, hover and table view (~1 day)
  - the rail with streaming steps (~0.5 day)
  - live scenario controls, which call the engine's simulate endpoint (~0.5 day).
- **Cut first if late:**
  - hover highlighting between rail and blocks
  - the full run table (fall back to the rail steps)
  - the scenario slider (keep the date chips).

## Fit with FinPilot judging

- **Orchestration (#1) and the core loop (#2):** shown directly by the rail and the checked/rejected pair.
- **Forecast and simulation (#3):** they're the canvas hero, with an uncertainty band and an interactive what-if.
- **Grounded advice (#4) and audit (#7):** evidence rows with statement row numbers, engine/seed stamps and the run table.
- **Self-evaluation (#6):** not shown on these screens. A small "System quality" block (categorisation accuracy, forecast error against baselines) fits naturally as another typed block on an Activity canvas.

## Recommendation for the synthesis

Use Direction A's editorial clarity for first-run orientation if it reads faster. Keep this Studio's typed, stamped blocks and agent rail for Workspace, Decision Lab and every "Investigate" click, because they're what makes the agent work and the evidence legible.

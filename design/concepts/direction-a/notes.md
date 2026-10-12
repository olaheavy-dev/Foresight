# Direction A — Intelligence Command Centre: notes

Design concept, Stage 1. Fictional data. Pages: `board.html`, `home.html`, `workspace.html` (open via any static server, e.g. `python -m http.server` in `design/concepts/`).

## The idea

A morning briefing for your money. Home answers "What should I know about my money today?" in one sentence, then shows one calm outlook of the weeks ahead, the one thing that needs attention, and a checked plan. A question in the Workspace becomes a **report** (verdict, chart, checked alternative, evidence), not a chat transcript. Signature element: the **outlook chart with an event rail** — each dated payment sits under the day it moves the line.

## Strengths

- **Fast orientation for non-experts and judges.** In under 30 seconds: where I stand (3 metrics with as-of and provenance), what is likely next (forecast with today boundary, likely range, buffer, dated risk point), what to do (insight → checked plan). Maps directly to the 90-second demo story.
- **Future-first without hiding evidence.** The outlook is the hero; history is a short run-up. Every number carries a provenance mark (observed / detected / forecast / scenario / AI-written / checked) and an inspect affordance.
- **The core loop is visible.** The checked plan shows the rejected first draft and why (79% below usual pace; still leaves £312), and the Workspace shows a Verifier correction (£200 → £180). Judges see the system checking itself, not just a claim that it does.
- **Proactive by default.** The insight is labelled "Found by Foresight · not prompted" and ranks above everything else.
- **Calm and buildable.** One accent, six type sizes, one chart component, hairline structure. It reuses the same `CashFlowTimeline`, `MetricSummary`, `RiskInsight`, `InterventionOptions`, `AgentActivityTimeline` and `AssumptionInspector` pieces across both pages.

## Weaknesses

- **Less "agent-native" at first glance than Direction B.** Agent work is visible (sidebar status, inspector trail, "not prompted" label) but secondary; a judge looking for a dramatic multi-agent surface may find this too composed.
- **The Workspace is one-report-per-question.** Comparing several generated analyses side by side, or pinning parts of different answers, is weaker than a canvas.
- **Home can feel sparse on a calm day.** By design it says "nothing needs you", which demos less impressively than a risk day.
- **Mobile not yet designed.** The rail needs a vertical "next 14 days" list on 390px; the inspector becomes a bottom sheet.

## Technical scope (solo builder, by 20 Oct)

Low-to-moderate. Two page layouts plus a fixed set of typed blocks:
- One reusable chart (history line, forecast line + band, ghost, scenario dashed, buffer, markers, event rail, crosshair). Roughly 1 day in Visx/D3, mostly done as the vanilla prototype in `assets/chart.js`.
- Home: one API call for the cached briefing snapshot (no LLM per visit). Workspace: render the typed `AgentResponse` blocks in a fixed report order; scenario controls re-call `simulate` (deterministic, no LLM).
- Inspector agent trail reads `AgentStep` rows already planned in docs/06.
Estimate: about 3–4 days of frontend for Home + Workspace at this fidelity, which fits Stage 3 only if Stage 1–2 hold. Decision Lab can reuse the Workspace layout (report + inspector) with more controls.

## Fit with FinPilot judging

- Criterion 2/3 (core loop, forecast + simulation): the outlook, scenario toggle and checked alternative put them on the first screen.
- Criterion 4 (grounded advice): insight shows cause → effect → window → next with real figures; no generic tips.
- Criterion 7 (audit): rejected draft, Verifier correction, assumptions and known payments are visible without opening a drawer.
- Criterion 1 (orchestration): visible but understated (inspector trail, sidebar status). Direction B shows it more strongly.

## Fixture note for the coordinator (please reconcile before Stage 2)

The shared fixture's November figures imply a very low November drain: after rent on 1 Nov the forecast sits near £1,590 and only reaches the given £1,380 low on 26 Nov (≈ £8/day), versus ≈ £40/day of everyday spending in October. The workspace chart shows this as an unusually flat November line. Either raise the 1 Nov starting point or lower the 26 Nov low (and the dependent £180 / £720 / £580 figures) so both months share one spending rate.

## Skills applied

- **ui-design:** one accent (signal blue) and reserved status colours; six type sizes and three weights; tokens named by role; text contrast measured (muted 6.7:1, faint 4.9:1 on white / 4.6:1 on canvas, amber text 5.9:1, teal text 6.0:1, accent 4.9:1); critiqued screenshots at ~1440 and 1280 and fixed collisions, label clashes and chart scaling.
- **dataviz:** form chosen per job (line + band for change over time, three metric tiles instead of a KPI grid); palette run through `validate_palette.js` — the amber/teal pair is 6.5 ΔE under protanopia, so every status and series also carries line style, an icon or a direct label; crosshair tooltip on the chart; direct labels on each series plus a legend; one y-axis.

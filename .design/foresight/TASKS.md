# Build Tasks: Foresight UI (Next.js)

Generated from: `.design/foresight/DESIGN_BRIEF.md` + `INFORMATION_ARCHITECTURE.md` + `design/tokens/tokens.css`
Visual reference: `design/hifi/` (owner-approved; aesthetic **"Atelier light"**: airy blue-grey canvas, white cards, Source Serif 4 + Inter, royal-blue forecast)
Date: 12 Oct 2026

## Ground rules

- Build in `frontend/` (Next.js 16, React 19, TypeScript; plain CSS on `app/tokens.css`).
- Every task ships **behind its flag in `features.yaml`**, and the UI hides anything whose flag is off. A task is "done" when its Vitest tests, a Playwright journey and axe (0 serious) pass, and a screenshot at 375/768/1280/1440 matches the hi-fi reference.
- The UI renders numbers **only** from API responses. No literal figures in components; `tests/unit/test_no_fixture_literals.py` scans `frontend/src` and `frontend/app`.
- Components are mobile-first (`min-width` queries) and use semantic tokens only.
- Ordered by backend stage (`docs/10`): a slice starts when its API exists, or against the API-01 fixtures (contract-typed JSON) if the API is late.

### Existing code inventory

| Item | Status |
|---|---|
| `app/tokens.css`, `app/globals.css`, `app/layout.tsx` (fonts via next/font) | **Reuse as-is** |
| `src/lib/features.ts` (timeout, validation, tests) | **Reuse**, extended into a typed API client |
| `src/components/ShippingStatus.tsx` | **Modify**: becomes the "Not shipped yet" state in the app shell and Quality page |
| `app/page.tsx` (Stage 0 placeholder) | **Replace** with Landing |
| Icons, charts, app shell, cards, tables, drawer | **Do not exist**. Port from `design/hifi/assets/{icons.js,charts.js,app.js}` into typed React components (no chart or icon library: inline SVG, as in the hi-fi) |

## Foundation (Stage 1 → early Stage 2)

- [ ] **App shell with real navigation**: sidebar from 1024px, bottom tab bar below 1024px, top bar (ask box, bell, avatar menu with Switch profile, Settings, Quality), "Design prototype"-style environment label replaced by a "Demo data" badge when the demo profile is active. Routes from the IA: `/home`, `/workspace`, `/lab`, `/transactions`, `/activity`, `/settings`, `/quality`. Disabled sections show the "Not shipped yet" state. _Creates: AppShell, SideNav, BottomTabs, TopBar, AvatarMenu. Modifies: ShippingStatus. Establishes the Atelier-light look first._
- [ ] **Icon set and core primitives**: the Lucide-style inline SVG icon component (from `icons.js`), Card, IconChip (tinted circle), Badge (Checked / Rejected / Below buffer / Upcoming), Button (primary / secondary / icon), Tabs (ARIA, keyboard, hash-synced), all with hover, active, focus-visible and disabled states. _New components; Vitest for Tabs keyboard behaviour._
- [ ] **Typed API client and money formatting**: extend `features.ts` into `lib/api.ts` with Zod-equivalent runtime validation of `docs/08` contracts (or generated TS types plus guards), and `formatMoney(minor, currency, locale)` (en-GB £1,284.50; en-IN lakh; zero-decimal currencies). _Modifies: features.ts. Tests: malformed payload → error state, never a fake number._
- [ ] **Chart kit**: `CashFlowChart` (observed solid, forecast line with P10–P90 band, Today rule, buffer dotted, pay-cycle-low markers, tooltip kept inside the plot, ≤4 ticks on mobile), `ScenarioComparison` (baseline vs dashed scenario starting at divergence), `SpendingBars` (horizontal ranked). Tokens: `--color-data-*`. Accessible hidden data table per chart. _Ports `charts.js`; highest visual and technical risk, so it's built early. Tests: renders from contract fixtures; no NaN paths._

## Core UI (Stage 2: agents and the AI Workspace)

- [ ] **AI Workspace shell (100dvh)**: conversation column with independent scroll and a **pinned follow-up input**, thread list, assistant and user bubbles, "Try asking…" chips, and the analysis canvas scrolling separately. Collapsible conversation panel below 1280px, with the input fixed above the bottom tabs on mobile. _Flag: `ask`. Depends on: App shell, primitives._
- [ ] **Answer canvas for `affordability`**: verdict headline, ≤3 key numbers, ScenarioComparison, Checked recommendation card ("What changes" list, two actions), evidence line "Checked by N agents · M drafts rejected · View how". Fixed tab set per the IA "Answer skeleton": Details (weekly cash flow), Recommendation (what-if table plus rejected draft), Transactions, How it was checked (agent timeline). Overview fits one screen at 1440×900. _Flag: `ask` + `checked_advice`. Depends on: Chart kit, the API returning AgentResponse._
- [ ] **Answer canvas for `spending_breakdown` / `trend_or_change`**: verdict, key numbers, SpendingBars by merchant, weekly trend, short transaction list, behaviour-based suggestion. Proves the canvas adapts by intent. _Flag: `ask` + `anomaly_detection`._
- [ ] **Clarifying-question and fallback blocks**: intent confidence < 0.6 → 2–4 option chips; an invalid block → Narrative fallback; out of scope → polite scope statement. _Flag: `ask`._
- [ ] **Evidence drawer**: global overlay via `?evidence=<id>` showing the calculation (inputs, formula summary, engine version, seed), source transactions, finding, the check trail (model vs deterministic steps, rejected drafts with reasons) and timestamps. Opened from any underlined figure and every "View how". _Flag: `audit_trail`. New component._
- [ ] **Workspace welcome (empty) state**: shown when no thread is selected (`/workspace`). Serif line "Ask anything about your money.", the line on computed-then-checked numbers, four starter cards (prepared threads open and stream; questions the engine can answer directly show a quick computed answer; anything else opens the input prefilled and says so), the disclaimer "Guidance, not regulated financial advice.", the recent-threads list with "New question", and the pinned input. 1 column below 768, 2×2 above. Reference: `design/hifi/workspace.html?state=new`. _Flag: `ask`. Depends on: AI Workspace shell._
- [ ] **Inline agent step checklist (compact AgentExecutionTimeline)**: while the answer streams, a vertical checklist in the answer area adds one row per finished SSE step (✓/✗ icon plus words, never colour alone; the rejected draft with its reason; logged time per step; `aria-live="polite"`; `aria-current="step"` on the running step). Only started steps render. On completion it collapses into the evidence line, which becomes a disclosure (`aria-expanded`) that expands the same list in place, with "Full details" → `#checked`. Spinner stops under reduced motion. Replaces the step labels in "Agent progress (loading) state" below. Reference: `workspace.html?state=loading`, `?state=live`, `?q=spending&state=loading`. _Flag: `ask` + `audit_trail`. Depends on: the AgentRun SSE events._
- [ ] **Agent progress (loading) state**: skeleton canvas under the inline step checklist (above), driven by SSE events, with a timeout or error state ("The forecast engine didn't respond. Try again."). _Flag: `ask`._

## Core UI (Stage 3: orientation, decisions, data)

- [ ] **Home**: greeting and serif hero with mountains (`mountains.svg`), four metric cards, CashFlowChart (pay-cycle lows), Financial briefing (≤4 items), Proactive insights (≤3 cards with one action each). Computed on first visit, then cached (the briefing is never regenerated per visit). _Flag: `briefing`. Depends on: Chart kit._
- [ ] **Insight detail** `/insights/[id]`: alert headline and severity, why it was detected (named change plus source observations), before/after projection with at-risk dates, suggested actions with effect and feasibility (including the rejected one), Accept / Dismiss, and an audit trail opening the Evidence drawer. _Flag: `briefing` + `checked_advice`._
- [ ] **Decision Lab**: wide baseline-vs-scenario chart; controls panel (amount, date, income disruption, savings adjustment, buffer) that recalculates through the engine (no AI); scenario chips (current path, holiday, delayed salary, car repair); outcome comparison; interventions with a rejected option and its reason; assumptions and likely-range note; a Goals view. _Flag: `decision_lab` (+ `goals`)._
- [ ] **Transactions**: search, filters (category, date, type), day-grouped rows with provenance, category correction (teaches merchant memory), tabs for Review queue (low confidence), Recurring and Imports. Stacked rows on mobile. _Flag: `ledger`._
- [ ] **Import / onboarding** `/start`: multi-file drop with per-file detected format, rows read and reconciliation status ("Confirm columns" once for an unknown layout, row-level rejection reasons), then Check what we found (income, bills, gap questions only where detected), then Home. _Flag: `csv_import`. Depends on: the import API._
- [ ] **Landing** `/`: split layout from `landing.html`. "Explore the live demo" (sets the demo profile → `/home`) and "Import a CSV statement" (→ `/start`); sign-in shown disabled; the marketing forecast card uses demo data via the API. _Replaces: `app/page.tsx`._
- [ ] **Activity** `/activity`: reverse-chronological feed (insights, recommendations checked or rejected, forecast updates, imports, digests sent, agent runs) with type filters and links into Insight detail, threads and the Evidence drawer. _Flag: `activity` for agent runs and the audit log (shipped 15 Oct); the insight, recommendation and digest items and the filters come with `briefing`._
- [ ] **Quality** `/quality` (public): evaluation results from `latest.json` (categorisation accuracy and macro-F1, forecast MAE and coverage vs baselines, Verifier catch rate, UI suite) with "not measured yet" states and the generated "Not shipped (planned)" list. _Flag: none (always on; it reports honestly whatever exists)._
- [ ] **Settings** `/settings`: profile (name, country, home currency), buffer and goals, digest channel and time, data and privacy (export, delete with typed confirmation). _Flag: `scheduled_digest` for the digest section only._

## Interactions & States

- [ ] **States pass across all surfaces.** Covers: empty (no data yet → import or demo), loading (skeletons), error (API down → retry; **model unavailable** → deterministic results still shown with "explanations unavailable"), stale balance ("balance as of 5 weeks ago → add this month's statement"), uncertain forecast (wide range note), failed import, checked and rejected recommendation, and unverifiable intervention ("couldn't be checked → not recommended").
- [ ] **Follow-up actions**: block actions post structured follow-ups (switch tab, "Try £800", "Save to Decision Lab", "See transactions") without re-classification; the thread updates in place.

## Responsive & Polish

- [ ] **Responsive verification.** Breakpoints: 375, 768, 1024, 1280, 1440. Check: input always visible in the AI Workspace, no horizontal scroll, ≥44px touch targets, charts at ≤4 ticks on mobile, tables stacked below 768.
- [ ] **Dark mode toggle.** The avatar menu offers Light / Dark / System, using the `[data-theme]` tokens. Verify charts (`--color-data-*` dark pair) and every state in dark.
- [ ] **Accessibility pass.** WCAG AA contrast (tokens are pre-checked; verify the composed UI), keyboard paths through nav, tabs, drawer and controls, visible focus rings (`--shadow-focus`), chart data tables for screen readers, `aria-live` for streaming answers and recalculated Lab readouts, reduced motion.

## Review

- [ ] **Design review**: run `/designer-skills:design-review` against `DESIGN_BRIEF.md` with Playwright screenshots of the running app (light and dark, 375/768/1280/1440) before each stage's flags are switched on.

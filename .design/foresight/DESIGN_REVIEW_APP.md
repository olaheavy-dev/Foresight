# Design Review: Foresight app (all pages and Workspace states)

Reviewed against: DESIGN_BRIEF.md
Philosophy: Calm premium fintech, "Atelier light"
Date: 14 Oct 2026
Build: `main` at b8f65f9. Pages captured on a local stack (`docker compose`, demo profile P1, Mesh disabled, so AI shows as paused). Workspace answers captured on the scripted mock API (`e2e/mock-api.mjs`).

## Screenshots Captured

All files are in `.design/foresight/screenshots/`.

| Screenshot | Breakpoint | Description |
| --- | --- | --- |
| `review-{landing,start,home,workspace,lab,transactions,activity,quality,settings}-mobile-375[-dark-mode].png` | Mobile 375 | Every page, light and dark, full page |
| `review-{…}-tablet-768[-dark-mode].png` | Tablet 768 | Every page, light and dark, full page |
| `review-{…}-desktop-1280[-dark-mode].png` | Desktop 1280 | Every page, light and dark, full page |
| `review-*.json` | All | axe violations and horizontal overflow for each capture |
| `app-workspace-{welcome,answer,spending,ai-paused}-*.png` | 375 / 768 / 1280 / 1440, light and dark | Workspace states (mock API) |
| `app-workspace-{recommendation,checked,evidence-drawer,clarify,error,loading,not-shipped}-desktop-1440.png` | 1440 | Workspace tabs, drawer and edge states |

Capture with `SCREENSHOTS=1 npx playwright test app.screenshots` (local stack on :3000) and `SCREENSHOTS=1 npx playwright test -c playwright.workspace.config.ts workspace.screenshots`.
The mobile tab bar appears mid-page in full-page captures. That's an artefact of capturing a `position: fixed` bar in a full-page screenshot, not a layout bug. Repeated "Recent" items in Workspace captures come from earlier runs on the same mock server.

## Summary

The shipped surfaces (landing, Home forecast, Workspace answers, tabs, the checked trail and dark mode) read as the crafted, calm product the brief asks for, and axe finds **no violations on any page at any width**. The biggest problems are layout ones around unshipped features: a placeholder dressed as a metric, and a half-empty briefing column on Home. There's also one real overflow (Quality at tablet) and a duplicated "AI paused" message in the Workspace.

## Must Fix

1. **Quality: the table overflows at tablet width.** The models table is 154 px wider than the viewport at 768 px (`review-quality-tablet-768.png`, `review-quality-tablet-768.json`). The stacked mobile layout only starts below tablet width. _Fix: use the stacked layout up to tablet width, or put the table in a horizontal scroll container._
2. **Workspace: "AI answers are paused" is said twice.** It appears once as a pill under the welcome heading and again as the dock notice. On mobile the two together push the starter cards out of view (`review-workspace-mobile-375-dark-mode.png`, `review-workspace-desktop-1280.png`). _Fix: show it once, in the dock notice, which carries the useful links._

## Should Fix

1. **Home: a placeholder dressed as a metric.** The fourth metric card shows "Not shipped yet" in the serif value slot, so it reads like a figure (`review-home-desktop-1280.png`, `review-home-tablet-768.png`). _Fix: show three metric cards until proactive insights ship._
2. **Home: the briefing column is mostly empty.** The Financial briefing card stretches to the forecast card's height around a small placeholder, leaving a large white area at desktop width (`review-home-desktop-1280.png`, dark as well). _Fix: until the briefing ships, give the forecast the full width and show the briefing and insights placeholders together as one compact "Coming next" card._
3. **Evidence drawer: internal block names.** "Used in this answer" lists "Financial Metric Group", the component's type name (`app-workspace-evidence-drawer-desktop-1440.png`). _Fix: map block types to plain names ("Key figures", "Forecast chart", "Recommendation" …)._
4. **Mock fixture: a percentage rise shown in red.** The spending answer's "+57%" is red (`app-workspace-spending-desktop-1280.png`). The brief keeps red for a genuine shortfall. The real composer already uses caution (amber) for a percentage change; only the mock fixture says `negative`. _Fix: set the fixture's tone to `caution` so review screenshots match the product._

## Could Improve

1. **Placeholder pages are bare.** Decision Lab, Transactions, Activity, Settings and `/start` show one dashed card on an empty canvas (`review-lab-desktop-1280.png`, `review-settings-desktop-1280.png`). Lab, Transactions and `/start` are the next features to be built. Activity and Settings could add a short "what will appear here" preview.
2. **Quality shows the raw run id.** `evalrun_20261014T162812Z_21b5e1e` is useful for judges but heavy. _Suggestion: show the date and link the id._
3. **Home date and data date differ.** The header says "Wed, 14 Oct 2026" while the data is as of 11 Oct. The as-of line is on the balance card; it could also sit next to the header date.

## What Works Well

- **Landing** matches the owner's mockup closely: serif headline, white card on a pale canvas, a disabled sign-in that says why, mountain artwork with the quote, and an honest metric strip.
- **The Home forecast** puts the future first, with observed and forecast clearly split at "Today", the likely range, the buffer line, the lowest point annotated and "if nothing changes" in plain words.
- **Workspace answers** give a one-line verdict in serif, citations as superscripts, key figures, tabs for progressive disclosure, a pinned follow-up input, and rejected drafts shown honestly with strike-through and a reason.
- **Dark mode** is intentional, not an inversion: navy surfaces, a muted band and a readable magenta dashed scenario line.
- **Accessibility:** no axe violations in 54 page captures, consistent 44 px targets on the mobile tab bar, and reduced motion respected.

## Fixes applied (14 Oct 2026, same session)

| Finding | Fix | Verified in |
| --- | --- | --- |
| Must 1: Quality table overflow at 768 | Tables in a focusable, labelled scroll region; long check lists wrap, so they fit with no scrolling | `review-quality-tablet-768.png`, overflow 0, axe 0 |
| Must 2: duplicate "AI paused" message | Welcome pill removed; the dock notice with its links stays | `review-workspace-mobile-375.png` |
| Should 1: placeholder metric card | Home shows three real metrics; the grid is three columns | `review-home-desktop-1280.png` |
| Should 2: empty briefing column | The forecast takes the full width; briefing and insights placeholders share one "Coming next" card | `review-home-desktop-1280.png`, `-mobile-375-dark-mode.png` |
| Should 3: internal block names in the evidence drawer | Plain names ("Key figures", "Recommendation" …) | `app-workspace-evidence-drawer-desktop-1440.png` |
| Should 4: mock fixture shows a rise in red | Fixture tone `caution` (amber), as the real composer uses | `app-workspace-spending-*.png` |

After the fixes: 54 page captures plus the Workspace states show **0 axe violations and 0 horizontal overflow**. Remaining "could improve" items stay open (bare Activity and Settings placeholders, the raw run id on Quality, header date vs data date).

## Import / onboarding (`/start`), built 14 Oct 2026

Captured by `e2e/import.spec.ts` with `SCREENSHOTS=1` (real local stack): `review-import-{files-empty,files-done,check-balance-needed,check-done}-{desktop,mobile,desktop-dark}.png`. The journey passes on desktop, mobile and dark with no serious axe issues: P1's Monzo CSV is imported (1,126 rows, format Monzo, "No balance column"), then "Check what we found" asks for today's balance, shows income and the eight largest regular payments with "Show 7 more", and leads to Home with the declared balance. It follows the auth-card layout used on Landing, with hairline panels, tinted icon chips and badges in green for imported, amber for needs-an-answer or balance-needed, and red for not imported.

## Transactions (`/transactions`), built 15 Oct 2026

Captured by `e2e/transactions.spec.ts` with `SCREENSHOTS=1` (real local stack): `review-transactions-{all,search-edit,review,recurring,imports}-{desktop,mobile,desktop-dark}.png` and `review-transactions-review-viewport-desktop-1280.png`. The views (`?tab=all|review|recurring|imports`) use pill links. Rows are grouped by day, with the bank's description first, a category chip showing where it came from ("Rule · 92%", "Merchant memory", "AI", "You") and right-aligned tabular amounts, money in shown in green. A correction opens inline under the row, with "Apply to all from <payee>"; on the demo it says the profile is read-only. Fixed while building: the violet "Commitment" badge failed axe contrast, so it uses the blue badge; each view now starts fresh rather than keeping the previous view's search and open editor; payee titles use the bank's description instead of the upper-case normalised payee; transfer and savings keys have plain names. Both journeys pass on desktop, mobile and dark, with no serious axe issues.

## Accounts, privacy, editable demo and column mapping, reviewed 15 Oct 2026

> From 15 Oct, `review-*` captures are not committed (they were half the repository's size). Regenerate them with `SCREENSHOTS=1 npx playwright test app.screenshots --project=desktop` against a local stack; failed CI runs keep theirs as Playwright artifacts. A curated final set for the README goes in `docs/screenshots/` at the freeze.

Captured by `e2e/app.screenshots.spec.ts` (`SCREENSHOTS=1`, real local stack) at 375, 768 and 1280 px in light and dark. The spec now also covers the states added today: `review-privacy-*`, `review-menu-open-*`, `review-menu-reset-confirm-*`, `review-start-columns-*` and `review-start-columns-error-*`, alongside every page. That's 84 captures; after the fixes below: **0 axe violations and 0 horizontal overflow** on all of them.

Found and fixed in this review:
- **Duplicate `search` landmarks on Transactions** (axe `landmark-unique`, 1280 px): the top bar's Ask box and the ledger filters were both unnamed `role="search"`. They're now labelled "Ask Foresight" and "Search and filter transactions".
- **A file waiting for a column answer showed contradictory details**: "Rows that didn't add up (1)", whose only entry was the internal "waiting for answers" note, and "Balance check: No balance column" for a file that has one. While a file needs an answer, the card now shows only its format, rows and the question.
- **The privacy page underlined the Foresight logo** (the prose link style caught it). Link styling now applies only to links inside the text.

Checked and kept: the account menu fits at 375 px with the inline Reset demo confirm reachable. The destructive actions (Delete my data, guest "Sign out and delete") use the error colour and stand apart from the calm reset confirm. The column form stacks to one column on mobile and two from 768 px. Each choice shows an example cell, with identifiers withheld or masked. The privacy page reads at a comfortable measure in both themes.

Could improve (open): the column choices show normalised, lower-case names (`value (gbp)`) rather than the file's own headings; and the menu is long on small phones, so it could group Sign out and Delete under a divider.

## Decision Lab, reviewed 15 Oct 2026

Captured by `e2e/app.screenshots.spec.ts` at 375, 768 and 1280 px in light and dark: `review-lab-*` (the empty form) and `review-lab-result-*` (a spread purchase compared with the current path). All 102 captures: **0 axe violations and 0 horizontal overflow** after the fixes below.

Found and fixed while reviewing:
- **The comparison chart rendered solid black areas and the page lost its block styles.** The Workspace's block styles were loaded only on the Workspace page. They're now imported where reused blocks appear (Decision Lab, and Home's checked-advice card, which had the same latent problem), inside `.ws-body.block-host`.
- **The page stopped scrolling.** The Workspace page lock (`.frame:has(.ws-body)`) caught any page with a reused block; it now skips `.block-host`.
- **98 px of horizontal overflow at 375 px.** The chart's hidden data table for screen readers ignored `width: 1px` (tables size to their content). It's now wrapped in a clipping `div.sr-only`, which fixes every page that draws a chart.

Checked and kept: six template cards in a grid from 768 px and stacked on mobile; labelled fields in two columns from 768 px; the result reuses the Workspace's comparison block (current path, dashed scenario line, likely range, a verdict badge and its reason) with a plain note that no AI was used. Refusals appear inline under the form, and a new run clears the previous result.

Could improve (open): the result could also show the scenario's key numbers (lowest balance before and after) as text above the chart.

## Quality run label, reviewed 15 Oct 2026

The Core metrics note now names its run in words ("From the evaluation run of 14 Oct 2026 (commit 21b5e1e)"), with the raw run id kept in a tooltip, instead of `evalrun_20261014T162812Z_21b5e1e`. Captured `review-quality-*` at 375, 768 and 1280 px in light and dark (`SCREENSHOTS=1`, real local stack): **0 axe violations and 0 horizontal overflow** on all six. At 375 px the longer note wraps to three lines within the measure and pushes nothing sideways. This closes the "raw run id on Quality" item left open on 14 Oct.

Could improve (open): the fast tier lists its model twice ("gpt-6-luna, openai/gpt-6-luna") because older recordings stored the name without its provider prefix; the label could normalise names before joining them.

## Settings, reviewed 16 Oct 2026

Captured by `e2e/app.screenshots.spec.ts` (`SCREENSHOTS=1`, real local stack) at 375, 768 and 1280 px in light and dark: `review-settings-*` (the demo copy, with its £500 buffer). All six: **0 axe violations and 0 horizontal overflow**. Journeys: `e2e/settings.spec.ts` (rename and a buffer that is set, survives a reload and is cleared; a bad amount refused; a failed save keeps what was typed; delete and guest sign-out each ask first and can be kept).

Found and fixed in this review:
- **The privacy link in "Your data" was told apart from its sentence by colour alone** (axe `link-in-text-block`, serious). It is now underlined.
- **"Sign out" and "Delete my data" touched**, with no gap between the buttons. They now sit apart, and the destructive one keeps the error colour.

Checked and kept: one card per concern (Profile, Buffer, Your data), each form saving on its own with a quiet "Saved." beside it. The fixed details (country, currency, time zone) read as facts, with one line on why they can't change. The buffer copy promises only what the forecast does ("once Foresight knows your balance"). From 768 px each field and its button share a row; on mobile they stack full width. The page replaces the dashed placeholder flagged open on 14 Oct.

Could improve (open): Settings is reached from the account menu only (the mobile tab bar has five slots); goals and digest delivery will join this page when those features ship.

## Activity, reviewed 15 Oct 2026

Captured by `e2e/app.screenshots.spec.ts` (`SCREENSHOTS=1`, real local stack) at 375, 768 and 1280 px in light and dark: `review-activity-*`, with the demo's empty run list and, in an earlier capture, a profile with an advice run. All six: **0 axe violations and 0 horizontal overflow**. Journeys: `e2e/activity.spec.ts` (no profile yet; an import plus a payee-wide correction shown as one line, audit chain intact).

Found and fixed in this review:
- **The step table on mobile showed bare values** ("coordinator", "1.8 s", "900 / 120") with no column names. Each step now stacks as its label (`td.lead`) and labelled rows (`data-label`), like the other data tables.
- **The empty "No agent runs yet" line sat tight against the card heading.** It now has the same gap as the chain badge below "Changes".

Checked and kept: run summaries read as plain outcomes ("Advised on a question", Done, time, cost), with steps behind a disclosure so the page stays calm. The audit chain badge uses the success colour only when the hash chain checks out, and states plainly what that means. Consecutive identical changes collapse to one line, and the "Traces stay on Foresight's own servers" note says where traces live without technical names.

Could improve (open): a run's steps could show a small time bar so the slow step stands out; the Changes list could page past its latest 40 lines.

## Goals (Decision Lab), reviewed 16 Oct 2026

Captured by `e2e/app.screenshots.spec.ts` (`SCREENSHOTS=1`, real local stack) at 375, 768 and 1280 px in light and dark: `review-lab-goal-*` (the demo with one goal, "Trip home", £1,500 in six months). All six: **0 axe violations and 0 horizontal overflow**. Journeys: `e2e/goals.spec.ts` (add, project, edit, reload, mark achieved, archive; a missing name and a past date refused with the reason; a profile with no known balance told why its goal can't be projected; a failed load says so).

Found and fixed in this review:
- **The chart contradicted the figures.** It drew weekly cash above the buffer, a sawtooth peaking near £4K after each payday, beside "0% chance" and "£0 likely". The engine's trajectory is now progress itself, each pay cycle's low above the buffer up to the target cycle, so the line ends at the projection shown above it (unit test `test_the_trajectory_ends_at_the_progress_it_reports`). The series is labelled "Spare at each low".
- **"Saved now" claimed savings that don't exist.** With residual funding nothing is set aside, so the block reads "Spare now · above your buffer, at the next low".
- **The add form kept the last goal's values** after a successful add. It now starts again.

Checked and kept: the goal block is the Workspace's own (one component, two places). The band badge uses the caution colour for at risk and off track. The required monthly change reads as a plain sentence ("£310.00 more a month would close the gap"). A goal more than 90 days out carries one quiet line about the wider range. Fields lock while the engine projects, as in the Lab.

Could improve (open): goals sit below the what-if on one long page; a "Goals" view switch (`/lab?view=goals`, docs/00 §9) would let each be found directly. The Workspace doesn't answer about stored goals yet.

## Goals sharing spare cash, reviewed 17 Oct 2026

Captured by `e2e/app.screenshots.spec.ts` (`SCREENSHOTS=1`, real local stack) at 375, 768 and 1280 px, light and dark: `review-lab-goals-shared-*` (the demo with "Trip home", £1,500, and "Laptop", £800, both due in six months). All six have **0 axe violations and 0 horizontal overflow**.

Journey: `e2e/goals.spec.ts` "two goals share what's spare". The later goal says what was set aside for the earlier one; archiving the earlier goal re-reads the list, and the note goes.

Checked and kept:
- The note is the Lab's quiet `lab-note` line under the goal block, like the lower-confidence line, so it explains without alarming.
- The second goal's honest result (£0 likely, 0%, "Off track") reads clearly beside the first.
- With only achieved goals, the empty state now says "No goals in progress", not "No goals yet".

Could improve (open): letting the person choose the order goals are funded in, rather than by date.

## Guest network allowance, reviewed 16 Oct 2026

Captured with `SCREENSHOTS=1`:
- `app-workspace-network-limit-*` (`e2e/workspace.screenshots.spec.ts`, mock API) at 375, 768, 1280 and 1440 px, light and dark: a guest question refused because the network has used today's allowance.
- `review-privacy-*` (`e2e/app.screenshots.spec.ts`, real local stack) at 375, 768 and 1280 px, light and dark: the new privacy line about the allowance.

Journeys:
- `e2e/workspace.spec.ts`: the refusal is said plainly with no "Try again", because a network's day is used until tomorrow. It points to signing in and to what still works.
- `e2e/smoke.spec.ts`: the privacy page states how the allowance is counted.

Both pass axe with no serious issues.

Found and fixed in this review:
- **A long question title ran past the Recent list** at 1280 px. The time was pushed out of view and the row overflowed the panel. The list's grid column grew to fit its content. It's now `minmax(0, 1fr)`, so titles end with an ellipsis and the time stays visible. The refusal journey checks that the row stays inside the list.

Checked and kept: the refusal uses the Workspace's existing failure card and caution icon. The thread keeps the person's question. The rate-limit refusal (a burst of questions) still offers a retry.

## Evidence chain, reviewed 18 Oct 2026

Mandatory requirement F: from a recommendation, reach how it was checked, the calculation and finding behind it, and the source transactions. I walked it in the UI first and found three dead ends:
- The card's "N of M checks passed" citation opened a drawer that said the record wasn't available.
- The findings that triggered a recommendation weren't in the answer at all.
- On Home, checked advice had no route to its checks.

Now:
- Every answer showing a recommendation carries "Where the numbers come from" in **How it was checked**. It lists the Verifier's item (each rule in plain words, computed or model check, and that a draft was revised), then the triggering finding with its transaction count and dates, the imported file and rows, the reconciliation wording the Transactions page uses, and "See these transactions".
- The card's citation opens the same Verifier item in the drawer.
- Home's checked advice links "How it was checked" to that run's trace in Activity, which opens and scrolls to it.

Captured with `SCREENSHOTS=1`, `e2e/workspace.screenshots.spec.ts` (mock API), at 375, 768, 1280 and 1440 px, light and dark:
- `app-workspace-verifier-drawer-*`
- `app-workspace-evidence-chain-*`

Journeys:
- `e2e/workspace.spec.ts`: the card citation leads to the checks, then the tab shows the finding, file and link.
- `e2e/activity.spec.ts`: `/activity#run-…` opens that run.

Found and fixed in this review: the source lines first rendered larger than the other evidence lines; they now use the panel's `ev-line` style.

Could improve (open):
- The verification item still shows the "Detected" provenance badge, which reads oddly for a check.
- The arrow icon after "See these transactions" doesn't show at this text size.
- Home's trace link isn't captured on the local stack: it needs a real checked recommendation, which needs a model key. A component test covers it.

## Mesh removed (copy only), reviewed 23 Oct 2026

Two text changes, no layout or style change. The privacy page's "When AI is used" now names OpenAI ("to an AI model from OpenAI, through OpenAI’s API and under its terms") instead of the Mesh gateway. Activity's run line drops "through Mesh" and reads "3 model calls · 5200 tokens in, 1100 out".

Captured on the local stack built from `chore/remove-mesh`, with no model key (`SCREENSHOTS=1 npx playwright test app.screenshots`): every page at 375, 768 and 1280 px, light and dark, including `review-privacy-*` and `review-activity-*`. No horizontal overflow and no serious or critical axe issues on either page. Screenshots are not committed.

Not captured: the Activity run line itself. With no key the stack has no agent runs, so Activity shows its empty state. `ActivityFeed.test.tsx` checks the new wording, and fails on the old.

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

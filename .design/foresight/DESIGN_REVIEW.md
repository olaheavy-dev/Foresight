# Design Review: Foresight hi-fi (landing, home, workspace) · light and dark

Reviewed against: `.design/foresight/DESIGN_BRIEF.md` (and `INFORMATION_ARCHITECTURE.md`)
Philosophy: calm premium fintech ("Atelier light"), light-first, with a deliberate cool-navy night palette from `tokens.css`
Date: 12 Oct 2026 (fourth review: adds the theme control and the dark-mode pass)

## Screenshots Captured

All are in `.design/foresight/screenshots/`, captured with Playwright (`?theme=light|dark`; the Workspace is an app shell, so its screenshots are viewport captures). Each was measured for horizontal overflow, the follow-up input being inside the viewport, the Overview chart's top position, and the lowest text contrast on the page (computed from the rendered colours).

| Screenshot | Breakpoint | Description |
|---|---|---|
| `review-landing-desktop-1440.png` / `-dark-mode.png` | Desktop 1440×900 | Split sign-in / hero; footer theme control |
| `review-landing-desktop-1280.png` / `-dark-mode.png` | Desktop 1280×800 | |
| `review-landing-tablet-768.png` / `-dark-mode.png` | Tablet 768×1024 | |
| `review-landing-mobile-375.png` / `-dark-mode.png` | Mobile 375×812 | Sign-in stacked above the hero |
| `review-home-desktop-1440.png` / `-dark-mode.png` | Desktop 1440×900 | Home after the car repair; pay-cycle-lows chart |
| `review-home-desktop-1280.png` / `-dark-mode.png` | Desktop 1280×800 | |
| `review-home-tablet-768.png` / `-dark-mode.png` | Tablet 768×1024 | |
| `review-home-mobile-375.png` / `-dark-mode.png` | Mobile 375×812 | Bottom tab bar, 1-up cards |
| `review-home-avatar-menu-desktop-1440.png` / `-dark-mode.png` | Desktop crop | Avatar menu open: Switch profile · Settings · Quality checks · Theme |
| `review-workspace-desktop-1440.png` / `-dark-mode.png` | Desktop 1440×900 | Holiday thread, Overview |
| `review-workspace-desktop-1280.png` / `-dark-mode.png` | Desktop 1280×800 | Three-column shell, pinned input |
| `review-workspace-tablet-768.png` / `-dark-mode.png` | Tablet 768×1024 | Collapsible conversation |
| `review-workspace-mobile-375.png` / `-dark-mode.png` | Mobile 375×812 | Chart now within the first viewport |
| `review-workspace-spending-{desktop-1440,desktop-1280,tablet-768,mobile-375}[-dark-mode].png` | All | Spending thread (different composition) |
| `review-workspace-tab-*-desktop-1440.png`, `review-workspace-loading-desktop-1440.png` | Desktop 1440 | Per-tab and loading state (from the previous review, unchanged) |

Measured across all 32 page × size × theme combinations:
- Horizontal overflow: **0 px** everywhere.
- Follow-up input visible: **yes** at every Workspace size, in both themes.
- Lowest text contrast: **4.66:1** in light ("Below buffer" badge on its tint) and **4.88:1** in dark. No text is below WCAG AA 4.5:1.
- Workspace at 375×812: the Overview chart starts at **555 px**, above the pinned input (it was at 790 px).

## Summary

Every Must and Should item is resolved in both themes:
- The pages now have a Light / Dark / System control.
- They render correctly in the night palette using semantic tokens only. There are no hex or rgba literals in the CSS/JS, and no inline SVG fills in the HTML. The artwork is adapted with filters and blend modes, not new colours.
- On phones the Overview chart is in the first viewport.
- The conversation links no longer wrap at 320 px.

What remains is polish (Could Improve).

## Fixed in this pass

| Item | Now | Evidence |
|---|---|---|
| Should: chart below the fold on phones (Workspace) | On phones the chart card follows the verdict, before the key numbers. The evidence line and the spending suggestion come after. The action icons share the "AI Analysis" row. The "Try asking" chips appear only while the composer is focused (always visible from 768 up). Chart top 790 → 555 px; the spending thread now leads with its weekly chart. | `review-workspace-mobile-375*.png`, `review-workspace-spending-mobile-375*.png` |
| Should: action links wrapping in the 320 px conversation column | Labels shortened to Compare · Week by week · Your plan · Transactions, with `white-space: nowrap` and an ellipsis guard. One line each at 1280 and 1440. | `review-workspace-desktop-1280.png` |
| Dark mode (new) | `assets/theme.js` in `<head>` applies the saved choice before first paint, honours `?theme=`, and falls back gracefully without storage. The avatar menu ("Switch profile" is a single constant) and a landing footer offer a Light / Dark / System radio group with arrow-key support; System follows `prefers-color-scheme` live. Charts redraw on theme change because they read the `--color-data-*` tokens at render time. The logo and assistant mark are drawn from tokens. The mountains use brightness plus `mix-blend-mode: luminosity`, so they take the navy hue. | `*-dark-mode.png`, `review-home-avatar-menu-*` |
| Contrast regression (found in this pass) | Faint text on tinted surfaces measured 4.46:1 in light (search placeholder, the "Conversation" label). Faint text on tinted surfaces now uses `--color-text-secondary`. | Contrast probe: minimum is now 4.66:1 |

## Must Fix

None.

## Should Fix

None.

## Could Improve

1. **Rejected-draft styling.** The serif strikethrough on the rejected £90 draft is readable but heavy. A quiet "Rejected" badge on plain text may read better.
2. **Overdrawn path on the Overview.** The 6 Nov "overdrawn" path appears only in the Recommendation tab. A small marker label on the Overview chart would make the risk visible at a glance.
3. **"Remind me on Friday"** on the spending suggestion has no backend. Keep it behind a flag in the real app, or replace it with "Not now".
4. **Dark landing artwork** is a calm slate-navy. If the owner wants more contrast between the ridge layers at night, a dedicated night variant of `mountains.svg` (generated by `design/fixture/make_mountains.py` with token-derived stops) would give finer control than filters.
5. **Avatar menu items** link to `#` in the prototype. Wire them to `/settings`, `/quality` and the profile switcher in the real app (see `TASKS.md`).

## What Works Well

- **Aesthetic fidelity:** both themes read as the same product as the owner's mockups. Light is airy and blue-grey; night is cool navy with the same hierarchy. Neither is a simple inversion.
- **Token discipline:** semantic tokens only, verified by audit. The theme switch costs no extra CSS beyond the token file, apart from the artwork treatment.
- **Honest content holds in both themes:**
  - The data styles (observed solid, forecast line and band, dashed scenario, dotted buffer, Today rule) are all visible in dark.
  - The colour-blind-validated dark chart pair from the tokens renders as intended.
- **App-shell Workspace:** the input is never off screen at any size, and the Overview answers the question first on every device.
- **Accessibility:**
  - Every rendered text element measures at least 4.5:1 in both themes.
  - The theme control is a proper radiogroup with keyboard support.
  - Focus rings use `--shadow-focus`, and reduced motion zeroes the duration tokens.

## Answer skeleton check (12 Oct 2026)

Rule: `.design/foresight/INFORMATION_ARCHITECTURE.md` › "Answer skeleton". Applied to both Workspace threads (`workspace.html`, affordability; `workspace.html?q=spending`, trend_or_change).

Verified with Playwright and asserted programmatically:

- **Same tabs, same order, same names** in both threads: Overview · Details · Recommendation · Transactions · How it was checked (`#overview #details #recommendation #transactions #checked`). Old hashes redirect: `#cashflow` and `#impact` → `#details`; `#methodology` → `#checked`. No tab is empty in either thread, so none are hidden.
- **Same Overview slot order** (`data-slot`) in the DOM: verdict → keynums → visual → todo → evidence, in both threads.
- **Same rendered order** in both threads at every size and theme:
  - 1440 light and dark: keynums → visual → what to do → evidence.
  - 375 light and dark: visual → keynums → what to do → evidence, the same mobile order for both.
- **Same evidence wording**, linking to `#checked`: "Checked by 6 agents · 1 draft rejected" and "Checked by 4 agents · 1 draft rejected".
- **Content now in its tabs:**
  - Spending: the per-app breakdown and the three 30-day periods moved into Details; the rejected £40 draft is in Recommendation; recent orders are in Transactions.
  - Affordability: "Impact on plan" merged into Details.
- **Other checks:** the follow-up input is visible, there's no horizontal overflow, there are no console errors, and no fixture value falls back to "—", in both threads at 1440 and 375, in light and dark.

Screenshots: `review-workspace{,-spending}-desktop-1440*.png`, `-mobile-375*.png`, and `review-workspace{,-spending}-tab-{overview,details,recommendation,transactions,checked}-desktop-1440.png`. The superseded per-tab shots for cashflow, impact and methodology were removed.

Result: **pass**, with no new Must or Should items.

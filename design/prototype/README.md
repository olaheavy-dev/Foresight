# Foresight: static hi-fi prototype

Open `index.html` in a browser. No build step and no server needed. It needs internet only for Google Fonts.

| Page | Experience |
|---|---|
| `index.html` | Briefing for Amara Nwosu (one Monzo account): where you stand, what’s likely next, what changed, act on this, under investigation |
| `ask.html` | Agent Workspace: "Can I afford £640 flights home for Christmas?" answered with typed blocks, evidence chips, and an execution timeline that shows the Verifier rejecting and revising a recommendation |
| `lab.html` | Decision Lab: flights scenario (docs/04 §5.1), with chips, a chart with the 41-day bracket, the comparison table and Make it work |
| `ledger.html` | Ledger: transactions with UK payment-type tags, Review (38 to check), Recurring, Statements, Activity |
| `onboarding.html` | `/start` in three steps (docs/04 §8): drop statements (per-file detected format, reconciled, confirm columns, rejected), check what we found (one balance question), your briefing |
| `household.html` | P3 Mensah household: the multi-account layer (scope selector, coverage indicator, money map, joint-account consent, Capital One card gap question). P1 never sees it. |
| `india.html` | P4 India workspace (fictional Aanya Rao): en-IN formatting (₹1,15,000, dd-mm-yyyy), XLS import row, UPI/NEFT/IMPS/NACH ledger excerpt, locale-pack summary, and the note that India support is validated on test data only |
| `components.html` | Design-system sheet (Broadsheet tokens, type, controls, chart grammar, states) |
| `states.html` | Loading, streaming, empty, error and partial states, ambiguous-currency confirm, second-currency balance, no-regular-income state, proactive event catalogue, Telegram digest |

Interactions: any dotted-underlined figure or evidence chip opens the **Evidence drawer** (Esc closes it). Tabs, scope and edition toggles work, and charts have a hover crosshair and tooltip.
The rail's bottom item is the **workspace switcher** (Amara, Jamie, Kofi & Hannah, Aanya, New workspace).
URL params: `?theme=light|dark`, `?ws=open` (opens the workspace switcher) and `?evidence=<key>` (e.g. `index.html?evidence=rec_plan`).

Files: `assets/foresight.css` holds the tokens and components, `assets/app.js` the shell, drawer and evidence registry, and `assets/charts.js` the SVG forecast renderer with the canonical P1 series.

Aligned specification: decision register rev 5.1; this static prototype demonstrates fixture states, not backend behaviour. Import, consent, verification, scheduling and numerical controls do not execute the planned product pipeline.

All people, accounts and figures are fictional design fixtures from `docs/00-DECISION-REGISTER.md` §10a, `docs/04` (marked “04 fixture”) and `docs/07` (P3). They are not engine output. The prototype is GBP/en-GB, except `india.html` (INR/en-IN) and the currency states.

The displayed engine seed `0x4F1C` and shortened evidence IDs are prototype annotations; public generator seed `1729` and full ULIDs belong to the planned production contracts. The £300 P1 buffer is a chosen fixture setting, not the one-month-essential-bills default.

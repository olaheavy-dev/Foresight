# Status

Last updated: 18 Nov 2026

What is done, open and next, so any session (person or agent) can pick up from the repository. Any pull request that changes what is done, open or next, or a decision, a plan or the backlog, updates this file in the same pull request.

## Where things stand

Foresight was frozen as portfolio-ready on 25 Oct 2026, after the narrated demo video (#81) and the README and case-study links to it (#83). Since then, only maintenance has gone in:

- **#84** (17 Nov) bumped Next.js from 16.4.2 to 16.4.5, which clears [GHSA-mfr8-8qww-v76h](https://github.com/advisories/GHSA-mfr8-8qww-v76h). That advisory had turned the scheduled Security run red earlier the same day.
- The post-deploy smoke run after #84 failed once because the live server timed out, then passed on a rerun (18 Nov). See #85.

## Open pull requests

None apart from the one that adds this file.

## Next

1. **#85** Post-deploy smoke: live-site journeys time out and pass only on retry. Every recent smoke run has had 2–5 tests that passed only on a retry. Start by timing guest profile creation, the demo copy, the first forecast and CSV import on the live stack. #56 may contribute (the first forecast hits the engine, and the smoke runs journeys in parallel), but nobody has measured that yet. #74 is related.

## Known limitations, left open on purpose

These are kept as honest write-ups of what the build doesn't do yet, not as planned work:

- **#56** Concurrent engine requests take about 10× as long as one alone on 1 CPU.
- **#58** Forecast draws aren't prefix-stable across horizons (goals past 90 days, extended what-ifs).
- **#61** Guest allowance: a duplicate retry of the network's last question can be refused instead of joining the run.

## Blockers

None.

## Owner to-dos

- Decide whether to work on #85 (and #56 with it) or keep the freeze.
- Optional: upload the demo `.mp4` through the github.com editor so the README can embed a player instead of linking the file.

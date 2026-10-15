# Foresight: guidance for coding agents

`CLAUDE.md` is a symlink to this file, so Claude Code, Codex and other agents read the same rules. Canonical product decisions live in `docs/00-DECISION-REGISTER.md`; the design source of truth is `.design/foresight/DESIGN_BRIEF.md`.

## What this is

An agent-native personal-finance workspace (Agent Arena 2026). Next.js frontend (`frontend/`), FastAPI backend (`backend/app`), a deterministic finance engine (`backend/finance_core`), LangGraph agents (`backend/agents`), PostgreSQL, and every model call through the Mesh gateway (`backend/mesh/mesh_client.py`). Features ship behind flags in `features.yaml`, and evaluation suites live in `evals/`.

## Commands

| Task | Command |
|---|---|
| Lint, types, import contracts, unit tests | `make check` |
| PostgreSQL integration tests | `DATABASE_URL=… make test-db` |
| Fast eval and regression gate (before every push) | `make eval-fast` |
| Full eval (replay, no model spend) | `make eval` |
| Frontend | `cd frontend && npm run typecheck && npm test && npm run format:check` |
| Browser journeys (real stack) | `docker compose up -d`, then `cd frontend && npx playwright test` |
| Workspace journeys (mock API) | `cd frontend && npx playwright test -c playwright.workspace.config.ts` |
| Regenerate API contracts | `python -m tools.export_schemas` (then commit `frontend/src/ui-contracts/*`) |

Evals replay recorded model responses by default (`evals/cassettes/`). Recording calls Mesh and **spends money**: never record without an owner-approved hard cap, and batch changes so each set is recorded once.

## Code review rules

Review every change against these rules. A finding names the rule, the file and line, and a concrete failure case.

### 1. Access: every workspace resource is owned

- Every endpoint that reads or writes workspace data resolves **session → ownership → workspace** through the `Profile` dependency (`backend/app/session.py`). That covers threads, messages, the run event stream (`/api/runs/{id}/events`), stored responses, evidence and calculations, imports, corrections, and follow-up or background runs.
- A resource from another workspace returns **404**, never 403 or the data, so its existence doesn't leak. Test cross-access with two clients (`make_client`), including two visitors on the same demo persona.
- The client never chooses a workspace by id (header, query or body). Background work receives its workspace id from the server, never from a cookie.
- Seeded demo templates (`kind = "demo"`) are never served to a browser; guests get private `sample` copies. `demo` and `sample` workspaces are read-only for imports and edits.
- State-changing `/api/*` calls must carry the `X-Foresight-Client` header (CSRF). New frontend writes must send it.
- Session tokens, OAuth secrets and account numbers never appear in logs, responses, fixtures or commits. Deleting user data goes through the purge path (`foresight.purge`) so the audit chain is removed with it.

### 2. Money: figures come from the engine, advice is checked

- Every number a user sees comes from `finance_core`, through a stored calculation (`calc_…` refs) or a hydrated `MoneyValue`. Model text never supplies a figure: model output uses placeholders, and numerals outside placeholders are rejected.
- Money is integer minor units with an ISO currency, never floats. Display rounding happens only at the edge.
- Only Verifier-approved recommendations are published. Rejected or withdrawn drafts appear only in the audit trail and the "How it was checked" view, labelled as such. No code path may publish a draft without a Verifier approval.
- Any ledger change (import, correction, declared balance) bumps `data_version`, so cached forecasts and answers can't go stale.

### 3. Models: Mesh only, recorded and costed

- All application model calls go through `MeshClient` (Mesh gateway). No direct provider SDKs or HTTP calls; `make imports` enforces this.
- A new or changed prompt, schema or model invalidates recordings. The PR says which suites need re-recording and the estimated cost, and recording waits for an approved cap.
- Report model cost and latency changes against the core metrics (E-EFF: cost, accuracy, latency).

### 4. Contracts, flags and claims

- A backend contract change (`backend/app/ui_contracts`) is regenerated (`tools.export_schemas`) and the frontend still compiles and validates payloads. Prefer additive, optional fields; breaking changes need every client updated in the same PR.
- A feature flag turns on only when its linked suites pass **and** its required targets are measured: a null target is not a pass. Check `features.yaml`, the gate result and `tools/check_feature_flags.py`.
- README, `/quality` and UI copy claim only what was measured, with its dataset and mode (replay, live, generated, holdout). Failures are disclosed, never hidden by relaxing a target; a target or baseline change needs an `evals/CHANGELOG.md` entry with the reason.

### 5. Tests and UI

- A bug fix comes with a regression test that fails without it. Isolation changes come with a two-browser test.
- UI changes pass axe with no serious issues and no horizontal overflow at 375, 768 and 1280 px, light and dark, and match the Atelier design brief.
- Copy: "Checked", not "Verified"; no regulated financial-product advice; no claims bank data can't support (say "overlap", not "unused subscription"); fictional data is labelled.

## Working rules

- Keep diffs focused; match the surrounding code's style and comment density.
- Never put infrastructure details (IPs, hosts, other apps) in this public repository.
- Ask before spending on Mesh, changing a frozen eval set (`evals/datasets/authored/`), or changing an owner decision recorded in `docs/00-DECISION-REGISTER.md`.

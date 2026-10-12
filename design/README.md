# design/ — illustrative artefacts only

Everything in this folder is a **design artefact with fictional data**. Nothing here is imported, loaded or served by the product at runtime.

| Folder | What it is |
|---|---|
| `hifi/` | **Current visual reference ("Atelier light").** Static hi-fi screens (Landing, Home, AI Workspace; light and dark) built on `tokens/`. |
| `tokens/` | `tokens.css`, the design tokens (served to the app as `frontend/app/tokens.css`). |
| `fixture/` | `fixture.json` and the scripts that generate it and the P1 contracts; the source of every P1 design figure. |
| `prototype/` | **Superseded** by `hifi/`. The earlier "Broadsheet" static mock; kept for history only. |
| `concepts/` | **Superseded** by `hifi/`. Direction explorations; kept for history only. |
| `contracts/` | Example `AgentResponse` payloads that illustrate the schemas in `docs/08-GENERATIVE-UI-CONTRACTS.md`. They are documentation, not fixtures the app reads. |

The figures here (for example £2,184.50 or £8,388) are design fixtures from `docs/00-DECISION-REGISTER.md` §10a. The product computes its own numbers from imported data; `tests/unit/test_no_fixture_literals.py` fails if any of these literals appear in `backend/`, `frontend/src` or `frontend/app`.

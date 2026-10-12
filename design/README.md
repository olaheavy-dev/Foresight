# design/ — illustrative artefacts only

Everything in this folder is a **design artefact with fictional data**. Nothing here is imported, loaded or served by the product at runtime.

| Folder | What it is |
|---|---|
| `prototype/` | Static HTML/CSS/JS mock of the five experiences, built before any product code. Every page shows an "Illustrative design prototype" banner. |
| `contracts/` | Example `AgentResponse` payloads that illustrate the schemas in `docs/08-GENERATIVE-UI-CONTRACTS.md`. They are documentation, not fixtures the app reads. |

The figures here (for example £116.39 or £640) are design fixtures from `docs/00-DECISION-REGISTER.md` §10a. The product computes its own numbers from imported data; `tests/test_no_fixture_literals.py` fails if any of these literals appear in `backend/` or `frontend/`.

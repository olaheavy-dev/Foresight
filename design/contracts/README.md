# Example agent response contracts (illustrative)

Six example `AgentResponse` payloads with **fictional data**, illustrating the schemas in `docs/08-GENERATIVE-UI-CONTRACTS.md`. They are documentation only: **never loaded at runtime** and not used as test fixtures for product output. Real responses are hydrated from persisted calculations.

Files 01–05 (persona P1) are **generated** by `design/fixture/build_contracts.py` from `design/fixture/fixture.json`, so every figure matches the hi-fi screens and register §10a. Regenerate them rather than editing by hand. File 06 (P4, India) is maintained by hand from `docs/07` §10a. Every block carries a `placement` (an Overview slot — `verdict`, `key_numbers`, `main_visual`, `what_to_do` — or one of the fixed tabs `details`, `recommendation`, `transactions`, `checked`), following the answer skeleton in `docs/08` §7a.

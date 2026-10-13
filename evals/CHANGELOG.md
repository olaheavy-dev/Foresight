# Eval baseline changelog

`evals/results/baseline.json` is the last accepted run. The regression gate (`python -m evals.regression`, docs/09 §16) compares every run with it and fails on a headline regression beyond tolerance. To accept a deliberate trade-off, replace `baseline.json` with the new run's `summary.json` in the same commit and add a line here naming its `run_id` and why. A baseline whose `run_id` is not listed here fails the gate.

- `evalrun_20261013T080503Z_2732b6c`: first accepted run (Stage 1, deterministic suites only). Numbers are as measured, including the targets missed. The working tree had uncommitted storage, API and frontend work from parallel Stage 1 tasks; none of it is imported by the eval suites.

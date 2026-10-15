.PHONY: install test test-db lint typecheck imports check eval eval-fast demo down

PY ?= python
EVAL_TMP ?= $${TMPDIR:-/tmp}/foresight-evals

install:
	$(PY) -m pip install -r requirements-dev.txt
	cd frontend && npm ci  # the pre-push hook runs Prettier, tsc, Vitest and the contract codegen
	pre-commit install

test:
	$(PY) -m pytest -m "not postgres"

test-db:  ## needs DATABASE_URL pointing at PostgreSQL (e.g. `docker compose up -d postgres`)
	$(PY) -m pytest -m postgres

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy

imports:  ## Mesh-only and module-boundary contracts (docs/05 §3.1)
	lint-imports

check: lint typecheck imports test
	$(PY) -m tools.check_feature_flags
	$(PY) -m tools.render_readme_status --check
	$(PY) -m tools.render_results --check

eval-fast:  ## < 60 s deterministic subset + regression gate, before every push (docs/09 §16)
	$(PY) -m evals.run --suite all --fast --results-dir $(EVAL_TMP)
	$(PY) -m evals.regression --latest $(EVAL_TMP)/latest.json

eval:  ## every deterministic suite → evals/results/, regression gate, README results table
	$(PY) -m evals.run --suite all
	$(PY) -m evals.regression
	$(PY) -m tools.render_results

demo:  ## postgres + api + web on http://localhost:3000
	docker compose up --build -d
	@echo "Foresight is starting on http://localhost:3000 (API health: http://localhost:8000/healthz)"

down:
	docker compose down

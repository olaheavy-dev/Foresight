.PHONY: install test test-db lint typecheck imports check demo down

PY ?= python

install:
	$(PY) -m pip install -r requirements-dev.txt
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

demo:  ## postgres + api + web on http://localhost:3000
	docker compose up --build -d
	@echo "Foresight is starting on http://localhost:3000 (API health: http://localhost:8000/healthz)"

down:
	docker compose down

#!/bin/sh
# Apply migrations, seed the demo workspaces (DEMO-01), then serve. A failed seed is logged and the
# app still starts; set SEED_DEMO=0 to skip seeding.
set -eu
alembic upgrade head
if [ "${SEED_DEMO:-1}" = "1" ]; then
    python -m backend.pipeline.seed_demo || echo "entrypoint: demo seeding failed; starting anyway" >&2
fi
exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --proxy-headers

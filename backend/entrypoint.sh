#!/bin/sh
# Apply migrations, then serve. Demo-workspace seeding joins here in DEMO-01 (docs/10).
set -eu
alembic upgrade head
exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --proxy-headers

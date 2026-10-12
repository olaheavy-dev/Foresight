"""FastAPI application: HTTP only, no business logic (docs/05 §3.1)."""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.features import load_features
from backend.settings import get_settings
from backend.storage.db import database_reachable


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Foresight API", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        """Readiness probe: deploy SHA and database reachability (docs/05 §12)."""
        db_ok = database_reachable(settings.database_url) if settings.database_url else None
        return {
            "status": "ok" if db_ok is not False else "degraded",
            "sha": settings.deploy_sha,
            "database": db_ok,
        }

    @app.get("/api/features")
    def features() -> dict[str, object]:
        """Which features are shipped. The UI hides anything disabled (docs/01 FR-86)."""
        return {
            "features": [
                {"key": f.key, "stage": f.stage, "title": f.title, "enabled": f.enabled}
                for f in load_features(settings.features_file)
            ]
        }

    return app


app = create_app()

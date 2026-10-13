"""FastAPI application: HTTP only, no business logic (docs/05 §3.1)."""

from __future__ import annotations

from fastapi import FastAPI, Response, status

from backend.app.routers import ask, engine, imports, ledger
from backend.app.routers import session as profile
from backend.features import load_features
from backend.settings import get_settings
from backend.storage.db import database_reachable


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Foresight API", version="0.1.0")

    @app.get("/healthz")
    def healthz(response: Response) -> dict[str, object]:
        """Readiness probe (docs/05 §12): 503 if a configured database is unreachable, so
        Docker health checks, CI and post-deploy smoke tests never pass a broken deploy."""
        db_ok = database_reachable(settings.database_url) if settings.database_url else None
        ready = db_ok is not False
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if ready else "unavailable",
            "sha": settings.build_sha,
            "database": db_ok,
            # A word only (ok | low | unavailable), never a balance figure.
            "ai": ask.ai_status(ask.get_mesh()),
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

    for router in (profile.router, imports.router, ledger.router, engine.router, ask.router):
        app.include_router(router)
    return app


app = create_app()

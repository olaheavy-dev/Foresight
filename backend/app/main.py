"""FastAPI application: HTTP only, no business logic (docs/05 §3.1)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from backend.app import demo_pool
from backend.app.routers import ask, auth, engine, financial_data, imports, ledger
from backend.app.routers import session as profile
from backend.app.session import CSRF_HEADER
from backend.features import load_features
from backend.settings import get_settings
from backend.storage.db import database_reachable, session_factory


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if demo_pool.enabled():
        try:
            with session_factory(get_settings().database_url)() as db:
                demo_pool.warm(db)
        except Exception:  # noqa: BLE001 - a cold pool still works (requests wait for a seed)
            demo_pool.log.exception("demo pool: warm-up failed")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Foresight API", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def require_client_header(request: Request, call_next):  # type: ignore[no-untyped-def]
        """CSRF (docs/05 §7.2): every state-changing API call must carry the custom
        `X-Foresight-Client` header. A cross-site page can't add one to a request that sends the
        session cookie, and the API answers no CORS preflight."""
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and request.url.path.startswith("/api/")
            and not request.headers.get(CSRF_HEADER)
        ):
            return JSONResponse(
                {"detail": "Missing client header."}, status_code=status.HTTP_403_FORBIDDEN
            )
        return await call_next(request)

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

    routers = (
        profile.router,
        auth.router,
        imports.router,
        ledger.router,
        ledger.categories_router,
        financial_data.router,
        engine.router,
        engine.public_router,
        ask.router,
    )
    for router in routers:
        app.include_router(router)
    return app


app = create_app()

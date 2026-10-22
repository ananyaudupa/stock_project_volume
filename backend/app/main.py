import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, cron, scans, stocks
from app.core.auth import require_login
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging

DISCLAIMER = (
    "Market-data screening tool. Rankings measure price movement and volume activity only; they are not "
    "investment advice, a recommendation to buy or sell, or a guarantee of future performance."
)

DEFAULT_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    if settings.app_env == "production" and not settings.app_password:
        raise RuntimeError("APP_PASSWORD must be set in production")

    app = FastAPI(title="NSE Daily Stock Scanner", version="1.0.0", description=DISCLAIMER)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Admin-Key", "X-Cron-Token"], allow_credentials=True,
    )
    install_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(scans.router, dependencies=[Depends(require_login)])
    app.include_router(stocks.router, dependencies=[Depends(require_login)])
    app.include_router(admin.router)
    app.include_router(cron.router)

    access_log = logging.getLogger("access")

    @app.middleware("http")
    async def _log_requests(request: Request, call_next):
        response = await call_next(request)
        access_log.info("request", extra={"method": request.method, "path": request.url.path, "status": response.status_code})
        return response

    @app.get("/api/health", tags=["meta"])
    def health():
        return {"status": "ok", "disclaimer": DISCLAIMER}

    # Serve the built website from the same origin as the API, so the login cookie is first-party.
    dist = Path(settings.frontend_dist) if settings.frontend_dist else DEFAULT_DIST
    if (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="site")

    return app


app = create_app()

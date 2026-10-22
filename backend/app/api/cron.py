"""HTTP trigger that runs due scans inside the web process. Disabled unless CRON_TOKEN is set.

Not used in the free Render deployment: its ~0.1 CPU instance cannot run a 494-stock scan while
serving the site. Only enable this on a host with real CPU; otherwise trigger the GitHub
workflow (see .github/workflows/scans.yml)."""

import hmac
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import calendar_dep, now_dep, provider_dep, session_factory_dep
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.trading_calendar import TradingCalendar
from app.scheduler import cron
from app.services.market_data.base import MarketDataProvider

router = APIRouter(prefix="/api/cron", tags=["cron"])
log = logging.getLogger("cron")


def require_cron_token(x_cron_token: str | None = Header(default=None), settings: Settings = Depends(get_settings)):
    if not settings.cron_token:
        raise ApiError(403, "cron_disabled", "CRON_TOKEN is not configured")
    if not x_cron_token or not hmac.compare_digest(x_cron_token.encode(), settings.cron_token.encode()):
        raise ApiError(401, "unauthorized", "Missing or invalid cron token")


def _run(**kwargs) -> None:
    try:
        code = cron.main(**kwargs)
        log.info("cron trigger finished", extra={"exit_code": code})
    except Exception:
        log.exception("cron trigger crashed")


@router.post("/run", status_code=202, dependencies=[Depends(require_cron_token)])
def run_due(
    background: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    factory: sessionmaker[Session] = Depends(session_factory_dep),
    provider: MarketDataProvider = Depends(provider_dep),
    calendar: TradingCalendar = Depends(calendar_dep),
    now: datetime = Depends(now_dep),
):
    job = cron.due_job(now, settings)
    if job is not None:
        background.add_task(_run, now=now, factory=factory, settings=settings, provider=provider, calendar=calendar)
    return {"due": job, "started": job is not None, "ist": now.astimezone(settings.tz).isoformat()}

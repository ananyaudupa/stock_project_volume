"""Admin endpoints. All routes require the X-Admin-Key header (see core/security.py)."""

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.api.deps import calendar_dep, get_db, now_dep, provider_dep, session_factory_dep, settings_dep
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import require_admin
from app.core.trading_calendar import TradingCalendar
from app.models import ScanRun, ScanSession, ScanType
from app.schemas.scans import AdminRunOut, AdminRunRequest, AttemptOut
from app.services.market_data.base import MarketDataProvider, ProviderError
from app.services.performance import measure_close_performance
from app.services.scanner import ScanRefused, run_scan, scheduled_time

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])
log = logging.getLogger("audit")


def admin_run_out(run: ScanRun) -> AdminRunOut:
    return AdminRunOut(
        run_id=run.id, trading_date=run.trading_date, session=run.session, scan_type=run.scan_type, status=run.status,
        provider=run.provider, is_mock_data=run.is_mock_data, scheduled_at=run.scheduled_at, started_at=run.started_at,
        completed_at=run.completed_at, duration_ms=run.duration_ms, error_message=run.error_message,
        algorithm_version=run.algorithm_version, classification_version=run.classification_version,
        config=run.config or {}, summary=run.summary or {},
        attempts=[AttemptOut.model_validate(a, from_attributes=True) for a in run.attempts],
    )


@router.post("/scans/run", response_model=AdminRunOut)
def trigger_scan(
    body: AdminRunRequest,
    db: Session = Depends(get_db),
    factory: sessionmaker[Session] = Depends(session_factory_dep),
    provider: MarketDataProvider = Depends(provider_dep),
    settings: Settings = Depends(settings_dep),
    cal: TradingCalendar = Depends(calendar_dep),
    now: datetime = Depends(now_dep),
):
    trading_date = body.trading_date or now.astimezone(settings.tz).date()
    as_of = None
    if body.use_scheduled_time:
        if not provider.capabilities.point_in_time_quotes:
            raise ApiError(409, "unsupported", f"provider '{provider.name}' cannot serve point-in-time quotes")
        as_of = scheduled_time(trading_date, ScanSession(body.session), settings)
    log.info("admin scan trigger", extra={"trading_date": str(trading_date), "session": body.session, "scan_type": body.scan_type})
    try:
        run = run_scan(
            factory, trading_date, ScanSession(body.session), provider=provider, scan_type=ScanType(body.scan_type),
            trigger="admin", as_of=as_of, settings=settings, calendar=cal,
        )
    except ScanRefused as exc:
        raise ApiError(409, exc.code, str(exc))
    fresh = db.get(ScanRun, run.id, options=[selectinload(ScanRun.attempts)])
    return admin_run_out(fresh)


@router.get("/scans/{run_id}", response_model=AdminRunOut)
def inspect_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(ScanRun, run_id, options=[selectinload(ScanRun.attempts)])
    if run is None:
        raise ApiError(404, "run_not_found", f"No scan run with id {run_id}")
    return admin_run_out(run)


class PerformanceRequest(BaseModel):
    trading_date: date


@router.post("/performance/run")
def trigger_performance(
    body: PerformanceRequest, db: Session = Depends(get_db), provider: MarketDataProvider = Depends(provider_dep)
):
    try:
        added = measure_close_performance(db, body.trading_date, provider)
    except (ProviderError, ValueError) as exc:
        raise ApiError(409, "performance_unavailable", str(exc))
    return {"trading_date": body.trading_date, "rows_added": added}

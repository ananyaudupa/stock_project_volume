"""Deterministic scoring engine. Pure functions: no I/O, no clock, no randomness.

For a given set of quotes, scan time and RankingConfig the output is always identical.

Metrics
-------
price_change_pct   (price - previous_close) / previous_close * 100
movement_strength  |price_change_pct|  (gainers and losers both qualify)
relative_volume    morning:   previous_session_volume / avg_daily_volume   (basis "previous_session")
                   afternoon: session_volume / same_time_avg_volume       (basis "same_time_baseline")
                              or, if the provider has no same-time baseline,
                              session_volume / (avg_daily_volume * elapsed session fraction)
                              (basis "pro_rata_daily" - a cruder, flagged fallback)
volume_score       percentile rank of relative_volume within the category's eligible stocks, 0..1
movement_score     percentile rank of movement_strength within the category, 0..1
final_score        w_v * volume_score + w_m * movement_score   (weights normalised to sum to 1)

Why the morning scan uses the previous session: at 09:15 IST continuous trading has only just
begun, so accumulated intraday volume is ~0 and cannot be meaningfully ranked. The morning scan
therefore combines the opening move (open/latest vs previous close) with how unusual the
previous session's volume was. The actual intraday volume at scan time is still stored for
transparency, but it is not used for ranking.
"""

import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models.enums import CapCategory, ScanSession
from app.services.market_data.base import Quote

ALGORITHM_VERSION = "pctrank-v1"

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)
SESSION_MINUTES = 375
FUTURE_TOLERANCE = timedelta(seconds=60)
MAX_PLAUSIBLE_MOVE_PCT = 35.0  # NSE price bands top out at 20%; anything larger is treated as bad data

VOLUME_BASIS_LABELS = {
    "previous_session": "previous session vs 20-day average",
    "same_time_baseline": "today so far vs typical volume by this time",
    "pro_rata_daily": "today so far vs pro-rated daily average (fallback)",
}


@dataclass(frozen=True)
class RankingConfig:
    volume_weight: float = 0.5
    movement_weight: float = 0.5
    picks_per_category: int = 5
    max_staleness_seconds: int = 300
    min_avg_traded_value_inr: float = 5_000_000

    @property
    def weights(self) -> tuple[float, float]:
        total = self.volume_weight + self.movement_weight
        return self.volume_weight / total, self.movement_weight / total

    def as_dict(self) -> dict:
        return asdict(self) | {"algorithm_version": ALGORITHM_VERSION}


@dataclass(frozen=True)
class Candidate:
    symbol: str
    company_name: str
    cap_category: str
    quote: Quote | None


@dataclass(frozen=True)
class StockMetrics:
    symbol: str
    company_name: str
    cap_category: str
    price: float
    previous_close: float
    reference_price: float
    price_change_pct: float
    movement_strength: float
    intraday_volume: int | None
    relative_volume: float
    volume_basis: str
    data_timestamp: datetime
    inputs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ScoredStock:
    metrics: StockMetrics
    volume_score: float
    movement_score: float
    final_score: float
    rank: int
    eligible_in_category: int

    @property
    def selection_reason(self) -> str:
        m = self.metrics
        direction = "Up" if m.price_change_pct >= 0 else "Down"
        return (
            f"{direction} {abs(m.price_change_pct):.2f}% vs previous close; "
            f"relative volume {m.relative_volume:.2f}x ({VOLUME_BASIS_LABELS[m.volume_basis]}). "
            f"Volume score {self.volume_score:.2f}, movement score {self.movement_score:.2f} "
            f"among {self.eligible_in_category} eligible {m.cap_category} stocks."
        )


@dataclass
class RankingResult:
    picks: dict[str, list[ScoredStock]]
    eligible_counts: dict[str, int]
    exclusions: Counter
    excluded_symbols: dict[str, str]
    metrics_by_symbol: dict[str, StockMetrics]


def _finite_pos(x: float | int | None) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x) and x > 0


def _session_fraction(ts: datetime) -> float:
    local = ts.astimezone(IST)
    minutes = local.hour * 60 + local.minute + local.second / 60 - (SESSION_OPEN.hour * 60 + SESSION_OPEN.minute)
    return min(max(minutes / SESSION_MINUTES, 0.0), 1.0)


def evaluate(c: Candidate, session: ScanSession, scan_time: datetime, cfg: RankingConfig) -> StockMetrics | str:
    """Return metrics for an eligible stock, or a short exclusion reason. Never fills in missing data."""
    q = c.quote
    if q is None:
        return "no_quote"
    if q.is_suspended:
        return "suspended"
    if q.data_timestamp is None:
        return "missing_timestamp"
    if q.data_timestamp > scan_time + FUTURE_TOLERANCE:
        return "future_timestamp"
    if (scan_time - q.data_timestamp).total_seconds() > cfg.max_staleness_seconds:
        return "stale_price"
    if not _finite_pos(q.last_price):
        return "invalid_price"
    if not _finite_pos(q.previous_close):
        return "missing_previous_close"
    if q.unadjusted_corporate_action:
        return "unadjusted_corporate_action"
    if not _finite_pos(q.avg_daily_volume):
        return "missing_volume_baseline"
    if q.avg_daily_volume * q.previous_close < cfg.min_avg_traded_value_inr:
        return "illiquid"

    change = (q.last_price - q.previous_close) / q.previous_close * 100
    if abs(change) > MAX_PLAUSIBLE_MOVE_PCT:
        return "implausible_move"

    if session == ScanSession.MORNING:
        if q.previous_session_volume is None or q.previous_session_volume < 0:
            return "missing_volume"
        basis = "previous_session"
        rel_vol = q.previous_session_volume / q.avg_daily_volume
    else:
        if q.session_volume is None or q.session_volume < 0:
            return "missing_volume"
        if _finite_pos(q.same_time_avg_volume):
            basis = "same_time_baseline"
            rel_vol = q.session_volume / q.same_time_avg_volume
        else:
            frac = _session_fraction(q.data_timestamp)
            if frac <= 0:
                return "missing_volume_baseline"
            basis = "pro_rata_daily"
            rel_vol = q.session_volume / (q.avg_daily_volume * frac)

    return StockMetrics(
        symbol=c.symbol,
        company_name=c.company_name,
        cap_category=c.cap_category,
        price=q.last_price,
        previous_close=q.previous_close,
        reference_price=q.previous_close,
        price_change_pct=round(change, 4),
        movement_strength=round(abs(change), 4),
        intraday_volume=q.session_volume,
        relative_volume=round(rel_vol, 4),
        volume_basis=basis,
        data_timestamp=q.data_timestamp,
        inputs={
            "open_price": q.open_price,
            "session_volume": q.session_volume,
            "previous_session_volume": q.previous_session_volume,
            "avg_daily_volume": q.avg_daily_volume,
            "same_time_avg_volume": q.same_time_avg_volume,
            "provider_flags": dict(q.flags),
        },
    )


def percentile_ranks(values: list[float]) -> list[float]:
    """Percentile rank in [0, 1]; ties share the average rank. A single value scores 1.0."""
    n = len(values)
    if n == 1:
        return [1.0]
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = avg / (n - 1)
        i = j + 1
    return ranks


def score_category(metrics: list[StockMetrics], cfg: RankingConfig) -> list[ScoredStock]:
    """Score and fully order one category. Tie-breaks: movement, relative volume, then symbol."""
    if not metrics:
        return []
    wv, wm = cfg.weights
    vs = percentile_ranks([m.relative_volume for m in metrics])
    ms = percentile_ranks([m.movement_strength for m in metrics])
    rows = []
    for m, v, mv in zip(metrics, vs, ms):
        rows.append((m, round(v, 6), round(mv, 6), round(wv * v + wm * mv, 6)))
    rows.sort(key=lambda r: (-r[3], -r[0].movement_strength, -r[0].relative_volume, r[0].symbol))
    n = len(rows)
    return [ScoredStock(m, v, mv, f, rank=i + 1, eligible_in_category=n) for i, (m, v, mv, f) in enumerate(rows)]


def rank_universe(
    candidates: list[Candidate], session: ScanSession, scan_time: datetime, cfg: RankingConfig
) -> RankingResult:
    by_cat: dict[str, list[StockMetrics]] = {c.value: [] for c in CapCategory}
    exclusions: Counter = Counter()
    excluded: dict[str, str] = {}
    metrics_by_symbol: dict[str, StockMetrics] = {}
    for c in sorted(candidates, key=lambda c: c.symbol):
        result = evaluate(c, session, scan_time, cfg)
        if isinstance(result, str):
            exclusions[result] += 1
            excluded[c.symbol] = result
            continue
        if c.cap_category not in by_cat:
            exclusions["unclassified"] += 1
            excluded[c.symbol] = "unclassified"
            continue
        by_cat[c.cap_category].append(result)
        metrics_by_symbol[c.symbol] = result

    picks = {cat: score_category(ms, cfg)[: cfg.picks_per_category] for cat, ms in by_cat.items()}
    return RankingResult(
        picks=picks,
        eligible_counts={cat: len(ms) for cat, ms in by_cat.items()},
        exclusions=exclusions,
        excluded_symbols=excluded,
        metrics_by_symbol=metrics_by_symbol,
    )

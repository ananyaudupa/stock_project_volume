import random
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.models import ScanSession
from app.services.market_data.base import Quote
from app.services.ranking import (
    Candidate,
    RankingConfig,
    evaluate,
    percentile_ranks,
    rank_universe,
    score_category,
)
from tests.conftest import IST

AFTERNOON = datetime(2026, 10, 16, 15, 0, tzinfo=IST)
MORNING = datetime(2026, 10, 16, 9, 15, tzinfo=IST)
CFG = RankingConfig()


def quote(sym="AAA", **kw) -> Quote:
    base = dict(
        symbol=sym, data_timestamp=AFTERNOON, last_price=105.0, open_price=101.0, previous_close=100.0,
        session_volume=2_000_000, previous_session_volume=1_500_000, avg_daily_volume=1_000_000.0,
        same_time_avg_volume=900_000.0,
    )
    return Quote(**(base | kw))


def cand(q: Quote | None, cat="mid-cap", sym=None) -> Candidate:
    return Candidate(sym or (q.symbol if q else "NONE"), "Co", cat, q)


def test_percentile_ranks_with_ties():
    assert percentile_ranks([5.0]) == [1.0]
    assert percentile_ranks([1, 2, 3]) == [0.0, 0.5, 1.0]
    assert percentile_ranks([1, 2, 2, 3]) == [0.0, 0.5, 0.5, 1.0]


def test_afternoon_metrics_use_same_time_baseline():
    m = evaluate(cand(quote()), ScanSession.AFTERNOON, AFTERNOON, CFG)
    assert m.price_change_pct == 5.0
    assert m.movement_strength == 5.0
    assert m.volume_basis == "same_time_baseline"
    assert m.relative_volume == round(2_000_000 / 900_000, 4)


def test_afternoon_falls_back_to_pro_rata_when_no_same_time_baseline():
    m = evaluate(cand(quote(same_time_avg_volume=None)), ScanSession.AFTERNOON, AFTERNOON, CFG)
    assert m.volume_basis == "pro_rata_daily"
    elapsed = (15 * 60 - (9 * 60 + 15)) / 375
    assert m.relative_volume == pytest.approx(2_000_000 / (1_000_000 * elapsed), rel=1e-4)


def test_morning_uses_previous_session_volume_not_opening_volume():
    q = quote(data_timestamp=MORNING, session_volume=0, same_time_avg_volume=None)
    m = evaluate(cand(q), ScanSession.MORNING, MORNING, CFG)
    assert m.volume_basis == "previous_session"
    assert m.relative_volume == 1.5
    assert m.intraday_volume == 0  # stored for transparency, not used for ranking


@pytest.mark.parametrize(
    "overrides,reason",
    [
        (dict(is_suspended=True), "suspended"),
        (dict(data_timestamp=None), "missing_timestamp"),
        (dict(data_timestamp=AFTERNOON - timedelta(minutes=10)), "stale_price"),
        (dict(data_timestamp=AFTERNOON + timedelta(minutes=5)), "future_timestamp"),
        (dict(last_price=None), "invalid_price"),
        (dict(last_price=0.0), "invalid_price"),
        (dict(last_price=float("nan")), "invalid_price"),
        (dict(previous_close=None), "missing_previous_close"),
        (dict(unadjusted_corporate_action=True), "unadjusted_corporate_action"),
        (dict(avg_daily_volume=None), "missing_volume_baseline"),
        (dict(avg_daily_volume=1000.0), "illiquid"),
        (dict(last_price=150.0), "implausible_move"),
        (dict(session_volume=None), "missing_volume"),
    ],
)
def test_exclusions_never_invent_data(overrides, reason):
    assert evaluate(cand(quote(**overrides)), ScanSession.AFTERNOON, AFTERNOON, CFG) == reason


def test_missing_quote_excluded():
    assert evaluate(cand(None), ScanSession.AFTERNOON, AFTERNOON, CFG) == "no_quote"


def _universe(n=30, cat="mid-cap"):
    r = random.Random(7)
    return [
        cand(quote(f"S{i:03d}", last_price=round(100 * (1 + r.uniform(-0.08, 0.08)), 2),
                   session_volume=int(r.uniform(2e5, 4e6))), cat)
        for i in range(n)
    ]


def test_ranking_is_deterministic_regardless_of_input_order():
    cands = _universe()
    a = rank_universe(cands, ScanSession.AFTERNOON, AFTERNOON, CFG)
    shuffled = cands[:]
    random.Random(1).shuffle(shuffled)
    b = rank_universe(shuffled, ScanSession.AFTERNOON, AFTERNOON, CFG)
    assert [(p.metrics.symbol, p.final_score) for p in a.picks["mid-cap"]] == [
        (p.metrics.symbol, p.final_score) for p in b.picks["mid-cap"]
    ]
    assert len(a.picks["mid-cap"]) == 5
    assert a.picks["large-cap"] == [] and a.eligible_counts["large-cap"] == 0
    assert [p.rank for p in a.picks["mid-cap"]] == [1, 2, 3, 4, 5]


def test_final_score_is_weighted_combination():
    cfg = RankingConfig(volume_weight=3, movement_weight=1)
    for p in score_category([m for c in _universe() if not isinstance(m := evaluate(c, ScanSession.AFTERNOON, AFTERNOON, cfg), str)], cfg):
        assert p.final_score == pytest.approx(0.75 * p.volume_score + 0.25 * p.movement_score, abs=1e-6)


def test_losers_qualify_alongside_gainers():
    cands = [
        cand(quote("UP", last_price=106.0, session_volume=3_000_000)),
        cand(quote("DOWN", last_price=93.0, session_volume=3_100_000)),
        cand(quote("FLAT", last_price=100.1, session_volume=500_000)),
    ]
    res = rank_universe(cands, ScanSession.AFTERNOON, AFTERNOON, CFG)
    top = [p.metrics.symbol for p in res.picks["mid-cap"]]
    assert top[0] == "DOWN"
    assert res.picks["mid-cap"][0].selection_reason.startswith("Down 7.00%")


def test_ties_break_by_symbol():
    cands = [cand(quote(s)) for s in ("CCC", "AAA", "BBB")]
    res = rank_universe(cands, ScanSession.AFTERNOON, AFTERNOON, CFG)
    assert [p.metrics.symbol for p in res.picks["mid-cap"]] == ["AAA", "BBB", "CCC"]


def test_exclusion_counts_and_unclassified():
    cands = [cand(quote("OK")), cand(quote("SUS", is_suspended=True)), cand(quote("X"), cat="micro")]
    res = rank_universe(cands, ScanSession.AFTERNOON, AFTERNOON, CFG)
    assert res.exclusions == {"suspended": 1, "unclassified": 1}
    assert res.eligible_counts["mid-cap"] == 1


def test_weights_must_not_both_be_zero():
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings(_env_file=None, volume_score_weight=0, movement_score_weight=0)
    assert RankingConfig(volume_weight=2, movement_weight=2).weights == (0.5, 0.5)
    assert replace(CFG, picks_per_category=3).picks_per_category == 3

from datetime import datetime, timedelta, timezone

import pandas as pd

from build_data import _ex_div_date, build_queue


def _ts(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M")


def test_queue_orders_new_then_stalest_and_skips_fresh():
    universe = pd.DataFrame({"ticker": ["NEW", "OLD", "OLDER", "FRESH"], "type": "Stock"})
    cache = pd.DataFrame({"ticker": ["OLD", "OLDER", "FRESH"], "fetched_at": [_ts(30), _ts(80), _ts(2)]})
    q = build_queue(universe, cache, max_age_hours=20)
    assert list(q["ticker"]) == ["NEW", "OLDER", "OLD"]


def test_queue_max_age_zero_refetches_everything():
    universe = pd.DataFrame({"ticker": ["A", "B"], "type": "ETF"})
    cache = pd.DataFrame({"ticker": ["A"], "fetched_at": [_ts(1)]})
    assert set(build_queue(universe, cache, max_age_hours=0)["ticker"]) == {"A", "B"}


def test_ex_div_prefers_newer_announced_date_and_ignores_stale_ones():
    upcoming = pd.Timestamp.now() + pd.Timedelta(days=10)
    assert _ex_div_date({"ex_div_ts": upcoming.timestamp(), "last_ex_div": "2026-01-05"}) == upcoming.strftime("%Y-%m-%d")
    stale = pd.Timestamp("1990-01-31").timestamp()
    assert _ex_div_date({"ex_div_ts": stale, "last_ex_div": float("nan")}) is None
    assert _ex_div_date({"ex_div_ts": None, "last_ex_div": "2026-06-01"}) == "2026-06-01"

import logging

import pandas as pd
import pytest

import live

logging.getLogger("streamlit").setLevel(logging.ERROR)


@pytest.fixture(autouse=True)
def fresh():
    live.clear_cache()
    yield
    live.clear_cache()


def quote(sym, price=10.0, prev=9.0, state="CLOSED", **kw):
    return {"symbol": sym, "regularMarketPrice": price, "regularMarketPreviousClose": prev,
            "regularMarketChangePercent": 1.0, "regularMarketTime": 1790366400, "marketState": state, **kw}


def test_success_returns_quotes(monkeypatch):
    monkeypatch.setattr(live, "_fetch_batch", lambda syms: [quote(s) for s in syms])
    q, as_of = live.fetch_quotes(("AAA", "BBB"))
    assert list(q["ticker"]) == ["AAA", "BBB"] and as_of is not None


def test_rate_limit_raises_and_backs_off(monkeypatch):
    calls = []
    monkeypatch.setattr(live, "_fetch_batch", lambda syms: calls.append(1))  # returns None = rate limited
    with pytest.raises(live.QuotesUnavailable):
        live.fetch_quotes(("AAA",))
    with pytest.raises(live.QuotesUnavailable):
        live.fetch_quotes(("AAA",))  # within the back-off window: no new request
    assert len(calls) == 1


def test_apply_uses_previous_close_while_market_open():
    df = pd.DataFrame({"ticker": ["AAA"], "last_close": [5.0], "market_cap": [1e9], "div_per_share": [0.5],
                       "rating_score": [2.0], "rating_key": ["buy"], "target_mean": [12.0],
                       "pe": [10.0], "forward_pe": [9.0], "pb": [1.0], "high_52w": [11.0], "low_52w": [4.0]})
    q = pd.DataFrame([quote("AAA", price=10.5, prev=10.0, state="REGULAR", averageAnalystRating="1.4 - Strong Buy",
                            dividendRate=1.0, marketCap=2e9)]).rename(columns={"symbol": "ticker"})
    out = live.apply_quotes(df, q, is_stock=True).iloc[0]
    assert out["last_close"] == 10.0 and out["price"] == 10.5
    assert out["upside"] == pytest.approx(0.2)
    assert out["dividend_yield"] == pytest.approx(0.1)
    assert out["rating_key"] == "strong_buy"

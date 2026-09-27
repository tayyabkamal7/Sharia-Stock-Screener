import numpy as np
import pandas as pd
import pytest

from peers import add_derived, comparison_table, implied_prices, peer_group, percentile_rank, premium


@pytest.fixture
def stocks():
    df = pd.DataFrame({
        "ticker": ["ME", "A", "B", "C", "D", "OTHER"],
        "industry": ["Chips"] * 5 + ["Banks"],
        "sector": ["Tech"] * 5 + ["Fin"],
        "market_cap": [100e9, 90e9, 110e9, 1e9, 500e9, 100e9],
        "status": ["Compliant", "Compliant", "Non-Compliant", "Compliant", "Compliant", "Non-Compliant"],
        "pe": [20.0, 10.0, 30.0, -5.0, 40.0, 8.0],
        "ps": [5.0, 4.0, 6.0, 2.0, 8.0, 2.0],
        "roe": [0.2, 0.1, 0.3, -0.1, 0.25, 0.12],
        "fcf": [5e9, 1e9, 2e9, 0.1e9, 20e9, 1e9],
    })
    return add_derived(df)


def test_peer_group_excludes_self_and_other_industries(stocks):
    p = peer_group(stocks, "ME")
    assert set(p["ticker"]) == {"A", "B", "C", "D"}


def test_peer_group_closest_by_market_cap(stocks):
    assert set(peer_group(stocks, "ME", n=2)["ticker"]) == {"A", "B"}


def test_peer_group_compliant_only(stocks):
    assert "B" not in set(peer_group(stocks, "ME", compliant_only=True)["ticker"])


def test_unknown_ticker_gives_empty_group(stocks):
    assert peer_group(stocks, "NOPE").empty


def test_comparison_ignores_negative_multiples(stocks):
    me = stocks.iloc[0].to_dict()
    peers = peer_group(stocks, "ME")
    t = comparison_table(me, peers, peers, peers, ["pe", "roe"]).set_index("key")
    assert t.loc["pe", "Peer median"] == pytest.approx(30.0)  # -5 dropped: median of 10, 30, 40
    assert t.loc["pe", "vs peers"] == pytest.approx(20 / 30 - 1)
    assert t.loc["roe", "Percentile"] == pytest.approx(50.0)  # beats A and C, not B or D


def test_derived_yields(stocks):
    assert stocks.loc[0, "fcf_yield"] == pytest.approx(0.05)
    assert np.isnan(stocks.loc[3, "earnings_yield"])  # negative P/E


def test_percentile_and_premium_edge_cases():
    assert np.isnan(percentile_rank(None, pd.Series([1, 2])))
    assert np.isnan(premium(5, 0))


def test_implied_prices(stocks):
    peers = peer_group(stocks, "ME")
    fund = {"eps": 2.0, "revenue": 50e9, "shares": 1e9, "total_debt": 0, "total_cash": 0}
    ip = implied_prices(fund, peers).set_index("Method")
    assert ip.loc["P/E (TTM)", "Median"] == pytest.approx(60.0)   # 30x * $2
    assert ip.loc["Price / sales", "Median"] == pytest.approx(250.0)  # median P/S 5 * $50 revenue/share
    assert "Forward P/E" not in ip.index  # no forward EPS given


def test_implied_prices_needs_shares(stocks):
    assert implied_prices({"eps": 1}, stocks).empty

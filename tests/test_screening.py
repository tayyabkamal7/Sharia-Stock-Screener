import json

import pytest

from screening import COMPLIANT, NON_COMPLIANT, QUESTIONABLE, screen_etf, screen_stock

B = 1e9


# ---------------- stocks ----------------
def test_clean_company_is_compliant():
    r = screen_stock("AAPL", "Consumer Electronics", total_debt=10 * B, total_cash=5 * B, market_cap=1000 * B)
    assert r["status"] == COMPLIANT
    assert r["debt_ratio"] == pytest.approx(0.01)
    assert r["reason"] == "Passes business and financial ratio tests"


@pytest.mark.parametrize("industry", ["Banks - Regional", "Insurance - Life", "Tobacco", "Resorts & Casinos",
                                      "Beverages - Brewers", "REIT - Mortgage"])
def test_prohibited_industries_fail(industry):
    r = screen_stock("X", industry, total_debt=0, total_cash=0, market_cap=10 * B)
    assert r["status"] == NON_COMPLIANT
    assert r["business_status"] == NON_COMPLIANT


def test_debt_at_limit_fails_with_reason():
    r = screen_stock("X", "Software - Application", total_debt=30 * B, total_cash=0, market_cap=100 * B)
    assert r["status"] == NON_COMPLIANT
    assert "Debt is 30% of market cap" in r["reason"]


def test_debt_just_under_limit_passes():
    r = screen_stock("X", "Software - Application", total_debt=29.9 * B, total_cash=0, market_cap=100 * B)
    assert r["status"] == COMPLIANT


def test_cash_over_limit_fails():
    r = screen_stock("X", "Biotechnology", total_debt=0, total_cash=45 * B, market_cap=100 * B)
    assert r["status"] == NON_COMPLIANT
    assert "Cash and securities are 45%" in r["reason"]


def test_multiple_failures_are_all_listed():
    r = screen_stock("X", "Banks - Diversified", total_debt=50 * B, total_cash=40 * B, market_cap=100 * B)
    assert r["reason"].count(";") == 2


def test_doubtful_industry_is_questionable():
    r = screen_stock("X", "Aerospace & Defense", total_debt=1 * B, total_cash=1 * B, market_cap=100 * B)
    assert r["status"] == QUESTIONABLE


def test_missing_market_cap_is_questionable_not_compliant():
    r = screen_stock("X", "Semiconductors", total_debt=1 * B, total_cash=1 * B, market_cap=None)
    assert r["status"] == QUESTIONABLE
    assert "unavailable" in r["reason"]


def test_missing_debt_counts_as_zero():
    r = screen_stock("X", "Semiconductors", total_debt=None, total_cash=float("nan"), market_cap=10 * B)
    assert r["status"] == COMPLIANT


def test_unknown_industry_is_questionable():
    assert screen_stock("X", None, 0, 0, 10 * B)["status"] == QUESTIONABLE


def test_ticker_override():
    assert screen_stock("HRL", "Packaged Foods", 0, 0, 10 * B)["status"] == NON_COMPLIANT


def test_payment_networks_are_questionable_not_lenders():
    r = screen_stock("V", "Credit Services", 1 * B, 1 * B, 500 * B)
    assert r["status"] == QUESTIONABLE and "Payment network" in r["reason"]
    assert screen_stock("COF", "Credit Services", 1 * B, 1 * B, 500 * B)["status"] == NON_COMPLIANT


# ---------------- ETFs ----------------
def etf(name="Some Equity ETF", family="Vanguard", category="Large Blend", holdings=None, fin=0.0, statuses=None):
    return screen_etf(name, family, category, json.dumps(holdings) if holdings is not None else None, fin,
                      statuses or {})


def test_shariah_fund_is_compliant():
    assert etf(name="SP Funds S&P 500 Sharia Industry Exclusions ETF", family="SP Funds")["status"] == COMPLIANT
    assert etf(name="Wahed FTSE USA Shariah ETF", family="Wahed")["status"] == COMPLIANT


@pytest.mark.parametrize("category", ["Intermediate Core Bond", "Long Government", "Money Market-Taxable",
                                      "Trading--Leveraged Equity", "Derivative Income", "Defined Outcome"])
def test_bond_leveraged_options_funds_fail(category):
    assert etf(category=category)["status"] == NON_COMPLIANT


def test_financials_exposure_fails():
    r = etf(fin=0.12, holdings=[["AAPL", 0.1]])
    assert r["status"] == NON_COMPLIANT
    assert "12%" in r["reason"]


def test_noncompliant_holdings_fail():
    r = etf(holdings=[["JPM", 0.04], ["BAC", 0.03], ["AAPL", 0.1]],
            statuses={"JPM": NON_COMPLIANT, "BAC": NON_COMPLIANT, "AAPL": COMPLIANT})
    assert r["status"] == NON_COMPLIANT
    assert "JPM" in r["reason"] and r["noncompliant_weight"] == pytest.approx(0.07)


def test_clean_conventional_fund_is_questionable():
    r = etf(holdings=[["AAPL", 0.1], ["MSFT", 0.1]], statuses={"AAPL": COMPLIANT, "MSFT": COMPLIANT})
    assert r["status"] == QUESTIONABLE


def test_class_share_symbols_match():
    r = etf(holdings=[["BRK.B", 0.2]], statuses={"BRK-B": NON_COMPLIANT})
    assert r["status"] == NON_COMPLIANT

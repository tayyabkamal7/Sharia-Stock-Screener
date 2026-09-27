import numpy as np
import pandas as pd
import pytest

from ratios import compute_ratios, format_value

P = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]


def stmt(rows):
    return pd.DataFrame(rows, index=P).T


@pytest.fixture
def statements():
    inc = stmt({"Total Revenue": [1000, 800], "Cost Of Revenue": [600, 500], "Gross Profit": [400, 300],
                "Operating Income": [200, 150], "EBIT": [200, 150], "EBITDA": [250, 190], "Net Income": [150, 100],
                "Pretax Income": [190, 130], "Tax Provision": [40, 30], "Interest Expense": [10, 10],
                "Interest Income": [20, 10], "Diluted EPS": [1.5, 1.0], "Diluted Average Shares": [100, 100]})
    bal = stmt({"Total Assets": [2000, 1800], "Current Assets": [800, 700], "Current Liabilities": [400, 400],
                "Stockholders Equity": [1000, 900], "Total Debt": [300, 350], "Cash And Cash Equivalents": [200, 150],
                "Cash Cash Equivalents And Short Term Investments": [250, 200], "Inventory": [100, 90],
                "Accounts Receivable": [120, 100], "Accounts Payable": [90, 80], "Invested Capital": [1300, 1250],
                "Ordinary Shares Number": [100, 100], "Total Liabilities Net Minority Interest": [1000, 900]})
    cf = stmt({"Operating Cash Flow": [220, 170], "Capital Expenditure": [-50, -40], "Free Cash Flow": [170, 130],
               "Cash Dividends Paid": [-30, -20]})
    prices = pd.Series([20.0, 30.0], index=[pd.Timestamp("2024-12-31"), pd.Timestamp("2025-12-31")])
    return inc, bal, cf, prices


def test_core_ratios(statements):
    inc, bal, cf, prices = statements
    t, meta = compute_ratios(inc, bal, cf, prices)
    latest = t[P[0]]
    assert latest["Gross margin"] == pytest.approx(0.4)
    assert latest["Net margin"] == pytest.approx(0.15)
    assert latest["Return on equity (ROE)"] == pytest.approx(0.15)
    assert latest["Current ratio"] == pytest.approx(2.0)
    assert latest["Quick ratio"] == pytest.approx(1.75)
    assert latest["Debt to equity"] == pytest.approx(0.3)
    assert latest["Interest coverage (EBIT / interest)"] == pytest.approx(20)
    assert latest["Revenue growth YoY"] == pytest.approx(0.25)
    assert latest["Dividend payout ratio"] == pytest.approx(0.2)
    assert meta["Gross margin"] == ("Profitability", "pct")


def test_shariah_and_valuation_use_period_end_market_cap(statements):
    inc, bal, cf, prices = statements
    t, _ = compute_ratios(inc, bal, cf, prices)
    latest = t[P[0]]  # market cap = 30 * 100 = 3000
    assert latest["Market cap (period end)"] == pytest.approx(3000)
    assert latest["Debt / market cap (AAOIFI < 30%)"] == pytest.approx(0.1)
    assert latest["Interest income / revenue (limit 5%)"] == pytest.approx(0.02)
    assert latest["Price to earnings (P/E)"] == pytest.approx(20)


def test_quarterly_annualizes_flow_ratios(statements):
    inc, bal, cf, prices = statements
    t, _ = compute_ratios(inc, bal, cf, prices, quarterly=True)
    assert t[P[0]]["Return on equity (ROE)"] == pytest.approx(0.6)


def test_missing_lines_are_dropped_not_errors():
    inc = stmt({"Total Revenue": [100, 90], "Net Income": [10, 9]})
    t, meta = compute_ratios(inc, pd.DataFrame(), pd.DataFrame())
    assert "Net margin" in t.index
    assert "Current ratio" not in t.index  # needs a balance sheet
    assert set(meta) == set(t.index)


@pytest.mark.parametrize("v,kind,out", [(0.1234, "pct", "12.3%"), (2.5, "x", "2.50x"), (1.5, "usd", "$1.50"),
                                        (45.4, "days", "45 days"), (2.5e9, "big", "$2.50B"),
                                        (-3e6, "big", "-$3.00M"), (np.nan, "pct", "—")])
def test_format_value(v, kind, out):
    assert format_value(v, kind) == out

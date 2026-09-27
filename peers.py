"""Peer selection and relative valuation (pure functions, no Streamlit)."""

import numpy as np
import pandas as pd

# key -> (label, kind, group, better)   kind: pct | x | num | usd | big;  better: "low" | "high" | None
METRICS = {
    "pe": ("P/E (TTM)", "x", "Valuation", "low"),
    "forward_pe": ("Forward P/E", "x", "Valuation", "low"),
    "peg": ("PEG ratio", "x", "Valuation", "low"),
    "ps": ("Price / sales", "x", "Valuation", "low"),
    "pb": ("Price / book", "x", "Valuation", "low"),
    "ev_ebitda": ("EV / EBITDA", "x", "Valuation", "low"),
    "ev_revenue": ("EV / revenue", "x", "Valuation", "low"),
    "fcf_yield": ("Free cash flow yield", "pct", "Valuation", "high"),
    "earnings_yield": ("Earnings yield", "pct", "Valuation", "high"),
    "gross_margin": ("Gross margin", "pct", "Profitability", "high"),
    "operating_margin": ("Operating margin", "pct", "Profitability", "high"),
    "ebitda_margin": ("EBITDA margin", "pct", "Profitability", "high"),
    "net_margin": ("Net margin", "pct", "Profitability", "high"),
    "roe": ("Return on equity", "pct", "Profitability", "high"),
    "roa": ("Return on assets", "pct", "Profitability", "high"),
    "revenue_growth": ("Revenue growth (YoY)", "pct", "Growth", "high"),
    "earnings_growth": ("Earnings growth (YoY)", "pct", "Growth", "high"),
    "earnings_q_growth": ("Quarterly earnings growth", "pct", "Growth", "high"),
    "return_1y": ("1-year share price return", "pct", "Growth", "high"),
    "current_ratio": ("Current ratio", "x", "Financial health", "high"),
    "quick_ratio": ("Quick ratio", "x", "Financial health", "high"),
    "debt_to_equity": ("Debt / equity", "x", "Financial health", "low"),
    "beta": ("Beta", "num", "Financial health", None),
    "dividend_yield": ("Dividend yield", "pct", "Dividends", "high"),
    "payout_ratio": ("Payout ratio", "pct", "Dividends", None),
    "div_yield_5y": ("5-year average dividend yield", "pct", "Dividends", "high"),
    "upside": ("Analyst upside", "pct", "Analysts", "high"),
    "rating_score": ("Rating score (1 = Strong Buy)", "num", "Analysts", "low"),
    "num_analysts": ("Number of analysts", "num", "Analysts", None),
    "debt_ratio": ("Debt / market cap (AAOIFI)", "pct", "Shariah", "low"),
    "cash_ratio": ("Cash / market cap (AAOIFI)", "pct", "Shariah", "low"),
    "market_cap": ("Market cap", "big", "Size", None),
    "revenue": ("Revenue (TTM)", "big", "Size", None),
    "employees": ("Employees", "num", "Size", None),
}
GROUPS = ["Valuation", "Profitability", "Growth", "Financial health", "Dividends", "Analysts", "Shariah", "Size"]
MULTIPLES = {"pe", "forward_pe", "peg", "ps", "pb", "ev_ebitda", "ev_revenue"}


def add_derived(stocks):
    """Columns derived from the dataset that the peer comparison needs."""
    df = stocks.copy()
    for c in ("fcf", "ev_revenue", "ebitda_margin", "quick_ratio", "earnings_q_growth", "employees",
              "div_yield_5y", "eps", "forward_eps", "bvps", "ebitda", "enterprise_value"):
        if c not in df:
            df[c] = np.nan
    df["fcf_yield"] = df["fcf"] / df["market_cap"]
    df["earnings_yield"] = 1 / df["pe"].where(df["pe"] > 0)
    return df


def clean(series, key):
    """Negative or absurd valuation multiples are meaningless for comparison."""
    s = pd.to_numeric(series, errors="coerce")
    if key in MULTIPLES:
        s = s.where((s > 0) & (s < 1000))
    return s


def peer_group(stocks, ticker, by="industry", n=15, compliant_only=False):
    """Closest companies by market cap within the same industry (or sector), excluding `ticker`."""
    me = stocks[stocks["ticker"] == ticker]
    if me.empty or pd.isna(me.iloc[0].get(by)):
        return stocks.iloc[0:0]
    me = me.iloc[0]
    pool = stocks[(stocks[by] == me[by]) & (stocks["ticker"] != ticker) & (stocks["market_cap"] > 0)]
    if compliant_only:
        pool = pool[pool["status"] == "Compliant"]
    if n and len(pool) > n and me.get("market_cap", 0) and me["market_cap"] > 0:
        dist = (np.log(pool["market_cap"]) - np.log(me["market_cap"])).abs()
        pool = pool.loc[dist.nsmallest(n).index]
    return pool.sort_values("market_cap", ascending=False)


def group_medians(df, keys):
    return pd.Series({k: clean(df[k], k).median() if k in df else np.nan for k in keys})


def percentile_rank(value, series):
    """Share of peers (0-100) with a lower value than `value`."""
    s = series.dropna()
    if value is None or pd.isna(value) or s.empty:
        return np.nan
    return float((s < value).mean() * 100)


def premium(value, median):
    if value is None or median is None or pd.isna(value) or pd.isna(median) or median == 0:
        return np.nan
    return value / median - 1


def comparison_table(company, peers, industry, sector, keys):
    """One row per metric: company value, medians, premium/discount and percentile vs peers."""
    rows = []
    for k in keys:
        label, kind, group, better = METRICS[k]
        v = clean(pd.Series([company.get(k)]), k).iloc[0]
        peer_vals = clean(peers[k], k) if k in peers else pd.Series(dtype=float)
        rows.append({
            "key": k, "Metric": label, "kind": kind, "better": better,
            "Company": v,
            "Peer median": peer_vals.median(),
            "Industry median": clean(industry[k], k).median() if k in industry else np.nan,
            "Sector median": clean(sector[k], k).median() if k in sector else np.nan,
            "vs peers": premium(v, peer_vals.median()),
            "Percentile": percentile_rank(v, peer_vals),
        })
    return pd.DataFrame(rows)


def implied_prices(fund, peers):
    """Share prices implied by applying peer multiples (25th/50th/75th percentile) to the company.

    fund: dict with eps, forward_eps, revenue, bvps, ebitda, total_debt, total_cash, shares.
    """
    shares = fund.get("shares")
    if not shares or shares <= 0:
        return pd.DataFrame()
    debt = fund.get("total_debt") or 0
    cash = fund.get("total_cash") or 0

    def per_share(base, positive=True):
        return None if base is None or pd.isna(base) or (positive and base <= 0) else base

    methods = [
        ("P/E (TTM)", "pe", per_share(fund.get("eps")), lambda m, b: m * b),
        ("Forward P/E", "forward_pe", per_share(fund.get("forward_eps")), lambda m, b: m * b),
        ("Price / sales", "ps", per_share((fund.get("revenue") or np.nan) / shares), lambda m, b: m * b),
        ("Price / book", "pb", per_share(fund.get("bvps")), lambda m, b: m * b),
        ("EV / EBITDA", "ev_ebitda", per_share(fund.get("ebitda")), lambda m, b: (m * b - debt + cash) / shares),
        ("EV / revenue", "ev_revenue", per_share(fund.get("revenue")), lambda m, b: (m * b - debt + cash) / shares),
    ]
    out = []
    for label, key, base, fn in methods:
        if base is None or key not in peers:
            continue
        mult = clean(peers[key], key).dropna()
        if len(mult) < 3:
            continue
        q = mult.quantile([0.25, 0.5, 0.75])
        vals = [max(fn(m, base), 0) for m in q]
        out.append({"Method": label, "Low (25th pct)": vals[0], "Median": vals[1], "High (75th pct)": vals[2],
                    "Peer multiple (median)": q[0.5], "Peers used": len(mult)})
    return pd.DataFrame(out)

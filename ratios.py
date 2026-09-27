"""Financial ratio engine: turns Yahoo Finance statements into ~50 ratios per reporting period."""

import numpy as np
import pandas as pd

# ratio kinds drive formatting: pct, x (multiple), usd (per share), days, big (absolute dollars)
CATEGORIES = [
    "Profitability", "Liquidity", "Leverage", "Efficiency", "Cash flow",
    "Per share", "Growth", "Valuation", "Shariah",
]


def _row(df, *names):
    """First matching statement line as a Series over the statement's periods (NaN if missing)."""
    if df is None or df.empty:
        return pd.Series(dtype=float)
    for n in names:
        if n in df.index:
            return pd.to_numeric(df.loc[n], errors="coerce")
    return pd.Series(np.nan, index=df.columns, dtype=float)


def _div(a, b):
    b = b.replace(0, np.nan)
    return a / b


def compute_ratios(inc, bal, cf, prices=None, quarterly=False):
    """Return (DataFrame ratios x periods, dict ratio -> (category, kind)).

    prices: Series of daily closes, used for period-end market cap and valuation ratios.
    For quarterly data, flow-based return and turnover ratios are annualized (x4).
    """
    periods = sorted(set(inc.columns) | set(bal.columns) | set(cf.columns), reverse=True)
    inc, bal, cf = (d.reindex(columns=periods) if d is not None and not d.empty
                    else pd.DataFrame(columns=periods) for d in (inc, bal, cf))
    ann = 4 if quarterly else 1

    rev = _row(inc, "Total Revenue", "Operating Revenue")
    cogs = _row(inc, "Cost Of Revenue", "Reconciled Cost Of Revenue")
    gp = _row(inc, "Gross Profit")
    op = _row(inc, "Operating Income", "Total Operating Income As Reported")
    ebit = _row(inc, "EBIT", "Operating Income")
    ebitda = _row(inc, "EBITDA", "Normalized EBITDA")
    ni = _row(inc, "Net Income Common Stockholders", "Net Income")
    pretax = _row(inc, "Pretax Income")
    tax = _row(inc, "Tax Provision")
    int_exp = _row(inc, "Interest Expense", "Interest Expense Non Operating")
    int_inc = _row(inc, "Interest Income", "Interest Income Non Operating")
    eps = _row(inc, "Diluted EPS", "Basic EPS")
    dil_shares = _row(inc, "Diluted Average Shares", "Basic Average Shares")

    assets = _row(bal, "Total Assets")
    ca = _row(bal, "Current Assets")
    cl = _row(bal, "Current Liabilities")
    liab = _row(bal, "Total Liabilities Net Minority Interest")
    equity = _row(bal, "Stockholders Equity", "Common Stock Equity")
    debt = _row(bal, "Total Debt")
    net_debt = _row(bal, "Net Debt")
    cash = _row(bal, "Cash And Cash Equivalents")
    cash_sti = _row(bal, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")
    inv = _row(bal, "Inventory").fillna(0)
    recv = _row(bal, "Accounts Receivable", "Receivables")
    payables = _row(bal, "Accounts Payable", "Payables")
    invested = _row(bal, "Invested Capital")
    shares = _row(bal, "Ordinary Shares Number", "Share Issued").fillna(dil_shares)

    ocf = _row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    capex = _row(cf, "Capital Expenditure").abs()
    fcf = _row(cf, "Free Cash Flow").fillna(ocf - capex)
    divs_paid = _row(cf, "Cash Dividends Paid", "Common Stock Dividend Paid").abs()
    buybacks = _row(cf, "Repurchase Of Capital Stock").abs()

    if net_debt.isna().all():
        net_debt = debt - cash
    tax_rate = _div(tax, pretax).clip(0, 0.5)

    # period-end market cap from price history
    mcap = pd.Series(np.nan, index=periods)
    if prices is not None and len(prices):
        p = prices.copy()
        p.index = pd.to_datetime(p.index).tz_localize(None)
        for d in periods:
            s = p[p.index <= pd.Timestamp(d)]
            if len(s) and (pd.Timestamp(d) - s.index[-1]).days < 10:
                mcap[d] = s.iloc[-1] * shares.get(d, np.nan)
    ev = mcap + debt - cash_sti

    def yoy(s):
        lag = 4 if quarterly else 1
        prev = s.shift(-lag)  # columns are newest first
        return (s - prev) / prev.abs().replace(0, np.nan)

    R = {}

    def add(cat, name, kind, series):
        R[name] = (cat, kind, series)

    add("Profitability", "Gross margin", "pct", _div(gp, rev))
    add("Profitability", "Operating margin", "pct", _div(op, rev))
    add("Profitability", "EBITDA margin", "pct", _div(ebitda, rev))
    add("Profitability", "Pre-tax margin", "pct", _div(pretax, rev))
    add("Profitability", "Net margin", "pct", _div(ni, rev))
    add("Profitability", "Return on equity (ROE)", "pct", _div(ni * ann, equity))
    add("Profitability", "Return on assets (ROA)", "pct", _div(ni * ann, assets))
    add("Profitability", "Return on invested capital (ROIC)", "pct", _div(ebit * (1 - tax_rate) * ann, invested))
    add("Profitability", "Effective tax rate", "pct", tax_rate)

    add("Liquidity", "Current ratio", "x", _div(ca, cl))
    add("Liquidity", "Quick ratio", "x", _div(ca - inv, cl))
    add("Liquidity", "Cash ratio", "x", _div(cash_sti, cl))
    add("Liquidity", "Working capital", "big", ca - cl)
    add("Liquidity", "Operating cash flow ratio", "x", _div(ocf, cl))

    add("Leverage", "Debt to equity", "x", _div(debt, equity))
    add("Leverage", "Debt to assets", "pct", _div(debt, assets))
    add("Leverage", "Liabilities to assets", "pct", _div(liab, assets))
    add("Leverage", "Equity multiplier", "x", _div(assets, equity))
    add("Leverage", "Debt to EBITDA", "x", _div(debt, ebitda * ann))
    add("Leverage", "Net debt to EBITDA", "x", _div(net_debt, ebitda * ann))
    add("Leverage", "Interest coverage (EBIT / interest)", "x", _div(ebit, int_exp.abs()))

    add("Efficiency", "Asset turnover", "x", _div(rev * ann, assets))
    add("Efficiency", "Inventory turnover", "x", _div(cogs * ann, inv.replace(0, np.nan)))
    add("Efficiency", "Days inventory outstanding", "days", _div(inv * 365, cogs * ann))
    add("Efficiency", "Receivables turnover", "x", _div(rev * ann, recv))
    add("Efficiency", "Days sales outstanding", "days", _div(recv * 365, rev * ann))
    add("Efficiency", "Days payables outstanding", "days", _div(payables * 365, cogs * ann))
    add("Efficiency", "Cash conversion cycle", "days",
        _div(inv * 365, cogs * ann).fillna(0) + _div(recv * 365, rev * ann) - _div(payables * 365, cogs * ann))

    add("Cash flow", "Operating cash flow", "big", ocf)
    add("Cash flow", "Free cash flow", "big", fcf)
    add("Cash flow", "Operating cash flow margin", "pct", _div(ocf, rev))
    add("Cash flow", "Free cash flow margin", "pct", _div(fcf, rev))
    add("Cash flow", "FCF to net income", "x", _div(fcf, ni))
    add("Cash flow", "Capex to revenue", "pct", _div(capex, rev))
    add("Cash flow", "Dividend payout ratio", "pct", _div(divs_paid, ni))
    add("Cash flow", "Buybacks to net income", "pct", _div(buybacks, ni))

    add("Per share", "Earnings per share (diluted)", "usd", eps)
    add("Per share", "Revenue per share", "usd", _div(rev, dil_shares))
    add("Per share", "Book value per share", "usd", _div(equity, shares))
    add("Per share", "Operating cash flow per share", "usd", _div(ocf, dil_shares))
    add("Per share", "Free cash flow per share", "usd", _div(fcf, dil_shares))
    add("Per share", "Dividends per share", "usd", _div(divs_paid, shares))

    lbl = "YoY" if not quarterly else "YoY (same quarter)"
    add("Growth", f"Revenue growth {lbl}", "pct", yoy(rev))
    add("Growth", f"Gross profit growth {lbl}", "pct", yoy(gp))
    add("Growth", f"Operating income growth {lbl}", "pct", yoy(op))
    add("Growth", f"Net income growth {lbl}", "pct", yoy(ni))
    add("Growth", f"EPS growth {lbl}", "pct", yoy(eps))
    add("Growth", f"Free cash flow growth {lbl}", "pct", yoy(fcf))
    add("Growth", f"Total assets growth {lbl}", "pct", yoy(assets))
    add("Growth", f"Equity growth {lbl}", "pct", yoy(equity))

    add("Valuation", "Market cap (period end)", "big", mcap)
    add("Valuation", "Enterprise value", "big", ev)
    add("Valuation", "Price to earnings (P/E)", "x", _div(mcap, ni * ann))
    add("Valuation", "Price to sales (P/S)", "x", _div(mcap, rev * ann))
    add("Valuation", "Price to book (P/B)", "x", _div(mcap, equity))
    add("Valuation", "EV to EBITDA", "x", _div(ev, ebitda * ann))
    add("Valuation", "EV to revenue", "x", _div(ev, rev * ann))
    add("Valuation", "Free cash flow yield", "pct", _div(fcf * ann, mcap))
    add("Valuation", "Earnings yield", "pct", _div(ni * ann, mcap))
    add("Valuation", "Dividend yield", "pct", _div(divs_paid * ann, mcap))

    add("Shariah", "Debt / market cap (AAOIFI < 30%)", "pct", _div(debt, mcap))
    add("Shariah", "Cash and securities / market cap (AAOIFI < 30%)", "pct", _div(cash_sti, mcap))
    add("Shariah", "Interest income / revenue (limit 5%)", "pct", _div(int_inc.abs(), rev))
    add("Shariah", "Receivables / market cap", "pct", _div(recv, mcap))
    add("Shariah", "Debt / total assets (MSCI < 33.33%)", "pct", _div(debt, assets))
    add("Shariah", "Cash and securities / total assets (MSCI < 33.33%)", "pct", _div(cash_sti, assets))

    table = pd.DataFrame({k: v[2] for k, v in R.items()}).T
    table = table.reindex(columns=periods).replace([np.inf, -np.inf], np.nan)
    # Yahoo's oldest period is often almost empty; drop sparse periods and ratios that don't apply
    counts = table.notna().sum()
    if counts.max() > 0:
        table = table.loc[:, counts >= 0.4 * counts.max()]
    table = table[table.notna().any(axis=1)]
    meta = {k: (v[0], v[1]) for k, v in R.items() if k in table.index}
    return table, meta


def format_value(v, kind):
    if v is None or pd.isna(v) or np.isinf(v):
        return "—"
    if kind == "pct":
        return f"{v:.1%}"
    if kind == "x":
        return f"{v:,.2f}x"
    if kind == "usd":
        return f"${v:,.2f}"
    if kind == "days":
        return f"{v:,.0f} days"
    if kind == "big":
        a = abs(v)
        for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
            if a >= div:
                return f"{'-' if v < 0 else ''}${a / div:,.2f}{suf}"
        return f"${v:,.0f}"
    return f"{v:,.2f}"

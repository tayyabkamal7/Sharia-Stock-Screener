"""Company / ETF drill-down page. All data here is fetched live from Yahoo Finance and cached."""

import json
import time
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots

import relative
import ui
from peers import METRICS, clean
from ratios import CATEGORIES, compute_ratios, format_value
from screening import (CASH_LIMIT, COMPLIANT, DEBT_LIMIT, INTEREST_INCOME_LIMIT, NON_COMPLIANT,
                       QUESTIONABLE, screen_stock)

TTL = 6 * 3600          # statements, analyst detail
LIVE_TTL = 15 * 60      # dividends, calendar
QUOTE_TTL = 60          # company quote (price, day change)
CHART_TTL = 5 * 60      # price history
UP, DOWN, NEUTRAL = "#16A34A", "#DC2626", "#3B82F6"


# ------------------------------------------------------------------------------------------------
# Cached data access (each piece separately, so one failure doesn't break the page)
# ------------------------------------------------------------------------------------------------
@st.cache_data(ttl=QUOTE_TTL, show_spinner=False)
def get_info(t):
    info = dict(yf.Ticker(t).info or {})
    if info:
        info["_checked_at"] = time.time()  # when this quote was fetched (shown in the price stamp)
    return info


@st.cache_data(ttl=CHART_TTL, show_spinner=False)
def get_history(t, period="max"):
    h = yf.Ticker(t).history(period=period, auto_adjust=False)
    if len(h):
        h.index = h.index.tz_localize(None)
    return h


@st.cache_data(ttl=TTL, show_spinner=False)
def get_statements(t, quarterly):
    tk = yf.Ticker(t)
    if quarterly:
        return tk.quarterly_income_stmt, tk.quarterly_balance_sheet, tk.quarterly_cashflow
    return tk.income_stmt, tk.balance_sheet, tk.cashflow


@st.cache_data(ttl=TTL, show_spinner=False)
def get_analyst(t):
    tk = yf.Ticker(t)
    out = {}
    for name in ("analyst_price_targets", "recommendations", "upgrades_downgrades",
                 "earnings_estimate", "revenue_estimate"):
        try:
            out[name] = getattr(tk, name)
        except Exception:
            out[name] = None
    return out


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def get_dividends(t):
    d = yf.Ticker(t).dividends
    if len(d):
        d.index = d.index.tz_localize(None)
    return d


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def get_calendar(t):
    try:
        return yf.Ticker(t).calendar or {}
    except Exception:
        return {}


@st.cache_data(ttl=TTL, show_spinner=False)
def get_fund(t):
    fd = yf.Ticker(t).funds_data
    out = {}
    for name in ("top_holdings", "sector_weightings", "asset_classes", "fund_overview", "fund_operations"):
        try:
            out[name] = getattr(fd, name)
        except Exception:
            out[name] = None
    return out


@st.cache_data(ttl=TTL, show_spinner=False)
def get_ownership(t):
    tk = yf.Ticker(t)
    out = {}
    for name in ("major_holders", "institutional_holders", "mutualfund_holders", "insider_transactions"):
        try:
            out[name] = getattr(tk, name)
        except Exception:
            out[name] = None
    return out


def _safe(fn, *args, default=None):
    try:
        return fn(*args)
    except Exception:
        return default


# ------------------------------------------------------------------------------------------------
# Page
# ------------------------------------------------------------------------------------------------
def render(ticker, row, stock_status, stocks=None):
    """row: the screener row for this ticker (pd.Series) or None for tickers outside the dataset.
    stocks: the full (live-updated) stock table, used for industry/sector comparisons."""
    with st.spinner(f"Loading {ticker}..."):
        info = _safe(get_info, ticker, default={}) or {}
        hist = _safe(get_history, ticker, default=pd.DataFrame())
    if not info and hist.empty:
        if row is None:
            st.error(f"Couldn't load data for {ticker}. Yahoo Finance may be busy; try again in a few minutes.")
            return
        _offline(ticker, row)
        return

    is_etf = info.get("quoteType") == "ETF" if info else (row is not None and row.get("type") == "ETF")
    closes = hist["Close"].dropna() if not hist.empty else pd.Series(dtype=float)
    if info.get("marketState") == "REGULAR" and len(closes) > 1:
        closes = closes.iloc[:-1]  # today's bar is still trading; use the latest official close
    last_close = closes.iloc[-1] if len(closes) else info.get("previousClose")
    prev_close = closes.iloc[-2] if len(closes) > 1 else None
    last_date = closes.index[-1].strftime("%b %d") if len(closes) else ""

    # Status: from the screener dataset, or screened live for tickers outside it
    if row is not None:
        status, reason = row["status"], row["reason"]
    elif not is_etf:
        r = screen_stock(ticker, info.get("industry"), info.get("totalDebt"), info.get("totalCash"),
                         info.get("marketCap"))
        status, reason = r["status"], r["reason"]
    else:
        status, reason = QUESTIONABLE, "Not in the screened dataset"

    # ---- header ----
    name = info.get("longName") or info.get("shortName") or ticker
    sub = " · ".join(filter(None, [info.get("fullExchangeName") or info.get("exchange"),
                                   info.get("category") if is_etf else info.get("sector"),
                                   info.get("fundFamily") if is_etf else info.get("industry")]))
    st.markdown(
        f'<div class="hs-title">{name} <span style="opacity:.55;font-weight:500">{ticker}</span> '
        f'&nbsp;{ui.badge(status)}</div><p class="hs-sub">{sub}</p>'
        f'<div class="hs-reason">{reason}</div>',
        unsafe_allow_html=True,
    )
    # price time: Yahoo's last trade time, or the last daily bar when the quote has none
    price_time = info.get("regularMarketTime") or (closes.index[-1] if len(closes) else None)
    st.markdown(ui.price_stamp(info.get("marketState", "CLOSED"), price_time, info.get("_checked_at")),
                unsafe_allow_html=True)
    st.write("")

    day_chg = (last_close / prev_close - 1) if last_close and prev_close else None
    divs = _safe(get_dividends, ticker, default=pd.Series(dtype=float))

    if is_etf:
        _etf_metrics(info, row, last_close, last_date, day_chg, divs)
        tabs = st.tabs(["Overview", "Holdings", "Dividends", "Shariah compliance"])
        with tabs[0]:
            _overview(ticker, info, hist, is_etf=True)
        with tabs[1]:
            _holdings(ticker, stock_status)
        with tabs[2]:
            _dividends(info, divs, last_close, is_etf=True)
        with tabs[3]:
            _shariah_etf(ticker, row, status, reason, stock_status)
    else:
        _stock_metrics(info, row, last_close, last_date, day_chg, divs)
        tabs = st.tabs(["Overview", "Financial statements", "Ratios", "Relative valuation", "Analysts",
                        "Ownership", "Dividends", "Shariah compliance"])
        with tabs[0]:
            _overview(ticker, info, hist, is_etf=False, row=row, stocks=stocks)
        with tabs[1]:
            _financials(ticker)
        with tabs[2]:
            _ratios(ticker, closes)
        with tabs[3]:
            relative.render(ticker, info, row, stocks, last_close)
        with tabs[4]:
            _analysts(ticker, info, last_close)
        with tabs[5]:
            _ownership(ticker, info)
        with tabs[6]:
            _dividends(info, divs, last_close, is_etf=False)
        with tabs[7]:
            _shariah_stock(ticker, info, row, status, reason, closes, divs)


def _offline(ticker, row):
    """Fallback when live data can't be fetched: show what the screened dataset already has."""
    g = row.get
    sub = " · ".join(str(x) for x in (g("exchange"), g("sector") or g("category"), g("industry") or g("fund_family"))
                     if isinstance(x, str))
    st.markdown(
        f'<div class="hs-title">{g("name")} <span style="opacity:.55;font-weight:500">{ticker}</span> '
        f'&nbsp;{ui.badge(g("status"))}</div><p class="hs-sub">{sub}</p>'
        f'<div class="hs-reason">{g("reason")}</div>', unsafe_allow_html=True)
    st.markdown(ui.price_stamp(None, None, fallback_date=g("last_close_date")
                               if isinstance(g("last_close_date"), str) else None), unsafe_allow_html=True)
    st.write("")
    st.warning("Live financials, charts and analyst details are temporarily unavailable (Yahoo Finance is "
               "limiting requests). Showing the latest screened data; try again in a few minutes.")
    c = st.columns(6)
    c[0].metric("Last close", ui.money(g("last_close")), border=True)
    c[1].metric("Mean analyst target", ui.money(g("target_mean")), border=True)
    c[2].metric("Upside to target", ui.pct(g("upside"), 1, sign=True), border=True)
    c[3].metric("Dividend per share", ui.money(g("div_per_share")), border=True)
    c[4].metric("Ex-dividend date", g("ex_div_date") if isinstance(g("ex_div_date"), str) else "—", border=True)
    etf = g("type") == "ETF"
    c[5].metric("AUM" if etf else "Market cap", ui.big(g("aum") if etf else g("market_cap")), border=True)
    if not etf:
        ui.section("Shariah ratios")
        ui.kv_rows([("Debt / 12-month avg market cap (limit 30%)", ui.pct(g("debt_ratio"))),
                    ("Cash and securities / market cap (limit 30%)", ui.pct(g("cash_ratio"))),
                    ("P/E", ui.mult(g("pe"))), ("Return on equity", ui.pct(g("roe"))),
                    ("Net margin", ui.pct(g("net_margin")))])


def _ttm_dividend(divs):
    if divs is None or not len(divs):
        return None
    recent = divs[divs.index >= pd.Timestamp.now() - pd.Timedelta(days=365)]
    return recent.sum() if len(recent) else None


def _next_ex_div(info, divs):
    ts = info.get("exDividendDate")
    announced = pd.to_datetime(ts, unit="s") if ts else None
    last = divs.index[-1] if divs is not None and len(divs) else None
    if announced is not None and announced < pd.Timestamp.now() - pd.Timedelta(days=400):
        announced = None
    cands = [d for d in (announced, last) if d is not None]
    return max(cands) if cands else None


def _price_metric(col, info, last_close, last_date, day_chg):
    """Live price while the market is open (upside elsewhere stays measured from the last close)."""
    price, chg = info.get("regularMarketPrice"), info.get("regularMarketChangePercent")
    if info.get("marketState") == "REGULAR" and price:
        col.metric("Price · live", ui.money(price), f"{chg:+.2f}% today" if chg is not None else None,
                   help=f"Last close {ui.money(last_close)} ({last_date}). Refreshes every minute.", border=True)
    else:
        col.metric(f"Close ({last_date})", ui.money(last_close),
                   ui.pct(day_chg, 2, sign=True) if day_chg is not None else None, border=True)


def _stock_metrics(info, row, last_close, last_date, day_chg, divs):
    target = info.get("targetMeanPrice")
    upside = target / last_close - 1 if target and last_close else None
    dps = info.get("dividendRate") or _ttm_dividend(divs)
    ex = _next_ex_div(info, divs)
    n = info.get("numberOfAnalystOpinions")
    c = st.columns(7)
    _price_metric(c[0], info, last_close, last_date, day_chg)
    c[1].metric("Mean target", ui.money(target), help="Mean 12-month analyst price target", border=True)
    c[2].metric("Upside", ui.pct(upside, 1, sign=True), help="Mean target vs last close", border=True)
    c[3].metric("Consensus", ui.rating_label(info.get("recommendationKey")),
                f"{n} analysts" if n else None, delta_color="off", border=True)
    c[4].metric("Dividend / share", ui.money(dps) if dps else "None", "annual" if dps else None,
                delta_color="off", border=True)
    c[5].metric("Ex-dividend", ex.strftime("%b %d, %Y") if ex is not None else "—", border=True)
    c[6].metric("Market cap", ui.big(info.get("marketCap")), border=True)


def _etf_metrics(info, row, last_close, last_date, day_chg, divs):
    dps = _ttm_dividend(divs)
    ex = _next_ex_div(info, divs)
    er = info.get("netExpenseRatio")
    ytd = info.get("ytdReturn")
    c = st.columns(7)
    _price_metric(c[0], info, last_close, last_date, day_chg)
    c[1].metric("AUM", ui.big(info.get("totalAssets")), help="Assets under management", border=True)
    c[2].metric("Expense ratio", ui.pct(er / 100, 2) if er is not None else "—", border=True)
    c[3].metric("Yield", ui.pct(info.get("yield"), 2), help="Distribution yield", border=True)
    c[4].metric("Dividend / share", ui.money(dps) if dps else "None", "trailing 12M" if dps else None,
                delta_color="off", border=True)
    c[5].metric("Ex-dividend", ex.strftime("%b %d, %Y") if ex is not None else "—", border=True)
    c[6].metric("YTD return", ui.pct(ytd / 100, 1, sign=True) if ytd is not None else "—", border=True)


# ------------------------------------------------------------------------------------------------
# Overview
# ------------------------------------------------------------------------------------------------
RANGES = {"1M": 21, "3M": 63, "6M": 126, "YTD": None, "1Y": 252, "5Y": 1260, "Max": 0}


def _price_chart(hist, info, rng, show_targets):
    h = hist
    if rng == "YTD":
        h = hist[hist.index >= pd.Timestamp(date.today().year, 1, 1)]
    elif RANGES[rng]:
        h = hist.tail(RANGES[rng])
    if h.empty:
        return None
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.03)
    if len(h) <= 400:
        fig.add_trace(go.Candlestick(x=h.index, open=h["Open"], high=h["High"], low=h["Low"], close=h["Close"],
                                     increasing_line_color=UP, decreasing_line_color=DOWN, name="Price"),
                      row=1, col=1)
    else:
        fig.add_trace(go.Scatter(x=h.index, y=h["Close"], line=dict(color=NEUTRAL, width=1.6), name="Close"),
                      row=1, col=1)
    colors = np.where(h["Close"] >= h["Open"], UP, DOWN)
    fig.add_trace(go.Bar(x=h.index, y=h["Volume"], marker_color=colors, opacity=0.5, name="Volume"),
                  row=2, col=1)
    if show_targets:
        for key, label, dash in (("targetHighPrice", "High target", "dot"), ("targetMeanPrice", "Mean target", "dash"),
                                 ("targetLowPrice", "Low target", "dot")):
            v = info.get(key)
            if v:
                fig.add_hline(y=v, line_dash=dash, line_color="#8B5CF6", line_width=1, row=1, col=1,
                              annotation_text=f"{label} ${v:,.2f}", annotation_position="top left",
                              annotation_font_size=11)
    fig.update_layout(height=470, margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
                      xaxis_rangeslider_visible=False, hovermode="x unified")
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])] if len(h) <= 400 else [])
    fig.update_yaxes(title_text="Price ($)", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1, showticklabels=False)
    return fig


def _overview(ticker, info, hist, is_etf, row=None, stocks=None):
    left, right = st.columns([2.2, 1], gap="large")
    with left:
        c1, c2 = st.columns([3, 1.3])
        rng = c1.segmented_control("Range", list(RANGES), default="1Y", key=f"rng_{ticker}",
                                   label_visibility="collapsed") or "1Y"
        show_t = False if is_etf else c2.toggle("Analyst targets", value=True, key=f"tg_{ticker}")
        fig = _price_chart(hist, info, rng, show_t) if not hist.empty else None
        if fig:
            st.plotly_chart(fig, key=f"px_{ticker}")
        else:
            st.info("Price history unavailable.")
    with right:
        if is_etf:
            ui.section("Fund facts")
            ui.kv_rows([
                ("Category", info.get("category") or "—"),
                ("Fund family", info.get("fundFamily") or "—"),
                ("Assets under management", ui.big(info.get("totalAssets"))),
                ("Expense ratio", ui.pct((info.get("netExpenseRatio") or np.nan) / 100, 2)),
                ("Distribution yield", ui.pct(info.get("yield"), 2)),
                ("3-year avg return", ui.pct(info.get("threeYearAverageReturn"), 1)),
                ("5-year avg return", ui.pct(info.get("fiveYearAverageReturn"), 1)),
                ("Beta (3Y)", ui.num(info.get("beta3Year"))),
                ("52-week range", f"{ui.money(info.get('fiftyTwoWeekLow'))} – {ui.money(info.get('fiftyTwoWeekHigh'))}"),
                ("Inception", datetime.fromtimestamp(info["fundInceptionDate"]).strftime("%b %Y")
                 if info.get("fundInceptionDate") else "—"),
            ])
        else:
            ui.section("Key statistics")
            cal = _safe(get_calendar, ticker, default={}) or {}
            dates = [d for d in (cal.get("Earnings Date") or []) if isinstance(d, date) and d >= date.today()]
            earn_ts = info.get("earningsTimestampStart") or info.get("earningsTimestamp")
            if dates:
                earn = dates[0].strftime("%b %d, %Y")
            elif earn_ts and datetime.fromtimestamp(earn_ts).date() >= date.today():
                earn = datetime.fromtimestamp(earn_ts).strftime("%b %d, %Y")
            else:
                earn = "Not announced"
            ui.kv_rows([
                ("Market cap", ui.big(info.get("marketCap"))),
                ("Enterprise value", ui.big(info.get("enterpriseValue"))),
                ("Revenue (TTM)", ui.big(info.get("totalRevenue"))),
                ("EBITDA", ui.big(info.get("ebitda"))),
                ("EPS (TTM)", ui.money(info.get("trailingEps"))),
                ("Forward EPS", ui.money(info.get("forwardEps"))),
                ("Book value per share", ui.money(info.get("bookValue"))),
                ("Shares outstanding", f"{info['sharesOutstanding'] / 1e6:,.1f}M" if info.get("sharesOutstanding")
                 else "—"),
                ("Short interest (% of float)", ui.pct(info.get("shortPercentOfFloat"), 2)),
                ("Beta", ui.num(info.get("beta"))),
                ("52-week range", f"{ui.money(info.get('fiftyTwoWeekLow'))} – {ui.money(info.get('fiftyTwoWeekHigh'))}"),
                ("Next earnings", earn),
            ])
    if not is_etf:
        _vs_industry(ticker, info, row, stocks)
    _about(info, is_etf)


# yfinance info field for each comparison metric (the company side comes from live data)
INFO_KEYS = {"pe": "trailingPE", "forward_pe": "forwardPE", "peg": "trailingPegRatio",
             "ps": "priceToSalesTrailing12Months", "pb": "priceToBook", "ev_ebitda": "enterpriseToEbitda",
             "ev_revenue": "enterpriseToRevenue", "gross_margin": "grossMargins",
             "operating_margin": "operatingMargins", "net_margin": "profitMargins", "roe": "returnOnEquity",
             "roa": "returnOnAssets", "revenue_growth": "revenueGrowth", "earnings_growth": "earningsGrowth",
             "current_ratio": "currentRatio", "beta": "beta", "payout_ratio": "payoutRatio"}
OVERVIEW_METRICS = ["pe", "forward_pe", "peg", "ps", "pb", "ev_ebitda", "gross_margin", "operating_margin",
                    "net_margin", "roe", "roa", "revenue_growth", "earnings_growth", "current_ratio",
                    "debt_to_equity", "dividend_yield", "payout_ratio", "beta"]


def _vs_industry(ticker, info, row, stocks):
    if stocks is None or stocks.empty or row is None:
        return
    industry = stocks[(stocks["industry"] == row.get("industry")) & (stocks["ticker"] != ticker)]
    sector = stocks[(stocks["sector"] == row.get("sector")) & (stocks["ticker"] != ticker)]
    ui.section(f"Key ratios vs industry ({len(industry)} companies) and sector ({len(sector)} companies)")
    rows = []
    for k in OVERVIEW_METRICS:
        label, kind = METRICS[k][0], METRICS[k][1]
        v = info.get(INFO_KEYS[k]) if k in INFO_KEYS else None
        if v is None:
            v = row.get(k)
        v = clean(pd.Series([v]), k).iloc[0]
        ind = clean(industry[k], k).median() if k in industry else np.nan
        sec = clean(sector[k], k).median() if k in sector else np.nan
        rows.append({"Metric": label, "Company": relative.fmt(v, kind), "Industry median": relative.fmt(ind, kind),
                     "Sector median": relative.fmt(sec, kind),
                     "vs industry": "—" if pd.isna(v) or pd.isna(ind) or ind == 0 else f"{v / ind - 1:+.0%}"})
    half = (len(rows) + 1) // 2
    c1, c2 = st.columns(2, gap="large")
    c1.dataframe(pd.DataFrame(rows[:half]), hide_index=True)
    c2.dataframe(pd.DataFrame(rows[half:]), hide_index=True)
    st.caption("Medians exclude the company itself; negative valuation multiples are left out. "
               "See Relative valuation for a full peer comparison.")


def _about(info, is_etf):
    summary = info.get("longBusinessSummary")
    if not summary:
        return
    ui.section("About the fund" if is_etf else "About the company")
    left, right = st.columns([1.7, 1], gap="large")
    with left:
        st.write(summary)
        officers = info.get("companyOfficers") or []
        if officers:
            ui.section("Key executives")
            st.dataframe(pd.DataFrame([{
                "Name": o.get("name", "—"), "Title": o.get("title", "—"),
                "Age": str(o["age"]) if o.get("age") else "—",
                "Total pay": ui.big(o["totalPay"]) if o.get("totalPay") else "—",
            } for o in officers[:8]]), hide_index=True)
    with right:
        hq = ", ".join(filter(None, [info.get("city"), info.get("state"), info.get("country")]))
        rows = [("Headquarters", hq or "—")]
        if not is_etf:
            rows += [("Sector", info.get("sectorDisp") or info.get("sector") or "—"),
                     ("Industry", info.get("industryDisp") or info.get("industry") or "—"),
                     ("Employees", f"{info['fullTimeEmployees']:,}" if info.get("fullTimeEmployees") else "—")]
        rows += [("Exchange", info.get("fullExchangeName") or "—"), ("Phone", info.get("phone") or "—")]
        ui.kv_rows(rows)
        if info.get("website"):
            st.markdown(f"[{info['website']}]({info['website']})")


# ------------------------------------------------------------------------------------------------
# Financial statements
# ------------------------------------------------------------------------------------------------
KEY_LINES = {
    "Income statement": ["Total Revenue", "Cost Of Revenue", "Gross Profit", "Research And Development",
                         "Selling General And Administration", "Operating Expense", "Operating Income",
                         "Interest Income", "Interest Expense", "Pretax Income", "Tax Provision", "Net Income",
                         "EBITDA", "Diluted EPS", "Diluted Average Shares"],
    "Balance sheet": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments",
                      "Accounts Receivable", "Inventory", "Current Assets", "Net PPE", "Goodwill",
                      "Total Assets", "Accounts Payable", "Current Liabilities", "Long Term Debt", "Total Debt",
                      "Total Liabilities Net Minority Interest", "Stockholders Equity", "Retained Earnings",
                      "Net Debt", "Working Capital", "Ordinary Shares Number"],
    "Cash flow": ["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow", "Investing Cash Flow",
                  "Purchase Of Business", "Financing Cash Flow", "Cash Dividends Paid",
                  "Repurchase Of Capital Stock", "Issuance Of Debt", "Repayment Of Debt",
                  "Stock Based Compensation", "Depreciation And Amortization", "Changes In Cash"],
}
DEFAULT_CHART = {"Income statement": ["Total Revenue", "Gross Profit", "Net Income"],
                 "Balance sheet": ["Total Assets", "Total Debt", "Stockholders Equity"],
                 "Cash flow": ["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure"]}


def _is_per_share(line):
    return "EPS" in line or "Per Share" in line or "Tax Rate" in line


def _is_shares(line):
    return "Shares" in line or "Share Issued" in line or "Shares Number" in line


def _financials(ticker):
    c1, c2, c3 = st.columns([2.2, 1.4, 1])
    stmt = c1.segmented_control("Statement", list(KEY_LINES), default="Income statement",
                                key=f"fs_{ticker}") or "Income statement"
    per = c2.segmented_control("Period", ["Annual", "Quarterly"], default="Annual", key=f"fp_{ticker}") or "Annual"
    show_all = c3.toggle("All line items", key=f"fa_{ticker}")

    try:
        inc, bal, cf = get_statements(ticker, per == "Quarterly")
    except Exception:
        st.warning("Financial statements are unavailable right now.")
        return
    df = {"Income statement": inc, "Balance sheet": bal, "Cash flow": cf}[stmt]
    if df is None or df.empty:
        st.info("No statement data reported for this company.")
        return
    df = df.loc[:, df.notna().mean() >= 0.3]
    if not show_all:
        df = df.reindex([l for l in KEY_LINES[stmt] if l in df.index])
    df = df.dropna(how="all")
    cols = [c.strftime("%b %Y" if per == "Annual" else "%b %d, %Y") for c in df.columns]

    def fmt(line, v):
        if pd.isna(v):
            return "—"
        if _is_per_share(line):
            return f"{v:,.2f}"
        if _is_shares(line):
            return f"{v / 1e6:,.1f}M"
        return f"{v / 1e6:,.0f}"

    shown = pd.DataFrame([[fmt(l, v) for v in df.loc[l]] for l in df.index], index=df.index, columns=cols)
    st.caption("USD millions, except per-share values and share counts. Fiscal periods as reported.")
    st.dataframe(shown, height=min(38 * (len(shown) + 1) + 4, 720))

    chartable = [l for l in df.index if not _is_per_share(l) and not _is_shares(l)]
    picks = st.multiselect("Chart line items", chartable,
                           default=[l for l in DEFAULT_CHART[stmt] if l in chartable][:3], key=f"fc_{ticker}_{stmt}")
    if picks:
        fig = go.Figure()
        for l in picks:
            fig.add_trace(go.Bar(x=cols[::-1], y=(df.loc[l] / 1e6).values[::-1], name=l))
        fig.update_layout(barmode="group", height=360, margin=dict(l=0, r=0, t=10, b=0),
                          yaxis_title="USD millions", legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, key=f"fcc_{ticker}")


# ------------------------------------------------------------------------------------------------
# Ratios
# ------------------------------------------------------------------------------------------------
def _ratios(ticker, closes):
    c1, c2 = st.columns([1.2, 4])
    per = c1.segmented_control("Period", ["Annual", "Quarterly"], default="Annual", key=f"rp_{ticker}") or "Annual"
    try:
        inc, bal, cf = get_statements(ticker, per == "Quarterly")
        table, meta = compute_ratios(inc, bal, cf, closes, quarterly=per == "Quarterly")
    except Exception:
        st.warning("Ratios are unavailable because financial statements couldn't be loaded.")
        return
    if table.empty:
        st.info("Not enough reported financial data to compute ratios.")
        return
    available = [c for c in CATEGORIES if any(meta[k][0] == c for k in table.index)]
    cat = c2.pills("Category", ["All"] + available, default="Profitability" if "Profitability" in available
                   else available[0], key=f"rc_{ticker}", label_visibility="collapsed") or "All"

    rows = [k for k in table.index if cat == "All" or meta[k][0] == cat]
    fmt_cols = [c.strftime("%b %Y" if per == "Annual" else "%b %d, %Y") for c in table.columns]
    shown = pd.DataFrame([[format_value(v, meta[k][1]) for v in table.loc[k]] for k in rows],
                         index=rows, columns=fmt_cols)
    if cat == "All":
        shown.insert(0, "Category", [meta[k][0] for k in rows])
    st.dataframe(shown, height=min(36 * (len(shown) + 1) + 4, 760))
    if per == "Quarterly":
        st.caption("Quarterly return, turnover and valuation ratios are annualized (x4). "
                   "Growth compares with the same quarter a year earlier.")

    picks = st.multiselect("Chart ratios", rows, default=rows[:2], key=f"rs_{ticker}_{cat}_{per}")
    if picks:
        kind = meta[picks[0]][1]
        fig = go.Figure()
        for k in picks:
            y = table.loc[k].values[::-1].astype(float)
            fig.add_trace(go.Scatter(x=fmt_cols[::-1], y=y * (100 if meta[k][1] == "pct" else 1), name=k,
                                     mode="lines+markers+text", line=dict(width=2.2),
                                     text=[format_value(v, meta[k][1]) for v in y], textposition="top center",
                                     textfont=dict(size=11)))
        for k in picks:
            if "30%" in k:
                fig.add_hline(y=30, line_dash="dash", line_color=DOWN, annotation_text="AAOIFI limit 30%")
            if "limit 5%" in k:
                fig.add_hline(y=5, line_dash="dash", line_color=DOWN, annotation_text="5% limit")
        fig.update_layout(height=380, margin=dict(l=0, r=0, t=30, b=0), legend=dict(orientation="h", y=1.12),
                          yaxis_title={"pct": "%", "x": "multiple (x)", "usd": "USD", "days": "days",
                                       "big": "USD"}.get(kind, ""))
        st.plotly_chart(fig, key=f"rch_{ticker}")


# ------------------------------------------------------------------------------------------------
# Analysts
# ------------------------------------------------------------------------------------------------
ACTIONS = {"up": "Upgrade", "down": "Downgrade", "main": "Maintained", "init": "Initiated", "reit": "Reiterated"}
EST_PERIODS = {"0q": "Current quarter", "+1q": "Next quarter", "0y": "Current fiscal year", "+1y": "Next fiscal year"}


def _analysts(ticker, info, last_close):
    a = _safe(get_analyst, ticker, default={}) or {}
    pt = a.get("analyst_price_targets") or {}
    low, med, mean, high = (pt.get("low") or info.get("targetLowPrice"), pt.get("median") or info.get("targetMedianPrice"),
                            pt.get("mean") or info.get("targetMeanPrice"), pt.get("high") or info.get("targetHighPrice"))
    if not any([low, med, mean, high]):
        st.info("No analyst coverage for this company.")
        return

    left, right = st.columns(2, gap="large")
    with left:
        ui.section(f"12-month price targets vs last close ({ui.money(last_close)})")
        rows = []
        for label, v in (("Low", low), ("Median", med), ("Mean", mean), ("High", high)):
            up = v / last_close - 1 if v and last_close else None
            rows.append((label, f"{ui.money(v)} &nbsp; {ui.signed_html(up)}"))
        ui.kv_rows(rows)
        if last_close:
            labels, vals = zip(*[(l, v) for l, v in (("Low", low), ("Median", med), ("Mean", mean), ("High", high)) if v])
            fig = go.Figure(go.Bar(
                x=list(vals), y=list(labels), orientation="h",
                marker_color=[UP if v >= last_close else DOWN for v in vals],
                text=[f"${v:,.2f}" for v in vals], textposition="outside", cliponaxis=False))
            fig.add_vline(x=last_close, line_dash="dash", line_color=NEUTRAL,
                          annotation_text=f"Last close ${last_close:,.2f}", annotation_position="top")
            fig.update_layout(height=230, showlegend=False, margin=dict(l=0, r=40, t=30, b=0),
                              xaxis=dict(tickprefix="$", range=[0, max(vals) * 1.18]),
                              yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, key=f"ptr_{ticker}")
    with right:
        n = info.get("numberOfAnalystOpinions")
        score = info.get("recommendationMean")
        ui.section("Consensus recommendation")
        st.markdown(f"**{ui.rating_label(info.get('recommendationKey'))}** "
                    f"<span class='hs-muted'>· score {score:.2f} on a 1 (Strong Buy) to 5 (Strong Sell) scale"
                    f"{f' · {n} analysts' if n else ''}</span>" if score else "—", unsafe_allow_html=True)
        rec = a.get("recommendations")
        if isinstance(rec, pd.DataFrame) and not rec.empty:
            labels = {"0m": "Current", "-1m": "1 month ago", "-2m": "2 months ago", "-3m": "3 months ago"}
            rec = rec.copy()
            rec["period"] = rec["period"].map(labels).fillna(rec["period"])
            fig = go.Figure()
            for col, label, color in (("strongBuy", "Strong Buy", "#15803D"), ("buy", "Buy", "#4ADE80"),
                                      ("hold", "Hold", "#FBBF24"), ("sell", "Sell", "#F87171"),
                                      ("strongSell", "Strong Sell", "#B91C1C")):
                fig.add_trace(go.Bar(y=rec["period"], x=rec[col], name=label, orientation="h", marker_color=color,
                                     text=rec[col], textposition="inside"))
            fig.update_layout(barmode="stack", height=250, margin=dict(l=0, r=0, t=10, b=0),
                              legend=dict(orientation="h", y=-0.15), yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, key=f"rec_{ticker}")

    ud = a.get("upgrades_downgrades")
    if isinstance(ud, pd.DataFrame) and not ud.empty:
        ui.section("Recent rating changes")
        u = ud.head(40).reset_index()
        u = pd.DataFrame({
            "Date": pd.to_datetime(u["GradeDate"]).dt.strftime("%b %d, %Y"),
            "Firm": u["Firm"],
            "Action": u["Action"].map(ACTIONS).fillna(u["Action"]),
            "From": u["FromGrade"].replace("", "—"),
            "To": u["ToGrade"],
            "Prior target": u.get("priorPriceTarget", pd.Series(dtype=float)).map(lambda v: ui.money(v) if v else "—"),
            "New target": u.get("currentPriceTarget", pd.Series(dtype=float)).map(lambda v: ui.money(v) if v else "—"),
        })
        st.dataframe(u, hide_index=True, height=360)

    for key, title, money_fmt in (("earnings_estimate", "Earnings per share estimates", True),
                                  ("revenue_estimate", "Revenue estimates", False)):
        e = a.get(key)
        if isinstance(e, pd.DataFrame) and not e.empty:
            ui.section(title)
            e = e.copy()
            e.index = e.index.map(lambda p: EST_PERIODS.get(p, p))
            e.index.name = "Period"
            f = (lambda v: ui.money(v)) if money_fmt else (lambda v: ui.big(v))
            out = pd.DataFrame(index=e.index)
            for col, label in (("avg", "Average"), ("low", "Low"), ("high", "High")):
                if col in e:
                    out[label] = e[col].map(f)
            if "yearAgoEps" in e:
                out["Year ago"] = e["yearAgoEps"].map(f)
            if "yearAgoRevenue" in e:
                out["Year ago"] = e["yearAgoRevenue"].map(f)
            if "growth" in e:
                out["Growth"] = e["growth"].map(lambda v: ui.pct(v, 1, sign=True))
            if "numberOfAnalysts" in e:
                out["Analysts"] = e["numberOfAnalysts"].map(lambda v: "—" if pd.isna(v) else f"{int(v)}")
            st.dataframe(out)


# ------------------------------------------------------------------------------------------------
# Ownership
# ------------------------------------------------------------------------------------------------
def _holders_table(df):
    d = df.copy()
    out = pd.DataFrame({
        "Holder": d["Holder"],
        "% of shares": d["pctHeld"].map(lambda v: ui.pct(v, 2)),
        "Shares": d["Shares"].map(lambda v: f"{v / 1e6:,.2f}M" if pd.notna(v) else "—"),
        "Value": d["Value"].map(ui.big),
        "Change": d["pctChange"].map(lambda v: ui.pct(v, 1, sign=True)) if "pctChange" in d else "—",
        "Reported": pd.to_datetime(d["Date Reported"]).dt.strftime("%b %d, %Y"),
    })
    return out


def _ownership(ticker, info):
    o = _safe(get_ownership, ticker, default={}) or {}
    mh = o.get("major_holders")
    vals = {}
    if isinstance(mh, pd.DataFrame) and not mh.empty:
        vals = mh.iloc[:, 0].to_dict()
    insiders = vals.get("insidersPercentHeld", info.get("heldPercentInsiders"))
    inst = vals.get("institutionsPercentHeld", info.get("heldPercentInstitutions"))
    if insiders is None and inst is None:
        st.info("Ownership data isn't available for this company.")
        return

    left, right = st.columns([1, 1.4], gap="large")
    with left:
        ui.section("Shareholding breakdown")
        ins, ins_t = float(insiders or 0), float(inst or 0)
        public = max(0.0, 1 - ins - ins_t)
        fig = go.Figure(go.Pie(labels=["Institutions", "Insiders", "Public and other"],
                               values=[ins_t, ins, public], hole=0.62, sort=False,
                               marker=dict(colors=["#14B8A6", "#8B5CF6", "#94A3B8"]),
                               texttemplate="%{percent:.1%}", textposition="inside"))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), showlegend=True,
                          legend=dict(orientation="h", y=-0.05))
        st.plotly_chart(fig, key=f"own_{ticker}")
    with right:
        ui.section("Ownership details")
        ui.kv_rows([
            ("Held by insiders", ui.pct(insiders, 2)),
            ("Held by institutions", ui.pct(inst, 2)),
            ("Institutional share of float", ui.pct(vals.get("institutionsFloatPercentHeld"), 2)),
            ("Number of institutions", f"{int(vals['institutionsCount']):,}" if vals.get("institutionsCount")
             else "—"),
            ("Shares outstanding", f"{info['sharesOutstanding'] / 1e6:,.1f}M" if info.get("sharesOutstanding")
             else "—"),
            ("Float", f"{info['floatShares'] / 1e6:,.1f}M" if info.get("floatShares") else "—"),
            ("Shares sold short", f"{info['sharesShort'] / 1e6:,.2f}M" if info.get("sharesShort") else "—"),
            ("Short interest (% of float)", ui.pct(info.get("shortPercentOfFloat"), 2)),
        ])

    for key, title in (("institutional_holders", "Top institutional holders"),
                       ("mutualfund_holders", "Top mutual fund and ETF holders")):
        d = o.get(key)
        if isinstance(d, pd.DataFrame) and not d.empty and "Holder" in d:
            ui.section(title)
            st.dataframe(_holders_table(d), hide_index=True)

    it = o.get("insider_transactions")
    if isinstance(it, pd.DataFrame) and not it.empty:
        ui.section("Recent insider transactions")
        t = it.head(25)
        st.dataframe(pd.DataFrame({
            "Date": pd.to_datetime(t["Start Date"]).dt.strftime("%b %d, %Y"),
            "Insider": t["Insider"].str.title(),
            "Position": t["Position"],
            "Transaction": t["Text"].replace("", "—"),
            "Shares": t["Shares"].map(lambda v: f"{v:,.0f}" if pd.notna(v) else "—"),
            "Value": t["Value"].map(lambda v: ui.big(v) if pd.notna(v) and v else "—"),
        }), hide_index=True, height=min(36 * (len(t) + 1) + 4, 520))
        st.caption("Transactions reported to the SEC (Form 4). Option exercises and gifts are included.")


# ------------------------------------------------------------------------------------------------
# Dividends
# ------------------------------------------------------------------------------------------------
def _dividends(info, divs, last_close, is_etf):
    if divs is None or not len(divs):
        st.info("This security hasn't paid a dividend.")
        return
    ttm = _ttm_dividend(divs)
    fwd = None if is_etf else info.get("dividendRate")
    last_ex = divs.index[-1]
    ts = info.get("exDividendDate")
    announced = pd.to_datetime(ts, unit="s") if ts else None
    cal = {} if is_etf else _safe(get_calendar, info.get("symbol", ""), default={}) or {}
    pay = cal.get("Dividend Date")
    next_ex = announced if announced is not None and announced > last_ex else None

    c = st.columns(4)
    c[0].metric("Annual dividend per share", ui.money(fwd or ttm), "forward rate" if fwd else "trailing 12 months",
                delta_color="off", border=True)
    c[1].metric("Dividend yield", ui.pct((fwd or ttm) / last_close if last_close and (fwd or ttm) else None, 2),
                border=True)
    c[2].metric("Last dividend per share", ui.money(divs.iloc[-1], 4 if divs.iloc[-1] < 0.1 else 2), border=True)
    c[3].metric("Last ex-dividend date", last_ex.strftime("%b %d, %Y"), border=True)
    c = st.columns(4)
    c[0].metric("Next ex-dividend date", next_ex.strftime("%b %d, %Y") if next_ex is not None else "Not announced",
                border=True)
    c[1].metric("Payment date", pay.strftime("%b %d, %Y") if isinstance(pay, (date, datetime)) else "—", border=True)
    if is_etf:
        c[2].metric("Distribution yield (fund)", ui.pct(info.get("yield"), 2), border=True)
        c[3].metric("Payments in last 12 months", f"{(divs.index >= pd.Timestamp.now() - pd.Timedelta(days=365)).sum()}",
                    border=True)
    else:
        c[2].metric("Payout ratio", ui.pct(info.get("payoutRatio"), 1), border=True)
        fy = info.get("fiveYearAvgDividendYield")
        c[3].metric("5-year average yield", ui.pct(fy / 100, 2) if fy else "—", border=True)

    left, right = st.columns([1.6, 1], gap="large")
    with left:
        view = st.segmented_control("View", ["Each payment", "Annual total"], default="Annual total",
                                    key=f"dv_{info.get('symbol')}") or "Annual total"
        if view == "Annual total":
            yearly = divs.groupby(divs.index.year).sum()
            fig = go.Figure(go.Bar(x=yearly.index.astype(str), y=yearly.values, marker_color=NEUTRAL,
                                   text=[f"${v:,.2f}" for v in yearly.values], textposition="outside"))
            st.caption(f"{date.today().year} is year-to-date.")
        else:
            d = divs.tail(60)
            fig = go.Figure(go.Bar(x=d.index, y=d.values, marker_color=NEUTRAL))
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), yaxis_tickprefix="$",
                          yaxis_title="Dividend per share")
        st.plotly_chart(fig, key=f"dch_{info.get('symbol')}")
    with right:
        ui.section("Recent payments")
        recent = divs.iloc[::-1].head(16)
        st.dataframe(pd.DataFrame({"Ex-dividend date": recent.index.strftime("%b %d, %Y"),
                                   "Amount per share": [f"${v:,.4f}" for v in recent.values]}),
                     hide_index=True, height=400)


# ------------------------------------------------------------------------------------------------
# Shariah compliance
# ------------------------------------------------------------------------------------------------
def _result(ok):
    if ok is None:
        return "No data"
    return "Pass" if ok else "Fail"


def _shariah_stock(ticker, info, row, status, reason, closes, divs):
    st.markdown(f"{ui.badge(status)} &nbsp; {reason}", unsafe_allow_html=True)

    debt_ratio = row["debt_ratio"] if row is not None else None
    cash_ratio = row["cash_ratio"] if row is not None else None
    mcap_basis = "12-month average market cap"
    if debt_ratio is None or pd.isna(debt_ratio):
        mc = info.get("marketCap")
        debt_ratio = (info.get("totalDebt") or 0) / mc if mc else None
        cash_ratio = (info.get("totalCash") or 0) / mc if mc else None
        mcap_basis = "current market cap"

    int_ratio = None
    try:
        inc, _, _ = get_statements(ticker, False)
        rev = inc.loc["Total Revenue"].dropna()
        ii = None
        for line in ("Interest Income", "Interest Income Non Operating"):
            if line in inc.index and inc.loc[line].notna().any():
                ii = inc.loc[line].dropna()
                break
        if ii is not None and len(rev):
            period = [p for p in ii.index if p in rev.index][0]
            int_ratio = abs(ii[period]) / rev[period]
    except Exception:
        pass

    biz = row["business_status"] if row is not None else None
    tests = pd.DataFrame([
        {"Test": "Business activity", "Value": info.get("industry") or "—", "Threshold": "Permissible core business",
         "Result": {COMPLIANT: "Pass", NON_COMPLIANT: "Fail", QUESTIONABLE: "Doubtful"}.get(biz, "—")},
        {"Test": f"Interest-bearing debt / {mcap_basis}", "Value": ui.pct(debt_ratio),
         "Threshold": "< 30%", "Result": _result(None if debt_ratio is None else debt_ratio < DEBT_LIMIT)},
        {"Test": f"Cash and interest-bearing securities / {mcap_basis}", "Value": ui.pct(cash_ratio),
         "Threshold": "< 30%", "Result": _result(None if cash_ratio is None else cash_ratio < CASH_LIMIT)},
        {"Test": "Interest income / revenue (latest fiscal year)", "Value": ui.pct(int_ratio, 2),
         "Threshold": "< 5%", "Result": _result(None if int_ratio is None else int_ratio < INTEREST_INCOME_LIMIT)},
    ])

    def color(v):
        return {"Pass": f"color:{UP};font-weight:600", "Fail": f"color:{DOWN};font-weight:600",
                "Doubtful": "color:#D97706;font-weight:600"}.get(v, "")

    st.dataframe(tests.style.map(color, subset=["Result"]), hide_index=True)
    st.caption("The interest income test is informational and not part of the overall status, "
               "because not every company reports interest income separately.")

    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Ratios against AAOIFI limits")
        fig = go.Figure()
        vals = [("Debt / market cap", debt_ratio, 0.30), ("Cash and securities / market cap", cash_ratio, 0.30),
                ("Interest income / revenue", int_ratio, 0.05)]
        for label, v, lim in vals:
            if v is not None and not pd.isna(v):
                fig.add_trace(go.Bar(y=[label], x=[v * 100], orientation="h", text=[f"{v:.1%}"],
                                     textposition="outside", marker_color=UP if v < lim else DOWN))
                fig.add_trace(go.Scatter(y=[label], x=[lim * 100], mode="markers", marker_symbol="line-ns-open",
                                         marker=dict(size=26, color=DOWN, line_width=3), name="Limit"))
        fig.update_layout(height=230, margin=dict(l=0, r=30, t=10, b=0), showlegend=False,
                          xaxis=dict(title="% (red tick = limit)", range=[0, max(35, *(v * 115 for _, v, _ in vals
                                                                                    if v is not None and not pd.isna(v)))]))
        st.plotly_chart(fig, key=f"sh_{ticker}")
    with right:
        ui.section("Dividend purification")
        dps = info.get("dividendRate") or _ttm_dividend(divs)
        if dps and int_ratio is not None:
            st.markdown(f"Estimated impure portion of income: **{int_ratio:.2%}** (interest income / revenue).")
            st.markdown(f"Suggested purification: **\\${dps * int_ratio:,.4f} per share per year** "
                        f"on an annual dividend of \\{ui.money(dps)}.")
            st.caption("Common method: donate the dividend multiplied by the share of non-permissible income. "
                       "Scholars differ; some also purify capital gains.")
        elif not dps:
            st.markdown("No dividend, so no dividend purification is needed.")
        else:
            st.markdown("Not enough data to estimate purification.")

    try:
        inc, bal, cf = get_statements(ticker, False)
        table, _ = compute_ratios(inc, bal, cf, closes)
        keys = [k for k in table.index if k.startswith(("Debt / market cap", "Cash and securities / market cap",
                                                        "Interest income / revenue"))]
        if keys:
            ui.section("Compliance trend by fiscal year")
            fig = go.Figure()
            for k in keys:
                fig.add_trace(go.Scatter(x=[c.strftime("%Y") for c in table.columns][::-1],
                                         y=(table.loc[k] * 100).values[::-1], name=k.split(" (")[0],
                                         mode="lines+markers"))
            fig.add_hline(y=30, line_dash="dash", line_color=DOWN, annotation_text="30% limit")
            fig.add_hline(y=5, line_dash="dot", line_color="#D97706", annotation_text="5% limit")
            fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="%",
                              legend=dict(orientation="h", y=1.12), xaxis_type="category")
            st.plotly_chart(fig, key=f"sht_{ticker}")
            st.caption("Historical ratios use each fiscal year-end market cap.")
    except Exception:
        pass


def _holdings(ticker, stock_status):
    f = _safe(get_fund, ticker, default={}) or {}
    th = f.get("top_holdings")
    left, right = st.columns([1.3, 1], gap="large")
    with left:
        ui.section("Top holdings")
        if isinstance(th, pd.DataFrame) and not th.empty:
            h = th.reset_index()
            h.columns = ["Symbol", "Name", "Weight"][:len(h.columns)]
            h["Shariah status"] = h["Symbol"].map(lambda s: stock_status.get(str(s).replace(".", "-"), "Not screened"))
            h["Weight"] = h["Weight"].map(lambda v: f"{v:.2%}")

            def color(v):
                return {COMPLIANT: f"color:{UP}", NON_COMPLIANT: f"color:{DOWN}",
                        QUESTIONABLE: "color:#D97706"}.get(v, "")

            st.dataframe(h.style.map(color, subset=["Shariah status"]), hide_index=True)
        else:
            st.info("Holdings data unavailable for this fund.")
    with right:
        sw = f.get("sector_weightings")
        if sw:
            ui.section("Sector weights")
            s = pd.Series(sw).sort_values()
            s = s[s > 0]
            s.index = [i.replace("_", " ").title() for i in s.index]
            fig = go.Figure(go.Bar(x=s.values * 100, y=s.index, orientation="h",
                                   marker_color=[DOWN if "Financial" in i else NEUTRAL for i in s.index],
                                   text=[f"{v:.1%}" for v in s.values], textposition="outside"))
            fig.update_layout(height=380, margin=dict(l=0, r=30, t=10, b=0), xaxis_title="% of fund")
            st.plotly_chart(fig, key=f"sw_{ticker}")
        ac = f.get("asset_classes")
        if ac:
            ui.section("Asset classes")
            ui.kv_rows([(k.replace("Position", "").replace("Position", "").title(), ui.pct(v, 1))
                        for k, v in ac.items() if v])


def _shariah_etf(ticker, row, status, reason, stock_status):
    st.markdown(f"{ui.badge(status)} &nbsp; {reason}", unsafe_allow_html=True)
    st.write("")
    ui.kv_rows([
        ("Category", (row["category"] if row is not None and isinstance(row.get("category"), str) else "—")),
        ("Weight in financial services", ui.pct(row.get("financials_weight") if row is not None else None)),
        ("Top-holdings weight in non-compliant stocks",
         ui.pct(row.get("noncompliant_weight") if row is not None else None)),
    ])
    st.write("")
    st.markdown("""
**How ETFs are screened**
- Funds that are Shariah-screened by mandate (for example SP Funds and Wahed) are **Compliant**.
- Bond, money-market, leveraged or inverse, options and futures funds are **Non-Compliant**.
- Other equity funds are checked against their holdings. More than 5% in financial services, or more than
  5% in non-compliant stocks among the top holdings, makes a fund **Non-Compliant**. Otherwise it's
  **Questionable**, because a conventional fund isn't screened or purified by its manager, and its
  holdings can change at any time.
""")

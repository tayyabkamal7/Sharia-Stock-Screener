import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

import company
import live
import methodology
import nav
import peers
import ui
from screening import COMPLIANT, NON_COMPLIANT, QUESTIONABLE, STATUSES

DATA = Path(__file__).parent / "data"

st.set_page_config(page_title="Shariah Stock Screener", page_icon="☪", layout="wide",
                   initial_sidebar_state="auto")  # open on desktop, closed on phones
MOBILE = ui.is_mobile()
ui.inject_css()

# Widgets that aren't drawn on a run lose their state; re-assigning keeps filters when visiting a company page.
for k in list(st.session_state.keys()):
    if isinstance(k, str) and k.startswith("f_"):
        st.session_state[k] = st.session_state[k]


# ------------------------------------------------------------------------------------------------
# Data
# ------------------------------------------------------------------------------------------------
def _mtime(name):
    p = DATA / name
    return p.stat().st_mtime if p.exists() else 0


@st.cache_data(show_spinner=False)
def load(version):
    """Screened dataset. `version` (file modification times) is part of the cache key, so the data reloads
    as soon as new files land. (Don't prefix it with "_": Streamlit leaves such arguments out of the key.)"""
    stocks = pd.read_csv(DATA / "stocks.csv") if (DATA / "stocks.csv").exists() else pd.DataFrame()
    etfs = pd.read_csv(DATA / "etfs.csv") if (DATA / "etfs.csv").exists() else pd.DataFrame()
    meta = json.loads((DATA / "meta.json").read_text()) if (DATA / "meta.json").exists() else {}
    if len(stocks):
        stocks["num_analysts"] = stocks["num_analysts"].fillna(0).astype(int)
        stocks["debt_to_equity"] = stocks["debt_to_equity"] / 100  # Yahoo reports this in percent
        if "div_yield_5y" in stocks:
            stocks["div_yield_5y"] = stocks["div_yield_5y"] / 100  # also in percent
    if len(etfs):
        etfs["expense_ratio"] = etfs["expense_ratio"] / 100      # Yahoo reports these two in percent
        etfs["ytd_return"] = etfs["ytd_return"] / 100
    for d in (stocks, etfs):
        if len(d):
            d["status_rank"] = d["status"].map({COMPLIANT: 3, QUESTIONABLE: 2, NON_COMPLIANT: 1})
            d["price"] = d["last_close"]
            d["day_change"] = np.nan
    return stocks, etfs, meta


stocks, etfs, meta = load((_mtime("stocks.csv"), _mtime("etfs.csv"), _mtime("meta.json")))
if stocks.empty and etfs.empty:
    st.error("No data found. Run `python build_data.py` to build the dataset.")
    st.stop()

# Live quotes for the whole universe on every visit (cached for 5 minutes, shared across visitors)
all_tickers = tuple(sorted(set(stocks["ticker"]) | set(etfs["ticker"])))
with st.spinner("Refreshing live market data..."):
    try:
        quotes, quotes_as_of = live.fetch_quotes(all_tickers)
    except Exception:
        quotes, quotes_as_of = pd.DataFrame(), None
stocks = live.apply_quotes(stocks, quotes, is_stock=True)
etfs = live.apply_quotes(etfs, quotes, is_stock=False)
if len(stocks):
    stocks["rating"] = stocks["rating_key"].map(ui.rating_label)
    stocks["rating_strength"] = 6 - stocks["rating_score"]  # higher = more bullish
    stocks = peers.add_derived(stocks)
stock_status = dict(zip(stocks["ticker"], stocks["status"])) if len(stocks) else {}

# Optional auto-refresh: a timer fragment re-runs the whole page about once a minute, which picks up the
# next live-quote fetch (quotes are cached for 60 seconds and shared by all visitors).
st.session_state["last_full_run"] = time.time()
if st.session_state.get("f_autorefresh"):
    @st.fragment(run_every=60)
    def _auto_refresh():
        if time.time() - st.session_state.get("last_full_run", 0) > 50:
            st.rerun(scope="app")

    _auto_refresh()


# ------------------------------------------------------------------------------------------------
# Company page (routed with ?ticker=XYZ so pages can be bookmarked and shared)
# ------------------------------------------------------------------------------------------------
market_state = live.market_state(quotes)
ticker = st.query_params.get("ticker")
page = st.query_params.get("view")

# Top bar on every page: back navigation on the left, site navigation on the right
# content-sized rows (not fixed columns), so labels never wrap however narrow the page gets
bar = st.container(key="topbar", horizontal=True, vertical_alignment="center")
left = bar.container(key="topbar_left", horizontal=True, vertical_alignment="center")
right = bar.container(key="topbar_right", horizontal=True, horizontal_alignment="right",
                      vertical_alignment="center")
if ticker:
    prev = nav.back_target()
    back_label = "← Back" if MOBILE else (f"← Back to {prev}" if prev else "← Back to screener")
    left.button(back_label, on_click=nav.go_back, type="tertiary")
right.button("Screener", on_click=nav.go_home, type="tertiary", icon=":material/table_view:",
             disabled=not (ticker or page))
right.button("Methodology", on_click=nav.go_methodology, type="tertiary", icon=":material/menu_book:",
             disabled=page == "methodology" and not ticker)

if page == "methodology" and not ticker:
    methodology.render(meta, stocks, etfs, market_state, quotes_as_of)
    st.stop()

if ticker:
    ticker = ticker.upper()
    row = None
    for d in (stocks, etfs):
        if len(d) and ticker in set(d["ticker"]):
            row = d[d["ticker"] == ticker].iloc[0]
    company.render(ticker, row, stock_status, stocks)
    st.divider()
    st.caption("For information and education only. Not a fatwa and not investment advice.")
    st.stop()


# ------------------------------------------------------------------------------------------------
# Screener configuration
# ------------------------------------------------------------------------------------------------
# The home page keeps to a few headline figures; every other ratio lives on the company page.
STOCK_COLUMNS = ["sector", "market_cap", "price", "day_change", "last_close", "pe", "dividend_yield", "target_mean",
                 "upside", "rating", "ex_div_date", "reason"]
ETF_COLUMNS = ["category", "aum", "expense_ratio", "price", "day_change", "dividend_yield", "return_1y",
               "ex_div_date", "reason"]
STOCK_SORTS = {
    "Market cap": "market_cap", "Day change": "day_change", "Dividend yield": "dividend_yield", "P/E ratio": "pe",
    "Analyst upside": "upside", "Analyst rating": "rating_strength", "Mean price target": "target_mean",
    "Price": "price", "Ex-dividend date": "ex_div_date", "Shariah status": "status_rank",
    "Company name": "name", "Ticker": "ticker",
}
ETF_SORTS = {
    "Assets under management": "aum", "Day change": "day_change", "Dividend yield": "dividend_yield",
    "Expense ratio": "expense_ratio", "1-year return": "return_1y", "Price": "price",
    "Ex-dividend date": "ex_div_date", "Shariah status": "status_rank", "Fund name": "name", "Ticker": "ticker",
}
PCT_COLS = {"upside", "day_change", "dividend_yield", "roe", "roa", "gross_margin", "operating_margin", "net_margin",
            "revenue_growth", "earnings_growth", "return_1y", "debt_ratio", "cash_ratio", "payout_ratio",
            "expense_ratio", "ytd_return", "return_3y", "return_5y", "yield", "financials_weight",
            "noncompliant_weight"}


def column_config():
    nc = st.column_config.NumberColumn
    cfg = {
        "ticker": st.column_config.TextColumn("Ticker", pinned=True, width="small"),
        "name": st.column_config.TextColumn("Name", pinned=not MOBILE, width="medium"),
        # colored status chips, rendered natively (much faster than styling every cell)
        "status": st.column_config.MultiselectColumn(
            "Status" if MOBILE else "Shariah status", width=130, options=STATUSES,
            color=[ui.STATUS_COLORS[s] for s in STATUSES]),
        "reason": st.column_config.TextColumn("Reason", width="large"),
        "sector": "Sector", "industry": "Industry", "category": "Category", "fund_family": "Fund family",
        "business_status": "Business activity",
        "market_cap": nc("Market cap ($B)", format="%.2f"), "aum": nc("AUM ($B)", format="%.2f"),
        "last_close": nc("Last close", format="$%.2f", help="Upside is measured from this close"),
        "price": nc("Price", format="$%.2f", help="Live during market hours, refreshed every minute"),
        "target_mean": nc("Mean target", format="$%.2f"), "target_median": nc("Median target", format="$%.2f"),
        "target_low": nc("Low target", format="$%.2f"), "target_high": nc("High target", format="$%.2f"),
        "rating": "Analyst rating", "rating_score": nc("Rating score", format="%.2f",
                                                        help="1 = Strong Buy, 5 = Strong Sell"),
        "num_analysts": nc("Analysts", format="%d"),
        "div_per_share": nc("Dividend / share", format="$%.2f"), "last_div": nc("Last dividend", format="$%.4f"),
        "ex_div_date": st.column_config.TextColumn("Ex-dividend date"),
        "pe": nc("P/E", format="%.1f"), "forward_pe": nc("Forward P/E", format="%.1f"),
        "peg": nc("PEG", format="%.2f"), "ps": nc("P/S", format="%.2f"), "pb": nc("P/B", format="%.2f"),
        "ev_ebitda": nc("EV/EBITDA", format="%.1f"), "current_ratio": nc("Current ratio", format="%.2f"),
        "debt_to_equity": nc("Debt / equity", format="%.2f"), "beta": nc("Beta", format="%.2f"),
        "low_52w": nc("52-week low", format="$%.2f"), "high_52w": nc("52-week high", format="$%.2f"),
    }
    labels = {"upside": "Upside", "dividend_yield": "Dividend yield", "roe": "ROE", "roa": "ROA",
              "gross_margin": "Gross margin", "operating_margin": "Operating margin", "net_margin": "Net margin",
              "revenue_growth": "Revenue growth", "earnings_growth": "Earnings growth", "return_1y": "1Y return",
              "debt_ratio": "Debt / mkt cap", "cash_ratio": "Cash / mkt cap", "payout_ratio": "Payout ratio",
              "expense_ratio": "Expense ratio", "ytd_return": "YTD return", "return_3y": "3Y avg return",
              "return_5y": "5Y avg return", "yield": "Distribution yield",
              "financials_weight": "Financials weight", "noncompliant_weight": "Non-compliant holdings"}
    for k, v in labels.items():
        cfg[k] = nc(v, format="%.2f%%" if k == "expense_ratio" else "%.1f%%")
    cfg["debt_ratio"] = nc("Debt / mkt cap", format="%.1f%%", help="AAOIFI limit: 30% of 12-month average market cap")
    cfg["cash_ratio"] = nc("Cash / mkt cap", format="%.1f%%", help="AAOIFI limit: 30% of 12-month average market cap")
    cfg["upside"] = nc("Upside", format="%+.1f%%", help="Mean analyst target vs last close")
    cfg["day_change"] = nc("Day change", format="%+.2f%%", help="Change vs the previous close")
    return cfg


CAP_BANDS = {"Mega (over $200B)": (200e9, np.inf), "Large ($10B–$200B)": (10e9, 200e9),
             "Mid ($2B–$10B)": (2e9, 10e9), "Small ($300M–$2B)": (300e6, 2e9), "Micro (under $300M)": (0, 300e6)}


def reset_filters():
    for k in [k for k in st.session_state if isinstance(k, str) and k.startswith("f_") and k != "f_asset"]:
        del st.session_state[k]


# ------------------------------------------------------------------------------------------------
# Header
# ------------------------------------------------------------------------------------------------
h1, h2 = st.columns([5, 1], vertical_alignment="bottom")
h1.markdown(
    '<div class="hs-title">Shariah Stock Screener</div>'
    '<p class="hs-sub">Shariah screening of US-listed stocks and ETFs using the AAOIFI methodology · '
    f'Fundamentals updated {meta.get("updated", "—")}</p>'
    + ui.price_stamp(market_state, quotes_as_of,
                     fallback_date=meta.get("prices_as_of") if quotes_as_of is None else None)
    + ('<div class="hs-muted">Auto-refreshing every minute</div>' if st.session_state.get("f_autorefresh")
       else ""),
    unsafe_allow_html=True,
)


def refresh():
    live.clear_cache()


h2.button("Refresh data", on_click=refresh, icon=":material/refresh:", width="stretch")
st.write("")

asset = st.segmented_control("Asset type", ["Stocks", "ETFs"], key=ui.remember("f_asset", "Stocks"),
                             label_visibility="collapsed") or "Stocks"
is_stock = asset == "Stocks"
df = stocks if is_stock else etfs

# ------------------------------------------------------------------------------------------------
# Sidebar filters
# ------------------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Filters")
    p = "f_s_" if is_stock else "f_e_"
    search = st.text_input("Search", placeholder="Ticker or name", key=p + "search")
    statuses = st.multiselect("Shariah status", STATUSES, key=p + "status", placeholder="All statuses")
    min_yield = st.number_input("Minimum dividend yield (%)", min_value=0.0, max_value=50.0,
                                step=0.5, placeholder="Any", key=ui.remember(p + "yield", None))
    if is_stock:
        min_upside = st.number_input("Minimum analyst upside (%)", min_value=-100.0, max_value=500.0,
                                     step=5.0, placeholder="Any", key=ui.remember(p + "upside", None),
                                     help="Mean analyst price target vs last close")
        st.divider()
        sectors = st.multiselect("Sector", sorted(df["sector"].dropna().unique()), key=p + "sector",
                                 placeholder="All sectors")
        pool = df[df["sector"].isin(sectors)] if sectors else df
        industries = st.multiselect("Industry", sorted(pool["industry"].dropna().unique()), key=p + "industry",
                                    placeholder="All industries")
        caps = st.multiselect("Market cap", list(CAP_BANDS), key=p + "cap", placeholder="All sizes")
        max_pe = st.number_input("Maximum P/E", min_value=1.0, max_value=1000.0, step=5.0, placeholder="Any",
                                 key=ui.remember(p + "pe", None), help="Excludes companies with negative earnings")
        ratings = st.multiselect("Analyst rating", [r for r in ui.RATING_LABELS.values() if r in set(df["rating"])]
                                 + ["No coverage"], key=p + "rating", placeholder="All ratings")
        min_analysts = st.number_input("Minimum number of analysts", min_value=0, max_value=60,
                                       key=ui.remember(p + "analysts", 0))
    else:
        st.divider()
        cats = st.multiselect("Category", sorted(df["category"].dropna().unique()), key=p + "category",
                              placeholder="All categories")
        fams = st.multiselect("Fund family", sorted(df["fund_family"].dropna().unique()), key=p + "family",
                              placeholder="All fund families")
        max_er = st.number_input("Maximum expense ratio (%)", min_value=0.0, max_value=5.0, step=0.05,
                                 key=ui.remember(p + "er", 5.0))
        min_aum = st.selectbox("Minimum AUM", ["Any", "$100M", "$1B", "$10B"], key=p + "aum")
    exchanges = st.multiselect("Exchange", sorted(df["exchange"].dropna().unique()), key=p + "exchange",
                               placeholder="All exchanges")
    payers = st.toggle("Dividend payers only", key=p + "payers")
    st.button("Reset filters", on_click=reset_filters)
    st.divider()
    st.toggle("Auto-refresh prices every minute", key=ui.remember("f_autorefresh", False),
              help="Keeps prices, day change and upside current while the page is open (US market hours)")
    st.caption("Switch between light and dark themes from the ⋮ menu (top right) → Settings.")

view = df
if search:
    s = search.strip().lower()
    view = view[view["ticker"].str.lower().str.startswith(s) | view["name"].fillna("").str.lower().str.contains(s,
                                                                                                             regex=False)]
if statuses:
    view = view[view["status"].isin(statuses)]
if exchanges:
    view = view[view["exchange"].isin(exchanges)]
if payers:
    view = view[view["div_per_share"].fillna(0) > 0]
if min_yield is not None:
    view = view[view["dividend_yield"] >= min_yield / 100]
if is_stock:
    if sectors:
        view = view[view["sector"].isin(sectors)]
    if industries:
        view = view[view["industry"].isin(industries)]
    if caps:
        mask = np.zeros(len(view), bool)
        for c in caps:
            lo, hi = CAP_BANDS[c]
            mask |= view["market_cap"].between(lo, hi, inclusive="left").values
        view = view[mask]
    if ratings:
        view = view[view["rating"].isin(ratings)]
    if min_analysts:
        view = view[view["num_analysts"] >= min_analysts]
    if min_upside is not None:
        view = view[view["upside"] >= min_upside / 100]
    if max_pe is not None:
        view = view[view["pe"].between(0, max_pe, inclusive="right")]
else:
    if cats:
        view = view[view["category"].isin(cats)]
    if fams:
        view = view[view["fund_family"].isin(fams)]
    if max_er < 5:
        view = view[view["expense_ratio"] <= max_er / 100]
    if min_aum != "Any":
        view = view[view["aum"] >= {"$100M": 1e8, "$1B": 1e9, "$10B": 1e10}[min_aum]]

# ------------------------------------------------------------------------------------------------
# Summary metrics
# ------------------------------------------------------------------------------------------------
counts = df["status"].value_counts()
total = len(df)
if MOBILE:
    st.caption("Tap **»** at the top left to search and filter.")
m = st.container(key="grid_kpis").columns(4)
m[0].metric(f"{asset} screened", f"{total:,}", border=True)
for col, s in zip(m[1:], STATUSES):
    n = int(counts.get(s, 0))
    col.metric(s, f"{n:,}", f"{n / total:.0%} of total" if total else None, delta_color="off", border=True)

# ------------------------------------------------------------------------------------------------
# Sort and column controls
# ------------------------------------------------------------------------------------------------
sorts = STOCK_SORTS if is_stock else ETF_SORTS
p = "f_s_" if is_stock else "f_e_"
st.write("")
c1, c2, c3, _ = st.container(key="grid_sort").columns([1.4, 1, 1.4, 2.2])
sort_by = c1.selectbox("Sort by", list(sorts), key=p + "sort")
order = c2.selectbox("Order", ["Descending", "Ascending"], key=p + "order")
then_by = c3.selectbox("Then by", ["None"] + [s for s in sorts if s != sort_by], key=p + "then")

keys = [sorts[sort_by]] + ([sorts[then_by]] if then_by != "None" else [])
asc = [order == "Ascending"] + ([order == "Ascending"] if then_by != "None" else [])
view = view.sort_values(keys, ascending=asc, na_position="last",
                        key=lambda s: s.astype("string").str.lower() if s.name in ("name", "ticker") else s)

# ------------------------------------------------------------------------------------------------
# Results table
# ------------------------------------------------------------------------------------------------
cols = ["ticker", "name", "status"] + (STOCK_COLUMNS if is_stock else ETF_COLUMNS)
if MOBILE:
    # phones: the figures people scan first come right after the ticker; the long name moves further right
    first = ["ticker", "status", "price", "day_change", "dividend_yield"] + (["upside", "pe"] if is_stock else [])
    cols = first + [c for c in cols if c not in first]
table = view[cols].copy()
for c in cols:
    if c in PCT_COLS:
        table[c] = table[c] * 100
for c in ("market_cap", "aum"):
    if c in table:
        table[c] = table[c] / 1e9
if "dividend_yield" in table:
    table["dividend_yield"] = table["dividend_yield"].fillna(0)  # non-payers yield 0%
if "ex_div_date" in table:
    # ISO text keeps header-click sorting chronological and lets missing dates read "—" instead of "None"
    table["ex_div_date"] = pd.to_datetime(table["ex_div_date"], errors="coerce").dt.strftime("%Y-%m-%d") \
        .fillna("—")

st.caption(f"Showing **{len(view):,}** of {total:,} {asset.lower()} · **Click any company** to open its full "
           "profile, financials, ratios and peer comparison. Click a column header to re-sort.")


table["status"] = table["status"].map(lambda s: [s])  # chip column expects a list per cell
event = st.dataframe(
    table,
    hide_index=True,
    height=min(640, 35 * (len(table) + 1) + 3),
    column_config=column_config(),
    on_select="rerun",
    selection_mode=["single-row", "single-cell"],  # clicking any cell opens that company
    key=f"grid_{asset}_{nav.selection_nonce()}",
)
picked = nav.picked_row(event)
if picked is not None:
    nav.open_company(view.iloc[picked]["ticker"])
    st.rerun()

st.download_button("Download results (CSV)", view[cols].to_csv(index=False),
                   f"shariah_{asset.lower()}.csv", "text/csv")

st.divider()
m1, m2 = st.columns([4, 1], vertical_alignment="center")
m1.caption("Screened with the AAOIFI standard: a permissible core business, and interest-bearing debt and cash "
           "each under 30% of the 12-month average market cap. For information and education only; not a fatwa "
           "and not investment advice.")
m2.button("Full methodology", on_click=nav.go_methodology, icon=":material/menu_book:", width="stretch")

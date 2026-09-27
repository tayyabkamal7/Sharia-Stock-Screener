"""Live market quotes for the whole universe, fetched when the app is opened.

Yahoo's batch quote endpoint returns ~250 symbols per request, so all ~11,000 US stocks and ETFs
refresh in roughly 15 seconds. Results are cached for a few minutes and shared by every visitor.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
from yfinance.data import YfData

QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
BATCH = 250
LIVE_TTL = 300  # seconds

RATING_KEYS = [(1.5, "strong_buy"), (2.5, "buy"), (3.5, "hold"), (4.5, "underperform"), (9, "sell")]


def _fetch_batch(symbols):
    data = YfData()
    for _ in range(3):
        try:
            r = data.get_raw_json(QUOTE_URL, params={"symbols": ",".join(symbols)})
            return r.get("quoteResponse", {}).get("result", [])
        except Exception:
            continue
    return []


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def fetch_quotes(tickers):
    batches = [tickers[i:i + BATCH] for i in range(0, len(tickers), BATCH)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [q for batch in pool.map(_fetch_batch, batches) for q in batch]
    if not results:
        return pd.DataFrame(), None
    q = pd.DataFrame(results)
    keep = ["symbol", "regularMarketPrice", "regularMarketPreviousClose", "regularMarketChangePercent",
            "regularMarketTime", "marketState", "marketCap", "trailingPE", "forwardPE", "priceToBook",
            "dividendRate", "trailingAnnualDividendRate", "averageAnalystRating",
            "fiftyTwoWeekHigh", "fiftyTwoWeekLow"]
    q = q.reindex(columns=keep).rename(columns={"symbol": "ticker"})
    as_of = pd.to_datetime(q["regularMarketTime"].max(), unit="s", utc=True) if q["regularMarketTime"].notna().any() \
        else None
    return q, as_of


def _rating(s):
    """'2.2 - Buy' -> (2.2, 'buy')"""
    try:
        score = float(str(s).split(" - ")[0])
    except (TypeError, ValueError):
        return np.nan, None
    if np.isnan(score):
        return np.nan, None
    return score, next(k for lim, k in RATING_KEYS if score < lim)


def apply_quotes(df, quotes, is_stock):
    """Overlay live quote fields onto a screener table and recompute price-dependent columns."""
    if quotes is None or quotes.empty or df.empty:
        return df
    q = quotes.set_index("ticker")
    df = df.copy()
    idx = df["ticker"]

    price = idx.map(q["regularMarketPrice"])
    # During regular trading the latest official close is the previous close; otherwise it's the last price.
    trading = idx.map(q["marketState"]).eq("REGULAR")
    last_close = price.where(~trading, idx.map(q["regularMarketPreviousClose"]))
    df["price"] = price.fillna(df["last_close"])
    df["last_close"] = last_close.fillna(df["last_close"])
    df["day_change"] = idx.map(q["regularMarketChangePercent"]) / 100

    for col, src in (("pe", "trailingPE"), ("forward_pe", "forwardPE"), ("pb", "priceToBook"),
                     ("high_52w", "fiftyTwoWeekHigh"), ("low_52w", "fiftyTwoWeekLow")):
        if col in df:
            df[col] = idx.map(q[src]).fillna(df[col])

    if is_stock:
        df["market_cap"] = idx.map(q["marketCap"]).fillna(df["market_cap"])
        live_div = idx.map(q["dividendRate"]).fillna(idx.map(q["trailingAnnualDividendRate"]))
        df["div_per_share"] = live_div.where(live_div > 0).fillna(df["div_per_share"])
        rating = idx.map(q["averageAnalystRating"]).map(_rating)
        score = rating.map(lambda r: r[0])
        df["rating_score"] = score.fillna(df["rating_score"])
        df["rating_key"] = rating.map(lambda r: r[1]).fillna(df["rating_key"])
        df["upside"] = df["target_mean"] / df["last_close"] - 1

    df["dividend_yield"] = df["div_per_share"] / df["last_close"]
    return df


def format_as_of(ts):
    if ts is None:
        return None
    return ts.tz_convert(ZoneInfo("America/New_York")).strftime("%b %d, %Y %I:%M %p ET")

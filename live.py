"""Live market quotes for the whole universe, fetched when the app is opened.

Yahoo's batch quote endpoint returns ~250 symbols per request, so all ~11,000 US stocks and ETFs
refresh in roughly 15 seconds. Results are cached for a few minutes and shared by every visitor.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st
from yfinance.data import YfData

QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
BATCH = 250
LIVE_TTL = 60  # seconds; one shared fetch per minute however many people are viewing

RATING_KEYS = [(1.5, "strong_buy"), (2.5, "buy"), (3.5, "hold"), (4.5, "underperform"), (9, "sell")]


BACKOFF = 180  # seconds to wait after Yahoo refuses, before trying again
QUOTE_FIELDS = ["symbol", "regularMarketPrice", "regularMarketPreviousClose", "regularMarketChangePercent",
                "regularMarketTime", "marketState", "marketCap", "trailingPE", "forwardPE", "priceToBook",
                "dividendRate", "trailingAnnualDividendRate", "averageAnalystRating",
                "fiftyTwoWeekHigh", "fiftyTwoWeekLow"]


class QuotesUnavailable(Exception):
    pass


@st.cache_resource
def _status():
    """Process-wide state shared by all visitors: when the last fetch failed."""
    return {"failed_at": 0.0}


def _fetch_batch(symbols):
    data = YfData()
    for attempt in range(2):
        try:
            r = data.get_raw_json(QUOTE_URL, params={"symbols": ",".join(symbols)})
            return r.get("quoteResponse", {}).get("result", [])
        except Exception as exc:
            if "RateLimit" in type(exc).__name__ or "Too Many Requests" in str(exc):
                return None  # don't retry into a rate limit
            time.sleep(1 + attempt)
    return []


def fetch_quotes(tickers):
    """Live quotes for all tickers. Raises QuotesUnavailable (never cached) when Yahoo refuses."""
    status = _status()
    if time.time() - status["failed_at"] < BACKOFF:
        raise QuotesUnavailable("backing off after a recent failure")
    try:
        return _fetch_quotes(tickers)
    except QuotesUnavailable:
        status["failed_at"] = time.time()
        raise


def clear_cache():
    _fetch_quotes.clear()
    _status()["failed_at"] = 0.0


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def _fetch_quotes(tickers):
    batches = [tickers[i:i + BATCH] for i in range(0, len(tickers), BATCH)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        chunks = list(pool.map(_fetch_batch, batches))
    results = [q for chunk in chunks if chunk for q in chunk]
    if not results or sum(c is None for c in chunks) > len(chunks) / 2:
        raise QuotesUnavailable("Yahoo Finance returned no quotes")  # exceptions are not cached
    q = pd.DataFrame(results).reindex(columns=QUOTE_FIELDS).rename(columns={"symbol": "ticker"})
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
    q = quotes.reindex(columns=["ticker"] + QUOTE_FIELDS[1:]).set_index("ticker")
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


def market_state(quotes):
    """Most common Yahoo market state across the universe: REGULAR, PRE, POST, POSTPOST, PREPRE or CLOSED."""
    if quotes is None or quotes.empty or "marketState" not in quotes:
        return None
    states = quotes["marketState"].dropna()
    return states.mode().iloc[0] if len(states) else None


def format_as_of(ts):
    if ts is None:
        return None
    return ts.tz_convert(ZoneInfo("America/New_York")).strftime("%b %d, %Y %I:%M %p ET")

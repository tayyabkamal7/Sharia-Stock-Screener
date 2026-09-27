"""Build the screener dataset for every US-listed stock and ETF.

Pipeline
  1. Universe  - all NASDAQ / NYSE / NYSE American / Arca / Cboe listings from the NASDAQ Trader
                 symbol directory (warrants, rights, units, preferreds, notes and test issues removed).
  2. Fundamentals - per-ticker Yahoo Finance data (profile, balance sheet, ratios, analyst targets,
                 ETF holdings). ~11,000 tickers is too many for one pass without rate limiting, so this
                 step is incremental: each run fetches never-seen tickers first, then the stalest ones,
                 until the time budget runs out. Results are cached in data/fundamentals.csv.
  3. Prices    - daily bulk download for every ticker: last close, 12-month average price,
                 1-year return and dividends paid in the last 12 months.
  4. Screening - AAOIFI rules (screening.py), then data/stocks.csv and data/etfs.csv are written.

Usage
    python build_data.py                  # default 150-minute fundamentals budget
    python build_data.py --minutes 30     # shorter run (the next run continues where this stopped)
    python build_data.py --limit 200      # quick test on the first 200 tickers
"""

import argparse
import io
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from screening import screen_etf, screen_stock

DATA = Path(__file__).parent / "data"
HEADERS = {"User-Agent": "Mozilla/5.0 (halal-stock-screener)"}
SYMBOL_FILES = {
    "nasdaq": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "other": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
}
EXCHANGES = {"N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
EXCLUDE_NAME = re.compile(
    r"\bwarrants?\b|\brights?\b|\bunits?\b|preferred|\bpfd\b|\bnotes? due\b|debenture|subordinated"
    r"|senior notes|% notes|trust preferred|when issued|\bcontingent value\b",
    re.I,
)

STOCK_FIELDS = {
    "longName": "name", "sector": "sector", "industry": "industry", "country": "country",
    "marketCap": "market_cap", "sharesOutstanding": "shares", "totalDebt": "total_debt",
    "totalCash": "total_cash", "totalRevenue": "revenue",
    "trailingPE": "pe", "forwardPE": "forward_pe", "priceToBook": "pb",
    "priceToSalesTrailing12Months": "ps", "enterpriseToEbitda": "ev_ebitda", "trailingPegRatio": "peg",
    "returnOnEquity": "roe", "returnOnAssets": "roa", "grossMargins": "gross_margin",
    "operatingMargins": "operating_margin", "profitMargins": "net_margin",
    "revenueGrowth": "revenue_growth", "earningsGrowth": "earnings_growth",
    "currentRatio": "current_ratio", "debtToEquity": "debt_to_equity", "beta": "beta",
    "recommendationKey": "rating_key", "recommendationMean": "rating_score",
    "numberOfAnalystOpinions": "num_analysts", "targetMeanPrice": "target_mean",
    "targetMedianPrice": "target_median", "targetHighPrice": "target_high", "targetLowPrice": "target_low",
    "dividendRate": "dividend_rate", "exDividendDate": "ex_div_ts", "payoutRatio": "payout_ratio",
    "fiftyTwoWeekHigh": "high_52w", "fiftyTwoWeekLow": "low_52w",
    # extra fields for relative valuation and peer comparison
    "enterpriseValue": "enterprise_value", "enterpriseToRevenue": "ev_revenue", "ebitda": "ebitda",
    "freeCashflow": "fcf", "operatingCashflow": "ocf", "trailingEps": "eps", "forwardEps": "forward_eps",
    "bookValue": "bvps", "quickRatio": "quick_ratio", "ebitdaMargins": "ebitda_margin",
    "heldPercentInsiders": "insiders_pct", "heldPercentInstitutions": "institutions_pct",
    "fullTimeEmployees": "employees", "fiveYearAvgDividendYield": "div_yield_5y",
    "earningsQuarterlyGrowth": "earnings_q_growth",
}
ETF_FIELDS = {
    "longName": "name", "category": "category", "fundFamily": "fund_family", "totalAssets": "aum",
    "netExpenseRatio": "expense_ratio", "yield": "yield", "ytdReturn": "ytd_return",
    "threeYearAverageReturn": "return_3y", "fiveYearAverageReturn": "return_5y", "beta3Year": "beta",
    "exDividendDate": "ex_div_ts", "fiftyTwoWeekHigh": "high_52w", "fiftyTwoWeekLow": "low_52w",
}


# ----------------------------------------------------------------------------------------------
# 1. Universe
# ----------------------------------------------------------------------------------------------
def load_universe():
    frames = []
    for source, url in SYMBOL_FILES.items():
        df = pd.read_csv(io.StringIO(requests.get(url, headers=HEADERS, timeout=60).text), sep="|")
        df = df[~df.iloc[:, 0].astype(str).str.startswith("File Creation")]
        if source == "nasdaq":
            df = df.rename(columns={"Symbol": "symbol"})
            df["exchange"] = "NASDAQ"
        else:
            df = df.rename(columns={"ACT Symbol": "symbol"})
            df["exchange"] = df["Exchange"].map(EXCHANGES).fillna("Other")
        frames.append(df[["symbol", "Security Name", "ETF", "Test Issue", "exchange"]])

    u = pd.concat(frames).dropna(subset=["symbol"])
    u = u[(u["Test Issue"] == "N") & ~u["symbol"].str.contains(r"[\$\^]")]
    u = u[~u["Security Name"].fillna("").str.contains(EXCLUDE_NAME)]
    # Class shares like BRK.B are BRK-B on Yahoo; .W/.U/.R suffixes are warrants/units/rights.
    u = u[~u["symbol"].str.contains(r"\.(?:W|WS|U|R|RT)$")]
    u["ticker"] = u["symbol"].str.replace(".", "-", regex=False)
    u["type"] = u["ETF"].map({"Y": "ETF", "N": "Stock"})
    u = u.rename(columns={"Security Name": "listing_name"})
    return u.drop_duplicates("ticker")[["ticker", "listing_name", "type", "exchange"]].reset_index(drop=True)


# ----------------------------------------------------------------------------------------------
# 2. Fundamentals (incremental)
# ----------------------------------------------------------------------------------------------
_pause_until = 0.0
_pause_total = 0.0
_rl_events = 0
_pause_lock = threading.Lock()


def _wait_for_rate_limit():
    while time.time() < _pause_until:
        time.sleep(1)


def _rate_limited():
    """Yahoo is throttling us: pause every worker, backing off harder on repeated limits."""
    global _pause_until, _pause_total, _rl_events
    with _pause_lock:
        if time.time() < _pause_until:  # another worker already started a pause
            return
        seconds = min(120 * 2 ** _rl_events, 900)
        _rl_events += 1
        _pause_total += seconds
        _pause_until = time.time() + seconds
        print(f"  rate limited by Yahoo; pausing {seconds // 60} min")


def _is_rate_limit(exc):
    msg = f"{type(exc).__name__} {exc}"
    return "RateLimit" in msg or "Too Many Requests" in msg or "429" in msg


def fetch_one(ticker, kind, retries=3):
    for attempt in range(retries):
        _wait_for_rate_limit()
        time.sleep(0.25 + random.random() * 0.5)  # stay well under Yahoo's request rate
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            if not info.get("quoteType"):
                return {"ticker": ticker, "fetch_ok": False}
            fields = ETF_FIELDS if kind == "ETF" else STOCK_FIELDS
            row = {"ticker": ticker, "fetch_ok": True, "quote_type": info.get("quoteType")}
            row.update({new: info.get(old) for old, new in fields.items()})
            if kind == "ETF":
                try:
                    fd = t.funds_data
                    th = fd.top_holdings
                    row["top_holdings"] = json.dumps(
                        [[str(s), round(float(w), 5)] for s, w in th["Holding Percent"].items()]
                    ) if th is not None and len(th) else None
                    sw = fd.sector_weightings or {}
                    row["financials_weight"] = sw.get("financial_services")
                    row["sector_weights"] = json.dumps({k: round(float(v), 4) for k, v in sw.items()})
                except Exception:
                    row["top_holdings"] = None
            return row
        except Exception as exc:
            if _is_rate_limit(exc):
                _rate_limited()
            elif "404" in str(exc) or "Not Found" in str(exc):
                return {"ticker": ticker, "fetch_ok": False}
            time.sleep(2 ** attempt + random.random())
    return None  # not cached, so it's retried on the next run


def build_queue(universe, cache, max_age_hours):
    """Tickers to fetch: never-fetched first, then those older than max_age_hours, stalest first."""
    queue = universe[["ticker", "type"]].merge(cache[["ticker", "fetched_at"]], on="ticker", how="left")
    age = pd.Timestamp.now(tz="UTC") - pd.to_datetime(queue["fetched_at"], utc=True)
    queue = queue[queue["fetched_at"].isna() | (age > pd.Timedelta(hours=max_age_hours))]
    return queue.sort_values("fetched_at", na_position="first")


def update_fundamentals(universe, minutes, workers, limit, max_age_hours=20):
    path = DATA / "fundamentals.csv"
    cache = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["ticker", "fetched_at"])
    cache = cache[cache["ticker"].isin(universe["ticker"])]

    queue = build_queue(universe, cache, max_age_hours)
    if limit:
        queue = queue.head(limit)
    todo = list(queue.itertuples(index=False))
    print(f"Fundamentals: {queue['fetched_at'].isna().sum()} new, {queue['fetched_at'].notna().sum()} stale, "
          f"{len(cache)} cached; budget {minutes} min")

    deadline = time.time() + minutes * 60
    rows, done = [], 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {}
        it = iter(todo)
        for _ in range(workers * 2):
            item = next(it, None)
            if item:
                pending[pool.submit(fetch_one, item.ticker, item.type)] = item.ticker
        while pending:
            fut = next(as_completed(pending))
            pending.pop(fut)
            result = fut.result()
            if result:
                result["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                rows.append(result)
            done += 1
            if done % 250 == 0:
                print(f"  {done}/{len(todo)} fetched")
                _save_cache(cache, rows, path)
            if _pause_total > 40 * 60 and done % 50 == 0:
                print("  Yahoo keeps rate limiting; stopping early (the next run resumes from here)")
                deadline = 0
            if time.time() < deadline:
                item = next(it, None)
                if item:
                    pending[pool.submit(fetch_one, item.ticker, item.type)] = item.ticker
    cache = _save_cache(cache, rows, path)
    print(f"Fundamentals: fetched {len(rows)} this run; {len(cache)} tickers cached")
    return cache


def _save_cache(cache, rows, path):
    if rows:
        new = pd.DataFrame(rows)
        cache = pd.concat([cache[~cache["ticker"].isin(new["ticker"])], new], ignore_index=True)
    DATA.mkdir(exist_ok=True)
    cache.to_csv(path, index=False)
    return cache


# ----------------------------------------------------------------------------------------------
# 3. Prices and dividends (bulk, every run)
# ----------------------------------------------------------------------------------------------
def fetch_prices(tickers, chunk=400):
    out = []
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        for attempt in range(3):
            try:
                raw = yf.download(batch, period="1y", interval="1d", actions=True, auto_adjust=False,
                                  progress=False, threads=True, group_by="column")
                break
            except Exception as exc:
                print(f"  price batch {i} failed ({exc}); retrying")
                time.sleep(30 * (attempt + 1))
        else:
            continue
        close = raw["Close"]
        divs = raw["Dividends"] if "Dividends" in raw.columns.get_level_values(0) else None
        for t in close.columns:
            s = close[t].dropna()
            if len(s) < 2:
                continue
            row = {"ticker": t, "last_close": s.iloc[-1], "last_close_date": s.index[-1].strftime("%Y-%m-%d"),
                   "avg_price_1y": s.mean(), "return_1y": s.iloc[-1] / s.iloc[0] - 1 if len(s) > 200 else None}
            if divs is not None and t in divs.columns:
                d = divs[t].fillna(0)
                d = d[d > 0]
                if len(d):
                    row.update(div_ttm=d.sum(), last_div=d.iloc[-1], last_ex_div=d.index[-1].strftime("%Y-%m-%d"))
            out.append(row)
        print(f"  prices {min(i + chunk, len(tickers))}/{len(tickers)}")
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------------------------
# 4. Assemble and screen
# ----------------------------------------------------------------------------------------------
def _ex_div_date(row):
    """Upcoming/most recent ex-dividend date: Yahoo's announced date if newer, else last paid."""
    ts = row.get("ex_div_ts")
    announced = pd.to_datetime(ts, unit="s") if pd.notna(ts) else None
    # Yahoo keeps decades-old dates for companies that stopped paying; ignore anything over ~13 months old.
    if announced is not None and announced < pd.Timestamp.now() - pd.Timedelta(days=400):
        announced = None
    announced = announced.strftime("%Y-%m-%d") if announced is not None else None
    last = row.get("last_ex_div") if pd.notna(row.get("last_ex_div")) else None
    return max(filter(None, [announced, last]), default=None)


def assemble(universe, fundamentals, prices):
    df = universe.merge(fundamentals, on="ticker", how="inner").merge(prices, on="ticker", how="left")
    df = df[df["fetch_ok"].astype(bool)]
    df["name"] = df["name"].fillna(df["listing_name"])
    df["ex_div_date"] = df.apply(_ex_div_date, axis=1)
    df["upside"] = df["target_mean"] / df["last_close"] - 1 if "target_mean" in df else None

    stocks = df[(df["type"] == "Stock") & (df["quote_type"] == "EQUITY")].copy()
    etfs = df[(df["type"] == "ETF") & (df["quote_type"] == "ETF")].copy()

    # ---- stocks ----
    stocks["market_cap"] = stocks["market_cap"].fillna(stocks["shares"] * stocks["last_close"])
    stocks["avg_market_cap"] = (stocks["avg_price_1y"] * stocks["shares"]).fillna(stocks["market_cap"])
    stocks["div_per_share"] = stocks["dividend_rate"].fillna(stocks["div_ttm"])
    stocks["dividend_yield"] = stocks["div_per_share"] / stocks["last_close"]
    res = stocks.apply(lambda r: screen_stock(r["ticker"], r["industry"], r["total_debt"],
                                              r["total_cash"], r["avg_market_cap"]), axis=1)
    stocks = pd.concat([stocks, pd.DataFrame(list(res), index=stocks.index)], axis=1)

    # ---- ETFs (holdings are checked against the stock results) ----
    stock_status = dict(zip(stocks["ticker"], stocks["status"]))
    etfs["div_per_share"] = etfs["div_ttm"]
    etfs["dividend_yield"] = etfs["div_ttm"] / etfs["last_close"]
    res = etfs.apply(lambda r: screen_etf(r["name"], r["fund_family"], r["category"],
                                          r.get("top_holdings"), r.get("financials_weight"), stock_status), axis=1)
    etfs = pd.concat([etfs, pd.DataFrame(list(res), index=etfs.index)], axis=1)
    return stocks, etfs


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--minutes", type=float, default=150, help="time budget for fundamentals")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--limit", type=int, default=0, help="only process N tickers (testing)")
    p.add_argument("--max-age-hours", type=float, default=20,
                   help="re-fetch fundamentals older than this (0 = re-fetch everything)")
    args = p.parse_args()

    DATA.mkdir(exist_ok=True)
    universe = load_universe()
    print(f"Universe: {(universe['type'] == 'Stock').sum()} stocks, {(universe['type'] == 'ETF').sum()} ETFs")
    if args.limit:
        universe = universe.sample(args.limit, random_state=1)

    fundamentals = update_fundamentals(universe, args.minutes, args.workers, args.limit, args.max_age_hours)
    have = universe[universe["ticker"].isin(fundamentals.loc[fundamentals["fetch_ok"].astype(bool), "ticker"])]
    prices = fetch_prices(have["ticker"].tolist())
    stocks, etfs = assemble(universe, fundamentals, prices)

    stocks.sort_values("market_cap", ascending=False).to_csv(DATA / "stocks.csv", index=False)
    etfs.sort_values("aum", ascending=False).to_csv(DATA / "etfs.csv", index=False)
    meta = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "prices_as_of": prices["last_close_date"].max() if len(prices) else None,
        "stocks": int(len(stocks)), "etfs": int(len(etfs)),
        "universe_stocks": int((universe["type"] == "Stock").sum()),
        "universe_etfs": int((universe["type"] == "ETF").sum()),
    }
    (DATA / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"Saved {len(stocks)} stocks and {len(etfs)} ETFs")
    for name, d in (("Stocks", stocks), ("ETFs", etfs)):
        print(f"  {name}: {d['status'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()

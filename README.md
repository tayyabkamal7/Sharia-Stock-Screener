# Halal Stock Screener (US)

A Streamlit web app that screens **every US-listed stock and ETF** (~5,900 stocks and ~5,700 ETFs on NASDAQ,
NYSE, NYSE American, NYSE Arca and Cboe) for Shariah compliance using the **AAOIFI** methodology.
All data comes from Yahoo Finance via `yfinance`.

## Features

- **Screener** for stocks and ETFs. Shows Shariah status, the reason for any non-compliance, sector, market
  cap, last close, P/E, dividend yield, analyst price target and upside, rating and ex-dividend date.
- **Filters:** Shariah status, minimum dividend yield, minimum analyst upside, maximum P/E, sector,
  industry, market cap, analyst rating, number of analysts, exchange, and dividend payers only. ETFs add
  category, fund family, expense ratio and AUM.
- **Sorting:** a primary and a secondary sort key, or click any column header.
- **Company pages** (click any company):
  - *Overview:* candlestick chart with analyst targets, key statistics, key ratios vs industry and sector
    medians, business description, profile and key executives.
  - *Financial statements:* income statement, balance sheet and cash flow, annual and quarterly, with charts.
  - *Ratios:* ~60 ratios across 9 categories (profitability, liquidity, leverage, efficiency, cash flow,
    per share, growth, valuation, Shariah) with history charts.
  - *Relative valuation:* industry or sector peers (closest by market cap, optionally compliant only);
    premium/discount and percentile vs peer, industry and sector medians across 30+ metrics; share prices
    implied by peer multiples; peer table, peer map and ranking chart. Click any peer to drill into it;
    Back retraces the path.
  - *Analysts:* price targets and upside, recommendation trend, rating changes, EPS and revenue estimates.
  - *Ownership:* insider/institutional split, top institutional and fund holders, insider transactions.
  - *Dividends:* per-share amounts, yield, ex-dividend and payment dates, full history.
  - *Shariah compliance:* each AAOIFI test against its limit, interest income test, purification estimate,
    and the compliance trend by year.
- **ETF pages:** fund facts, holdings with each holding's Shariah status, sector weights, dividends.
- **Live data:** every time the app is opened it pulls live quotes for the whole universe (~15 seconds,
  cached for 5 minutes). Company pages are fetched live (cached for 15 minutes).
- Light and dark themes (follows the viewer's system; switch under the top-right menu, then Settings).

## Files

| File | Purpose |
|---|---|
| `app.py` | Screener page, filters, sorting and routing |
| `company.py` | Company and ETF drill-down pages (live data) |
| `relative.py` / `peers.py` | Relative valuation page / peer selection and comparison logic |
| `nav.py` | Page navigation and the Back history |
| `ratios.py` | Ratio engine (profitability, liquidity, leverage, efficiency, cash flow, per share, growth, valuation, Shariah) |
| `live.py` | Live quotes for all tickers on each visit |
| `tests/` | Automated tests (`python -m pytest tests`) |
| `screening.py` | AAOIFI rules for stocks and ETFs. Edit the industry lists and thresholds here |
| `build_data.py` | Builds `data/` (universe, fundamentals, prices, screening) |
| `data/` | Screened dataset the app reads |
| `.github/workflows/refresh-data.yml` | Rebuilds `data/` every weekday after the US close |

## How data stays fresh

| Data | Refreshed |
|---|---|
| Prices, last close, upside, dividend yield, P/E, consensus rating | Live, every time the app is opened (5-minute cache) |
| Company financials, charts, analyst detail, dividends | Live when a company page is opened (15-minute cache) |
| Balance sheets, Shariah ratios, price targets, list of securities | Daily via GitHub Actions |

Yahoo Finance limits request rates, so the daily job fetches fundamentals incrementally: new tickers first,
then the stalest. It stops cleanly if Yahoo throttles it, and the next run continues where it stopped.

## Run locally

```bash
pip install -r requirements.txt
python build_data.py            # first full build takes 1-2 hours; later runs are incremental
streamlit run app.py
```

After editing the rules in `screening.py`, re-screen the cached data without downloading anything:

```bash
python build_data.py --offline
```

## Deploy on Streamlit Community Cloud (free)

1. Create a **public** GitHub repository (for example `halal-screener`) and upload every file in this
   folder, including the `data/`, `.streamlit/` and `.github/` folders.
2. Go to https://share.streamlit.io, sign in with GitHub, click **Create app**, and choose the repo,
   branch `main` and file `app.py`. Under **Advanced settings**, pick Python 3.12. Click **Deploy**.
3. In the GitHub repo, open **Actions**, enable workflows, select **Refresh screening data**, and click
   **Run workflow** once. After that it runs automatically every weekday, and Streamlit picks up
   the new data automatically.

## Disclaimer

For information and education only. Not a fatwa and not investment advice. Verify with a qualified scholar
or a certified Shariah screening service before investing.

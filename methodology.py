"""Methodology page: how Shariah compliance is determined and how current the data is.

The industry lists and thresholds are read from screening.py, so this page always matches the rules in use.
"""

from collections import defaultdict

import pandas as pd
import streamlit as st

import ui
from screening import (CASH_LIMIT, COMPLIANT, DEBT_LIMIT, DOUBTFUL_INDUSTRIES, ETF_TOLERANCE,
                       INTEREST_INCOME_LIMIT, NON_COMPLIANT, PROHIBITED_INDUSTRIES, QUESTIONABLE,
                       SHARIAH_FAMILIES, TICKER_OVERRIDES)


def _table(rows, columns):
    st.dataframe(pd.DataFrame(rows, columns=columns), hide_index=True)


def render(meta, stocks, etfs, market_state, quotes_as_of):
    st.markdown('<div class="hs-title">Methodology</div>'
                '<p class="hs-sub">How Shariah compliance is determined, where the data comes from and how '
                'current it is</p>', unsafe_allow_html=True)
    st.write("")

    contents, body = st.columns([1, 3.2], gap="large")
    with contents:
        ui.section("On this page")
        st.markdown("""
1. [Overview](#overview)
2. [Business activity screen](#business-activity-screen)
3. [Financial ratio screen](#financial-ratio-screen)
4. [How the status is decided](#how-the-status-is-decided)
5. [Extra checks on company pages](#extra-checks-on-company-pages)
6. [ETF screening](#etf-screening)
7. [Data sources and price timing](#data-sources-and-price-timing)
8. [Limitations](#limitations)
""")
    with body:
        _overview(stocks, etfs)
        _business()
        _ratios()
        _status()
        _extra_checks()
        _etfs()
        _data_timing(meta, market_state, quotes_as_of)
        _limitations()


def _overview(stocks, etfs):
    st.header("Overview", anchor="overview")
    st.markdown(f"""
Stocks are screened with the **AAOIFI** methodology (Accounting and Auditing Organization for Islamic
Financial Institutions, *Shari'ah Standard No. 21: Financial Paper*). A company must pass **two tests**:

1. **Business activity:** its core business must be permissible.
2. **Financial ratios:** its interest-bearing debt and its interest-bearing cash and securities must each
   stay below **{DEBT_LIMIT:.0%}** of its market value.
""")
    c = st.columns(3)
    for col, s in zip(c, (COMPLIANT, QUESTIONABLE, NON_COMPLIANT)):
        n_s = int((stocks["status"] == s).sum()) if len(stocks) else 0
        n_e = int((etfs["status"] == s).sum()) if len(etfs) else 0
        col.metric(s, f"{n_s:,} stocks", f"{n_e:,} ETFs", delta_color="off", border=True)


def _business():
    st.header("Business activity screen", anchor="business-activity-screen")
    st.markdown("Each company is classified using its Yahoo Finance industry. Companies whose **core business** "
                "is impermissible are **Non-Compliant**:")
    grouped = defaultdict(list)
    for industry, reason in PROHIBITED_INDUSTRIES.items():
        grouped[reason].append(industry)
    _table([(reason, ", ".join(inds)) for reason, inds in grouped.items()], ["Reason", "Industries"])

    st.markdown("Industries where scholars differ, or where a large share of revenue may be impermissible, are "
                "**Questionable**:")
    _table(list(DOUBTFUL_INDUSTRIES.items()), ["Industry", "Why"])

    st.markdown("Some companies are classified individually because their industry label doesn't reflect "
                "their business:")
    _table([(t, s, r) for t, (s, r) in TICKER_OVERRIDES.items()], ["Ticker", "Status", "Reason"])
    st.caption("All other industries pass the business activity screen.")


def _ratios():
    st.header("Financial ratio screen", anchor="financial-ratio-screen")
    _table([
        ("Interest-bearing debt ÷ market cap", f"under {DEBT_LIMIT:.0%}",
         "Total debt reported on the latest balance sheet"),
        ("Cash + interest-bearing securities ÷ market cap", f"under {CASH_LIMIT:.0%}",
         "Cash, cash equivalents and short-term investments"),
    ], ["Ratio", "Limit", "What is counted"])
    st.markdown("""
- **Market cap** is the **12-month average**: average daily closing price over the past year × shares
  outstanding. This stops a short-term price swing from changing a company's status.
- The cash test counts **all** cash and short-term investments as interest-bearing. That's conservative:
  some cash may earn no interest, but free data doesn't separate the two.
""")


def _status():
    st.header("How the status is decided", anchor="how-the-status-is-decided")
    _table([
        (NON_COMPLIANT, "Fails the business activity screen, or either financial ratio"),
        (QUESTIONABLE, "The business is doubtful (see above), or balance sheet data is unavailable"),
        (COMPLIANT, "Passes the business screen and both ratios"),
    ], ["Status", "When"])
    st.markdown("The **Reason** column in the screener lists every test a company fails, for example "
                "*“Conventional insurance; Debt is 40% of market cap (limit 30%)”*.")


def _extra_checks():
    st.header("Extra checks on company pages", anchor="extra-checks-on-company-pages")
    st.markdown(f"""
These appear in each company's **Shariah compliance** tab. They're informational and don't change the status.

- **Interest income ÷ revenue, under {INTEREST_INCOME_LIMIT:.0%}:** AAOIFI's limit on non-permissible income,
  from the latest annual income statement. It isn't part of the status because many companies don't
  report interest income separately.
- **Dividend purification:** dividend per share × (interest income ÷ revenue). This is the portion of each
  dividend to give away to charity.
- **Compliance trend:** the debt, cash and interest-income ratios for each fiscal year, using each year-end
  market cap.
- **MSCI-style ratios:** debt and cash ÷ total assets (limit 33.33%), for comparison with other methodologies.
""")


def _etfs():
    st.header("ETF screening", anchor="etf-screening")
    _table([
        (COMPLIANT, "Shariah-screened by mandate: the fund name contains “Shariah”, “Islamic” or “Halal”, or the "
                    f"fund family is {', '.join(sorted(SHARIAH_FAMILIES))}"),
        (NON_COMPLIANT, "Bond, treasury, municipal or money-market funds (interest-bearing)"),
        (NON_COMPLIANT, "Allocation and target-date funds (they hold bonds)"),
        (NON_COMPLIANT, "Leveraged or inverse funds (derivatives and borrowing)"),
        (NON_COMPLIANT, "Options, covered-call, buffer and futures strategies"),
        (NON_COMPLIANT, f"Equity funds with more than {ETF_TOLERANCE:.0%} in financial services, or more than "
                        f"{ETF_TOLERANCE:.0%} of the fund in non-compliant stocks among the top holdings"),
        (QUESTIONABLE, "Commodity funds (often hold futures) and crypto funds (scholars differ)"),
        (QUESTIONABLE, "Conventional equity funds whose top holdings pass: the fund itself isn't screened or "
                       "purified by its manager, and its holdings can change at any time"),
    ], ["Status", "Rule"])


def _data_timing(meta, market_state, quotes_as_of):
    st.header("Data sources and price timing", anchor="data-sources-and-price-timing")
    ui.section("Right now")
    st.markdown(ui.price_stamp(market_state, quotes_as_of,
                               fallback_date=meta.get("prices_as_of") if quotes_as_of is None else None),
                unsafe_allow_html=True)
    st.markdown(f"Fundamentals and Shariah screening last updated **{meta.get('updated', '—')}** · "
                f"closing prices in the screened dataset are from **{meta.get('prices_as_of', '—')}**.")
    ui.section("Update schedule")
    _table([
        ("Price, day change, upside, dividend yield, P/E, consensus rating (screener)",
         "Live quotes, fetched at most once a minute", "During US market hours; otherwise the last close"),
        ("Company page price", "Live quote, refreshed every minute", "Stamped under each company's name"),
        ("Company page price chart", "Refreshed every 5 minutes", "Daily bars"),
        ("Financial statements, ratios, analyst detail, ownership", "Fetched live when a company is opened",
         "Cached for up to 6 hours"),
        ("Balance sheets, Shariah ratios, analyst price targets, list of securities",
         "Rebuilt every weekday after the US close (about 6:30 PM ET)", "Fundamentals change quarterly"),
    ], ["Data", "Refreshed", "Notes"])
    st.markdown("""
- **US market hours:** 9:30 AM–4:00 PM Eastern Time, Monday–Friday, excluding exchange holidays. Outside those
  hours the app shows the **last official close**, and each company page says so with its date and time.
- **Extended-hours (pre-market and after-hours) prices aren't used**, so prices and upside always refer to
  regular-session trading.
- **Upside** is measured from the **last close** (mean analyst target ÷ last close − 1), so it doesn't
  jump around during the day.
- **Source:** all data comes from Yahoo Finance via the open-source `yfinance` library. Analyst ratings and
  targets are Yahoo's consensus of contributing analysts. Free quotes are real-time for most US stocks but
  may be slightly delayed for some.
""")


def _limitations():
    st.header("Limitations", anchor="limitations")
    st.markdown("""
1. **The 5% non-permissible income rule is approximated by industry.** A company in a clean industry can still
   earn small impure income, such as interest on its cash; dividend purification addresses this.
2. **Industry labels are broad.** A diversified company with a small prohibited division (for example a retailer
   that sells alcohol) passes unless it's classified individually.
3. **ETF checks use the top holdings only** (usually the largest 10 positions), as reported by Yahoo.
4. **Other standards differ.** S&P, MSCI and Dow Jones Islamic indexes use a 33% limit and sometimes total assets
   instead of market cap, so a stock can be compliant under one standard and not another.

*This screener is for information and education only. It is not a fatwa and not investment advice. Please
verify with a qualified scholar or a certified Shariah screening service before investing.*
""")

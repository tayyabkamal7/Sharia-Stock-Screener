"""AAOIFI (Shari'ah Standard No. 21) style screening rules for stocks and ETFs.

Stocks
  1. Business activity - the core business must be permissible. Free data can't measure the
     "non-permissible income < 5% of revenue" rule directly for every company, so it's approximated
     with Yahoo Finance industry classifications plus per-ticker overrides. (The company page also
     checks interest income / revenue from the income statement.)
  2. Financial ratios, measured against the 12-month average market cap:
       interest-bearing debt / market cap              < 30%
       cash + interest-bearing securities / market cap < 30%

ETFs
  - Funds that are Shariah-screened by mandate (e.g. SP Funds, Wahed) are Compliant.
  - Bond, money-market, leveraged/inverse, options and futures strategies are Non-Compliant.
  - Other equity ETFs are checked against their holdings: meaningful exposure to financials or to
    non-compliant stocks makes them Non-Compliant; otherwise they're Questionable, because a
    conventional fund isn't screened or purified by its manager.

Edit the lists below to match the scholar or methodology you follow.
"""

import json
import math
import re

DEBT_LIMIT = 0.30
CASH_LIMIT = 0.30
INTEREST_INCOME_LIMIT = 0.05
ETF_TOLERANCE = 0.05  # max fund weight allowed in financials / non-compliant holdings

COMPLIANT = "Compliant"
QUESTIONABLE = "Questionable"
NON_COMPLIANT = "Non-Compliant"
STATUSES = [COMPLIANT, QUESTIONABLE, NON_COMPLIANT]

# ------------------------------------------------------------------------------------------------
# Stock business-activity rules
# ------------------------------------------------------------------------------------------------
PROHIBITED_INDUSTRIES = {
    "Banks - Diversified": "Conventional banking (interest-based)",
    "Banks - Regional": "Conventional banking (interest-based)",
    "Credit Services": "Interest-based lending",
    "Mortgage Finance": "Interest-based mortgage lending",
    "Capital Markets": "Conventional investment banking and brokerage",
    "Financial Conglomerates": "Conventional financial services",
    "Insurance - Life": "Conventional insurance",
    "Insurance - Property & Casualty": "Conventional insurance",
    "Insurance - Diversified": "Conventional insurance",
    "Insurance - Reinsurance": "Conventional insurance",
    "Insurance - Specialty": "Conventional insurance",
    "Insurance Brokers": "Conventional insurance",
    "REIT - Mortgage": "Interest-based real estate lending",
    "Shell Companies": "Blank-check company holding interest-bearing trust assets",
    "Beverages - Brewers": "Alcohol production",
    "Beverages - Wineries & Distilleries": "Alcohol production",
    "Tobacco": "Tobacco products",
    "Gambling": "Gambling",
    "Resorts & Casinos": "Casino and gambling operations",
}

DOUBTFUL_INDUSTRIES = {
    "Asset Management": "Manages conventional, interest-bearing funds",
    "Financial Data & Stock Exchanges": "Revenue tied to conventional finance",
    "Aerospace & Defense": "Weapons manufacturing (scholars differ)",
    "Entertainment": "Music and film content (scholars differ)",
    "Lodging": "Hotels commonly serve alcohol",
}

TICKER_OVERRIDES = {
    "HRL": (NON_COMPLIANT, "Major pork products business"),
    "TSN": (QUESTIONABLE, "Significant pork processing segment"),
}


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _ratio(numerator, denominator):
    n, d = _num(numerator), _num(denominator)
    if d is None or d <= 0:
        return None
    return (n or 0.0) / d


def business_screen(ticker, industry):
    """Return (status, reason) for the business-activity test."""
    if ticker in TICKER_OVERRIDES:
        return TICKER_OVERRIDES[ticker]
    if not isinstance(industry, str) or not industry:
        return QUESTIONABLE, "Business activity unknown"
    if industry in PROHIBITED_INDUSTRIES:
        return NON_COMPLIANT, PROHIBITED_INDUSTRIES[industry]
    if industry in DOUBTFUL_INDUSTRIES:
        return QUESTIONABLE, DOUBTFUL_INDUSTRIES[industry]
    return COMPLIANT, ""


def screen_stock(ticker, industry, total_debt, total_cash, market_cap):
    debt_ratio = _ratio(total_debt, market_cap)
    cash_ratio = _ratio(total_cash, market_cap)
    biz_status, biz_reason = business_screen(ticker, industry)

    fails, doubts = [], []
    if biz_status == NON_COMPLIANT:
        fails.append(biz_reason)
    elif biz_status == QUESTIONABLE:
        doubts.append(biz_reason)
    if debt_ratio is None or cash_ratio is None:
        doubts.append("Balance sheet data unavailable")
    if debt_ratio is not None and debt_ratio >= DEBT_LIMIT:
        fails.append(f"Debt is {debt_ratio:.0%} of market cap (limit 30%)")
    if cash_ratio is not None and cash_ratio >= CASH_LIMIT:
        fails.append(f"Cash and securities are {cash_ratio:.0%} of market cap (limit 30%)")

    if fails:
        status, reason = NON_COMPLIANT, "; ".join(fails)
    elif doubts:
        status, reason = QUESTIONABLE, "; ".join(doubts)
    else:
        status, reason = COMPLIANT, "Passes business and financial ratio tests"

    return {
        "debt_ratio": debt_ratio,
        "cash_ratio": cash_ratio,
        "business_status": biz_status,
        "debt_pass": None if debt_ratio is None else debt_ratio < DEBT_LIMIT,
        "cash_pass": None if cash_ratio is None else cash_ratio < CASH_LIMIT,
        "status": status,
        "reason": reason,
    }


# ------------------------------------------------------------------------------------------------
# ETF rules
# ------------------------------------------------------------------------------------------------
SHARIAH_FUND = re.compile(r"shari'?a|islamic|halal", re.I)
SHARIAH_FAMILIES = {"SP Funds", "Wahed Invest", "Wahed"}

ETF_CATEGORY_RULES = [
    (re.compile(r"bond|treasur|government|muni|credit|corporate|money market|inflation|ultrashort|"
                r"high yield|bank loan|preferred|mortgage|securitized|fixed income|target maturity", re.I),
     NON_COMPLIANT, "Fixed-income fund (interest-bearing)"),
    (re.compile(r"allocation|target.?date|retirement", re.I),
     NON_COMPLIANT, "Allocation fund that holds bonds"),
    (re.compile(r"leveraged|inverse", re.I),
     NON_COMPLIANT, "Leveraged or inverse fund (derivatives and borrowing)"),
    (re.compile(r"options|derivative income|defined outcome|trading--misc|managed futures|"
                r"systematic trend|macro trading|multialternative|event driven|volatility", re.I),
     NON_COMPLIANT, "Options, futures or other derivatives strategy"),
    (re.compile(r"^financial$", re.I),
     NON_COMPLIANT, "Invests in conventional financial companies"),
    (re.compile(r"commodit", re.I),
     QUESTIONABLE, "Commodity exposure, often through futures"),
    (re.compile(r"digital assets", re.I),
     QUESTIONABLE, "Crypto assets (scholars differ)"),
]
ETF_NAME_RULES = [
    (re.compile(r"\b(2x|3x|ultra|leveraged|inverse|bear|short)\b", re.I),
     NON_COMPLIANT, "Leveraged or inverse fund (derivatives and borrowing)"),
    (re.compile(r"\bbond|treasury|t-bill|fixed income|floating rate|\bclo\b|\bmbs\b", re.I),
     NON_COMPLIANT, "Fixed-income fund (interest-bearing)"),
    (re.compile(r"covered call|buffer|option income|premium income|put ?write", re.I),
     NON_COMPLIANT, "Options-based strategy"),
]


def screen_etf(name, fund_family, category, top_holdings, financials_weight, stock_status):
    name = name if isinstance(name, str) else ""
    category = category if isinstance(category, str) else ""

    def out(status, reason, nc_weight=None):
        return {"status": status, "reason": reason, "noncompliant_weight": nc_weight}

    if SHARIAH_FUND.search(name) or fund_family in SHARIAH_FAMILIES:
        return out(COMPLIANT, "Shariah-screened fund by mandate")

    for pattern, status, reason in ETF_CATEGORY_RULES:
        if pattern.search(category):
            return out(status, reason)
    for pattern, status, reason in ETF_NAME_RULES:
        if pattern.search(name):
            return out(status, reason)

    fin = _num(financials_weight)
    holdings = []
    if isinstance(top_holdings, str) and top_holdings:
        try:
            holdings = json.loads(top_holdings)
        except ValueError:
            holdings = []

    bad = [(s, w) for s, w in holdings if stock_status.get(str(s).replace(".", "-")) == NON_COMPLIANT]
    bad_weight = sum(w for _, w in bad)
    if fin is not None and fin > ETF_TOLERANCE:
        return out(NON_COMPLIANT, f"{fin:.0%} of the fund is in financial services (banks, insurers)", bad_weight)
    if bad_weight > ETF_TOLERANCE:
        names = ", ".join(s for s, _ in sorted(bad, key=lambda x: -x[1])[:3])
        return out(NON_COMPLIANT, f"Top holdings include non-compliant stocks ({names}: {bad_weight:.0%} of fund)",
                   bad_weight)
    if not holdings and fin is None:
        return out(QUESTIONABLE, "Holdings data unavailable")
    return out(QUESTIONABLE, "Top holdings pass, but the fund isn't Shariah-screened or purified", bad_weight)

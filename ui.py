"""Shared styling and number formatting."""

import math
import re

import pandas as pd
import streamlit as st

from screening import COMPLIANT, NON_COMPLIANT, QUESTIONABLE

STATUS_COLORS = {COMPLIANT: "#16A34A", QUESTIONABLE: "#D97706", NON_COMPLIANT: "#DC2626"}
STATUS_CLASS = {COMPLIANT: "ok", QUESTIONABLE: "warn", NON_COMPLIANT: "bad"}
RATING_LABELS = {
    "strong_buy": "Strong Buy", "buy": "Buy", "hold": "Hold", "underperform": "Underperform",
    "sell": "Sell", "strong_sell": "Strong Sell",
}

CSS = """
<style>
.block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1480px;}
[data-testid="stSidebar"] .block-container {padding-top: 1.5rem;}
h1, h2, h3 {letter-spacing: -0.01em;}
.hs-title {font-size: 1.7rem; font-weight: 650; line-height: 1.2; margin: 0;}
.hs-sub {font-size: 0.9rem; opacity: 0.68; margin: 0.25rem 0 0 0;}
.hs-section {font-size: 0.78rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;
             opacity: 0.6; margin: 1.1rem 0 0.4rem 0;}
.hs-badge {display: inline-block; padding: 3px 12px; border-radius: 999px; font-size: 0.8rem;
           font-weight: 600; white-space: nowrap; vertical-align: middle;}
.hs-badge.ok {background: rgba(22,163,74,0.14); color: #16A34A;}
.hs-badge.warn {background: rgba(217,119,6,0.15); color: #D97706;}
.hs-badge.bad {background: rgba(220,38,38,0.13); color: #DC2626;}
.hs-reason {font-size: 0.92rem; opacity: 0.85; margin-top: 0.35rem;}
.hs-muted {opacity: 0.62; font-size: 0.85rem;}
.hs-stamp {font-size: 0.84rem; opacity: 0.85; margin: 0.35rem 0 0.2rem 0;}
.hs-kv {display: flex; justify-content: space-between; gap: 1rem; padding: 0.45rem 0;
        border-bottom: 1px solid rgba(128,128,128,0.18); font-size: 0.92rem;}
.hs-kv span:first-child {opacity: 0.7;}
.hs-kv span:last-child {font-weight: 550; text-align: right;}
.hs-pos {color: #16A34A;} .hs-neg {color: #DC2626;}
[data-testid="stMetric"] {padding: 0.7rem 0.9rem;}
[data-testid="stMetricLabel"] p {font-size: 0.8rem; opacity: 0.75;}
[data-testid="stMetricValue"] {font-size: 1.22rem;}
[data-testid="stMetricDelta"] svg {display: none;}
[data-testid="stTabs"] button p {font-size: 0.95rem;}
footer {visibility: hidden;}
.hs-mobile-only {display: none;}
.st-key-topbar button p {white-space: nowrap;}
/* Top bar: Back hugs its text on the left; the nav group takes the rest and right-aligns, all on one line */
.st-key-topbar {flex-wrap: nowrap !important;}
.st-key-topbar > [data-testid="stLayoutWrapper"] {min-width: 0 !important;}
.st-key-topbar > [data-testid="stLayoutWrapper"]:has(> .st-key-topbar_left) {flex: 0 0 auto !important; width: auto !important;}
.st-key-topbar_left {width: auto !important;}
.st-key-topbar > [data-testid="stLayoutWrapper"]:has(> .st-key-topbar_right) {flex: 1 1 0 !important; width: auto !important;}
.st-key-topbar_right {flex-wrap: nowrap !important; justify-content: flex-end !important; width: 100% !important;}

/* ---------- phones ---------- */
@media (max-width: 640px) {
  .block-container {padding: 3.2rem 0.8rem 3rem 0.8rem;}  /* clears Streamlit's fixed top bar */
  .hs-title {font-size: 1.3rem;}
  .hs-sub, .hs-reason {font-size: 0.82rem;}
  .hs-stamp {font-size: 0.76rem;}
  .hs-mobile-only {display: block;}
  /* keep these rows side by side instead of stacking one per line */
  .st-key-topbar [data-testid="stHorizontalBlock"],
  [class*="st-key-grid"] [data-testid="stHorizontalBlock"] {
      flex-direction: row !important; flex-wrap: wrap !important; gap: 0.5rem !important;}
  .st-key-topbar [data-testid="stColumn"] {
      flex: 0 1 auto !important; width: auto !important; min-width: 0 !important;}
  /* metric cards: two per row */
  [class*="st-key-grid"] [data-testid="stColumn"] {
      flex: 1 1 calc(50% - 0.5rem) !important; width: calc(50% - 0.5rem) !important;
      min-width: calc(50% - 0.5rem) !important;}
  [data-testid="stMetric"] {padding: 0.45rem 0.6rem;}
  [data-testid="stMetricLabel"] p {font-size: 0.72rem;}
  [data-testid="stMetricValue"] {font-size: 1.02rem;}
  [data-testid="stMetricDelta"] {font-size: 0.72rem;}
  .hs-kv {font-size: 0.85rem;}
  [data-testid="stTabs"] button p {font-size: 0.85rem;}
}
/* teal accent instead of Streamlit's default red, so red only ever means Non-Compliant */
button[kind="segmented_controlActive"], button[kind="pillsActive"] {
    border-color: #14B8A6 !important; color: #14B8A6 !important; background: rgba(20,184,166,0.10) !important;}
span[data-baseweb="tag"] {background-color: #0F766E !important;}
[data-testid="stTabs"] [aria-selected="true"] p {color: #14B8A6;}
[data-baseweb="tab-highlight"] {background-color: #14B8A6 !important;}
[data-testid="stToggle"] [aria-checked="true"] {background-color: #0F766E !important;}
[data-testid="stSlider"] [role="slider"] {background-color: #14B8A6 !important; box-shadow: none !important;}
[data-testid="stSliderThumbValue"] {color: #14B8A6 !important;}
</style>
"""


def is_mobile():
    """True for phone browsers (from the request's User-Agent)."""
    try:
        ua = st.context.headers.get("User-Agent", "") or ""
    except Exception:
        return False
    return bool(re.search(r"Mobi|Android|iPhone|iPod", ua))


def chart(fig, **kwargs):
    """st.plotly_chart with a tidy toolbar: hidden on phones (it covers the chart), no Plotly logo."""
    config = {"displaylogo": False, "displayModeBar": False if is_mobile() else "hover"}
    if is_mobile():
        fig.update_layout(margin=dict(l=0, r=0), legend=dict(font=dict(size=10)))
    return st.plotly_chart(fig, config=config, **kwargs)


def remember(key, default):
    """Seed a persistent widget setting once and return its key.

    Settings keyed "f_*" are carried across pages (see app.py), so widgets using them must not also pass a
    default/value/index argument, otherwise the display and the stored value can disagree."""
    st.session_state.setdefault(key, default)
    return key


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def badge(status):
    return f'<span class="hs-badge {STATUS_CLASS.get(status, "warn")}">{status}</span>'


def section(label):
    st.markdown(f'<div class="hs-section">{label}</div>', unsafe_allow_html=True)


def kv_rows(pairs):
    html = "".join(f'<div class="hs-kv"><span>{k}</span><span>{v}</span></div>' for k, v in pairs)
    st.markdown(html.replace("$", "&#36;"), unsafe_allow_html=True)  # stop "$...$" rendering as math


ET = "America/New_York"
MARKET_TEXT = {"REGULAR": "Market open", "PRE": "Pre-market", "POST": "After hours",
               "POSTPOST": "Market closed", "PREPRE": "Market closed", "CLOSED": "Market closed"}


def _et(ts):
    """Epoch seconds or a Timestamp -> Timestamp in US Eastern time."""
    if ts is None or (isinstance(ts, float) and math.isnan(ts)):
        return None
    t = pd.Timestamp(ts, unit="s", tz="UTC") if isinstance(ts, (int, float)) else pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.tz_convert(ET)


def price_stamp(state, price_time, checked_at=None, fallback_date=None):
    """One line telling the reader how current the price is.

    state: Yahoo marketState; price_time: time of the price shown (epoch or Timestamp);
    checked_at: when the app fetched it; fallback_date: 'YYYY-MM-DD' of the last close when live data is missing.
    """
    t = _et(price_time)
    is_open = state == "REGULAR"
    dot = "#16A34A" if is_open else "#94A3B8"
    if t is not None and is_open:
        text = f"<b>Market open</b> · live price as of {t:%I:%M %p ET} on {t:%a, %b %d, %Y} · refreshes every minute"
    elif t is not None:
        label = MARKET_TEXT.get(state, "Market closed")
        text = (f"<b>{label}</b> · prices are from the last close on {t:%a, %b %d, %Y} "
                f"(last update {t:%I:%M %p ET})")
        if state in ("PRE", "POST"):
            text += " · extended-hours trading isn't included"
    elif fallback_date:
        text = f"<b>Live prices unavailable</b> · showing closing prices from {pd.Timestamp(fallback_date):%a, %b %d, %Y}"
        dot = "#D97706"
    else:
        return ""
    if checked_at is not None:
        c = _et(checked_at)
        text += f" · checked {c:%I:%M:%S %p ET}"
    return (f'<div class="hs-stamp"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
            f'background:{dot};margin-right:7px;vertical-align:middle"></span>{text}</div>')


def rating_label(key):
    return RATING_LABELS.get(key, "No coverage") if isinstance(key, str) else "No coverage"


# ---------------- number formatting ----------------
def _bad(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or (not isinstance(v, (int, float)) and pd.isna(v))


def money(v, d=2):
    return "—" if _bad(v) else f"${v:,.{d}f}"


def big(v):
    if _bad(v):
        return "—"
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{'-' if v < 0 else ''}${a / div:,.2f}{suf}"
    return f"${v:,.0f}"


def pct(v, d=1, sign=False):
    return "—" if _bad(v) else f"{v:+.{d}%}" if sign else f"{v:.{d}%}"


def mult(v, d=2):
    return "—" if _bad(v) else f"{v:,.{d}f}x"


def num(v, d=2):
    return "—" if _bad(v) else f"{v:,.{d}f}"


def signed_html(v, d=1):
    if _bad(v):
        return "—"
    return f'<span class="{"hs-pos" if v >= 0 else "hs-neg"}">{v:+.{d}%}</span>'

"""Shared styling and number formatting."""

import math

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
/* teal accent instead of Streamlit's default red, so red only ever means Non-Compliant */
button[kind="segmented_controlActive"], button[kind="pillsActive"] {
    border-color: #14B8A6 !important; color: #14B8A6 !important; background: rgba(20,184,166,0.10) !important;}
span[data-baseweb="tag"] {background-color: #0F766E !important;}
[data-testid="stTabs"] [aria-selected="true"] p {color: #14B8A6;}
[data-baseweb="tab-highlight"] {background-color: #14B8A6 !important;}
[data-testid="stToggle"] [aria-checked="true"] {background-color: #0F766E !important;}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def badge(status):
    return f'<span class="hs-badge {STATUS_CLASS.get(status, "warn")}">{status}</span>'


def section(label):
    st.markdown(f'<div class="hs-section">{label}</div>', unsafe_allow_html=True)


def kv_rows(pairs):
    html = "".join(f'<div class="hs-kv"><span>{k}</span><span>{v}</span></div>' for k, v in pairs)
    st.markdown(html.replace("$", "&#36;"), unsafe_allow_html=True)  # stop "$...$" rendering as math


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

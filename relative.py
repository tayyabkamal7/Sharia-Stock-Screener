"""Relative valuation tab: compare a company with its industry/sector peers and drill into any peer."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import nav
import ui
from peers import GROUPS, METRICS, clean, comparison_table, implied_prices, peer_group

TEAL, GREY, UP, DOWN, PURPLE = "#14B8A6", "#94A3B8", "#16A34A", "#DC2626", "#8B5CF6"
STATUS_COLORS = {"Compliant": "#16A34A", "Questionable": "#D97706", "Non-Compliant": "#DC2626"}


def fmt(v, kind):
    if v is None or pd.isna(v):
        return "—"
    if kind == "pct":
        return f"{v:.1%}"
    if kind == "x":
        return f"{v:,.2f}x"
    if kind == "big":
        return ui.big(v)
    if kind == "usd":
        return ui.money(v)
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"


def _assessment(row):
    d, better, group = row["vs peers"], row["better"], METRICS[row["key"]][2]
    if pd.isna(d) or better is None:
        return "—"
    if abs(d) < 0.10:
        return "In line"
    if group == "Valuation" and better == "low":
        return "Premium" if d > 0 else "Discount"
    if group == "Valuation":
        return "Discount" if d > 0 else "Premium"  # higher yield = cheaper
    good = (d > 0) == (better == "high")
    return "Better than peers" if good else "Worse than peers"


def _assessment_color(text):
    return {"Discount": f"color:{UP}", "Better than peers": f"color:{UP}", "Premium": f"color:{DOWN}",
            "Worse than peers": f"color:{DOWN}"}.get(text, "")


def render(ticker, info, row, stocks, last_close):
    if row is None or stocks is None or stocks.empty:
        st.info("Relative valuation is available for companies in the screened dataset.")
        return

    c1, c2, c3 = st.columns([1.4, 2.4, 1.4], vertical_alignment="bottom")
    # peer settings persist across companies, so they stay put while drilling from peer to peer
    by = c1.segmented_control("Peer group", ["Industry", "Sector"], key=ui.remember("f_rv_by", "Industry")) \
        or "Industry"
    n_label = c2.select_slider("Number of peers (closest by market cap)", ["5", "10", "15", "25", "50", "All"],
                               key=ui.remember("f_rv_n", "15"))
    compliant_only = c3.toggle("Shariah-compliant peers only", key=ui.remember("f_rv_c", False))
    n = 0 if n_label == "All" else int(n_label)

    col = by.lower()
    peers = peer_group(stocks, ticker, col, n, compliant_only)
    if peers.empty:
        st.info(f"No comparable companies found in this {col}.")
        return
    industry = stocks[(stocks["industry"] == row.get("industry")) & (stocks["ticker"] != ticker)]
    sector = stocks[(stocks["sector"] == row.get("sector")) & (stocks["ticker"] != ticker)]
    company = row.to_dict()
    st.caption(f"Comparing with **{len(peers)}** {'Shariah-compliant ' if compliant_only else ''}peers in "
               f"**{row.get(col)}** ({by.lower()}). Peer, industry and sector figures are medians; negative "
               "valuation multiples are excluded. Select any peer in the table or chart to open it.")

    # ---- valuation snapshot ----
    snap = comparison_table(company, peers, industry, sector, ["pe", "forward_pe", "ev_ebitda", "ps", "pb"])
    cols = st.columns(len(snap))
    for c, (_, r) in zip(cols, snap.iterrows()):
        delta = f"{r['vs peers']:+.0%} vs peer median {fmt(r['Peer median'], 'x')}" if pd.notna(r["vs peers"]) \
            else f"Peer median {fmt(r['Peer median'], 'x')}"
        c.metric(r["Metric"], fmt(r["Company"], "x"), delta, delta_color="inverse", border=True)

    # ---- implied share price ----
    ui.section("Share price implied by peer multiples")
    fund = {
        "eps": info.get("trailingEps") or company.get("eps"),
        "forward_eps": info.get("forwardEps") or company.get("forward_eps"),
        "revenue": info.get("totalRevenue") or company.get("revenue"),
        "bvps": info.get("bookValue") or company.get("bvps"),
        "ebitda": info.get("ebitda") or company.get("ebitda"),
        "total_debt": info.get("totalDebt") or company.get("total_debt"),
        "total_cash": info.get("totalCash") or company.get("total_cash"),
        "shares": info.get("sharesOutstanding") or company.get("shares"),
    }
    ip = implied_prices(fund, peers)
    if ip.empty:
        st.info("Not enough peer data or company fundamentals to compute implied prices.")
    else:
        left, right = st.columns([2.2, 1], gap="large")
        with left:
            fig = go.Figure()
            fig.add_trace(go.Bar(y=ip["Method"], x=ip["High (75th pct)"] - ip["Low (25th pct)"],
                                 base=ip["Low (25th pct)"], orientation="h", marker_color="rgba(20,184,166,0.35)",
                                 marker_line_color=TEAL, name="25th–75th percentile",
                                 hovertemplate="%{y}: $%{base:,.2f} – $%{x:,.2f}<extra></extra>"))
            fig.add_trace(go.Scatter(y=ip["Method"], x=ip["Median"], mode="markers+text", name="Peer median",
                                     marker=dict(color=TEAL, size=12, symbol="diamond"),
                                     text=[f"${v:,.0f}" for v in ip["Median"]], textposition="top center"))
            if info.get("targetLowPrice") and info.get("targetHighPrice"):
                fig.add_vrect(x0=info["targetLowPrice"], x1=info["targetHighPrice"], fillcolor=PURPLE, opacity=0.08,
                              line_width=0, annotation_text="Analyst target range", annotation_position="bottom left")
            if last_close:
                fig.add_vline(x=last_close, line_dash="dash", line_color=ui.STATUS_COLORS["Non-Compliant"],
                              annotation_text=f"Last close ${last_close:,.2f}", annotation_position="top")
            fig.update_layout(height=80 + 55 * len(ip), margin=dict(l=0, r=10, t=30, b=0), showlegend=False,
                              xaxis=dict(tickprefix="$", rangemode="tozero"), yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, key=f"rv_ff_{ticker}")
        with right:
            fair = ip["Median"].median()
            up = fair / last_close - 1 if last_close else None
            st.metric("Blended implied price", ui.money(fair),
                      f"{up:+.1%} vs last close" if up is not None else None, border=True,
                      help="Median of the peer-median implied prices across all methods")
            if info.get("targetMeanPrice"):
                st.metric("Mean analyst target", ui.money(info["targetMeanPrice"]), border=True)
            st.caption("Bars span the prices implied by the 25th–75th percentile of peer multiples; "
                       "the diamond uses the peer median.")
        shown = ip.copy()
        for c in ("Low (25th pct)", "Median", "High (75th pct)"):
            shown[c] = shown[c].map(ui.money)
        shown["Peer multiple (median)"] = shown["Peer multiple (median)"].map(lambda v: f"{v:,.2f}x")
        with st.expander("Implied price details"):
            st.dataframe(shown, hide_index=True)

    # ---- metric comparison ----
    ui.section("Company vs peers, industry and sector")
    group = st.pills("Metrics", GROUPS, key=ui.remember("f_rv_g", "Valuation"),
                     label_visibility="collapsed") or "Valuation"
    keys = [k for k, m in METRICS.items() if m[2] == group]
    comp = comparison_table(company, peers, industry, sector, keys)
    comp["Assessment"] = comp.apply(_assessment, axis=1)
    disp = pd.DataFrame({
        "Metric": comp["Metric"],
        ticker: [fmt(v, k) for v, k in zip(comp["Company"], comp["kind"])],
        "Peer median": [fmt(v, k) for v, k in zip(comp["Peer median"], comp["kind"])],
        "Industry median": [fmt(v, k) for v, k in zip(comp["Industry median"], comp["kind"])],
        "Sector median": [fmt(v, k) for v, k in zip(comp["Sector median"], comp["kind"])],
        "vs peer median": comp["vs peers"].map(lambda v: "—" if pd.isna(v) else f"{v:+.0%}"),
        "Higher than": comp["Percentile"].map(lambda v: "—" if pd.isna(v) else f"{v:.0f}% of peers"),
        "Assessment": comp["Assessment"],
    })
    st.dataframe(disp.style.map(_assessment_color, subset=["Assessment"]), hide_index=True)

    # ---- peer table (drill-down) ----
    ui.section(f"Peer companies · {group.lower()}")
    table = pd.concat([stocks[stocks["ticker"] == ticker], peers])
    view = table[["ticker", "name", "status", "market_cap"] + [k for k in keys if k != "market_cap"]].copy()
    # pre-formatted text so missing values read "—" (the table is already ordered by market cap)
    for k in view.columns[3:]:
        view[k] = view[k].map(ui.big) if k == "market_cap" else view[k].map(lambda v, kind=METRICS[k][1]: fmt(v, kind))
    formats = {}

    def highlight(r):
        return ["background-color: rgba(20,184,166,0.16); font-weight: 600" if r["ticker"] == ticker else ""] * len(r)

    labels = {k: st.column_config.Column(METRICS[k][0]) for k in keys}
    labels.update({"ticker": st.column_config.Column("Ticker", pinned=True), "name": "Name",
                   "status": "Shariah status", "market_cap": "Market cap"})
    ev = st.dataframe(
        view.style.apply(highlight, axis=1).format(formats)
        .map(lambda s: f"color:{STATUS_COLORS.get(s, 'inherit')}", subset=["status"]),
        hide_index=True, column_config=labels, on_select="rerun", selection_mode="single-row",
        height=min(36 * (len(view) + 1) + 4, 600), key=f"rv_tbl_{nav.selection_nonce()}_{ticker}_{group}_{by}_{n_label}_{compliant_only}")
    if ev.selection.rows:
        target = view.iloc[ev.selection.rows[0]]["ticker"]
        if target != ticker:
            nav.open_company(target)
            st.rerun()

    # ---- peer map ----
    ui.section("Peer map")
    options = [k for k in METRICS if k in stocks]
    c1, c2 = st.columns(2)
    x_key = c1.selectbox("X axis", options, format_func=lambda k: METRICS[k][0], key=ui.remember("f_rv_x", "roe"))
    y_key = c2.selectbox("Y axis", options, format_func=lambda k: METRICS[k][0], key=ui.remember("f_rv_y", "pe"))
    pts = table.assign(_x=clean(table[x_key], x_key), _y=clean(table[y_key], y_key)).dropna(subset=["_x", "_y"])
    if len(pts) < 2:
        st.info("Not enough data for these two metrics.")
    else:
        size = np.sqrt(pts["market_cap"].fillna(0).clip(lower=1))
        size = 12 + 38 * (size - size.min()) / max(size.max() - size.min(), 1)
        fig = go.Figure()
        for status, color in STATUS_COLORS.items():
            s = pts[(pts["status"] == status) & (pts["ticker"] != ticker)]
            if len(s):
                fig.add_trace(go.Scatter(
                    x=s["_x"], y=s["_y"], mode="markers+text", name=status, text=s["ticker"],
                    textposition="top center", customdata=s[["ticker", "name"]].values,
                    marker=dict(size=size[s.index], color=color, opacity=0.55, line=dict(width=1, color="white")),
                    hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]}<br>x: %{x:.3g}<br>y: %{y:.3g}"
                                  "<extra></extra>"))
        me = pts[pts["ticker"] == ticker]
        if len(me):
            fig.add_trace(go.Scatter(x=me["_x"], y=me["_y"], mode="markers+text", name=ticker, text=[ticker],
                                     textposition="top center", customdata=me[["ticker", "name"]].values,
                                     marker=dict(size=24, symbol="star", color=TEAL,
                                                 line=dict(width=1.5, color="white"))))
        for key, axis in ((x_key, "x"), (y_key, "y")):
            med = clean(peers[key], key).median()
            if pd.notna(med):
                (fig.add_vline if axis == "x" else fig.add_hline)(
                    **{axis: med}, line_dash="dot", line_color=GREY, annotation_text="peer median")
        pct_axis = lambda k: dict(tickformat=".0%") if METRICS[k][1] == "pct" else {}
        fig.update_layout(height=480, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.08),
                          xaxis=dict(title=METRICS[x_key][0], **pct_axis(x_key)),
                          yaxis=dict(title=METRICS[y_key][0], **pct_axis(y_key)))
        ev = st.plotly_chart(fig, on_select="rerun", selection_mode="points",
                             key=f"rv_map_{nav.selection_nonce()}_{ticker}_{x_key}_{y_key}_{by}_{n_label}_{compliant_only}")
        points = ev.selection.points if ev and ev.selection else []
        if points and points[0].get("customdata"):
            target = points[0]["customdata"][0]
            if target != ticker:
                nav.open_company(target)
                st.rerun()
        st.caption("Bubble size reflects market cap. Click a bubble to open that company.")

    # ---- ranking ----
    ui.section("Ranking")
    rk = st.selectbox("Rank peers by", options, format_func=lambda k: METRICS[k][0],
                      key=ui.remember("f_rv_rk", "ev_ebitda"))
    r = table.assign(_v=clean(table[rk], rk)).dropna(subset=["_v"])
    if len(r):
        better = METRICS[rk][3]
        r = r.sort_values("_v", ascending=better == "low")
        fig = go.Figure(go.Bar(
            y=r["ticker"], x=r["_v"], orientation="h", customdata=r[["ticker", "name"]].values,
            marker_color=[TEAL if t == ticker else GREY for t in r["ticker"]],
            text=[fmt(v, METRICS[rk][1]) for v in r["_v"]], textposition="outside", cliponaxis=False,
            hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]}<extra></extra>"))
        med = clean(peers[rk], rk).median()
        if pd.notna(med):
            fig.add_vline(x=med, line_dash="dot", line_color=GREY, annotation_text="peer median")
        fig.update_layout(height=max(260, 26 * len(r) + 60), margin=dict(l=0, r=40, t=20, b=0),
                          yaxis=dict(autorange="reversed"),
                          xaxis=dict(tickformat=".0%") if METRICS[rk][1] == "pct" else {})
        ev = st.plotly_chart(fig, on_select="rerun", selection_mode="points",
                             key=f"rv_rank_{nav.selection_nonce()}_{ticker}_{rk}_{by}_{n_label}_{compliant_only}")
        points = ev.selection.points if ev and ev.selection else []
        if points and points[0].get("customdata"):
            target = points[0]["customdata"][0]
            if target != ticker:
                nav.open_company(target)
                st.rerun()
        st.caption(f"Best first ({'lower' if better == 'low' else 'higher'} is better)." if better
                   else "Sorted high to low.")

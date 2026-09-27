"""Page navigation. Company pages are addressed by ?ticker=XYZ; a history stack powers the Back button
when drilling from one company to its peers."""

import streamlit as st


def selection_nonce():
    """Part of every selectable table/chart key. Bumping it after a selection is used gives those widgets a
    fresh (empty) selection, so an old click can't re-trigger navigation when the page is revisited."""
    return st.session_state.setdefault("sel_nonce", 0)


def picked_row(event):
    """Row position chosen in a dataframe with row and/or cell selection, or None."""
    sel = getattr(event, "selection", None) or {}
    rows = sel.get("rows") or []
    if rows:
        return rows[0]
    cells = sel.get("cells") or []
    return cells[0][0] if cells else None


def open_company(ticker):
    current = st.query_params.get("ticker")
    if current and current.upper() != ticker.upper():
        st.session_state.setdefault("nav_history", []).append(current.upper())
    st.session_state["sel_nonce"] = selection_nonce() + 1
    st.query_params["ticker"] = ticker


def back_target():
    history = st.session_state.get("nav_history", [])
    return history[-1] if history else None


def go_back():
    history = st.session_state.get("nav_history", [])
    if history:
        st.query_params["ticker"] = history.pop()
    else:
        go_home()


def go_home():
    st.query_params.clear()
    st.session_state["nav_history"] = []
    st.session_state["sel_nonce"] = selection_nonce() + 1

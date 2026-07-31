"""
Password gate — drop into any Streamlit app.

Usage: put this file beside your app.py, then add two lines near the top of
app.py, immediately after st.set_page_config():

    import auth
    auth.gate()

Then set DM_PASSWORD in that app's Streamlit secrets.

The gate is active only when DM_PASSWORD exists. With no password set it does
nothing at all, so local development and any app you have not configured yet
keep working untouched.
"""

import os

import streamlit as st


def _password():
    """Environment first, then Streamlit secrets. Neither is required."""
    v = os.environ.get("DM_PASSWORD")
    if v:
        return v
    try:
        return st.secrets.get("DM_PASSWORD")
    except Exception:
        return None


def gate(title="Inripe 2026", subtitle="Internal dashboard. Sign in to continue."):
    """Block the app until the right password is entered.

    Call immediately after st.set_page_config(). Everything below the call only
    runs once the session is authenticated, because this stops the script
    otherwise.
    """
    pw = _password()
    if not pw:
        return                       # no password configured: no gate
    if st.session_state.get("_auth_ok"):
        return

    st.markdown("<div style='height:60px'></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown(
            f"<div style='background:linear-gradient(135deg,#1B4F8A,#1A6B4A);"
            f"padding:18px 22px;border-radius:10px;margin-bottom:18px'>"
            f"<div style='color:white;font-size:18px;font-weight:700'>📊 {title}</div>"
            f"<div style='color:#BDD7F5;font-size:12px;margin-top:3px'>{subtitle}</div>"
            f"</div>", unsafe_allow_html=True)
        entry = st.text_input("Password", type="password",
                              label_visibility="collapsed", placeholder="Password")
        if st.button("Open dashboard", use_container_width=True):
            if entry == pw:
                st.session_state["_auth_ok"] = True
                st.rerun()
            else:
                st.error("That password is not correct.")
    st.stop()

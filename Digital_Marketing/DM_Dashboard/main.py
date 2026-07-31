"""
INRIPE DM DASHBOARD — unified entry point

One app, two views: Tracking and Planning. This file owns everything that can
only exist once per Streamlit app — page config, the access gate, and the view
switcher — then hands off to the view module for whichever tab is selected.

Why a radio switcher rather than st.tabs
----------------------------------------
st.tabs renders the contents of every tab on every rerun, so with two full
dashboards each click would build both. The switcher renders only the view being
looked at. It reads the same and does half the work.

Layout
------
    main.py             this file: config, gate, switcher
    tracking_view.py    render() draws the tracking dashboard
    planning_view.py    render() draws the planning dashboard
    dm_engine.py        all tracking arithmetic
    sharepoint_loader.py    live workbook from SharePoint
    audit_v7.py         run before every deploy
"""

import os

import streamlit as st

st.set_page_config(page_title="Inripe DM Dashboard 2026", page_icon="📊",
                   layout="wide")

VIEWS = {
    "Tracking": ("tracking_view", "Plan vs actual · pacing · allocation · comparison"),
    "Planning": ("planning_view", "Channel plan · budget allocation · capacity"),
}
DEFAULT_VIEW = "Tracking"

st.markdown("""
<style>
[data-testid="stAppViewContainer"]{background:#F8F9FA}
[data-testid="stSidebar"]{display:none}
div[role="radiogroup"]{gap:6px}
div[role="radiogroup"] label{
    background:white;border:0.5px solid #e2e4e8;border-radius:8px;
    padding:7px 20px;margin:0;font-weight:600;font-size:13.5px;
    box-shadow:0 1px 3px rgba(0,0,0,0.04);cursor:pointer}
div[role="radiogroup"] label:has(input:checked){
    background:#1B4F8A;border-color:#1B4F8A;color:white}
div[role="radiogroup"] label:has(input:checked) p{color:white}
div[role="radiogroup"] input{display:none}
.app-head{background:linear-gradient(135deg,#1B4F8A 0%,#1A6B4A 100%);
    padding:15px 24px;border-radius:10px;margin-bottom:14px;
    display:flex;justify-content:space-between;align-items:center}
</style>
""", unsafe_allow_html=True)


# ─── ACCESS GATE ─────────────────────────────────────────────────────
# Active only when DM_PASSWORD is set on the host. Unset means no gate, so
# local runs are unaffected. Lives here because a gate inside a view would
# only guard that view.
def _password():
    v = os.environ.get("DM_PASSWORD")
    if v:
        return v
    try:
        return st.secrets.get("DM_PASSWORD")
    except Exception:
        return None


_pw = _password()
if _pw and not st.session_state.get("dm_auth"):
    st.markdown("<div style='height:60px'></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown(
            "<div class='app-head'><div>"
            "<div style='color:white;font-size:18px;font-weight:700'>"
            "📊 DM Dashboard · Inripe 2026</div>"
            "<div style='color:#BDD7F5;font-size:12px;margin-top:3px'>"
            "Internal dashboard. Sign in to continue.</div></div></div>",
            unsafe_allow_html=True)
        entry = st.text_input("Password", type="password",
                              label_visibility="collapsed", placeholder="Password")
        if st.button("Open dashboard", use_container_width=True):
            if entry == _pw:
                st.session_state["dm_auth"] = True
                st.rerun()
            else:
                st.error("That password is not correct.")
    st.stop()


# ─── VIEW SWITCHER ───────────────────────────────────────────────────
names = list(VIEWS)
choice = st.radio("View", names, index=names.index(DEFAULT_VIEW),
                  horizontal=True, label_visibility="collapsed")

module_name, subtitle = VIEWS[choice]
st.markdown(f"""<div class='app-head'>
<div>
<div style='color:white;font-size:19px;font-weight:700'>📊 DM {choice} · Inripe 2026</div>
<div style='color:#BDD7F5;font-size:12px;margin-top:3px'>{subtitle}</div>
</div>
<div style='text-align:right;color:#BDD7F5;font-size:12px'>Inripe 2026</div>
</div>""", unsafe_allow_html=True)

try:
    view = __import__(module_name)
    view.render()
except Exception as e:
    st.error(f"The {choice} view could not be loaded.\n\n"
             f"{type(e).__name__}: {e}")
    st.caption(f"Expected a module named {module_name}.py beside this file, "
               f"exposing a render() function. The other view is unaffected — "
               f"switch tabs above to keep working.")

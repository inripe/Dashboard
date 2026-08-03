"""
INRIPE DM DASHBOARD V2

Presentation only. Every figure comes from dm_engine, which imports no Streamlit
and can be verified on its own: run audit.py before any deploy.

Structure
---------
    Overview        always visible, no tab. The management answer.
    Performance     market and channel, plan vs actual, with the trend beneath.
    Comparison      period A vs period B.
    Efficiency      what an order costs and whether spending more buys more.
    Data            whether the numbers can be trusted.

One dashboard for four audiences, layered rather than split. Separate views per
role would produce two versions of the truth and turn every meeting into an
argument about which is right. A CEO reads the overview and stops; a media buyer
scrolls into the tabs.
"""

import datetime as dt
import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import dm_engine as E
import sharepoint_loader as SP

st.set_page_config(page_title="Dashboard | Digital Marketing Performance",
                   page_icon="📊", layout="wide")

LOCAL_FALLBACKS = ["DM_Model_2026_V3_5.xlsx", "DM_Model_2026_V3.xlsx"]

NAVY, GREEN, AMBER, RED, GREY = "#1B4F8A", "#0F6E56", "#854F0B", "#A32D2D", "#8A8A8A"
BLUE, PURPLE = "#185FA5", "#534AB7"
MCOL = {"UAE": "#378ADD", "KSA": "#D85A30", "Qatar": "#1D9E75", "Egypt": "#D4537E"}
CCOL = {"API": "#0F6E56", "Meta": "#534AB7", "Meta API": "#534AB7",
        "Meta Ecom": "#8B84E0", "TikTok": "#BA7517",
        "Snapchat": "#EF9F27", "YouTube": "#E24B4A"}

CSS = """
<style>
[data-testid="stAppViewContainer"]{background:#F8F9FA}
[data-testid="stSidebar"]{display:none}
.hero{background:linear-gradient(135deg,#1B4F8A 0%,#0F6E56 100%);padding:15px 24px;
      border-radius:10px;margin-bottom:14px;display:flex;justify-content:space-between;
      align-items:center}
.hero h1{color:white;font-size:19px;font-weight:700;margin:0}
.hero p{color:#BDD7F5;font-size:12px;margin:3px 0 0}
.hero .meta{text-align:right;color:#BDD7F5;font-size:12px}
.say{border-radius:0;padding:13px 18px;margin:8px 0 6px;font-size:13.5px;line-height:1.7;
     border-left:4px solid}
.say-good{background:#F1F8F4;border-color:#0F6E56;color:#0b4a39}
.say-warn{background:#FFF8EC;border-color:#854F0B;color:#5c3f0b}
.say-risk{background:#FDF2F2;border-color:#A32D2D;color:#5c1a1a}
.say-info{background:#F4F5F7;border-color:#8A8A8A;color:#3a3a3a}
.health{font-size:12px;color:#6B7280;margin:2px 0 16px}
.card{background:white;border-radius:12px;padding:15px 17px;
      box-shadow:0 1px 3px rgba(0,0,0,0.06);height:100%}
.card .lab{font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:0.06em}
.card .val{font-size:26px;font-weight:700;color:#1A1A1A;margin:5px 0 3px;line-height:1.1}
.card .sub{font-size:12px;color:#6B7280;line-height:1.6}
.card .ver{font-size:12.5px;font-weight:700;margin-top:8px}
.dev{position:relative;height:12px;background:#F1F2F4;border-radius:3px;margin-top:9px}
.dev-mid{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:#9AA0A6}
.dev-fill{position:absolute;top:3px;bottom:3px;border-radius:2px}
.dev-cap{position:absolute;top:1px;bottom:1px;width:2.5px;border-radius:1px}
.sect{font-size:15px;font-weight:700;color:#1A1A1A;margin:24px 0 2px;
  padding-left:10px;border-left:3px solid #1B4F8A}
.sect-sub{font-size:12px;color:#6B7280;margin:0 0 9px;padding-left:13px}
.note{font-size:11.5px;color:#8A8A8A;line-height:1.6;margin:-4px 0 14px}
/* Tabs read as navigation, not as faint text. The selected one is filled so
   the current screen is unmistakable at a glance in a meeting. */
.stTabs [data-baseweb="tab-list"]{gap:4px;background:#E8EBEF;padding:5px;
  border-radius:11px;border:none}
.stTabs [data-baseweb="tab"]{font-size:13.5px;font-weight:600;padding:9px 22px;
  border-radius:8px;color:#4A5560;background:transparent;transition:none}
.stTabs [data-baseweb="tab"]:hover{background:#DDE2E8;color:#1B4F8A}
.stTabs [aria-selected="true"]{background:#1B4F8A !important;color:#FFFFFF !important;
  box-shadow:0 1px 3px rgba(27,79,138,0.28)}
.stTabs [aria-selected="true"] p{color:#FFFFFF !important;font-weight:700}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"]{display:none}
.stTabs [data-baseweb="tab-panel"]{padding-top:6px}
[data-testid="stDataFrame"]{border-radius:10px;overflow:hidden;
  box-shadow:0 1px 3px rgba(0,0,0,0.06);border:0.5px solid #E6E8EB}
[data-testid="stDataFrame"] thead th{background:#1B4F8A !important;color:#fff !important}
div[data-baseweb="select"]>div{border-radius:8px;border-color:#DDE1E6}
label[data-testid="stWidgetLabel"] p{font-size:12px;color:#6B7280;font-weight:600;
  text-transform:uppercase;letter-spacing:0.05em}
.chk{display:flex;gap:10px;padding:7px 0;font-size:12.5px;border-bottom:0.5px solid #f1f2f4}
.chk:last-child{border-bottom:none}
.pill{font-size:10px;font-weight:700;padding:2px 9px;border-radius:10px;color:white;
      width:46px;text-align:center;flex-shrink:0;margin-top:1px}
</style>
"""

def sparkline(vals, colour, w=100, h=22):
    """A shape, not a chart. Enough to see direction without reading a number."""
    v = [x for x in vals if x is not None and not (isinstance(x, float) and np.isnan(x))]
    if len(v) < 2:
        return ""
    lo, hi = min(v), max(v)
    rng = (hi - lo) or 1
    step = w / (len(v) - 1)
    pts = " ".join(f"{i*step:.1f},{h - 3 - (x-lo)/rng*(h-6):.1f}"
                   for i, x in enumerate(v))
    return (f"<svg viewBox='0 0 {w} {h}' style='width:100%;height:{h}px;"
            f"display:block;margin:5px 0 6px' preserveAspectRatio='none'>"
            f"<polyline points='{pts}' fill='none' stroke='{colour}' "
            f"stroke-width='1.6' stroke-linejoin='round'/></svg>")


def pace_bar(pctv, colour, cap=100):
    """Fills to percent-of-pace with a tick at 100, so being behind is visible
    before any number is read."""
    if pctv is None:
        return ("<div style='height:5px;background:#F1F2F4;border-radius:3px;"
                "margin:6px 0 8px'></div>")
    fill = min(pctv, 100.0)
    tick = 100.0 if pctv <= 100 else (100.0 / pctv * 100)
    return (f"<div style='position:relative;height:5px;background:#F1F2F4;"
            f"border-radius:3px;margin:6px 0 8px'>"
            f"<div style='position:absolute;left:0;top:0;bottom:0;"
            f"width:{fill:.0f}%;background:{colour};border-radius:3px'></div>"
            f"<div style='position:absolute;left:{tick:.0f}%;top:-3px;bottom:-3px;"
            f"width:1.5px;background:#8A8A8A'></div></div>")


def metric_card(c):
    v = E.fmt(c.value, c.prefix, c.suffix, c.dec)
    pc = ("" if c.pct_of is None else
          f"<div style='font-size:12px;color:{c.colour};font-weight:600'>"
          f"{c.pct_of:.0f}% of {c.basis}</div>")
    foot = "<br>".join(c.foot.split("\n")) if c.foot else ""
    return (f"<div class='card'>"
            f"<div class='lab'>{c.label}</div>"
            f"<div class='val'>{v}</div>{pc}"
            f"{pace_bar(c.pct_of, c.colour)}"
            f"{sparkline(c.spark, c.colour)}"
            f"<div class='sub'>{foot}</div></div>")


ARROW = {"up": "▲", "down": "▼", "flat": "—"}
ARROW_C = {"up": GREEN, "down": RED, "flat": "#999"}
DEV_SCALE = 50.0


SECTION_N = {"n": 0}


def section(title, sub=None, band=False, reset=None):
    """A numbered rule above each block, so a room can say 'on 3' rather than
    'the one with the capacity thing'.

    The band is a tinted wrapper. It is opened here and closed by the next
    section or by end_band(), because Streamlit writes elements in order and
    cannot nest a container around calls it has not seen yet.
    """
    if reset is not None:
        SECTION_N["n"] = reset
    SECTION_N["n"] += 1
    n = SECTION_N["n"]
    bg = "#F1F3F6" if band else "transparent"
    st.markdown(
        f"<div style='background:{bg};margin:26px -18px 0;padding:18px 18px 2px;"
        f"border-radius:{'12px 12px 0 0' if band else '0'}'>"
        f"<div style='display:flex;align-items:baseline;gap:11px;"
        f"border-top:1px solid #DDE1E6;padding-top:11px'>"
        f"<span style='font-size:11px;font-weight:700;color:#FFF;"
        f"background:#1B4F8A;width:19px;height:19px;border-radius:5px;"
        f"display:inline-flex;align-items:center;justify-content:center;"
        f"flex-shrink:0'>{n}</span>"
        f"<span style='font-size:14.5px;font-weight:700;color:#1A1A1A'>{title}</span>"
        f"{f'<span style=&quot;font-size:12px;color:#6B7280&quot;>{sub}</span>' if sub else ''}"
        f"</div></div>", unsafe_allow_html=True)
    if band:
        st.markdown(f"<div style='background:{bg};margin:0 -18px;padding:2px 18px 16px;"
                    f"border-radius:0 0 12px 12px'>", unsafe_allow_html=True)


def end_band():
    st.markdown("</div>", unsafe_allow_html=True)


def chart(fig, h=300):
    fig.update_layout(height=h, margin=dict(t=26, b=10, l=10, r=10),
                      plot_bgcolor="#FAFAFA", paper_bgcolor="rgba(0,0,0,0)",
                      yaxis_gridcolor="#EBEBEB", yaxis_gridwidth=0.5,
                      font=dict(family="Arial", size=12, color="#444"),
                      legend=dict(orientation="h", y=1.13, x=0,
                                  bgcolor="rgba(0,0,0,0)", font_size=12),
                      hovermode="x unified",
                      hoverlabel=dict(bgcolor="white", bordercolor="#ddd", font_size=12))
    fig.update_xaxes(showgrid=False, tickfont=dict(size=11, color="#888"),
                     linecolor="#ddd", linewidth=0.5)
    fig.update_yaxes(tickfont=dict(size=11, color="#888"),
                     linecolor="#ddd", linewidth=0.5, zeroline=False)
    return fig


# Columns whose content carries a verdict, so it can be coloured. Matching on
# the name rather than the position means a reordered table still styles right.
_GOOD_WORDS = ("ok", "on plan", "better", "cheapest")
_BAD_WORDS = ("over the ceiling", "behind", "short by", "worse", "check data",
              "must be 100%")
_WARN_WORDS = ("watch", "not planned", "no actuals", "no plan", "n/a", "new")


def _verdict_colour(v):
    t = str(v).lower()
    if any(w in t for w in _BAD_WORDS):
        return f"color:{RED};font-weight:600"
    if any(w in t for w in _GOOD_WORDS):
        return f"color:{GREEN};font-weight:600"
    if any(w in t for w in _WARN_WORDS):
        return f"color:{AMBER}"
    return ""


def _num_align(col):
    """Right-align anything numeric. A column of figures is read down, and
    ragged left-aligned numbers cannot be compared at a glance."""
    return "text-align:right" if any(
        ch.isdigit() for ch in "".join(str(x) for x in col.head(5))) else ""


def table(df, note=None):
    if df is None or df.empty:
        st.caption("Nothing to show for this selection.")
        return

    verdict_cols = [c for c in df.columns
                    if str(c).lower() in ("status", "read", "verdict",
                                          "plan status", "actual status",
                                          "direction", "scored")]
    sty = (df.style
           .set_table_styles([
               {"selector": "th",
                "props": [("background-color", NAVY), ("color", "white"),
                          ("font-weight", "600"), ("font-size", "11px"),
                          ("text-transform", "uppercase"),
                          ("letter-spacing", "0.04em"),
                          ("border-bottom", "1px solid #16406e"),
                          ("padding", "8px 10px")]},
               {"selector": "td",
                "props": [("font-size", "12.5px"), ("padding", "7px 10px"),
                          ("border-bottom", "0.5px solid #EDEFF2")]},
               {"selector": "tbody tr:nth-child(even)",
                "props": [("background-color", "#FAFBFC")]},
               {"selector": "tbody tr:hover",
                "props": [("background-color", "#EEF4FB")]},
           ]))
    for c in verdict_cols:
        sty = sty.map(_verdict_colour, subset=[c])
    for c in df.columns:
        if _num_align(df[c]):
            sty = sty.set_properties(subset=[c], **{"text-align": "right"})

    st.dataframe(sty, use_container_width=True, hide_index=True,
                 height=min(35 * (len(df) + 1) + 3, 620))
    if note:
        st.markdown(f"<div class='note'>{note}</div>", unsafe_allow_html=True)


def say(sev, text):
    st.markdown(f"<div class='say say-{sev}'>{text}</div>", unsafe_allow_html=True)


# ─── ACCESS ──────────────────────────────────────────────────────────
def _pw():
    v = os.environ.get("DM_PASSWORD")
    if v:
        return v
    try:
        return st.secrets.get("DM_PASSWORD")
    except Exception:
        return None


st.markdown(CSS, unsafe_allow_html=True)

pw = _pw()
if pw and not st.session_state.get("auth"):
    st.markdown("<div style='height:60px'></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("<div class='hero'><div>"
                    "<h1>📊 Dashboard | Digital Marketing Performance</h1>"
                    "<p>Internal dashboard. Sign in to continue.</p></div></div>",
                    unsafe_allow_html=True)
        entry = st.text_input("Password", type="password",
                              label_visibility="collapsed", placeholder="Password")
        if st.button("Open dashboard", use_container_width=True):
            if entry == pw:
                st.session_state["auth"] = True
                st.rerun()
            else:
                st.error("That password is not correct.")
    st.stop()


# ─── LOAD ────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def load():
    if SP.is_configured():
        buf, meta = SP.fetch_workbook()
        return E.load_model(buf), meta
    for p in LOCAL_FALLBACKS:
        if Path(p).exists():
            return E.load_model(p), {"name": p, "local": True}
    raise FileNotFoundError("Workbook not found: " + ", ".join(LOCAL_FALLBACKS))


try:
    M, META = load()
except Exception as e:
    st.error(f"Cannot load the workbook.\n\n{e}")
    if not SP.is_configured():
        st.caption("SharePoint is not configured. Missing: " + ", ".join(SP.missing_keys()))
    st.stop()

periods = M.periods()
if not periods:
    st.warning("The workbook has no plan and no actuals.")
    st.stop()

stamp = (META["modified"].replace("T", " ")[:16] + " UTC") if META.get("modified") else "local file"
who = META.get("modified_by")
st.markdown(f"""<div class='hero'>
<div><h1>📊 Dashboard | Digital Marketing Performance</h1>
<p>Plan, actuals and allocation across markets and channels</p></div>
<div class='meta'>Workbook updated <b style='color:white'>{stamp}</b>{f'<br>by {who}' if who else ''}</div>
</div>""", unsafe_allow_html=True)

years = M.years()
c0, c1, c2, c3 = st.columns([0.8, 1.3, 1.8, 1.8])
YEAR = c0.selectbox("Year", years, index=len(years) - 1)
all_mo = M.months_in(YEAR)
closed = E.closed_months(M, YEAR)
cur = E.current_month(M, YEAR) or (all_mo[-1] if all_mo else None)

# One period at a time. A free mix of closed, running and unstarted months
# produces a paced percentage that measures none of them — and it gets quoted.
# Year to date is a defined aggregate over closed months only.
opts = list(all_mo) + (["Year to date"] if len(closed) > 1 else [])
default = opts.index(cur) if cur in opts else len(opts) - 1
PERIOD = c1.selectbox("Period", opts, index=default)
YTD = PERIOD == "Year to date"
MONTH = closed if YTD else PERIOD

all_m = M.market_list()
all_c = M.display_channels(False)          # Meta as planned; the split is a panel
sel_m = c2.multiselect("Markets", all_m, default=all_m)
sel_disp = c3.multiselect("Channels", all_c, default=all_c)

if not all_mo or not sel_m or not sel_disp:
    st.warning("Select at least one market and one channel.")
    st.stop()

sel_c = M.expand(sel_disp, False)
SPLIT = False
COV = E.coverage(M, YEAR, MONTH)
KW = dict(markets=sel_m, channels=sel_c, year=YEAR, month=MONTH)
sel_p = f"{PERIOD} {YEAR}" if not YTD else f"Year to date {YEAR}"
PREV = None
if not YTD and PERIOD in all_mo:
    i = all_mo.index(PERIOD)
    PREV = all_mo[i - 1] if i > 0 else None

if YTD:
    st.markdown(f"<div class='note' style='margin:-6px 0 12px'>Year to date covers "
                f"{', '.join(closed)} — closed months only. "
                f"{cur} is still running and is excluded.</div>",
                unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════
# OVERVIEW
# ═════════════════════════════════════════════════════════════════════
# ── management section ───────────────────────────────────────────────
# Cards carry everything a visual can. One sentence beneath says only what a
# card cannot: a relationship between two of them.
fr = E.freshness(M)
if fr.stale:
    st.markdown(f"<div style='background:#FFF8EC;border:0.5px solid #F0DFC0;"
                f"border-radius:9px;padding:9px 15px;margin-bottom:12px;"
                f"font-size:12.5px;color:#5C3F0B;line-height:1.7'>"
                f"&#9888;&#65038; {fr.text}</div>", unsafe_allow_html=True)
else:
    st.markdown(f"<div style='background:#F1F8F4;border:0.5px solid #B6DEC9;"
                f"border-radius:9px;padding:8px 15px;margin-bottom:12px;"
                f"font-size:12.5px;color:#0B4A39'>&#10003; {fr.text}</div>",
                unsafe_allow_html=True)

if COV.days_elapsed == 0:
    period_line = f"{sel_p} has not started"
elif COV.days_remaining == 0:
    period_line = f"{sel_p} · complete"
else:
    period_line = f"Day {COV.days_elapsed} of {COV.days_in_month}"
scope_lab = (("All markets" if len(sel_m) == len(all_m) else ", ".join(sel_m))
             + " &middot; "
             + ("all channels" if len(sel_disp) == len(all_c) else ", ".join(sel_disp)))
st.markdown(f"<div style='display:flex;align-items:baseline;gap:14px;"
            f"flex-wrap:wrap;margin-bottom:12px'>"
            f"<span style='font-size:17px;font-weight:600'>{period_line}</span>"
            f"<span style='font-size:13px;color:#6B7280'>{sel_p} &middot; "
            f"{scope_lab}</span></div>", unsafe_allow_html=True)

section("Where we stand", "orders, revenue, spend, and what they cost", reset=0)
CARDS = E.management_cards(M, sel_m, sel_c, YEAR, MONTH, COV)
cols = st.columns(len(CARDS))
for col, c in zip(cols, CARDS):
    col.markdown(metric_card(c), unsafe_allow_html=True)

ML = E.management_line(M, sel_m, sel_disp, YEAR, MONTH, COV)
if ML:
    st.markdown(f"<div style='background:#FAFBFC;border-left:3px solid #EF9F27;"
                f"padding:11px 16px;font-size:13px;line-height:1.75;"
                f"margin:14px 0 4px'>{ML}</div>", unsafe_allow_html=True)
st.markdown("<div class='note'>Paced is the month plan pro-rated to today — what "
            "you should have by now to finish on target. Ratios are shown against "
            "plan only, because a ratio does not accumulate. Spend carries no "
            "verdict; ROAS and CPA judge what it bought.</div>",
            unsafe_allow_html=True)

# ── will we land it ──────────────────────────────────────────────────
section("How each month landed" if YTD else "Will we land the month?",
        "actual against the plan pace", band=True)
ser = E.daily_series(M, E.M_ORDERS, sel_m, sel_c, YEAR, MONTH)
t_ord = E.target_orders(M, sel_m, YEAR, MONTH)
if YTD:
    # Across closed months a cumulative run rate is meaningless — every month
    # has already landed. Plan against actual per month says it honestly.
    st.markdown("<div class='sect-sub'>Each closed month, plan against "
                "actual.</div>", unsafe_allow_html=True)
    fm = go.Figure()
    tg_v = [E.target_orders(M, sel_m, YEAR, mo) or 0 for mo in MONTH]
    ac_v = [E.actual(M, E.M_ORDERS, markets=sel_m, channels=sel_c,
                     year=YEAR, month=mo) or 0 for mo in MONTH]
    fm.add_trace(go.Bar(x=list(MONTH), y=tg_v, name="Target",
                        marker_color="#C9D6E5"))
    fm.add_trace(go.Bar(x=list(MONTH), y=ac_v, name="Actual", marker_color=GREEN))
    chart(fm, 280)
    fm.update_layout(barmode="group", yaxis_title="Orders")
    st.plotly_chart(fm, use_container_width=True)
elif len(ser) and t_ord:
    cum = list(ser.cumsum().values)
    plan_line = [t_ord / COV.days_in_month * d for d in range(1, COV.days_in_month + 1)]
    rate = cum[-1] / COV.days_elapsed
    proj = [cum[-1] + rate * d for d in range(0, COV.days_remaining + 1)]
    xs = list(range(COV.days_elapsed, COV.days_in_month + 1))
    land = E.eom(cum[-1], COV)
    st.markdown(f"<div class='sect-sub'>Holding {rate:,.0f} orders/day for the "
                f"{COV.days_remaining} days left lands at {land:,.0f}, "
                f"{E.fmt_pct(land, t_ord)} of plan.</div>", unsafe_allow_html=True)
    fig = go.Figure()
    if len(xs) > 1:
        upper = plan_line[COV.days_elapsed - 1:][:len(xs)]
        fill = "rgba(163,45,45,0.07)" if land < t_ord else "rgba(15,110,86,0.07)"
        fig.add_trace(go.Scatter(x=xs + xs[::-1], y=upper + proj[:len(xs)][::-1],
                                 fill="toself", fillcolor=fill,
                                 line=dict(color="rgba(0,0,0,0)"),
                                 name="Gap to plan", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=list(range(1, COV.days_in_month + 1)), y=plan_line,
                             name="Plan pace", mode="lines",
                             line=dict(color=BLUE, dash="dash", width=2)))
    fig.add_trace(go.Scatter(x=list(range(1, COV.days_elapsed + 1)), y=cum,
                             name="Actual", mode="lines+markers",
                             line=dict(color=GREEN, width=2.5),
                             marker=dict(size=4.5, color=GREEN,
                                         line=dict(color="white", width=1.4))))
    if len(xs) > 1:
        c = GREEN if land >= t_ord * 0.9 else AMBER if land >= t_ord * 0.7 else RED
        fig.add_trace(go.Scatter(x=xs, y=proj[:len(xs)], mode="lines",
                                 name=f"Run rate → {land:,.0f}",
                                 line=dict(color=c, dash="dot", width=2)))
    fig.add_hline(y=t_ord, line_color=BLUE, line_width=1, opacity=0.35,
                  annotation_text=f"Plan {t_ord:,.0f}", annotation_position="bottom right")
    chart(fig, 290)
    fig.update_layout(xaxis_title=f"Day of {MONTH} {YEAR}", yaxis_title="Orders",
                      legend=dict(orientation="h", y=-0.22))
    st.plotly_chart(fig, use_container_width=True)
    st.markdown("<div class='note'>A straight run rate, not a forecast: it assumes no "
                "change in trajectory.</div>", unsafe_allow_html=True)
else:
    st.caption("No plan or no actuals for this selection.")

# ── spend trajectory ─────────────────────────────────────────────────
end_band()
section("Where spend lands", "daily rate, direction, and the ceiling")
SP_ = E.spend_path(M, sel_m, sel_c, YEAR, MONTH, COV)
if not len(SP_.daily):
    st.caption("No spend recorded for this selection.")
else:
    dirn = {"rising": ("▲", RED), "falling": ("▼", GREEN),
            "steady": ("—", "#6B7280"), "flat": ("—", "#6B7280")}[SP_.direction]
    land = (f"{SP_.landing_pct:.0f}% of the ceiling"
            if SP_.landing_pct is not None else "no ceiling set")
    over = SP_.landing_pct is not None and SP_.landing_pct > 100
    st.markdown(f"<div class='sect-sub'>Spend is <b style='color:{dirn[1]}'>"
                f"{SP_.direction} {dirn[0]}</b>. {SP_.note}. "
                f"At that rate the month lands at "
                f"<b>{E.fmt(SP_.eom, 'AED ')}</b> — {land}.</div>",
                unsafe_allow_html=True)
    figs = go.Figure()
    figs.add_trace(go.Bar(x=list(SP_.daily.index), y=list(SP_.daily.values),
                          name="Daily spend", marker_color=BLUE, opacity=0.7))
    roll = SP_.daily.rolling(7, min_periods=1).mean()
    figs.add_trace(go.Scatter(x=list(roll.index), y=list(roll.values),
                              name="7-day average", mode="lines",
                              line=dict(color=PURPLE, width=2.2)))
    if SP_.ceiling and COV.days_in_month:
        figs.add_hline(y=SP_.ceiling / COV.days_in_month, line_dash="dash",
                       line_color=GREEN, line_width=1.5,
                       annotation_text=f"Ceiling rate "
                                       f"{SP_.ceiling/COV.days_in_month:,.0f}/day",
                       annotation_position="top left")
    chart(figs, 260)
    figs.update_layout(yaxis_title="AED")
    st.plotly_chart(figs, use_container_width=True)
    if over:
        say("risk", f"<b>On the current rate the month closes at "
                    f"{E.fmt(SP_.eom, 'AED ')} against a ceiling of "
                    f"{E.fmt(SP_.ceiling, 'AED ')}</b> — over by "
                    f"{E.fmt(SP_.eom - SP_.ceiling, 'AED ')}. "
                    f"A projection, not a commitment: buyers move bids daily.")
    st.markdown("<div class='note'>Projected from the last 7 days rather than the "
                "month average, because a channel that has just scaled up would "
                "otherwise look cheaper than it now is.</div>",
                unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════
# TABS
# ═════════════════════════════════════════════════════════════════════
st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
T_PERF, T_WHY, T_CMP, T_DATA = st.tabs(
    ["Where", "Why", "Compare", "Data"])

# ── WHERE ────────────────────────────────────────────────────────────
with T_PERF:
    section("By market", "each market against its own pace", reset=0)
    mk_cards = []
    for mk in sel_m:
        kw = dict(markets=[mk], channels=sel_c, year=YEAR, month=MONTH)
        o = E.actual(M, E.M_ORDERS, **kw)
        sp = E.actual(M, E.M_SPEND, **kw)
        rev = E.actual(M, E.M_REVENUE, **kw)
        t = E.target_orders(M, [mk], YEAR, MONTH)
        pc = E.pct(o, E.paced(t, COV))
        col = (GREY if pc is None else
               GREEN if pc >= 90 else AMBER if pc >= 70 else RED)
        spark = E._spark(E.daily_series(M, E.M_ORDERS, [mk], sel_c, YEAR, MONTH))
        dot = MCOL.get(mk, "#888")
        head = (f"<div style='display:flex;align-items:baseline;gap:7px'>"
                f"<span style='width:8px;height:8px;border-radius:2px;"
                f"background:{dot}'></span>"
                f"<span style='font-size:12.5px;font-weight:600'>{mk}</span>"
                f"<span style='font-size:11.5px;color:{col};font-weight:600;"
                f"margin-left:auto'>"
                f"{'no plan' if pc is None else f'{pc:.0f}%'}</span></div>")
        foot = (f"paced {E.fmt(E.paced(t, COV))} &middot; "
                f"CPA {E.fmt(E.div(sp, o), 'AED ', dec=2)} &middot; "
                f"{E.fmt(E.div(rev, sp), '', 'x', 1)}")
        mk_cards.append(
            f"<div style='background:white;border-radius:10px;padding:12px 14px;"
            f"box-shadow:0 1px 3px rgba(0,0,0,0.06)'>{head}"
            f"<div style='font-size:21px;font-weight:600;margin:5px 0 1px'>"
            f"{E.fmt(o)}</div>{pace_bar(pc, col)}"
            f"{sparkline(spark, col, h=16)}"
            f"<div style='font-size:11px;color:#6B7280'>{foot}</div></div>")
    cols = st.columns(max(len(mk_cards), 1))
    for c_, h_ in zip(cols, mk_cards):
        c_.markdown(h_, unsafe_allow_html=True)

    section("Market &times; channel", "ranked by contribution to the gap", band=True)
    G = E.gap_table(M, sel_m, sel_disp, YEAR, MONTH, COV, False)
    A = E.allocation_table(M, sel_m, sel_disp, YEAR, MONTH, COV, False)
    if G.empty:
        st.caption("No plan or actuals for this selection.")
    else:
        rows_html = [
            "<div style='display:flex;padding:8px 16px;background:#F4F5F7;"
            "font-size:10px;color:#6B7280;text-transform:uppercase;"
            "letter-spacing:0.05em'>"
            "<div style='width:150px'>Cell</div>"
            "<div style='width:64px;text-align:right'>Orders</div>"
            "<div style='width:60px;text-align:right'>Paced</div>"
            "<div style='width:110px;padding-left:14px'>vs paced</div>"
            "<div style='width:96px'>Shape</div>"
            "<div style='width:70px;text-align:right'>CPA</div>"
            "<div style='width:58px;text-align:right'>ROAS</div>"
            "<div style='flex:1;text-align:right'>Share of gap</div></div>"]
        for _, r in G.iterrows():
            a = A[(A.Market == r["Market"]) & (A.Channel == r["Channel"])]
            cpa = a["CPA"].iloc[0] if len(a) else None
            roas = a["ROAS"].iloc[0] if len(a) else None
            pcv = r["vs paced"]
            col = (GREY if pd.isna(pcv) else
                   GREEN if pcv >= 90 else AMBER if pcv >= 70 else RED)
            never = (r["Actual"] == 0 and r["Spend"] == 0
                     and (r["Paced plan"] or 0) > 0)
            bar = ("<div style='font-size:10.5px;color:#8A8A8A'>never ran</div>"
                   if never else
                   pace_bar(None if pd.isna(pcv) else pcv, col)
                   + (f"<div style='font-size:10.5px;color:{col}'>"
                      f"{'no plan' if pd.isna(pcv) else f'{pcv:.0f}%'}</div>"))
            spark = E._spark(E.daily_series(
                M, E.M_ORDERS, [r["Market"]], M.expand([r["Channel"]], False),
                YEAR, MONTH))
            share = ("&mdash;" if r["Share of gap"] <= 0
                     else f"{r['Share of gap']:.0f}%")
            sbar = ("" if r["Share of gap"] <= 0 else
                    f"<div style='width:74px;height:6px;background:#F1F2F4;"
                    f"border-radius:3px'><div style='width:"
                    f"{min(r['Share of gap'],100):.0f}%;height:6px;"
                    f"background:{col};border-radius:3px'></div></div>")
            tint = "background:#FDF6F6;" if r["Share of gap"] >= 25 else ""
            paced_txt = ("&mdash;" if pd.isna(r["Paced plan"])
                         else f"{r['Paced plan']:,.0f}")
            rows_html.append(
                f"<div style='display:flex;align-items:center;padding:9px 16px;"
                f"border-top:0.5px solid #EDEFF2;font-size:12.5px;{tint}'>"
                f"<div style='width:150px'><b>{r['Market']}</b> "
                f"<span style='color:#6B7280'>{r['Channel']}</span></div>"
                f"<div style='width:64px;text-align:right;font-weight:600'>"
                f"{r['Actual']:,.0f}</div>"
                f"<div style='width:60px;text-align:right;color:#6B7280'>"
                f"{paced_txt}</div>"
                f"<div style='width:110px;padding-right:14px'>{bar}</div>"
                f"<div style='width:96px'>{sparkline(spark, col, w=88, h=16)}</div>"
                f"<div style='width:70px;text-align:right'>"
                f"{E.fmt(cpa, 'AED ', dec=2) if cpa else 'n/a'}</div>"
                f"<div style='width:58px;text-align:right'>"
                f"{E.fmt(roas, '', 'x', 1) if roas else 'n/a'}</div>"
                f"<div style='flex:1;display:flex;align-items:center;gap:8px;"
                f"justify-content:flex-end'>{sbar}"
                f"<span style='width:32px;text-align:right;font-weight:600'>"
                f"{share}</span></div></div>")
        st.markdown(
            f"<div style='background:white;border:0.5px solid #E6E8EB;"
            f"border-radius:12px;overflow:hidden'>{''.join(rows_html)}</div>",
            unsafe_allow_html=True)

        WL = E.where_line(M, sel_m, sel_disp, YEAR, MONTH, COV)
        if WL:
            st.markdown(f"<div style='background:#FAFBFC;border-left:3px solid "
                        f"#EF9F27;padding:11px 16px;font-size:13px;"
                        f"line-height:1.75;margin:12px 0 4px'>{WL}</div>",
                        unsafe_allow_html=True)
        st.markdown("<div class='note'>A cell marked 'never ran' was planned and "
                    "carries no spend — that is different from a channel "
                    "performing badly, and needs a different response. Cells "
                    "ahead of pace show a dash rather than a share.</div>",
                    unsafe_allow_html=True)

    end_band()
    section("Where the next dirham should go", "cheapest orders first")
    if A.empty:
        st.caption("Nothing to allocate against.")
    else:
        d = pd.DataFrame({
            "Market": A["Market"], "Channel": A["Channel"],
            "Orders": A["Orders"].map(lambda v: f"{v:,.0f}"),
            "CPA (AED)": A["CPA"].map(
                lambda v: "n/a" if pd.isna(v) or v == 0 else f"{v:.2f}"),
            "Cost vs plan": A["Cost vs plan"].map(
                lambda v: "n/a" if pd.isna(v) else f"{v:.2f}x"),
            "Budget used": A["Budget used"].map(
                lambda v: "n/a" if pd.isna(v) else f"{v:.0f}%"),
            "Unspent (AED)": A["Unspent"].map(
                lambda v: "n/a" if pd.isna(v) else ("over" if v < 0 else f"{v:,.0f}")),
            "ROAS": A["ROAS"].map(
                lambda v: "n/a" if pd.isna(v) or v == 0 else f"{v:.1f}x"),
            "Read": A["Read"],
        })
        table(d, "Sorted by what an order actually costs, cheapest first, so the "
                 "table reads in the order money should flow. Budget used is spend "
                 "against the paced ceiling: it separates a channel that has "
                 "stopped working from one that simply has not spent.")

    section("Daily trend", "shape of the period", band=True)
    m1, m2 = st.columns([1.4, 1.4])
    tmetric = m1.selectbox("Metric", ["Orders", "Revenue", "Spend", "Units"],
                           key="perf_metric")
    tsplit = m2.selectbox("Split by", ["Market", "Channel", "Total"],
                          key="perf_split")
    metric = {"Orders": E.M_ORDERS, "Revenue": E.M_REVENUE,
              "Spend": E.M_SPEND, "Units": E.M_UNITS}[tmetric]
    figt = go.Figure()
    if tsplit == "Total":
        ser2 = E.daily_series(M, metric, sel_m, sel_c, YEAR, MONTH)
        if len(ser2):
            figt.add_trace(go.Bar(x=list(ser2.index), y=list(ser2.values),
                                  name=tmetric, marker_color=BLUE, opacity=0.75))
            roll = ser2.rolling(3, min_periods=1).mean()
            figt.add_trace(go.Scatter(x=list(roll.index), y=list(roll.values),
                                      name="3-day average", mode="lines",
                                      line=dict(color=PURPLE, width=2)))
    else:
        keys = sel_m if tsplit == "Market" else sel_disp
        pal = MCOL if tsplit == "Market" else CCOL
        for k in keys:
            s2 = (E.daily_series(M, metric, [k], sel_c, YEAR, MONTH)
                  if tsplit == "Market"
                  else E.daily_series(M, metric, sel_m, M.expand([k], False),
                                      YEAR, MONTH))
            if not len(s2):
                continue
            c2 = pal.get(k, "#888")
            figt.add_trace(go.Scatter(x=list(s2.index), y=list(s2.values), name=k,
                                      mode="lines+markers",
                                      line=dict(color=c2, width=2.3),
                                      marker=dict(size=4, color=c2,
                                                  line=dict(color="white",
                                                            width=1.2))))
    t_ord2 = E.target_orders(M, sel_m, YEAR, MONTH)
    if tmetric == "Orders" and t_ord2 and tsplit == "Total" and COV.days_in_month:
        figt.add_hline(y=t_ord2 / COV.days_in_month, line_dash="dash",
                       line_color=GREEN, line_width=1.5,
                       annotation_text=f"Plan rate "
                                       f"{t_ord2/COV.days_in_month:,.0f}/day",
                       annotation_position="top left")
    if figt.data:
        chart(figt, 300)
        figt.update_layout(yaxis_title=tmetric)
        st.plotly_chart(figt, use_container_width=True)
        mo2 = E.momentum(E.daily_series(M, metric, sel_m, sel_c, YEAR, MONTH))
        if mo2.recent is not None:
            st.markdown(f"<div class='note'>Momentum {mo2.label}: last "
                        f"{mo2.window} days average {mo2.recent:,.0f}/day against "
                        f"{mo2.prior:,.0f}/day in the {mo2.window} before.</div>",
                        unsafe_allow_html=True)
    else:
        st.caption("No data for this selection.")
    end_band()


# ── COMPARISON ───────────────────────────────────────────────────────
with T_CMP:
    days = sorted(M.actuals["Day"].unique())
    if len(days) < 4:
        st.caption("At least 4 days of actuals are needed to compare two periods.")
    else:
        presets = E.cmp_presets(days)
        p1, _ = st.columns([1.6, 2.4])
        pk = list(presets) + ["Custom"]
        preset = p1.selectbox("Preset", pk, key="cmp_preset")
        if preset != "Custom":
            da_s, da_e, db_s, db_e = presets[preset]
        else:
            da_e = days[-1]
            da_s = days[max(len(days) - 7, 0)]
            db_e = da_s - dt.timedelta(days=1)
            db_s = max(db_e - dt.timedelta(days=6), days[0])

        d1, d2, d3, d4 = st.columns(4)
        lo, hi = days[0], days[-1]
        a_s = d1.date_input("A · from", value=da_s, min_value=lo, max_value=hi, key="ca1")
        a_e = d2.date_input("A · to", value=da_e, min_value=lo, max_value=hi, key="ca2")
        b_s = d3.date_input("B · from", value=db_s, min_value=lo, max_value=hi, key="cb1")
        b_e = d4.date_input("B · to", value=db_e, min_value=lo, max_value=hi, key="cb2")

        if a_s > a_e or b_s > b_e:
            st.error("Each period's start date must fall on or before its end date.")
        else:
            AR, BR = (a_s, a_e), (b_s, b_e)
            CL = E.compare_line(M, AR, BR, sel_m, sel_c)
            if CL:
                o_ = E.cmp_change(E.cmp_block(M, *AR, sel_m, sel_c),
                                  E.cmp_block(M, *BR, sel_m, sel_c), "orders")
                bar = (RED if o_["read"] == "worse" else
                       GREEN if o_["read"] == "better" else "#9AA0A6")
                st.markdown(f"<div style='background:#FAFBFC;border-left:3px solid "
                            f"{bar};padding:12px 17px;font-size:13.5px;"
                            f"line-height:1.8;margin-bottom:14px'>{CL}</div>",
                            unsafe_allow_html=True)
            for sev, text in E.cmp_summary(M, AR, BR, sel_m, sel_c)[2:]:
                say(sev, text)

            section("Headline", "period A against period B", reset=0)
            A_b = E.cmp_block(M, *AR, sel_m, sel_c)
            B_b = E.cmp_block(M, *BR, sel_m, sel_c)
            cmp_cards = []
            for k, lab, pfx, sfx, dec in [("orders", "Orders", "", "", 0),
                                          ("revenue", "Revenue", "AED ", "", 0),
                                          ("spend", "Spend", "AED ", "", 0),
                                          ("cpa", "CPA", "AED ", "", 2),
                                          ("roas", "ROAS", "", "x", 1)]:
                c_ = E.cmp_change(A_b, B_b, k)
                col = (GREEN if c_["read"] == "better" else
                       RED if c_["read"] == "worse" else "#6B7280")
                pc = "" if c_["pct"] is None else f"{c_['pct']:+.0f}%"
                cmp_cards.append(
                    f"<div style='background:white;border-radius:10px;"
                    f"padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,0.06)'>"
                    f"<div style='font-size:10.5px;color:#6B7280;"
                    f"text-transform:uppercase;letter-spacing:0.06em'>{lab}</div>"
                    f"<div style='display:flex;align-items:baseline;gap:8px;"
                    f"margin:4px 0'>"
                    f"<span style='font-size:21px;font-weight:600'>"
                    f"{E.fmt(A_b[k], pfx, sfx, dec)}</span>"
                    f"<span style='font-size:13px;color:{col};font-weight:600'>"
                    f"{pc}</span></div>"
                    f"<div style='font-size:11.5px;color:#6B7280'>was "
                    f"{E.fmt(B_b[k], pfx, sfx, dec)}</div></div>")
            cc = st.columns(len(cmp_cards))
            for c_, h_ in zip(cc, cmp_cards):
                c_.markdown(h_, unsafe_allow_html=True)
            st.markdown("<div class='note'>Colour reads the move, not the size: a "
                        "falling CPA is better, a rising one worse. Spend carries "
                        "no verdict — CPA and ROAS judge what it bought.</div>",
                        unsafe_allow_html=True)

            section("Market and channel detail",
                    "ordered by how much each market moved", band=True)
            H = E.cmp_hierarchy(M, AR, BR, sel_m, sel_disp, False)
            ind = {0: "", 1: "", 2: "    · "}
            disp = pd.DataFrame({
                "Scope": [ind[l] + s for l, s in zip(H["_level"], H["Scope"])],
                "A orders": H["A orders"].map(lambda v: f"{v:,.0f}"),
                "B orders": H["B orders"].map(lambda v: f"{v:,.0f}"),
                "Δ orders": H["Δ orders"].map(lambda v: f"{v:+,.0f}"),
                "Δ%": H["Δ%"].map(lambda v: "new" if pd.isna(v) else f"{v:+.0f}%"),
                "A revenue": H["A revenue"].map(lambda v: E.fmt(v, "AED ")),
                "B revenue": H["B revenue"].map(lambda v: E.fmt(v, "AED ")),
                "A spend": H["A spend"].map(lambda v: E.fmt(v, "AED ")),
                "B spend": H["B spend"].map(lambda v: E.fmt(v, "AED ")),
                "CPA B→A": [f"{b:.2f}→{a:.2f}" if a and b else
                            (f"—→{a:.2f}" if a else "n/a")
                            for a, b in zip(H["A CPA"], H["B CPA"])],
                "ROAS B→A": [f"{b:.1f}→{a:.1f}x" if a and b else
                             (f"—→{a:.1f}x" if a else "n/a")
                             for a, b in zip(H["A ROAS"], H["B ROAS"])],
                "Share of change": H["Share of change"].map(
                    lambda v: "" if pd.isna(v) else f"{v:.0f}%"),
            })
            table(disp,
                  "Group first, then each market, then the channels inside it. Markets are "
                  "ordered by how much they moved, so whatever drove the change sits at the "
                  "top. 'new' means period B had nothing to compare against. CPA and ROAS "
                  "read oldest first, so the arrow runs the way time does.")

            end_band()
            section("Day by day, aligned",
                    "by position in each range, not by calendar date")
            D = E.cmp_daily(M, AR, BR, sel_m, sel_c)
            figc = go.Figure()
            figc.add_trace(go.Bar(x=D["Day"], y=D["Period B"], name="Period B",
                                  marker_color="#B4B2A9", opacity=0.85,
                                  customdata=D["B date"],
                                  hovertemplate="%{customdata}: %{y:.0f}<extra>B</extra>"))
            figc.add_trace(go.Bar(x=D["Day"], y=D["Period A"], name="Period A",
                                  marker_color=BLUE, customdata=D["A date"],
                                  hovertemplate="%{customdata}: %{y:.0f}<extra>A</extra>"))
            chart(figc, 270)
            figc.update_layout(barmode="group", yaxis_title="Orders", hovermode="x unified")
            st.plotly_chart(figc, use_container_width=True)
            st.markdown("<div class='note'>Days align by position in each range, not by "
                        "calendar date, so day 1 of A sits against day 1 of B and two "
                        "windows of different length stay readable together. Hover for "
                        "the real dates.</div>", unsafe_allow_html=True)


# ── WHY ──────────────────────────────────────────────────────────────
with T_WHY:
    section("Does the capacity model hold?",
            "every paid budget is sized from the gap this model leaves", reset=0)
    CAPC = E.capacity_check(M, sel_m, YEAR, MONTH if not YTD else MONTH[-1])
    if CAPC.empty:
        st.caption("No capacity modelled for this period, or no market reported.")
    else:
        cards_h = []
        for _, r in CAPC.iterrows():
            hit = r["Hit before uptime"]
            col = (GREY if pd.isna(hit) else
                   GREEN if 90 <= hit <= 115 else AMBER if hit >= 60 else RED)
            msg_pct = r["Messages %"]
            cr_ratio = (None if pd.isna(r["CR% actual"]) or not r["CR% assumed"]
                        else r["CR% actual"] / r["CR% assumed"] * 100)
            untested = not r["Messages sent"]
            body = (f"<div style='font-size:11.5px;line-height:1.6;color:#791F1F'>"
                    f"<b>Not a single message went out.</b> The model is untested "
                    f"here, not wrong.</div>" if untested else
                    f"<div style='font-size:11.5px;line-height:1.6;color:#1A1A1A'>"
                    f"{r['Read'].split('. ')[0].split(': ', 1)[-1]}.</div>")
            cards_h.append(
                f"<div style='background:white;border-radius:11px;padding:13px 15px;"
                f"box-shadow:0 1px 3px rgba(0,0,0,0.06);"
                f"{'border:1px solid #F0C9C9' if untested else ''}'>"
                f"<div style='display:flex;align-items:baseline'>"
                f"<span style='font-size:12.5px;font-weight:600'>{r['Market']}</span>"
                f"<span style='font-size:12px;color:{col};font-weight:600;"
                f"margin-left:auto'>{0 if pd.isna(hit) else hit:.0f}% of reachable"
                f"</span></div>"
                f"<div style='font-size:11px;color:#6B7280;margin:7px 0 5px'>"
                f"delivered {r['Delivered']:,.0f} of {r['Reachable']:,.0f} reachable"
                f" &middot; {r['Modelled capacity']:,.0f} net</div>"
                f"<div style='font-size:10.5px;color:#6B7280'>Messages sent</div>"
                f"{pace_bar(msg_pct, RED if (msg_pct or 0) < 90 else GREEN)}"
                f"<div style='font-size:10.5px;color:#6B7280'>Conversion vs assumed"
                f"</div>{pace_bar(cr_ratio, GREEN if (cr_ratio or 100) >= 96 else AMBER)}"
                f"{body}</div>")
        cols_c = st.columns(max(len(cards_h), 1))
        for c_, h_ in zip(cols_c, cards_h):
            c_.markdown(h_, unsafe_allow_html=True)
        st.markdown("<div class='note'>Capacity is messages &times; CR% &times; "
                    "uptime, and delivery carries no uptime haircut — so the two "
                    "bars are measured against reachable capacity, or a market on "
                    "plan for both factors would read as over-delivering. Both "
                    "figures are shown.</div>", unsafe_allow_html=True)

    section("What an order costs, in context",
            "against the cheapest channel in the same market", band=True)
    CTX = E.cpa_context(M, sel_m, sel_disp, YEAR, MONTH, PREV)
    if CTX.empty:
        st.caption("No spend recorded for this selection.")
    else:
        worst = CTX["vs cheapest"].max() or 1
        rows_h = ["<div style='display:flex;padding:8px 16px;background:#F4F5F7;"
                  "font-size:10px;color:#6B7280;text-transform:uppercase;"
                  "letter-spacing:0.05em'>"
                  "<div style='width:140px'>Cell</div>"
                  "<div style='width:70px;text-align:right'>CPA</div>"
                  "<div style='width:168px;padding-left:16px'>vs cheapest in market"
                  "</div><div style='width:76px;text-align:right'>Last month</div>"
                  "<div style='width:70px;text-align:right'>Plan CPA</div>"
                  "<div style='flex:1;padding-left:14px'>What it means</div></div>"]
        for _, r in CTX.iterrows():
            ratio = r["vs cheapest"]
            col = (GREEN if ratio <= 1.05 else AMBER if ratio < 2 else RED)
            w = min(ratio / max(worst, 1.01) * 100, 100)
            bar = (f"<div style='height:6px;background:{col};width:{max(w,4):.0f}%;"
                   f"border-radius:3px'></div>")
            tag = ("" if ratio <= 1.001 else
                   f"<span style='font-size:11px;color:{col};font-weight:600'>"
                   f"{ratio:.1f}x</span>")
            vsl = ("n/a" if pd.isna(r["vs last month"])
                   else f"{r['vs last month']:+.0f}%")
            tint = "background:#FDF6F6;" if ratio >= 3 else ""
            plan_cpa_txt = ("n/a" if pd.isna(r["Plan CPA"])
                            else f"{r['Plan CPA']:.2f}")
            rows_h.append(
                f"<div style='display:flex;align-items:center;padding:8px 16px;"
                f"border-top:0.5px solid #EDEFF2;font-size:12.5px;{tint}'>"
                f"<div style='width:140px'><b>{r['Market']}</b> "
                f"<span style='color:#6B7280'>{r['Channel']}</span></div>"
                f"<div style='width:70px;text-align:right;color:{col};"
                f"font-weight:600'>{r['CPA']:.2f}</div>"
                f"<div style='width:168px;padding-left:16px;display:flex;"
                f"align-items:center;gap:8px'>"
                f"<div style='flex:1'>{bar}</div>{tag}</div>"
                f"<div style='width:76px;text-align:right;color:#6B7280'>{vsl}</div>"
                f"<div style='width:70px;text-align:right;color:#6B7280'>"
                f"{plan_cpa_txt}</div>"
                f"<div style='flex:1;padding-left:14px;font-size:11.5px;"
                f"color:#6B7280'>{r['Read']}</div></div>")
        st.markdown(f"<div style='background:white;border:0.5px solid #E6E8EB;"
                    f"border-radius:12px;overflow:hidden'>{''.join(rows_h)}</div>",
                    unsafe_allow_html=True)
        st.markdown("<div class='note'>The bar is an opportunity cost inside the "
                    "same market: 3.2x means three of that market's cheapest orders "
                    "for the price of one. Plan CPA is shown for budget control but "
                    "is not the verdict — it is a number you set, so a lenient "
                    "assumption would turn an expensive channel green.</div>",
                    unsafe_allow_html=True)
        if PREV is None and not YTD:
            st.markdown("<div class='note'>No prior month in the data yet, so "
                        "'last month' reads n/a. It fills in from the second month "
                        "onward.</div>", unsafe_allow_html=True)

    # Meta breakdown: a diagnostic, not a scorecard. No plan columns, because
    # the plan is written for Meta as a whole and cannot be attributed to a
    # platform without inventing a split.
    # The parent is read from the register, never named: a second channel
    # planned as one and reported as several needs no code change.
    _par = M.parent_of()
    parent = (max(set(_par.values()), key=lambda p: sum(1 for v in _par.values()
                                                        if v == p)) if _par else None)
    kids = [c for c, p in _par.items() if p == parent]
    if kids:
        end_band()
        section(f"Inside {parent}",
                "reported per platform, planned as one — a diagnostic, not a scorecard")
        rows_s = []
        tot_o = sum(E.actual(M, E.M_ORDERS, markets=sel_m, channels=[k],
                             year=YEAR, month=MONTH) or 0 for k in kids)
        hdr = ("<div style='display:flex;padding:8px 16px;background:#F4F5F7;"
               "font-size:10px;color:#6B7280;text-transform:uppercase;"
               "letter-spacing:0.05em'><div style='width:76px'>Market</div>"
               "<div style='width:104px'>Platform</div>"
               "<div style='width:64px;text-align:right'>Orders</div>"
               f"<div style='width:170px;padding-left:16px'>Share of {parent}</div>"
               "<div style='width:74px;text-align:right'>CPA</div>"
               "<div style='flex:1;text-align:right'>ROAS</div></div>")
        rows_s.append(hdr)
        pal = ["#534AB7", "#8B84E0", "#B3AEEF"]
        for mk in sel_m:
            cells = []
            for k in kids:
                kw2 = dict(markets=[mk], channels=[k], year=YEAR, month=MONTH)
                o2 = E.actual(M, E.M_ORDERS, **kw2) or 0
                sp2 = E.actual(M, E.M_SPEND, **kw2) or 0
                rev2 = E.actual(M, E.M_REVENUE, **kw2) or 0
                if o2 or sp2:
                    cells.append((k, o2, sp2, rev2))
            if not cells:
                continue
            mk_tot = sum(c[1] for c in cells) or 1
            best = min((E.div(c[2], c[1]) or 9e9) for c in cells)
            for i2, (k, o2, sp2, rev2) in enumerate(cells):
                cpa2 = E.div(sp2, o2)
                share = o2 / mk_tot * 100
                col2 = pal[i2 % len(pal)]
                cheap = cpa2 is not None and abs(cpa2 - best) < 0.001
                rows_s.append(
                    f"<div style='display:flex;align-items:center;padding:8px 16px;"
                    f"border-top:0.5px solid "
                    f"{'#D9DCE1' if i2 == 0 else '#EDEFF2'};font-size:12.5px'>"
                    f"<div style='width:76px'><b>{mk if i2 == 0 else ''}</b></div>"
                    f"<div style='width:104px;color:#6B7280'>{k}</div>"
                    f"<div style='width:64px;text-align:right'>{o2:,.0f}</div>"
                    f"<div style='width:170px;padding-left:16px;display:flex;"
                    f"align-items:center;gap:8px'>"
                    f"<div style='flex:1;height:6px;background:#F1F2F4;"
                    f"border-radius:3px'><div style='width:{share:.0f}%;height:6px;"
                    f"background:{col2};border-radius:3px'></div></div>"
                    f"<span style='font-size:11px;width:28px;text-align:right'>"
                    f"{share:.0f}%</span></div>"
                    f"<div style='width:74px;text-align:right;"
                    f"color:{GREEN if cheap else '#1A1A1A'};"
                    f"font-weight:{'600' if cheap else '400'}'>"
                    f"{E.fmt(cpa2, 'AED ', dec=2)}</div>"
                    f"<div style='flex:1;text-align:right'>"
                    f"{E.fmt(E.div(rev2, sp2), '', 'x', 1)}</div></div>")
        st.markdown(f"<div style='background:white;border:0.5px solid #E6E8EB;"
                    f"border-radius:12px;overflow:hidden'>{''.join(rows_s)}</div>",
                    unsafe_allow_html=True)
        st.markdown(f"<div class='note'>A diagnostic for deciding where inside "
                    f"{parent} to push, not a scorecard. The cheaper platform in "
                    f"each market is highlighted. Plan comparisons live on Where, "
                    f"where {parent} is whole.</div>", unsafe_allow_html=True)


        MTL = E.split_line(M, sel_m, YEAR, MONTH)
        if MTL:
            st.markdown(f"<div style='background:#FAFBFC;border-left:3px solid #534AB7;"
                        f"padding:11px 16px;font-size:13px;line-height:1.75;"
                        f"margin:12px 0 16px'>{MTL}</div>", unsafe_allow_html=True)
        

    section("Does spending more buy more?", "daily relationships", band=True)
    day_rows = []
    for day, g in E.scope(M.actuals, sel_m, sel_c, YEAR, MONTH).groupby("Day"):
        o = g[g["Metric"] == E.M_ORDERS]["Value"].sum()
        sp = g[g["Metric"] == E.M_SPEND]["Value"].sum()
        day_rows.append({"day_num": day.day, "orders": o, "spend": sp,
                         "cpa": (sp / o) if o else None})
    DF = pd.DataFrame(day_rows).sort_values("day_num") if day_rows else pd.DataFrame()

    def scat(title, x, y, xlab, ylab, colour, meaning):
        st.markdown(f"**{title}**")
        if DF.empty or DF[[x, y]].dropna().shape[0] < 4:
            st.caption("Not enough days to test this.")
            return
        dd = DF[[x, y]].dropna()
        f = go.Figure(go.Scatter(x=dd[x], y=dd[y], mode="markers",
                                 marker=dict(size=8, color=colour, opacity=0.7,
                                             line=dict(color="white", width=1))))
        if dd[x].nunique() > 1 and dd[y].nunique() > 1:
            try:
                z = np.polyfit(dd[x], dd[y], 1)
                xl = np.linspace(dd[x].min(), dd[x].max(), 50)
                f.add_trace(go.Scatter(x=xl, y=np.poly1d(z)(xl), mode="lines",
                                       line=dict(color=RED, dash="dash", width=1.5)))
            except (np.linalg.LinAlgError, ValueError):
                pass
        chart(f, 250)
        f.update_layout(xaxis_title=xlab, yaxis_title=ylab, showlegend=False,
                        hovermode="closest")
        st.plotly_chart(f, use_container_width=True)
        try:
            rr = float(dd.corr().iloc[0, 1])
        except Exception:
            rr = float("nan")
        if np.isnan(rr):
            st.caption(f"Not enough variation across {len(dd)} days to measure a "
                       f"relationship.")
        else:
            st.caption(f"r = {rr:+.2f} over {len(dd)} days — {E.corr_band(rr)}. "
                       f"{meaning}")

    e1, e2 = st.columns(2)
    with e1:
        scat("Daily spend against daily orders", "spend", "orders",
             "Spend (AED)", "Orders", BLUE,
             "A weak relationship means spend alone is not the lever — look at "
             "targeting and creative.")
    with e2:
        scat("Does CPA drift through the month?", "day_num", "cpa",
             "Day of month", "CPA (AED)", AMBER,
             "A positive relationship means acquisition gets more expensive late "
             "in the month.")
    end_band()


# ── DATA ─────────────────────────────────────────────────────────────
with T_DATA:
    checks = []
    checks.append(("Revenue converted to AED", M.fx_note == "ok",
                   ", ".join(f"{k[0]} x{v:.4f}" for k, v in M.fx.items() if k[1] is None)
                   or M.fx_note))
    G = E.gap_table(M, sel_m, sel_disp, YEAR, MONTH, COV, False)
    npl = sorted({r["Market"] + " " + r["Channel"] for _, r in G.iterrows()
                  if r.get("_noplan")}) if not G.empty else []
    checks.append(("Every reporting cell has a plan", not npl,
                   "complete" if not npl else "reporting without a plan: " + ", ".join(npl)))
    thin2 = [f"{k} {v[0]}/{COV.days_elapsed}d" for k, v in COV.per_market.items()
             if k in sel_m and COV.days_elapsed and v[0] / COV.days_elapsed < E.COVERAGE_MIN]
    checks.append(("Every market reported the full period", not thin2,
                   "all complete" if not thin2 else "thin: " + ", ".join(thin2)))
    bad = []
    if not A.empty:
        for _, r in A.iterrows():
            ok, why = E.plausible(r["CPA"], r["Cost vs plan"] and r["Cost vs plan"] * 100,
                                  "cpa")
            if not ok:
                bad.append(f"{r['Market']} {r['Channel']}: {why}")
    checks.append(("No implausible values", not bad,
                   "every figure sits inside a range a real result could take"
                   if not bad else "; ".join(bad)))
    sp_all = E.actual(M, E.M_SPEND, **KW)
    ceil_all = E.plan_budget(M, sel_m, sel_c, YEAR, MONTH)
    checks.append(("Spend inside the budget ceiling",
                   not (sp_all and ceil_all and sp_all > ceil_all),
                   f"AED {sp_all:,.0f} against a ceiling of AED {ceil_all:,.0f}"
                   if sp_all and ceil_all else "no ceiling set"))

    section("Can the numbers be trusted?", "every check the model runs", reset=0)
    html = ""
    for name, ok, detail in checks:
        col = GREEN if ok else AMBER
        html += (f"<div class='chk'><div class='pill' style='background:{col}'>"
                 f"{'PASS' if ok else 'CHECK'}</div>"
                 f"<div style='width:270px;flex-shrink:0'>{name}</div>"
                 f"<div style='color:#6B7280'>{detail}</div></div>")
    st.markdown(f"<div class='card'>{html}</div>", unsafe_allow_html=True)

    section("Reporting coverage", "who submitted, and on how many days", band=True)
    cov_rows = [{"Market": k, "Days reported": f"{v[0]}/{COV.days_elapsed}",
                 "Days with orders": f"{v[1]}/{COV.days_elapsed}",
                 "Coverage": f"{v[0]/COV.days_elapsed*100:.0f}%" if COV.days_elapsed else "n/a",
                 "Scored": "yes" if not COV.gate(k)[0] else "no — too thin"}
                for k, v in sorted(COV.per_market.items()) if k in sel_m]
    table(pd.DataFrame(cov_rows),
          "'Days reported' counts days the market submitted any figure. 'Days with "
          "orders' counts days it recorded a non-zero order. A gap between them is a "
          "real zero-order day, not a missing feed.")
    end_band()

src = (f"SharePoint · {META.get('name')}" if not META.get("local")
       else f"local file · {META.get('name')}")
period_txt = (sel_p if COV.days_remaining == 0 or COV.days_elapsed == 0
              else f"{sel_p} · day {COV.days_elapsed} of {COV.days_in_month}")
st.markdown(
    f"<div style='margin:34px -18px 0;padding:16px 18px;background:#1B4F8A;"
    f"border-radius:12px 12px 0 0;color:#BDD7F5;font-size:11.5px;"
    f"line-height:1.75'>"
    f"<div style='color:#FFFFFF;font-weight:600;font-size:12.5px;"
    f"margin-bottom:4px'>© {dt.date.today().year} Inripe. All rights reserved."
    f"</div>"
    f"Confidential and proprietary. This dashboard and the data within it are the "
    f"property of Inripe and are provided for internal use only. Copying, "
    f"exporting, screenshotting or distributing any part of it outside the company "
    f"is a breach of company policy and of the terms under which access was granted."
    f"</div>"
    f"<div style='margin:0 -18px;padding:9px 18px 12px;background:#163F6E;"
    f"border-radius:0 0 12px 12px;color:#8FB6E0;font-size:11px'>"
    f"Source: {src} &nbsp;·&nbsp; {period_txt} &nbsp;·&nbsp; engine V2 "
    f"&nbsp;·&nbsp; refreshes every 60s</div>",
    unsafe_allow_html=True)

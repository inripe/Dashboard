"""
INRIPE DM TRACKING DASHBOARD v6
Presentation layer only. Every number comes from dm_engine.py, which is
independently testable — run `python validate.py` to verify the arithmetic
without launching Streamlit.

v6 changes vs v5
----------------
S0   new  Data integrity panel. Self-audit runs on load; a failed check
          suppresses the affected verdict instead of showing a false pass.
polarity  Overspend and CAC overruns can no longer render green.
basis     Every percentage states what it is measured against.
missing   Blank data shows n/a in grey; it is never scored as 0% and red.
momentum  Last 7 days vs the 7 before, not first half vs second half.
rounding  2,918 and 3,345 no longer both display as "3K".
S6        Compares the last 7 days against the previous 7 by default, and
          reports a true delta so identical periods read 0%, not 100%.
S8        CR% uses API orders over API messages, matching the scorecard.
"""

import datetime
import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import dm_engine as E
import sharepoint_loader as SP

st.set_page_config(page_title="Inripe DM Tracking 2026", page_icon="📊", layout="wide")

# Deployed path first, local checkout second.
EXCEL_CANDIDATES = [
    "Digital_Marketing/DM_Tracking/DM_Planing_Tracking_2026_25JUL26_V1_21.xlsx",
    "DM_Planing_Tracking_2026_25JUL26_V1_21.xlsx",
]

GREEN, BLUE, PURPLE, AMBER, RED, GREY = (
    E.GREEN, E.BLUE, "#534AB7", E.AMBER, E.RED, E.GREY)
MCOLORS = {"UAE": "#2a78d6", "KSA": "#eb6834", "Qatar": "#1baf7a", "Egypt": "#e87ba4"}

st.markdown("""
<style>
[data-testid="stAppViewContainer"]{background:#F8F9FA}
[data-testid="stSidebar"]{display:none}
.card{background:white;border-radius:12px;padding:18px 22px;margin:10px 0 18px;
      box-shadow:0 2px 8px rgba(0,0,0,0.06)}
.commentary{background:white;border-radius:12px;padding:20px 24px;
            border-left:5px solid #1B4F8A;margin:12px 0 20px;
            box-shadow:0 2px 8px rgba(0,0,0,0.06)}
.commentary-title{font-size:12px;font-weight:700;color:#1B4F8A;
                  text-transform:uppercase;letter-spacing:0.08em;margin-bottom:10px}
.commentary-text{font-size:14px;color:#2D3436;line-height:1.75;margin:0}
.commentary-text b{color:#1B4F8A}
.c-good{color:#1A6B4A;font-weight:600}
.c-warn{color:#854F0B;font-weight:600}
.c-risk{color:#A32D2D;font-weight:600}
.c-info{color:#555}
.verdict-row{display:flex;align-items:center;gap:8px;padding:7px 0;
             border-bottom:0.5px solid #f0f0f0}
.verdict-row:last-child{border-bottom:none}
.v-metric{font-size:12px;color:#666;width:120px;flex-shrink:0}
.v-actual{font-size:14px;font-weight:700;color:#1A1A1A;width:105px;flex-shrink:0}
.v-arrow{font-size:13px;width:18px;text-align:center;flex-shrink:0}
.v-basis{font-size:11px;color:#888;width:150px;flex-shrink:0}
.v-eom{font-size:11px;color:#1B4F8A;font-weight:600;width:120px;flex-shrink:0}
.dev{position:relative;flex:1;height:15px;min-width:140px;background:#F1F2F4;border-radius:3px}
.dev-mid{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:#9AA0A6}
.dev-q{position:absolute;top:4px;bottom:4px;width:1px;background:#E1E3E6}
.dev-fill{position:absolute;top:3px;bottom:3px;border-radius:2px;opacity:0.92}
.dev-cap{position:absolute;top:1px;bottom:1px;width:2.5px;border-radius:1px}
.dev-na{position:absolute;left:50%;transform:translateX(-50%);font-size:10px;
        color:#BBB;line-height:15px}
.dev-scale{display:flex;font-size:10px;color:#AAA;margin:2px 0 0 0}
.dev-scale span{flex:1}
.v-status{font-size:11px;font-weight:700;width:120px;text-align:right;flex-shrink:0}
.shdr{font-size:12px;font-weight:700;color:white;background:#1B4F8A;
      padding:7px 16px;border-radius:6px;margin:26px 0 14px;
      letter-spacing:0.05em;display:inline-block}
.chk{display:flex;align-items:flex-start;gap:10px;padding:6px 0;font-size:12.5px;
     border-bottom:0.5px solid #f2f2f2}
.chk:last-child{border-bottom:none}
.chk-pill{font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;
          color:white;flex-shrink:0;margin-top:1px;width:44px;text-align:center}
.chk-name{width:330px;flex-shrink:0;color:#333}
.chk-detail{color:#777;font-size:12px}
.banner{border-radius:10px;padding:14px 18px;margin:10px 0 4px;font-size:13.5px;line-height:1.6}
.banner-bad{background:#FDF2F2;border-left:5px solid #A32D2D;color:#5c1a1a}
.banner-ok{background:#F1F8F4;border-left:5px solid #1A6B4A;color:#14432f}
.note{font-size:11.5px;color:#8A8A8A;margin-top:-6px;margin-bottom:10px}
</style>
""", unsafe_allow_html=True)


def shdr(t):
    st.markdown(f"<div class='shdr'>▸ {t}</div>", unsafe_allow_html=True)


def chart_style(fig, h=300):
    fig.update_layout(
        height=h, margin=dict(t=24, b=10, l=10, r=10),
        plot_bgcolor="#FAFAFA", paper_bgcolor="rgba(0,0,0,0)",
        yaxis_gridcolor="#EBEBEB", yaxis_gridwidth=0.5,
        font=dict(family="Arial", size=12, color="#444"),
        legend=dict(orientation="h", y=1.12, x=0, bgcolor="rgba(0,0,0,0)", font_size=12),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="white", bordercolor="#ddd", font_size=12))
    fig.update_xaxes(showgrid=False, tickfont=dict(size=11, color="#888"),
                     linecolor="#ddd", linewidth=0.5)
    fig.update_yaxes(tickfont=dict(size=11, color="#888"),
                     linecolor="#ddd", linewidth=0.5, zeroline=False)
    return fig


def table(df, note=None):
    """Explicit height stops the last row being clipped by the container."""
    if df is None or df.empty:
        st.caption("No rows for this selection.")
        return
    st.dataframe(df, use_container_width=True, hide_index=True,
                 height=min(38 * len(df) + 40, 620))
    if note:
        st.markdown(f"<div class='note'>{note}</div>", unsafe_allow_html=True)


ARROW = {"up": "▲", "down": "▼", "flat": "▬"}
ARROW_COLOR = {"up": GREEN, "down": RED, "flat": "#999"}


# ─── ACCESS GATE ─────────────────────────────────────────────────────
# Active only when a DM_PASSWORD env var (or secret) is set on the host.
# Unset means no gate, so local runs and Streamlit Cloud are unaffected.
def _password():
    v = os.environ.get("DM_PASSWORD")
    if v:
        return v
    try:
        return st.secrets.get("DM_PASSWORD")
    except Exception:
        return None


_pw = _password()
if _pw:
    if not st.session_state.get("dm_auth"):
        st.markdown("<div style='height:60px'></div>", unsafe_allow_html=True)
        _, mid, _ = st.columns([1, 1.2, 1])
        with mid:
            st.markdown(
                "<div style='background:linear-gradient(135deg,#1B4F8A,#1A6B4A);"
                "padding:18px 22px;border-radius:10px;margin-bottom:18px'>"
                "<div style='color:white;font-size:18px;font-weight:700'>"
                "📊 DM Tracking · Inripe 2026</div>"
                "<div style='color:#BDD7F5;font-size:12px;margin-top:3px'>"
                "Internal dashboard. Sign in to continue.</div></div>",
                unsafe_allow_html=True)
            entry = st.text_input("Password", type="password",
                                  label_visibility="collapsed",
                                  placeholder="Password")
            if st.button("Open dashboard", use_container_width=True):
                if entry == _pw:
                    st.session_state["dm_auth"] = True
                    st.rerun()
                else:
                    st.error("That password is not correct.")
        st.stop()


# ─── LOAD ────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def load():
    """SharePoint first, local copy second.

    When SharePoint is configured the workbook is read live on every cache
    refresh, so the team's daily edits appear without anyone touching git.
    When it is not configured the app falls back to the file in the repo, which
    keeps local development and the old setup working unchanged.
    """
    if SP.is_configured():
        buf, meta = SP.fetch_workbook()
        label = f"SharePoint · {meta['name']}"
        if meta.get("modified"):
            label += f" · edited {meta['modified'][:16].replace('T', ' ')}"
            if meta.get("modified_by"):
                label += f" by {meta['modified_by']}"
        return E.load_data(buf) + (label,)
    for c in EXCEL_CANDIDATES:
        if Path(c).exists():
            return E.load_data(c) + (f"local file · {c}",)
    raise FileNotFoundError(
        "Workbook not found. Looked in: " + ", ".join(EXCEL_CANDIDATES))


try:
    t2, t3, src = load()
except Exception as e:
    st.error(f"Cannot load the workbook.\n\n{e}")
    if SP.is_configured():
        st.caption("SharePoint is configured, so the problem is with the "
                   "connection or the file name rather than a missing local copy.")
    else:
        st.caption("SharePoint is not configured. Missing settings: "
                   + ", ".join(SP.missing_keys()))
    st.stop()

if t2.empty:
    st.warning("T2. Actuals has no usable rows.")
    st.stop()

last_dt = t2["Date"].max()
markets = sorted(t2["Market"].unique().tolist())

st.markdown(f"""
<div style='background:linear-gradient(135deg,#1B4F8A 0%,#1A6B4A 100%);
padding:16px 24px;border-radius:10px;margin-bottom:16px;
display:flex;justify-content:space-between;align-items:center'>
<div>
<div style='color:white;font-size:19px;font-weight:700'>📊 DM Tracking · Inripe 2026</div>
<div style='color:#BDD7F5;font-size:12px;margin-top:3px'>
Plan vs actual · pacing · EOM forecast · v6 with integrity checks</div>
</div>
<div style='text-align:right;color:#BDD7F5;font-size:12px'>
Last entry <b style='color:white'>{last_dt.strftime('%d %b %Y') if pd.notna(last_dt) else 'n/a'}</b>
</div></div>""", unsafe_allow_html=True)

c1, c2, _ = st.columns([1, 1, 3])
sel_mkt = c1.selectbox("Market", ["All"] + markets)
pairs = sorted({(int(y), int(m)) for y, m in zip(t2["Year"], t2["Month"])})
labels = [f"{pd.Timestamp(year=y, month=m, day=1).strftime('%b %Y')}" for y, m in pairs]
sel_label = c2.selectbox("Month", labels, index=len(labels) - 1)
sel_year, sel_mo = pairs[labels.index(sel_label)]

snap = E.build_snapshot(t2, t3, sel_mkt, sel_mo, sel_year)
cov = snap.coverage
r = snap.raw

# ══════════════════════════════════════════════════════════════════════
# S0 — DATA INTEGRITY
# ══════════════════════════════════════════════════════════════════════
shdr("S0 · Data integrity — read this before acting on anything below")

failed = [f for f in snap.integrity if not f["pass"]]
high = [f for f in failed if f["severity"] == "high"]

if not failed:
    st.markdown(
        f"<div class='banner banner-ok'><b>All {len(snap.integrity)} checks pass.</b> "
        f"Totals reconcile, targets are present, and every market has "
        f"reported for the full period. Figures below can be acted on.</div>",
        unsafe_allow_html=True)
else:
    names = "; ".join(f["check"] for f in failed)
    st.markdown(
        f"<div class='banner banner-bad'><b>{len(failed)} of {len(snap.integrity)} "
        f"checks failed:</b> {names}.<br>Affected verdicts are marked UNVERIFIED "
        f"rather than passed. Fix the source data before circulating this view.</div>",
        unsafe_allow_html=True)

with st.expander(f"All {len(snap.integrity)} checks", expanded=bool(high)):
    html = ""
    for f in snap.integrity:
        col = GREEN if f["pass"] else (RED if f["severity"] == "high" else AMBER)
        pill = "PASS" if f["pass"] else "FAIL"
        html += (f"<div class='chk'><div class='chk-pill' style='background:{col}'>{pill}</div>"
                 f"<div class='chk-name'>{f['check']}</div>"
                 f"<div class='chk-detail'>{f['detail']}</div></div>")
    st.markdown(f"<div class='card'>{html}</div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# COMMENTARY
# ══════════════════════════════════════════════════════════════════════
body = " ".join(f"<span class='c-{sev}'>{txt}</span>"
                for sev, txt in E.build_commentary(snap))
st.markdown(f"""<div class='commentary'>
<div class='commentary-title'>📋 Executive commentary · {snap.market} · {sel_label} · auto-generated</div>
<div class='commentary-text'>{body}</div></div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════
# SNAPSHOT STRIP
# ══════════════════════════════════════════════════════════════════════
shdr(f"Performance snapshot · day {cov.days_elapsed} of {cov.days_in_month} · "
     f"{cov.days_remaining} days remaining")

DEV_SCALE = 50.0   # the track spans plan −50% … plan +50%


def dev_bar(v):
    """A bar centred on plan, not a share of a fixed width.

    The old bar drew `ratio%` of a wide track, so 69% and 96% looked nearly the
    same and anything above 100% clamped flat. Here the centre line is plan and
    the fill shows how far off it you are, in which direction, coloured by the
    verdict. Values beyond ±50% are clipped and marked with an end cap.
    """
    if v.ratio is None:
        return ("<div class='dev'><div class='dev-mid'></div>"
                "<span class='dev-na'>no basis</span></div>")
    d = v.ratio - 100.0
    clipped = abs(d) > DEV_SCALE
    mag = min(abs(d), DEV_SCALE) / DEV_SCALE * 50.0
    if d >= 0:
        fill = f"left:50%;width:{mag}%;background:{v.color}"
        cap_left = 50.0 + mag
    else:
        fill = f"left:{50 - mag}%;width:{mag}%;background:{v.color}"
        cap_left = 50.0 - mag
    cap = (f"<div class='dev-cap' style='left:{cap_left}%;background:{v.color}'></div>"
           if clipped else "")
    return ("<div class='dev'>"
            "<div class='dev-q' style='left:25%'></div>"
            "<div class='dev-q' style='left:75%'></div>"
            "<div class='dev-mid'></div>"
            f"<div class='dev-fill' style='{fill}'></div>{cap}</div>")


rows = ""
for ln in snap.lines:
    v = ln.verdict
    f = lambda x: E.fmt(x, ln.prefix, ln.suffix, ln.dec)
    basis_val = ln.paced if ln.basis == "paced" else ln.plan
    basis_txt = (f"vs paced {f(basis_val)}" if ln.basis == "paced"
                 else f"vs plan {f(basis_val)}")
    eom_txt = f"EOM {f(ln.eom)}" if ln.eom is not None else "EOM n/a"
    bar = dev_bar(v)
    rows += f"""<div class='verdict-row'>
        <div class='v-metric'>{ln.label}</div>
        <div class='v-actual'>{f(ln.actual)}</div>
        <div class='v-arrow' style='color:{ARROW_COLOR[ln.trend]}'>{ARROW[ln.trend]}</div>
        <div class='v-basis'>{basis_txt}</div>
        <div class='v-eom'>{eom_txt}</div>
        {bar}
        <div class='v-status' style='color:{v.color}'>{v.label}</div>
    </div>"""
st.markdown(f"<div class='card'>{rows}</div>", unsafe_allow_html=True)
st.markdown("<div class='note'>The bar is centred on plan: the line in the middle is 100%, "
            "fill to the right means above the comparison, fill to the left means below, and "
            "the faint marks are ±25%. A bar capped with a thin block runs past ±50%.<br>"
            "Volume metrics are scored against the paced plan "
            "(plan × days elapsed ÷ days in month). Ratios are scored against the full-month "
            "plan, because a ratio does not accumulate. The arrow is the last 7 days against "
            "the 7 before, on that metric's own daily series.<br>Revenue and units are separate targets entered independently in P4, so their percentages measure different assumptions and are not comparable with each other.</div>", unsafe_allow_html=True)

st.divider()

# ══════════════════════════════════════════════════════════════════════
# S1 — MASTER SCORECARD
# ══════════════════════════════════════════════════════════════════════
shdr("S1 · Master scorecard")

sc = []
for ln in snap.lines:
    f = lambda x: E.fmt(x, ln.prefix, ln.suffix, ln.dec)
    sc.append({
        "Metric": ln.label,
        "Plan (month)": f(ln.plan),
        f"Paced to D{cov.days_elapsed}": f(ln.paced) if ln.paced is not None else "n/a",
        "Actual MTD": f(ln.actual),
        "Trend 7d": ARROW[ln.trend],
        "EOM forecast": f(ln.eom) if ln.eom is not None else "n/a",
        "EOM % plan": E.fmt_pct(ln.eom, ln.plan) if ln.eom is not None else "n/a",
        "Scored against": "paced plan" if ln.basis == "paced" else "full-month plan",
        "Status": ln.verdict.label,
    })
table(pd.DataFrame(sc),
      "Status and EOM % plan are different comparisons and will not match: status uses the "
      "column named in 'Scored against', EOM % plan always uses the full-month plan.")

st.divider()

# ══════════════════════════════════════════════════════════════════════
# S2 — RUN RATE
# ══════════════════════════════════════════════════════════════════════
shdr("S2 · Will we land the month? — run rate projection")

s2a, _ = st.columns([1, 3])
m2 = s2a.selectbox("Metric", ["Orders", "Revenue", "Budget spent"], key="s2")
key = {"Orders": "orders", "Revenue": "revenue", "Budget spent": "spend"}[m2]
ln = snap.line(key)
series = (E.daily_orders_series(t2, None if sel_mkt == "All" else sel_mkt, sel_mo, sel_year)
          if key == "orders" else
          E.daily_metric_series(t2, E.REVENUE if key == "revenue" else E.SPEND,
                                None if sel_mkt == "All" else sel_mkt, sel_mo, sel_year))

if len(series) and ln.plan:
    cum = list(series.cumsum().values)
    plan_cum = [ln.plan / cov.days_in_month * d for d in range(1, cov.days_in_month + 1)]
    rate = ln.actual / cov.days_elapsed
    proj = [cum[-1] + rate * d for d in range(0, cov.days_remaining + 1)]
    xs = list(range(cov.days_elapsed, cov.days_in_month + 1))

    fig = go.Figure()
    if len(xs) > 1:
        upper = plan_cum[cov.days_elapsed - 1:][:len(xs)]
        gap_col = ("rgba(163,45,45,0.07)" if (ln.eom or 0) < ln.plan
                   else "rgba(26,107,74,0.07)")
        fig.add_trace(go.Scatter(x=xs + xs[::-1], y=upper + proj[:len(xs)][::-1],
                                 fill="toself", fillcolor=gap_col,
                                 line=dict(color="rgba(0,0,0,0)"),
                                 name="Gap to plan", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=list(range(1, cov.days_in_month + 1)), y=plan_cum,
                             name="Plan pace", mode="lines",
                             line=dict(color=BLUE, dash="dash", width=2)))
    fig.add_trace(go.Scatter(x=list(range(1, cov.days_elapsed + 1)), y=cum,
                             name="Actual", mode="lines+markers",
                             line=dict(color=GREEN, width=2.5),
                             marker=dict(size=5, color=GREEN,
                                         line=dict(color="white", width=1.5))))
    if len(xs) > 1:
        col = (GREEN if (ln.eom or 0) >= ln.plan * 0.9
               else AMBER if (ln.eom or 0) >= ln.plan * 0.7 else RED)
        fig.add_trace(go.Scatter(x=xs, y=proj[:len(xs)], mode="lines",
                                 name=f"Run rate → {E.fmt(ln.eom, ln.prefix)}",
                                 line=dict(color=col, dash="dot", width=2)))
    fig.add_hline(y=ln.plan, line_dash="solid", line_color=BLUE, line_width=1, opacity=0.35,
                  annotation_text=f"Plan {E.fmt(ln.plan, ln.prefix)}",
                  annotation_position="top left")
    chart_style(fig, 330)
    fig.update_layout(xaxis_title=f"Day of {sel_label}", yaxis_title=m2,
                      legend=dict(orientation="h", y=-0.22))
    st.plotly_chart(fig, use_container_width=True)
    st.markdown(
        f"<div class='note'>Projection holds the current {E.fmt(rate, ln.prefix, dec=1)}/day "
        f"rate for the remaining {cov.days_remaining} days. It is a straight run rate, not a "
        f"forecast — it assumes no change in trajectory.</div>", unsafe_allow_html=True)
else:
    st.caption("No plan or no data for this metric.")

st.divider()

# ══════════════════════════════════════════════════════════════════════
# S3 — MARKET × CHANNEL
# ══════════════════════════════════════════════════════════════════════
shdr("S3 · Market × channel breakdown")
table(E.market_channel_breakdown(t2, t3, sel_mo, sel_year, cov),
      "Meta targets are set for Meta as a whole, so Meta API and Meta Ecom rows show no "
      "plan comparison on their own — see the Meta figure in the commentary and the market "
      "Total row. Coverage shows days reported out of days elapsed; a market below "
      f"{int(E.COVERAGE_MIN*100)}% is greyed rather than scored.")

st.divider()

# ══════════════════════════════════════════════════════════════════════
# S4 — DAILY PULSE
# ══════════════════════════════════════════════════════════════════════
shdr("S4 · Daily pulse")

s4a, s4b, _ = st.columns([1, 1, 3])
mk4 = s4a.selectbox("Market", ["All"] + markets, key="s4m")
mt4 = s4b.selectbox("Metric", ["Orders", "Revenue", "Budget spent"], key="s4x")
scope4 = None if mk4 == "All" else mk4
ser4 = (E.daily_orders_series(t2, scope4, sel_mo, sel_year) if mt4 == "Orders"
        else E.daily_metric_series(t2, E.REVENUE if mt4 == "Revenue" else E.SPEND,
                                   scope4, sel_mo, sel_year))

if len(ser4):
    df4 = ser4.reset_index()
    df4.columns = ["Date", "Value"]
    df4["avg3"] = df4["Value"].rolling(3, min_periods=1).mean()
    fig4 = go.Figure()
    fig4.add_trace(go.Bar(x=df4["Date"], y=df4["Value"], name=mt4,
                          marker_color=BLUE, opacity=0.72))
    fig4.add_trace(go.Scatter(x=df4["Date"], y=df4["avg3"], name="3-day average",
                              mode="lines", line=dict(color=PURPLE, width=2)))
    if mt4 == "Orders":
        snap4 = E.build_snapshot(t2, t3, mk4, sel_mo, sel_year)
        tgt = snap4.raw["daily_target"]
        if tgt:
            fig4.add_hline(y=tgt, line_dash="dash", line_color=GREEN, line_width=2,
                           annotation_text=f"Daily plan rate {tgt:.0f}",
                           annotation_position="top left")
    chart_style(fig4, 300)
    fig4.update_layout(yaxis_title=mt4)
    st.plotly_chart(fig4, use_container_width=True)
else:
    st.caption("No data for this selection.")

st.divider()

# ══════════════════════════════════════════════════════════════════════
# S5 — API DEEP DIVE
# ══════════════════════════════════════════════════════════════════════
shdr("S5 · API channel deep dive")

paced_msg = E._pace(r["plan_msg_api"], cov)
paced_ord_api = E._pace(r["plan_ord_api"], cov)
paced_bud_api = E._pace(r["plan_bud_api"], cov)


def api_row(name, act, plan, paced, direction="up", pfx="", sfx="", dec=0):
    v = E.rag(act, paced if paced is not None else plan, direction,
              "paced" if paced is not None else "plan")
    return {"Metric": name,
            "Actual MTD": E.fmt(act, pfx, sfx, dec),
            "Plan (month)": E.fmt(plan, pfx, sfx, dec),
            f"Paced to D{cov.days_elapsed}": E.fmt(paced, pfx, sfx, dec),
            "vs paced": E.fmt_pct(act, paced),
            "vs full-month plan": E.fmt_pct(act, plan),
            "Status": v.label}


api_rows = [
    api_row("Messages sent", r["msg_api"], r["plan_msg_api"], paced_msg),
    {"Metric": "  · to customers", "Actual MTD": E.fmt(r["msg_cust"]),
     "Plan (month)": "n/a", f"Paced to D{cov.days_elapsed}": "n/a",
     "vs paced": "n/a", "vs full-month plan": "n/a", "Status": "not planned"},
    {"Metric": "  · to leads", "Actual MTD": E.fmt(r["msg_lead"]),
     "Plan (month)": "n/a", f"Paced to D{cov.days_elapsed}": "n/a",
     "vs paced": "n/a", "vs full-month plan": "n/a", "Status": "not planned"},
    api_row("API orders", r["ord_api"], r["plan_ord_api"], paced_ord_api),
    api_row("API CR%", r["cr_api"], r["plan_cr_api"], None, sfx="%", dec=2),
    api_row("API spend", r["spend_api"], r["plan_bud_api"], paced_bud_api,
            direction="spend", pfx="AED "),
    {"Metric": "API revenue", "Actual MTD": E.fmt(r["rev_api"], "AED "),
     "Plan (month)": E.fmt(r["plan_rev_api"], "AED "),
     f"Paced to D{cov.days_elapsed}": E.fmt(E._pace(r["plan_rev_api"], cov), "AED "),
     "vs paced": E.fmt_pct(r["rev_api"], E._pace(r["plan_rev_api"], cov)),
     "vs full-month plan": E.fmt_pct(r["rev_api"], r["plan_rev_api"]),
     "Status": E.rag(r["rev_api"], E._pace(r["plan_rev_api"], cov), "up", "paced").label},
    {"Metric": "API ROAS", "Actual MTD": E.fmt(r["roas_api"], suffix="x", dec=1),
     "Plan (month)": "n/a", f"Paced to D{cov.days_elapsed}": "n/a",
     "vs paced": "n/a", "vs full-month plan": "n/a", "Status": "not planned"},
]
# Open/read rate: tracked in T1 but not populated in T2 — absent, not zero.
for nm in ("Open rate %", "Read rate %"):
    api_rows.append({"Metric": nm, "Actual MTD": "n/a", "Plan (month)": "n/a",
                     "Paced to D%d" % cov.days_elapsed: "n/a", "vs paced": "n/a",
                     "vs full-month plan": "n/a", "Status": "not reported"})

table(pd.DataFrame(api_rows),
      "Both comparisons are shown side by side because they answer different questions: "
      "'vs paced' asks whether the channel is on track today, 'vs full-month plan' asks how "
      "much of the month's plan is already banked. Rows marked 'not reported' have no data in "
      "T2 — they are blank, not zero, and are not scored.")

st.divider()

# ══════════════════════════════════════════════════════════════════════
# S6 — PERIOD COMPARISON
# ══════════════════════════════════════════════════════════════════════
shdr("S6 · Period comparison")

all_days = sorted(t2["Day"].unique())
if len(all_days) >= 4:
    da_s, da_e, db_s, db_e = E.default_compare_periods(all_days)
    p1, p2, p3, p4 = st.columns(4)
    a_s = p1.date_input("Period A · start", value=da_s,
                        min_value=all_days[0], max_value=all_days[-1])
    a_e = p2.date_input("Period A · end", value=da_e,
                        min_value=all_days[0], max_value=all_days[-1])
    b_s = p3.date_input("Period B · start", value=db_s,
                        min_value=all_days[0], max_value=all_days[-1])
    b_e = p4.date_input("Period B · end", value=db_e,
                        min_value=all_days[0], max_value=all_days[-1])
    table(E.period_compare(t2, sel_mkt, a_s, a_e, b_s, b_e),
          "Δ% is a true change: (A − B) ÷ B. Identical periods read 0%. Direction accounts "
          "for polarity — a fall in CAC reads 'better', a rise in spend does not. "
          "Defaults compare the most recent 7 days against the 7 before.")
else:
    st.caption("Need at least 4 days of data to compare periods.")

st.divider()

# ══════════════════════════════════════════════════════════════════════
# S7 — TIMESERIES EXPLORER
# ══════════════════════════════════════════════════════════════════════
shdr("S7 · Timeseries explorer")

t7a, t7b, t7c = st.columns([2, 1.3, 1])
ts_mkts = t7a.multiselect("Markets", markets, default=markets, key="s7m")
ts_metric = t7b.selectbox("Metric", ["Orders", "Revenue", "Budget spent", "ROAS", "CAC"],
                          key="s7x")
ts_view = t7c.selectbox("View", ["Daily", "Cumulative"], key="s7v")

if ts_mkts:
    fig7 = go.Figure()
    summary = []
    for m in ts_mkts:
        if ts_metric == "Orders":
            s = E.daily_orders_series(t2, m, sel_mo, sel_year)
        elif ts_metric in ("Revenue", "Budget spent"):
            s = E.daily_metric_series(
                t2, E.REVENUE if ts_metric == "Revenue" else E.SPEND, m, sel_mo, sel_year)
        else:
            rev = E.daily_metric_series(t2, E.REVENUE, m, sel_mo, sel_year)
            sp = E.daily_metric_series(t2, E.SPEND, m, sel_mo, sel_year)
            od = E.daily_orders_series(t2, m, sel_mo, sel_year)
            s = (rev / sp.replace(0, np.nan)) if ts_metric == "ROAS" \
                else (sp / od.replace(0, np.nan))
        if not len(s):
            continue
        vals = list(s.cumsum().values) if ts_view == "Cumulative" else list(s.values)
        col = MCOLORS.get(m, "#888")
        fig7.add_trace(go.Scatter(x=list(s.index), y=vals, name=m, mode="lines+markers",
                                  line=dict(color=col, width=2.4),
                                  marker=dict(size=4.5, color=col,
                                              line=dict(color="white", width=1.2)),
                                  connectgaps=False))
        entries, active = cov.per_market.get(m, (0, 0))
        clean = s.dropna()
        summary.append({
            "Market": m,
            "Total" if ts_view == "Cumulative" else "Average/day":
                E.fmt(float(clean.sum()) if ts_view == "Cumulative"
                      else float(clean.mean()), dec=1),
            "Latest": E.fmt(float(clean.iloc[-1]) if len(clean) else None, dec=1),
            "Days reported": f"{entries}/{cov.days_elapsed}",
            "Days with orders": f"{active}/{cov.days_elapsed}",
        })
    chart_style(fig7, 330)
    fig7.update_layout(yaxis_title=ts_metric, xaxis=dict(tickangle=45))
    st.plotly_chart(fig7, use_container_width=True)
    table(pd.DataFrame(summary),
          "'Days reported' counts days the market submitted any figure. 'Days with orders' "
          "counts days it recorded a non-zero order. A gap between the two is a genuine "
          "zero-order day, not a missing feed — v5 conflated the two and understated coverage.")

st.divider()

# ══════════════════════════════════════════════════════════════════════
# S8 — ANALYTICAL DEPTH
# ══════════════════════════════════════════════════════════════════════
shdr("S8 · Efficiency and correlations")

s8a, _ = st.columns([1, 3])
mk8 = s8a.selectbox("Market", ["All"] + markets, key="s8m")
day_df = E.daily_frame(t2, mk8, sel_mo, sel_year)


def scatter_panel(title, x, y, xlab, ylab, color, question, invert_good=False):
    st.markdown(f"**{title}**")
    if day_df.empty or day_df[[x, y]].dropna().shape[0] < 4:
        st.caption("Not enough days to test this.")
        return
    d = day_df[[x, y]].dropna()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d[x], y=d[y], mode="markers",
                             marker=dict(size=8, color=color, opacity=0.7,
                                         line=dict(color="white", width=1))))
    z = np.polyfit(d[x], d[y], 1)
    xl = np.linspace(d[x].min(), d[x].max(), 50)
    fig.add_trace(go.Scatter(x=xl, y=np.poly1d(z)(xl), mode="lines",
                             line=dict(color=RED, dash="dash", width=1.5)))
    chart_style(fig, 280)
    fig.update_layout(xaxis_title=xlab, yaxis_title=ylab, showlegend=False,
                      hovermode="closest")
    st.plotly_chart(fig, use_container_width=True)
    rr = float(d.corr().iloc[0, 1])
    st.caption(f"r = {rr:+.2f} over {len(d)} days — {E.corr_band(rr)} "
               f"{'negative' if rr < 0 else 'positive'} relationship. {question}")


col1, col2 = st.columns(2)
with col1:
    st.markdown("**Efficiency map — spend vs ROAS vs API CR%**")
    pts = E.efficiency_points(t2, t3, sel_mo, sel_year, mk8)
    pts = [p for p in pts if p["roas"] is not None and p["cr_api"] is not None]
    if pts:
        fig_e = go.Figure()
        for p in pts:
            fig_e.add_trace(go.Scatter(
                x=[p["cr_api"]], y=[p["roas"]], mode="markers+text",
                marker=dict(size=max((p["budget"] ** 0.5) * 0.34, 16),
                            color=MCOLORS.get(p["market"], "#888"), opacity=0.55,
                            line=dict(color="white", width=2)),
                text=[f"  {p['market']}"], textposition="middle right",
                textfont=dict(size=12, color="#333"), name=p["market"],
                hovertemplate=(f"<b>{p['market']}</b><br>Spend: AED {p['budget']:,.0f}"
                               f"<br>ROAS: {p['roas']:.1f}x"
                               f"<br>API CR%: {p['cr_api']:.2f}%<extra></extra>")))
        chart_style(fig_e, 290)
        fig_e.update_layout(xaxis_title="API CR% (API orders ÷ API messages)",
                            yaxis_title="ROAS (all channels)", showlegend=False,
                            hovermode="closest")
        st.plotly_chart(fig_e, use_container_width=True)
        st.caption("Bubble size is spend. Up and to the right is more efficient. "
                   "CR% here is API orders over API messages — the same definition "
                   "S1 and S5 use, so the three sections now agree.")
with col2:
    scatter_panel("Does spending more buy more orders?", "spend", "orders",
                  "Daily spend (AED)", "Daily orders", BLUE,
                  "Spend alone is a weak lever if r is low — look at targeting and creative.")

col3, col4 = st.columns(2)
with col3:
    scatter_panel("Does CAC drift up through the month?", "day_num", "cac",
                  f"Day of {sel_label}", "CAC (AED)", AMBER,
                  "A positive r means acquisition gets more expensive late in the month.")
with col4:
    scatter_panel("Do more API messages produce more orders?", "messages", "api_orders",
                  "API messages sent", "API orders", GREEN,
                  "API orders are plotted against API messages — mixing all-channel orders "
                  "with API-only messages overstates the link.")

st.caption(f"Source: {src} · T2. Actuals + T3. Targets · cache refreshes every 60s · "
           f"{snap.market} · {sel_label} · day {cov.days_elapsed} of {cov.days_in_month} · "
           f"engine v6 ({len(snap.integrity)} integrity checks, "
           f"{len(failed)} failing)")

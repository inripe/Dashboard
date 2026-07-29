"""
INRIPE DM TRACKING DASHBOARD v7
Presentation only. All arithmetic lives in dm_engine.py.

v7 restructure
--------------
Two parts instead of eleven stacked sections.

  PART A  Management review   one screen: is the month landing, and where is
                              the gap coming from.
  PART B  Operational         tabs, one per metric family, entered only when a
                              question needs it.

Metric families are kept apart because they are not comparable:
  demand      orders, units, daily rate      scored against paced plan
  financial   revenue, spend, contribution   scored against paced plan
  efficiency  ROAS, CAC, CR%                 scored against full-month plan
  quality     coverage, integrity            scored against a threshold

Removed from v6: the duplicate scorecard, the standalone daily pulse, and the
API-specific section - API is a channel like any other and now uses the same
drill-down as Meta. Basket size is gone: it is a planning input, not a result.

Spend, burn and message volume are reported without a verdict. Spending more is
neither good nor bad on its own; CAC and ROAS judge whether it bought anything.
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

EXCEL_CANDIDATES = [
    "Digital_Marketing/DM_Tracking/DM_Planing_Tracking_2026_25JUL26_V1_21.xlsx",
    "DM_Planing_Tracking_2026_25JUL26_V1_21.xlsx",
]

GREEN, BLUE, PURPLE, AMBER, RED, GREY = (
    E.GREEN, E.BLUE, "#534AB7", E.AMBER, E.RED, E.GREY)
MCOLORS = {"UAE": "#2a78d6", "KSA": "#eb6834", "Qatar": "#1baf7a", "Egypt": "#e87ba4"}
CCOLORS = {"API": E.GREEN, "Meta": "#534AB7", "Meta API": "#6f68c9", "Meta Ecom": "#9a95dc"}

st.markdown("""
<style>
[data-testid="stAppViewContainer"]{background:#F8F9FA}
[data-testid="stSidebar"]{display:none}
.card{background:white;border-radius:12px;padding:18px 22px;margin:10px 0 16px;
      box-shadow:0 2px 8px rgba(0,0,0,0.06)}
.part{font-size:11px;font-weight:700;color:#8A8A8A;letter-spacing:0.14em;
      text-transform:uppercase;margin:26px 0 4px}
.part-title{font-size:20px;font-weight:700;color:#1A1A1A;margin:0 0 14px}
.commentary{background:white;border-radius:12px;padding:18px 22px;
            border-left:5px solid #1B4F8A;margin:10px 0 18px;
            box-shadow:0 2px 8px rgba(0,0,0,0.06)}
.commentary-title{font-size:11px;font-weight:700;color:#1B4F8A;
                  text-transform:uppercase;letter-spacing:0.09em;margin-bottom:9px}
.commentary-text{font-size:14px;color:#2D3436;line-height:1.75;margin:0}
.c-good{color:#1A6B4A;font-weight:600}
.c-warn{color:#854F0B;font-weight:600}
.c-risk{color:#A32D2D;font-weight:600}
.c-info{color:#555}
.kpi{background:white;border-radius:12px;padding:16px 18px;
     box-shadow:0 2px 8px rgba(0,0,0,0.06);height:100%}
.kpi-label{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.06em}
.kpi-val{font-size:27px;font-weight:700;color:#1A1A1A;margin:5px 0 2px;line-height:1.1}
.kpi-sub{font-size:12px;color:#666}
.kpi-verdict{font-size:12px;font-weight:700;margin-top:7px}
.dev{position:relative;height:13px;background:#F1F2F4;border-radius:3px;margin-top:9px}
.dev-mid{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:#9AA0A6}
.dev-fill{position:absolute;top:3px;bottom:3px;border-radius:2px;opacity:0.92}
.dev-cap{position:absolute;top:1px;bottom:1px;width:2.5px;border-radius:1px}
.banner{border-radius:10px;padding:13px 18px;margin:8px 0 14px;font-size:13.5px;line-height:1.6}
.banner-bad{background:#FDF2F2;border-left:5px solid #A32D2D;color:#5c1a1a}
.banner-ok{background:#F1F8F4;border-left:5px solid #1A6B4A;color:#14432f}
.banner-warn{background:#FFF8EC;border-left:5px solid #854F0B;color:#5c3f0b}
.note{font-size:11.5px;color:#8A8A8A;margin-top:-4px;margin-bottom:12px;line-height:1.6}
.chk{display:flex;align-items:flex-start;gap:10px;padding:6px 0;font-size:12.5px;
     border-bottom:0.5px solid #f2f2f2}
.chk:last-child{border-bottom:none}
.chk-pill{font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;
          color:white;flex-shrink:0;margin-top:1px;width:44px;text-align:center}
.chk-name{width:330px;flex-shrink:0;color:#333}
.chk-detail{color:#777;font-size:12px}
.legend{background:white;border-radius:10px;padding:14px 18px;margin:2px 0 14px;
        box-shadow:0 2px 8px rgba(0,0,0,0.06)}
.leg-row{display:flex;align-items:flex-start;gap:12px;padding:6px 0;
         border-bottom:0.5px solid #f4f4f4;font-size:12.5px}
.leg-row:last-child{border-bottom:none}
.leg-chip{font-size:10px;font-weight:700;letter-spacing:0.04em;padding:3px 10px;
          border-radius:11px;color:white;flex-shrink:0;width:76px;text-align:center;
          margin-top:1px}
.leg-rule{width:290px;flex-shrink:0;color:#555;font-family:monospace;font-size:11.5px}
.leg-do{color:#333}
.leg-head{font-size:11px;font-weight:700;color:#8A8A8A;letter-spacing:0.1em;
          text-transform:uppercase;margin-bottom:8px}
.stTabs [data-baseweb="tab-list"]{gap:4px}
.stTabs [data-baseweb="tab"]{font-size:13px;font-weight:600;padding:8px 16px}
</style>
""", unsafe_allow_html=True)

ARROW = {"up": "▲", "down": "▼", "flat": "—"}
ARROW_COLOR = {"up": GREEN, "down": RED, "flat": "#999"}
DEV_SCALE = 50.0


def dev_bar(v, height_css="dev"):
    """Bar centred on plan. Distance and direction from target are the visual."""
    if v.ratio is None:
        return f"<div class='{height_css}'><div class='dev-mid'></div></div>"
    d = v.ratio - 100.0
    clipped = abs(d) > DEV_SCALE
    mag = min(abs(d), DEV_SCALE) / DEV_SCALE * 50.0
    if d >= 0:
        fill, cap_left = f"left:50%;width:{mag}%;background:{v.color}", 50.0 + mag
    else:
        fill, cap_left = f"left:{50-mag}%;width:{mag}%;background:{v.color}", 50.0 - mag
    cap = (f"<div class='dev-cap' style='left:{cap_left}%;background:{v.color}'></div>"
           if clipped else "")
    return (f"<div class='{height_css}'><div class='dev-mid'></div>"
            f"<div class='dev-fill' style='{fill}'></div>{cap}</div>")


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
    if df is None or df.empty:
        st.caption("No rows for this selection.")
        return
    st.dataframe(df, use_container_width=True, hide_index=True,
                 height=min(35 * (len(df) + 1) + 3, 620))
    if note:
        st.markdown(f"<div class='note'>{note}</div>", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════
# ACCESS GATE
# ═════════════════════════════════════════════════════════════════════
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
                                  label_visibility="collapsed", placeholder="Password")
            if st.button("Open dashboard", use_container_width=True):
                if entry == _pw:
                    st.session_state["dm_auth"] = True
                    st.rerun()
                else:
                    st.error("That password is not correct.")
        st.stop()


# ═════════════════════════════════════════════════════════════════════
# LOAD
# ═════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=60)
def load():
    if SP.is_configured():
        buf, meta = SP.fetch_workbook()
        return E.load_data(buf) + (meta,)
    for c in EXCEL_CANDIDATES:
        if Path(c).exists():
            return E.load_data(c) + ({"name": c, "local": True},)
    raise FileNotFoundError("Workbook not found: " + ", ".join(EXCEL_CANDIDATES))


try:
    t2, t3, META = load()
except Exception as e:
    st.error(f"Cannot load the workbook.\n\n{e}")
    if not SP.is_configured():
        st.caption("SharePoint is not configured. Missing: " + ", ".join(SP.missing_keys()))
    st.stop()

if t2.empty:
    st.warning("T2. Actuals has no usable rows.")
    st.stop()

markets = sorted(t2["Market"].unique().tolist())
last_dt = t2["Date"].max()

# Last entry: the workbook edit timestamp is more precise than the data date,
# because T2 carries dates only.
if META.get("modified"):
    stamp = META["modified"].replace("T", " ")[:16] + " UTC"
    stamp_label = "Workbook updated"
    who = META.get("modified_by")
else:
    stamp = last_dt.strftime("%d %b %Y") if pd.notna(last_dt) else "n/a"
    stamp_label = "Last entry"
    who = None

st.markdown(f"""
<div style='background:linear-gradient(135deg,#1B4F8A 0%,#1A6B4A 100%);
padding:15px 24px;border-radius:10px;margin-bottom:14px;
display:flex;justify-content:space-between;align-items:center'>
<div>
<div style='color:white;font-size:19px;font-weight:700'>📊 DM Tracking · Inripe 2026</div>
<div style='color:#BDD7F5;font-size:12px;margin-top:3px'>
Management review · operational detail · v7</div>
</div>
<div style='text-align:right;color:#BDD7F5;font-size:12px'>
Latest data <b style='color:white'>{last_dt.strftime('%d %b %Y') if pd.notna(last_dt) else 'n/a'}</b><br>
{stamp_label} <b style='color:white'>{stamp}</b>{f"<br>by {who}" if who else ""}
</div></div>""", unsafe_allow_html=True)

c1, c2, _ = st.columns([1, 1, 3])
sel_mkt = c1.selectbox("Market", ["All"] + markets)
pairs = sorted({(int(y), int(m)) for y, m in zip(t2["Year"], t2["Month"])})
labels = [pd.Timestamp(year=y, month=m, day=1).strftime("%b %Y") for y, m in pairs]
sel_label = c2.selectbox("Month", labels, index=len(labels) - 1)
sel_year, sel_mo = pairs[labels.index(sel_label)]

snap = E.build_snapshot(t2, t3, sel_mkt, sel_mo, sel_year)
cov, r = snap.coverage, snap.raw
GAP = E.gap_contribution(t2, t3, sel_mo, sel_year, cov)
GAP_SCOPED = GAP if sel_mkt == "All" else GAP[GAP["Market"] == sel_mkt].copy()

failed = [f for f in snap.integrity if not f["pass"]]
bad_data = [l for l in snap.lines if l.verdict and l.verdict.label == "CHECK DATA"]

# ═════════════════════════════════════════════════════════════════════
# PART A — MANAGEMENT REVIEW
# ═════════════════════════════════════════════════════════════════════
st.markdown("<div class='part'>Part A</div>"
            "<div class='part-title'>Management review</div>", unsafe_allow_html=True)

if bad_data:
    names = ", ".join(l.label for l in bad_data)
    st.markdown(f"<div class='banner banner-bad'><b>Implausible values detected:</b> {names}. "
                f"These are almost certainly data entry faults — a misplaced decimal or a "
                f"value in the wrong column. Verdicts are suppressed until corrected.</div>",
                unsafe_allow_html=True)
elif failed:
    st.markdown(f"<div class='banner banner-bad'><b>{len(failed)} of {len(snap.integrity)} "
                f"data checks failed.</b> " + "; ".join(f["check"] for f in failed) +
                ". See the Data quality tab.</div>", unsafe_allow_html=True)
else:
    st.markdown(f"<div class='banner banner-ok'><b>All {len(snap.integrity)} data checks pass.</b> "
                f"Day {cov.days_elapsed} of {cov.days_in_month}, "
                f"{cov.days_remaining} remaining. Figures below can be acted on.</div>",
                unsafe_allow_html=True)

body = " ".join(f"<span class='c-{sev}'>{txt}</span>"
                for sev, txt in E.build_commentary(snap, GAP_SCOPED))
st.markdown(f"""<div class='commentary'>
<div class='commentary-title'>Executive commentary · {snap.market} · {sel_label} · auto-generated</div>
<div class='commentary-text'>{body}</div></div>""", unsafe_allow_html=True)

# ── four KPIs, nothing else ──────────────────────────────────────────
KPI = [("orders", "Orders", "demand"), ("revenue", "Revenue", "financial"),
       ("spend", "Budget spent", "financial"), ("roas", "ROAS", "efficiency"),
       ("cac", "CAC", "efficiency")]
cols = st.columns(5)
for col, (key, label, family) in zip(cols, KPI):
    ln = snap.line(key)
    if ln is None:
        continue
    v = ln.verdict
    f = lambda x: E.fmt(x, ln.prefix, ln.suffix, ln.dec)
    basis_val = ln.paced if ln.basis == "paced" else ln.plan
    basis_txt = ("paced " if ln.basis == "paced" else "plan ") + f(basis_val)
    col.markdown(f"""<div class='kpi'>
      <div class='kpi-label'>{label}</div>
      <div class='kpi-val'>{f(ln.actual)}</div>
      <div class='kpi-sub'>vs {basis_txt} · month plan {f(ln.plan)}</div>
      {dev_bar(v)}
      <div class='kpi-verdict' style='color:{v.color}'>{v.label}
        <span style='color:{ARROW_COLOR[ln.trend]}'>{ARROW[ln.trend]}</span></div>
    </div>""", unsafe_allow_html=True)

st.markdown(f"<div class='note'>Paced plan = month plan x {cov.days_elapsed}/{cov.days_in_month} "
            f"days elapsed — what you should have by today to finish on target. "
            "Orders and revenue are scored against it. "
            "Spend carries no verdict — spending more is neither good nor bad on its own; "
            "ROAS and CAC judge whether it bought anything. The arrow is the last 7 days "
            "against the 7 before.</div>", unsafe_allow_html=True)

# ── where the next dirham should go ──────────────────────────────────
st.markdown("#### Where the next dirham should go")
ALLOC = E.allocation_view(t2, t3, sel_mo, sel_year, cov, sel_mkt)

if ALLOC.empty:
    st.caption("No channel plan available to allocate against.")
else:
    disp = pd.DataFrame({
        "Market": ALLOC["Market"],
        "Channel": ALLOC["Channel"],
        "Orders": ALLOC["Orders"].map(lambda v: f"{v:,.0f}"),
        "vs paced": ALLOC["vs paced"].map(lambda v: "n/a" if v is None else f"{v:.0f}%"),
        "Budget used": ALLOC["Budget used"].map(lambda v: "n/a" if v is None else f"{v:.0f}%"),
        "Unspent (AED)": ALLOC["Headroom"].map(
            lambda v: "over" if v is None or v < 0 else f"{v:,.0f}"),
        "CAC": ALLOC["CAC"].map(lambda v: "n/a" if v is None else f"{v:.1f}"),
        "Plan CAC": ALLOC["Plan CAC"].map(lambda v: "n/a" if v is None else f"{v:.1f}"),
        "Cost vs plan": ALLOC["Cost index"].map(
            lambda v: "n/a" if v is None else f"{v:.2f}x"),
        "ROAS": ALLOC["ROAS"].map(lambda v: "n/a" if v is None else f"{v:.1f}x"),
        "Read": ALLOC["Read"],
    })
    table(disp,
          "Sorted by what an order actually costs, cheapest first — so the table reads in "
          "the order money should flow. Cost vs plan is actual CAC divided by the CAC the "
          "plan implied, so 1.00x is on budget and 3.00x is three times what each order was "
          "costed at. Budget used is spend against the paced budget: it separates a channel "
          "that has stopped working from one that simply has not spent its money, which look "
          "identical on pace alone. Read is written from that row's own figures and changes "
          "as the data does.")

    # headline: idle money first, then the swap
    rec = E.reallocation_estimate(ALLOC)
    idle = ALLOC[ALLOC["Headroom"] > 0]
    if len(idle):
        top_idle = idle.loc[idle["Headroom"].idxmax()]
        st.markdown(
            f"<div class='banner banner-warn'><b>AED "
            f"{idle['Headroom'].sum():,.0f} of paced budget has not gone out</b>, "
            f"AED {top_idle['Headroom']:,.0f} of it in {top_idle['Market']} "
            f"{top_idle['Channel']} — which is at {top_idle['vs paced']:.0f}% of paced "
            f"orders on {top_idle['Budget used']:.0f}% of its budget. With "
            f"{cov.days_remaining} days left, that is the constraint, not the channel.</div>",
            unsafe_allow_html=True)
    if rec:
        st.markdown(
            f"<div class='banner banner-bad'><b>AED {rec['freed']:,.0f} in "
            f"{rec['from']} bought {rec['current_orders']:,} orders.</b> The same money at "
            f"{rec['to']}'s current CAC of {rec['to_cac']:.1f} would buy roughly "
            f"{rec['would_buy']:,} — about {rec['delta']:,} more. A ceiling, not a forecast: "
            f"it assumes the cheaper channel absorbs the budget without its cost rising, "
            f"which no channel does indefinitely.</div>", unsafe_allow_html=True)

# ── will we land it ──────────────────────────────────────────────────
st.markdown("#### Will we land the month?")
m2 = st.selectbox("Metric", ["Orders", "Revenue", "Budget spent"], key="runrate",
                  label_visibility="collapsed")
key = {"Orders": "orders", "Revenue": "revenue", "Budget spent": "spend"}[m2]
ln = snap.line(key)
series = (E.daily_orders_series(t2, None if sel_mkt == "All" else sel_mkt, sel_mo, sel_year)
          if key == "orders" else
          E.daily_metric_series(t2, E.REVENUE if key == "revenue" else E.SPEND,
                                None if sel_mkt == "All" else sel_mkt, sel_mo, sel_year))

if len(series) and ln and ln.plan:
    cum = list(series.cumsum().values)
    plan_cum = [ln.plan / cov.days_in_month * d for d in range(1, cov.days_in_month + 1)]
    rate = ln.actual / cov.days_elapsed
    proj = [cum[-1] + rate * d for d in range(0, cov.days_remaining + 1)]
    xs = list(range(cov.days_elapsed, cov.days_in_month + 1))
    fig = go.Figure()
    if len(xs) > 1:
        upper = plan_cum[cov.days_elapsed - 1:][:len(xs)]
        col_fill = ("rgba(163,45,45,0.07)" if (ln.eom or 0) < ln.plan
                    else "rgba(26,107,74,0.07)")
        fig.add_trace(go.Scatter(x=xs + xs[::-1], y=upper + proj[:len(xs)][::-1],
                                 fill="toself", fillcolor=col_fill,
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
        c = (GREEN if (ln.eom or 0) >= ln.plan * 0.9
             else AMBER if (ln.eom or 0) >= ln.plan * 0.7 else RED)
        fig.add_trace(go.Scatter(x=xs, y=proj[:len(xs)], mode="lines",
                                 name=f"Run rate → {E.fmt(ln.eom, ln.prefix)}",
                                 line=dict(color=c, dash="dot", width=2)))
    fig.add_hline(y=ln.plan, line_color=BLUE, line_width=1, opacity=0.35,
                  annotation_text=f"Plan {E.fmt(ln.plan, ln.prefix)}",
                  annotation_position="bottom right")
    chart_style(fig, 300)
    fig.update_layout(xaxis_title=f"Day of {sel_label}", yaxis_title=m2,
                      legend=dict(orientation="h", y=-0.22))
    st.plotly_chart(fig, use_container_width=True)
    st.markdown(f"<div class='note'>Holds the current "
                f"{E.fmt(rate, ln.prefix, dec=1)}/day rate for the remaining "
                f"{cov.days_remaining} days. A straight run rate, not a forecast.</div>",
                unsafe_allow_html=True)

# ═════════════════════════════════════════════════════════════════════
# PART B — OPERATIONAL
# ═════════════════════════════════════════════════════════════════════
st.markdown("<div class='part'>Part B</div>"
            "<div class='part-title'>Operational detail</div>", unsafe_allow_html=True)

TABS = st.tabs(["Demand", "Channels", "Efficiency", "Financial",
                "Comparison", "Trends", "Data quality"])

# ── DEMAND ───────────────────────────────────────────────────────────
with TABS[0]:
    dem = []
    for k in ("orders", "units", "daily_orders"):
        ln = snap.line(k)
        if ln is None:
            continue
        f = lambda x: E.fmt(x, ln.prefix, ln.suffix, ln.dec)
        dem.append({"Metric": ln.label, "Plan (month)": f(ln.plan),
                    f"Paced to D{cov.days_elapsed}": f(ln.paced) if ln.paced else "n/a",
                    "Actual MTD": f(ln.actual), "Trend 7d": ARROW[ln.trend],
                    "EOM forecast": f(ln.eom) if ln.eom is not None else "n/a",
                    "EOM % plan": E.fmt_pct(ln.eom, ln.plan) if ln.eom else "n/a",
                    "Scored against": "paced plan" if ln.basis == "paced" else "full-month plan",
                    "Status": ln.verdict.label})
    table(pd.DataFrame(dem))

    st.markdown("##### By market")
    rows = []
    for m in markets:
        s = E.build_snapshot(t2, t3, m, sel_mo, sel_year)
        o = s.line("orders")
        ent, act = cov.per_market.get(m, (0, 0))
        rows.append({"Market": m, "Orders": E.fmt(o.actual),
                     "Paced plan": E.fmt(o.paced), "vs paced": E.fmt_pct(o.actual, o.paced),
                     "EOM": E.fmt(o.eom), "Month plan": E.fmt(o.plan),
                     "EOM % plan": E.fmt_pct(o.eom, o.plan),
                     "Days reported": f"{ent}/{cov.days_elapsed}",
                     "Status": o.verdict.label})
    table(pd.DataFrame(rows))

# ── CHANNELS ─────────────────────────────────────────────────────────
with TABS[1]:
    cc1, cc2 = st.columns([1, 3])
    split = cc1.toggle("Split Meta into API / Ecom", value=False)
    table(E.channel_summary(t2, t3, sel_mkt, sel_mo, sel_year, cov, split),
          "Meta is consolidated by default because targets are set at Meta level. "
          "Split shows the two platforms, which have no separate plan of their own.")

    planned_only = E.planned_only_channels(t3, sel_mkt, sel_mo, sel_year)
    if planned_only:
        st.markdown(
            f"<div class='note'>Planned but not reporting: <b>{', '.join(planned_only)}</b>. "
            f"{'These channels have' if len(planned_only) > 1 else 'This channel has'} a "
            f"target in T3 but no actuals in T2, so {'they are' if len(planned_only) > 1 else 'it is'} "
            f"excluded from the tables above rather than shown as zero. Any orders planned "
            f"there are still counted in the market's total target.</div>",
            unsafe_allow_html=True)

    st.markdown("##### Channel drill-down")
    ch = st.selectbox("Channel", E.CHANNEL_ORDER, key="chdetail")
    table(E.channel_detail(t2, t3, ch, sel_mkt, sel_mo, sel_year, cov),
          "'vs paced' asks whether the channel is on track today. 'vs full-month plan' asks "
          "how much of the month is already banked. Spend and message volume carry no "
          "verdict — they are inputs, judged by ROAS and CAC below them.")

    st.markdown("##### Market × channel")
    table(E.market_channel_breakdown(t2, t3, sel_mo, sel_year, cov))

# ── EFFICIENCY ───────────────────────────────────────────────────────
with TABS[2]:
    eff = []
    for k in ("roas", "cac", "cr_api", "cr_meta"):
        ln = snap.line(k)
        if ln is None:
            continue
        f = lambda x: E.fmt(x, ln.prefix, ln.suffix, ln.dec)
        eff.append({"Metric": ln.label, "Actual MTD": f(ln.actual),
                    "Plan (month)": f(ln.plan), "vs plan": E.fmt_pct(ln.actual, ln.plan),
                    "Status": ln.verdict.label})
    table(pd.DataFrame(eff),
          "Efficiency ratios are scored against the full-month plan, not a paced one — "
          "a ratio does not accumulate, so pacing it is meaningless.")

    mk8 = st.selectbox("Market", ["All"] + markets, key="effm")
    day_df = E.daily_frame(t2, mk8, sel_mo, sel_year)

    def scatter(title, x, y, xlab, ylab, colour, note):
        st.markdown(f"**{title}**")
        if day_df.empty or day_df[[x, y]].dropna().shape[0] < 4:
            st.caption("Not enough days to test this.")
            return
        d = day_df[[x, y]].dropna()
        fig = go.Figure(go.Scatter(x=d[x], y=d[y], mode="markers",
                                   marker=dict(size=8, color=colour, opacity=0.7,
                                               line=dict(color="white", width=1))))
        z = np.polyfit(d[x], d[y], 1)
        xl = np.linspace(d[x].min(), d[x].max(), 50)
        fig.add_trace(go.Scatter(x=xl, y=np.poly1d(z)(xl), mode="lines",
                                 line=dict(color=RED, dash="dash", width=1.5)))
        chart_style(fig, 260)
        fig.update_layout(xaxis_title=xlab, yaxis_title=ylab, showlegend=False,
                          hovermode="closest")
        st.plotly_chart(fig, use_container_width=True)
        rr = float(d.corr().iloc[0, 1])
        st.caption(f"r = {rr:+.2f} over {len(d)} days — {E.corr_band(rr)}. {note}")

    e1, e2 = st.columns(2)
    with e1:
        scatter("Does spending more buy more orders?", "spend", "orders",
                "Daily spend (AED)", "Daily orders", BLUE,
                "A weak r means spend alone is not the lever.")
    with e2:
        scatter("Does CAC drift up through the month?", "day_num", "cac",
                f"Day of {sel_label}", "CAC (AED)", AMBER,
                "Positive r means acquisition gets more expensive late in the month.")

# ── FINANCIAL ────────────────────────────────────────────────────────
with TABS[3]:
    table(E.financial_summary(t2, t3, sel_mkt, sel_mo, sel_year, cov),
          "Money only, kept apart from volume so the two are never scored alike. "
          "Budget spent carries no verdict by design.")

    st.markdown("##### Spend and return by market")
    frows = []
    for m in markets:
        sp = E.actual(t2, E.SPEND, market=m, month=sel_mo, year=sel_year)
        rev = E.actual(t2, E.REVENUE, market=m, month=sel_mo, year=sel_year)
        o = E.total_orders(t2, market=m, month=sel_mo, year=sel_year)
        pb = E.target(t3, E.TGT_BUDGET, m, sel_mo, sel_year, "Total")
        paced = E._pace(pb, cov)
        frows.append({"Market": m, "Spend": E.fmt(sp, "AED "),
                      "Paced budget": E.fmt(paced, "AED "),
                      "vs paced": E.fmt_pct(sp, paced),
                      "Revenue": E.fmt(rev, "AED "),
                      "ROAS": f"{rev/sp:.1f}x" if sp else "n/a",
                      "CAC": f"AED {sp/o:.1f}" if o else "n/a",
                      "Contribution": E.fmt((rev - sp) if None not in (rev, sp) else None, "AED ")})
    table(pd.DataFrame(frows),
          "'vs paced' on spend is reported without a verdict. Whether an overspend is a "
          "problem depends on the CAC and ROAS beside it, not on the overspend itself.")

# ── COMPARISON ───────────────────────────────────────────────────────
with TABS[4]:
    all_days = sorted(t2["Day"].unique())
    if len(all_days) < 4:
        st.caption("At least 4 days of data are needed to compare two periods.")
    else:
        presets = E.cmp_presets(all_days)
        pk = list(presets.keys())
        p1, p2 = st.columns([1.4, 2.6])
        preset = p1.selectbox("Preset", pk + ["Custom"], key="cmp_preset")
        if preset != "Custom":
            da_s, da_e, db_s, db_e = presets[preset]
        else:
            da_s, da_e, db_s, db_e = E.default_compare_periods(all_days)

        d1, d2, d3, d4 = st.columns(4)
        lo, hi = all_days[0], all_days[-1]
        a_s = d1.date_input("A · from", value=da_s, min_value=lo, max_value=hi, key="cA1")
        a_e = d2.date_input("A · to", value=da_e, min_value=lo, max_value=hi, key="cA2")
        b_s = d3.date_input("B · from", value=db_s, min_value=lo, max_value=hi, key="cB1")
        b_e = d4.date_input("B · to", value=db_e, min_value=lo, max_value=hi, key="cB2")

        f1, f2, f3 = st.columns([2, 2, 1.2])
        cmp_mkts = f1.multiselect("Markets", markets, default=markets, key="cmp_m")
        cmp_split = f3.toggle("Split Meta", value=False, key="cmp_split")
        chan_opts = (["API", "Meta API", "Meta Ecom"] if cmp_split else list(E.CHANNEL_ORDER))
        cmp_chans = f2.multiselect("Channels", chan_opts, default=chan_opts, key="cmp_c")

        AR, BR = (a_s, a_e), (b_s, b_e)
        if a_s > a_e or b_s > b_e:
            st.error("Each period's start date must fall on or before its end date.")
        elif not cmp_mkts or not cmp_chans:
            st.caption("Select at least one market and one channel.")
        else:
            kw = dict(markets=cmp_mkts, channels=cmp_chans, split_meta=cmp_split)

            body_c = " ".join(f"<span class='c-{sev}'>{txt}</span>"
                              for sev, txt in E.cmp_summary(t2, AR, BR, **kw))
            st.markdown(f"""<div class='commentary'>
<div class='commentary-title'>What changed · {a_s:%d %b} – {a_e:%d %b} vs {b_s:%d %b} – {b_e:%d %b}</div>
<div class='commentary-text'>{body_c}</div></div>""", unsafe_allow_html=True)

            st.markdown("##### Headline")
            table(E.cmp_headline(t2, AR, BR, **kw),
                  "Direction reads the move, not the size: a falling CAC is better, a rising "
                  "one is worse. Spend reports higher or lower without a verdict, because "
                  "spending more is neither good nor bad on its own.")

            st.markdown("##### Market and channel detail")
            H = E.cmp_hierarchy(t2, AR, BR, **kw)
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
                "CAC B→A": [f"{b:.1f}→{a:.1f}" if a and b else
                            (f"—→{a:.1f}" if a else "n/a")
                            for a, b in zip(H["A CAC"], H["B CAC"])],
                "ROAS B→A": [f"{b:.1f}→{a:.1f}x" if a and b else
                             (f"—→{a:.1f}x" if a else "n/a")
                             for a, b in zip(H["A ROAS"], H["B ROAS"])],
                "Share of change": H["Share of change"].map(
                    lambda v: "" if pd.isna(v) else f"{v:.0f}%"),
            })
            table(disp,
                  "Group first, then each market, then the channels inside it. Markets are "
                  "ordered by how much they moved, so whatever drove the change sits at the "
                  "top. Share of change is each market's portion of the total movement, "
                  "counting falls as well as rises. 'new' means period B had nothing to "
                  "compare against. CAC and ROAS read oldest first, so the arrow runs the "
                  "way time does.")

            st.markdown("##### Day by day, aligned")
            D = E.cmp_daily(t2, AR, BR, **kw)
            figc = go.Figure()
            figc.add_trace(go.Bar(x=D["Day"], y=D["Period B"], name="Period B",
                                  marker_color="#B4B2A9", opacity=0.85,
                                  customdata=D["B date"],
                                  hovertemplate="%{customdata}: %{y:.0f}<extra>Period B</extra>"))
            figc.add_trace(go.Bar(x=D["Day"], y=D["Period A"], name="Period A",
                                  marker_color=BLUE,
                                  customdata=D["A date"],
                                  hovertemplate="%{customdata}: %{y:.0f}<extra>Period A</extra>"))
            chart_style(figc, 280)
            figc.update_layout(barmode="group", yaxis_title="Orders",
                               hovermode="x unified")
            st.plotly_chart(figc, use_container_width=True)
            st.markdown("<div class='note'>Days are aligned by position in each range, not by "
                        "calendar date, so day 1 of A sits against day 1 of B and two windows "
                        "of different length stay readable together. Hover for the real "
                        "dates.</div>", unsafe_allow_html=True)


# ── TRENDS ───────────────────────────────────────────────────────────
with TABS[5]:
    t1c, t2c, t3c, t4c = st.columns([1.6, 1.2, 1.2, 1])
    ts_mkts = t1c.multiselect("Markets", markets, default=markets, key="tsm")
    ts_chan = t2c.selectbox("Channel", ["All channels"] + E.CHANNEL_ORDER
                            + E.ACTUAL_PLATFORMS, key="tsc")
    ts_metric = t3c.selectbox("Metric", ["Orders", "Revenue", "Budget spent"], key="tsx")
    ts_view = t4c.selectbox("View", ["Daily", "Cumulative"], key="tsv")

    def series_for(market, channel, metric):
        plats = (None if channel == "All channels"
                 else E.CHANNEL_GROUPS[channel] if channel in E.CHANNEL_GROUPS
                 else [channel])
        d = t2[(t2["Month"] == sel_mo) & (t2["Year"] == sel_year) & (t2["Market"] == market)]
        if plats:
            d = d[d["Platform"].isin(plats)]
        if metric == "Orders":
            d = d[d["Metric"].isin(E.ORDER_METRICS_ALL)]
        else:
            d = d[d["Metric"] == (E.REVENUE if metric == "Revenue" else E.SPEND)]
        return d.groupby("Date")["Value"].sum().sort_index() if not d.empty else pd.Series(dtype=float)

    fig = go.Figure()
    summary = []
    for m in ts_mkts:
        s = series_for(m, ts_chan, ts_metric)
        if not len(s):
            continue
        vals = list(s.cumsum().values) if ts_view == "Cumulative" else list(s.values)
        c = MCOLORS.get(m, "#888")
        fig.add_trace(go.Scatter(x=list(s.index), y=vals, name=m, mode="lines+markers",
                                 line=dict(color=c, width=2.4),
                                 marker=dict(size=4.5, color=c,
                                             line=dict(color="white", width=1.2))))
        ent, actv = cov.per_market.get(m, (0, 0))
        summary.append({"Market": m,
                        "Average/day": E.fmt(float(s.mean()), dec=1),
                        "Total": E.fmt(float(s.sum())),
                        "Latest": E.fmt(float(s.iloc[-1]), dec=1),
                        "Days reported": f"{ent}/{cov.days_elapsed}",
                        "Days with orders": f"{actv}/{cov.days_elapsed}"})
    if summary:
        chart_style(fig, 320)
        fig.update_layout(yaxis_title=f"{ts_metric} · {ts_chan}", xaxis=dict(tickangle=45))
        st.plotly_chart(fig, use_container_width=True)
        table(pd.DataFrame(summary),
              "'Days reported' counts days the market submitted any figure. 'Days with orders' "
              "counts days it recorded a non-zero order. A gap between them is a real "
              "zero-order day, not a missing feed.")
    else:
        st.caption("No data for this combination.")

# ── DATA QUALITY ─────────────────────────────────────────────────────
with TABS[6]:
    html = ""
    for f in snap.integrity:
        col = GREEN if f["pass"] else (RED if f["severity"] == "high" else AMBER)
        html += (f"<div class='chk'><div class='chk-pill' style='background:{col}'>"
                 f"{'PASS' if f['pass'] else 'FAIL'}</div>"
                 f"<div class='chk-name'>{f['check']}</div>"
                 f"<div class='chk-detail'>{f['detail']}</div></div>")
    st.markdown(f"<div class='card'>{html}</div>", unsafe_allow_html=True)

    st.markdown("##### Plausibility")
    if bad_data:
        for l in bad_data:
            st.markdown(f"<div class='banner banner-bad'><b>{l.label}</b> — "
                        f"{l.verdict.note}. Value shown: "
                        f"{E.fmt(l.actual, l.prefix, l.suffix, l.dec)}.</div>",
                        unsafe_allow_html=True)
    else:
        st.markdown("<div class='banner banner-ok'>No implausible values. Every metric sits "
                    "inside a range a real result could take.</div>", unsafe_allow_html=True)

    st.markdown("##### Reporting coverage")
    crows = [{"Market": m, "Days reported": f"{e}/{cov.days_elapsed}",
              "Days with orders": f"{a}/{cov.days_elapsed}",
              "Coverage": f"{e/cov.days_elapsed*100:.0f}%" if cov.days_elapsed else "n/a",
              "Scored": "yes" if not cov.gate(m)[0] else "no — too thin"}
             for m, (e, a) in sorted(cov.per_market.items())]
    table(pd.DataFrame(crows))

src = (f"SharePoint · {META.get('name')}" if not META.get("local")
       else f"local file · {META.get('name')}")
st.caption(f"Source: {src} · T2. Actuals + T3. Targets · refreshes every 60s · "
           f"{snap.market} · {sel_label} · day {cov.days_elapsed} of {cov.days_in_month} · "
           f"engine v7 · {len(snap.integrity)} checks, {len(failed)} failing")

"""Inripe — Sales performance.

Presentation only. Every figure comes from metrics_engine, which holds the
definitions, so a number cannot mean two things on two screens.

Two levels. The management screen is five cards on one page: orders, units
and revenue as a chain, then margin as the outcome. Each card opens a
drill-down that explains it, in four blocks that are always in the same
order — where the gap went, the cross-tab, the dimensional split, and the
structural view. A manager learns the shape once.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

# The read time is stamped in Cairo, not the machine clock. Locally that is
# Dubai and on Streamlit Cloud it is UTC, so the same line would otherwise
# read three different times depending on where it happened to run.
TZ = ZoneInfo("Africa/Cairo")

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

import metrics_engine as me
import plan_engine as pe
import variance_engine as ve
from data_loader import load_plan, load_actuals_any

YEAR = 2026
MARKETS = me.MARKETS
MONTHS = me.MONTHS
ALL_MK, YTD = "All markets", "Full year"

BLUE, ORANGE, TEAL, AMBER, GREY = "#378ADD", "#D85A30", "#1D9E75", "#EF9F27", "#B4B2A9"
GOOD, WARN, BAD, NEUT = "#1D9E75", "#EF9F27", "#D85A30", "#C2C0B8"
SERIES = [BLUE, ORANGE, TEAL, AMBER, "#E87BA4", GREY]

st.set_page_config(page_title="Inripe · Sales performance", layout="wide")

pio.templates["inripe"] = go.layout.Template(layout=dict(
    font=dict(family="-apple-system, Helvetica Neue, sans-serif", size=12,
              color="#4a4842"),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    colorway=SERIES,
    xaxis=dict(showgrid=False, zeroline=False, linecolor="#e2e5ea",
               ticks="outside", tickcolor="#e2e5ea", ticklen=4,
               title=dict(font=dict(size=11, color="#8a8d93"))),
    yaxis=dict(gridcolor="#eef0f3", zeroline=False, showline=False,
               title=dict(font=dict(size=11, color="#8a8d93"))),
    legend=dict(font=dict(size=11.5), bgcolor="rgba(0,0,0,0)"),
    hoverlabel=dict(bgcolor="#ffffff", bordercolor="#dfe3e8",
                    font=dict(size=12, color="#17181a")),
    margin=dict(l=0, r=0, t=10, b=0)))
pio.templates.default = "inripe"

st.markdown("""
<style>
.block-container {padding-top: 3rem; padding-bottom: 3rem; max-width: 1500px;}
header[data-testid="stHeader"] {background: transparent; height: 0;}
#MainMenu, footer {visibility: hidden;}
.band {background:#123A63;border-radius:12px;padding:16px 22px 15px;
  margin:0 0 .9rem;display:flex;justify-content:space-between;
  align-items:flex-end;flex-wrap:wrap;gap:10px}
.band .ttl {font-size:20px;font-weight:500;color:#F4F7FA;line-height:1.35}
.band .sc {font-size:12px;color:#9DB6CF;margin-top:4px}
.band .mt {text-align:right;font-size:11px;line-height:1.7;color:#93AAC2}
.band .mt b {color:#DDE7F1;font-weight:500}
.sec {font-size:11px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;
  color:#85888f;margin:1.2rem 0 .5rem}
.k {background:#fff;border:0.5px solid #e4e7ec;border-radius:12px;
  padding:13px 15px;height:100%}
.k .lab {font-size:12px;color:#6d7076}
.k .row {display:flex;align-items:baseline;gap:8px}
.k .val {font-size:26px;font-weight:500;color:#17181a;line-height:1.25;
  letter-spacing:-.02em}
.k .dl {font-size:12px;font-weight:500}
.k .pl {display:flex;justify-content:space-between;font-size:11px;
  color:#6d7076;margin:6px 0 4px}
.k .track {position:relative;height:5px;background:#f1f3f6;border-radius:3px}
.k .fill {height:100%;border-radius:3px}
.k .tick {position:absolute;left:100%;top:-3px;width:1px;height:11px;background:#b0b3b8}
.k .seg {display:flex;height:4px;margin-top:10px;border-radius:2px;
  overflow:hidden;gap:1px}
.k .lg {display:flex;justify-content:space-between;font-size:10.5px;margin-top:4px}
.k .ft {font-size:10.5px;color:#8a8d93;margin-top:8px;padding-top:8px;
  border-top:0.5px solid #e4e7ec;line-height:1.55}
.k .note {margin-top:9px;padding:8px 10px;background:#FAEEDA;border-radius:8px;
  font-size:10.5px;color:#633806;line-height:1.5}
.take {background:#f4f6f9;border-radius:8px;padding:11px 14px;font-size:13px;
  line-height:1.65;color:#17181a;margin-top:.6rem}
.defs {font-size:11px;color:#8a8d93;line-height:1.8;border-top:0.5px solid #e4e7ec;
  padding-top:10px;margin-top:1.5rem}
.defs b {color:#55585e;font-weight:500}
div[data-baseweb="tab-list"] {gap:2px}
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------- data

@st.cache_data(ttl=900)
def get_data(year: int):
    raw, fx, pmeta, aliases, cost_log = load_plan()
    plan = pe.attach_fx(pe.derive(raw), fx)
    actuals, ameta, lines = load_actuals_any(year, cost_log, plan)
    return (plan, lines, pmeta, ameta, aliases, cost_log, fx,
            datetime.now(TZ))


with st.spinner("Reading the plan from SharePoint and every order from the "
                "four Shopify stores. The first load takes a minute or two."):
    try:
        (plan, lines, pmeta, ameta, aliases, cost_log, fx,
         pulled) = get_data(YEAR)
    except Exception as exc:
        st.error(f"Could not load: {exc}")
        st.stop()

HAS_LINES = lines is not None and len(lines) > 0
if not HAS_LINES:
    st.error("No order data. The dashboard needs the Shopify API source.")
    st.stop()


def n(v, f="{:,.0f}"):
    return "n/a" if v is None or pd.isna(v) else f.format(v)


def p(v):
    return "n/a" if v is None or pd.isna(v) else f"{v:.0%}"


def tone(v, good=1.0, warn=0.9, invert=False):
    if v is None or pd.isna(v):
        return NEUT
    if invert:
        return GOOD if v <= good else WARN if v <= warn else BAD
    return GOOD if v >= good else WARN if v >= warn else BAD


def momentum_svg(mo, height=30):
    """Daily bars against the recent average, as inline SVG.

    Bars above the average are green, below are grey — so acceleration reads
    without a legend. Drawn rather than charted because a chart per card
    costs a round trip and this only has to show a shape.
    """
    if not mo or not mo.get("values") or len(mo["values"]) < 3:
        return ""
    vals, avg = mo["values"], mo["average"]
    hi = max(max(vals), avg) or 1
    n = len(vals)
    w = 100 / n
    bars = "".join(
        f"<rect x='{i*w:.2f}' y='{100 - v/hi*100:.2f}' "
        f"width='{w*0.84:.2f}' height='{max(1.5, v/hi*100):.2f}' "
        f"fill='{'#5DCAA5' if v >= avg else '#D3D1C7'}'/>"
        for i, v in enumerate(vals))
    y = 100 - avg / hi * 100
    return (
        f"<svg viewBox='0 0 100 100' preserveAspectRatio='none' "
        f"style='width:100%;height:{height}px;display:block;margin:7px 0 3px'>"
        f"{bars}<line x1='0' y1='{y:.2f}' x2='100' y2='{y:.2f}' "
        f"stroke='#888780' stroke-width='1.2' stroke-dasharray='3,2' "
        f"vector-effect='non-scaling-stroke'/></svg>")


def progress_svg(pr, height=34):
    """Cumulative progress against the plan line, as inline SVG.

    A daily bar chart shows activity. This shows whether the gap against
    plan is opening or closing, which is the question a card is actually
    asked. Drawn rather than charted because a chart object per card costs
    a round trip and this only has to show a shape.
    """
    if not pr or not pr.get("actual") or len(pr["actual"]) < 2:
        return ""
    act, pl = pr["actual"], pr["plan"]
    hi = max(max(act), max(pl)) or 1
    n = len(act)

    def path(vals, upto=None):
        vs = vals[:upto] if upto else vals
        return " ".join(
            f"{'M' if i == 0 else 'L'}{i / (n - 1) * 100:.2f},"
            f"{100 - v / hi * 100:.2f}"
            for i, v in enumerate(vs))

    # The plan line runs the full period; actual stops at today, so the gap
    # between the two ends is the shortfall to date rather than to the end.
    area = (path(act) + f" L{(len(act) - 1) / (n - 1) * 100:.2f},100 L0,100 Z")
    return (
        f"<svg viewBox='0 0 100 100' preserveAspectRatio='none' "
        f"style='width:100%;height:{height}px;display:block;margin:8px 0 4px'>"
        f"<path d='{area}' fill='#DCEAF9'/>"
        f"<path d='{path(pl)}' stroke='#B4B2A9' stroke-width='1.6' "
        f"fill='none' stroke-dasharray='3,2' vector-effect='non-scaling-stroke'/>"
        f"<path d='{path(act)}' stroke='#2A78D6' stroke-width='2' fill='none' "
        f"vector-effect='non-scaling-stroke'/></svg>")


def card(col, label, value, delta=None, delta_good=None, pace=None,
         pace_label=None, segs=None, footer=None, note=None, accent=None,
         spark=None, trend=None, trend_good_down=None, momentum=None):
    """One metric card. Value, movement, pace bar, split, footer.

    Every card is built from this so two cards cannot drift apart in shape.
    """
    h = [f"<div class='k'><div class='lab'>{label}</div><div class='row'>",
         f"<div class='val'>{value}</div>"]
    if delta:
        c = GOOD if (delta_good if delta_good is not None
                     else delta.strip().startswith("+")) else BAD
        h.append(f"<div class='dl' style='color:{c}'>{delta}</div>")
    h.append("</div>")

    if momentum is not None and not pd.isna(momentum):
        up = momentum >= 0
        h.append(
            f"<div style='font-size:11.5px;font-weight:500;margin-top:4px;"
            f"color:{GOOD if up else BAD}'>{'↗' if up else '↘'} "
            f"{abs(momentum):.0f}% {'above' if up else 'below'} the 7-day "
            f"average</div>")

    if trend is not None and not pd.isna(trend):
        # Direction alone is not good or bad, so the caller says which way is
        # healthy and the colour carries it.
        up = trend > 0
        bad = up if trend_good_down else not up
        h.append(
            f"<div style='font-size:11.5px;font-weight:500;margin-top:3px;"
            f"color:{BAD if bad else GOOD}'>"
            f"{'↗' if up else '↘'} {abs(trend):.1f} pts on last week</div>")

    if spark:
        h.append(momentum_svg(spark))

    if pace is not None:
        pct = max(0.0, min(1.0, pace))
        col_ = accent or tone(pace)
        h.append(f"<div class='pl'><span>{pace:.0%} of pace</span>"
                 f"<span style='color:#8a8d93'>{pace_label or ''}</span></div>"
                 f"<div class='track'><div class='fill' style='width:{pct*100:.1f}%;"
                 f"background:{col_}'></div><div class='tick'></div></div>")

    if segs:
        total = sum(abs(v) for _, v, _ in segs) or 1
        bars = "".join(
            f"<div style='width:{abs(v)/total*100:.1f}%;background:{c}'></div>"
            for _, v, c in segs)
        labs = "".join(
            f"<span style='color:{c}'>{lab}</span>" for lab, _, c in segs)
        h.append(f"<div class='seg'>{bars}</div><div class='lg'>{labs}</div>")

    if note:
        h.append(f"<div class='note'>{note}</div>")
    if footer:
        h.append(f"<div class='ft'>{footer}</div>")
    h.append("</div>")
    col.markdown("".join(h), unsafe_allow_html=True)


def waterfall(steps, title=None, height=300):
    """The gap decomposition bar that opens every drill-down."""
    if not steps:
        return None
    measure, x, y, text = [], [], [], []
    for s in steps:
        x.append(s["label"])
        if s["kind"] == "start":
            measure.append("absolute"); y.append(s["value"])
        elif s["kind"] == "end":
            measure.append("total"); y.append(None)
        else:
            measure.append("relative"); y.append(s["value"])
        text.append(f"{s['value']:,.0f}")
    f = go.Figure(go.Waterfall(
        orientation="v", measure=measure, x=x, y=y, text=text,
        textposition="outside",
        connector={"line": {"color": GREY, "width": 1}},
        increasing={"marker": {"color": TEAL}},
        decreasing={"marker": {"color": ORANGE}},
        totals={"marker": {"color": BLUE}}))
    f.update_layout(height=height, margin=dict(t=24), showlegend=False,
                    yaxis_title=title)
    return f


def table(df, height=None, empty="Nothing in this scope.", into=None, **kw):
    """One formatter for every table, so precision never drifts."""
    t = into if into is not None else st
    if df is None or len(df) == 0:
        t.caption(empty)
        return
    d = df.copy()
    cfg = {}
    for c in d.columns:
        nm = str(c).lower()
        if d[c].dtype.kind not in "if":
            continue
        mx = float(d[c].abs().max() or 0)
        if any(k in nm for k in ("%", "pct", "share", "rate", "index",
                                 "attainment")):
            if mx <= 1.5:
                d[c] = d[c] * 100
            cfg[c] = st.column_config.NumberColumn(format="%.1f%%")
        elif any(k in nm for k in ("order", "unit", "box", "count", "days",
                                   "product")):
            cfg[c] = st.column_config.NumberColumn(format="%d")
        elif any(k in nm for k in ("price", "cost", "aov", "per box")):
            cfg[c] = st.column_config.NumberColumn(format="%.2f")
        else:
            cfg[c] = st.column_config.NumberColumn(format="%,.0f")
    if height is not None:
        kw["height"] = height
    t.dataframe(d, hide_index=True, width="stretch", column_config=cfg, **kw)


def footer_definitions():
    """The definitions strip. Reads from the engine so it cannot drift."""
    st.markdown(
        "<div class='defs'>"
        + " &nbsp;·&nbsp; ".join(f"<b>{k}</b> {v}" for k, v in me.DEFINITIONS)
        + "</div>", unsafe_allow_html=True)


# -------------------------------------------------------------- selectors

c = st.columns([1, 1.1, 1.4, 1.5, 1.6])
market = c[0].selectbox("Market", [ALL_MK] + MARKETS, index=0)
_now = date.today()
_default_month = (MONTHS[_now.month - 1] if _now.year == YEAR else MONTHS[-1])
month = c[1].selectbox("Period", [YTD] + MONTHS,
                       index=MONTHS.index(_default_month) + 1)
cats = sorted(plan["category"].dropna().unique())
sel_cats = c[2].multiselect("Category", cats, default=[])
pool = plan[plan.category.isin(sel_cats)] if sel_cats else plan
sel_prods = c[3].multiselect("Product",
                             sorted(pool["product"].dropna().unique()),
                             default=[])

# The month selection sets the default range; the range can then be narrowed.
# Both sides are filtered by it, so a partial range compares like with like.
if month == YTD:
    d0, d1 = date(YEAR, 1, 1), date(YEAR, 12, 31)
else:
    import calendar as _cal
    _n = MONTHS.index(month) + 1
    d0 = date(YEAR, _n, 1)
    d1 = date(YEAR, _n, _cal.monthrange(YEAR, _n)[1])
picked = c[4].date_input("Date range", value=(d0, d1),
                         min_value=date(YEAR, 1, 1),
                         max_value=date(YEAR, 12, 31),
                         key=f"range_{month}",
                         help="Filters orders and plan together. A partial "
                              "range takes a pro-rated share of the month's "
                              "plan, so attainment stays comparable.")
start, end = (picked if isinstance(picked, tuple) and len(picked) == 2
              else (d0, d1))

scope = me.Scope(year=YEAR,
                 market=None if market == ALL_MK else market,
                 month=None if month == YTD else month,
                 categories=sel_cats, products=sel_prods,
                 start=start, end=end)

CUR = "AED" if scope.consolidated else plan[
    plan.market == market]["currency"].iloc[0]

try:
    C = me.cards(lines, plan, scope, cost_log)
except Exception as exc:
    st.error(f"Could not compute: {exc}")
    st.stop()

problems = me.check_chain(C)

# Every source states when it was last touched and by whom. A stale plan or
# an abandoned cost log otherwise looks identical to a current one.
_edited = (pmeta.get("modified") or "")[:16].replace("T", " ")
_by = pmeta.get("modified_by") or "unknown"
_cls = me.cost_log_status(cost_log)
_cost_line = ""
if _cls:
    _age = _cls.get("days_old")
    _cost_line = (
        f"Cost log · <b>{_cls['latest']:%d %b %Y}</b>"
        + (f" · {_age} days ago" if _age is not None else "")
        + f" · {_cls['products']} products"
        + (f" · {C['dated_share']:.0%} of lines dated"
           if not C.get("empty") else ""))
else:
    _cost_line = "Cost log · <b>none</b> · margin at plan cost"

st.markdown(
    f"<div class='band'><div><div class='ttl'>Inripe — Sales performance</div>"
    f"<div class='sc'>{market} · {scope.label} {YEAR}"
    + (f" · day {C['days_elapsed']} of {C['days_total']}"
       if not C.get("empty") and C["pace_fraction"] < 1 else "")
    + f" · {CUR}</div></div>"
    f"<div class='mt'>Actuals · <b>Shopify</b> · read {pulled:%d %b %H:%M}<br>"
    f"Plan · <b>{pmeta.get('name','')}</b> · saved {_edited} by {_by}<br>"
    f"{_cost_line}</div></div>", unsafe_allow_html=True)

if _cls and (_cls.get("days_old") or 0) > 30:
    st.warning(f"The cost log has not been updated in "
               f"{_cls['days_old']} days. Margin uses the last entered cost, "
               f"which may no longer be what you pay.")

if problems:
    st.error("The cards do not reconcile: " + " · ".join(problems)
             + ". Figures below should not be trusted until this is fixed.")

if C.get("empty"):
    st.info("No orders in this scope.")
    footer_definitions()
    st.stop()

view = st.radio("View", ["Management", "Forecast", "Portfolio pricing",
                         "Orders", "Units", "Revenue", "Margin",
                         "Payment", "Data quality", "How to read this"],
                horizontal=True, label_visibility="collapsed")

O, U, R, M = C["orders"], C["units"], C["revenue"], C["margin"]


# ------------------------------------------------------------- management

if view == "Management":
    st.markdown("<div class='sec'>The chain</div>", unsafe_allow_html=True)
    k = st.columns(3)

    sp_o = me.momentum(lines, plan, scope, "orders")
    sp_u = me.momentum(lines, plan, scope, "units")
    sp_r = me.momentum(lines, plan, scope, "revenue")
    wm = me.week_move(lines, plan, scope, cost_log)

    def peak(pr, fmt="{:,.0f}"):
        if not pr or not pr.get("peak_date"):
            return ""
        return (f" · peak {fmt.format(pr['peak_value'])} on "
                f"{pr['peak_date']:%d %b}")

    def mom_line(mo):
        """Above or below the recent average, in words."""
        if not mo or mo.get("change") is None:
            return None
        return mo["change"] * 100

    o_pace = O["total"] / O["paced"] if O["paced"] else None
    card(k[0], "Orders", n(O["total"]),
         n(O["total"] - O["paced"], "{:+,.0f}"), delta_good=None,
         pace=o_pace, pace_label=f"pace {n(O['paced'])}",
         segs=[(f"{O['delivered']} delivered", O["delivered"], "#0F6E56"),
               (f"{O['open']} open", O["open"], "#185FA5")],
         footer=f"plan {n(O['plan_full'])} · AOV {n(O['aov'])} {CUR}"
                + peak(sp_o),
         spark=sp_o, momentum=mom_line(sp_o))

    u_pace = U["total"] / U["paced"] if U["paced"] else None
    card(k[1], "Units", n(U["total"]),
         n(U["total"] - U["paced"], "{:+,.0f}"),
         pace=u_pace, pace_label=f"pace {n(U['paced'])}",
         segs=[(f"{n(U['delivered'])} delivered", U["delivered"], "#0F6E56"),
               (f"{n(U['open'])} open", U["open"], "#185FA5")],
         footer=f"plan {n(U['plan_full'])} · "
                f"{n(U['per_order'], '{:.1f}')} boxes per order"
                + peak(sp_u),
         spark=sp_u, momentum=mom_line(sp_u))

    r_pace = R["total"] / R["paced"] if R["paced"] else None
    card(k[2], f"Revenue {CUR}", n(R["total"]),
         n(R["total"] - R["paced"], "{:+,.0f}"),
         pace=r_pace, pace_label=f"pace {n(R['paced'])}",
         segs=[(f"{n(R['collected'])} collected", R["collected"], "#0F6E56"),
               (f"{n(R['owed'])} owed", R["owed"], "#854F0B"),
               (f"{n(R['at_risk'] + R['prepaid'])} at risk",
                R["at_risk"] + R["prepaid"], "#185FA5")],
         footer=f"plan {n(R['plan_full'])} · discount {n(R['discount'])}"
                + peak(sp_r),
         spark=sp_r, momentum=mom_line(sp_r))

    st.markdown("<div class='sec'>The outcome</div>", unsafe_allow_html=True)
    k2 = st.columns([1.25, 1, 1])

    m_pace = M["cm"] / M["paced"] if M["paced"] else None
    cost_note = None
    if C["cost_basis"] == "dated" and abs(M["cost_effect"]) > 1:
        cc = me.cost_changes(cost_log, plan, scope)
        if len(cc):
            top = cc.head(3)
            names = " · ".join(
                f"{r['product'].split()[-1]} {r['vs_plan_pct']:+.0%}"
                for _, r in top.iterrows() if pd.notna(r["vs_plan_pct"]))
            cost_note = (f"<b>Cost moved</b> · {names}<br>"
                         f"{n(abs(M['cost_effect']))} {CUR} of margin "
                         f"{'lost' if M['cost_effect'] < 0 else 'gained'}")
    card(k2[0], f"Contribution margin {CUR}", n(M["cm"]),
         n(M["cm"] - M["paced"], "{:+,.0f}"),
         pace=m_pace, pace_label=f"pace {n(M['paced'])}",
         segs=[(f"{n(M['commercial_effect'], '{:+,.0f}')} commercial",
                abs(M["commercial_effect"]), "#993C1D"),
               (f"{n(M['cost_effect'], '{:+,.0f}')} cost",
                abs(M["cost_effect"]), "#854F0B")],
         note=cost_note,
         footer=f"plan {n(M['plan_full'])} · at {C['cost_basis']} cost · "
                f"{n(M['per_box'], '{:.2f}')} per box")

    pts = ((M["cm_pct"] - M["plan_pct"]) * 100
           if M["cm_pct"] is not None and M["plan_pct"] else None)
    card(k2[1], "CM %", p(M["cm_pct"]),
         None if pts is None else f"{pts:+.1f} pts",
         delta_good=(pts or 0) >= 0,
         pace=(M["cm_pct"] / M["plan_pct"]
               if M["cm_pct"] and M["plan_pct"] else None),
         pace_label=f"plan {p(M['plan_pct'])}",
         trend=wm.get("cm_pct"), trend_good_down=False,
         footer=f"price {p(M['price_index'])} of plan · "
                f"cost {p(M['cost_index'])} of plan<br>"
                f"weighted by actual mix")

    # Lost sits on its own card rather than inside orders. It is not a
    # smaller sale, it is no sale, and every other headline excludes it.
    card(k2[2], "Lost", n(O["lost"]) + " orders",
         None if O.get("cancel_rate") is None
         else f"{O['cancel_rate']:.1%} of placed",
         delta_good=False,
         pace=None,
         segs=[(f"{n(U['lost'])} boxes", U["lost"], "#993C1D"),
               (f"{n(R['lost'])} {CUR}", R["lost"] / 100
                if R["lost"] else 0, "#F0997B")],
         trend=wm.get("lost_rate"), trend_good_down=True,
         footer=f"{n(O['placed'])} orders placed · "
                f"{n(M['lost_cm'])} {CUR} of margin never earned",
         accent=BAD)

    bits = []
    if o_pace and u_pace:
        bits.append(f"Orders {o_pace:.0%}, units {u_pace:.0%}"
                    + (", so baskets are smaller as well as fewer"
                       if u_pace < o_pace - 0.03 else
                       ", and baskets are holding"))
    if m_pace:
        share = (abs(M["cost_effect"])
                 / max(1e-9, abs(M["commercial_effect"]) + abs(M["cost_effect"])))
        bits.append(f"margin {m_pace:.0%}"
                    + (f", {share:.0%} of the gap from cost"
                       if C["cost_basis"] == "dated" and share > 0.1 else ""))
    if bits:
        st.markdown(f"<div class='take'>{'. '.join(bits).capitalize()}.</div>",
                    unsafe_allow_html=True)


# ------------------------------------------------------------- drill-downs


elif view == "Forecast":
    fc = me.forecast(lines, plan, scope, cost_log)
    if not fc:
        st.info("The period has finished, so there is nothing left to "
                "forecast. Pick a period that is still running.")
    else:
        st.caption(f"{market} · {scope.label} · day {fc['elapsed']} of "
                   f"{fc['days']} · {fc['remaining']} days remaining")

        cmetric = st.radio(
            "Confidence for", ["Revenue", "Orders", "Units", "Margin"],
            horizontal=True, key="conf_metric",
            help="Each metric is calibrated on its own history. Orders are "
                 "steadier than margin, so they do not share an interval.")
        conf = me.confidence(lines, plan, scope, cost_log,
                             metric=cmetric.lower())
        if conf:
            lvl = conf["level"]
            colr = GOOD if lvl >= 0.7 else AMBER if lvl >= 0.45 else ORANGE
            st.markdown(
                f"<div style='background:#fff;border:0.5px solid #e4e7ec;"
                f"border-left:3px solid {colr};padding:13px 16px;"
                f"max-width:900px;margin-bottom:14px'>"
                f"<div style='display:flex;justify-content:space-between;"
                f"align-items:baseline;flex-wrap:wrap;gap:10px'>"
                f"<span style='font-size:13px;color:#6d7076'>"
                f"{cmetric} will land near</span>"
                f"<span style='font-size:12px;color:{colr};font-weight:500'>"
                f"{lvl:.0%} confidence</span></div>"
                f"<div style='font-size:27px;font-weight:500;line-height:1.3;"
                f"margin:2px 0'>{n(conf['point'])}"
                + (f" <span style='font-size:14px;color:#6d7076'>{CUR}</span>"
                   if cmetric in ("Revenue", "Margin") else "")
                + "</div>"
                f"<div style='font-size:12.5px;color:#55585e'>"
                f"between {n(conf['low'])} and {n(conf['high'])}"
                + (f" · plan {n(conf['plan'])}" if conf.get("plan") else "")
                + "</div>"
                f"<div style='font-size:11.5px;color:#8a8d93;margin-top:7px;"
                f"padding-top:7px;border-top:0.5px solid #e4e7ec'>"
                f"day {conf['elapsed']} of {conf['days']} · "
                f"interval {conf['basis']}"
                + (f" on {conf['tested']} past projections"
                   if conf["tested"] else "")
                + f" · {conf['months']} completed months"
                f"</div></div>", unsafe_allow_html=True)

            if conf["todo"]:
                st.markdown(
                    "<div style='font-size:11px;font-weight:500;"
                    "letter-spacing:.06em;text-transform:uppercase;"
                    "color:#85888f;margin:0 0 7px'>What would raise it</div>",
                    unsafe_allow_html=True)
                for t in conf["todo"]:
                    when = (f" · in {t['in_days']} days"
                            if t.get("in_days") else "")
                    st.markdown(
                        f"<div style='display:flex;gap:11px;padding:5px 0;"
                        f"font-size:12.5px'>"
                        f"<span style='color:#B4B2A9'>○</span>"
                        f"<span style='color:#17181a;min-width:230px'>"
                        f"{t['what']}{when}</span>"
                        f"<span style='color:#6d7076'>{t['gives']}</span>"
                        f"</div>", unsafe_allow_html=True)
                if conf["done"]:
                    with st.expander(f"{len(conf['done'])} already in place"):
                        for t in conf["done"]:
                            st.markdown(
                                f"<div style='display:flex;gap:11px;"
                                f"padding:4px 0;font-size:12.5px'>"
                                f"<span style='color:#1D9E75'>✓</span>"
                                f"<span style='color:#6d7076'>{t['what']} — "
                                f"{t['gives']}</span></div>",
                                unsafe_allow_html=True)
                st.markdown("<div style='height:10px'></div>",
                            unsafe_allow_html=True)

        acc = me.basis_accuracy(lines, plan, scope, cost_log)
        if len(acc):
            best = acc.iloc[0]
            st.markdown(
                f"<div style='background:#E1F5EE;border-radius:8px;"
                f"padding:10px 13px;font-size:12.5px;color:#04342C;"
                f"line-height:1.65;max-width:900px;margin-bottom:12px'>"
                f"<b style='font-weight:500'>{best['basis']} has been closest, "
                f"missing by {best['avg_error']:.1%} on average.</b> "
                f"Tested on {int(best['months'])} completed month"
                f"{'s' if best['months'] != 1 else ''} by computing all three "
                f"on day {int(best['at_day'])} and comparing to what the month "
                f"actually did.</div>", unsafe_allow_html=True)
            show = acc[["basis", "avg_error", "bias", "months"]].copy()
            show.columns = ["basis", "avg error", "bias", "months tested"]
            with st.expander("How each basis scored"):
                table(show)

        basis = st.radio(
            "Basis", ["Run rate", "Attainment", "Plan"], horizontal=True,
            index=(["Run rate", "Attainment", "Plan"].index(acc.iloc[0]["basis"])
                   if len(acc) and acc.iloc[0]["basis"]
                   in ["Run rate", "Attainment", "Plan"] else 0),
            help="Run rate assumes the last 7 days repeat. Attainment assumes "
                 "the rate achieved so far continues. Plan assumes the "
                 "remaining days run exactly to plan.")
        key = {"Run rate": "run_rate", "Attainment": "attainment",
               "Plan": "at_plan"}[basis]
        b = fc["bases"][key]
        P, SF = fc["plan"], fc["so_far"]

        st.markdown("<div class='sec'>Demand</div>", unsafe_allow_html=True)
        st.caption("Orders and basket are forecast separately because they "
                   "fail for different reasons. Boxes follow from them.")
        dk = st.columns(3)
        dk[0].markdown(
            f"<div class='k'><div class='lab'>Orders</div>"
            f"<div class='val'>{n(b['orders'])}</div>"
            f"<div class='dl' style='color:{tone(b['orders_pct'])}'>"
            f"{p(b['orders_pct'])} of plan</div>"
            f"<div class='ft' style='border:none;padding:0;margin-top:5px'>"
            f"{n(SF['orders'])} placed · {n(b['orders'] - SF['orders'])} to come"
            f"</div></div>", unsafe_allow_html=True)
        bk_pct = b["basket"] / P["basket"] if P.get("basket") else None
        dk[1].markdown(
            f"<div class='k'><div class='lab'>Basket</div>"
            f"<div class='val'>{n(b['basket'], '{:.2f}')}</div>"
            f"<div class='dl' style='color:{tone(bk_pct)}'>"
            f"{'holding' if bk_pct and abs(bk_pct - 1) < .03 else p(bk_pct)}</div>"
            f"<div class='ft' style='border:none;padding:0;margin-top:5px'>"
            f"boxes per order · so far {n(P['basket'], '{:.2f}')}</div></div>",
            unsafe_allow_html=True)
        dk[2].markdown(
            f"<div class='k'><div class='lab'>Boxes</div>"
            f"<div class='val'>{n(b['units'])}</div>"
            f"<div class='dl' style='color:{tone(b['units_pct'])}'>"
            f"{p(b['units_pct'])} of plan</div>"
            f"<div class='ft' style='border:none;padding:0;margin-top:5px'>"
            f"orders × basket · plan {n(P['units'])}</div></div>",
            unsafe_allow_html=True)

        if P.get("orders") and P.get("basket"):
            ord_gap = b["orders"] - P["orders"]
            bkt_gap = (b["basket"] - P["basket"]) * b["orders"]
            driver = "order count" if abs(ord_gap * P["basket"]) > abs(bkt_gap) \
                else "basket size"
            st.markdown(
                f"<div class='take'>The projected box shortfall is mostly "
                f"<b>{driver}</b> — {n(ord_gap, '{:+,.0f}')} orders against "
                f"plan, basket {n(b['basket'] - P['basket'], '{:+.2f}')}. "
                + ("Fewer customers is a demand question."
                   if driver == "order count"
                   else "Smaller baskets is a merchandising question.")
                + "</div>", unsafe_allow_html=True)

        st.markdown("<div class='sec'>Financials</div>", unsafe_allow_html=True)
        st.caption("Derived from the demand above, so the two cannot "
                   "contradict.")
        fk = st.columns(3)
        fk[0].markdown(
            f"<div class='k'><div class='lab'>Revenue {CUR}</div>"
            f"<div class='val'>{n(b['revenue'])}</div>"
            f"<div class='dl' style='color:{tone(b['revenue_pct'])}'>"
            f"{p(b['revenue_pct'])} of plan</div>"
            f"<div class='ft' style='border:none;padding:0;margin-top:5px'>"
            f"{n(b['price'], '{:.2f}')} a box · plan "
            f"{n(P['price'], '{:.2f}')}</div></div>", unsafe_allow_html=True)
        fk[1].markdown(
            f"<div class='k'><div class='lab'>Cost {CUR}</div>"
            f"<div class='val'>{n(b['cogs'])}</div>"
            f"<div class='dl' style='color:{NEUT}'>at {fc['cost_basis']} cost</div>"
            f"<div class='ft' style='border:none;padding:0;margin-top:5px'>"
            f"{n(b['cost_per_box'], '{:.2f}')} a box · plan "
            f"{n(P['cost'], '{:.2f}')}</div></div>", unsafe_allow_html=True)
        fk[2].markdown(
            f"<div class='k'><div class='lab'>Margin {CUR}</div>"
            f"<div class='val'>{n(b['cm'])}</div>"
            f"<div class='dl' style='color:{tone(b['cm_pct_of_plan'])}'>"
            f"{p(b['cm_pct_of_plan'])} of plan · {p(b['cm_pct'])}</div>"
            f"<div class='ft' style='border:none;padding:0;margin-top:5px'>"
            f"plan {n(P['cm'])} at {p(P['cm'] / P['revenue'] if P['revenue'] else None)}"
            f"</div></div>", unsafe_allow_html=True)

        ms = fc["margin_split"]
        w = waterfall([
            {"label": "plan", "value": P["cm"], "kind": "start"},
            {"label": "volume", "value": ms["volume"],
             "kind": "up" if ms["volume"] >= 0 else "down"},
            {"label": "price", "value": ms["price"],
             "kind": "up" if ms["price"] >= 0 else "down"},
            {"label": "cost", "value": ms["cost"],
             "kind": "up" if ms["cost"] >= 0 else "down"},
            {"label": "projected", "value": b["cm"], "kind": "end"},
        ], title=f"Margin {CUR}", height=300)
        if w:
            st.plotly_chart(w, width="stretch")
        tot = abs(ms["volume"]) + abs(ms["cost"]) + abs(ms["price"])
        if tot:
            st.caption(
                f"Of the projected margin gap, {abs(ms['volume'])/tot:.0%} is "
                f"volume, {abs(ms['cost'])/tot:.0%} cost and "
                f"{abs(ms['price'])/tot:.0%} price.")

        st.markdown("<div class='sec'>Revenue to period end</div>",
                    unsafe_allow_html=True)
        daily = fc["daily"]
        if len(daily):
            g = go.Figure()
            g.add_trace(go.Scatter(x=daily["date"], y=daily["revenue"],
                                   name="actual",
                                   line=dict(color=BLUE, width=2.5)))
            last_d = daily["date"].iloc[-1]
            last_v = float(daily["revenue"].iloc[-1])
            end_ts = pd.Timestamp(scope.end)
            for lab, kk, colr in (("run rate", "run_rate", ORANGE),
                                  ("attainment", "attainment", AMBER),
                                  ("plan", "at_plan", GREY)):
                g.add_trace(go.Scatter(
                    x=[last_d, end_ts],
                    y=[last_v, fc["bases"][kk]["revenue"]], name=lab,
                    line=dict(color=colr, width=2,
                              dash="dash" if kk == "at_plan" else "dot")))
            g.update_layout(height=300, yaxis_title=f"Cumulative revenue {CUR}",
                            legend=dict(orientation="h", y=1.12, x=0))
            st.plotly_chart(g, width="stretch")

        lo = min(v["revenue"] for v in fc["bases"].values())
        hi = max(v["revenue"] for v in fc["bases"].values())
        st.markdown(
            f"<div style='font-size:12px;color:#6d7076;line-height:1.7;"
            f"background:#f4f6f9;border-radius:8px;padding:10px 13px;"
            f"max-width:900px'><b style='font-weight:500;color:#17181a'>"
            f"None of these is a prediction.</b> Each is arithmetic from a "
            f"stated assumption. Run rate follows the last {fc['window']} days "
            f"and turns fastest. Attainment assumes the shape so far holds. "
            f"Plan is the ceiling — what a perfect rest of period would give. "
            f"The {n(hi - lo)} {CUR} spread between them is the honest measure "
            f"of how uncertain the period is.</div>",
            unsafe_allow_html=True)



elif view == "Portfolio pricing":
    pf = me.portfolio(lines, plan, scope, cost_log)
    if not pf:
        st.info("No sales in this scope.")
    else:
        gk = st.columns(3)
        gk[0].markdown(
            f"<div class='k'><div class='lab'>Mix CM%</div>"
            f"<div class='val'>{p(pf['cm_pct'])}</div>"
            f"<div class='dl' style='color:"
            f"{GOOD if (pf['points'] or 0) >= 0 else BAD}'>"
            f"{pf['points']:+.1f} pts vs plan {p(pf['plan_cm_pct'])}</div>"
            f"</div>", unsafe_allow_html=True)
        gk[1].markdown(
            f"<div class='k'><div class='lab'>Margin gap</div>"
            f"<div class='val' style='color:"
            f"{BAD if pf['gap'] < 0 else GOOD}'>{n(pf['gap'], '{:+,.0f}')}</div>"
            f"<div class='ft' style='border:none;padding:0;margin-top:4px'>"
            f"{CUR}, at the volume actually sold</div></div>",
            unsafe_allow_html=True)
        gk[2].markdown(
            f"<div class='k'><div class='lab'>Working on</div>"
            f"<div class='val'>{'Recovery' if pf['gap'] < 0 else 'Surplus'}</div>"
            f"<div class='ft' style='border:none;padding:0;margin-top:4px'>"
            + ("where can a price rise be absorbed"
               if pf["gap"] < 0 else "how much can be spent on demand")
            + f" · at {pf['cost_basis']} cost</div></div>",
            unsafe_allow_html=True)

        st.markdown(
            f"<div class='take'>"
            + ("Below plan, so this is a recovery. Set a move on the products "
               "that can carry it — nothing is proposed that you have not "
               "allowed."
               if pf["gap"] < 0 else
               "Above plan, so there is room to spend. A negative move is a "
               "price cut or an offer.")
            + "</div>", unsafe_allow_html=True)

        st.markdown("<div class='sec'>Set your moves</div>",
                    unsafe_allow_html=True)
        st.caption("Alone is what that product would need to close the whole "
                   "gap by itself — a feasibility test, not a proposal. "
                   "Anything past 10% is not a candidate.")

        g = pf["products"]
        editable = g[["product", "units", "price", "cost", "cm_pct",
                      "alone_pct", "share"]].copy()
        editable["move_pct"] = 0.0
        editable.columns = ["product", "boxes", "price", "cost", "CM%",
                            "alone", "share", "your move %"]
        edited = st.data_editor(
            editable, hide_index=True, width="stretch", height=320,
            disabled=["product", "boxes", "price", "cost", "CM%", "alone",
                      "share"],
            column_config={
                "CM%": st.column_config.NumberColumn(format="%.1f%%"),
                "alone": st.column_config.NumberColumn(
                    format="%.1f%%",
                    help="The rise this product alone would need to close the "
                         "whole gap."),
                "share": st.column_config.NumberColumn(format="%.1f%%"),
                "price": st.column_config.NumberColumn(format="%.2f"),
                "cost": st.column_config.NumberColumn(format="%.2f"),
                "boxes": st.column_config.NumberColumn(format="%d"),
                "your move %": st.column_config.NumberColumn(
                    format="%.1f", step=0.5, min_value=-50.0, max_value=50.0,
                    help="Type a percentage. Positive raises price, negative "
                         "cuts it."),
            }, key="pf_editor")

        moves = dict(zip(edited["product"], edited["your move %"].fillna(0)))
        res = me.apply_moves(pf, moves)

        if res.get("moved"):
            st.markdown("<div class='sec'>Result</div>", unsafe_allow_html=True)
            rk = st.columns(3)
            rk[0].markdown(
                f"<div class='k' style='background:#E1F5EE;border-color:#9FE1CB'>"
                f"<div class='lab' style='color:#0F6E56'>"
                f"{'Margin recovered' if pf['gap'] < 0 else 'Margin spent'}</div>"
                f"<div class='val' style='color:#04342C'>"
                f"{n(res['recovered'], '{:+,.0f}')}</div>"
                f"<div class='ft' style='border:none;padding:0;margin-top:4px;"
                f"color:#0F6E56'>"
                + (f"{p(res['closed_share'])} of the {n(-pf['gap'])} gap"
                   if res.get("closed_share") else f"of a {n(pf['gap'])} surplus")
                + "</div></div>", unsafe_allow_html=True)
            rk[1].markdown(
                f"<div class='k' style='background:#E1F5EE;border-color:#9FE1CB'>"
                f"<div class='lab' style='color:#0F6E56'>New mix CM%</div>"
                f"<div class='val' style='color:#04342C'>"
                f"{p(res['new_cm_pct'])}</div>"
                f"<div class='ft' style='border:none;padding:0;margin-top:4px;"
                f"color:#0F6E56'>plan {p(pf['plan_cm_pct'])} · "
                f"{(res['new_cm_pct'] - pf['plan_cm_pct']) * 100:+.1f} pts"
                f"</div></div>", unsafe_allow_html=True)
            rk[2].markdown(
                f"<div class='k' style='background:#E1F5EE;border-color:#9FE1CB'>"
                f"<div class='lab' style='color:#0F6E56'>Volume you can lose"
                f"</div><div class='val' style='color:#04342C'>"
                f"{p(res['breakeven_volume'])}</div>"
                f"<div class='ft' style='border:none;padding:0;margin-top:4px;"
                f"color:#0F6E56'>before this is worse than doing nothing"
                f"</div></div>", unsafe_allow_html=True)

            t = res["table"]
            t = t[t["move"].abs() > 0]
            show = t[["product", "units", "price", "move", "new_price",
                      "cm_pct", "new_cm_pct", "cm_change"]].copy()
            show["move"] = show["move"] * 100
            show.columns = ["product", "boxes", "current price", "move %",
                            "new price", "CM% now", "CM% after",
                            f"margin change {CUR}"]
            st.caption("New prices")
            table(show)

            if res.get("below_cost"):
                st.warning("These fall below cost at the new price: "
                           + ", ".join(res["below_cost"]))

            st.download_button(
                "Download the new price list",
                show.to_csv(index=False).encode(),
                file_name=f"price_moves_{market}_{month}_{YEAR}.csv",
                mime="text/csv", key="dl_prices")
        else:
            st.caption("Type a move against a product to see the result.")

        st.markdown(
            f"<div style='font-size:12px;color:#6d7076;line-height:1.7;"
            f"background:#f4f6f9;border-radius:8px;padding:10px 13px;"
            f"margin-top:14px;max-width:900px'>"
            f"<b style='font-weight:500;color:#17181a'>Volume is held flat on "
            f"purpose.</b> The tool does not predict what a price rise does to "
            f"demand — it states the break-even, so the person who knows the "
            f"market can judge whether the trade is worth taking. An "
            f"elasticity estimated from this data would be seasonal demand "
            f"wearing a price label, because price and season moved together "
            f"all year.</div>", unsafe_allow_html=True)



elif view == "How to read this":

    def rows(title, items):
        st.markdown(f"<div class='sec'>{title}</div>", unsafe_allow_html=True)
        for k, v in items:
            st.markdown(
                f"<div style='display:flex;gap:14px;padding:7px 0;"
                f"border-bottom:0.5px solid #e4e7ec'>"
                f"<div style='min-width:135px;font-weight:500;font-size:13px'>"
                f"{k}</div><div style='font-size:13px;color:#55585e;"
                f"line-height:1.6'>{v}</div></div>", unsafe_allow_html=True)

    guide = st.radio("Section", ["The numbers", "Management", "Forecast",
                                 "Portfolio pricing", "Drill-downs",
                                 "Payment", "Rules"],
                     horizontal=True, label_visibility="collapsed")

    if guide == "The numbers":
        rows("What each figure means", [
            ("Orders", "Orders that can still become revenue — delivered plus "
                       "open. Cancelled orders are counted separately."),
            ("Units", "Boxes on those orders. Cancelled boxes are excluded."),
            ("Revenue", "Net of discount, on delivered and open orders. "
                        "Cancelled revenue was never earned."),
            ("CM", "Revenue less the cost of the boxes sold. Freight, "
                   "marketing and overhead are not in it."),
            ("CM %", "CM divided by revenue, weighted by what actually sold — "
                     "never an average of product percentages."),
            ("Lost", "Cancelled, refunded or voided, as a rate against orders "
                     "placed."),
            ("AOV", "Revenue divided by orders. Both exclude lost."),
            ("Basket", "Boxes per order. Both exclude lost."),
        ])

    elif guide == "Management":
        rows("The two rows", [
            ("The chain", "Orders × basket = units. Units × price = revenue. "
                          "Reading left to right shows which link broke."),
            ("The outcome", "Margin is the result of the row above, not a "
                            "fourth step in it."),
        ])
        rows("On each card", [
            ("Pace", "Plan × days elapsed ÷ days in the period. 45% of pace "
                     "means 45% of what the plan expected by today — not 45% "
                     "of the month."),
            ("The bar", "Fills to the percentage of pace. The tick is 100%."),
            ("The bars above", "Daily activity with the recent average as a "
                               "dashed line. Green above means momentum is "
                               "building, grey below means fading."),
            ("Split bar", "On the chain cards it is order state. On revenue "
                          "it is cash certainty — collected, owed, at risk."),
            ("Arrow", "Last 7 days against the 7 before, in points. Colour "
                      "says whether that direction is good."),
            ("Cost strip", "Appears only when dated costs exist and cost has "
                           "moved. Names the products driving it."),
        ])

    elif guide == "Forecast":
        rows("Two sections", [
            ("Demand", "Orders and basket are forecast separately because "
                       "they fail for different reasons. Boxes follow."),
            ("Financials", "Derived from the demand above, so the two cannot "
                           "contradict."),
        ])
        rows("The three bases", [
            ("Run rate", "The last 7 days repeat to the end. Turns fastest."),
            ("Attainment", "The rate achieved so far continues."),
            ("Plan", "The remaining days run exactly to plan. A ceiling, not "
                     "a forecast."),
            ("Which to use", "The dashboard tests all three against your "
                             "completed months and defaults to whichever was "
                             "closest. The scores are in the expander."),
            ("The spread", "The gap between the three is the honest measure "
                           "of how uncertain the period is."),
            ("Confidence", "Measured, not asserted. The interval comes from "
                           "how far the same method missed on completed "
                           "months. With nothing to test against it falls "
                           "back to a deliberately wide default and says so."),
            ("What would raise it", "Each item states what it buys. They "
                                    "disappear as they are met."),
        ])

    elif guide == "Portfolio pricing":
        rows("The idea", [
            ("Why it exists", "Margin is a weighted average across a mix, so "
                              "a cost rise on one product does not have to be "
                              "recovered on that product. It has to be "
                              "recovered somewhere demand can absorb it."),
            ("The gate", "Mix CM% against plan. Below plan is a recovery. "
                         "Above plan is a surplus you can spend on offers."),
            ("The gap", "Measured at the volume actually sold, so a volume "
                        "shortfall is not mixed into a pricing question."),
        ])
        rows("The columns", [
            ("Alone", "The rise this product alone would need to close the "
                      "whole gap. A feasibility test — past 10% it is not a "
                      "candidate."),
            ("Your move", "You type it. Positive raises price, negative cuts "
                          "it. Nothing is proposed that you have not set."),
            ("Volume you can lose", "The break-even. How much demand the move "
                                    "can cost before you are worse off than "
                                    "doing nothing."),
            ("Why no elasticity", "Price and season moved together all year "
                                  "in this data, so any elasticity derived "
                                  "from it would be seasonal demand wearing a "
                                  "price label."),
        ])

    elif guide == "Drill-downs":
        rows("Four blocks, always in this order", [
            ("1 · The gap", "Plan to actual in named steps. Every step "
                            "reconciles — nothing hides in a residual."),
            ("2 · The detail", "Orders and revenue show status against "
                               "payment. Units and margin show product "
                               "against plan."),
            ("3 · Dimensions", "Channel, city and customer, with the same "
                               "measures throughout."),
            ("4 · Structure", "Orders shows concentration. Units shows basket "
                              "composition. Revenue shows price realisation. "
                              "Margin shows cost movement."),
        ])
        rows("Reading them", [
            ("Concentration", "Share of orders containing each product. Sums "
                              "past 100% because an order holds several. When "
                              "a product in half the orders ends, those orders "
                              "disappear — they do not shrink."),
            ("Price realisation", "Achieved price against plan price. Below "
                                  "100% is revenue given away on boxes "
                                  "actually sold."),
            ("Cost movement", "Against plan on the cards, against the "
                              "previous cost entry here."),
        ])

    elif guide == "Payment":
        rows("What it shows", [
            ("Days to reconcile", "Median days from delivery to the order "
                                  "being marked paid. Measured only on orders "
                                  "already settled — an unpaid order has no "
                                  "lag yet."),
            ("Cash outstanding", "Delivered and not yet marked paid. On cash "
                                 "on delivery this sits with the delivery "
                                 "company until accounting reconciles it."),
            ("Stuck past 21 days", "Beyond any reconciliation window. Either "
                                   "the cash has not been remitted, or the "
                                   "goods never reached the customer."),
            ("Ageing", "From the delivery date, not the order date. The clock "
                       "that matters starts when the customer took the goods."),
            ("Downloads", "The outstanding orders and delivered quantities, "
                          "with dates, so any period can be filtered in Excel."),
        ])

    else:
        rows("Rules that apply everywhere", [
            ("Cost", "Matched to the order date, so cost and revenue are "
                     "recognised at the same moment. Where the cost log does "
                     "not reach, plan cost is used and the card says so."),
            ("Cost log", "Append only. To change a cost, add a row with a new "
                         "date. Each box carries the cost in force on the day "
                         "it sold, so a mid-month change splits the month "
                         "correctly."),
            ("Date range", "Filters orders and plan together. A partial range "
                           "takes a pro-rated share of the month's plan, so "
                           "attainment stays comparable."),
            ("Currency", "One market shows its own. All markets converts to "
                         "AED using the rates on the FX sheet."),
            ("Missing", "Blank is not zero. A month with no plan is absent, "
                        "not a failure."),
            ("Lost", "Excluded from every headline, never counted as zero. It "
                     "was never revenue."),
        ])
        st.markdown(
            "<div style='margin-top:1.5rem;font-size:12px;color:#8a8d93;"
            "line-height:1.7'>Every figure is checked before release: the "
            "chain must multiply, each gap must decompose to zero, cash "
            "buckets must sum to revenue, and the forecast parts must "
            "reconcile. If any check fails, a red banner appears at the top "
            "of the page instead of the numbers.</div>",
            unsafe_allow_html=True)

elif view in ("Orders", "Units", "Revenue", "Margin"):
    metric = view.lower()

    strip = st.columns(4)
    if metric == "orders":
        for i, (lab, v, sub) in enumerate([
                ("Orders", n(O["total"]), f"{p(O['total']/O['paced']) if O['paced'] else 'n/a'} of pace"),
                ("Delivered", n(O["delivered"]), p(O["delivered"]/O["total"] if O["total"] else None)),
                ("Open", n(O["open"]), p(O["open"]/O["total"] if O["total"] else None)),
                ("Lost", n(O["lost"]), f"{p(O['cancel_rate'])} of {n(O['placed'])} placed")]):
            strip[i].metric(lab, v, sub, delta_color="off")
    elif metric == "units":
        for i, (lab, v, sub) in enumerate([
                ("Units", n(U["total"]), f"{p(U['total']/U['paced']) if U['paced'] else 'n/a'} of pace"),
                ("Delivered", n(U["delivered"]), p(U["delivered"]/U["total"] if U["total"] else None)),
                ("Open", n(U["open"]), p(U["open"]/U["total"] if U["total"] else None)),
                ("Lost", n(U["lost"]), p(U["lost"]/(U["total"]+U["lost"]) if U["total"] else None))]):
            strip[i].metric(lab, v, sub, delta_color="off")
    elif metric == "revenue":
        for i, (lab, v, sub) in enumerate([
                (f"Revenue {CUR}", n(R["total"]), f"{p(R['total']/R['paced']) if R['paced'] else 'n/a'} of pace"),
                ("Collected", n(R["collected"]), p(R["collected"]/R["total"] if R["total"] else None)),
                ("Owed", n(R["owed"]), p(R["owed"]/R["total"] if R["total"] else None)),
                ("At risk", n(R["at_risk"]), p(R["at_risk"]/R["total"] if R["total"] else None))]):
            strip[i].metric(lab, v, sub, delta_color="off")
    else:
        for i, (lab, v, sub) in enumerate([
                (f"CM {CUR}", n(M["cm"]), f"{p(M['cm']/M['paced']) if M['paced'] else 'n/a'} of pace"),
                ("CM %", p(M["cm_pct"]), f"plan {p(M['plan_pct'])}"),
                ("CM per box", n(M["per_box"], "{:.2f}"), f"plan {n(M['plan_per_box'], '{:.2f}')}"),
                ("Lost to cancellation", n(M["lost_cm"]), "margin never earned")]):
            strip[i].metric(lab, v, sub, delta_color="off")

    st.markdown("<div class='sec'>1 · Where the gap went</div>",
                unsafe_allow_html=True)
    steps = me.gap_decomposition(C, metric)
    f = waterfall(steps, title=metric.title() if metric != "revenue"
                  else f"Revenue {CUR}")
    if f:
        st.plotly_chart(f, width="stretch")

    if metric in ("orders", "revenue"):
        st.markdown("<div class='sec'>2 · Status against payment</div>",
                    unsafe_allow_html=True)
        g = me.state_payment_grid(lines, plan, scope,
                                  "orders" if metric == "orders" else "money",
                                  cost_log)
        if len(g):
            g = g.reindex(index=["delivered", "open"]).fillna(0)
            gg = g.reset_index()
            gg.columns = ["state"] + list(g.columns)
            gg["total"] = g.sum(axis=1).values
            table(gg)
    else:
        st.markdown("<div class='sec'>2 · By product against plan</div>",
                    unsafe_allow_html=True)
        pp = me.product_performance(lines, plan, scope, cost_log)
        if len(pp):
            d = pp.head(14).iloc[::-1]
            f = go.Figure()
            if metric == "units":
                f.add_trace(go.Bar(y=d["product"], x=d.plan_units, name="plan",
                                   orientation="h", marker_color="#D3D1C7"))
                f.add_trace(go.Bar(y=d["product"], x=d.units, name="actual",
                                   orientation="h", marker_color=BLUE))
                f.update_layout(barmode="group", xaxis_title="Boxes")
            else:
                f.add_trace(go.Bar(y=d["product"], x=d.cm, orientation="h",
                                   marker_color=[TEAL if v >= 0 else ORANGE
                                                 for v in d.cm]))
                f.update_layout(xaxis_title=f"Contribution margin {CUR}")
            f.update_layout(height=max(320, 26 * len(d)),
                            legend=dict(orientation="h", y=1.1, x=0))
            st.plotly_chart(f, width="stretch")

    st.markdown("<div class='sec'>3 · By channel, city and customer</div>",
                unsafe_allow_html=True)
    bd = me.by_dimension(lines, plan, scope, cost_log=cost_log)
    if len(bd):
        cols = {
            "orders": ["dimension", "value", "orders", "share", "cancel_rate",
                       "aov"],
            "units": ["dimension", "value", "units", "share",
                      "boxes_per_order", "cancel_rate"],
            "revenue": ["dimension", "value", "revenue", "share", "aov",
                        "discount_rate"],
            "margin": ["dimension", "value", "cm", "share", "cm_pct",
                       "cm_per_box"],
        }[metric]
        show = bd[cols].copy()
        show.columns = [c.replace("_", " ") for c in cols]
        table(show, height=340)

    if metric == "orders":
        st.markdown("<div class='sec'>4 · Order concentration</div>",
                    unsafe_allow_html=True)
        st.caption("Share of orders containing each product. Shares sum past "
                   "100% because an order holds several.")
        oc = me.order_concentration(lines, plan, scope)
        if len(oc):
            cat = oc[oc.level == "category"].head(8)
            f = go.Figure(go.Bar(
                y=cat["product"].iloc[::-1], x=cat["share"].iloc[::-1] * 100,
                orientation="h", marker_color=BLUE,
                text=[f"{v:.0%}" for v in cat["share"].iloc[::-1]],
                textposition="auto"))
            f.update_layout(height=max(240, 28 * len(cat)),
                            xaxis_title="Share of orders %")
            st.plotly_chart(f, width="stretch")
            show = oc[["level", "product", "orders", "share"]].head(25)
            table(show, height=320)

    elif metric == "units":
        st.markdown("<div class='sec'>4 · Basket composition</div>",
                    unsafe_allow_html=True)
        bc = me.basket_composition(lines, scope)
        if len(bc):
            c1, c2 = st.columns([1, 1])
            f = go.Figure(go.Bar(
                x=bc.band, y=bc.share * 100,
                marker_color=[ORANGE, AMBER, TEAL, TEAL, TEAL][:len(bc)],
                text=[f"{v:.0%}" for v in bc.share], textposition="outside"))
            f.update_layout(height=250, margin=dict(t=26),
                            xaxis_title="products in order",
                            yaxis_title="share of orders %")
            c1.plotly_chart(f, width="stretch")
            show = bc[["band", "orders", "share", "avg_order", "avg_units"]].copy()
            show.columns = ["products", "orders", "share", "avg order",
                            "avg boxes"]
            table(show, into=c2)

    elif metric == "revenue":
        st.markdown("<div class='sec'>4 · Price realisation by product</div>",
                    unsafe_allow_html=True)
        pp = me.product_performance(lines, plan, scope, cost_log)
        pp = pp[pp.price_index.notna()].sort_values("price_index")
        if len(pp):
            f = go.Figure(go.Bar(
                y=pp["product"], x=pp.price_index * 100, orientation="h",
                marker_color=[TEAL if v >= 1 else AMBER if v >= .95 else ORANGE
                              for v in pp.price_index],
                text=[f"{v:.0%}" for v in pp.price_index], textposition="auto"))
            f.update_layout(height=max(300, 26 * len(pp)),
                            xaxis_title="Achieved against plan price %",
                            xaxis=dict(range=[80, 115]))
            st.plotly_chart(f, width="stretch")
            show = pp[["product", "units", "plan_price", "price",
                       "price_index", "revenue"]].copy()
            show.columns = ["product", "units", "plan price", "achieved",
                            "index", f"revenue {CUR}"]
            table(show, height=320)

    else:
        st.markdown("<div class='sec'>4 · Cost movement</div>",
                    unsafe_allow_html=True)
        cc = me.cost_changes(cost_log, plan, scope)
        if not len(cc):
            st.caption("No dated costs recorded. Margin above is at plan cost, "
                       "so it measures commercial performance only and cost "
                       "movement is invisible.")
        else:
            d = cc[cc.vs_plan_pct.notna()].head(20).iloc[::-1]
            f = go.Figure(go.Bar(
                y=d["product"], x=d.vs_plan_pct * 100, orientation="h",
                marker_color=[ORANGE if v > .10 else AMBER if v > .02
                              else TEAL if v < -.02 else GREY
                              for v in d.vs_plan_pct],
                text=[f"{v:+.0%}" for v in d.vs_plan_pct], textposition="auto"))
            f.update_layout(height=max(300, 26 * len(d)),
                            xaxis_title="Actual cost against plan %")
            st.plotly_chart(f, width="stretch")
            show = cc[["product", "plan_cost", "previous", "cogs_unit_lc",
                       "vs_plan_pct", "vs_previous_pct", "changes"]].copy()
            show.columns = ["product", "plan cost", "previous", "current",
                            "vs plan", "vs previous", "changes"]
            table(show, height=320)


# ------------------------------------------------------------- payment

elif view == "Payment":
    st.markdown("<div class='sec'>Payment</div>", unsafe_allow_html=True)
    pay = me.payment(lines, plan, scope, cost_log)
    if not pay or not pay.get("delivered_orders"):
        st.caption("Nothing delivered in this scope.")
    else:
        def arrow(v, good_down=True, fmt="{:+.0%}"):
            """A movement against the previous seven days.

            Direction alone is not meaning: rising cash outstanding is bad,
            rising collection speed is good. Each caller says which.
            """
            if v is None or pd.isna(v):
                return ""
            up = v > 0
            bad = up if good_down else not up
            icon = "↗" if up else "↘"
            colr = BAD if bad else GOOD
            return (f"<span style='color:{colr};font-weight:500;font-size:12px'>"
                    f"{icon} {fmt.format(abs(v))}</span>")

        k = st.columns(3)
        lag = pay.get("median_lag")
        k[0].markdown(
            f"<div class='k'><div class='lab'>Days to reconcile</div>"
            f"<div class='row'><div class='val'>{'n/a' if lag is None else f'{lag:.0f}'}</div>"
            f"{arrow(pay.get('lag_change'), True, '{:.0f}')}</div>"
            f"<div class='ft' style='border:none;padding:0;margin-top:4px'>"
            f"median, delivery to paid"
            + (f" · was {pay['lag_prev']:.0f}" if pay.get("lag_prev") is not None else "")
            + "</div></div>", unsafe_allow_html=True)
        k[1].markdown(
            f"<div class='k'><div class='lab'>Cash outstanding</div>"
            f"<div class='row'><div class='val'>{n(pay['outstanding'])}</div>"
            f"{arrow(pay.get('outstanding_change'), True)}</div>"
            f"<div class='ft' style='border:none;padding:0;margin-top:4px'>"
            f"{pay['orders']} orders delivered, not paid</div></div>",
            unsafe_allow_html=True)
        k[2].markdown(
            f"<div class='k'><div class='lab'>Stuck past "
            f"{pay['stuck_after']} days</div>"
            f"<div class='row'><div class='val' style='color:{BAD}'>"
            f"{n(pay['stuck_value'])}</div></div>"
            f"<div class='ft' style='border:none;padding:0;margin-top:4px'>"
            f"{pay['stuck_orders']} orders · oldest {pay['oldest']} days"
            f"</div></div>", unsafe_allow_html=True)

        c1, c2 = st.columns([1.15, 1])
        bb = pay["by_band"]
        f = go.Figure(go.Bar(
            x=bb.band, y=bb.outstanding,
            marker_color=[TEAL, "#5DCAA5", AMBER, ORANGE, "#A32D2D"][:len(bb)],
            text=[f"{v:,.0f}" for v in bb.outstanding], textposition="outside"))
        f.update_layout(height=250, margin=dict(t=26),
                        xaxis_title="days since delivery",
                        yaxis_title=f"Outstanding {CUR}")
        c1.plotly_chart(f, width="stretch")

        if pay["stuck_orders"]:
            c2.markdown(
                f"<div style='background:#FCEBEB;border-radius:8px;"
                f"padding:12px 14px;font-size:12.5px;color:#791F1F;"
                f"line-height:1.65;margin-top:14px'>"
                f"<b style='font-weight:500'>{pay['stuck_orders']} orders past "
                f"{pay['stuck_after']} days, worth {n(pay['stuck_value'])} "
                f"{CUR}.</b><br>Beyond any reconciliation window. Either the "
                f"cash has not been remitted, or the goods never reached the "
                f"customer.</div>", unsafe_allow_html=True)
            st_ = pay["stuck_table"]
            keep = [c for c in ["order", "days_since_delivery", "outstanding",
                                "boxes", "channel", "delivered_on", "basis"]
                    if c in st_.columns]
            c2.download_button(
                f"Download the {pay['stuck_orders']} stuck orders",
                st_[keep].to_csv(index=False).encode(),
                file_name=f"stuck_orders_{market}_{month}_{YEAR}.csv",
                mime="text/csv", key="dl_stuck")
        else:
            c2.caption("Nothing is stuck beyond the window.")

        ot = pay["orders_table"]
        if len(ot):
            keep = [c for c in ["order", "days_since_delivery", "outstanding",
                                "boxes", "channel", "delivered_on", "basis"]
                    if c in ot.columns]
            st.download_button(
                f"Download all {pay['orders']} outstanding orders",
                ot[keep].to_csv(index=False).encode(),
                file_name=f"outstanding_{market}_{month}_{YEAR}.csv",
                mime="text/csv", key="dl_out")

        st.markdown("<div class='sec'>Delivered to customers</div>",
                    unsafe_allow_html=True)
        st.caption(f"{n(pay['delivered_boxes'])} boxes · "
                   f"{pay['delivered_orders']} orders · "
                   f"{n(pay['delivered_value'])} {CUR}")
        bp = pay["by_product"].copy()
        bp.columns = ["product", "boxes", "orders", f"value {CUR}"]
        table(bp, height=320)
        st.download_button(
            "Download delivered by product",
            bp.to_csv(index=False).encode(),
            file_name=f"delivered_by_product_{market}_{month}_{YEAR}.csv",
            mime="text/csv", key="dl_prod")

        if pay.get("no_delivery_date"):
            st.caption(f"{pay['no_delivery_date']} orders had no delivery date "
                       f"and are aged from the order date instead.")


elif view == "Data quality":
    dq = me.data_quality(lines, plan, scope, cost_log, fx)
    k = st.columns(3)
    k[0].metric("Findings", dq["total"],
                f"{dq['high']} need attention", delta_color="off")
    k[1].metric(f"At stake {CUR}", n(dq["at_stake"]),
                "revenue that cannot be measured", delta_color="off")
    k[2].metric("Reconciliation",
                "Failing" if dq["consistency"] else "Passing",
                "the chain and every decomposition", delta_color="off")

    st.caption("Grouped by where it must be fixed, because that is what "
               "decides who fixes it. Every finding carries what it is worth "
               "and what to do.")

    COLOUR = {"high": ORANGE, "medium": AMBER, "low": GREY}

    def block(title, items, empty):
        st.markdown(f"<div class='sec'>{title}</div>", unsafe_allow_html=True)
        if not items:
            st.caption(empty)
            return
        for e in items:
            st.markdown(
                f"<div style='background:#fff;border:0.5px solid #e4e7ec;"
                f"border-left:3px solid {COLOUR[e['severity']]};"
                f"padding:11px 14px;margin-bottom:7px'>"
                f"<div style='display:flex;justify-content:space-between;"
                f"gap:8px;flex-wrap:wrap'>"
                f"<span style='font-size:13px;font-weight:500'>"
                f"{e['title']}</span>"
                f"<span style='font-size:12px;color:{COLOUR[e['severity']]};"
                f"font-weight:500'>"
                + (f"{e['value']:,.0f} {CUR}" if e.get("value") else "")
                + "</span></div>"
                f"<div style='font-size:12px;color:#6d7076;margin-top:3px;"
                f"line-height:1.55'>{e['detail']}<br>"
                f"<b style='font-weight:500;color:#17181a'>{e['action']}</b>"
                f"</div></div>", unsafe_allow_html=True)
            if e.get("table") is not None and len(e["table"]):
                with st.expander(f"All {len(e['table'])} rows"):
                    table(e["table"])

    block("Consistency · the dashboard itself", dq["consistency"],
          "Every check passes. The chain multiplies, each decomposition "
          "reconciles to zero, and cash buckets sum to revenue.")
    block("The workbook · fix in Excel", dq["sheet"], "Nothing flagged.")
    block("Shopify · fix in the stores", dq["shopify"], "Nothing flagged.")

footer_definitions()

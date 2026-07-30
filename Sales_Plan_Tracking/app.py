"""Inripe — Sales performance.

Presentation only. Every number comes from plan_engine or variance_engine.
No calculation happens in this file.

The executive block is generated, not written: findings are ranked by money at
stake, so the top card is the thing that costs the most this month. Each tab
carries its own one-line read for the same reason.

One market reports in its own currency. Across markets everything consolidates
to AED using the plan workbook's rates, because SAR, QAR, AED and EGP cannot
be added.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

import plan_engine as pe
import pricing_engine as px
import variance_engine as ve
from data_loader import load_plan, load_actuals_any, load_previous_plan

YEAR = 2026
MARKETS = ["UAE", "QA", "KSA", "EG"]
ALL_MK, YTD = "All markets", "Full year"
MONTHS = pe.MONTHS
BLUE, ORANGE, TEAL, YELLOW, PINK, GREY = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#888780",
)
SERIES = [BLUE, ORANGE, TEAL, YELLOW, PINK, GREY]
GOOD, WARN, BAD, NEUT = "#1baf7a", "#eda100", "#e0553a", "#c2c0b8"
SEV = {"bad": BAD, "warn": YELLOW, "good": GOOD}

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
    margin=dict(l=0, r=0, t=10, b=0),
))
pio.templates.default = "inripe"

st.markdown("""
<style>
/* Streamlit's own toolbar overlaps the top of the page on a deployed app,
   so the container needs clearance the local server does not. */
.block-container {padding-top: 3.4rem; padding-bottom: 3rem; max-width: 1540px;}
header[data-testid="stHeader"] {background: transparent; height: 0;}
#MainMenu, footer {visibility: hidden;}
/* The scope selectors stay in reach. Changing market or month from the
   bottom of a long tab should not mean scrolling back to the top. */
.stElementContainer:has(.scope-anchor) + div[data-testid="stHorizontalBlock"] {
  position: sticky; top: 0; z-index: 99; background: #fff;
  padding: 8px 0 10px; border-bottom: 1px solid #eceff3; margin-bottom: 2px;}
div[data-testid="stDataFrame"] {border-radius: 8px;}
.band {background: #123a63; border-radius: 12px; padding: 20px 24px 18px;
       margin: 0 0 1rem; display: flex; justify-content: space-between;
       align-items: flex-end; flex-wrap: wrap; gap: 12px;
       box-shadow: 0 1px 3px rgba(18,58,99,.14);}
.band .ttl {font-size: 22px; font-weight: 500; color: #f4f7fa;
            letter-spacing: -.015em; line-height: 1.35; padding-top: 2px;}
.band .sc {font-size: 12.5px; color: #9db6cf; margin-top: 5px;}
.band .mt {text-align: right; font-size: 11.5px; line-height: 1.7;
           color: #93aac2;}
.band .mt b {color: #dde7f1; font-weight: 500;}
.sec {font-size: 12px; font-weight: 500; letter-spacing: .06em;
      text-transform: uppercase; color: #85888f; margin: 1.35rem 0 .55rem;}
.kpi {background: #fff; border: 1px solid #e4e7ec; border-radius: 12px;
      padding: 13px 15px 12px; position: relative; overflow: hidden; height: 100%;}
.kpi:before {content: ""; position: absolute; left: 0; top: 0; bottom: 0;
             width: 3px; background: var(--acc, #d5d8dd);}
.kpi .lab {font-size: 12px; color: #6d7076; margin-bottom: 3px;}
.kpi .val {font-size: 25px; font-weight: 500; color: #17181a; line-height: 1.15;
           letter-spacing: -.02em;}
.kpi .dl {font-size: 12px; font-weight: 500; margin-top: 2px;}
.kpi .sub {font-size: 11.5px; color: #8a8d93; margin-top: 4px; line-height: 1.45;}
.fin {background: #fff; border: 1px solid #e4e7ec; border-radius: 12px;
      padding: 12px 15px 13px; height: 100%; border-left: 3px solid var(--acc);}
.fin .t {font-size: 13.5px; font-weight: 500; color: #17181a; line-height: 1.4;}
.fin .d {font-size: 12px; color: #6d7076; margin-top: 5px; line-height: 1.55;}
.fin .s {font-size: 11px; color: var(--acc); font-weight: 500;
         letter-spacing: .04em; text-transform: uppercase; margin-bottom: 4px;}
.note {font-size: 12.5px; color: #55585e; background: #f4f6f9;
       border-radius: 8px; padding: 9px 13px; margin: 0 0 .9rem;
       line-height: 1.55;}
div[data-baseweb="tab-list"] {gap: 2px;}
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=900)
def get_data(year: int):
    raw, fx, pmeta, aliases, cost_log = load_plan()
    plan = pe.attach_fx(pe.derive(raw), fx)
    actuals, ameta, lines = load_actuals_any(year, cost_log, plan)
    combined = ve.combine(plan, actuals, year, aliases)
    return (plan, actuals, lines, combined, pmeta, ameta, aliases, cost_log,
            raw, datetime.now())


# The first load pulls every order from all four stores, which takes a couple
# of minutes. Without this the page is simply blank and looks broken.
with st.spinner("Reading the plan from SharePoint and every order from the "
                "four Shopify stores. The first load takes a minute or two; "
                "after that it is cached for 15 minutes."):
    try:
        (plan, actuals, lines, combined, pmeta, ameta, aliases,
         cost_log, raw_plan, pulled) = get_data(YEAR)
    except Exception as exc:
        st.error(f"Could not load: {exc}")
        st.stop()

HAS_LINES = lines is not None and len(lines) > 0
HAS_TIERS = "net_confirmed_lc" in combined.columns


def n(v, f="{:,.0f}"):
    return "n/a" if v is None or pd.isna(v) else f.format(v)


def p(v):
    return "n/a" if v is None or pd.isna(v) else f"{v:.0%}"


def delta(v):
    return None if v is None or pd.isna(v) else f"{(v - 1) * 100:+.0f} pts vs plan"


def pts(now, prev, label, invert=False):
    """Month-on-month movement, so a quiet drift is visible."""
    if now is None or prev is None or pd.isna(now) or pd.isna(prev):
        return None
    d = (now - prev) * 100
    if abs(d) < 0.5:
        return f"flat vs {label}"
    return f"{d:+.1f} pts vs {label}"


def tone(v, good=1.0, warn=0.9, invert=False):
    if v is None or pd.isna(v):
        return NEUT
    if invert:
        return GOOD if v <= good else WARN if v <= warn else BAD
    return GOOD if v >= good else WARN if v >= warn else BAD


def kpi(col, label, value, dl=None, sub=None, accent=NEUT, dl_good=None):
    d = ""
    if dl:
        pos = dl_good if dl_good is not None else dl.strip().startswith("+")
        colr = GOOD if pos else (NEUT if dl.startswith("flat") else BAD)
        d = f"<div class='dl' style='color:{colr}'>{dl}</div>"
    col.markdown(f"<div class='kpi' style='--acc:{accent}'>"
                 f"<div class='lab'>{label}</div><div class='val'>{value}</div>{d}"
                 f"<div class='sub'>{sub or ''}</div></div>",
                 unsafe_allow_html=True)


def table(df, height=None, empty="Nothing in this scope.", into=None, **kw):
    """Every table renders through here, so formatting is decided once.

    Money carries thousands separators, counts stay whole, and a ratio shows
    as a percentage whether it was stored as 0.42 or as 42. A frame that
    comes back empty says so, rather than leaving a blank grid for the reader
    to interpret.

    `into` takes a column or container so a table can sit where it was placed
    rather than always spanning the page.
    """
    target = into if into is not None else st
    if df is None or len(df) == 0:
        target.caption(empty)
        return

    d = df.copy()
    cfg = {}
    for col in d.columns:
        name = str(col).lower()
        if d[col].dtype.kind not in "if":
            continue
        mx = float(d[col].abs().max() or 0)
        if any(k in name for k in ("%", "pct", "share", " att", "rate",
                                   "realisation")):
            # Ratios arrive as 0.42 from the engine and as 42 from a chart
            # frame, so both are normalised before formatting.
            if mx <= 1.5:
                d[col] = d[col] * 100
            cfg[col] = st.column_config.NumberColumn(format="%.1f%%")
        elif any(k in name for k in ("unit", "box", "order", "count", "days",
                                     "product", "rows", "lost", "items")):
            cfg[col] = st.column_config.NumberColumn(format="%d")
        elif "fx" in name:
            cfg[col] = st.column_config.NumberColumn(format="%.4f")
        elif any(k in name for k in ("price", "cost", "aov", "per box",
                                     "cm/box", "basket")):
            cfg[col] = st.column_config.NumberColumn(format="%.2f")
        else:
            cfg[col] = st.column_config.NumberColumn(format="%,.0f")
    # Streamlit rejects height=None outright, so the argument is omitted
    # rather than passed empty.
    if height is not None:
        kw["height"] = height
    target.dataframe(d, hide_index=True, width="stretch",
                     column_config=cfg, **kw)

def note(text):
    st.markdown(f"<div class='note'>{text}</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------- header

st.markdown(
    f"<div class='band'><div><div class='ttl'>Inripe — Sales performance</div>"
    f"<div class='sc' id='scope'>plan against actual, {YEAR}</div></div>"
    f"<div class='mt'>Actuals · <b>{ameta.get('source')}</b> · "
    f"read {pulled:%d %b %H:%M}<br>Plan · <b>{pmeta.get('name','')}</b> · "
    f"{'edited ' + (pmeta.get('modified') or '')[:16].replace('T', ' ')}"
    f"</div></div>", unsafe_allow_html=True)

mode = st.radio("View", ["Tracking", "Plan"], horizontal=True,
                label_visibility="collapsed")

st.markdown("<div class='scope-anchor'></div>", unsafe_allow_html=True)
c = st.columns([1.1, 1.2, 1.5, 1.7, 1.2])
market = c[0].selectbox("Market", [ALL_MK] + MARKETS, index=3)
month = c[1].selectbox("Month", [YTD] + MONTHS,
                       index=MONTHS.index("July") + 1)
mk_scope = MARKETS if market == ALL_MK else [market]
base = combined[combined.market.isin(mk_scope)]
cats = sorted(base["category"].dropna().unique())
sel_cats = c[2].multiselect("Category", cats, default=[])
pool = base[base.category.isin(sel_cats)] if sel_cats else base
LBL = "product_label" if "product_label" in combined.columns else "product"
label_of = (combined.drop_duplicates("product")
            .set_index("product")[LBL].to_dict())
name_of = {v: k for k, v in label_of.items()}
sel_labels = c[3].multiselect("Product",
                              sorted(set(label_of.values())), default=[])
sel_prods = [name_of[x] for x in sel_labels if x in name_of]
as_of = c[4].date_input("As of", value=date.today())

# A single market normally reads best in its own currency, but comparing it
# against another needs a common one. Across markets AED is the only honest
# choice, so the toggle is offered rather than assumed.
if market != ALL_MK:
    ccy = st.radio("Report in", ["Local currency", "AED"], horizontal=True,
                   index=0, label_visibility="collapsed",
                   help="AED uses the rates on the FX sheet, matched by "
                        "market and month.")
else:
    ccy = "AED"

CONSOL = market == ALL_MK
IN_AED = CONSOL or ccy == "AED"
SUF = "_aed" if IN_AED else "_lc"
LOCAL = "AED" if CONSOL else plan[plan.market == market]["currency"].iloc[0]
cur = "AED" if IN_AED else LOCAL
ATT = "revenue_attainment_aed" if IN_AED else "revenue_attainment"
CMP_ = "act_cm_pct_aed" if IN_AED else "act_cm_pct"

sel = base if month == YTD else base[base.month == month]
if sel_cats:
    sel = sel[sel.category.isin(sel_cats)]
if sel_prods:
    sel = sel[sel["product"].isin(sel_prods)]
if sel.empty:
    st.info("No plan and no sales in this scope.")
    st.stop()


def agg(df):
    pu, au = df.plan_units.sum(), df.act_units.sum()
    pr, ar = df[f"plan_revenue{SUF}"].sum(), df[f"act_net{SUF}"].sum()
    pc, ac = df[f"plan_cm{SUF}"].sum(), df[f"act_cm_at_plan{SUF}"].sum()
    return dict(plan_units=pu, act_units=au, unit_att=au / pu if pu else None,
                plan_rev=pr, act_rev=ar, rev_att=ar / pr if pr else None,
                plan_cm=pc, act_cm=ac, cm_att=ac / pc if pc else None,
                plan_cm_pct=pc / pr if pr else None,
                act_cm_pct=ac / ar if ar else None)


A = agg(sel)
SINGLE = (not CONSOL) and month != YTD
land = ve.landing(combined, market, month, as_of, YEAR) if SINGLE else None
conc = ve.concentration(sel, by=["market"]) if not CONSOL else pd.DataFrame()
cb = ve.cm_per_box(sel)
oq = ve.order_quality(lines, plan, YEAR) if HAS_LINES else pd.DataFrame()
oqs = oq[oq.market.isin(mk_scope)] if len(oq) else oq
if len(oqs) and month != YTD:
    oqs = oqs[oqs.month == month]
orders = (ve.order_count(lines, YEAR, None if CONSOL else market,
                         None if month == YTD else month) if HAS_LINES else None)
mom = ve.momentum(combined, lines, plan, market, month, YEAR) if SINGLE else {}
tb = (ve.traffic_basket(lines, combined, YEAR, market,
                        None if month == YTD else month)
      if HAS_LINES and not CONSOL else {})

scope_txt = " · ".join(filter(None, [
    market, f"{month} {YEAR}",
    f"day {land['days_elapsed']} of {land['days_total']}" if land else None,
    ", ".join(sel_cats[:2]) if sel_cats else None,
    f"{len(sel_prods)} products" if sel_prods else None,
    f"reported in {cur}"
    + ("" if cur == LOCAL else f", converted from {LOCAL}")]))
st.caption(scope_txt + ". Plan is compared against net sales. Cancelled, "
           "refunded and voided orders are excluded, not zeroed. Margin is at "
           "planned unit cost.")


# ------------------------------------------------------- executive block

if SINGLE:
    fnd = ve.findings(combined, lines, plan, market, month, as_of, YEAR)
    if fnd:
        st.markdown("<div class='sec'>Executive summary · ranked by money at "
                    "stake</div>", unsafe_allow_html=True)
        top = fnd[:3]
        cols = st.columns(len(top))
        for i, f in enumerate(top):
            cols[i].markdown(
                f"<div class='fin' style='--acc:{SEV[f['severity']]}'>"
                f"<div class='s'>{n(f['stake'])} {cur} at stake</div>"
                f"<div class='t'>{f['title']}</div>"
                f"<div class='d'>{f['detail']}</div></div>",
                unsafe_allow_html=True)
        if len(fnd) > 3:
            with st.expander(f"{len(fnd) - 3} further findings"):
                for f in fnd[3:]:
                    st.markdown(
                        f"<div class='fin' style='--acc:{SEV[f['severity']]};"
                        f"margin-bottom:8px'>"
                        f"<div class='s'>{n(f['stake'])} {cur} at stake</div>"
                        f"<div class='t'>{f['title']}</div>"
                        f"<div class='d'>{f['detail']}</div></div>",
                        unsafe_allow_html=True)
else:
    note("The executive summary and the landing estimate need one market and "
         "one month, so the findings can be attributed. Everything below still "
         "works across the wider scope.")


# ------------------------------------------------------ plan vs actual


# ------------------------------------------------------------- plan view

if mode == "Plan":
    pscope = plan[plan.market.isin(mk_scope)]
    if month != YTD:
        pscope = pscope[pscope.month == month]
    if sel_cats:
        pscope = pscope[pscope.category.isin(sel_cats)]
    if sel_prods:
        pscope = pscope[pscope["product"].isin(sel_prods)]
    filled = pscope[pscope.plan_units > 0]

    PSUF = SUF
    st.markdown("<div class='sec'>The plan</div>", unsafe_allow_html=True)
    pk = st.columns(5)
    prev_u = filled.plan_units.sum()
    prev_r = filled[f"plan_revenue{PSUF}"].sum()
    prev_c = filled[f"plan_cm{PSUF}"].sum()
    kpi(pk[0], "Units", n(prev_u), None,
        f"{filled['product'].nunique()} products · "
        f"{filled.month.nunique()} months", NEUT)
    kpi(pk[1], f"Revenue {cur}", n(prev_r), None,
        f"{n(prev_r / prev_u if prev_u else None, '{:,.2f}')} average price",
        NEUT)
    kpi(pk[2], f"CM {cur}", n(prev_c), None,
        f"{n((prev_r - prev_c) / prev_u if prev_u else None, '{:,.2f}')} "
        f"average cost", NEUT)
    kpi(pk[3], "CM %", p(prev_c / prev_r if prev_r else None), None,
        "weighted by the planned mix",
        tone(prev_c / prev_r if prev_r else None, good=0.40, warn=0.30))
    kpi(pk[4], "Rows", f"{len(filled):,}", None,
        f"of {len(pscope):,} in scope · {len(pscope) - len(filled):,} blank",
        NEUT)

    mq = pe.plan_margin_quality(filled)
    if mq:
        bits = []
        if mq["below_cost_rows"]:
            bits.append(f"<b>{mq['below_cost_rows']} rows are planned at or "
                        f"below cost</b>, losing {abs(mq['below_cost_cm']):,.0f}")
        if mq["thin_rows"]:
            bits.append(f"{mq['thin_rows']} rows sit under 15% margin, "
                        f"{mq['thin_revenue_share']:.0%} of planned revenue")
        bits.append(f"CM% across rows runs {mq['cm_pct_min']:.0%} to "
                    f"{mq['cm_pct_max']:.0%}, median {mq['cm_pct_median']:.0%}")
        note("Every one of these is knowable before anything is sold. "
             + ". ".join(bits) + ".")

    ptabs = st.tabs(["Shape", "Detail table", "Concentration",
                     "Margin quality", "Coverage", "What changed"])

    with ptabs[0]:
        st.caption("Where the year is loaded.")
        sh = pe.shape(filled, ["market", "month"])
        f = go.Figure()
        for i, mk in enumerate([m for m in MARKETS if m in set(sh.market)]):
            d = sh[sh.market == mk]
            f.add_trace(go.Bar(x=d.month.astype(str), y=d[f"plan_revenue{PSUF}"],
                               name=mk, marker_color=SERIES[i % len(SERIES)]))
        f.update_layout(barmode="stack", height=320,
                        yaxis_title=f"Planned revenue {cur}",
                        legend=dict(orientation="h", y=1.15, x=0))
        st.plotly_chart(f, width="stretch")

        cat = pe.shape(filled, ["category"]).sort_values(
            f"plan_revenue{PSUF}", ascending=False)
        c1, c2 = st.columns(2)
        f2 = go.Figure(go.Bar(x=cat[f"plan_revenue{PSUF}"], y=cat.category,
                              orientation="h", marker_color=BLUE,
                              text=[f"{v:,.0f}" for v in cat[f"plan_revenue{PSUF}"]],
                              textposition="auto"))
        f2.update_layout(height=max(300, 26 * len(cat)),
                         xaxis_title=f"Planned revenue {cur}",
                         yaxis=dict(autorange="reversed"))
        c1.plotly_chart(f2, width="stretch")
        f3 = go.Figure(go.Bar(x=cat.cm_pct * 100, y=cat.category,
                              orientation="h",
                              marker_color=[TEAL if v >= .35 else YELLOW
                                            if v >= .2 else ORANGE
                                            for v in cat.cm_pct],
                              text=[f"{v:.0%}" for v in cat.cm_pct],
                              textposition="auto"))
        f3.update_layout(height=max(300, 26 * len(cat)),
                         xaxis_title="Planned CM %",
                         yaxis=dict(autorange="reversed"))
        c2.plotly_chart(f3, width="stretch")
        st.caption("Left is where the money is planned. Right is how well it "
                   "converts. A tall bar on the left with a short one on the "
                   "right is volume bought at a poor rate.")

    with ptabs[1]:
        st.caption("Every planned row, as entered. Sortable and filterable — "
                   "the figures finance will look up directly.")
        cols = ["product_id", "category", "product", "market", "currency",
                "month", "plan_units", "plan_price_lc", "plan_cogs_unit_lc",
                "plan_revenue_lc", "plan_cogs_lc", "plan_cm_lc",
                "plan_revenue_aed", "plan_cm_aed", "fx_to_aed"]
        det = filled[[c for c in cols if c in filled.columns]].copy()
        det["plan_cm_pct"] = (det["plan_cm_lc"] / det["plan_revenue_lc"]).where(
            det["plan_revenue_lc"].ne(0))
        table(det, height=460)
        st.caption(f"{len(det):,} rows · "
                   f"{det.plan_units.sum():,.0f} units · "
                   f"AED {det.get('plan_revenue_aed', pd.Series(dtype=float)).sum():,.0f} "
                   f"consolidated")

        st.caption("Market by month, both currencies")
        mm_ = pe.shape(filled, ["market", "currency", "month"])
        keep = ["market", "currency", "month", "plan_units", "plan_revenue_lc",
                "plan_cogs_lc", "plan_cm_lc", "cm_pct", "wavg_price",
                "wavg_cost", "plan_revenue_aed", "plan_cm_aed"]
        table(mm_[[c for c in keep if c in mm_.columns]],
                     height=340)

        st.caption("Product by market, full year")
        bp = pe.shape(filled, ["market", "category", "product"])
        keep2 = ["market", "category", "product", "plan_units",
                 "plan_revenue_lc", "plan_cm_lc", "cm_pct", "wavg_price",
                 "wavg_cost", "plan_revenue_aed"]
        table(bp[[c for c in keep2 if c in bp.columns]].sort_values(
            "plan_revenue_lc", ascending=False),
            height=340)

    with ptabs[2]:
        st.caption("A plan can be achievable and still fragile.")
        cc = pe.plan_concentration(filled)
        if cc.empty:
            st.info("Nothing planned in this scope.")
        else:
            for r in cc.itertuples():
                note(f"<b>{r.market}: {r.top1_share:.0%} of planned revenue "
                     f"rests on {r.largest}</b>, top three carry "
                     f"{r.top3_share:.0%} across {r.items} products. "
                     f"It takes only {r.items_to_half} product"
                     f"{'s' if r.items_to_half != 1 else ''} to reach half the "
                     f"plan. Peak month {r.peak_month} is "
                     f"{r.peak_month_share:.0%} of the year.")
            show = cc[["market", "items", "largest", "top1_share", "top3_share",
                       "top5_share", "items_to_half", "peak_month",
                       "peak_month_share"]]
            table(show)

    with ptabs[3]:
        if not mq:
            st.info("Nothing planned in this scope.")
        else:
            if mq["below_cost_rows"]:
                st.caption(f"Planned at or below cost · {mq['below_cost_rows']}")
                table(mq["below_cost_detail"])
            if mq["thin_rows"]:
                st.caption(f"Under 15% margin · {mq['thin_rows']}")
                table(mq["thin_detail"], height=300)
            dist = filled.copy()
            dist["cm_pct"] = (dist["plan_cm_lc"] / dist["plan_revenue_lc"])
            f = go.Figure(go.Histogram(x=dist["cm_pct"] * 100, nbinsx=30,
                                       marker_color=BLUE))
            f.update_layout(height=280, xaxis_title="Planned CM % per row",
                            yaxis_title="Rows")
            st.plotly_chart(f, width="stretch")
            st.caption("A wide spread means the plan is not priced to a "
                       "consistent margin. That may be deliberate.")

    with ptabs[4]:
        st.caption("Where the plan is silent. Blank is not zero.")
        cov = pe.coverage(plan)
        piv = cov.pivot(index="market", columns="month", values="planned")
        piv = piv.reindex([m for m in MARKETS if m in piv.index])
        piv = piv.reindex(columns=[m for m in MONTHS if m in piv.columns])
        h = go.Figure(go.Heatmap(
            z=piv.astype(float).values, x=list(piv.columns), y=list(piv.index),
            colorscale=[[0, "#f6cfc8"], [1, "#bfe6d5"]], showscale=False,
            text=[["planned" if v else "no plan" for v in rv]
                  for rv in piv.values],
            texttemplate="%{text}",
            hovertemplate="%{y} · %{x}<br>%{text}<extra></extra>"))
        h.update_layout(height=230)
        st.plotly_chart(h, width="stretch")
        gaps = cov[(cov.market.isin(mk_scope)) & (~cov.planned)]
        if len(gaps):
            table(gaps[["market", "month"]])

    with ptabs[5]:
        st.caption("The workbook against its previous saved version in "
                   "SharePoint. No one has to remember what they edited.")
        prev, pinfo = load_previous_plan()
        if prev is None:
            st.info(f"No comparison available: {pinfo}")
        else:
            try:
                dp = pe.diff_plans(raw_plan, prev)
            except Exception as e:
                st.warning(f"Could not compare versions: {e}")
                dp = None
            if dp:
                who = (pinfo.get("modified_by") or "someone")
                when = (pinfo.get("modified") or "")[:16].replace("T", " ")
                d1 = st.columns(4)
                kpi(d1[0], "Rows changed", f"{dp['n_changed']:,}", None,
                    f"{dp['n_added']:,} added · {dp['n_removed']:,} removed",
                    NEUT)
                kpi(d1[1], "Units", n(dp["units_after"]),
                    n(dp["units_delta"], "{:+,.0f}"),
                    f"was {n(dp['units_before'])}",
                    GOOD if dp["units_delta"] >= 0 else BAD)
                kpi(d1[2], "Revenue", n(dp["revenue_after"]),
                    n(dp["revenue_delta"], "{:+,.0f}"),
                    f"was {n(dp['revenue_before'])} · local currency", NEUT)
                kpi(d1[3], "CM", n(dp["cm_after"]),
                    n(dp["cm_delta"], "{:+,.0f}"),
                    f"was {n(dp['cm_before'])}",
                    GOOD if dp["cm_delta"] >= 0 else BAD)
                note(f"Compared against the version saved {when} by "
                     f"<b>{who}</b>. {pinfo.get('versions_kept', 0)} versions "
                     f"kept by SharePoint.")
                if len(dp["newly_below_cost"]):
                    st.warning(
                        f"{len(dp['newly_below_cost'])} rows moved to or below "
                        f"cost in this edit: "
                        + ", ".join(dp["newly_below_cost"]["product"].head(6)))
                if dp["n_changed"]:
                    st.caption("Changed rows, largest CM impact first")
                    ch = dp["changed"][[
                        "market", "month", "product", "what", "units_delta",
                        "price_delta", "cost_delta", "revenue_delta",
                        "cm_delta"]].copy()
                    table(ch.reindex(
                        ch["cm_delta"].abs().sort_values(
                            ascending=False).index),
                        height=320)
                if dp["n_added"]:
                    st.caption(f"Added · {dp['n_added']}")
                    table(dp["added"][[
                        "market", "month", "product", "plan_units_now",
                        "plan_price_lc_now", "revenue_now", "cm_now"]],
                        height=220)
                if dp["n_removed"]:
                    st.caption(f"Removed · {dp['n_removed']}")
                    table(dp["removed"][[
                        "market", "month", "product", "plan_units_was",
                        "plan_price_lc_was", "revenue_was", "cm_was"]],
                        height=220)

    st.stop()


st.markdown("<div class='sec'>Plan against actual</div>", unsafe_allow_html=True)
k = st.columns(5)
kpi(k[0], "Units", n(A["act_units"]), delta(A["unit_att"]),
    f"plan {n(A['plan_units'])} boxes", tone(A["unit_att"]))

if orders and tb.get("implied_plan_orders"):
    kpi(k[1], "Orders", n(orders),
        f"{(orders / tb['implied_plan_orders'] - 1) * 100:+.0f} pts vs implied",
        f"basket {n(tb['basket'], '{:.1f}')} boxes · implied plan "
        f"{n(tb['implied_plan_orders'])} orders",
        tone(orders / tb["implied_plan_orders"]))
else:
    kpi(k[1], "Orders", n(orders), None,
        (f"{n(A['act_units'] / orders, '{:.1f}')} boxes per order"
         if orders else "needs the API source"), NEUT)

kpi(k[2], f"Revenue {cur}", n(A["act_rev"]), delta(A["rev_att"]),
    f"plan {n(A['plan_rev'])}", tone(A["rev_att"]))
kpi(k[3], f"CM {cur}", n(A["act_cm"]), delta(A["cm_att"]),
    f"plan {n(A['plan_cm'])}", tone(A["cm_att"]))
cmp_pts = ((A["act_cm_pct"] - A["plan_cm_pct"]) * 100
           if A["act_cm_pct"] is not None and A["plan_cm_pct"] is not None
           else None)
kpi(k[4], "CM %", p(A["act_cm_pct"]),
    None if cmp_pts is None else f"{cmp_pts:+.1f} pts vs plan",
    f"plan {p(A['plan_cm_pct'])}",
    NEUT if cmp_pts is None else (GOOD if cmp_pts >= 0
                                  else WARN if cmp_pts > -3 else BAD))

if tb.get("units_from_orders") is not None:
    note(f"<b>Unit gap decomposed.</b> "
         f"{n(tb['units_from_orders'], '{:+,.0f}')} boxes from order count and "
         f"{n(tb['units_from_basket'], '{:+,.0f}')} from basket size, against "
         f"an implied {n(tb['implied_plan_orders'])} orders at the achieved "
         f"basket of {n(tb['basket'], '{:.1f}')}. Fewer orders is a demand "
         f"problem; a smaller basket is a merchandising one.")


# ------------------------------------------------------- quality and risk

st.markdown("<div class='sec'>Quality and risk</div>", unsafe_allow_html=True)
q = st.columns(5)
pm = mom.get("prev_month", "")
prev = mom.get("prev", {})
now = mom.get("now", {})

if len(conc):
    cc = conc.iloc[0]
    kpi(q[0], "Concentration", p(cc.top1_share),
        pts(now.get("top1_share"), prev.get("top1_share"), pm),
        f"{cc.top1_product} · top 3 = {p(cc.top3_share)}",
        tone(cc.top1_share, good=0.30, warn=0.45, invert=True), dl_good=False)
else:
    kpi(q[0], "Concentration", "per market", None,
        "select a single market to see it")

if len(oqs):
    lost, tot_o = oqs.orders_lost.sum(), oqs.orders.sum()
    rate = lost / tot_o if tot_o else None
    kpi(q[1], "Cancellation rate", p(rate),
        pts(now.get("cancel_rate"), prev.get("cancel_rate"), pm),
        f"{int(lost)} of {int(tot_o)} orders · "
        f"{n(oqs.cost_lost_lc.sum())} of cost written off",
        tone(rate, good=0.05, warn=0.10, invert=True), dl_good=False)
else:
    kpi(q[1], "Cancellation rate", "n/a", None, "needs the API source")

denom = (sel.act_units * sel.plan_price_lc.fillna(0)).sum()
pr_ = sel.act_net_lc.sum() / denom if denom else None
kpi(q[2], "Price realisation", p(pr_), None,
    f"{int((cb.price_realisation < 0.90).sum()) if len(cb) else 0} products "
    f"below 90% of plan price", tone(pr_, good=0.98, warn=0.93))

if HAS_TIERS and sel.act_net_lc.sum():
    soft = 1 - sel.net_confirmed_lc.sum() / sel.act_net_lc.sum()
    kpi(q[3], "Revenue at risk", p(soft), None,
        "not yet delivered or paid, can still move",
        tone(soft, good=0.30, warn=0.60, invert=True))
else:
    kpi(q[3], "Revenue at risk", "n/a", None, "needs the API source")

if land:
    kpi(q[4], "Landing estimate", p(land["projected_attainment"]), None,
        f"{n(land['projected'])} {cur} if the run rate holds · paced at "
        f"{p(land['vs_paced'])}", tone(land["projected_attainment"]))
else:
    kpi(q[4], "Months in scope",
        str(sel[(sel.plan_units > 0) | (sel.act_units > 0)].month.nunique()),
        None, "landing estimate needs one market and one month")


# ------------------------------------------------------------ trend

if HAS_LINES:
    d = lines.copy()
    d["ts"] = pd.to_datetime(d.processed_at, utc=True, format="mixed")
    d = d[(d.market.isin(mk_scope)) & (d.ts.dt.year == YEAR) & (~d.cancelled)
          & (~d.financial_status.isin(ve.DEAD_STATUSES))]
    if sel_prods:
        d = d[d["product"].isin(sel_prods)]
    g = go.Figure()
    if month != YTD:
        dm = d[d.ts.dt.month == MONTHS.index(month) + 1]
        total = land["days_total"] if land else 31
        days = list(range(1, total + 1))
        daily = (dm.assign(day=dm.ts.dt.day).groupby("day")["net_line_lc"].sum()
                 .reindex(days, fill_value=0).cumsum())
        cut = max(1, land["days_elapsed"] if land else total)
        g.add_trace(go.Scatter(x=days, y=[A["plan_rev"] * i / total for i in days],
                               name="Plan, paced",
                               line=dict(color=GREY, width=2, dash="dash")))
        g.add_trace(go.Scatter(x=days[:cut], y=list(daily.values)[:cut],
                               name="Actual", line=dict(color=BLUE, width=2.5),
                               fill="tozeroy", fillcolor="rgba(42,120,214,.07)"))
        if land and land["projected"] and cut < total:
            g.add_trace(go.Scatter(x=[cut, total],
                                   y=[daily.values[cut - 1], land["projected"]],
                                   name="Landing estimate",
                                   line=dict(color=YELLOW, width=2, dash="dot")))
        g.update_layout(xaxis_title=f"Day of {month}")
    else:
        grid = ve.rollup(sel, ["month"])
        g.add_trace(go.Bar(x=grid.month.astype(str), y=grid[f"plan_revenue{SUF}"],
                           name="Plan", marker_color="#dfe3e8"))
        g.add_trace(go.Bar(x=grid.month.astype(str), y=grid[f"act_net{SUF}"],
                           name="Actual", marker_color=BLUE))
        g.update_layout(barmode="overlay")
    g.update_layout(height=300, legend=dict(orientation="h", y=1.15, x=0),
                    yaxis_title=f"Revenue {cur}")
    st.plotly_chart(g, width="stretch")

if ameta.get("missing"):
    st.caption(f"Not connected yet: {', '.join(ameta['missing'])}")
for m_, e in (ameta.get("errors") or {}).items():
    st.warning(f"{m_}: {e}")


# ------------------------------------------------------------------ tabs

st.divider()
HAS_COST = "act_cm_dated_lc" in combined.columns
tabs = st.tabs(["Attainment", "Comparison", "Margin bridge", "Cost & margin",
                "Price simulator", "Pricing advisor", "Price realisation",
                "Portfolio", "Where demand came from", "Order quality",
                "Exceptions"])

with tabs[0]:
    grid = ve.rollup(combined, ["market", "month"])
    piv = grid.pivot(index="market", columns="month",
                     values="revenue_attainment_aed")
    piv = piv.reindex([m for m in MARKETS if m in piv.index])
    piv = piv.reindex(columns=[m for m in MONTHS if m in piv.columns])
    flat = piv.stack().dropna() if len(piv) else pd.Series(dtype=float)
    if len(flat):
        worst = flat.idxmin()
        note(f"<b>{len(flat)} market-months have both a plan and sales.</b> "
             f"Weakest is {worst[0]} in {worst[1]} at {flat.min():.0%} of plan; "
             f"strongest is {flat.idxmax()[0]} in {flat.idxmax()[1]} at "
             f"{flat.max():.0%}. Blank cells mean no plan and no sales, which "
             f"is not the same as zero.")
    h = go.Figure(go.Heatmap(
        z=piv.values * 100, x=list(piv.columns), y=list(piv.index),
        colorscale=[[0, "#f6cfc8"], [0.5, "#fdf1da"], [1, "#bfe6d5"]],
        zmin=0, zmax=140,
        text=[[f"{v*100:.0f}%" if pd.notna(v) else "" for v in rv]
              for rv in piv.values],
        texttemplate="%{text}", hoverongaps=False,
        hovertemplate="%{y} · %{x}<br>%{text} of plan<extra></extra>",
        colorbar=dict(title="% of plan")))
    h.update_layout(height=250)
    st.plotly_chart(h, width="stretch")

    mm = ve.rollup(sel, ["month"])
    show = mm[["month", "plan_units", "act_units", "unit_attainment",
               f"plan_revenue{SUF}", f"act_net{SUF}", ATT,
               f"plan_cm{SUF}", f"act_cm_at_plan{SUF}", CMP_]].copy()
    show.columns = ["month", "plan units", "actual units", "unit att",
                    f"plan rev {cur}", f"actual rev {cur}", "rev att",
                    f"plan CM {cur}", f"actual CM {cur}", "CM%"]
    table(show, height=300)

with tabs[1]:
    cc1, cc2 = st.columns([1, 3])
    dim = cc1.selectbox("Compare by", ["Market", "Month", "Category", "Product"])
    col = {"Market": "market", "Month": "month", "Category": "category",
           "Product": "product"}[dim]
    universe = (MARKETS if col == "market" else
                [m for m in MONTHS if m in set(base.month)] if col == "month"
                else sorted(base[col].dropna().unique()))
    picked = cc2.multiselect(f"{dim}s", universe,
                             default=list(universe[:3]) if universe else [])
    if not picked:
        st.info("Pick at least one to compare.")
    else:
        scope = base if col in ("market", "month") else sel
        if col != "month" and month != YTD:
            scope = scope[scope.month == month]
        scope = scope[scope[col].isin(picked)]
        g = ve.rollup(scope, [col]).set_index(col).reindex(picked).reset_index()
        best = g.loc[g[ATT].idxmax()] if g[ATT].notna().any() else None
        wrst = g.loc[g[ATT].idxmin()] if g[ATT].notna().any() else None
        if best is not None and wrst is not None and len(g) > 1:
            note(f"<b>{best[col]} leads at {best[ATT]:.0%} of plan; "
                 f"{wrst[col]} trails at {wrst[ATT]:.0%}.</b> "
                 f"A spread of {(best[ATT] - wrst[ATT]) * 100:.0f} points on the "
                 f"same plan basis, worth "
                 f"{abs(best[f'var_revenue{SUF}'] - wrst[f'var_revenue{SUF}']):,.0f} "
                 f"{cur} of variance between them.")
        cols = st.columns(len(picked))
        for i, rowi in g.iterrows():
            kpi(cols[i], str(rowi[col]), n(rowi[f"act_net{SUF}"]),
                delta(rowi[ATT]),
                f"plan {n(rowi[f'plan_revenue{SUF}'])} {cur} · "
                f"{n(rowi.act_units)} boxes · CM {p(rowi[CMP_])}",
                tone(rowi[ATT]))
        f = go.Figure()
        f.add_trace(go.Bar(x=g[col].astype(str), y=g[f"plan_revenue{SUF}"],
                           name="Plan", marker_color="#dfe3e8"))
        f.add_trace(go.Bar(x=g[col].astype(str), y=g[f"act_net{SUF}"],
                           name="Actual", marker_color=BLUE))
        f.update_layout(barmode="group", height=320,
                        legend=dict(orientation="h", y=1.15, x=0),
                        yaxis_title=f"Revenue {cur}")
        st.plotly_chart(f, width="stretch")
        show = g[[col, "plan_units", "act_units", "unit_attainment",
                  f"plan_revenue{SUF}", f"act_net{SUF}", ATT,
                  f"act_cm_at_plan{SUF}", CMP_]].copy()
        show.columns = [dim.lower(), "plan units", "actual units", "unit att",
                        f"plan rev {cur}", f"actual rev {cur}", "rev att",
                        f"CM {cur}", "CM%"]
        table(show)

with tabs[2]:
    b = ve.bridge(sel)
    drv = {"volume": b["volume"], "price": b["price"], "mix": b["mix"]}
    worst = min(drv, key=drv.get)
    share = abs(drv[worst]) / abs(b["gap"]) if b["gap"] else None
    note(f"<b>{worst.title()} is {share:.0%} of the gap.</b> "
         f"Plan {b['plan']:,.0f}, actual {b['actual']:,.0f}, a difference of "
         f"{b['gap']:+,.0f}. Volume {b['volume']:+,.0f}, price "
         f"{b['price']:+,.0f}, mix {b['mix']:+,.0f}. "
         + ("A volume gap is supply or demand. " if worst == "volume" else
            "A price gap is discounting or downtrading. " if worst == "price"
            else "A mix gap means the same boxes sold at a different blend. ")
         + "Read one market at a time — the bridge is in local currency.")
    w = go.Figure(go.Waterfall(
        orientation="v",
        measure=["absolute", "relative", "relative", "relative", "total"],
        x=["Plan", "Volume", "Price", "Mix", "Actual"],
        y=[b["plan"], b["volume"], b["price"], b["mix"], None],
        text=[f"{v:,.0f}" for v in [b["plan"], b["volume"], b["price"],
                                    b["mix"], b["actual"]]],
        textposition="outside",
        connector={"line": {"color": GREY, "width": 1}},
        increasing={"marker": {"color": TEAL}},
        decreasing={"marker": {"color": ORANGE}},
        totals={"marker": {"color": BLUE}}))
    w.update_layout(height=330, margin=dict(t=20), showlegend=False,
                    yaxis_title=f"Revenue, {LOCAL}")
    st.plotly_chart(w, width="stretch")
    rows = [{"category": cat} | dict(ve.bridge(sel, category=cat))
            for cat in sorted(sel.category.dropna().unique())]
    if rows:
        st.caption("The same decomposition per category, so the gap has an owner.")
        table(pd.DataFrame(rows).sort_values("gap"), height=280)

with tabs[3]:
    st.caption("Plan cost is what you forecast. Dated cost is what the product "
               "actually cost on the day each box was sold. The gap between "
               "them is cost movement, not commercial performance.")
    if not HAS_COST:
        st.info("Add a Cost_Log sheet to the plan workbook to see margin at "
                "actual dated cost. Columns: store_product_name, market, "
                "valid_from, cogs_unit_lc, note. Append a row when a cost "
                "changes — never edit an old one.")
    else:
        g = ve.rollup(sel, ["month"])
        c1, c2, c3 = st.columns(3)
        pc = sel["act_cm_at_plan_lc"].sum()
        dc = sel["act_cm_dated_lc"].sum()
        rv = sel["act_net_lc"].sum()
        kpi(c1, "CM at plan cost", n(pc), None,
            p(pc / rv if rv else None) + " of net revenue", NEUT)
        kpi(c2, "CM at dated cost", n(dc), None,
            p(dc / rv if rv else None) + " of net revenue",
            tone(dc / rv if rv else None, good=0.40, warn=0.30))
        kpi(c3, "Cost movement", n(dc - pc, "{:+,.0f}"), None,
            "dated cost against plan cost",
            GOOD if dc >= pc else BAD)

        f = go.Figure()
        f.add_trace(go.Bar(x=g.month.astype(str), y=g.act_cm_at_plan_lc,
                           name="At plan cost", marker_color="#dfe3e8"))
        f.add_trace(go.Bar(x=g.month.astype(str), y=g.act_cm_dated_lc,
                           name="At dated cost", marker_color=TEAL))
        f.update_layout(barmode="group", height=310,
                        legend=dict(orientation="h", y=1.15, x=0),
                        yaxis_title="Contribution margin")
        st.plotly_chart(f, width="stretch")

        show = g[["month", "act_units", "act_net_lc", "act_cm_at_plan_lc",
                  "act_cm_dated_lc", "act_cm_dated_pct",
                  "dated_vs_plan_cost"]].copy()
        show.columns = ["month", "units", "net revenue", "CM at plan cost",
                        "CM at dated cost", "CM%", "cost movement"]
        table(show)

        if HAS_LINES and cost_log is not None:
            cov = ve.cost_coverage(lines, cost_log, plan, YEAR)
            cov = cov[cov.market.isin(mk_scope)]
            if len(cov):
                gap = cov[cov.cost_source != "dated"]
                if len(gap):
                    note(f"<b>{gap.share.sum():.0%} of revenue in scope has no "
                         f"dated cost entry</b> and falls back to the planned "
                         f"cost. Those months will restate when you add the "
                         f"missing Cost_Log rows.")
                st.caption("Where the cost figure came from")
                table(cov)

        st.caption("The log is append-only. To change a cost, add a row with a "
                   "new valid_from — never edit an existing one, or history "
                   "silently rewrites itself.")


with tabs[4]:
    st.caption("Change a price and see what would have to be true. Volume is "
               "held flat on purpose — the number that decides it is the "
               "break-even, not a guess at how customers respond.")

    s1, s2, s3, s4 = st.columns([1.4, 1.4, 1.6, 1])
    scope = s1.radio("Apply to", ["Whole market", "One category", "One product"],
                     index=0)
    sim_cat = sim_prod = None
    if scope == "One category":
        sim_cat = s2.selectbox("Category", sorted(sel.category.dropna().unique()))
    elif scope == "One product":
        opts = sorted(sel[sel.act_units > 0]["product"].dropna().unique())
        sim_prod = s2.selectbox("Product", opts) if len(opts) else None
    else:
        s2.markdown("&nbsp;", unsafe_allow_html=True)
    pct = s3.slider("Price change %", -30, 30, -10, 1)
    basis = s4.radio("Basis", ["Actual", "Plan"], index=0,
                     help="Actual uses what was really sold and achieved. "
                          "Plan is for months that have not happened yet.")

    scope_df = combined[combined.market.isin(mk_scope)]
    if month != YTD:
        scope_df = scope_df[scope_df.month == month]

    try:
        sim = px.simulate(
            scope_df,
            [px.Scenario(pct=pct, category=sim_cat, product=sim_prod)],
            use_actual=(basis == "Actual"))
    except px.PricingError as e:
        st.info(str(e))
        sim = None

    if sim:
        be = sim["breakeven_volume_pct"]
        k1 = st.columns(4)
        kpi(k1[0], f"CM at {pct:+d}%", n(sim["new_cm"]),
            n(sim["cm_change"], "{:+,.0f}"),
            f"from {n(sim['base_cm'])} {cur}",
            GOOD if sim["cm_change"] >= 0 else BAD)
        kpi(k1[1], "Break-even volume",
            "n/a" if be is None else f"{be:+.0f}%", None,
            "units needed to hold CM" if (be or 0) > 0
            else "units you could afford to lose",
            NEUT if be is None else tone(-abs(be), good=-15, warn=-30))
        kpi(k1[2], "CM %", p(sim["new_cm_pct"]), None,
            f"from {p(sim['base_cm_pct'])}",
            tone(sim["new_cm_pct"], good=0.35, warn=0.25))
        kpi(k1[3], "Revenue", n(sim["new_revenue"]),
            n(sim["revenue_change"], "{:+,.0f}"),
            f"on {n(sim['base_units'])} boxes held flat", NEUT)

        if be is not None:
            verdict = ("easy" if abs(be) < 10 else
                       "demanding" if abs(be) < 30 else "unlikely")
            note(f"<b>A {abs(pct)}% "
                 f"{'cut' if pct < 0 else 'rise'} needs "
                 f"{'+' if be > 0 else ''}{be:.0f}% volume to hold "
                 f"contribution margin — {verdict}.</b> "
                 f"Margin here is {p(sim['base_cm_pct'])}, and the thinner the "
                 f"margin the more volume a cut has to find. Costed at "
                 f"{sim['cost_basis']} cost.")
        if sim["rows_below_cost_after"]:
            st.warning(
                f"{sim['rows_below_cost_after']} rows fall below cost at this "
                f"price: {', '.join(sim['products_below_cost_after'][:6])}")

        sens = px.sensitivity(scope_df, category=sim_cat, product=sim_prod,
                              use_actual=(basis == "Actual"))
        f = go.Figure()
        f.add_trace(go.Bar(x=sens.price_change_pct, y=sens.cm, name="CM",
                           marker_color=[TEAL if v >= sim["base_cm"] else ORANGE
                                         for v in sens.cm]))
        f.add_trace(go.Scatter(x=sens.price_change_pct,
                               y=sens.breakeven_volume_pct, name="Break-even %",
                               yaxis="y2", line=dict(color=BLUE, width=2.5)))
        f.update_layout(height=330, yaxis_title=f"CM {cur}",
                        yaxis2=dict(title="Break-even volume %", overlaying="y",
                                    side="right", showgrid=False),
                        xaxis_title="Price change %",
                        legend=dict(orientation="h", y=1.15, x=0))
        st.plotly_chart(f, width="stretch")
        st.caption("Break-even is not linear in the price change. A small cut "
                   "on a thin margin can need more volume than a larger cut on "
                   "a fat one.")

        bt = px.breakeven_table(scope_df, pct, by="product",
                               use_actual=(basis == "Actual"))
        if len(bt):
            st.caption(f"What each product would need at {pct:+d}%")
            show = bt[["market", "product", "units", "cm_pct_before",
                       "breakeven_volume_pct", "verdict"]].copy()
            show.columns = ["market", "product", "units", "CM% now",
                            "volume needed %", "verdict"]
            table(show, height=300)

with tabs[5]:
    st.caption("What the margin arithmetic says, ranked by money at stake. "
               "No recommendation names an optimal price — that needs an "
               "elasticity this data cannot yet identify.")
    adv = px.advise(combined, plan, cost_log,
                    market=None if CONSOL else market,
                    month=None if month == YTD else month)
    if adv.empty:
        note("Nothing flagged in this scope. Either the pricing is sound or "
             "there is not enough volume yet to judge — the advisor ignores "
             "products under 20 boxes.")
    else:
        counts = adv.severity.value_counts().to_dict()
        note("<b>" + " · ".join(f"{v} {k}" for k, v in counts.items())
             + f"</b> · {n(adv.stake.sum())} {cur} at stake in total. "
               "Each recommendation states what is wrong, what it costs, and "
               "what would have to be true to fix it with price.")
        SEV_C = {"urgent": BAD, "high": ORANGE, "medium": YELLOW, "low": NEUT}
        for r in adv.head(12).itertuples():
            st.markdown(
                f"<div class='fin' style='--acc:{SEV_C.get(r.severity, NEUT)};"
                f"margin-bottom:9px'>"
                f"<div class='s'>{n(r.stake)} {cur} · {r.severity}</div>"
                f"<div class='t'>{r.product} · {r.market} · {r.month} — "
                f"{r.issue}</div>"
                f"<div class='d'>{r.detail}<br><b>{r.action}</b></div></div>",
                unsafe_allow_html=True)
        if len(adv) > 12:
            with st.expander(f"{len(adv) - 12} more"):
                table(adv[["severity", "stake", "product", "market",
                                  "month", "issue", "action"]],
                             )

    health = px.portfolio_price_health(combined,
                                       None if CONSOL else market)
    if len(health):
        st.caption("Price health by product — what it earns a box, its share "
                   "of margin, and the volume a 5% cut would have to find.")
        show = health[["market", "product", "units", "price", "cost", "cm_box",
                       "cm_pct", "cm_share", "realisation",
                       "breakeven_at_minus5"]].copy()
        show.columns = ["market", "product", "units", "price", "cost",
                        "CM/box", "CM%", "CM share", "realisation",
                        "vol needed at -5%"]
        table(show, height=340)


with tabs[6]:
    if cb.empty:
        st.info("No sales in this scope.")
    else:
        weak = cb[cb.price_realisation < 0.90]
        lost = ((cb.plan_wavg_price - cb.act_wavg_price) * cb.act_units)
        note(f"<b>{len(weak)} of {len(cb)} products sold below 90% of plan "
             f"price.</b> Net effect across all products is "
             f"{-lost.sum():+,.0f} against plan price on units actually sold. "
             + (f"Worst is {weak.iloc[0]['product']} at "
                f"{weak.iloc[0]['price_realisation']:.0%}. " if len(weak) else "")
             + "A low realisation is either discounting or a shift to cheaper "
               "grades within the same product.")
        d = cb.sort_values("price_realisation")
        f = go.Figure(go.Bar(
            x=(d.price_realisation - 1) * 100, y=d[LBL], orientation="h",
            marker_color=[ORANGE if v < 1 else TEAL for v in d.price_realisation],
            text=[f"{v:.0%}" for v in d.price_realisation], textposition="auto"))
        f.update_layout(height=max(300, 28 * len(d)),
                        xaxis_title="Achieved vs plan price, percentage points",
                        yaxis=dict(autorange="reversed"))
        st.plotly_chart(f, width="stretch")
        show = d[[LBL, "product", "act_units", "plan_wavg_price",
                  "act_wavg_price", "price_realisation",
                  "act_cm_at_plan_lc"]].copy()
        show.columns = ["product", "store name", "units", "plan price",
                        "achieved price", "realisation", "CM"]
        table(show, height=280)

with tabs[7]:
    if cb.empty:
        st.info("No sales in this scope.")
    else:
        rng = cb.cm_per_box.max() / cb.cm_per_box.min() if cb.cm_per_box.min() else None
        note(f"<b>CM per box ranges "
             f"{cb.cm_per_box.min():,.1f} to {cb.cm_per_box.max():,.1f}"
             + (f", a {rng:.1f}× spread." if rng else ".")
             + f"</b> {cb.iloc[0]['product']} contributes "
               f"{cb.iloc[0]['cm_share']:.0%} of all margin. When freight "
               f"capacity binds, the per-box ranking on the right is the "
               f"allocation decision, not the total on the left.")
        c1, c2 = st.columns(2)
        d = cb.head(14)
        f = go.Figure(go.Bar(x=d.act_cm_at_plan_lc, y=d[LBL],
                             orientation="h", marker_color=BLUE,
                             text=[f"{v:,.0f}" for v in d.act_cm_at_plan_lc],
                             textposition="auto"))
        f.update_layout(height=max(320, 28 * len(d)),
                        xaxis_title="CM contribution",
                        yaxis=dict(autorange="reversed"))
        c1.plotly_chart(f, width="stretch")
        d2 = cb.sort_values("cm_per_box", ascending=False)
        f2 = go.Figure(go.Bar(x=d2.cm_per_box, y=d2[LBL], orientation="h",
                              marker_color=TEAL,
                              text=[f"{v:,.1f}" for v in d2.cm_per_box],
                              textposition="auto"))
        f2.update_layout(height=max(320, 28 * len(d2)),
                         xaxis_title="CM per box",
                         yaxis=dict(autorange="reversed"))
        c2.plotly_chart(f2, width="stretch")
        cy = ve.concentration(base)
        if len(cy):
            st.caption("Concentration across the year.")
            show = cy[["market", "month", "products", "top1_product",
                       "top1_share", "top3_share", "revenue_lc"]].copy()
            show.columns = ["market", "month", "products sold", "largest",
                            "largest share", "top 3 share", "revenue"]
            table(show, height=320)

with tabs[8]:
    if not HAS_LINES:
        st.info("This needs the Shopify API source.")
    else:
        mk = None if CONSOL else market
        mo = None if month == YTD else month
        segs = {dim_: ve.by_segment(lines, dim_, plan, YEAR, mk, mo)
                for dim_ in ve.SEGMENTS}
        bits = []
        for dim_, label in ve.SEGMENTS.items():
            g = segs[dim_]
            if g.empty:
                continue
            t = g.iloc[0]
            bits.append(f"{t[dim_]} is {t.revenue_share:.0%} of revenue at "
                        f"{t.cm_pct:.0%} margin and {t.units_per_order:.1f} "
                        f"boxes per order")
        if bits:
            note("<b>Where the demand sits.</b> " + "; ".join(bits) +
                 ". These dimensions live on the order, not the plan, so they "
                 "say where demand came from rather than whether plan was met.")
        cols = st.columns(3)
        for i, (dim_, label) in enumerate(ve.SEGMENTS.items()):
            g = segs[dim_]
            if g.empty:
                cols[i].info(f"No {label.lower()} data.")
                continue
            fig = go.Figure(go.Bar(x=g[dim_].astype(str), y=g.revenue_lc,
                                   marker_color=SERIES[: len(g)],
                                   text=[f"{v:.0%}" for v in g.revenue_share],
                                   textposition="outside"))
            fig.update_layout(height=260, margin=dict(t=26),
                              title=dict(text=label, font=dict(size=13)),
                              yaxis_title="Revenue", showlegend=False)
            cols[i].plotly_chart(fig, width="stretch")
        for dim_, label in ve.SEGMENTS.items():
            g = segs[dim_]
            if g.empty:
                continue
            st.caption(f"{label} · orders, basket size and margin")
            show = g[[dim_, "orders", "units", "units_per_order", "aov_lc",
                      "revenue_lc", "revenue_share", "cm_lc", "cm_pct",
                      "products"]].copy()
            show.columns = [label.lower(), "orders", "units", "boxes/order",
                            "avg order", "revenue", "share", "CM", "CM%",
                            "products"]
            table(show)

with tabs[9]:
    if oq.empty:
        st.info("Order quality needs the Shopify API source.")
    else:
        d = oq[oq.market.isin(mk_scope)]
        note(f"<b>{int(d.orders_lost.sum())} of {int(d.orders.sum())} orders "
             f"lost across the scope, {d.orders_lost.sum()/d.orders.sum():.0%}.</b> "
             f"{d.units_lost.sum():,.0f} boxes and "
             f"{d.cost_lost_lc.sum():,.0f} of cost at plan rates. On "
             f"make-to-order air freight that fruit was already procured and "
             f"flown, so this is a write-off rather than a lost sale.")
        g = go.Figure()
        g.add_trace(go.Bar(x=d.month.astype(str), y=d.orders - d.orders_lost,
                           name="Kept", marker_color=TEAL))
        g.add_trace(go.Bar(x=d.month.astype(str), y=d.orders_lost,
                           name="Cancelled or voided", marker_color=ORANGE))
        g.update_layout(barmode="stack", height=300, yaxis_title="Orders",
                        legend=dict(orientation="h", y=1.15, x=0))
        st.plotly_chart(g, width="stretch")
        show = d[["market", "month", "orders", "orders_lost", "cancel_rate",
                  "units_lost", "value_lost_lc", "cost_lost_lc"]].copy()
        show.columns = ["market", "month", "orders", "lost", "rate",
                        "units lost", "revenue lost", "cost written off"]
        table(show)
        if HAS_TIERS:
            st.caption("Of what survived, how much is settled.")
            tot = sel[["net_confirmed_lc", "net_committed_lc",
                       "net_potential_lc"]].sum()
            t3 = st.columns(3)
            for i, (lab, sub, key) in enumerate([
                    ("Confirmed", "delivered and paid", "net_confirmed_lc"),
                    ("Committed", "delivered, COD open", "net_committed_lc"),
                    ("Potential", "not yet delivered", "net_potential_lc")]):
                kpi(t3[i], lab, n(tot[key]), None,
                    p(tot[key] / tot.sum() if tot.sum() else None) + " · " + sub,
                    {"Confirmed": GOOD, "Committed": BLUE,
                     "Potential": WARN}[lab])

with tabs[10]:
    e = ve.exceptions(base)
    ns = e[e.presence == "sold, not planned"].copy()
    npl = e[e.presence == "planned, not sold"].copy()
    thin = plan[(plan.market.isin(mk_scope))
                & (plan.plan_cogs_unit_lc >= plan.plan_price_lc)]
    note(f"<b>Ranked by money at stake, not by row order.</b> "
         f"{len(npl)} planned rows sold nothing, worth "
         f"{npl.plan_revenue_lc.sum():,.0f} of plan. "
         f"{len(ns)} products sold without a plan, worth "
         f"{ns.act_net_lc.sum():,.0f} of revenue the plan never expected. "
         f"{len(thin)} rows are planned at or below cost.")
    a1, a2 = st.columns(2)
    a1.caption(f"Sold but not planned · {len(ns)} · highest value first")
    table(ns.sort_values("act_net_lc", ascending=False)[
        ["market", "month", "product_label", "product", "act_units",
         "act_net_lc"]],
        height=260)
    a2.caption(f"Planned but not sold · {len(npl)} · highest value first")
    table(npl.sort_values("plan_revenue_lc", ascending=False)[
        ["market", "month", "product_label", "product", "plan_units",
         "plan_revenue_lc"]],
        height=260)
    if len(thin):
        st.caption(f"Planned at or below cost · {len(thin)}")
        table(thin[["market", "month", "product", "plan_units",
                        "plan_price_lc", "plan_cogs_unit_lc"]])
    um = ve.unmatched_products(actuals, plan, aliases)
    if len(um):
        st.caption(f"Store product names that do not reach a plan product · "
                   f"{len(um)} · highest revenue first")
        table(um, height=260)
        st.caption(
            "Each of these means sales going unattributed and a plan row "
            "looking unsold. Add an Aliases sheet to the plan workbook with "
            "columns store_name and plan_name to close them. Word-order "
            "differences resolve on their own; only genuinely different names "
            "need an entry.")

    cov = pe.coverage(plan)
    gaps = cov[(cov.market.isin(mk_scope)) & (~cov.planned)]
    if len(gaps):
        st.caption("Months with no plan at all")
        table(gaps[["market", "month"]])

"""Inripe — Product Availability dashboard.

Presentation only. Every number comes from availability_engine.
No calculation happens in this file.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import availability_engine as ae
from calendar_engine import week_grid
from data_loader import load_master

YEAR = 2026
MARKETS = ["UAE", "QA", "KSA", "EG"]
BLUE, ORANGE, TEAL, YELLOW, PINK, GREY = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#888780",
)

st.set_page_config(page_title="Inripe · Availability", layout="wide")


# ----------------------------------------------------------------- data


@st.cache_data(ttl=600)
def get_data(year: int):
    raw, markets = load_master()
    spine = ae.build_spine(raw, year)
    return raw, markets, spine


try:
    raw, markets_sheet, spine = get_data(YEAR)
except Exception as exc:
    st.error(f"Could not load the product master: {exc}")
    st.stop()

grid = week_grid(YEAR)
week_dates = {n: (a, b) for n, a, b in grid}


def week_label(n: int) -> str:
    a, _ = week_dates[n]
    return f"wk {n} · {a.strftime('%-d %b')}"


def this_week() -> int:
    today = date.today()
    if today.year != YEAR:
        return 1
    for n, a, b in grid:
        if a <= today <= b:
            return n
    return 52


# ------------------------------------------------------------ selectors

st.markdown("### Product availability")
st.caption(
    f"What can be sold, {YEAR}. Breadth only — no volumes, no revenue, no targets."
)

c = st.columns([1, 1.4, 1.6, 1, 1, 2.2])
market = c[0].selectbox("Market", MARKETS, index=0)

cats = sorted(spine["category"].unique())
sel_cats = c[1].multiselect("Category", cats, default=[])

prod_pool = spine[spine["category"].isin(sel_cats)] if sel_cats else spine
prods = sorted(prod_pool["product"].unique())
sel_prods = c[2].multiselect("Product", prods, default=[])

tiers = sorted(spine["tier"].unique())
sel_tiers = c[3].selectbox("Tier", ["All"] + tiers, index=0)
origins = sorted(spine["origin"].unique())
sel_origin = c[4].selectbox("Origin", ["All"] + origins, index=0)
week = c[5].slider("Week", 1, len(grid), this_week(), format="%d")

flt = dict(
    category=sel_cats or None,
    product=sel_prods or None,
    tier=None if sel_tiers == "All" else sel_tiers,
    origin=None if sel_origin == "All" else sel_origin,
)
scope_bits = [market]
if sel_cats:
    scope_bits.append(", ".join(sel_cats[:2]) + ("…" if len(sel_cats) > 2 else ""))
if sel_tiers != "All":
    scope_bits.append(sel_tiers)
if sel_origin != "All":
    scope_bits.append(sel_origin)
SCOPE = " · ".join(scope_bits)

breadth = ae.weekly_breadth(spine, market=market, **flt)
row = breadth[breadth["report_week"] == week]
n_sku = int(row["skus"].iloc[0]) if len(row) else 0
n_cat = int(row["categories"].iloc[0]) if len(row) else 0


def na(v: int) -> str:
    return "n/a" if v == 0 else str(v)


# ---------------------------------------------------------------- part A

st.divider()
k = st.columns(5)

k[0].metric("Shelf now", f"{na(n_sku)} SKUs")
k[0].caption(f"{na(n_cat)} categories · {SCOPE} · {week_label(week)}")

live = ae.live_on(spine, week_dates[week][0], market=market, **flt)
t1 = live[live["tier"] == "Tier 1"]["product"].nunique()
n_t1_total = int(spine[spine["tier"] == "Tier 1"]["product"].nunique())
k[1].metric("Hero coverage", f"{t1} Tier 1")
k[1].caption(f"live this week, of {n_t1_total} Tier 1 products")

if n_sku:
    top = live.groupby("category")["product_id"].nunique().sort_values(ascending=False)
    share = top.iloc[0] / n_sku
    k[2].metric("Concentration", f"{share:.0%}")
    k[2].caption(f"{top.index[0]} · {top.iloc[0]} of {n_sku} · largest category")
else:
    k[2].metric("Concentration", "n/a")

tr = ae.transitions(spine, market=market, **flt)
w_start, _ = week_dates[week]
w_end = week_dates[min(len(grid), week + 4)][1]
ent = tr[(tr["first_day"] > w_start) & (tr["first_day"] <= w_end)]
exi = tr[(tr["last_day"] >= w_start) & (tr["last_day"] <= w_end)]
k[3].metric("Changing soon", f"{len(ent)} in · {len(exi)} out")
k[3].caption(f"next 4 weeks, to {w_end.strftime('%-d %b')}")

ahead = breadth[breadth["report_week"] >= week]
if len(ahead):
    lo = ahead.loc[ahead["categories"].idxmin()]
    run = int((ahead["categories"] == lo["categories"]).sum())
    k[4].metric("Narrow stretch ahead", f"{int(lo['categories'])} categories")
    k[4].caption(f"{run} weeks at that level, from {week_label(int(lo['report_week']))}")

fig = go.Figure()
fig.add_trace(go.Scatter(x=breadth["report_week"], y=breadth["skus"], name="SKUs live",
                         line=dict(color=BLUE, width=2)))
fig.add_trace(go.Scatter(x=breadth["report_week"], y=breadth["categories"],
                         name="Categories live",
                         line=dict(color=ORANGE, width=2, dash="dash")))
fig.add_vline(x=week, line=dict(color=GREY, width=1, dash="dot"))
fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                  legend=dict(orientation="h", y=1.15, x=0),
                  xaxis_title="Reporting week", yaxis_title=None,
                  yaxis=dict(rangemode="tozero"))
st.plotly_chart(fig, width='stretch')
st.caption(f"{SCOPE} · does the SKU peak match the category peak?")

qc = []
if raw.get("quality_month") is not None:
    qc.append(f"{int(raw['quality_month'].isna().sum())} products without a quality point")
if qc:
    st.caption("Data check · " + " · ".join(qc))


# ---------------------------------------------------------------- part B

st.divider()
tabs = st.tabs([
    "Season calendar", "Coverage & gaps", "Transitions & continuity",
    "Portfolio shape", "Market gaps",
])

with tabs[0]:
    st.caption("When each product is available.")
    by = st.radio("Group by", ["Category", "Product"], horizontal=True,
                  label_visibility="collapsed")
    t = ae.transitions(spine, market=market, **flt)
    if t.empty:
        st.info("Nothing live in this scope.")
    else:
        t = t.copy()
        t["start"] = pd.to_datetime(t["first_day"])
        t["finish"] = pd.to_datetime(t["last_day"]) + pd.Timedelta(days=1)
        t["row"] = t["category"] if by == "Category" else t["product"]
        t = t.sort_values(["category", "product", "start"])
        order = list(dict.fromkeys(t["row"]))
        g = px.timeline(t, x_start="start", x_end="finish", y="row",
                        color="category",
                        hover_data={"product": True, "start": False,
                                    "finish": False, "row": False,
                                    "category": False},
                        category_orders={"row": order})
        g.update_yaxes(autorange="reversed", title=None)
        g.update_xaxes(range=[date(YEAR, 1, 1), date(YEAR, 12, 31)], title=None)
        g.update_layout(height=max(340, 26 * len(order)),
                        margin=dict(l=0, r=0, t=10, b=0),
                        showlegend=False, bargap=0.25)
        st.plotly_chart(g, width='stretch')
        st.caption(f"{SCOPE} · bars show sellable windows. "
                   "Wrapping seasons appear as two bars.")

with tabs[1]:
    st.caption("Weeks with too few products, and categories that disappear.")
    b = breadth.copy()
    b["week"] = b["report_week"].map(week_label)
    st.dataframe(
        b[["week", "skus", "categories"]].rename(
            columns={"skus": "SKUs live", "categories": "Categories live"}),
        hide_index=True, width='stretch', height=300)
    gp = ae.gaps(spine, market, YEAR)
    if len(gp):
        summary = (gp.groupby("category")["report_week"]
                   .agg(weeks_absent="count").reset_index()
                   .sort_values("weeks_absent", ascending=False))
        st.caption(f"{market} · categories absent for part of the year")
        st.dataframe(summary, hide_index=True, width='stretch', height=240)

with tabs[2]:
    st.caption("What starts and stops, and when.")
    horizon = st.radio("Horizon", [4, 8, 12], horizontal=True, index=1,
                       format_func=lambda n: f"{n} weeks")
    end = week_dates[min(len(grid), week + horizon)][1]
    t = ae.transitions(spine, market=market, **flt)
    e_in = t[(t["first_day"] > w_start) & (t["first_day"] <= end)]
    e_out = t[(t["last_day"] >= w_start) & (t["last_day"] <= end)]
    c1, c2 = st.columns(2)
    c1.caption("Entering")
    c1.dataframe(e_in[["product", "category", "first_day"]], hide_index=True,
                 width='stretch')
    c2.caption("Exiting")
    c2.dataframe(e_out[["product", "category", "last_day"]], hide_index=True,
                 width='stretch')
    st.caption("First and last week per product")
    st.dataframe(t[["category", "product", "span_no", "first_day", "last_day"]],
                 hide_index=True, width='stretch', height=280)
    cont = ae.continuity(spine, market)
    if len(cont):
        piv = cont.pivot(index="category", columns="report_week", values="varieties")
        piv = piv.reindex(columns=range(1, len(grid) + 1)).fillna(0)
        h = go.Figure(go.Heatmap(z=piv.values, x=list(piv.columns), y=list(piv.index),
                                 colorscale=[[0, "#f1efe8"], [1, BLUE]],
                                 hovertemplate="%{y}<br>wk %{x} · %{z} varieties<extra></extra>",
                                 showscale=False))
        h.update_layout(height=max(300, 18 * len(piv)),
                        margin=dict(l=0, r=0, t=10, b=0),
                        xaxis_title="Reporting week")
        st.caption("Continuity · varieties live per category per week")
        st.plotly_chart(h, width='stretch')

with tabs[3]:
    st.caption("How much depends on one fruit.")
    mix = ae.category_mix(spine, market, **flt)
    if mix.empty:
        st.info("Nothing live in this scope.")
    else:
        totals = mix.groupby("category")["skus"].sum().sort_values(ascending=False)
        top5 = list(totals.head(5).index)
        m = go.Figure()
        palette = [ORANGE, BLUE, TEAL, YELLOW, PINK]
        for cat, col in zip(top5, palette):
            d = mix[mix["category"] == cat].set_index("report_week")["skus"]
            m.add_trace(go.Bar(x=d.index, y=d.values, name=cat, marker_color=col))
        other = (mix[~mix["category"].isin(top5)]
                 .groupby("report_week")["skus"].sum())
        if len(other):
            m.add_trace(go.Bar(x=other.index, y=other.values, name="Other",
                               marker_color=GREY))
        m.update_layout(barmode="stack", height=300,
                        margin=dict(l=0, r=0, t=10, b=0),
                        legend=dict(orientation="h", y=1.15, x=0),
                        xaxis_title="Reporting week")
        st.plotly_chart(m, width='stretch')

        c1, c2 = st.columns(2)
        depth = (spine[spine["market"] == market]
                 .groupby("category")["product"].nunique()
                 .sort_values(ascending=False).reset_index(name="varieties"))
        c1.caption("Varieties per category")
        c1.dataframe(depth, hide_index=True, width='stretch', height=260)

        t = ae.transitions(spine, market=market)
        t["weeks"] = (t["last_day"] - t["first_day"]).map(lambda x: x.days + 1) / 7
        length = t.groupby("product")["weeks"].sum().round(0)
        buckets = pd.cut(length, [0, 8, 16, 26, 53],
                         labels=["8 weeks or less", "9-16", "17-26", "27+"])
        dist = (buckets.value_counts().sort_index()
                .rename_axis("season length").reset_index(name="products"))
        c2.caption("Season length distribution")
        c2.dataframe(dist, hide_index=True, width='stretch', height=260)

with tabs[4]:
    st.caption("What each market is missing.")
    wide = (spine.groupby(["category", "product", "origin", "tier", "market"])
            .size().unstack("market").notna())
    for m in MARKETS:
        if m not in wide.columns:
            wide[m] = False
    wide = wide[MARKETS].reset_index()
    wide["markets"] = wide[MARKETS].sum(axis=1)
    wide = wide.sort_values(["markets", "category", "product"])
    carried = int(wide[market].sum())
    shown = wide.copy()
    for m in MARKETS:
        shown[m] = shown[m].map({True: "yes", False: "-"})
    st.dataframe(shown, hide_index=True, width='stretch', height=420)
    st.caption(
        f"{int((wide['markets'] < 4).sum())} products are not carried everywhere. "
        f"{market} carries {carried} of {len(wide)}."
    )

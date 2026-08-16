import streamlit as st, pandas as pd, numpy as np, altair as alt, os
import engine
import sharepoint_loader as sp

st.set_page_config(page_title="Inripe · Inventory Control", page_icon="📦", layout="wide")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("INRIPE_FILE", os.path.join(HERE, "INRIPE_Stock_Entry_v1.xlsx"))

NAVY="#1F3864"; ACC="#2E75B6"; INK="#26324A"; MUT="#7A879C"
st.markdown(f"""<style>
.block-container{{padding-top:1.6rem;padding-bottom:3rem;max-width:1500px}}
h1,h2,h3{{color:{INK};letter-spacing:-.01em}}
h1{{font-weight:600!important;font-size:1.9rem!important;margin-bottom:.1rem!important}}
h2{{font-weight:600!important;font-size:1.05rem!important;margin:1.6rem 0 .5rem!important;
   text-transform:uppercase;letter-spacing:.06em;color:{MUT}!important}}
h3{{font-weight:600!important;font-size:.95rem!important}}
div[data-testid="stMetric"]{{background:#FFFFFF;border:1px solid #E3E8F0;border-left:3px solid {ACC};
   border-radius:10px;padding:.75rem .95rem}}
div[data-testid="stMetricLabel"] p{{font-size:.72rem!important;color:{MUT}!important;
   text-transform:uppercase;letter-spacing:.05em;font-weight:600}}
div[data-testid="stMetricValue"]{{font-size:1.75rem!important;font-weight:600!important;color:{INK}}}
div[data-testid="stMetricDelta"]{{font-size:.75rem!important}}
button[data-baseweb="tab"]{{font-weight:600;font-size:.9rem;letter-spacing:.01em}}
div[data-baseweb="tab-highlight"]{{background:{ACC}!important}}
div[data-testid="stTabs"] div[data-baseweb="tab-list"]{{gap:.4rem;border-bottom:1px solid #E3E8F0}}
thead tr th{{background:#F4F7FB!important;color:{INK}!important;font-weight:600!important;
   text-transform:uppercase;font-size:.7rem!important;letter-spacing:.04em}}
div[data-testid="stDataFrame"]{{border:1px solid #E3E8F0;border-radius:10px}}
div[data-testid="stAlert"]{{border-radius:10px;border-left-width:4px}}
hr{{margin:1.6rem 0;border-color:#E3E8F0}}
.spark-lbl{{font-size:.7rem;color:{MUT};text-transform:uppercase;letter-spacing:.05em;font-weight:600}}
.spark-d{{float:right;font-weight:600;letter-spacing:0;text-transform:none}}
.hdr-sub{{color:{MUT};font-size:.82rem;margin:-.2rem 0 .9rem}}
.card{{background:#FFFFFF;border:1px solid #E3E8F0;border-radius:10px;padding:.7rem .9rem}}
</style>""", unsafe_allow_html=True)

@st.cache_data(ttl=300, show_spinner="Loading data…")
def get_local(path, _mtime):
    return engine.load(path)

@st.cache_data(ttl=300, show_spinner="Loading from SharePoint…")
def get_sharepoint(_bust):
    buf, meta = sp.fetch_workbook()
    return engine.load(buf) + (meta,)

SOURCE, SP_META, SP_ERROR = "local", None, None
if sp.is_configured():
    try:
        ship, moves, count, cfg, errs, SP_META = get_sharepoint(
            st.session_state.get("_refresh", 0))
        SOURCE = "sharepoint"
    except Exception as e:
        SP_ERROR = str(e)

if SOURCE == "local":
    if not os.path.exists(DATA):
        st.error(f"Entry file not found: {DATA}")
        if SP_ERROR: st.error(f"SharePoint also failed: {SP_ERROR}")
        st.stop()
    ship, moves, count, cfg, errs = get_local(DATA, os.path.getmtime(DATA))

# ---------- filters ----------
st.markdown("# Inripe · Inventory Control")
st.markdown('<div class="hdr-sub">Shipment, stock, courier and loss control across all markets</div>',
            unsafe_allow_html=True)
f1, f2, f3, f4 = st.columns([1.2, 1.2, 1.4, 2])
markets = ["All markets"] + (cfg["markets"] or sorted(ship["Market"].dropna().unique().tolist()))
mkt = f1.selectbox("Market", markets, label_visibility="collapsed")
shipments = ["All shipments"] + sorted(ship["Shipment ID"].dropna().unique().tolist())
shp = f2.selectbox("Shipment", shipments, label_visibility="collapsed")
as_of = pd.Timestamp(f3.date_input("As of", cfg["as_of"].date(), label_visibility="collapsed"))
with f4:
    if SOURCE == "sharepoint":
        when = pd.to_datetime(SP_META["modified"]).tz_convert(None)
        who = SP_META.get("modified_by") or "unknown"
        st.caption(f"SharePoint · edited {when:%d %b %Y · %H:%M} by {who}")
    else:
        st.caption(f"Local file · {pd.Timestamp.fromtimestamp(os.path.getmtime(DATA)):%d %b %Y · %H:%M}")
    if st.button("Refresh", width="content"):
        st.cache_data.clear()
        st.session_state["_refresh"] = st.session_state.get("_refresh", 0) + 1
        st.rerun()
if SP_ERROR:
    st.warning(f"SharePoint unavailable, showing the file in the repo instead. {SP_ERROR}")
elif SOURCE == "local" and not sp.is_configured():
    st.caption(f"SharePoint not configured yet — missing {', '.join(sp.missing_keys())}")

sf = ship.copy(); mf = moves.copy()
if mkt != "All markets":
    sf = sf[sf["Market"] == mkt]; mf = mf[mf["Market"] == mkt]
if shp != "All shipments":
    sf = sf[sf["Shipment ID"] == shp]; mf = mf[mf["Shipment"] == shp]
mf = mf[mf["Date"] <= as_of]
cf = count[count["Shipment"].isin(sf["Shipment ID"])] if len(sf) else count.iloc[0:0]

stock = engine.stock_by_item(sf, mf, as_of)
clear = engine.clearance_by_shipment(sf, mf, as_of, cfg)
cour  = engine.courier_positions(sf, mf, as_of, cfg)
var   = engine.variance(stock, cf)

# ---------- exceptions ----------
def build_exceptions():
    rows = []
    a = lambda w,c,d,p: rows.append({"What":w,"Count":int(c),"Where":d,"Priority":p})
    held = cour[cour["Flag"]=="Holding too long"] if len(cour) else cour
    a("Courier holding beyond limit", len(held),
      ", ".join(f"{r.Courier} · {r.Shipment} · {int(r.DaysSince)}d" for r in held.itertuples()), "High")
    od = clear[clear["Overdue"]]
    a("Shipment overdue to clear", len(od),
      ", ".join(f"{r.Shipment} · {int(r.Outstanding)} boxes" for r in od.itertuples()), "High")
    vv = var[var["VarPct"].abs() > cfg["var_tol"]] if len(var) else var
    a("Physical count variance", len(vv),
      ", ".join(f"{r.Shipment} · {r.Item} · {int(r.Var):+d}" for r in vv.itertuples()), "Med")
    neg = stock[stock["Store"] < 0]
    a("Negative stock", len(neg), ", ".join(f"{r.Shipment} · {r.Item}" for r in neg.itertuples()), "High")
    qa = stock[stock["QA"].round(6) != 0]
    a("Stock balance error", len(qa), ", ".join(f"{r.Shipment} · {r.Item}" for r in qa.itertuples()), "High")
    sd = stock[stock["ShipDiff"].round(6) != 0]
    a("Shipment quantity unexplained", len(sd),
      ", ".join(f"{r.Shipment} · {r.Item} · {int(r.ShipDiff):+d}" for r in sd.itertuples()), "High")
    ov = cour[cour["Flag"]=="Over-delivered"] if len(cour) else cour
    a("Courier over-delivered", len(ov), ", ".join(f"{r.Courier} · {r.Shipment}" for r in ov.itertuples()), "High")
    oc = cour[cour["Flag"]=="Order count error"] if len(cour) else cour
    a("Order counts do not add up", len(oc), ", ".join(f"{r.Courier} · {r.Shipment}" for r in oc.itertuples()), "Med")
    rq = (mf.loc[mf.Movement=="Returned","Qty"].sum()
          - mf.loc[mf.Movement=="Return to Saleable","Qty"].sum()
          - mf.loc[mf.Movement=="Return to Scrap","Qty"].sum())
    a("Returns not split to item", 1 if abs(rq) > 0.001 else 0, f"{rq:+.0f} boxes unaccounted" if rq else "", "Med")
    a("Rows with entry errors", len(errs), f"{len(errs)} rows across the logs", "High")
    return pd.DataFrame(rows)

exc = build_exceptions()
open_exc = exc[exc["Count"] > 0]

# ---------- history for sparklines ----------
def history(days=30):
    end = as_of; start = end - pd.Timedelta(days=days-1)
    idx = pd.date_range(start, end, freq="D")
    out = pd.DataFrame(index=idx)
    q = lambda mt: mf[mf.Movement==mt].groupby("Date")["Qty"].sum().reindex(idx, fill_value=0)
    rec, scr, tos, adj, tc = q("Received"), q("Scrap"), q("Return to Saleable"), q("Count Adjustment"), q("To Courier")
    out["Available"] = (rec - scr + tos + adj - tc).cumsum()
    out["Delivered"] = q("Delivered")
    cum_loss = (scr + q("Customs / Loss") + q("Return to Scrap")).cumsum()
    cum_rec = rec.cumsum()
    out["LossPct"] = np.where(cum_rec > 0, cum_loss/cum_rec*100, np.nan)
    out["Held"] = (tc - q("Delivered") - q("Returned")).cumsum()
    return out.reset_index(names="Date")

hist = history()

def spark(df, col, color, pct=False):
    d = df.dropna(subset=[col])
    if d.empty or d[col].nunique() <= 1:
        return alt.Chart(pd.DataFrame({"x":[0],"y":[0]})).mark_point(opacity=0).encode(x="x",y="y").properties(height=46)
    return (alt.Chart(d).mark_line(color=color, strokeWidth=2, interpolate="monotone")
            .encode(x=alt.X("Date:T", axis=None),
                    y=alt.Y(f"{col}:Q", axis=None, scale=alt.Scale(zero=False)),
                    tooltip=[alt.Tooltip("Date:T", format="%d %b"),
                             alt.Tooltip(f"{col}:Q", format=".1f" if pct else ".0f")])
            .properties(height=44).configure_view(strokeWidth=0))

def delta(df, col, unit=""):
    d = df.dropna(subset=[col])
    if len(d) < 8: return None
    now, prev = d[col].iloc[-1], d[col].iloc[-8]
    if prev == 0: return None
    return f"{(now-prev)/abs(prev)*100:+.0f}%" if not unit else f"{now-prev:+.1f}{unit}"

held_total = cour["Held"].sum() if len(cour) else 0
oldest = int(stock.loc[stock["Store"] > 0, "AgeDays"].max()) if (stock["Store"] > 0).any() else 0


RAMP_BLUE = ["#F2F7FD","#E6F1FB","#CFE4F8","#B5D4F4","#96BEEC","#6FA3E2"]
RAMP_HEAT = ["#EAF3DE","#F7F0C8","#FAEEDA","#FAC775","#F0997B","#F09595"]
RAMP_RED  = ["#FCEBEB","#F9DADA","#F7C1C1","#F4AEAE","#F09595","#E88080"]

def _shade(v, lo, hi, ramp):
    if pd.isna(v) or hi <= lo: return ""
    i = int(round((float(v)-lo)/(hi-lo)*(len(ramp)-1)))
    return f"background-color: {ramp[max(0,min(i,len(ramp)-1))]}"

def heat_cols(df, cols, ramp):
    """Colour specific numeric columns, no matplotlib."""
    out = pd.DataFrame("", index=df.index, columns=df.columns)
    for c in cols:
        v = pd.to_numeric(df[c], errors="coerce")
        lo, hi = v.min(), v.max()
        out[c] = [_shade(x, lo, hi, ramp) for x in v]
    return out

def heat_all(df, ramp):
    """Colour the whole frame on one shared scale."""
    v = df.apply(pd.to_numeric, errors="coerce")
    lo, hi = np.nanmin(v.values), np.nanmax(v.values)
    return pd.DataFrame([[_shade(x, lo, hi, ramp) for x in row] for row in v.values],
                        index=df.index, columns=df.columns)

EMPTY = len(sf) == 0
T1, T2, T3, T4, T5 = st.tabs(["Overview", "Stock", "Shipments", "Couriers", "Losses & check"])
if EMPTY:
    for T in (T1, T2, T3, T4, T5):
        with T:
            st.info("No shipments match this filter. Choose another market or shipment.")
    st.stop()

# ============================== TAB 1 · OVERVIEW ==============================
with T1:
    if len(open_exc):
        top = open_exc.iloc[0]
        st.error(f"**{int(open_exc['Count'].sum())} exceptions** — {top['What']}: {top['Where']}")
    else:
        st.success("All controls pass")

    k = st.columns(6)
    k[0].metric("Available to sell", f"{stock['Store'].sum():,.0f}")
    k[1].metric("With couriers", f"{held_total:,.0f}")
    k[2].metric("Open shipments", int((clear['Cleared']=='No').sum()))
    k[3].metric("Oldest stock (days)", oldest)
    k[4].metric("Orders outstanding", f"{clear['OrdersOutstanding'].sum():,.0f}")
    k[5].metric("Exceptions", int(open_exc["Count"].sum()))

    st.caption("30-day trend")
    s = st.columns(4)
    for col, (label, field, colour, unit, pct) in zip(s, [
        ("Available", "Available", "#378ADD", "", False),
        ("Delivered per day", "Delivered", "#1D9E75", "", False),
        ("Loss % of received", "LossPct", "#E24B4A", "pp", True),
        ("Boxes with couriers", "Held", "#EF9F27", "", False)]):
        with col:
            d = delta(hist, field, unit)
            dc = "#1D9E75" if (d and d.startswith("+") and field in ("Available","Delivered")) else \
                 ("#C0392B" if (d and d.startswith("+") and field in ("LossPct","Held")) else MUT)
            st.markdown(f"<div class='spark-lbl'>{label}"
                        f"<span class='spark-d' style='color:{dc}'>{d or ''}</span></div>",
                        unsafe_allow_html=True)
            st.altair_chart(spark(hist, field, colour, pct), use_container_width=True)

    st.subheader("Available to sell")
    if len(stock):
        piv = (stock.pivot_table(index="Item", columns="Market", values="Store",
                                 aggfunc="sum", fill_value=0))
        piv["Total"] = piv.sum(axis=1)
        piv.loc["Total"] = piv.sum()
        body = piv.iloc[:-1, :-1]
        sty = pd.DataFrame("", index=piv.index, columns=piv.columns)
        sty.loc[body.index, body.columns] = heat_all(body, RAMP_BLUE).values
        st.dataframe(piv.style.format("{:,.0f}").apply(lambda _: sty, axis=None),
                     use_container_width=True)
    else:
        st.info("No stock in the current filter.")

    st.subheader("Top actions")
    if len(open_exc):
        for r in open_exc.head(3).itertuples():
            st.markdown(f"**{r.What}** ({r.Count}) — {r.Where}")
    else:
        st.write("Nothing needs action.")

# ============================== TAB 2 · STOCK ==============================
with T2:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Store stock", f"{stock['Store'].sum():,.0f}")
    c2.metric("With couriers", f"{held_total:,.0f}")
    c3.metric("Total owned", f"{stock['Store'].sum()+held_total:,.0f}")
    c4.metric("Oldest (days)", oldest)

    st.subheader("Stock aging")
    ag = stock[stock["Store"] > 0][["Item","Market","Shipment","Arrival Date","AgeDays","Store"]]
    ag = ag.sort_values("AgeDays", ascending=False).rename(
        columns={"AgeDays":"Days","Store":"Qty","Arrival Date":"Arrival"})
    if len(ag):
        ag["Arrival"] = ag["Arrival"].dt.strftime("%d %b")
        st.dataframe(ag.style.format({"Qty":"{:,.0f}"})
                     .apply(lambda d: heat_cols(d, ["Days"], RAMP_HEAT), axis=None),
                     use_container_width=True, hide_index=True)
        st.altair_chart(
            alt.Chart(ag).mark_bar().encode(
                x=alt.X("Qty:Q", title="Boxes"),
                y=alt.Y("Item:N", title=None, sort="-x"),
                color=alt.Color("Days:Q", scale=alt.Scale(scheme="yelloworangered"), title="Days"),
                tooltip=["Item","Market","Shipment","Days","Qty"]
            ).properties(height=max(130, 36*ag["Item"].nunique())).configure_view(strokeWidth=0)
              .configure_axis(grid=True, gridColor="#EDF1F7", domainColor="#DDE3EC",
                              labelColor="#7A879C", titleColor="#7A879C", labelFontSize=11),
            use_container_width=True)

    st.subheader("Movements on the selected day")
    day = mf[mf["Date"] == as_of]
    mv = (day.groupby("Movement")["Qty"].sum()
          .reindex(engine.MV).fillna(0).reset_index())
    mv = mv[mv["Qty"] != 0]
    if len(mv):
        st.dataframe(mv.style.format({"Qty":"{:,.0f}"}), use_container_width=True, hide_index=True)
    else:
        st.caption("No movements on this date.")

# ============================== TAB 3 · SHIPMENTS ==============================
with T3:
    st.subheader("Shipment status")
    disp = clear.copy()
    disp["Arrival"] = disp["Arrival"].dt.strftime("%d %b")
    disp["Status"] = np.where(disp["Overdue"], "Overdue",
                       np.where(disp["Cleared"]=="Yes", "Cleared", "Open"))
    cols = ["Shipment","Market","Arrival","Received","Scrap","Delivered","Returned",
            "Outstanding","DaysOpen","Span","Status","OrdersAssigned","OrdersHanded",
            "OrdersOutstanding","OrdersVsAssigned"]
    st.dataframe(disp[cols].style.format(
        {c:"{:,.0f}" for c in ["Received","Scrap","Delivered","Returned","Outstanding",
                               "DaysOpen","Span","OrdersAssigned","OrdersHanded",
                               "OrdersOutstanding","OrdersVsAssigned"]}, na_rep="—"),
        use_container_width=True, hide_index=True)

    st.subheader("Clearance curve")
    st.caption(f"Cumulative % of received delivered, by day since arrival. Target {cfg['clear_target']:.0f} days.")
    dl = mf[mf["Movement"]=="Delivered"].copy()
    if len(dl):
        arr = clear.set_index("Shipment")["Arrival"]
        base = clear.set_index("Shipment")["Received"]
        dl["Day"] = (dl["Date"] - dl["Shipment"].map(arr)).dt.days
        cur = dl.groupby(["Shipment","Day"])["Qty"].sum().reset_index()
        cur["Cum"] = cur.groupby("Shipment")["Qty"].cumsum()
        cur["Pct"] = cur["Cum"] / cur["Shipment"].map(base) * 100
        st.altair_chart(
            alt.Chart(cur).mark_line(point=True).encode(
                x=alt.X("Day:Q", title="Days since arrival"),
                y=alt.Y("Pct:Q", title="% delivered", scale=alt.Scale(domain=[0,100])),
                color=alt.Color("Shipment:N", title=None),
                tooltip=["Shipment","Day",alt.Tooltip("Pct:Q",format=".1f")]
            ).properties(height=300).configure_view(strokeWidth=0)
              .configure_axis(grid=True, gridColor="#EDF1F7", domainColor="#DDE3EC",
                              labelColor="#7A879C", titleColor="#7A879C", labelFontSize=11),
            use_container_width=True)
    else:
        st.info("No deliveries recorded yet.")

    st.subheader("Item breakdown")
    pick = None
    if len(clear):
        pick = st.selectbox("Shipment", clear["Shipment"].tolist(), label_visibility="collapsed")
    if pick:
        b = stock[stock["Shipment"]==pick][
            ["Item","Source","Shipped Qty","Customs","Received","Scrap",
             "ToSaleable","ToCourier","Store","AgeDays"]]
        b = b.rename(columns={"Shipped Qty":"Shipped","ToSaleable":"Back to stock",
                              "ToCourier":"To courier","Store":"In store","AgeDays":"Days"})
        st.dataframe(b.style.format({c:"{:,.0f}" for c in b.columns if c not in ("Item","Source")}),
                     use_container_width=True, hide_index=True)

# ============================== TAB 4 · COURIERS ==============================
with T4:
    if not len(cour):
        st.info("No courier activity in the current filter.")
    else:
        sc = cour.groupby(["Courier","Market"]).agg(
            OrdersHanded=("OrdersHanded","sum"), OrdersDelivered=("OrdersDelivered","sum"),
            OrdersReturned=("OrdersReturned","sum"), OrdersOutstanding=("OrdersOutstanding","sum"),
            QtyOut=("ToCourier","sum"), QtyHeld=("Held","sum"),
            MaxDays=("DaysSince","max")).reset_index()
        sc["Return %"] = np.where(sc["OrdersHanded"]>0,
                                  sc["OrdersReturned"]/sc["OrdersHanded"]*100, 0)
        sc["Flag"] = np.where(sc["QtyHeld"]<0, "Over-delivered",
                      np.where((sc["QtyHeld"]>0)&(sc["MaxDays"]>cfg["courier_limit"]),
                               "Holding too long", "OK"))
        k = st.columns(4)
        k[0].metric("Orders handed", f"{sc['OrdersHanded'].sum():,.0f}")
        k[1].metric("Orders outstanding", f"{sc['OrdersOutstanding'].sum():,.0f}")
        k[2].metric("Boxes held", f"{sc['QtyHeld'].sum():,.0f}")
        k[3].metric("Return rate", f"{sc['OrdersReturned'].sum()/max(sc['OrdersHanded'].sum(),1)*100:.1f}%")

        st.subheader("Scorecard")
        st.dataframe(sc.style.format({
            "OrdersHanded":"{:,.0f}","OrdersDelivered":"{:,.0f}","OrdersReturned":"{:,.0f}",
            "OrdersOutstanding":"{:,.0f}","QtyOut":"{:,.0f}","QtyHeld":"{:,.0f}",
            "MaxDays":"{:,.0f}","Return %":"{:.1f}%"}, na_rep="—")
            .apply(lambda d: heat_cols(d, ["Return %"], RAMP_RED), axis=None),
            use_container_width=True, hide_index=True)

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Boxes held now")
            st.altair_chart(
                alt.Chart(sc).mark_bar().encode(
                    x=alt.X("QtyHeld:Q", title="Boxes"),
                    y=alt.Y("Courier:N", title=None, sort="-x"),
                    color=alt.condition(alt.datum.MaxDays > cfg["courier_limit"],
                                        alt.value("#E24B4A"), alt.value("#85B7EB")),
                    tooltip=["Courier","QtyHeld","MaxDays"]
                ).properties(height=max(130, 42*len(sc))).configure_view(strokeWidth=0)
                  .configure_axis(grid=True, gridColor="#EDF1F7", domainColor="#DDE3EC",
                                  labelColor="#7A879C", titleColor="#7A879C", labelFontSize=11),
                use_container_width=True)
        with c2:
            st.subheader("Open positions")
            op = cour[cour["Held"] != 0][
                ["Courier","Shipment","Market","ToCourier","Delivered","Returned","Held","DaysSince"]]
            if len(op):
                st.dataframe(op.style.format({c:"{:,.0f}" for c in
                    ["ToCourier","Delivered","Returned","Held","DaysSince"]}, na_rep="—"),
                    use_container_width=True, hide_index=True)
            else:
                st.caption("Every courier is clear.")

# ============================== TAB 5 · LOSSES & CHECK ==============================
with T5:
    rec = stock["Received"].sum()
    customs = stock["Customs"].sum(); scrap = stock["Scrap"].sum()
    rscrap = stock["ReturnScrap"].sum(); total_loss = customs + scrap + rscrap
    loss_pct = total_loss/rec*100 if rec else 0
    k = st.columns(4)
    k[0].metric("Customs / transit", f"{customs:,.0f}")
    k[1].metric("QC scrap", f"{scrap:,.0f}")
    k[2].metric("Return scrap", f"{rscrap:,.0f}")
    k[3].metric("Total loss", f"{total_loss:,.0f}",
                f"{loss_pct-cfg['loss_target']*100:+.1f}pp vs target", delta_color="inverse")

    st.subheader("Loss % of received")
    h = hist.dropna(subset=["LossPct"])
    if len(h):
        line = alt.Chart(h).mark_line(color="#E24B4A", strokeWidth=2).encode(
            x=alt.X("Date:T", title=None), y=alt.Y("LossPct:Q", title="% of received"),
            tooltip=[alt.Tooltip("Date:T",format="%d %b"), alt.Tooltip("LossPct:Q",format=".2f")])
        tgt = alt.Chart(pd.DataFrame({"y":[cfg["loss_target"]*100]})).mark_rule(
            color="#888", strokeDash=[5,4]).encode(y="y:Q")
        st.altair_chart((line+tgt).properties(height=250).configure_view(strokeWidth=0)
              .configure_axis(grid=True, gridColor="#EDF1F7", domainColor="#DDE3EC",
                              labelColor="#7A879C", titleColor="#7A879C", labelFontSize=11),
            use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Scrap by reason")
        sr = mf[mf["Movement"].isin(["Scrap","Return to Scrap"])].groupby("Reason")["Qty"].sum().reset_index()
        if len(sr):
            st.altair_chart(alt.Chart(sr).mark_bar(color="#EF9F27").encode(
                x=alt.X("Qty:Q", title="Boxes"), y=alt.Y("Reason:N", title=None, sort="-x"),
                tooltip=["Reason","Qty"]).properties(height=max(130,36*len(sr)))
                  .configure_view(strokeWidth=0)
                  .configure_axis(grid=True, gridColor="#EDF1F7", domainColor="#DDE3EC",
                                  labelColor="#7A879C", titleColor="#7A879C", labelFontSize=11),
                use_container_width=True)
        else:
            st.caption("No scrap recorded.")
    with c2:
        st.subheader("Returns by reason")
        rr = mf[mf["Movement"]=="Returned"].groupby("Reason")["Qty"].sum().reset_index()
        if len(rr):
            st.altair_chart(alt.Chart(rr).mark_bar(color="#D4537E").encode(
                x=alt.X("Qty:Q", title="Boxes"), y=alt.Y("Reason:N", title=None, sort="-x"),
                tooltip=["Reason","Qty"]).properties(height=max(130,36*len(rr)))
                  .configure_view(strokeWidth=0)
                  .configure_axis(grid=True, gridColor="#EDF1F7", domainColor="#DDE3EC",
                                  labelColor="#7A879C", titleColor="#7A879C", labelFontSize=11),
                use_container_width=True)
        else:
            st.caption("No returns recorded.")

    st.subheader("Loss by item")
    li = stock.groupby("Item").agg(Received=("Received","sum"), Customs=("Customs","sum"),
                                   Scrap=("Scrap","sum"), ReturnScrap=("ReturnScrap","sum")).reset_index()
    li["Total loss"] = li["Customs"]+li["Scrap"]+li["ReturnScrap"]
    li["Loss %"] = np.where(li["Received"]>0, li["Total loss"]/li["Received"]*100, 0)
    st.dataframe(li.style.format({c:"{:,.0f}" for c in
        ["Received","Customs","Scrap","ReturnScrap","Total loss"]} | {"Loss %":"{:.1f}%"})
        .apply(lambda d: heat_cols(d, ["Loss %"], RAMP_RED), axis=None),
        use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Reconciliation")
    checks = [
        ("Shipment", abs(stock["ShipDiff"]).sum() == 0, "shipped = customs + received"),
        ("Stock", abs(stock["QA"]).sum() < 1e-6, "received − scrap + returns − to courier = store"),
        ("Courier", (cour["Held"] >= 0).all() if len(cour) else True, "out = delivered + returned + held"),
        ("Returns", abs(mf.loc[mf.Movement=="Returned","Qty"].sum()
                        - mf.loc[mf.Movement=="Return to Saleable","Qty"].sum()
                        - mf.loc[mf.Movement=="Return to Scrap","Qty"].sum()) < 1e-6,
         "returned = back to stock + scrapped"),
    ]
    cc = st.columns(4)
    for col,(name, ok, note) in zip(cc, checks):
        bg, fg, mark = ("#EAF6EE","#1D6F45","Balanced") if ok else ("#FDECEC","#B3261E","Off")
        col.markdown(
            f"<div style='background:{bg};border-radius:10px;padding:.7rem .85rem'>"
            f"<div style='font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;"
            f"font-weight:600;color:{fg};opacity:.8'>{name}</div>"
            f"<div style='font-size:1.05rem;font-weight:600;color:{fg}'>{mark}</div>"
            f"<div style='font-size:.68rem;color:{fg};opacity:.75;margin-top:.15rem'>{note}</div></div>",
            unsafe_allow_html=True)

    st.subheader("Exceptions")
    show = exc.copy(); show["Status"] = np.where(show["Count"]>0, show["Priority"], "clear")
    st.dataframe(show[["What","Count","Where","Status"]], use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Count variance")
        if len(var):
            v = var[["Date","Shipment","Item","System","Physical","Var"]].copy()
            v["Date"] = v["Date"].dt.strftime("%d %b")
            st.dataframe(v.style.format({c:"{:,.0f}" for c in ["System","Physical","Var"]}),
                         use_container_width=True, hide_index=True)
            st.caption("To correct a variance, post a Count Adjustment row in MOVES with a reason.")
        else:
            st.caption("No counts recorded.")
    with c2:
        st.subheader("Data entry errors")
        if len(errs):
            st.error(f"{len(errs)} rows need fixing before this data can be trusted.")
            st.dataframe(errs, use_container_width=True, hide_index=True)
        else:
            st.success("0 rows flagged across SHIPMENTS, MOVES and COUNT.")

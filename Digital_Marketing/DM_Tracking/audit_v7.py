"""
v7 LOGIC AUDIT

Not a smoke test. Recomputes every figure independently from the sheet and
checks that the same metric agrees wherever it appears, that every accounting
identity holds, and that the edge cases behave.
"""
import sys
import numpy as np
import pandas as pd
import dm_engine as E

# Source the workbook the same way the dashboard does: SharePoint when
# configured, a local copy otherwise. Auditing a stale local file would prove
# nothing about what the dashboard is actually showing.
def _source():
    import io
    from pathlib import Path
    try:
        import sharepoint_loader as SP
        if SP.is_configured():
            buf, meta = SP.fetch_workbook()
            print(f"Source: SharePoint · {meta['name']} · edited {meta.get('modified')}")
            return io.BytesIO(buf.getvalue())
    except Exception as ex:
        print(f"SharePoint unavailable ({ex}); falling back to a local file.")
    for p in ("DM_Planing_Tracking_2026_25JUL26_V1_21.xlsx",
              "Digital_Marketing/DM_Tracking/DM_Planing_Tracking_2026_25JUL26_V1_21.xlsx"):
        if Path(p).exists():
            print(f"Source: local file · {p}")
            return p
    raise FileNotFoundError(
        "No workbook available. Configure SharePoint (.streamlit/secrets.toml) "
        "or place the .xlsx beside this script.")


_SRC = _source()


def PATH_():
    """Fresh handle each read - a BytesIO is consumed once."""
    import io
    if isinstance(_SRC, str):
        return _SRC
    _SRC.seek(0)
    return io.BytesIO(_SRC.getvalue())


PATH = PATH_()
M, Y = 7, 2026   # overridden below to the latest month present
fails, warns = [], []


def ck(name, got, want, tol=0.5):
    ok = (got is None and want is None) or (
        got is not None and want is not None and abs(got - want) <= tol)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {got} vs {want}")
    if not ok:
        fails.append(name)
    return ok


def ck_true(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        fails.append(name)
    return cond


def warn(name, cond, detail=""):
    if not cond:
        print(f"  [WARN] {name} {detail}")
        warns.append(name)
    else:
        print(f"  [PASS] {name} {detail}")


# ── independent recompute, no engine ─────────────────────────────────
raw = pd.read_excel(PATH_(), sheet_name="T2. Actuals", skiprows=1)
raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")
raw["Value"] = pd.to_numeric(raw["Value"], errors="coerce")
raw = raw.dropna(subset=["Date", "Value"])
J = raw[(raw.Date.dt.month == M) & (raw.Date.dt.year == Y)]

tg = pd.read_excel(PATH_(), sheet_name="T3. Targets", skiprows=1)
tg["Month"] = pd.to_datetime(tg["Month"], errors="coerce")
tg["Target Value"] = pd.to_numeric(tg["Target Value"], errors="coerce")
tg = tg.dropna(subset=["Month", "Target Value"])
TJ = tg[(tg.Month.dt.month == M) & (tg.Month.dt.year == Y)]

if J.empty:
    _last = raw.Date.max()
    M, Y = int(_last.month), int(_last.year)
    J = raw[(raw.Date.dt.month == M) & (raw.Date.dt.year == Y)]
    TJ = tg[(tg.Month.dt.month == M) & (tg.Month.dt.year == Y)]
    print(f"No data for the default month; auditing {M}/{Y} instead.")

import calendar as _cal
DAYS = J.Date.dt.date.nunique()
DIM = _cal.monthrange(Y, M)[1]

t2, t3 = E.load_data(PATH_())
cov = E.build_coverage(t2, M, Y)
snap = E.build_snapshot(t2, t3, "All", M, Y)
GAP = E.gap_contribution(t2, t3, M, Y, cov)

print("\n=== 1. CHANNEL ROLL-UP ===")
i_api = J[(J.Platform == "API") & (J.Metric == "Total Orders")].Value.sum()
i_meta = J[(J.Platform.isin(["Meta API", "Meta Ecom"])) & (J.Metric == "Orders")].Value.sum()
ck("API orders", E._chan_orders(t2, None, "API", M, Y), i_api)
ck("Meta orders (consolidated)", E._chan_orders(t2, None, "Meta", M, Y), i_meta)
ck("API + Meta = all orders", i_api + i_meta,
   J[J.Metric.isin(["Total Orders", "Orders"])].Value.sum())

cs = E.channel_summary(t2, t3, "All", M, Y, cov, split_meta=False)
ck("channel summary API", float(cs[cs.Channel == "API"]["Orders"].iloc[0]), i_api)
ck("channel summary Meta", float(cs[cs.Channel == "Meta"]["Orders"].iloc[0]), i_meta)
ck_true("channel shares sum to 100%",
        abs(sum(float(s.rstrip('%')) for s in cs["Share of orders"]) - 100) <= 1)

css = E.channel_summary(t2, t3, "All", M, Y, cov, split_meta=True)
ck("split Meta sums to consolidated",
   float(css[css.Channel.isin(["Meta API", "Meta Ecom"])]["Orders"].sum()), i_meta)

print("\n=== 2. GAP ATTRIBUTION ===")
for _, g in GAP.iterrows():
    m, ch = g["Market"], g["Channel"]
    ia = (J[(J.Market == m) & (J.Platform.isin(E.CHANNEL_GROUPS[ch]))
            & (J.Metric.isin(["Total Orders", "Orders"]))].Value.sum())
    ip = TJ[(TJ.Market == m) & (TJ.Platform == ch)
            & (TJ.Metric == "Target Orders")]["Target Value"].sum()
    ipaced = ip * DAYS / DIM
    ck(f"{m} {ch} actual", float(g["Actual"]), ia)
    ck(f"{m} {ch} paced", float(g["Paced plan"]), ipaced, 1.0)
    ck(f"{m} {ch} gap", float(g["Gap (orders)"]), round(ipaced - ia), 1.0)

behind = GAP[GAP["Share of shortfall"] > 0]
ck_true("group shares sum to 100%",
        abs(behind["Share of shortfall"].sum() - 100) < 0.5,
        f"= {behind['Share of shortfall'].sum():.1f}%")
ck_true("cells ahead of pace get no share",
        (GAP[GAP["Gap (orders)"] < 0]["Share of shortfall"] == 0).all())

print("\n=== 3. CROSS-SECTION CONSISTENCY ===")
# the same metric must agree in Part A KPI, Demand tab and channel summary
kpi_orders = snap.line("orders").actual
demand_orders = E.total_orders(t2, month=M, year=Y)
chan_orders = float(cs["Orders"].sum())
gap_actual = float(GAP["Actual"].sum())
mcb = E.market_channel_breakdown(t2, t3, M, Y, cov)
mcb_total = float(mcb[mcb.Channel == "Total"]["Orders"].sum())
ck("KPI = demand tab", kpi_orders, demand_orders)
ck("KPI = channel summary", kpi_orders, chan_orders)
ck("KPI = gap table", kpi_orders, gap_actual)
ck("KPI = market x channel totals", kpi_orders, mcb_total)

fin = E.financial_summary(t2, t3, "All", M, Y, cov)
fin_rev = fin[fin.Metric == "Revenue"]["Actual MTD"].iloc[0]
ck_true("financial revenue matches KPI",
        fin_rev == E.fmt(snap.line("revenue").actual, "AED "),
        f"{fin_rev} vs {E.fmt(snap.line('revenue').actual, 'AED ')}")

print("\n=== 4. CHANNEL DETAIL vs SUMMARY ===")
for ch in E.CHANNEL_ORDER:
    det = E.channel_detail(t2, t3, ch, "All", M, Y, cov)
    d_ord = det[det.Metric == "Orders"]["Actual MTD"].iloc[0]
    s_ord = E.fmt(float(cs[cs.Channel == ch]["Orders"].iloc[0]))
    ck_true(f"{ch} detail = summary", d_ord == s_ord, f"{d_ord} vs {s_ord}")

print("\n=== 5. POLARITY ===")
for key, want_dir in [("orders", "up"), ("units", "up"), ("revenue", "up"),
                      ("spend", "neutral"), ("roas", "up"), ("cac", "down"),
                      ("burn", "neutral")]:
    ln = snap.line(key)
    ck_true(f"{key} direction is {want_dir}", ln is not None and ln.direction == want_dir,
            f"got {ln.direction if ln else 'MISSING'}")
ck_true("basket size removed", snap.line("basket") is None)
for rr in (80, 105, 160):
    v = E.rag(rr, 100, "neutral")
    ck_true(f"spend {rr}% carries no verdict", not v.scored and v.color == E.GREY, v.label)
ck_true("CAC over plan is not green", E.rag(140, 100, "down").color == E.RED)
ck_true("orders over plan is green", E.rag(140, 100, "up").color == E.GREEN)

print("\n=== 6. PLAUSIBILITY GUARD ===")
for act, ratio, key, should_block in [
        (0, 0, "cac", True), (1e11, 2.37e9, "orders", True),
        (5.97e7, 4.8e9, "cr_api", True), (16.9, 119, "roas", False),
        (2918, 69, "orders", False), (18.7, 117, "cac", False)]:
    ok, why = E.plausible(act, ratio, key)
    ck_true(f"{key} act={act:g} ratio={ratio:g} -> {'BLOCK' if should_block else 'ALLOW'}",
            (not ok) == should_block, why)

print("\n=== 7. PACED PLAN DEFINITION ===")
for key in ("orders", "units", "revenue", "spend"):
    ln = snap.line(key)
    if ln and ln.plan:
        ck(f"{key} paced = plan x {DAYS}/{DIM}", ln.paced, ln.plan * DAYS / DIM, 1.0)
for key in ("roas", "cac", "cr_api", "burn"):
    ln = snap.line(key)
    ck_true(f"{key} has no paced value (ratio)", ln is None or ln.paced is None)

print("\n=== 8. EOM RUN RATE ===")
for key in ("orders", "units", "revenue", "spend"):
    ln = snap.line(key)
    if ln and ln.actual:
        ck(f"{key} EOM = actual / {DAYS} x {DIM}", ln.eom, ln.actual / DAYS * DIM, 1.0)

print("\n=== 9. EVERY MARKET / MONTH BUILDS ===")
for mk in ["All"] + sorted(t2.Market.unique()):
    try:
        s = E.build_snapshot(t2, t3, mk, M, Y)
        c = E.build_commentary(s)
        g = E.gap_contribution(t2, t3, M, Y, s.coverage)
        gm = g if mk == "All" else g[g.Market == mk]
        b = gm[gm["Gap (orders)"] > 0]
        tot = b["Gap (orders)"].sum()
        share = [x / tot * 100 for x in b["Gap (orders)"]] if tot > 0 else []
        ck_true(f"{mk}: builds, {len(s.lines)} lines, scoped share sums 100%",
                not share or abs(sum(share) - 100) < 0.5)
    except Exception as e:
        ck_true(f"{mk} builds", False, f"{type(e).__name__}: {e}")

for yy, mm in sorted({(int(y), int(m)) for y, m in zip(t2.Year, t2.Month)}):
    try:
        E.build_snapshot(t2, t3, "All", mm, yy)
        E.gap_contribution(t2, t3, mm, yy, E.build_coverage(t2, mm, yy))
        print(f"  [PASS] month {mm}/{yy} builds")
    except Exception as e:
        ck_true(f"month {mm}/{yy}", False, str(e))

print("\n=== 10. NULL / EMPTY HANDLING ===")
ck_true("None formats n/a", E.fmt(None) == "n/a")
ck_true("zero formats 0", E.fmt(0) == "0")
ck_true("None never scored", not E.rag(None, 100, "up").scored)
ck_true("no basis never scored", not E.rag(50, None, "up").scored)
ck_true("2918 and 3345 render differently", E.fmt(2918) != E.fmt(3345))
empty = E.gap_contribution(t2, t3, 1, 2020, E.build_coverage(t2, 1, 2020))
ck_true("gap table on empty month returns empty frame", empty.empty)

print("\n=== 11. COVERAGE ===")
for m in sorted(cov.per_market):
    ent, act = cov.per_market[m]
    ind = J[J.Market == m].Date.dt.date.nunique()
    ck(f"{m} days reported", ent, ind)
    ck_true(f"{m} active <= reported", act <= ent, f"{act} <= {ent}")

print("\n" + "=" * 62)
if fails:
    print(f"RESULT: {len(fails)} FAILURE(S)")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print(f"RESULT: ALL v7 LOGIC CHECKS PASS ({len(warns)} warnings)")


# ─────────────────────────────────────────────────────────────────────
print("\n=== 12. ALLOCATION VIEW ===")
alloc = E.allocation_view(t2, t3, M, Y, cov)

for _, a_ in alloc.iterrows():
    m, ch = a_["Market"], a_["Channel"]
    ia = (J[(J.Market == m) & (J.Platform.isin(E.CHANNEL_GROUPS[ch]))
            & (J.Metric.isin(["Total Orders", "Orders"]))].Value.sum())
    isp = (J[(J.Market == m) & (J.Platform.isin(E.CHANNEL_GROUPS[ch]))
             & (J.Metric == "Budget Spent")].Value.sum())
    ipo = TJ[(TJ.Market == m) & (TJ.Platform == ch)
             & (TJ.Metric == "Target Orders")]["Target Value"].sum()
    ipb = TJ[(TJ.Market == m) & (TJ.Platform == ch)
             & (TJ.Metric == "Budget")]["Target Value"].sum()
    ck(f"{m} {ch} orders", float(a_["Orders"]), ia)
    ck(f"{m} {ch} spend", float(a_["Spend"]), isp, 1.0)
    ck(f"{m} {ch} CAC", a_["CAC"], isp / ia if ia else None, 0.01)
    ck(f"{m} {ch} plan CAC", a_["Plan CAC"], ipb / ipo if ipo else None, 0.01)
    ck(f"{m} {ch} cost index", a_["Cost index"],
       (isp / ia) / (ipb / ipo) if ia and ipo else None, 0.01)
    ck(f"{m} {ch} budget used", a_["Budget used"],
       isp / (ipb * DAYS / DIM) * 100 if ipb else None, 0.1)
    ck(f"{m} {ch} headroom", float(a_["Headroom"]),
       round(ipb * DAYS / DIM - isp), 1.0)

print("\n--- sort order and read sentence ---")
ck_true("sorted by CAC ascending",
        list(alloc["CAC"]) == sorted(alloc["CAC"]),
        f"{[round(c,1) for c in alloc['CAC']]}")
ck_true("cheapest label on the lowest-CAC row only",
        sum("Cheapest orders here" in r for r in alloc["Read"]) == 1)
ck_true("cheapest label sits on row 0",
        "Cheapest orders here" in alloc.iloc[0]["Read"])
ck_true("every row has a read sentence",
        alloc["Read"].notna().all() and (alloc["Read"].str.len() > 10).all())
ck_true("read sentences are distinct", alloc["Read"].nunique() == len(alloc))
for _, rr in alloc.iterrows():
    ci = rr["Cost index"]
    txt = rr["Read"]
    if ci < 1:
        want = f"{(1-ci)*100:.0f}% less than planned"
    elif ci < 1.1:
        want = "about what was planned"
    elif ci < 2:
        want = f"{(ci-1)*100:.0f}% more than planned"
    else:
        want = f"{ci:.1f}x what was planned"
    ck_true(f"{rr['Market']} {rr['Channel']} read states cost correctly",
            want in txt, f"expected '{want}'")
for mk in sorted(t2.Market.unique()):
    av = E.allocation_view(t2, t3, M, Y, cov, mk)
    ck_true(f"{mk} scoped: cheapest label follows the selection",
            sum("Cheapest orders here" in r for r in av["Read"]) == 1)
ck_true("every row has a verdict", alloc["Verdict"].notna().all())
ck_true("no row left unclassified", (alloc["Verdict"] != "n/a").all())
ck_true("allocation orders = KPI orders",
        abs(alloc["Orders"].sum() - snap.line("orders").actual) < 0.5,
        f"{alloc['Orders'].sum()} vs {snap.line('orders').actual}")
ck_true("allocation spend = KPI spend",
        abs(alloc["Spend"].sum() - snap.line("spend").actual) < 1.0,
        f"{alloc['Spend'].sum()} vs {snap.line('spend').actual}")

rec = E.reallocation_estimate(alloc)
if rec:
    ck_true("reallocation arithmetic",
            abs(rec["would_buy"] - rec["freed"] / rec["to_cac"]) < 1.0)
    ck_true("reallocation destination is a SCALE cell",
            rec["to"] in [f"{r['Market']} {r['Channel']}"
                          for _, r in alloc[alloc.Verdict == "SCALE"].iterrows()])
    ck_true("reallocation delta = would_buy - current",
            rec["delta"] == rec["would_buy"] - rec["current_orders"])

for mk in ["All"] + sorted(t2.Market.unique()):
    try:
        av = E.allocation_view(t2, t3, M, Y, cov, mk)
        ck_true(f"{mk} allocation builds", not av.empty or mk not in t2.Market.unique())
    except Exception as ex:
        ck_true(f"{mk} allocation builds", False, str(ex))

print("\n" + "=" * 62)
if fails:
    print(f"FINAL: {len(fails)} FAILURE(S)")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("FINAL: ALL v7.1 LOGIC CHECKS PASS")

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


def _absent(v):
    """NaN and None both mean 'no value'. Treating them differently is how the
    missing-vs-zero mistake gets into the test itself."""
    return v is None or (isinstance(v, float) and np.isnan(v))


def ck(name, got, want, tol=0.5):
    ok = (_absent(got) and _absent(want)) or (
        not _absent(got) and not _absent(want) and abs(got - want) <= tol)
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
    tgt_rows = TJ[(TJ.Market == m) & (TJ.Platform == ch)
                  & (TJ.Metric == "Target Orders")]["Target Value"]
    ck(f"{m} {ch} actual", float(g["Actual"]), ia)
    # An empty target selection sums to 0.0, which is not the same as a target
    # of zero. A cell with no plan must show no paced figure and no gap, not a
    # gap equal to everything it sold.
    if tgt_rows.empty:
        ck_true(f"{m} {ch} has no plan, so no paced figure",
                pd.isna(g["Paced plan"]), f"got {g['Paced plan']}")
        ck_true(f"{m} {ch} has no plan, so no gap",
                pd.isna(g["Gap (orders)"]), f"got {g['Gap (orders)']}")
        ck_true(f"{m} {ch} still appears in the table", g["Actual"] == ia)
    else:
        ipaced = tgt_rows.sum() * DAYS / DIM
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
    ck(f"{m} {ch} headroom", a_["Headroom"],
       (round(ipb * DAYS / DIM - isp) if ipb else None), 1.0)

print("\n--- sort order and read sentence ---")
_cacs = [c if (c and c > 0) else float("inf") for c in alloc["CAC"]]
ck_true("sorted by CAC ascending, absent or zero last",
        _cacs == sorted(_cacs), f"{[round(c,1) for c in alloc['CAC']]}")
_n_real = int((alloc["CAC"].fillna(0) > 0).sum())
ck_true("cheapest label appears at most once",
        sum("Cheapest orders here" in r for r in alloc["Read"]) == (1 if _n_real > 1 else 0))
if _n_real > 1:
    ck_true("cheapest label sits on row 0",
            "Cheapest orders here" in alloc.iloc[0]["Read"])
ck_true("every row has a read sentence",
        alloc["Read"].notna().all() and (alloc["Read"].str.len() > 10).all())
ck_true("read sentences are distinct", alloc["Read"].nunique() == len(alloc))
for _, rr in alloc.iterrows():
    ci = rr["Cost index"]
    txt = rr["Read"]
    if pd.isna(ci):
        ck_true(f"{rr['Market']} {rr['Channel']} read says there is no plan",
                "no plan" in txt.lower(), txt[:60])
        continue
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
    n_real = int((av["CAC"].fillna(0) > 0).sum())
    ck_true(f"{mk} scoped: cheapest label follows the selection",
            sum("Cheapest orders here" in r for r in av["Read"])
            == (1 if n_real > 1 else 0),
            f"{n_real} priced row(s)")
ck_true("every row has a verdict", alloc["Verdict"].notna().all())
ck_true("no row left unclassified", (alloc["Verdict"] != "n/a").all())

# A market can report actuals before it has a plan. Dropping those rows made
# real orders disappear from tables that are meant to account for all of them.
_act_cells = set()
for _m in sorted(t2.Market.unique()):
    for _c in E.CHANNEL_ORDER:
        if (E._chan_orders(t2, _m, _c, M, Y) or 0) or \
           (E._chan_metric(t2, E.SPEND, _m, _c, M, Y) or 0):
            _act_cells.add((_m, _c))
_alloc_cells = {(r["Market"], r["Channel"]) for _, r in alloc.iterrows()}
_gap_cells = {(r["Market"], r["Channel"]) for _, r in GAP.iterrows()}
ck_true("allocation covers every reporting cell",
        _act_cells <= _alloc_cells, f"missing {sorted(_act_cells - _alloc_cells)}")
ck_true("gap table covers every reporting cell",
        _act_cells <= _gap_cells, f"missing {sorted(_act_cells - _gap_cells)}")
ck_true("unplanned cells are labelled, not scored",
        all(r["Verdict"] == "no plan"
            for _, r in alloc.iterrows() if pd.isna(r["Cost index"])))
ck_true("unplanned cells never take the cheapest label",
        not any("Cheapest orders here" in r["Read"]
                for _, r in alloc.iterrows() if r["Verdict"] == "no plan"))
ck_true("a zero-CAC row never sorts to the top",
        alloc.iloc[0]["CAC"] > 0 if len(alloc) else True,
        f"top row CAC {alloc.iloc[0]['CAC'] if len(alloc) else 'n/a'}")
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

print("\n=== 13. CURRENCY ===")
_FX = {("UAE", None): 1.000, ("KSA", None): 0.979, ("Qatar", None): 1.009,
       ("Egypt", None): 0.072, ("Egypt", "2026-08"): 0.070}
fx_live = t2.attrs.get("fx", {})
print(f"  workbook FX table: {t2.attrs.get('fx_note')} "
      f"({len(fx_live)} row(s))")

b2, b3 = E.apply_fx(t2, t3, _FX)
for m in sorted(t2.Market.unique()):
    r_before = E.actual(t2, E.REVENUE, market=m, month=M, year=Y)
    r_after = E.actual(b2, E.REVENUE, market=m, month=M, year=Y)
    s_before = E.actual(t2, E.SPEND, market=m, month=M, year=Y)
    s_after = E.actual(b2, E.SPEND, market=m, month=M, year=Y)
    rate = E.fx_rate(_FX, m, M, Y)
    ck(f"{m} revenue x{rate}", r_after, r_before * rate, 1.0)
    ck_true(f"{m} spend untouched by FX", abs(s_before - s_after) < 1e-9,
            f"{s_before:,.2f} vs {s_after:,.2f}")

pr_b = E.target(t3, E.TGT_REVENUE, "KSA", M, Y, "Total")
pr_a = E.target(b3, E.TGT_REVENUE, "KSA", M, Y, "Total")
ck("KSA target revenue converts", pr_a, pr_b * 0.979, 1.0)
pb_b = E.target(t3, E.TGT_BUDGET, "KSA", M, Y, "Total")
pb_a = E.target(b3, E.TGT_BUDGET, "KSA", M, Y, "Total")
ck_true("target budget untouched by FX", abs(pb_b - pb_a) < 1e-9)

ck_true("month override beats default", E.fx_rate(_FX, "Egypt", 8, 2026) == 0.070)
ck_true("default used when no month row", E.fx_rate(_FX, "Egypt", 7, 2026) == 0.072)
ck_true("unknown market falls back to 1.0", E.fx_rate(_FX, "Oman", 7, 2026) == 1.0)
ck_true("empty FX table is a no-op", E.fx_rate({}, "KSA", 7, 2026) == 1.0)
n2, n3 = E.apply_fx(t2, t3, {})
ck_true("no FX table leaves data unchanged",
        abs(E.actual(n2, E.REVENUE, month=M, year=Y)
            - E.actual(t2, E.REVENUE, month=M, year=Y)) < 1e-9)

sb_ = E.build_snapshot(b2, b3, "All", M, Y)
ck_true("CAC unaffected by FX (spend is already AED)",
        abs(sb_.raw["cac"] - snap.raw["cac"]) < 1e-9,
        f"{snap.raw['cac']:.4f} vs {sb_.raw['cac']:.4f}")
fxchk = next(f for f in sb_.integrity if f["id"] == "FX")
ck_true("FX integrity check passes when rates cover every market", fxchk["pass"],
        fxchk["detail"])
fxchk0 = next(f for f in snap.integrity if f["id"] == "FX")
ck_true("FX integrity check fails loudly when the table is missing",
        (not fxchk0["pass"]) if not fx_live else fxchk0["pass"],
        fxchk0["detail"][:70])

print("\n" + "=" * 62)
if fails:
    print(f"FINAL: {len(fails)} FAILURE(S)")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("FINAL: ALL v7.2 LOGIC CHECKS PASS")


# ─────────────────────────────────────────────────────────────────────
print("\n=== 14. PERIOD COMPARISON ===")
import datetime as _d
_days = sorted(t2["Day"].unique())
_A = (_days[-7], _days[-1])
_B = (_days[-14], _days[-8])

def _raw(rng, mkts=None, plats=None, metric=None):
    d = J[(J.Date >= pd.Timestamp(rng[0])) & (J.Date <= pd.Timestamp(rng[1]))]
    if mkts: d = d[d.Market.isin(mkts)]
    if plats: d = d[d.Platform.isin(plats)]
    if metric == "orders":
        return d[d.Metric.isin(["Total Orders", "Orders"])].Value.sum()
    return d[d.Metric == metric].Value.sum()

blkA = E.cmp_block(t2, *_A)
blkB = E.cmp_block(t2, *_B)
ck("A orders", blkA["orders"], _raw(_A, metric="orders"))
ck("B orders", blkB["orders"], _raw(_B, metric="orders"))
ck("A spend", blkA["spend"], _raw(_A, metric="Budget Spent"), 1.0)
ck("A units", blkA["units"], _raw(_A, metric="Units"))
ck("A CAC = spend/orders", blkA["cac"],
   _raw(_A, metric="Budget Spent") / _raw(_A, metric="orders"), 0.01)
ck("A orders/day", blkA["daily"], blkA["orders"] / 7, 0.01)

print("\n--- deltas and polarity ---")
ck("orders delta", E.cmp_change(blkA, blkB, "orders")["delta"],
   blkA["orders"] - blkB["orders"])
ck("orders pct", E.cmp_change(blkA, blkB, "orders")["pct"],
   (blkA["orders"] - blkB["orders"]) / blkB["orders"] * 100, 0.01)
ck_true("identical periods read flat",
        E.cmp_change(blkA, blkA, "orders")["read"] == "flat")
ck_true("identical periods delta is zero",
        abs(E.cmp_change(blkA, blkA, "orders")["delta"]) < 1e-9)
ck_true("rising spend never reads better",
        E.cmp_change({"spend": 200}, {"spend": 100}, "spend")["read"] == "higher")
ck_true("falling spend never reads worse",
        E.cmp_change({"spend": 50}, {"spend": 100}, "spend")["read"] == "lower")
ck_true("falling CAC reads better",
        E.cmp_change({"cac": 10}, {"cac": 20}, "cac")["read"] == "better")
ck_true("rising CAC reads worse",
        E.cmp_change({"cac": 20}, {"cac": 10}, "cac")["read"] == "worse")
ck_true("rising orders reads better",
        E.cmp_change({"orders": 20}, {"orders": 10}, "orders")["read"] == "better")
ck_true("zero baseline reads new",
        E.cmp_change({"orders": 20}, {"orders": 0}, "orders")["read"] == "new")
ck_true("zero baseline has no percentage",
        E.cmp_change({"orders": 20}, {"orders": 0}, "orders")["pct"] is None)

print("\n--- hierarchy reconciles ---")
Hy = E.cmp_hierarchy(t2, _A, _B)
grp = Hy[Hy._level == 0].iloc[0]
mk = Hy[Hy._level == 1]
ck("group A = sum of markets", grp["A orders"], mk["A orders"].sum())
ck("group B = sum of markets", grp["B orders"], mk["B orders"].sum())
ck("group A = raw recompute", grp["A orders"], _raw(_A, metric="orders"))
for _, r in mk.iterrows():
    kids = Hy[(Hy._level == 2) & (Hy.index > _)]
ck_true("market shares sum to 100%",
        abs(mk["Share of change"].sum() - 100) < 0.5,
        f"{mk['Share of change'].sum():.1f}%")
ck_true("markets ordered by size of movement",
        list(mk["Share of change"]) == sorted(mk["Share of change"], reverse=True))

print("\n--- Meta split reconciles to consolidated ---")
Hc = E.cmp_hierarchy(t2, _A, _B, split_meta=False)
Hs = E.cmp_hierarchy(t2, _A, _B, split_meta=True)
ck("split group A = consolidated group A",
   Hs[Hs._level == 0].iloc[0]["A orders"], Hc[Hc._level == 0].iloc[0]["A orders"])
for m in sorted(t2.Market.unique()):
    cons = Hc[(Hc._level == 2) & (Hc.Scope == "Meta")]
    sp = Hs[(Hs._level == 2) & (Hs.Scope.isin(["Meta API", "Meta Ecom"]))]
mA = E.cmp_block(t2, *_A, [m for m in sorted(t2.Market.unique())], ["Meta API", "Meta Ecom"])
mS = (E.cmp_block(t2, *_A, None, ["Meta API"])["orders"]
      + E.cmp_block(t2, *_A, None, ["Meta Ecom"])["orders"])
ck("Meta split orders = Meta consolidated", mS, mA["orders"])

print("\n--- day alignment ---")
Dd = E.cmp_daily(t2, _A, _B)
ck_true("one row per day of the longer period", len(Dd) == 7, f"{len(Dd)} rows")
ck("daily A sums to period A", Dd["Period A"].sum(), blkA["orders"], 1.0)
ck("daily B sums to period B", Dd["Period B"].sum(), blkB["orders"], 1.0)
ck_true("every day carries its real date", (Dd["A date"].str.len() > 0).all())
Duneven = E.cmp_daily(t2, (_days[-5], _days[-1]), (_days[-14], _days[-8]))
ck_true("uneven windows pad rather than truncate", len(Duneven) == 7)
ck_true("short period padded with nulls, not zeros",
        Duneven["Period A"].isna().sum() == 2)

print("\n--- scoping ---")
for m in sorted(t2.Market.unique()):
    b = E.cmp_block(t2, *_A, [m])
    ck(f"{m} scoped orders", b["orders"], _raw(_A, mkts=[m], metric="orders"))
api = E.cmp_block(t2, *_A, None, ["API"])
ck("API scoped orders", api["orders"], _raw(_A, plats=["API"], metric="orders"))
ck_true("platform resolution consolidates Meta",
        E._platforms_for(["Meta"], False) == ["Meta API", "Meta Ecom"])
ck_true("platform resolution passes split names through",
        E._platforms_for(["Meta API"], True) == ["Meta API"])
ck_true("no channel selection means every platform",
        E._platforms_for(None, False) is None)

print("\n--- summary text ---")
summ = E.cmp_summary(t2, _A, _B)
ck_true("summary produced", len(summ) >= 2)
ck_true("every line has a severity",
        all(s in ("good", "warn", "risk", "info") for s, _ in summ))
same = E.cmp_summary(t2, _A, _A)
ck_true("identical periods do not claim a change",
        not any("rose" in t or "fell" in t for _, t in same),
        same[0][1][:60] if same else "")

print("\n--- presets ---")
pre = E.cmp_presets(_days)
ck_true("presets produced", len(pre) >= 1)
for name, (as_, ae_, bs_, be_) in pre.items():
    ck_true(f"preset '{name}' ranges are ordered", as_ <= ae_ and bs_ <= be_)
    ck_true(f"preset '{name}' periods do not overlap", be_ < as_)

print("\n" + "=" * 62)
if fails:
    print(f"COMPARISON: {len(fails)} FAILURE(S)")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("COMPARISON: ALL v7.3 LOGIC CHECKS PASS")

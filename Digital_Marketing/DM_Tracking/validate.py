"""Independent validation of dm_engine against the raw workbook.

Recomputes every headline figure straight from the sheet with plain pandas and
compares it to what the engine produces. Any mismatch is an engine bug.
"""
import sys
import pandas as pd
import numpy as np
import dm_engine as E

PATH = "/mnt/user-data/uploads/DM_Planing_Tracking_2026_25JUL26_V1_21.xlsx"
MONTH, YEAR = 7, 2026

fails = []


def check(name, got, want, tol=0.5):
    if got is None or want is None:
        ok = got is None and want is None
    else:
        ok = abs(got - want) <= tol
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: engine={got} independent={want}")
    if not ok:
        fails.append(name)


def check_eq(name, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: engine={got!r} independent={want!r}")
    if not ok:
        fails.append(name)


# ── independent recomputation, deliberately not using the engine ──────
raw = pd.read_excel(PATH, sheet_name="T2. Actuals", skiprows=1)
raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")
raw["Value"] = pd.to_numeric(raw["Value"], errors="coerce")
raw = raw.dropna(subset=["Date", "Value"])
J = raw[(raw.Date.dt.month == MONTH) & (raw.Date.dt.year == YEAR)]

tg = pd.read_excel(PATH, sheet_name="T3. Targets", skiprows=1)
tg["Month"] = pd.to_datetime(tg["Month"], errors="coerce")
tg["Target Value"] = pd.to_numeric(tg["Target Value"], errors="coerce")
tg = tg.dropna(subset=["Month", "Target Value"])
TJ = tg[(tg.Month.dt.month == MONTH) & (tg.Month.dt.year == YEAR)]

i_orders = J[J.Metric.isin(["Total Orders", "Orders"])].Value.sum()
i_units = J[J.Metric == "Units"].Value.sum()
i_rev = J[J.Metric == "Revenue (AED)"].Value.sum()
i_spend = J[J.Metric == "Budget Spent"].Value.sum()
i_api_ord = J[(J.Platform == "API") & (J.Metric == "Total Orders")].Value.sum()
i_meta_ord = J[(J.Platform.isin(["Meta API", "Meta Ecom"])) & (J.Metric == "Orders")].Value.sum()
i_msg = J[J.Metric.isin(["Messages to Customers", "Messages to Leads"])].Value.sum()
i_days = J.Date.dt.date.nunique()

t_ord = TJ[(TJ.Platform == "Total") & (TJ.Metric == "Target Orders")]["Target Value"].sum()
t_rev = TJ[(TJ.Platform == "Total") & (TJ.Metric == "Target Revenue")]["Target Value"].sum()
t_un = TJ[(TJ.Platform == "Total") & (TJ.Metric == "Target Units")]["Target Value"].sum()
t_bud = TJ[(TJ.Platform == "Total") & (TJ.Metric == "Budget")]["Target Value"].sum()

# ── engine ───────────────────────────────────────────────────────────
t2, t3 = E.load_data(PATH)
s = E.build_snapshot(t2, t3, "All", MONTH, YEAR)
r = s.raw

print("\n=== A. ACTUALS vs INDEPENDENT RECOMPUTE ===")
check("orders", r["ord_tot"], i_orders)
check("units", r["units"], i_units)
check("revenue", r["rev"], i_rev)
check("spend", r["spend"], i_spend)
check("API orders", r["ord_api"], i_api_ord)
check("Meta orders", r["ord_meta"], i_meta_ord)
check("API messages", r["msg_api"], i_msg)
check("days elapsed", s.coverage.days_elapsed, i_days)

print("\n=== B. TARGETS vs INDEPENDENT RECOMPUTE ===")
check("plan orders", r["plan_ord"], t_ord)
check("plan revenue", r["plan_rev"], t_rev)
check("plan units", r["plan_units"], t_un)
check("plan budget", r["plan_bud"], t_bud)

print("\n=== C. DERIVED IDENTITIES ===")
check("AOV = rev/orders", r["aov"], i_rev / i_orders, 0.01)
check("basket = units/orders", r["basket"], i_units / i_orders, 0.001)
check("ROAS = rev/spend", r["roas"], i_rev / i_spend, 0.01)
check("CAC = spend/orders", r["cac"], i_spend / i_orders, 0.01)
check("price/unit", r["price_per_unit"], i_rev / i_units, 0.01)
eom_ord = i_orders / i_days * 31
check("EOM orders", s.line("orders").eom, eom_ord, 1.0)
check("EOM revenue", s.line("revenue").eom, i_rev / i_days * 31, 5.0)

print("\n=== E. POLARITY: overspend must never be green ===")
for r_test, want in [(80, E.AMBER), (95, E.GREEN), (100, E.GREEN),
                     (110, E.AMBER), (130, E.RED), (50, E.RED)]:
    v = E.rag(r_test, 100, "spend")
    ok = v.color == want
    print(f"  [{'PASS' if ok else 'FAIL'}] spend at {r_test}% -> {v.label} ({'green' if v.color==E.GREEN else 'amber' if v.color==E.AMBER else 'red'})")
    if not ok:
        fails.append(f"polarity spend {r_test}")
for r_test, want in [(100, E.GREEN), (117, E.AMBER), (140, E.RED)]:
    v = E.rag(r_test, 100, "down")
    ok = v.color == want
    print(f"  [{'PASS' if ok else 'FAIL'}] CAC at {r_test}% of plan -> {v.label}")
    if not ok:
        fails.append(f"polarity cac {r_test}")

print("\n=== F. MISSING vs ZERO ===")
check_eq("None formats as n/a", E.fmt(None), "n/a")
check_eq("zero formats as 0", E.fmt(0), "0")
v = E.rag(None, 100, "up")
check_eq("None never scored", (v.label, v.scored), ("n/a", False))
v = E.rag(50, None, "up")
check_eq("no basis never scored", (v.label, v.scored), ("n/a", False))

print("\n=== G. ROUNDING keeps distinct values distinct ===")
a, b = E.fmt(2918), E.fmt(3345)
ok = a != b
print(f"  [{'PASS' if ok else 'FAIL'}] 2918 -> {a}, 3345 -> {b}")
if not ok:
    fails.append("rounding collision")

print("\n=== H. TRUE DELTA ===")
check("identical periods -> 0%", E.delta_pct(100, 100), 0.0, 1e-9)
check("A double B -> +100%", E.delta_pct(200, 100), 100.0, 1e-9)

print("\n=== I. MOMENTUM window ===")
ser = E.daily_orders_series(t2, None, MONTH, YEAR)
m = E.momentum(ser)
v = list(ser.values)
ind_recent, ind_prior = np.mean(v[-7:]), np.mean(v[-14:-7])
check("momentum recent", m.recent, ind_recent, 0.01)
check("momentum prior", m.prior, ind_prior, 0.01)
print(f"  label: {m.label}  ({m.recent:.0f}/day vs {m.prior:.0f}/day)")

print("\n=== J. COVERAGE: entries vs activity ===")
for mk, (entries, active) in sorted(s.coverage.per_market.items()):
    ind_e = J[J.Market == mk].Date.dt.date.nunique()
    ok = entries == ind_e
    print(f"  [{'PASS' if ok else 'FAIL'}] {mk}: entries={entries} (independent {ind_e}), active days={active}")
    if not ok:
        fails.append(f"coverage {mk}")

print("\n=== K. INTEGRITY CHECKS AS RUN BY THE ENGINE ===")
for f in s.integrity:
    print(f"  [{'PASS' if f['pass'] else 'FAIL'}] {f['check']} :: {f['detail']}")

print("\n=== L. PER-MARKET SNAPSHOTS BUILD CLEANLY ===")
for mk in ["All"] + sorted(t2.Market.unique()):
    try:
        sm = E.build_snapshot(t2, t3, mk, MONTH, YEAR)
        c = E.build_commentary(sm)
        bd = E.market_channel_breakdown(t2, t3, MONTH, YEAR, sm.coverage)
        print(f"  [PASS] {mk}: {len(sm.lines)} lines, {len(c)} commentary, {len(bd)} breakdown rows")
    except Exception as e:
        print(f"  [FAIL] {mk}: {type(e).__name__}: {e}")
        fails.append(f"snapshot {mk}")

print("\n=== M. SCORECARD RENDER ===")
for ln in s.lines:
    print(f"  {ln.label:<15} act={E.fmt(ln.actual, ln.prefix, ln.suffix, ln.dec):>12} "
          f"plan={E.fmt(ln.plan, ln.prefix, ln.suffix, ln.dec):>12} "
          f"basis={ln.basis:<6} {ln.verdict.label:>16}  trend={ln.trend}")

print("\n=== N. COMMENTARY (All / Jul) ===")
for sev, txt in E.build_commentary(s):
    print(f"  [{sev}] {txt}")

print("\n" + "=" * 62)
if fails:
    print(f"RESULT: {len(fails)} FAILURE(S): {fails}")
    sys.exit(1)
print("RESULT: ALL ENGINE CHECKS PASS")

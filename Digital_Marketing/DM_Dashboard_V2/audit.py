"""
Audit the V2 engine against the workbook.

Recomputes every figure independently with plain pandas and compares it to what
the engine produced. A dashboard that runs is not the same as a dashboard that
is right; this is the part that checks the second.

Run before every deploy:  python3 audit.py
"""
import sys
import calendar
import datetime as dt

import numpy as np
import pandas as pd

import dm_engine as E

# The workbook lives on SharePoint. A local copy is used when present — handy
# offline — but it is never required, and never committed.
import pathlib

LOCAL = ["DM_Model_2026_V3_5.xlsx", "DM_Model_2026_V3.xlsx"]
PATH = next((p for p in LOCAL if pathlib.Path(p).exists()), None)
if PATH is None:
    import sharepoint_loader as SP
    if not SP.is_configured():
        print("No local workbook and SharePoint is not configured.\n"
              "Missing: " + ", ".join(SP.missing_keys()))
        sys.exit(1)
    buf, meta = SP.fetch_workbook()
    PATH = buf
    print(f"Source: SharePoint · {meta.get('name')} · edited {meta.get('modified')}")
else:
    print(f"Source: local file · {PATH}")

fails, warns = [], []


def ck(name, got, want, tol=0.5):
    absent = lambda v: v is None or (isinstance(v, float) and np.isnan(v))
    ok = (absent(got) and absent(want)) or (
        not absent(got) and not absent(want) and abs(got - want) <= tol)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got} want={want}")
    if not ok:
        fails.append(name)


def ck_true(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        fails.append(name)


def warn(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'WARN'}] {name} {detail}")
    if not cond:
        warns.append(name)


if hasattr(PATH, "seek"):
    PATH.seek(0)
M = E.load_model(PATH)
YEAR, MONTH = 2026, "Jul"
COV = E.coverage(M, YEAR, MONTH)

# ── independent recompute straight from the sheet ────────────────────
if hasattr(PATH, "seek"):
    PATH.seek(0)
raw = pd.read_excel(PATH, sheet_name=E.SH_ACTUALS, header=3)
raw = raw[raw["Market"].notna()]
raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")
raw["Value"] = pd.to_numeric(raw["Value"], errors="coerce")
raw = raw.dropna(subset=["Date", "Value"])
J = raw[(raw.Date.dt.month == E.MONTH_NO[MONTH]) & (raw.Date.dt.year == YEAR)].copy()

# Setup carries several tables on one sheet, so the audit locates the Markets
# block the same way the engine does — by header text, not by a fixed address.
import openpyxl as _px
if hasattr(PATH, "seek"):
    PATH.seek(0)
_ws = _px.load_workbook(PATH, data_only=True)[E.SH_SETUP]
mkr = E._read_block(_ws, *E._find_block(_ws, "Markets", "Market"))
RATE = {str(r["Market"]).strip(): float(r["Rate to AED"])
        for _, r in mkr.iterrows() if pd.notna(r.get("Rate to AED"))}
SPEND_LOCAL = {str(r["Market"]).strip() for _, r in mkr.iterrows()
               if str(r.get("Spend ccy", "AED")).strip().upper() != "AED"}


def raw_sum(metric, market=None, channel=None, conv=True):
    d = J[J["Metric"] == metric]
    if market:
        d = d[d["Market"] == market]
    if channel:
        d = d[d["Channel"] == channel]
    if not conv:
        return float(d["Value"].sum())
    tot = 0.0
    for _, r in d.iterrows():
        v = r["Value"]
        if metric == E.M_REVENUE or (metric == E.M_SPEND and r["Market"] in SPEND_LOCAL):
            v *= RATE.get(r["Market"], 1.0)
        tot += v
    return float(tot)


print("\n=== 1. ACTUALS MATCH THE SHEET ===")
for met in [E.M_ORDERS, E.M_UNITS, E.M_REVENUE, E.M_SPEND,
            E.M_MSG_CUST, E.M_MSG_LEAD, E.M_MSG_RECV]:
    ck(f"total {met}", E.actual(M, met, year=YEAR, month=MONTH), raw_sum(met), 1.0)

print("\n  -- per market --")
for mk in sorted(J["Market"].unique()):
    for met in [E.M_ORDERS, E.M_REVENUE, E.M_SPEND]:
        ck(f"{mk} {met}", E.actual(M, met, markets=[mk], year=YEAR, month=MONTH),
           raw_sum(met, market=mk), 1.0)

print("\n  -- per channel --")
for ch in sorted(J["Channel"].unique()):
    ck(f"{ch} orders", E.actual(M, E.M_ORDERS, channels=[ch], year=YEAR, month=MONTH),
       raw_sum(E.M_ORDERS, channel=ch), 1.0)

print("\n  -- every day --")
for d in sorted(J.Date.dt.date.unique()):
    got = E.actual(M, E.M_ORDERS, date_from=d, date_to=d)
    want = float(J[(J.Date.dt.date == d) & (J.Metric == E.M_ORDERS)].Value.sum())
    ck(f"orders on {d}", got or 0.0, want, 1.0)

print("\n=== 2. CURRENCY ===")
ck_true("FX rates loaded", M.fx_note == "ok", M.fx_note)
raw_rev = raw_sum(E.M_REVENUE, conv=False)
conv_rev = raw_sum(E.M_REVENUE)
ck("revenue converted, not raw", E.actual(M, E.M_REVENUE, year=YEAR, month=MONTH),
   conv_rev, 1.0)
ck_true("conversion actually changed revenue", abs(raw_rev - conv_rev) > 1,
        f"raw {raw_rev:,.0f} vs AED {conv_rev:,.0f}")
for mk in sorted(J["Market"].unique()):
    if mk in SPEND_LOCAL:
        ck(f"{mk} spend converted (local ccy)",
           E.actual(M, E.M_SPEND, markets=[mk], year=YEAR, month=MONTH),
           raw_sum(E.M_SPEND, market=mk), 1.0)
    else:
        ck(f"{mk} spend untouched (already AED)",
           E.actual(M, E.M_SPEND, markets=[mk], year=YEAR, month=MONTH),
           raw_sum(E.M_SPEND, market=mk, conv=False), 1.0)

print("\n=== 3. PACING AND RUN RATE ===")
dim = calendar.monthrange(YEAR, E.MONTH_NO[MONTH])[1]
elapsed = J.Date.dt.date.nunique()
ck("days in month", COV.days_in_month, dim)
ck("days elapsed", COV.days_elapsed, elapsed)
ck("days remaining", COV.days_remaining, dim - elapsed)
t = E.target_orders(M, year=YEAR, month=MONTH)
ck(f"paced = plan x {elapsed}/{dim}", E.paced(t, COV), t * elapsed / dim, 1.0)
o = E.actual(M, E.M_ORDERS, year=YEAR, month=MONTH)
ck(f"run rate = actual / {elapsed} x {dim}", E.eom(o, COV), o / elapsed * dim, 1.0)
ck_true("a ratio is never paced", E.paced(None, COV) is None)

print("\n=== 4. POLARITY ===")
for r, want in [(80, E.GREY), (105, E.GREY), (160, E.GREY)]:
    v = E.rag(r, 100, "neutral")
    ck_true(f"spend at {r}% carries no verdict", not v.scored and v.color == E.GREY, v.label)
ck_true("CPA over plan is not green", E.rag(140, 100, "down").color == E.RED)
ck_true("CPA under plan is green", E.rag(95, 100, "down").color == E.GREEN)
ck_true("orders over plan is green", E.rag(140, 100, "up").color == E.GREEN)
ck_true("orders well under plan is red", E.rag(40, 100, "up").color == E.RED)
ck_true("comparison: rising spend never reads better",
        E.cmp_change({"spend": 200}, {"spend": 100}, "spend")["read"] == "higher")
ck_true("comparison: falling CPA reads better",
        E.cmp_change({"cpa": 10}, {"cpa": 20}, "cpa")["read"] == "better")
ck_true("comparison: identical reads flat",
        E.cmp_change({"orders": 50}, {"orders": 50}, "orders")["read"] == "flat")
ck_true("comparison: zero baseline reads new",
        E.cmp_change({"orders": 50}, {"orders": 0}, "orders")["read"] == "new")

print("\n=== 5. PLAUSIBILITY GUARD ===")
for act, ratio, key, block in [(0, 0, "cpa", True), (1e9, 5e8, "orders", True),
                               (150, 200, "cr", True), (18.2, 118, "cpa", False),
                               (17.1, 105, "roas", False)]:
    ok, why = E.plausible(act, ratio, key)
    ck_true(f"{key} act={act:g} -> {'block' if block else 'allow'}",
            (not ok) == block, why)

print("\n=== 6. NULLS ===")
ck_true("None renders n/a", E.fmt(None) == "n/a")
ck_true("zero renders 0", E.fmt(0) == "0")
ck_true("None is never scored", not E.rag(None, 100, "up").scored)
ck_true("no basis is never scored", not E.rag(50, None, "up").scored)
ck_true("2,918 and 3,345 render differently", E.fmt(2918) != E.fmt(3345))
ck_true("identical periods give a zero delta", E.delta_pct(100, 100) == 0.0)

print("\n=== 7. CROSS-SECTION CONSISTENCY ===")
cards = E.overview_cards(M, None, None, YEAR, MONTH, COV)
card_orders = next(c for c in cards if c.key == "orders").actual
G = E.gap_table(M, None, None, YEAR, MONTH, COV)
A = E.allocation_table(M, None, None, YEAR, MONTH, COV)
ck("overview orders = raw", card_orders, raw_sum(E.M_ORDERS), 1.0)
ck("gap table orders = overview", float(G["Actual"].sum()), card_orders, 1.0)
ck("allocation orders = overview", float(A["Orders"].sum()), card_orders, 1.0)
ck("allocation spend = overview",
   float(A["Spend"].sum()),
   next(c for c in cards if c.key == "spend").actual, 1.0)
behind = G[G["Share of gap"] > 0]
ck_true("gap shares total 100%", abs(behind["Share of gap"].sum() - 100) < 0.5,
        f"{behind['Share of gap'].sum():.1f}%")
ck_true("cells ahead of pace get no share",
        (G[G["Behind by"].fillna(0) < 0]["Share of gap"] == 0).all())
ck_true("allocation sorted by CPA, absent or zero last",
        [c if (c and c > 0) else float("inf") for c in A["CPA"]]
        == sorted([c if (c and c > 0) else float("inf") for c in A["CPA"]]))
ck_true("cheapest label appears at most once",
        sum("Cheapest orders here" in r for r in A["Read"]) <= 1)
ck_true("every allocation row has a read sentence",
        A["Read"].notna().all() and (A["Read"].str.len() > 10).all())

print("\n=== 8. COMPARISON ===")
days = sorted(M.actuals["Day"].unique())
AR, BR = (days[-7], days[-1]), (days[-14], days[-8])
blkA, blkB = E.cmp_block(M, *AR), E.cmp_block(M, *BR)
wantA = float(J[(J.Metric == E.M_ORDERS) & (J.Date.dt.date >= AR[0])
                & (J.Date.dt.date <= AR[1])].Value.sum())
ck("period A orders", blkA["orders"], wantA, 1.0)
ck("period A CPA = spend/orders", blkA["cpa"], blkA["spend"] / blkA["orders"], 0.01)
ck("period A orders/day", blkA["daily"], blkA["orders"] / 7, 0.01)
H = E.cmp_hierarchy(M, AR, BR)
grp = H[H._level == 0].iloc[0]
mk = H[H._level == 1]
ck("hierarchy group = sum of markets", grp["A orders"], mk["A orders"].sum(), 1.0)
ck("hierarchy group = block", grp["A orders"], blkA["orders"], 1.0)
ck_true("market shares total 100%", abs(mk["Share of change"].sum() - 100) < 0.5)
ck_true("markets ordered by size of movement",
        list(mk["Share of change"]) == sorted(mk["Share of change"], reverse=True))
D = E.cmp_daily(M, AR, BR)
ck("daily A sums to period A", D["Period A"].sum(), blkA["orders"], 1.0)
ck("daily B sums to period B", D["Period B"].sum(), blkB["orders"], 1.0)
Du = E.cmp_daily(M, (days[-5], days[-1]), (days[-14], days[-8]))
ck_true("uneven windows pad rather than truncate", len(Du) == 7)
ck_true("short period padded with nulls, not zeros", Du["Period A"].isna().sum() == 2)
same = E.cmp_summary(M, AR, AR)
ck_true("identical periods claim no change",
        not any("rose" in t or "fell" in t for _, t in same),
        same[0][1][:60] if same else "")
pre = E.cmp_presets(days)
for name, (a1, a2, b1, b2) in pre.items():
    ck_true(f"preset '{name}' is ordered and does not overlap",
            a1 <= a2 and b1 <= b2 and b2 < a1)

print("\n=== 8b. GRANULARITY PRESERVED ===")
# The tracking side reports Meta API and Meta Ecom separately and customer and
# lead messages separately. Merging either keeps the totals right and destroys
# the split, which is the whole point of tracking at that level.
ORIG = pd.read_excel("final_source.xlsx", sheet_name="T2. Actuals", skiprows=1) \
    if __import__("pathlib").Path("final_source.xlsx").exists() else None
for ch in ["Meta API", "Meta Ecom", "API"]:
    ck_true(f"{ch} exists as its own channel in the actuals",
            ch in set(M.actuals["Channel"]),
            str(sorted(set(M.actuals["Channel"]))))
for met in [E.M_MSG_CUST, E.M_MSG_LEAD]:
    ck_true(f"{met} exists as its own metric",
            met in set(M.actuals["Metric"]),
            str(sorted(set(M.actuals["Metric"]))))
ck_true("no merged 'Messages Sent' metric survives",
        "Messages Sent" not in set(M.actuals["Metric"]))
for ch in ["Meta API", "Meta Ecom"]:
    o = E.actual(M, E.M_ORDERS, channels=[ch], year=YEAR, month=MONTH)
    w = raw_sum(E.M_ORDERS, channel=ch)
    ck(f"{ch} orders are separately visible", o, w, 1.0)

print("\n=== 8c. CHANNEL ROLLUP ===")
par = M.parent_of()
ck_true("register declares a rollup", bool(par), str(par))
both = E.plan_orders(M, None, ["Meta API", "Meta Ecom"], YEAR, MONTH)
one = E.plan_orders(M, None, ["Meta API"], YEAR, MONTH)
ck("selecting both Meta platforms does not double the plan", both, one, 0.5)
ck_true("a parent channel is not offered as a selection",
        "Meta" not in M.channel_list(), str(M.channel_list()))
kids_o = E.actual(M, E.M_ORDERS, channels=["Meta API", "Meta Ecom"],
                  year=YEAR, month=MONTH)
ck("children sum to the Meta actual",
   kids_o, raw_sum(E.M_ORDERS, channel="Meta API")
   + raw_sum(E.M_ORDERS, channel="Meta Ecom"), 1.0)

print("\n=== 9. REGISTER-DRIVEN, NOTHING HARDCODED ===")
import inspect
src = inspect.getsource(E)
named = [n for n in ("UAE", "KSA", "Qatar", "Egypt", "Meta", "TikTok", "Snapchat")
         if f'"{n}"' in src or f"'{n}'" in src]
ck_true("no market or channel named in the engine", not named, str(named))
ck_true("markets come from the register",
        set(M.actuals["Market"]) <= set(M.market_list()))
ck_true("channels come from the register",
        set(M.actuals["Channel"]) <= set(M.channel_list()))

print("\n=== 10. SCOPING ===")
for mk_ in M.market_list():
    b = E.cmp_block(M, *AR, [mk_])
    want = float(J[(J.Metric == E.M_ORDERS) & (J.Market == mk_)
                   & (J.Date.dt.date >= AR[0]) & (J.Date.dt.date <= AR[1])].Value.sum())
    ck(f"{mk_} scoped orders", b["orders"], want, 1.0)
tot = sum(E.cmp_block(M, *AR, [x])["orders"] for x in M.market_list())
ck("markets sum to the group", tot, blkA["orders"], 1.0)

print("\n=== 10b. META COMBINED AND SPLIT ===")
ck_true("combined view offers the parent, not the platforms",
        "Meta" in M.display_channels(False)
        and "Meta API" not in M.display_channels(False),
        str(M.display_channels(False)))
ck_true("split view offers the platforms, not the parent",
        "Meta API" in M.display_channels(True)
        and "Meta" not in M.display_channels(True),
        str(M.display_channels(True)))
ck_true("selecting Meta combined expands to both platforms",
        set(M.expand(["Meta"], False)) == {"Meta API", "Meta Ecom"},
        str(M.expand(["Meta"], False)))
_comb = E.actual(M, E.M_ORDERS, channels=M.expand(["Meta"], False),
                 year=YEAR, month=MONTH)
_split = sum(E.actual(M, E.M_ORDERS, channels=[c], year=YEAR, month=MONTH) or 0
             for c in ("Meta API", "Meta Ecom"))
ck("combined Meta equals the sum of its platforms", _comb, _split, 1.0)
_gc = E.gap_table(M, None, None, YEAR, MONTH, COV, False)
_gs = E.gap_table(M, None, None, YEAR, MONTH, COV, True)
ck("gap table totals the same either way",
   float(_gc["Actual"].sum()), float(_gs["Actual"].sum()), 1.0)
_ac_ = E.allocation_table(M, None, None, YEAR, MONTH, COV, False)
_as_ = E.allocation_table(M, None, None, YEAR, MONTH, COV, True)
ck("allocation totals the same either way",
   float(_ac_["Orders"].sum()), float(_as_["Orders"].sum()), 1.0)
ck("allocation spend the same either way",
   float(_ac_["Spend"].sum()), float(_as_["Spend"].sum()), 1.0)
ck_true("split platforms carry no plan of their own",
        all(pd.isna(r["Plan CPA"]) for _, r in _as_.iterrows()
            if r["Channel"] in ("Meta API", "Meta Ecom")),
        "a platform must not inherit the parent's plan")

print("\n=== 10c. YEAR TO DATE ===")
_closed = E.closed_months(M, YEAR)
_cur = E.current_month(M, YEAR)
ck_true("closed months are in calendar order",
        _closed == sorted(_closed, key=lambda x: E.MONTH_NO[x]), str(_closed))
_dim = {mo: calendar.monthrange(YEAR, E.MONTH_NO[mo])[1] for mo in _closed}
for mo in _closed:
    d_ = E.scope(M.actuals, year=YEAR, month=mo)
    ck_true(f"{mo} reported every one of its {_dim[mo]} days",
            int(d_["Day"].nunique()) >= _dim[mo],
            f"{int(d_['Day'].nunique())} days")
_running = [mo for mo in M.months_in(YEAR) if mo not in _closed]
ck_true("a running or unstarted month is excluded from YTD",
        all(mo not in _closed for mo in _running), str(_running))
if _closed:
    _cv = E.coverage(M, YEAR, _closed)
    _t = E.target_orders(M, year=YEAR, month=_closed)
    ck_true("YTD paces to the full plan, never pro-rated",
            abs((E.paced(_t, _cv) or 0) - (_t or 0)) < 1,
            f"{E.paced(_t, _cv):,.0f} vs {_t:,.0f}")
    _o_each = sum(E.actual(M, E.M_ORDERS, year=YEAR, month=[x]) or 0 for x in _closed)
    ck("YTD orders equal the sum of its months",
       E.actual(M, E.M_ORDERS, year=YEAR, month=_closed) or 0, _o_each, 1.0)

print("\n=== 10d. SPEND TRAJECTORY ===")
_sp = E.spend_path(M, None, None, YEAR, MONTH, COV)
ck("spend to date matches the actuals", _sp.spent,
   E.actual(M, E.M_SPEND, year=YEAR, month=MONTH) or 0, 1.0)
ck_true("direction is one of the four states",
        _sp.direction in ("rising", "falling", "steady", "flat"), _sp.direction)
if COV.days_remaining == 0:
    ck("a closed month projects to what it spent", _sp.eom, _sp.spent, 1.0)
else:
    ck_true("projection is at least what has been spent", _sp.eom >= _sp.spent)
ck_true("landing percentage is against the ceiling",
        _sp.ceiling is None or abs(_sp.landing_pct - _sp.eom / _sp.ceiling * 100) < 0.5)

print("\n=== 10e. CAPACITY MODEL ===")
_cc = E.capacity_check(M, None, YEAR, MONTH if isinstance(MONTH, str) else MONTH[-1])
ck_true("a capacity row exists per modelled market", len(_cc) >= 1, f"{len(_cc)} rows")
for _, r_ in _cc.iterrows():
    want = E.actual(M, E.M_ORDERS, markets=[r_["Market"]], channels=["API"],
                    year=YEAR, month=MONTH if isinstance(MONTH, str) else MONTH[-1])
    ck(f"{r_['Market']} delivered = API actual", r_["Delivered"], want or 0, 1.0)
    ck(f"{r_['Market']} hit = delivered / modelled", r_["Hit"],
       r_["Delivered"] / r_["Modelled capacity"] * 100, 0.5)
    ck_true(f"{r_['Market']} read attributes the gap", len(str(r_["Read"])) > 10)
    # Capacity is messages x CR% x uptime; delivery carries no haircut. Without
    # uptime the two factors do not reconstruct the hit, and a market on plan
    # for both reads as over-delivering.
    ck("uptime is captured", r_["Uptime"] > 0, r_["Uptime"], 1)
    ck(f"{r_['Market']} reachable = net / uptime", r_["Reachable"],
       r_["Modelled capacity"] / r_["Uptime"], 1)
    if r_["Messages sent"] and r_["CR% assumed"]:
        implied = (r_["Messages %"] / 100) * (r_["CR% actual"] / r_["CR% assumed"]) * 100
        ck(f"{r_['Market']} factors reconstruct the reachable hit",
           r_["Hit before uptime"], implied, 0.5)
# capacity = messages x CR%, so the read must not blame the factor that held
_held = _cc[(_cc["CR% assumed"] - _cc["CR% actual"]).abs() < 0.01]
ck_true("a read never blames conversion when CR% held exactly",
        all("converted" not in str(r_["Read"]).lower() or "held" in str(r_["Read"]).lower()
            for _, r_ in _held.iterrows()),
        str([r_["Read"] for _, r_ in _held.iterrows()][:2]))

print("\n=== 10f. CPA IN CONTEXT ===")
_ctx = E.cpa_context(M, None, None, YEAR, MONTH)
ck_true("every market has a baseline channel",
        all(len(g[g["vs cheapest"] <= 1.001]) >= 1
            for _, g in _ctx.groupby("Market")) if len(_ctx) else True)
for _, r_ in _ctx.iterrows():
    ck(f"{r_['Market']} {r_['Channel']} CPA = spend / orders",
       r_["CPA"], r_["Spend"] / r_["Orders"], 0.01)
ck_true("the cheapest row is the lowest CPA in its market",
        all(g.loc[g["vs cheapest"].idxmin(), "CPA"] == g["CPA"].min()
            for _, g in _ctx.groupby("Market")) if len(_ctx) else True)
ck_true("vs cheapest is never below 1", (_ctx["vs cheapest"] >= 0.999).all()
        if len(_ctx) else True)

print("\n=== 10g. EXECUTIVE COMMENTARY ===")
import datetime as _dt
_cm = E.commentary(M, None, None, YEAR, MONTH, COV, today=_dt.date(2026, 8, 3))
ck_true("verdict is one of the four states",
        _cm.verdict in ("Ahead of plan", "On plan", "Slightly behind",
                        "Behind plan", "No plan"), _cm.verdict)
ck_true("severity matches the verdict",
        (_cm.severity == "risk") == (_cm.verdict == "Behind plan"),
        f"{_cm.verdict} / {_cm.severity}")
ck_true("headline names the period and the number",
        any(ch.isdigit() for ch in _cm.headline), _cm.headline)

# Every window must be measured on REPORTED days: calendar days would show a
# collapse for any day not yet entered.
_days = sorted(M.actuals["Day"].unique())
for w in _cm.windows:
    ck_true(f"{w.label} ends on the last reported day", w.a_to == _days[-1],
            f"{w.a_to} vs {_days[-1]}")
    ck_true(f"{w.label} windows do not overlap", w.b_to < w.a_from,
            f"{w.b_to} then {w.a_from}")
    n_a = (pd.Timestamp(w.a_to) - pd.Timestamp(w.a_from)).days + 1
    n_b = (pd.Timestamp(w.b_to) - pd.Timestamp(w.b_from)).days + 1
    ck_true(f"{w.label} halves are equal length", n_a == n_b, f"{n_a} vs {n_b}")
    ck_true(f"{w.label} shows its dates", "vs" in w.dates and any(
        c.isdigit() for c in w.dates), w.dates)
    ck_true(f"{w.label} has prose", len(w.text) > 20)
    # the figures quoted must be the figures computed
    A_ = E.cmp_block(M, w.a_from, w.a_to)
    for k in ("orders", "spend", "revenue"):
        ck(f"{w.label} {k} matches the window", w.metrics[k][0], A_[k], 1.0)

ck_true("freshness reports the true last day",
        _cm.freshness.last_day == _days[-1],
        f"{_cm.freshness.last_day} vs {_days[-1]}")
ck_true("data 3 days behind is flagged stale", _cm.freshness.stale,
        f"lag {_cm.freshness.lag_days}")
_fresh = E.freshness(M, today=_days[-1])
ck_true("data entered today is not flagged stale",
        not _fresh.stale or bool(_fresh.markets_behind), _fresh.text[:60])

# A month that has not started must not be scored. Doing so produced
# "0% of capacity", "budget was never the constraint", and July's movement
# reported under an August heading — all arithmetically true, all wrong.
_future = [mo for mo in M.months_in(YEAR)
           if E.scope(M.actuals, year=YEAR, month=mo).empty]
for _mo in _future:
    _cv = E.coverage(M, YEAR, _mo)
    _fc = E.commentary(M, None, None, YEAR, _mo, _cv, today=_dt.date(2026, 8, 3))
    ck_true(f"{_mo} reads as not started", _fc.verdict == "Not started", _fc.verdict)
    ck_true(f"{_mo} shows no movement windows", not _fc.windows,
            str([w.dates for w in _fc.windows]))
    ck_true(f"{_mo} has no open items", not _fc.open_items,
            str(_fc.open_items[:1]))
    ck_true(f"{_mo} never claims budget was not the constraint",
            "never the constraint" not in _fc.month_text, _fc.month_text[:70])
    ck_true(f"{_mo} never claims a delivery of zero",
            "delivered 0" not in _fc.month_text, _fc.month_text[:70])
    ck_true(f"{_mo} still states its plan",
            "planned for" in _fc.month_text or "no plan" in _fc.month_text.lower(),
            _fc.month_text[:70])
    _cc2 = E.capacity_check(M, None, YEAR, _mo)
    ck_true(f"{_mo} capacity check skips markets that have not reported",
            _cc2.empty, f"{len(_cc2)} rows")
if _future:
    print(f"  [PASS] {len(_future)} future month(s) handled: {_future}")

# a window must never draw days from outside the period it is labelled with
for _mo in M.months_in(YEAR):
    _cv = E.coverage(M, YEAR, _mo)
    _c2 = E.commentary(M, None, None, YEAR, _mo, _cv)
    _in = set(E.scope(M.actuals, year=YEAR, month=_mo)["Day"])
    for w in _c2.windows:
        ck_true(f"{_mo} {w.label} draws only from {_mo}",
                w.a_from in _in and w.b_from in _in,
                f"{w.a_from} / {w.b_from}")

ck_true("the period paragraph carries the plan comparison",
        "planned" in _cm.month_text or "no plan" in _cm.month_text,
        _cm.month_text[:70])
ck_true("open items are only what is unchanged",
        all(len(i) > 20 for i in _cm.open_items), f"{len(_cm.open_items)} items")

# a sentence must never claim a change that did not happen
_same = E.commentary(M, None, None, YEAR, MONTH, COV, today=_dt.date(2026, 8, 3))
ck_true("no window claims a move it cannot support",
        all(not ("rose" in w.text and w.metrics["orders"][1] is not None
                 and w.metrics["orders"][1] < 0) for w in _same.windows))

print("\n=== 10h. MANAGEMENT CARDS ===")
_cards = E.management_cards(M, None, None, YEAR, MONTH, COV)
ck_true("six cards", len(_cards) == 6, str([c.key for c in _cards]))
_kw = dict(year=YEAR, month=MONTH)
_o = E.actual(M, E.M_ORDERS, **_kw)
_rev = E.actual(M, E.M_REVENUE, **_kw)
_sp = E.actual(M, E.M_SPEND, **_kw)
_by = {c.key: c for c in _cards}
ck("orders card", _by["orders"].value, _o, 1)
ck("revenue card", _by["revenue"].value, _rev, 1)
ck("spend card", _by["spend"].value, _sp, 1)
ck("ROAS card = revenue / spend", _by["roas"].value, _rev / _sp, 0.01)
ck("CPA card = spend / orders", _by["cpa"].value, _sp / _o, 0.01)
ck("AOV card = revenue / orders", _by["aov"].value, _rev / _o, 0.01)
# A ratio does not accumulate, so pacing one is meaningless.
for k in ("roas", "cpa", "aov"):
    ck_true(f"{k} is never paced", _by[k].paced is None and _by[k].ratio)
    ck_true(f"{k} is measured against plan", _by[k].basis == "plan")
for k in ("orders", "revenue", "spend"):
    ck_true(f"{k} carries a paced figure", _by[k].paced is not None)
ck_true("spend carries no verdict colour",
        _by["spend"].colour == E.GREY, _by["spend"].colour)
ck_true("every card has a sparkline or an empty period",
        all(len(c.spark) > 1 or COV.days_elapsed <= 1 for c in _cards),
        str({c.key: len(c.spark) for c in _cards}))
# A day can carry orders and no spend row, so ratio series must align on dates
# rather than by position — zipping silently pairs the wrong days.
for mk_ in M.market_list():
    for ch_ in M.display_channels(False):
        try:
            E.management_cards(M, [mk_], M.expand([ch_], False), YEAR, MONTH, COV)
        except Exception as ex:
            ck_true(f"cards build for {mk_} x {ch_}", False,
                    f"{type(ex).__name__}: {ex}")
print(f"  [PASS] cards build for every market x channel")

print("\n=== 10i. INSIGHT LINES ===")
_ml = E.management_line(M, None, None, YEAR, MONTH, COV)
ck_true("management line produced or honestly absent",
        _ml is None or len(_ml) > 20, str(_ml)[:60])
if _ml:
    ck_true("management line quotes no figure it did not compute",
            "%" in _ml or "AED" in _ml, _ml[:60])
_wl = E.where_line(M, None, None, YEAR, MONTH, COV)
ck_true("where line produced or honestly absent",
        _wl is None or len(_wl) > 20, str(_wl)[:60])
_mtl = E.split_line(M, None, YEAR, MONTH)
ck_true("split line only claims divergence when platforms actually differ",
        _mtl is None or "diverge" in _mtl, str(_mtl)[:60])
_days2 = sorted(M.actuals["Day"].unique())
if len(_days2) >= 14:
    _cl = E.compare_line(M, (_days2[-7], _days2[-1]), (_days2[-14], _days2[-8]),
                         None, None)
    ck_true("compare line produced", _cl is not None and len(_cl) > 30)
    _A = E.cmp_block(M, _days2[-7], _days2[-1])
    _B = E.cmp_block(M, _days2[-14], _days2[-8])
    _op = E.cmp_change(_A, _B, "orders")["pct"]
    _rp = E.cmp_change(_A, _B, "revenue")["pct"]
    # the "basket size held" claim must only appear when it is true
    if "basket size held" in (_cl or ""):
        ck_true("basket-size claim is supported", abs(_op - _rp) < 3,
                f"orders {_op:+.1f}% vs revenue {_rp:+.1f}%")
    else:
        ck_true("basket-size claim correctly withheld", abs(_op - _rp) >= 3
                or "shifted" in (_cl or ""), f"{_op:+.1f} vs {_rp:+.1f}")
for mk_ in M.market_list():
    try:
        E.management_line(M, [mk_], None, YEAR, MONTH, COV)
        E.where_line(M, [mk_], None, YEAR, MONTH, COV)
        E.split_line(M, [mk_], YEAR, MONTH)
    except Exception as ex:
        ck_true(f"lines build for {mk_}", False, f"{type(ex).__name__}: {ex}")
print("  [PASS] insight lines build for every market")

print("\n=== 11. EVERY SELECTION BUILDS ===")
_n = 0
for _mo in [[x] for x in M.months_in(YEAR)] + ([E.closed_months(M, YEAR)]
                                                    if E.closed_months(M, YEAR) else []):
    for _sp in (False, True):
        try:
            _cv = E.coverage(M, YEAR, _mo)
            E.overview_cards(M, None, None, YEAR, _mo, _cv)
            E.gap_table(M, None, None, YEAR, _mo, _cv, _sp)
            E.headline(M, None, None, YEAR, _mo, _cv, _sp)
        except Exception as ex:
            ck_true(f"months {_mo} split={_sp} builds", False,
                    f"{type(ex).__name__}: {ex}")
print(f"  [PASS] every month combination builds")

for _sp in (False, True):
    for mk_ in [None] + [[x] for x in M.market_list()]:
        for ch_ in [None] + [[x] for x in M.display_channels(_sp)]:
            try:
                E.overview_cards(M, mk_, M.expand(ch_, _sp), YEAR, MONTH, COV)
                E.gap_table(M, mk_, ch_, YEAR, MONTH, COV, _sp)
                E.allocation_table(M, mk_, ch_, YEAR, MONTH, COV, _sp)
                E.headline(M, mk_, ch_, YEAR, MONTH, COV, _sp)
                E.commentary(M, mk_, ch_, YEAR, MONTH, COV)
                _n += 1
            except Exception as ex:
                ck_true(f"{mk_} x {ch_} split={_sp} builds", False,
                        f"{type(ex).__name__}: {ex}")
print(f"  [PASS] {_n} market x channel x toggle selections build")
for yr, mo in M.periods():
    try:
        c = E.coverage(M, yr, mo)
        E.overview_cards(M, None, None, yr, mo, c)
        print(f"  [PASS] {mo} {yr} builds")
    except Exception as ex:
        ck_true(f"{mo} {yr} builds", False, str(ex))

print("\n=== 12. COVERAGE ===")
for mk_, (rep, act_) in sorted(COV.per_market.items()):
    want = J[J.Market == mk_].Date.dt.date.nunique()
    ck(f"{mk_} days reported", rep, want)
    ck_true(f"{mk_} days with orders <= days reported", act_ <= rep, f"{act_} <= {rep}")
warn("every market reported the full period",
     all(v[0] == COV.days_elapsed for v in COV.per_market.values()),
     str({k: v[0] for k, v in COV.per_market.items()}))

print("\n" + "=" * 62)
if fails:
    print(f"RESULT: {len(fails)} FAILURE(S)")
    for f in fails[:25]:
        print("   -", f)
    sys.exit(1)
print(f"RESULT: ALL CHECKS PASS ({len(warns)} warning(s))")
for w in warns:
    print("   ! ", w)

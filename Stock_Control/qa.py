"""
QA harness for Inripe Inventory Control.

Checks the identities that must hold for ANY dataset — no hardcoded numbers,
so it works on the demo file and on your real data.

    python3 qa.py                       # checks INRIPE_Stock_Entry_v1.xlsx
    python3 qa.py OTHER_FILE.xlsx
"""
import sys, pandas as pd, numpy as np, engine

FILE = sys.argv[1] if len(sys.argv) > 1 else "INRIPE_Stock_Entry_v1.xlsx"
P, F = [], []
def ck(name, got, want, tol=1e-6):
    ok = abs(float(got) - float(want)) <= tol
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {name}: got {got:,.2f}, want {want:,.2f}")
def ck0(name, count):
    ok = int(count) == 0
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {name}: {int(count)} offending rows")

ship, moves, count, cfg, errs = engine.load(FILE)
as_of = cfg["as_of"]
st = engine.stock_by_item(ship, moves, as_of)
cl = engine.clearance_by_shipment(ship, moves, as_of, cfg)
cp = engine.courier_positions(ship, moves, as_of, cfg)
vr = engine.variance(st, count)
q = lambda t: moves.loc[moves.Movement == t, "Qty"].sum()
o = lambda t: moves.loc[moves.Movement == t, "Orders"].sum()

print(f"File: {FILE}")
print(f"  {len(ship):,} shipment lines · {len(moves):,} moves · {len(count):,} counts · "
      f"{ship['Shipment ID'].nunique()} shipments · as of {as_of:%d %b %Y}\n")

print("A. DATA ENTRY")
ck0("every row passes its Excel check", len(errs))
ck0("no move references a missing shipment",
    (~moves["Shipment"].isin(ship["Shipment ID"])).sum())
ck0("no move dated before its shipment arrived",
    (moves["Date"] < moves["Shipment"].map(
        ship.groupby("Shipment ID")["Arrival Date"].min())).sum())

print("B. SHIPPED = CUSTOMS + RECEIVED")
ck("customs + received equals shipped", q("Not received") + q("Received"),
   st["Shipped Qty"].sum())
ck0("no shipment line with an unexplained gap", (st["ShipDiff"].round(6) != 0).sum())

print("C. STORE BALANCE")
ck("store stock equals the raw movement maths", st.Store.sum(),
   q("Received") - q("Scrap") + q("Return to Saleable") + q("Count Adjustment") - q("To Courier"))
ck0("QA column non-zero on any row", (st["QA"].round(6) != 0).sum())
ck0("negative store stock", (st["Store"] < 0).sum())

print("D. COURIER BALANCE")
ck("to courier", cp.ToCourier.sum() if len(cp) else 0, q("To Courier"))
ck("delivered", cp.Delivered.sum() if len(cp) else 0, q("Delivered"))
ck("returned", cp.Returned.sum() if len(cp) else 0, q("Returned"))
ck("held = out - delivered - returned", cp.Held.sum() if len(cp) else 0,
   q("To Courier") - q("Delivered") - q("Returned"))
ck0("negative courier holding", (cp["Held"] < 0).sum() if len(cp) else 0)

print("E. RETURN LOOP")
ck("returned = back to stock + scrapped", q("Returned"),
   q("Return to Saleable") + q("Return to Scrap"))

print("G. CLEARANCE")
ck("received per shipment ties to the log", cl.Received.sum(), q("Received"))
ck("outstanding = received - delivered - scrap + count adjustments", cl.Outstanding.sum(),
   q("Received") - q("Delivered") - q("Scrap") - q("Return to Scrap") + q("Count Adjustment"))
ck("outstanding = store + with courier", cl.Outstanding.sum(),
   st.Store.sum() + (cp.Held.sum() if len(cp) else 0))
ck0("clearance span before arrival", (cl["Span"].dropna() < 0).sum())

print("H. AGING")
ck0("negative stock age", (st["AgeDays"] < 0).sum())
returned_keys = set(zip(moves.loc[moves.Movement == "Return to Saleable", "Shipment"],
                        moves.loc[moves.Movement == "Return to Saleable", "Item"]))
_age_ok = st.apply(lambda r: r["AgeDays"] == (as_of - r["Arrival Date"]).days, axis=1)
_is_ret = st.apply(lambda r: (r["Shipment"], r["Item"]) in returned_keys, axis=1)
bad_age = int((_is_ret & ~_age_ok).sum())
ck0("returned stock whose age clock was reset", bad_age)

print("I. PHYSICAL COUNT")
if len(vr):
    ck("variance = physical - system", vr["Var"].sum(),
       vr["Physical"].sum() - vr["System"].sum())
else:
    P.append("PASS  no counts recorded, nothing to check")

print("J. MARKET SPLIT")
tot = 0
for m in ship["Market"].dropna().unique():
    s2 = ship[ship.Market == m]; m2 = moves[moves.Market == m]
    a = engine.stock_by_item(s2, m2, as_of)
    c2 = engine.courier_positions(s2, m2, as_of, cfg)
    ck0(f"  {m}: QA breaks", (a["QA"].round(6) != 0).sum())
    ck0(f"  {m}: negative courier holding", (c2["Held"] < 0).sum() if len(c2) else 0)
    tot += a.Store.sum()
ck("market totals add up to the whole", tot, st.Store.sum())

print("K. TIME TRAVEL")
for back in (0, 3, 7, 14):
    d = as_of - pd.Timedelta(days=back)
    mm = moves[moves.Date <= d]
    a = engine.stock_by_item(ship, mm, d)
    c2 = engine.courier_positions(ship, mm, d, cfg)
    ck0(f"  as of {d:%d %b}: QA breaks", (a["QA"].round(6) != 0).sum())
    ck0(f"  as of {d:%d %b}: negative courier holding", (c2["Held"] < 0).sum() if len(c2) else 0)

print()
for line in F: print(line)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

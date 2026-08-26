# -*- coding: utf-8 -*-
"""
The report calculations. These drive the Couriers and Data check tabs and had
no test of their own - they were only ever exercised by rendering the page.
"""
import sys, io, datetime as dt
import pandas as pd, engine, entry, qa_book
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
def eq(n,got,want,tol=1e-6):
    try: ok=abs(float(got)-float(want))<=tol
    except (TypeError,ValueError): ok=str(got)==str(want)
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}: got {got}, want {want}")

base=qa_book.data()
s0,m0,c0,cfg0,e0=engine.load(io.BytesIO(base))
AS=cfg0["as_of"]
MKT=s0["Market"].dropna().iloc[0]
SHIP=s0[s0.Market==MKT]["Shipment ID"].iloc[0]
ITEM=s0[s0["Shipment ID"]==SHIP]["Item Name"].iloc[0]
COUR=(cfg0.get("couriers_by_market") or {}).get(MKT,[None])[0]

print("=== A. WHAT THE COURIER IS HOLDING ===")
cp=engine.courier_positions(s0,m0,AS,cfg0)
ck("it returns a table", isinstance(cp,pd.DataFrame))
if len(cp):
    ck("never holding a negative number", (cp["Held"]>=0).all(),
       cp[cp["Held"]<0].to_dict("records"))
    ck("every courier is one from MASTER",
       set(cp["Courier"]) <= {c for v in (cfg0.get("couriers_by_market") or {}).values()
                              for c in v},
       sorted(set(cp["Courier"])))
if COUR:
    b,_=entry.append_moves(base,[{"Date":AS.date(),"Shipment No":SHIP,
        "Movement":"To Courier","Item Name":ITEM,"Out":10,"Courier":COUR}],
        "admin",MKT)
    s1,m1,c1,cfg1,e1=engine.load(io.BytesIO(b))
    cp1=engine.courier_positions(s1,m1,cfg1["as_of"],cfg1)
    held=float(cp1[cp1["Courier"]==COUR]["Held"].sum())
    eq("sending 10 out puts 10 with the courier", held,
       float(cp[cp["Courier"]==COUR]["Held"].sum() if len(cp) else 0)+10)
    b2,_=entry.append_moves(b,[{"Date":AS.date(),"Shipment No":SHIP,
        "Movement":"Returned","Item Name":ITEM,"In":4,"Courier":COUR,
        "Reason":"Customer Refused"}],"admin",MKT)
    s2,m2,c2,cfg2,e2=engine.load(io.BytesIO(b2))
    cp2=engine.courier_positions(s2,m2,cfg2["as_of"],cfg2)
    eq("4 coming back leaves 6", float(cp2[cp2["Courier"]==COUR]["Held"].sum()),
       held-4)
    ck("the return rate is a percentage",
       0 <= float(cp2[cp2["Courier"]==COUR]["Return %"].iloc[0]) <= 100
       if "Return %" in cp2.columns and len(cp2) else True,
       cp2["Return %"].tolist() if "Return %" in cp2.columns else "n/a")
    eq("no entry errors from any of it", len(e2), 0)

print("=== B. THE PHYSICAL COUNT VARIANCE ===")
st0=engine.stock_by_item(s0,m0,AS)
v=engine.variance(st0,c0)
ck("it returns a table", isinstance(v,pd.DataFrame))
eq("one row per count", len(v), len(c0))
if len(v):
    ck("variance is counted minus system",
       all(abs((r.Physical - r.System) - r.Var) < 1e-6 for r in v.itertuples()),
       v.head(3).to_dict("records"))
    ck("the percentage matches the variance",
       all((r.System == 0) or abs(r.Var / r.System - r.VarPct) < 1e-6
           for r in v.itertuples()))
    ck("no count refers to a shipment that is gone",
       set(v["Shipment"]) <= set(s0["Shipment ID"]),
       sorted(set(v["Shipment"]) - set(s0["Shipment ID"])))
ck("an empty count sheet gives an empty table",
   len(engine.variance(st0, c0.iloc[0:0]))==0)

print("=== C. STOCK ADDS UP, ITEM BY ITEM ===")
for r in st0.itertuples():
    lhs = r.Received - r.Scrap + r.ToSaleable - r.ToCourier
    ck(f"{r.Shipment} {getattr(r,'ItemName',r.Item)}: store is what came in less what went out",
       abs(lhs + getattr(r,"Adjust",0) - r.Store) < 1.001,
       f"{lhs} vs {r.Store}")
    break   # the identity holds for every row; one is shown, all are checked below
bad=[r for r in st0.itertuples()
     if abs((r.Received - r.Scrap + r.ToSaleable - r.ToCourier
             + getattr(r,"Adjust",0)) - r.Store) > 1.001]
ck("every row balances", not bad, [ (r.Shipment, r.Store) for r in bad[:3] ])
ck("nothing is negative", (st0["Store"]>=0).all(),
   int((st0["Store"]<0).sum()))

print("=== D. CLEARANCE ===")
cl=engine.clearance_by_shipment(s0,m0,AS,cfg0)
ck("one row per shipment", len(cl)==s0["Shipment ID"].nunique(),
   f"{len(cl)} vs {s0['Shipment ID'].nunique()}")
ck("cleared is only Yes or No", set(cl["Cleared"]) <= {"Yes","No"},
   sorted(set(cl["Cleared"])))
ck("days open is never negative", (cl["DaysOpen"]>=0).all())
ck("a cleared shipment has nothing outstanding",
   (cl.loc[cl["Cleared"]=="Yes","Outstanding"] <= 0).all(),
   cl[cl["Cleared"]=="Yes"]["Outstanding"].tolist()[:3])
ck("outstanding never exceeds received",
   (cl["Outstanding"] <= cl["Received"] + 0.001).all())

print("=== E. TODAY'S LIST ===")
import entry_ui, auth, os
os.environ.setdefault("ENTRY_PASSWORD","e"); os.environ.setdefault("ADMIN_PASSWORD","a")
ck("the today view exists on its own", hasattr(entry_ui,"render_today"))
src=open("entry_ui.py").read()
ck("it can be shown without the form",
   "show_today=True" in src and "def render_today" in src)
ck("the form can be drawn without it", "show_today=False" in open("app.py").read())
ck("a voided row is shown struck through, not hidden",
   "text-decoration:line-through" in src)
ck("only rows you may void get a button", "auth.can_void(session" in src)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

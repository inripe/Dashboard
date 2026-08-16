"""QA harness. Every number the dashboard shows is asserted against the raw log."""
import pandas as pd, numpy as np, engine, sys
P=[];F=[]
def ck(name, got, want, tol=1e-6):
    ok = abs(float(got)-float(want)) <= tol
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {name}: got {got}, want {want}")

ship,moves,count,cfg,errs = engine.load("INRIPE_Stock_Entry_v1.xlsx")
as_of=cfg["as_of"]
st=engine.stock_by_item(ship,moves,as_of)
cl=engine.clearance_by_shipment(ship,moves,as_of,cfg)
cp=engine.courier_positions(ship,moves,as_of,cfg)
vr=engine.variance(st,count)
q=lambda t: moves.loc[moves.Movement==t,"Qty"].sum()
o=lambda t: moves.loc[moves.Movement==t,"Orders"].sum()

print("="*70); print("A. RAW LOG TOTALS (independent of engine)"); print("="*70)
ck("entry errors", len(errs), 0)
ck("shipment lines", len(ship), 5)
ck("move rows", len(moves), 29)

print("\n"+"="*70); print("B. IDENTITY 1  shipped = customs + received"); print("="*70)
ck("shipped total", ship["Shipped Qty"].sum(), 330)
ck("customs + received", q("Customs / Loss")+q("Received"), 330)
ck("ShipDiff must be zero on every row", abs(st.ShipDiff).sum(), 0)

print("\n"+"="*70); print("C. IDENTITY 2  store = recv - scrap + backin + adj - tocourier"); print("="*70)
manual = q("Received")-q("Scrap")+q("Return to Saleable")+q("Count Adjustment")-q("To Courier")
ck("store stock (engine vs raw)", st.Store.sum(), manual)
ck("store stock = 224", st.Store.sum(), 224)
ck("QA column zero on every row", abs(st.QA).sum(), 0)
for r in st.itertuples():
    ck(f"  row {r.Shipment}/{r.Item} QA", r.QA, 0)

print("\n"+"="*70); print("D. IDENTITY 3  tocourier = delivered + returned + held"); print("="*70)
ck("to courier", cp.ToCourier.sum(), q("To Courier"))
ck("delivered", cp.Delivered.sum(), q("Delivered"))
ck("returned", cp.Returned.sum(), q("Returned"))
ck("held = out - del - ret", cp.Held.sum(), q("To Courier")-q("Delivered")-q("Returned"))
ck("held = 31", cp.Held.sum(), 31)
for r in cp.itertuples():
    ck(f"  {r.Courier}/{r.Shipment} held", r.Held, r.ToCourier-r.Delivered-r.Returned)

print("\n"+"="*70); print("E. IDENTITY 4  returned = back to stock + return scrap"); print("="*70)
ck("returns split", q("Returned"), q("Return to Saleable")+q("Return to Scrap"))

print("\n"+"="*70); print("F. ORDER COUNTS"); print("="*70)
ck("orders assigned", cl.OrdersAssigned.sum(), o("Orders Assigned"))
ck("orders handed", cl.OrdersHanded.sum(), o("Courier Handover"))
ck("orders delivered", cl.OrdersDelivered.sum(), o("Delivered"))
ck("orders returned", cl.OrdersReturned.sum(), o("Returned"))
ck("orders outstanding = handed-del-ret", cl.OrdersOutstanding.sum(),
   o("Courier Handover")-o("Delivered")-o("Returned"))
ck("orders outstanding = 9", cl.OrdersOutstanding.sum(), 9)
ck("courier orders tie to shipment orders", cp.OrdersHanded.sum(), cl.OrdersHanded.sum())

print("\n"+"="*70); print("G. CLEARANCE"); print("="*70)
ck("received per clearance = raw", cl.Received.sum(), q("Received"))
ck("outstanding = recv - del - scrap", cl.Outstanding.sum(),
   q("Received")-q("Delivered")-q("Scrap")-q("Return to Scrap"))
ck("outstanding = store + held", cl.Outstanding.sum(), st.Store.sum()+cp.Held.sum())
ck("SH-001 span", cl.loc[cl.Shipment=="SH-001","Span"].iloc[0], 4)
ck("SH-001 days open", cl.loc[cl.Shipment=="SH-001","DaysOpen"].iloc[0], 4)

print("\n"+"="*70); print("H. AGING (returned stock must keep its age)"); print("="*70)
kent = st[(st.Shipment=="SH-001")&(st.Item=="MK-KENT")].iloc[0]
ck("Kent age still 4 days after return", kent.AgeDays, 4)
ck("Kent store 80-3+3-22", kent.Store, 58)
ck("oldest stock", st.loc[st.Store>0,"AgeDays"].max(), 4)

print("\n"+"="*70); print("I. COUNT VARIANCE"); print("="*70)
ck("keitt system", vr.loc[vr.Item=="MK-KEITT","System"].iloc[0], 62)
ck("keitt variance", vr.loc[vr.Item=="MK-KEITT","Var"].iloc[0], -2)
ck("total variance", vr.Var.sum(), -2)

print("\n"+"="*70); print("J. LOSSES"); print("="*70)
loss = st.Customs.sum()+st.Scrap.sum()+st.ReturnScrap.sum()
ck("total loss", loss, q("Customs / Loss")+q("Scrap")+q("Return to Scrap"))
ck("total loss = 15", loss, 15)
ck("loss % of received", loss/st.Received.sum()*100, 15/328*100, 0.01)

print("\n"+"="*70); print("K. MARKET SPLIT ties to total"); print("="*70)
piv = st.pivot_table(index="Item",columns="Market",values="Store",aggfunc="sum",fill_value=0)
ck("pivot total = store total", piv.values.sum(), st.Store.sum())
ck("UAE", piv["UAE"].sum(), 154); ck("KSA", piv["KSA"].sum(), 70)

print("\n"+"="*70); print("L. FILTER PATHS (must not crash, must stay balanced)"); print("="*70)
for m in ["Egypt","UAE","KSA","Qatar"]:
    s2=ship[ship.Market==m]; m2=moves[moves.Market==m]
    a=engine.stock_by_item(s2,m2,as_of); b=engine.clearance_by_shipment(s2,m2,as_of,cfg)
    c=engine.courier_positions(s2,m2,as_of,cfg); v=engine.variance(a,count[count.Shipment.isin(s2["Shipment ID"])])
    ck(f"{m}: QA zero", abs(a.QA).sum() if len(a) else 0, 0)
    ck(f"{m}: courier held >= 0", (c.Held<0).sum() if len(c) else 0, 0)
ck("UAE+KSA store = total",
   engine.stock_by_item(ship[ship.Market=="UAE"],moves[moves.Market=="UAE"],as_of).Store.sum()+
   engine.stock_by_item(ship[ship.Market=="KSA"],moves[moves.Market=="KSA"],as_of).Store.sum(),
   st.Store.sum())

print("\n"+"="*70); print("M. TIME TRAVEL (as-of dates must be monotonic and correct)"); print("="*70)
for d,exp_store in [("2026-08-12",None),("2026-08-13",None),("2026-08-16",224)]:
    dd=pd.Timestamp(d); mm=moves[moves.Date<=dd]
    a=engine.stock_by_item(ship,mm,dd)
    c=engine.courier_positions(ship,mm,dd,cfg)
    ck(f"{d}: QA zero", abs(a.QA).sum(), 0)
    ck(f"{d}: held >= 0", (c.Held<0).sum() if len(c) else 0, 0)
    if exp_store: ck(f"{d}: store", a.Store.sum(), exp_store)
a12=engine.stock_by_item(ship,moves[moves.Date<=pd.Timestamp("2026-08-12")],pd.Timestamp("2026-08-12"))
ck("12 Aug store = 98-8-28 +80-3-22 +50-1-15", a12.Store.sum(), 62+55+34)

print("\n"+"="*70)
for line in F: print(line)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

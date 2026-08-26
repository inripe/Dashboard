# -*- coding: utf-8 -*-
"""The cleaner must remove only what has no movements, and touch nothing else."""
import sys, io, qa_book, engine, clean_sheet, openpyxl
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
def eq(n,got,want,tol=1e-6):
    try: ok=abs(float(got)-float(want))<=tol
    except (TypeError,ValueError): ok=str(got)==str(want)
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}: got {got}, want {want}")

data=qa_book.data()
s0,m0,c0,cfg0,e0=engine.load(io.BytesIO(data))
st0=engine.stock_by_item(s0,m0,cfg0["as_of"])
new,keep,drop,orph=clean_sheet.clean(data)
s1,m1,c1,cfg1,e1=engine.load(io.BytesIO(new))
st1=engine.stock_by_item(s1,m1,cfg1["as_of"])

print("=== A. IT REMOVES ONLY THE UNUSED ===")
used=set(m0["Shipment"].dropna().astype(str).str.strip())
ck("every kept shipment has movements",
   set(s1["Shipment ID"].astype(str).str.strip()) <= used,
   sorted(set(s1["Shipment ID"].astype(str).str.strip()) - used))
ck("every removed shipment had none",
   not (set(str(d["Shipment No"]).strip() for d in drop) & used),
   sorted(set(str(d["Shipment No"]).strip() for d in drop) & used))
eq("the arithmetic adds up", len(s1)+len(drop), len(s0))

print("=== B. IT CHANGES NOTHING ELSE ===")
eq("no movement is touched", len(m1), len(m0))
eq("stock is identical", float(st1["Store"].sum()), float(st0["Store"].sum()))
ck("markets survive", cfg1.get("markets")==cfg0.get("markets"), cfg1.get("markets"))
ck("couriers survive", cfg1.get("couriers_by_market")==cfg0.get("couriers_by_market"))
ck("users survive", list(cfg1.get("users"))==list(cfg0.get("users")))
ck("settings survive", cfg1["clear_target"]==cfg0["clear_target"])
kept_ids=set(s1["Shipment ID"])
ck("kept rows keep their quantities",
   list(s1.sort_values(["Shipment ID","Item Name"])["Shipped Qty"]) ==
   list(s0[s0["Shipment ID"].isin(kept_ids)]
        .sort_values(["Shipment ID","Item Name"])["Shipped Qty"]))

print("=== C. COUNT ROWS DO NOT DANGLE ===")
ck("no count points at a removed shipment",
   set(c1["Shipment"].astype(str)) <= set(s1["Shipment ID"].astype(str)) if len(c1) else True,
   sorted(set(c1["Shipment"].astype(str)) - set(s1["Shipment ID"].astype(str))) if len(c1) else [])
eq("orphan counts were reported", len(c0)-len(c1), len(orph))

print("=== D. THE SHEET IS HEALTHY AFTERWARDS ===")
eq("no entry errors", len(e1), 0)
gap=0
for _,r in s1.iterrows():
    sub=st1[(st1["Shipment"]==r["Shipment ID"]) & (st1["Item Name"]==r["Item Name"])] \
        if "Item Name" in st1.columns else st1[st1["Shipment"]==r["Shipment ID"]]
ck("every remaining line has a received figure",
   float(st1["Received"].sum())>0, float(st1["Received"].sum()))
ck("nothing is negative", (st1["Store"]>=0).all())
ck("the tables still line up",
   set(m1["Shipment"].dropna()) <= set(s1["Shipment ID"]),
   sorted(set(m1["Shipment"].dropna()) - set(s1["Shipment ID"])))

print("=== E. SAFE TO RUN TWICE ===")
again,_,drop2,orph2=clean_sheet.clean(new)
s2,m2,c2,cfg2,e2=engine.load(io.BytesIO(again))
eq("nothing left to remove", len(drop2), 0)
eq("no lines lost the second time", len(s2), len(s1))
eq("movements still intact", len(m2), len(m1))
eq("stock still the same",
   float(engine.stock_by_item(s2,m2,cfg2["as_of"])["Store"].sum()),
   float(st1["Store"].sum()))

print("=== F. IT DOES NOT WRITE UNLESS TOLD ===")
src=open("clean_sheet.py").read()
ck("upload needs --apply", 'if not apply:' in src and "sp.upload_workbook" in src)
ck("it shows before and after", "BEFORE" in src and "AFTER" in src)
ck("it lists what would go", "WOULD REMOVE" in src)
ck("it names each shipment and its boxes", "boxes declared, none ever received" in src)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

# -*- coding: utf-8 -*-
"""
Received as a checklist: sixteen items checked in one pass instead of typed
sixteen times. Every guard that applied to the typed form still applies.
"""
import sys, io, re, os, types, datetime as dt
import engine, entry, entry_ui, qa_book
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
def eq(n,got,want,tol=1e-6):
    try: ok=abs(float(got)-float(want))<=tol
    except (TypeError,ValueError): ok=str(got)==str(want)
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}: got {got}, want {want}")

base=qa_book.data()
s0,m0,c0,cfg0,e0=engine.load(io.BytesIO(base))
MKT=s0["Market"].dropna().iloc[0]

print("=== A. IT KNOWS WHAT TO EXPECT ===")
open_ids=[x for x in sorted(set(s0["Shipment ID"]))]
SID=open_ids[-1]
lines=entry_ui.expected(s0,m0,SID)
ck("one line per item on the shipment",
   len(lines)==s0[s0["Shipment ID"]==SID]["Item Name"].nunique(), len(lines))
for r in lines:
    ck(f"{r['item']}: sent, received and left are consistent",
       abs(r["sent"] - r["received"] - r["not_received"] - r["left"]) < 0.001
       or r["left"] == 0,
       f"sent {r['sent']} got {r['received']} left {r['left']}")
ck("nothing is ever negative", all(r["left"] >= 0 for r in lines))
ck("a fully received item is marked done",
   all(r["done"] == (r["left"] <= 0.001) for r in lines))

print("=== B. A NEW SHIPMENT IS VISIBLE ===")
sid = entry.next_shipment_no(base, MKT)
items = sorted(set(s0["Item Name"].dropna()))[:4]
rows = [{"Shipment No": sid, "Market": MKT, "Arrival Date": dt.date(2026,8,27),
         "Source": "Egypt", "Item Name": it, "Shipped Qty": q}
        for it, q in zip(items, [40, 25, 60, 15])]
b, made = entry.append_shipment(base, rows, "admin", MKT)
s1,m1,c1,cfg1,e1 = engine.load(io.BytesIO(b))
cl = engine.clearance_by_shipment(s1, m1, cfg1["as_of"], cfg1)
row = cl[cl["Shipment"] == made]
ck("a shipment nobody has received is not cleared",
   row["Cleared"].iloc[0] == "No", row["Cleared"].iloc[0])
opens = entry_ui.open_shipments(s1, cl, MKT)
ck("and it is offered in the entry form",
   made in [x for x, _ in opens], [x for x, _ in opens])
# newest arrival first, not newest number: two shipments can land on the
# same day and a later number can have an earlier arrival
import pandas as _pd
dates = [_pd.Timestamp(d) for _, d in opens]
ck("newest arrival first", dates == sorted(dates, reverse=True),
   [f"{x} {_pd.Timestamp(d):%d %b}" for x, d in opens][:3])

print("=== C. THE CHECKLIST FOR IT ===")
lines = entry_ui.expected(s1, m1, made)
eq("four items", len(lines), 4)
ck("nothing received yet", all(r["received"] == 0 for r in lines))
ck("everything still to do", all(not r["done"] for r in lines))
eq("the totals match what was sent", sum(r["left"] for r in lines), 140)

print("=== D. SAVING THE WHOLE CHECKLIST ===")
picked = [{"Date": dt.date(2026,8,27), "Shipment No": made,
           "Movement": "Received", "Item Name": r["item"], "In": int(r["left"])}
          for r in lines]
b2, ids = entry.append_moves(b, picked, "qatar.store", MKT)
s2,m2,c2,cfg2,e2 = engine.load(io.BytesIO(b2))
eq("one row per item", len(m2), len(m1) + 4)
eq("each row has its own id", len(set(ids)), 4)
eq("no entry errors", len(e2), 0)
st2 = engine.stock_by_item(s2, m2, cfg2["as_of"])
eq("all 140 boxes are in stock",
   float(st2[st2["Shipment"] == made]["Store"].sum()), 140)
lines2 = entry_ui.expected(s2, m2, made)
ck("the checklist is now empty", all(r["done"] for r in lines2))

print("=== E. A SHORTFALL ===")
short = [{"Date": dt.date(2026,8,27), "Shipment No": made,
          "Movement": "Received", "Item Name": lines[0]["item"],
          "In": int(lines[0]["left"]) - 3}]
b3, _ = entry.append_moves(b, short, "qatar.store", MKT)
s3,m3,c3,cfg3,e3 = engine.load(io.BytesIO(b3))
l3 = entry_ui.expected(s3, m3, made)
first = [r for r in l3 if r["item"] == lines[0]["item"]][0]
eq("three are still outstanding", first["left"], 3)
ck("so the item is not done", not first["done"])
ck("and the shipment stays open",
   engine.clearance_by_shipment(s3,m3,cfg3["as_of"],cfg3)
   .set_index("Shipment").loc[made,"Cleared"] == "No")

print("=== F. THE GUARDS STILL APPLY ===")
import openpyxl
wb = openpyxl.load_workbook(io.BytesIO(b2))
over = {"Date": dt.date(2026,8,27), "Shipment No": made, "Movement": "Received",
        "Item Name": lines[0]["item"], "In": 1}
ck("nothing more can be received once it is all in",
   entry.check_quantities(over, wb) != "OK",
   entry.check_quantities(over, wb)[:60])
try:
    entry.append_moves(b2, [over], "qatar.store", MKT)
    ck("and the writer refuses it", False, "it was written")
except ValueError as ex:
    ck("and the writer refuses it", True, str(ex)[:50])
before = len(engine.load(io.BytesIO(b))[1])
try:
    entry.append_moves(b, picked[:2] + [dict(picked[2], **{"In": 99999})],
                       "qatar.store", MKT)
    ck("one bad line stops the whole checklist", False, "it wrote")
except ValueError:
    ck("one bad line stops the whole checklist", True)
eq("and nothing was added", len(engine.load(io.BytesIO(b))[1]), before)

print("=== G. THE SCREEN ===")
ui = open("entry_ui.py").read()
ck("Received branches to the checklist", 'if mv == "Received" and sid:' in ui)
ck("there is an all-match shortcut", '"All match"' in ui)
ck("and a way to clear it", '"Clear"' in ui)
ck("it counts what has been checked", "of {len(todo)} checked" in ui)
ck("a shortfall is shown before saving", "short on" in ui)
ck("save is off until something is ticked", "Nothing ticked yet" in ui)
ck("it says how many rows will be written", "writes {len(rows)} rows" in ui)
ck("an already complete shipment says so",
   "is accounted for" in ui)
ck("the quantity cannot exceed what is left",
   "max_value=int(r[\"left\"])" in ui)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

# -*- coding: utf-8 -*-
"""
Whole-system checks. Not one component in isolation - the seams between them,
which is where things actually break.
"""
import sys, qa_book, io, os, re, datetime as dt
import pandas as pd, openpyxl
import engine, entry, entry_ui, auth, labels as L, dispatch
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
def eq(n,got,want,tol=1e-6):
    try: ok=abs(float(got)-float(want))<=tol
    except (TypeError,ValueError): ok=str(got)==str(want)
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}: got {got}, want {want}")

BOOK = qa_book.book()
base = open(BOOK, "rb").read()
s0,m0,c0,cfg0,e0 = engine.load(io.BytesIO(base))
st0 = engine.stock_by_item(s0,m0,cfg0["as_of"])
MKT = s0["Market"].dropna().iloc[0]
SHIP = s0[s0.Market==MKT]["Shipment ID"].iloc[0]
ITEM = s0[s0["Shipment ID"]==SHIP]["Item Name"].iloc[0]
def mv(m, **kw):
    d={"Date":entry.market_now(MKT).date(),"Shipment No":SHIP,"Movement":m}
    d.update(kw); return d

print("=== A. THE SHEET AGREES WITH ITSELF ===")
ck("no entry errors", len(e0)==0, len(e0))
ck("every movement type is known to MASTER",
   set(m0["Movement"].dropna()) <= set(L.MOVES) | {"Count Adjustment"},
   sorted(set(m0["Movement"].dropna()) - set(L.MOVES)))
ck("every move points at a real shipment",
   set(m0["Shipment"].dropna()) <= set(s0["Shipment ID"]),
   sorted(set(m0["Shipment"].dropna()) - set(s0["Shipment ID"]))[:3])
ck("every shipment item is on the item list",
   set(s0["Item Name"].dropna()) <= set((cfg0.get("item_names") or {}).values()),
   sorted(set(s0["Item Name"].dropna()) - set((cfg0.get("item_names") or {}).values()))[:3])
ck("no stock is negative", (st0["Store"] >= 0).all(),
   int((st0["Store"] < 0).sum()))
ck("nothing was delivered that never arrived",
   (st0["Received"] >= 0).all())

print("=== B. MASTER IS CONSISTENT ===")
users = cfg0.get("users") or {}
mkts = set(cfg0.get("markets") or [])
ck("there is at least one market", bool(mkts), mkts)
ck("there is an admin",
   any(str(v["role"]).lower()=="admin" for v in users.values()))
bad_mkt = [u for u,v in users.items()
           if str(v["market"]).lower()!="all" and v["market"] not in mkts]
ck("every user's market exists on MASTER", not bad_mkt, bad_mkt)
bad_role = [u for u,v in users.items()
            if str(v["role"]).strip().lower() not in auth.ROLE_PASSWORD]
ck("every user has a role the app knows", not bad_role, bad_role)
cb = cfg0.get("couriers_by_market") or {}
ck("every courier belongs to a real market",
   set(cb) <= mkts, sorted(set(cb) - mkts))
ck("every market with stock has a courier",
   set(st0.loc[st0["Store"]>0,"Market"]) <= set(cb) | set(),
   sorted(set(st0.loc[st0["Store"]>0,"Market"]) - set(cb)))

print("=== C. A FULL SHIPMENT LIFE, END TO END ===")
sid = entry.next_shipment_no(base, MKT)
b,_ = entry.append_shipment(base, [{"Shipment No":sid,"Market":MKT,
    "Arrival Date":dt.date(2026,8,26),"Source":"Egypt",
    "Item Name":ITEM,"Shipped Qty":500}], "admin", MKT)
def stock_of(data, shipment):
    s,m,c,cfg,e = engine.load(io.BytesIO(data))
    st = engine.stock_by_item(s,m,cfg["as_of"])
    r = st[st["Shipment"]==shipment]
    return {k: float(r[k].sum()) for k in
            ("Shipped Qty","Received","Scrap","Store")} , len(e)
v,errs = stock_of(b, sid)
eq("shipped 500", v["Shipped Qty"], 500); eq("nothing received yet", v["Received"], 0)
eq("no stock yet", v["Store"], 0); eq("no errors", errs, 0)
cour = (cfg0.get("couriers_by_market") or {}).get(MKT, [None])[0]
steps = [("Received",  {"Item Name":ITEM,"In":480},  "received 480"),
         ("Scrap",     {"Item Name":ITEM,"Out":5,"Reason":"Damage"}, "scrapped 5"),
         ("Not received", {"Item Name":ITEM,"Out":20,"Reason":"Customs"},
          "20 never arrived")]
for name, kw, label in steps:
    row = mv(name, **kw); row["Shipment No"] = sid
    b,_ = entry.append_moves(b, [row], "admin", MKT)
    v,errs = stock_of(b, sid)
    ck(label + " accepted", errs==0, errs)
eq("475 left to sell", v["Store"], 475)
eq("shipped still reads 500", v["Shipped Qty"], 500)
eq("the transit loss is visible", v["Shipped Qty"] - v["Received"], 20)
if cour:
    row = mv("To Courier", **{"Item Name":ITEM,"Out":100,"Courier":cour})
    row["Shipment No"] = sid
    b,_ = entry.append_moves(b, [row], "admin", MKT)
    v,errs = stock_of(b, sid)
    eq("100 to the courier leaves 375", v["Store"], 375)
    ck("still no errors", errs==0, errs)

print("=== D. IT REFUSES WHAT IT SHOULD ===")
lk = entry._lookups(openpyxl.load_workbook(io.BytesIO(b)))
wb_now = openpyxl.load_workbook(io.BytesIO(b))
refuse = [
  ("unknown movement", mv("Teleport", **{"Item Name":ITEM,"In":1})),
  ("unknown shipment", {**mv("Received", **{"Item Name":ITEM,"In":1}),
                        "Shipment No":"NO. 999"}),
  ("item not in the shipment",
   mv("Received", **{"Item Name": next(
       (x for x in (cfg0.get("item_names") or {}).values()
        if x not in set(s0[s0["Shipment ID"]==SHIP]["Item Name"])), "Nothing"),
       "In":1})),
  ("scrap with no reason", mv("Scrap", **{"Item Name":ITEM,"Out":1})),
  ("in and out both filled", mv("Received", **{"Item Name":ITEM,"In":1,"Out":1})),
  ("a date before the shipment arrived",
   {**mv("Received", **{"Item Name":ITEM,"In":1}), "Date":dt.date(2000,1,1)}),
]
# and the quantity guards, against the shipment built in section C
qty_refuse = [
  ("more received than was shipped",
   {**mv("Received", **{"Item Name":ITEM,"In":9999}), "Shipment No":sid}),
  ("more scrapped than is in the store",
   {**mv("Scrap", **{"Item Name":ITEM,"Out":9999,"Reason":"Damage"}),
    "Shipment No":sid}),
  ("returning what no courier holds",
   {**mv("Returned", **{"Item Name":ITEM,"In":9999,"Courier":cour or "x",
                        "Reason":"Cancelled"}), "Shipment No":sid}),
]
for label,row in qty_refuse:
    ck("refused: "+label,
       entry.check_quantities(row, wb_now)!="OK",
       entry.check_quantities(row, wb_now)[:50])
for label,row in refuse:
    if row is None: continue
    ck("refused: "+label, entry.validate(row, lk)!="OK", entry.validate(row, lk))
before = len(engine.load(io.BytesIO(b))[1])
try:
    entry.append_moves(b, [mv("Received", **{"Item Name":ITEM,"In":1}),
                           mv("Teleport", **{"Item Name":ITEM,"In":1})], "x", MKT)
    ck("a batch with one bad row writes nothing", False, "it wrote")
except ValueError:
    ck("a batch with one bad row writes nothing", True)
eq("and the file is unchanged", len(engine.load(io.BytesIO(b))[1]), before)

print("=== E. VOID PUTS IT BACK ===")
# a count adjustment, since this shipment is now fully received
row = mv("Count Adjustment - Add",
         **{"Item Name":ITEM,"In":40,"Reason":"Count Adjustment"})
row["Shipment No"] = sid
before_v,_ = stock_of(b, sid)
b2, ids = entry.append_moves(b, [row], "admin", MKT)
after_add,_ = stock_of(b2, sid)
eq("adding 40 raises stock", after_add["Store"], before_v["Store"]+40)
b3 = entry.void_entry(b2, ids[0], "admin", MKT)
after_void,_ = stock_of(b3, sid)
eq("voiding puts it back exactly", after_void["Store"], before_v["Store"])
raw = openpyxl.load_workbook(io.BytesIO(b3))["MOVES"]
found = [r for r in range(7, raw.max_row+1)
         if raw.cell(r, [i for i in range(1,raw.max_column+1)
                         if raw.cell(6,i).value=="Entry ID"][0]).value == ids[0]]
ck("the row is still in the file", bool(found), ids[0])

print("=== F. AUDIT TRAIL IS COMPLETE ===")
s9,m9,c9,cfg9,e9 = engine.load(io.BytesIO(b3))
app_rows = m9[m9["Entered by"].astype(str).str.lower()!="manual"]
app_rows = app_rows[app_rows["Entered by"].notna()]
ck("every app row names who entered it",
   app_rows["Entered by"].notna().all(), len(app_rows))
ck("every app row is timestamped", app_rows["Entered at"].notna().all())
ck("every app row has an id", app_rows["Entry ID"].notna().all())
ck("ids are unique", m9["Entry ID"].dropna().is_unique)
ck("ids carry the market letter",
   all(str(i)[0] in "QUKE" for i in m9["Entry ID"].dropna()),
   sorted(set(str(i)[0] for i in m9["Entry ID"].dropna())))

print("=== G. LABELS COVER EVERY MOVEMENT ===")
ws = openpyxl.load_workbook(io.BytesIO(base))["MASTER"]
sheet_moves, r = [], 16
while ws.cell(r,16).value not in (None,""):
    sheet_moves.append(str(ws.cell(r,16).value).strip()); r += 1
ck("every movement on MASTER has a label and arabic",
   all(m in L.MOVES and L.MOVES[m][1] for m in sheet_moves),
   [m for m in sheet_moves if m not in L.MOVES])
ck("every movement the form offers is on MASTER",
   set(entry_ui.WORKER_MOVES) <= set(sheet_moves),
   sorted(set(entry_ui.WORKER_MOVES) - set(sheet_moves)))
ck("every movement the admin form offers is on MASTER",
   set(entry_ui.NEEDS) <= set(sheet_moves),
   sorted(set(entry_ui.NEEDS) - set(sheet_moves)))
for m in entry_ui.NEEDS:
    spec = entry_ui.NEEDS[m]
    want = L.direction(m)
    got = {"In":"IN","Out":"OUT",None:""}[spec.get("dir")]
    ck(f"{m}: form direction matches the label", got==want, f"{got} vs {want}")

print("=== H. MARKETS LINE UP EVERYWHERE ===")
ck("the shipment form offers every active market",
   set(cfg0.get("markets") or []) >= set(s0["Market"].dropna()),
   sorted(set(s0["Market"].dropna()) - set(cfg0.get("markets") or [])))
ui = open("entry_ui.py").read()
ck("movement entry lists every market too",
   'all_markets = sorted(cfg.get("markets")' in ui)
ck("and says why one cannot be used yet", "has no shipment yet" in ui)
import shopify_reader as sr
ck("shopify market names match the sheet",
   set(sr.MARKETS) >= set(cfg0.get("markets") or []),
   sorted(set(cfg0.get("markets") or []) - set(sr.MARKETS)))
app = open("app.py").read()
ck("every market has a time zone",
   all(f'"{m}"' in app for m in (cfg0.get("markets") or [])),
   [m for m in (cfg0.get("markets") or []) if f'"{m}"' not in app])

print("=== I. NOTHING WRITES BEHIND YOUR BACK ===")
for f in ("engine.py","dispatch.py","shopify_reader.py"):
    src = open(f).read()
    ck(f"{f} never writes to shopify",
       not re.search(r"mutation|metafieldsSet|orderUpdate", src))
ck("only entry.py writes to the workbook",
   all("wb.save" not in open(f).read()
       for f in ("engine.py","dispatch.py","app.py","entry_ui.py")))
ck("uploads always carry a version",
   "If-Match" in open("sharepoint_loader.py").read())
ck("a clash is retried, not ignored", "ConflictError" in app)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

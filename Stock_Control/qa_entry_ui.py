"""The screens a store worker sees: what they can pick, and what they cannot."""
import sys, qa_book, io, os, engine, entry, entry_ui, auth, pandas as pd
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
os.environ["ENTRY_PASSWORD"]="e"; os.environ["ADMIN_PASSWORD"]="a"
s,m,c,cfg,e=engine.load(qa_book.book())
stock=engine.stock_by_item(s,m,cfg["as_of"])
clear=engine.clearance_by_shipment(s,m,cfg["as_of"],cfg)
users=cfg["users"]

print("=== A. A WORKER IS LOCKED TO ONE MARKET ===")
ENTRY_U=qa_book.entry_user(cfg) or "qatar.store"
ADMIN_U=qa_book.admin_user(cfg) or "admin"
ok,w=auth.check(ENTRY_U,"e",users)
ck("the entry user signs in", ok, w if not ok else "")
ok2,a=auth.check(ADMIN_U,"a",users)
allm=["Qatar","UAE","KSA","Egypt"]
ck("worker sees exactly one market", len(auth.markets_for(w,allm))==1, auth.markets_for(w,allm))
ck("admin sees them all", auth.markets_for(a,allm)==allm)
ck("market is never a free choice for a worker", len(auth.markets_for(w,allm))==1)

print("=== B. ONLY OPEN SHIPMENTS, NEWEST FIRST ===")
MKT=(cfg.get("markets") or ["Qatar"])[0]
MKT=next((m for m in (cfg.get("markets") or []) 
          if len(entry_ui.open_shipments(s,clear,m))), MKT)
op=entry_ui.open_shipments(s,clear,MKT)
ck("something is offered", len(op)>0, f"{len(op)} shipments")
if len(op)>1:
    ck("newest first", op[0][1]>=op[1][1], f"{op[0][1]} then {op[1][1]}")
cleared=set(clear[clear.Cleared=="Yes"]["Shipment"])
ck("cleared shipments are not offered", not (set(x for x,_ in op) & cleared))
ck("another market's shipments are not offered",
   not (set(x for x,_ in op) & set(s[s.Market!=MKT]["Shipment ID"])))

print("=== C. ITEMS COME FROM THE SHIPMENT, NOT THE CATALOGUE ===")
sid=op[0][0]
its=entry_ui.items_in(s,sid)
all_items=set(s["Item Name"].dropna())
ck("only that shipment's items", set(its) <= set(s[s["Shipment ID"]==sid]["Item Name"]))
ck("fewer than the whole catalogue", len(its)<=len(all_items), f"{len(its)} of {len(all_items)}")
ck("nothing from a different shipment",
   not (set(its) & (set(s[s["Shipment ID"]!=sid]["Item Name"]) - set(s[s["Shipment ID"]==sid]["Item Name"]))))

print("=== D. EACH MOVEMENT ASKS FOR THE RIGHT FIELDS ===")
N=entry_ui.NEEDS
ck("received asks for an item and an In", N["Received"]["item"] and N["Received"]["dir"]=="In")
ck("scrap asks for a reason", N["Scrap"].get("reason") is True)
ck("to courier asks for a courier", N["To Courier"].get("courier") is True)
ck("returned names the item now", N["Returned"]["item"] is True)
ck("returned asks for courier and reason",
   all(N["Returned"].get(k) for k in ("courier","reason")))
ck("not received asks for a reason", N["Not received"].get("reason") is True)
ck("a worker sees four movements", len(entry_ui.WORKER_MOVES)==4,
   entry_ui.WORKER_MOVES)
ck("the retired ones are gone",
   not ({"Delivered","Orders Assigned","Courier Handover"} & set(N)), sorted(N))
ck("count adjustments are admin only",
   not any("Count Adjustment" in x for x in entry_ui.WORKER_MOVES))

print("=== E. THE CONFIRMATION IS PLAIN ENGLISH ===")
row={"Date":entry.market_now("Qatar").date(),"Shipment No":sid,"Movement":"Received",
     "Item Name":its[0],"In":48}
t=entry_ui._sentence(row,"Received","Qatar","qatar.store")
ck("says the number", "48" in t, t[:60])
ck("says the item", its[0] in t)
ck("says the shipment", sid in t)
ck("says who and where", "qatar.store" in t and "Qatar" in t)
ck("no field names leak in", "Shipment No" not in t and "In" not in t.split("<")[0])
t2=entry_ui._sentence({"Shipment No":sid,"Movement":"To Courier","Item Name":its[0],
                       "Out":30,"Courier":"WareOne"},"To Courier","Qatar","x")
ck("courier movement names the courier", "WareOne" in t2, t2[:70])
t3=entry_ui._sentence({"Shipment No":sid,"Movement":"Scrap","Item Name":its[0],
                       "Out":2,"Reason":"Quality"},"Scrap","Qatar","x")
ck("scrap names the reason", "Quality" in t3)

print("=== F. VOID RIGHTS ===")
today=entry.market_now("Qatar")
yest=today-pd.Timedelta(days=1)
ck("own row today can be voided", auth.can_void(w,ENTRY_U,today,today))
ck("someone else's row cannot", not auth.can_void(w,"somebody.else",today,today))
ck("yesterday's own row cannot", not auth.can_void(w,ENTRY_U,yest,today))
ck("admin can void anything", auth.can_void(a,ENTRY_U,yest,today))
ck("nobody signed in can void nothing", not auth.can_void(None,"x",today,today))

print("=== G. BAD SIGN-INS ===")
ck("wrong password refused", not auth.check(ENTRY_U,"nope",users)[0])
ck("unknown user refused", not auth.check("ghost","e",users)[0])
ck("worker password does not open admin", not auth.check(ADMIN_U,"e",users)[0])
ck("admin password does not open a worker account",
   not auth.check(ENTRY_U,"a",users)[0])
ck("blank refused", not auth.check("","",users)[0])
ck("entry stays off with no users", not auth.is_enabled({}))

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

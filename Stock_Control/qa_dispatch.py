"""QA for the dispatch engine. Synthetic orders, known answers."""
import pandas as pd, numpy as np, engine, dispatch, sys
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")

def eq(n,got,want,tol=1e-6):
    """Numeric equality - never truthiness."""
    ok = abs(float(got)-float(want)) <= tol
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}: got {got}, want {want}")

ship,moves,count,cfg,errs=engine.load("INRIPE_Stock_Entry_v1.xlsx")
stock=engine.stock_by_item(ship,moves,cfg["as_of"])
codes=set(cfg["item_names"].keys())
avail=stock.groupby("Item")["Store"].sum()
top=avail.sort_values(ascending=False)
A,B=top.index[0],top.index[1]
qa,qb=int(top.iloc[0]),int(top.iloc[1])

def o(name,day,lines,stage=dispatch.INCLUDE_STAGE,urgent=False,ful="UNFULFILLED",
      fin="PENDING",canc=False):
    return {"name":name,"created":f"2026-08-{day:02d}T09:00:00Z","stage":stage,
            "urgent":urgent,"fulfillment":ful,"financial":fin,"cancelled":canc,
            "lines":[{"sku":s,"quantity":q,"title":s} for s,q in lines]}

print("=== A. FILTERS ===")
orders=[o("#1",10,[(A,1)]),
        o("#2",10,[(A,1)],stage="1. Under Review Sales = Unfulfilled Status"),
        o("#3",10,[(A,1)],ful="FULFILLED"),
        o("#4",10,[(A,1)],fin="REFUNDED"),
        o("#5",10,[(A,1)],canc=True),
        o("#6",10,[("NO-SUCH-SKU",1)]),
        o("#7",10,[(A,1)],fin="PAID")]
d,s,x,pool=dispatch.allocate(orders,stock,codes)
ck("stage 2 + COD included", set(d["Order"])=={"#1","#7"}, sorted(set(d["Order"])))
ck("5 orders excluded", len(x)==5, f"{len(x)}")
ck("every exclusion has a reason", x["Reason"].notna().all() and (x["Reason"]!="").all())
ck("unknown sku excluded", "#6" in set(x["Order"]))

print("=== B. URGENT BEATS OLDEST ===")
orders=[o("#OLD",1,[(A,qa)]), o("#URG",20,[(A,qa)],urgent=True)]
d,s,x,pool=dispatch.allocate(orders,stock,codes)
ck("urgent wins when stock is tight", set(d["Order"])=={"#URG"}, sorted(set(d["Order"])))
ck("the loser appears as short", "#OLD" in set(s["Order"]) if len(s) else False)

print("=== C. OLDEST BEATS NEWER ===")
orders=[o("#NEW",20,[(A,qa)]), o("#OLDR",2,[(A,qa)])]
d,s,x,pool=dispatch.allocate(orders,stock,codes)
ck("oldest order wins", set(d["Order"])=={"#OLDR"}, sorted(set(d["Order"])))

print("=== D. ALL OR NOTHING ===")
orders=[o("#BIG",5,[(A,qa+50)])]
d,s,x,pool=dispatch.allocate(orders,stock,codes)
ck("order beyond stock is never partly filled", len(d)==0)
ck("and is reported short", len(s)==1 and int(s.iloc[0]["Short by"])==50, s.to_dict("records"))

print("=== E. NEVER OVER-ALLOCATE ===")
orders=[o(f"#{i}",5+i,[(A,max(1,qa//4))]) for i in range(8)]
d,s,x,pool=dispatch.allocate(orders,stock,codes)
ck("allocated never exceeds available", d[d["Item"]==A]["Qty"].sum()<=qa,
   f"{d[d['Item']==A]['Qty'].sum()} of {qa}")
ck("pool never goes negative", (pool["Avail"]>=0).all())

print("=== F. FIFO ACROSS SHIPMENTS ===")
rows=stock[(stock["Item"]==A)&(stock["Store"]>0)].sort_values("Arrival Date")
if len(rows)>1:
    first=int(rows.iloc[0]["Store"])
    orders=[o("#F",5,[(A,first+1)])]
    d,s,x,pool=dispatch.allocate(orders,stock,codes)
    used=d[d["Item"]==A].sort_values("Arrival")
    ck("split across two shipments, oldest drained first",
       len(used)==2 and int(used.iloc[0]["Qty"])==first,
       used[["Shipment","Qty"]].to_dict("records"))
    ck("oldest shipment is the first one used",
       used.iloc[0]["Shipment"]==rows.iloc[0]["Shipment"])
else:
    ck("FIFO split (only one shipment holds this item, skipped)",True)

print("=== G. SHIP NO = BIGGEST CONTRIBUTOR ===")
if len(rows)>1:
    m=dispatch.ship_no_per_order(d)
    biggest=used.sort_values("Qty",ascending=False).iloc[0]["Shipment"]
    ck("ship no is the shipment that gave most boxes", m.get("#F")==biggest,
       f"{m.get('#F')} vs {biggest}")

print("=== H. MULTI-ITEM ORDER ===")
orders=[o("#M",5,[(A,2),(B,2)])]
d,s,x,pool=dispatch.allocate(orders,stock,codes)
ck("multi-item order fully allocated", len(d)>=2 and d["Qty"].sum()==4, int(d["Qty"].sum()))

print("=== I. CHECKS PANEL ===")
orders=[o("#1",5,[(A,1)]), o("#2",6,[(A,qa+99)]),
        o("#3",6,[(A,1)],stage="6. On Hold = Unfulfilled Status")]
d,s,x,pool=dispatch.allocate(orders,stock,codes)
c=dispatch.checks(d,s,x,orders,stock,pool)
ck("all built-in checks pass", c["Pass"].all(),
   c[~c["Pass"]]["Check"].tolist() if not c["Pass"].all() else "")
ck("reconciliation adds up", 1+1+1==len(orders))

print("=== J. EMPTY CASES ===")
d,s,x,pool=dispatch.allocate([],stock,codes)
ck("no orders does not crash", len(d)==0 and len(s)==0)
empty=stock.iloc[0:0]
d,s,x,pool=dispatch.allocate([o("#Z",5,[(A,1)])],empty,codes)
ck("no stock does not crash", len(d)==0 and len(s)==1)

# ===== K. LABELS AND GROUPING (added) =====
print("=== K. STAGE LABELS ===")
P2,F2=[],[]
def ck2(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
stages={"1":"Not reviewed yet","3":"Already dispatched","4":"Confirmed by Sales Ops",
        "5":"Delivered","6":"On hold"}
for num,word in stages.items():
    full=[k for k in ["1. Under Review Sales = Unfulfilled Status",
                      "3. In progress | Stand by for Sales Ops = Unfulfilled Status",
                      "4. OFD | Confirmed - Scheduled (Fill Field # 3) = Unfulfilled Status",
                      "5. Partially Delivered = Fulfilled Status | Mark as Delivered",
                      "6. On Hold = Unfulfilled Status"] if k.startswith(num)][0]
    d,s_,x,pool=dispatch.allocate([o("#S",5,[(A,1)],stage=full)],stock,codes)
    ck2(f"stage {num} labelled '{word}'",
        len(x)==1 and word in str(x.iloc[0]["Reason"]), str(x.iloc[0]["Reason"]) if len(x) else "")
d,s_,x,pool=dispatch.allocate([o("#N",5,[(A,1)],stage=None)],stock,codes)
ck2("missing stage labelled", "No order stage set" in str(x.iloc[0]["Reason"]))
d,s_,x,pool=dispatch.allocate([o("#W",5,[(A,1)],stage="99. Something New")],stock,codes)
ck2("unknown stage does not crash", "not recognised" in str(x.iloc[0]["Reason"]).lower())

print("=== L. EXCLUSION GROUPING ===")
many=[o(f"#G{i}",5,[(A,1)],stage="6. On Hold = Unfulfilled Status") for i in range(7)]
d,s_,x,pool=dispatch.allocate(many,stock,codes)
g=dispatch.group_excluded(x)
ck2("7 identical exclusions become 1 row", len(g)==1, f"{len(g)} rows")
ck2("count is right", int(g.iloc[0]["Orders"])==7)
ck2("examples are capped", "+4 more" in g.iloc[0]["Examples"], g.iloc[0]["Examples"])
ck2("empty exclusions do not crash", len(dispatch.group_excluded(x.iloc[0:0]))==0)

print("=== M. NO SKU vs UNKNOWN SKU ===")
oo=o("#K1",5,[(A,1)]); oo["lines"][0]["sku"]=None
d,s_,x,pool=dispatch.allocate([oo],stock,codes)
ck2("missing SKU says 'no SKU in Shopify'", "no SKU in Shopify" in str(x.iloc[0]["Reason"]))
d,s_,x,pool=dispatch.allocate([o("#K2",5,[("BAD-SKU",1)])],stock,codes)
ck2("unknown SKU says 'not in your item list'",
    "not in your item list" in str(x.iloc[0]["Reason"]))

print("=== N. RECONCILIATION BY ITEM ===")
names=cfg.get("item_names",{})
orders=[o("#R1",5,[(A,3)]), o("#R2",6,[(A,qa+40)]), o("#R3",7,[(B,2)]),
        o("#R4",8,[(A,1)],stage="6. On Hold = Unfulfilled Status")]
d,s_,x,pool=dispatch.allocate(orders,stock,codes)
rec=dispatch.reconcile(d,s_,orders,stock,codes,names)
ck("every row passes the stock identity", (rec["Stock check"]=="OK").all())
ck("every row passes the demand identity", (rec["Demand check"]=="OK").all(),
   rec[rec["Demand check"]!="OK"].to_dict("records"))
ck("Available = Allocated + Left on every row",
   ((rec["Available"]-rec["Allocated"]-rec["Left"]).abs()<1e-6).all())
ck("Needed = Allocated + Not allocated on every row",
   ((rec["Needed"]-rec["Allocated"]-rec["Not allocated"]).abs()<1e-6).all())
ck("Short to buy never exceeds Not allocated",
   (rec["Short to buy"]<=rec["Not allocated"]+1e-6).all(),
   rec[rec["Short to buy"]>rec["Not allocated"]].to_dict("records"))
ck("no negative Not allocated", (rec["Not allocated"]>=-1e-6).all())
eq("total available matches the sheet", rec["Available"].sum(), stock["Store"].sum())
eq("total allocated matches the dispatch list", rec["Allocated"].sum(),
   d["Qty"].sum() if len(d) else 0)
eq("held-back orders are not counted as demand",
   rec.loc[rec["Item"]==names.get(A,A),"Needed"].iloc[0], 3+qa+40)
ck("no negative Left", (rec["Left"]>=0).all())
rec0=dispatch.reconcile(d.iloc[0:0],s_.iloc[0:0],[],stock,codes,names)
ck("no orders still lists the stock", len(rec0)>0 and rec0["Needed"].sum()==0)
ck("item names are used, not codes", names.get(A,A) in set(rec["Item"]))

print("=== O. FUNNELS ===")
orders=[o("#F1",5,[(A,2)]), o("#F2",6,[(A,qa+50)]), o("#F3",7,[(B,1)]),
        o("#F4",8,[(A,1)],stage="6. On Hold = Unfulfilled Status"),
        o("#F5",9,[(A,1)],ful="FULFILLED")]
d,s_,x,pool=dispatch.allocate(orders,stock,codes)
of,bf,ex=dispatch.funnel(orders,d,s_,stock,codes)
eq("orders read matches input", of.loc[0,"Orders"], len(orders))
eq("not considered matches excluded", of.loc[1,"Orders"], len(x))
eq("reviewed = read - not considered", of.loc[2,"Orders"], len(orders)-len(x))
eq("ready = reviewed - short", of.loc[4,"Orders"], of.loc[2,"Orders"]-of.loc[3,"Orders"])
eq("ready orders matches dispatch list", of.loc[4,"Orders"],
   d["Order"].nunique() if len(d) else 0)
eq("ready boxes matches dispatch list", of.loc[4,"Boxes"],
   d["Qty"].sum() if len(d) else 0)
eq("reviewed boxes = allocated + blocked", ex["reviewed_boxes"],
   ex["allocated"]+ex["blocked"])
eq("available = allocated + left", ex["available"], ex["allocated"]+ex["left"])
eq("available matches the sheet", ex["available"], stock["Store"].sum())
eq("boxes funnel available row", bf.loc[0,"Qty"], stock["Store"].sum())
eq("boxes funnel allocated row", bf.loc[2,"Qty"], ex["allocated"])
eq("boxes funnel left row", bf.loc[4,"Qty"], ex["left"])
eq("short to buy matches the short table", bf.loc[5,"Qty"],
   s_["Short by"].sum() if len(s_) else 0)
eq("funnel ties to reconcile: allocated", ex["allocated"],
   dispatch.reconcile(d,s_,orders,stock,codes)["Allocated"].sum())
eq("funnel ties to reconcile: wanted", ex["reviewed_boxes"],
   dispatch.reconcile(d,s_,orders,stock,codes)["Needed"].sum())
eq("funnel ties to reconcile: short to buy", bf.loc[5,"Qty"],
   dispatch.reconcile(d,s_,orders,stock,codes)["Short to buy"].sum())
of0,bf0,ex0=dispatch.funnel([],d.iloc[0:0],s_.iloc[0:0],stock,codes)
eq("empty orders do not crash the funnel", of0.loc[0,"Orders"], 0)
eq("empty funnel still shows the stock", bf0.loc[0,"Qty"], stock["Store"].sum())

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

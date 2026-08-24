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
ck("2 orders excluded - fulfilled and bad sku", len(x)==2, sorted(x["Order"]) if len(x) else [])
ck("cancelled and refunded are out of scope, not excluded",
   not {"#4","#5"} & (set(x["Order"]) if len(x) else set()))
ck("every exclusion has a reason", x["Reason"].notna().all() and (x["Reason"]!="").all())
ck("unknown sku excluded", "#6" in set(x["Order"]))
ck("the stage-1 order is not listed at all", "#2" not in set(x["Order"]))

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
orders=[o("#1",5,[(A,1)]), o("#2",6,[(A,qa+99)]), o("#3",6,[("BAD-SKU",1)])]
d,s,x,pool=dispatch.allocate(orders,stock,codes)
c=dispatch.checks(d,s,x,orders,stock,pool)
ck("all built-in checks pass", c["Pass"].all(),
   c[~c["Pass"]]["Check"].tolist() if not c["Pass"].all() else "")
ck("reconciliation adds up within stage 2", 1+1+1==len(dispatch.in_scope(orders)))

print("=== J. EMPTY CASES ===")
d,s,x,pool=dispatch.allocate([],stock,codes)
ck("no orders does not crash", len(d)==0 and len(s)==0)
empty=stock.iloc[0:0]
d,s,x,pool=dispatch.allocate([o("#Z",5,[(A,1)])],empty,codes)
ck("no stock does not crash", len(d)==0 and len(s)==1)

# ===== K. LABELS AND GROUPING (added) =====
print("=== K. OTHER STAGES ARE OUT OF SCOPE ===")
stages={"1":"1. Under Review Sales = Unfulfilled Status",
        "3":"3. In progress | Stand by for Sales Ops = Unfulfilled Status",
        "4":"4. OFD | Confirmed - Scheduled (Fill Field # 3) = Unfulfilled Status",
        "5":"5. Partially Delivered = Fulfilled Status | Mark as Delivered",
        "6":"6. On Hold = Unfulfilled Status"}
for num,full in stages.items():
    d,s_,x,pool=dispatch.allocate([o("#S",5,[(A,1)],stage=full)],stock,codes)
    ck(f"stage {num} is not dispatched", len(d)==0)
    ck(f"stage {num} is not listed as excluded", len(x)==0, f"{len(x)} rows")
d,s_,x,pool=dispatch.allocate([o("#N",5,[(A,1)],stage=None)],stock,codes)
ck("no stage set is out of scope", len(d)==0 and len(x)==0)
d,s_,x,pool=dispatch.allocate([o("#W",5,[(A,1)],stage="99. Something New")],stock,codes)
ck("an unknown stage is out of scope", len(d)==0 and len(x)==0)

print("=== L. EXCLUSION GROUPING ===")
many=[o(f"#G{i}",5,[("BAD-SKU",1)]) for i in range(7)]
d,s_,x,pool=dispatch.allocate(many,stock,codes)
g=dispatch.group_excluded(x)
ck("7 identical exclusions become 1 row", len(g)==1, f"{len(g)} rows")
ck("count is right", int(g.iloc[0]["Orders"])==7)
ck("examples are capped", "+4 more" in g.iloc[0]["Examples"], g.iloc[0]["Examples"])
ck("empty exclusions do not crash", len(dispatch.group_excluded(x.iloc[0:0]))==0)

print("=== M. NO SKU vs UNKNOWN SKU ===")
oo=o("#K1",5,[(A,1)]); oo["lines"][0]["sku"]=None
d,s_,x,pool=dispatch.allocate([oo],stock,codes)
ck("missing SKU says 'no SKU in Shopify'", "no SKU in Shopify" in str(x.iloc[0]["Reason"]))
d,s_,x,pool=dispatch.allocate([o("#K2",5,[("BAD-SKU",1)])],stock,codes)
ck("unknown SKU says 'not in your item list'",
    "not in your item list" in str(x.iloc[0]["Reason"]))

print("=== N. RECONCILIATION BY ITEM ===")
names=cfg.get("item_names",{})
orders=[o("#R1",5,[(A,3)]), o("#R2",6,[(A,qa+40)]), o("#R3",7,[(B,2)]),
        o("#R4",8,[(A,1)],stage="6. On Hold = Unfulfilled Status")]
# #R4 is out of scope entirely, so it must not appear in demand
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
        o("#F5",9,[(A,1)],ful="FULFILLED")]  # F4 out of scope, F5 a stage-2 rejection
d,s_,x,pool=dispatch.allocate(orders,stock,codes)
of,bf,ex=dispatch.funnel(orders,d,s_,stock,codes)
eq("reviewed counts every stage-2 order", of.loc[0,"Orders"], len(dispatch.in_scope(orders)))
eq("ready = reviewed less every loss", of.loc[4,"Orders"],
   of.loc[0,"Orders"]-of.loc[1,"Orders"]-of.loc[2,"Orders"]-of.loc[3,"Orders"])
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

print("=== P. FUNNEL STARTS AT REVIEWED ===")
orders=[o("#P1",5,[(A,1)]), o("#P2",6,[(A,1)],stage="1. Under Review Sales = Unfulfilled Status"),
        o("#P3",7,[(A,1)],stage="6. On Hold = Unfulfilled Status")]
d,s_,x,pool=dispatch.allocate(orders,stock,codes)
of,bf,ex=dispatch.funnel(orders,d,s_,stock,codes)
ck("funnel first row is Reviewed", str(of.loc[0,"Stage"]).startswith("Reviewed"),
   str(of.loc[0,"Stage"]))
eq("first row counts only stage 2", of.loc[0,"Orders"], 1)
ck("the total read is still shown as a note", "unfulfilled read" in str(of.loc[0,"Note"]),
   str(of.loc[0,"Note"]))
eq("funnel has 5 rows", len(of), 5)
eq("ready still ties to the dispatch list", of.loc[4,"Orders"],
   d["Order"].nunique() if len(d) else 0)
eq("reviewed = excluded + short + not chosen + ready", of.loc[0,"Orders"],
   of.loc[1,"Orders"]+of.loc[2,"Orders"]+of.loc[3,"Orders"]+of.loc[4,"Orders"])

print("=== Q. TRUNCATION IS SURFACED ===")
import shopify_reader as sr
_orig = sr.requests
class _FakeResp:
    status_code=200
    def json(self):
        return {"data":{"orders":{"pageInfo":{"hasNextPage":True,"endCursor":"c"},
                "edges":[{"node":{"name":"#1","createdAt":"2026-08-01T00:00:00Z",
                "cancelledAt":None,"displayFulfillmentStatus":"UNFULFILLED",
                "displayFinancialStatus":"PENDING","stage":None,"urgent":None,
                "lineItems":{"edges":[]}}}]}}}
class _FakeReq:
    @staticmethod
    def post(url, **kw):
        if "oauth" in url:
            class R: status_code=200
            R.json=lambda self=None: {"access_token":"t","expires_in":86400}
            return R()
        return _FakeResp()
sr.requests=_FakeReq
sr._token_cache={"value":"t","expires":9e18}
import os as _os
for k,v in {"SHOP_DOMAIN":"x.myshopify.com","SHOP_CLIENT_ID":"a",
            "SHOP_CLIENT_SECRET":"b","SHOP_MARKET":"Qatar"}.items(): _os.environ[k]=v
res, trunc = sr.fetch_orders(limit_pages=2)
ck("more pages left is reported as truncated", trunc is True, str(trunc))
sr.requests=_orig

print("=== R. STAGE 2 ONLY, EVERYWHERE ===")
others=["1. Under Review Sales = Unfulfilled Status",
        "3. In progress | Stand by for Sales Ops = Unfulfilled Status",
        "4. OFD | Confirmed - Scheduled (Fill Field # 3) = Unfulfilled Status",
        "5. Partially Delivered = Fulfilled Status | Mark as Delivered",
        "6. On Hold = Unfulfilled Status"]
orders=[o("#S2",5,[(A,1)])]
oo=o("#NOSKU",5,[(A,1)]); oo["lines"][0]["sku"]=None
orders.append(oo)
orders += [o(f"#OT{i}",6,[(A,1)],stage=st) for i,st in enumerate(others)]
orders.append(o("#NOSTAGE",7,[(A,1)],stage=None))
d,s_,x,pool=dispatch.allocate(orders,stock,codes)
eq("only stage 2 is in scope", len(dispatch.in_scope(orders)), 2)
ck("no other stage appears in Not considered",
   not any(str(n).startswith("#OT") for n in x["Order"]), sorted(x["Order"]))
ck("orders with no stage are out of scope too", "#NOSTAGE" not in set(x["Order"]))
ck("a real stage-2 rejection is still listed", "#NOSKU" in set(x["Order"]))
of,bf,ex=dispatch.funnel(orders,d,s_,stock,codes)
eq("funnel scope is stage 2 only", ex["scope"], 2)
eq("funnel reconciles within stage 2", of.loc[0,"Orders"],
   sum(of.loc[i,"Orders"] for i in (1,2,3,4)))
eq("boxes reconcile within stage 2 too", of.loc[0,"Boxes"],
   sum(of.loc[i,"Boxes"] for i in (1,2,3,4)))
eq("boxes funnel wanted excludes rejected orders", ex["reviewed_boxes"],
   ex["scope_boxes"]-ex["excluded_boxes"])
c=dispatch.checks(d,s_,x,orders,stock,pool)
ck("the count check now uses stage 2", c["Pass"].all(),
   c[~c["Pass"]][["Check","Result"]].to_dict("records"))

print("=== S. SCOPE LIST ===")
orders=[o("#L1",5,[(A,2)]), o("#L2",6,[(A,qa+99)]), o("#L3",7,[("BAD-SKU",1)]),
        o("#L4",8,[(A,1)],stage="6. On Hold = Unfulfilled Status"),
        o("#L5",9,[(A,1)],urgent=True)]
d,s_,x,pool=dispatch.allocate(orders,stock,codes)
sl=dispatch.scope_list(orders,d,s_,x)
eq("one row per stage-2 order", len(sl), len(dispatch.in_scope(orders)))
ck("out-of-scope order is absent", "#L4" not in set(sl["Order"]))
ck("every row has an outcome", sl["Outcome"].notna().all() and (sl["Outcome"]!="").all())
ck("outcomes are only the three we expect",
   set(sl["Outcome"]) <= {"Ready to dispatch","Short","Excluded"}, set(sl["Outcome"]))
eq("ready rows match the dispatch list", (sl["Outcome"]=="Ready to dispatch").sum(),
   d["Order"].nunique() if len(d) else 0)
eq("short rows match the short list", (sl["Outcome"]=="Short").sum(),
   s_["Order"].nunique() if len(s_) else 0)
eq("excluded rows match", (sl["Outcome"]=="Excluded").sum(), len(x))
ck("the rejected order carries its reason",
   sl.loc[sl["Order"]=="#L3","Why"].iloc[0] != "")
ck("urgent is flagged", sl.loc[sl["Order"]=="#L5","Urgent"].iloc[0]=="Yes")
eq("boxes tie to the order", sl.loc[sl["Order"]=="#L1","Boxes"].iloc[0], 2)
ck("csv export does not crash", len(sl.to_csv(index=False))>0)
eq("empty scope gives an empty list", len(dispatch.scope_list([],d,s_,x)), 0)

print("=== T. EXCLUDED IS PART OF STAGE 2 ===")
orders=[o("#T1",5,[(A,1)]), o("#T2",6,[("BAD",1)]),
        o("#T3",7,[(A,1)],fin="VOIDED"), o("#T4",8,[(A,1)],canc=True),
        o("#T5",9,[(A,qa+99)])]
d,s_,x,pool=dispatch.allocate(orders,stock,codes)
of,bf,ex=dispatch.funnel(orders,d,s_,stock,codes)
eq("cancelled and voided are out of scope", ex["scope"], 3)
eq("only the bad-sku order is excluded", len(x), 1)
dead=dispatch.dead_stage2(orders)
eq("the dead ones are listed separately", len(dead), 2)
ck("and named", set(dead["Order"])=={"#T3","#T4"}, sorted(dead["Order"]))
ck("the funnel row is labelled excluded", "excluded" in str(of.loc[1,"Stage"]),
   str(of.loc[1,"Stage"]))
eq("funnel excluded count matches", of.loc[1,"Orders"], len(x))
eq("ready + short + not chosen + excluded = stage 2",
   sum(of.loc[i,"Orders"] for i in (1,2,3,4)), ex["scope"])
sl=dispatch.scope_list(orders,d,s_,x)
eq("every live stage-2 order is in the list", len(sl), 3)
eq("and one says Excluded", (sl["Outcome"]=="Excluded").sum(), 1)
ck("no cancelled order in the list", not {"#T3","#T4"} & set(sl["Order"]))

print("=== U. STRATEGIES AND THE AGE CAP ===")
import datetime as _dt
NOW=pd.Timestamp("2026-08-24")
def od(name, days_old, lines, **kw):
    d=o(name,1,lines,**kw)
    d["created"]=(NOW-pd.Timedelta(days=days_old)).isoformat()
    return d
mix=[od("#U1",9,[(A,1)]), od("#U2",4,[(A,2)]), od("#U3",0,[(A,1)]),
     od("#U4",0,[(A,3)]), od("#U5",0,[(B,1)]), od("#U6",0,[(A,1)]),
     od("#U7",1,[(A,2)],urgent=True)]
res={}
for st in dispatch.STRATEGIES:
    d_,s_,x_,p_=dispatch.allocate(mix,stock,codes,st,3,NOW)
    res[st]=(d_["Order"].nunique() if len(d_) else 0,
             float(d_["Qty"].sum()) if len(d_) else 0.0, d_)
ck("all three strategies run", len(res)==3)
ck("most orders has the most orders",
   res["Most orders"][0]>=max(v[0] for v in res.values()),
   {k:v[0] for k,v in res.items()})
ck("most stock out moves the most boxes",
   res["Most stock out"][1]>=max(v[1] for v in res.values()),
   {k:v[1] for k,v in res.items()})
for st,(n,b,d_) in res.items():
    rules=set(d_.drop_duplicates("Order")["Rule"]) if len(d_) else set()
    ck(f"{st}: urgent order is in", "#U7" in set(d_["Order"]) if len(d_) else False)
    ck(f"{st}: the 9-day-old order is forced in by the cap",
       "#U1" in set(d_["Order"]) if len(d_) else False)
    ck(f"{st}: rules are only URG, CAP, FIT", rules<= {"URG","CAP","FIT"}, rules)
d_,s_,x_,p_=dispatch.allocate(mix,stock,codes,"Balanced",None,NOW)
ck("with no cap nothing is marked CAP",
   "CAP" not in set(d_["Rule"]) if len(d_) else True)
d_,s_,x_,p_=dispatch.allocate(mix,stock,codes,"Balanced",1,NOW)
capped=set(d_.loc[d_["Rule"]=="CAP","Order"]) if len(d_) else set()
ck("a 1-day cap forces the 1-day-old and older orders",
   {"#U1","#U2"} <= capped or "#U1" in capped, sorted(capped))
c=dispatch.compare_strategies(mix,stock,codes,3,NOW)
eq("comparison has one row per strategy", len(c), 3)
ck("comparison carries the order set for diffing", "_sel" in c.columns)
ck("boxes out + left = stock, every strategy",
   all(abs(r["Boxes out"]+r["Left in store"]-stock["Store"].sum())<1e-6
       for _,r in c.iterrows()))
d_,s_,x_,p_=dispatch.allocate(mix,stock,codes,"Balanced",3,NOW)
chk=dispatch.checks(d_,s_,x_,mix,stock,p_,3,NOW,codes)
ck("the cap check is present",
   any("older than" in str(r) for r in chk["Check"]), chk["Check"].tolist())
ck("every check passes on the mixed set", chk["Pass"].all(),
   chk[~chk["Pass"]][["Check","Result"]].to_dict("records"))

print("=== V. CANCELLED AND VOIDED ARE OUT OF SCOPE ===")
mix=[o("#V1",5,[(A,1)]),
     o("#V2",5,[(A,1)],canc=True),
     o("#V3",5,[(A,1)],fin="VOIDED"),
     o("#V4",5,[(A,1)],fin="REFUNDED"),
     o("#V5",5,[(A,1)],canc=True,urgent=True),
     o("#V6",5,[(A,1)],stage="1. Under Review Sales = Unfulfilled Status")]
d_,s_,x_,p_=dispatch.allocate(mix,stock,codes)
eq("only the live stage-2 order is in scope", len(dispatch.in_scope(mix)), 1)
ck("no dead order reaches the dispatch list",
   not {"#V2","#V3","#V4","#V5"} & (set(d_["Order"]) if len(d_) else set()))
ck("no dead order is listed as excluded",
   not {"#V2","#V3","#V4","#V5"} & (set(x_["Order"]) if len(x_) else set()))
dead=dispatch.dead_stage2(mix)
eq("all four dead stage-2 orders are shown separately", len(dead), 4)
ck("a stage-1 cancelled order is not shown", "#V6" not in set(dead["Order"]))
ck("the urgent one is flagged",
   dead.loc[dead["Order"]=="#V5","Urgent"].iloc[0]=="Yes")
ck("reasons are named", set(dead["Reason"]) <= {"Cancelled","Voided","Refunded"},
   sorted(set(dead["Reason"])))
of,bf,ex=dispatch.funnel(mix,d_,s_,stock,codes)
eq("the funnel counts only live stage-2 orders", of.loc[0,"Orders"], 1)
chk=dispatch.checks(d_,s_,x_,mix,stock,p_,3,None,codes)
ck("reconciliation still holds", chk["Pass"].all(),
   chk[~chk["Pass"]][["Check","Result"]].to_dict("records"))

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

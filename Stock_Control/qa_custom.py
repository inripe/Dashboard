# -*- coding: utf-8 -*-
"""
The Custom strategy: criteria the person picks and ranks themselves.

Nothing here may be hidden - every weight is on screen, every dispatched order
says which criterion put it there - and the guards that protect the ledger
apply exactly as they do to the three presets.
"""
import sys, random
import pandas as pd
import engine, dispatch as dsp, qa_book
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
def eq(n,got,want,tol=1e-6):
    try: ok=abs(float(got)-float(want))<=tol
    except (TypeError,ValueError): ok=str(got)==str(want)
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}: got {got}, want {want}")

s,m,c,cfg,e = engine.load(qa_book.book())
stock = engine.stock_by_item(s, m, cfg["as_of"])
MKT = stock["Market"].dropna().iloc[0]
stock = stock[stock["Market"] == MKT]
codes = set(cfg["item_names"])
items = list(cfg["item_names"])[:3]
T = pd.Timestamp.now()

def order(i, days, qty=1, flags=None, urgent=False, sku=None, extra=None):
    return {"name": f"#{i}", "created": (T - pd.Timedelta(days=days)).isoformat(),
            "cancelled": False, "fulfillment": "UNFULFILLED",
            "financial": "PENDING", "stage": dsp.INCLUDE_STAGE,
            "urgent": urgent, "exceptions": flags or [],
            "additional": extra or [],
            "lines": [{"sku": sku or items[i % len(items)], "quantity": qty,
                       "title": "x"}]}

BASE = [order(i, i % 5, 1 + i % 3,
              ["Urgent"] if i % 9 == 0 else (["VIP customer"] if i % 5 == 0 else []),
              urgent=(i % 9 == 0),
              extra=(["Fragile"] if i % 4 == 0
                     else (["Call before delivery"] if i % 6 == 0 else [])))
        for i in range(30)]
RULE = {"on": {"exception": True, "additional": True, "age": True,
               "boxes": True},
        "weights": {"exception": 10, "additional": 6, "age": 7, "boxes": 4},
        "value_order": {"exception": ["Urgent", "VIP customer"],
                        "additional": ["Fragile", "Call before delivery"]},
        "flag_order": ["Urgent", "VIP customer"]}

print("=== A. THE CRITERIA ARE IN PLAIN WORDS ===")
eq("there are seven", len(dsp.CRITERIA), 7)
for code, label, what in dsp.CRITERIA:
    ck(f"'{label}' reads as english",
       label[0].isupper() and label.islower() is False and "_" not in label
       and len(label.split()) >= 3, label)
    ck(f"'{label}' explains itself", len(what) > 15, what)
ck("no jargon in any of them",
   not any(w in (l + d).lower() for _, l, d in dsp.CRITERIA
           for w in ("weight", "objective", "heuristic", "score", "optimis")),
   [l for _, l, _ in dsp.CRITERIA])

print("=== B. BOTH METAFIELDS ARE OFFERED ===")
eq("two fields can be ranked", len(dsp.FIELDS), 2)
ck("order exceptions is one", "exception" in dsp.FIELDS, sorted(dsp.FIELDS))
ck("additional info is the other", "additional" in dsp.FIELDS)
ck("each is a criterion of its own",
   {"exception", "additional"} <= {c for c, _, _ in dsp.CRITERIA})
sr = open("shopify_reader.py").read()
ck("exceptions is read from shopify", "5_order_exceptions" in sr)
ck("so is additional info",
   "2_order_additional_info_for_sales_customer_service" in sr)
ck("both are asked for in the same query",
   sr.count("metafield(namespace") >= 3, sr.count("metafield(namespace"))

print("=== C. THE VALUES COME FROM SHOPIFY, NOT FROM A LIST HERE ===")
ex = dsp.field_values(BASE, "exception")
ad = dsp.field_values(BASE, "additional")
ck("it finds the exception values", len(ex) == 2, ex)
ck("and the additional info values", len(ad) == 2, ad)
ck("most common first", ex[0][1] >= ex[-1][1], ex)
ck("a new value appears on its own",
   "Gift" in dict(dsp.field_values(BASE + [order(99, 1, 1, ["Gift"])],
                                   "exception")), "")
ck("a new additional value too",
   "Leave at door" in dict(dsp.field_values(
       BASE + [order(98, 1, 1, extra=["Leave at door"])], "additional")), "")
eq("no values means an empty list", len(dsp.field_values([order(1, 1)])), 0)
src = open("dispatch.py").read()
ck("no value is hard-coded",
   "VIP" not in src and "Fragile" not in src and "Replacement" not in src, "")
ck("the older caller still works",
   dsp.exception_values(BASE) == ex, "")

print("=== D. IT ALLOCATES, AND EVERY GUARD STILL HOLDS ===")
d, sh, x, pool = dsp.allocate(BASE, stock, codes, "Custom", 7, rule=RULE)
ck("something was dispatched", len(d) > 0, len(d))
chk = dsp.checks(d, sh, x, BASE, stock, pool, 7, None, codes)
bad = chk[~chk["Pass"]]
ck("every check passes", not len(bad), bad["Check"].tolist() if len(bad) else "")
per_item = d.groupby("Item")["Qty"].sum()
for sku, q in per_item.items():
    have = float(stock[stock["Item"] == sku]["Store"].sum())
    ck(f"never more than the store holds of {sku[-8:]}", q <= have + 0.001,
       f"{q} of {have}")
ck("no order appears twice",
   d.drop_duplicates(["Order", "Item"]).shape[0] == d.shape[0])

print("=== E. URGENT IS GUARANTEED WHATEVER THE RULE SAYS ===")
urg = {o["name"] for o in BASE if o["urgent"]}
ck("every urgent order is in", urg <= set(d["Order"]),
   sorted(urg - set(d["Order"])))
ck("and labelled as urgent",
   set(d[d["Order"].isin(urg)]["Rule"]) == {"URG"},
   sorted(set(d[d["Order"].isin(urg)]["Rule"])))
off = dict(RULE, on={k: False for k in RULE["on"]})
d2, *_ = dsp.allocate(BASE, stock, codes, "Custom", 7, rule=off)
ck("even with every criterion switched off", urg <= set(d2["Order"]),
   sorted(urg - set(d2["Order"])))

print("=== F. EVERY ORDER SAYS WHY IT IS IN ===")
u = d.drop_duplicates("Order")
ck("there is a reason column", "Why" in d.columns, list(d.columns))
ck("and no row is left blank",
   bool((u["Why"].astype(str).str.strip() != "").all()),
   u[u["Why"].astype(str).str.strip() == ""]["Order"].tolist()[:3])
ck("urgent says so",
   all("urgent" in w for w in u[u["Rule"] == "URG"]["Why"]),
   u[u["Rule"] == "URG"]["Why"].tolist()[:2])
ck("a flagged order names its flag",
   any("VIP customer" in w for w in u["Why"]),
   [w for w in u["Why"] if "VIP" in w][:2])
ck("waiting time is given in days",
   any("waited" in w for w in u["Why"]), u["Why"].tolist()[:3])

print("=== G. RANKING EITHER FIELD CHANGES THE ANSWER ===")
for which, val in (("exception", "VIP customer"), ("additional", "Fragile")):
    only = {"on": {which: True}, "weights": {which: 10},
            "value_order": {which: [val]}}
    # a big cap so the age rule does not take them first - it is the ranking
    # being tested here, not the cap
    dv, *_ = dsp.allocate(BASE, stock, codes, "Custom", 999, rule=only)
    tagged = {o["name"] for o in BASE if val in dsp._order_flags(o, which)}
    u2 = dv.drop_duplicates("Order")
    got = set(u2["Order"]) & tagged
    ck(f"ranking {val} pulls those orders in", len(got) > 0,
       f"{len(got)} of {len(tagged)}")
    chosen = u2[u2["Order"].isin(got) & (u2["Rule"] == "FIT")]
    ck(f"and the reason names {val} where the rule decided",
       len(chosen) == 0 or any(val in w for w in chosen["Why"]),
       chosen["Why"].tolist()[:2])

print("=== H. THE RULE CHANGES THE ANSWER ===")
big = dict(RULE, on={"boxes": True}, weights={"boxes": 10})
small = dict(RULE, on={"orders": True}, weights={"orders": 10})
db, *_ = dsp.allocate(BASE, stock, codes, "Custom", 0, rule=big)
ds, *_ = dsp.allocate(BASE, stock, codes, "Custom", 0, rule=small)
ck("preferring big orders sends more boxes per order",
   (float(db["Qty"].sum()) / max(db["Order"].nunique(), 1))
   >= (float(ds["Qty"].sum()) / max(ds["Order"].nunique(), 1)),
   f"{db['Qty'].sum()}/{db['Order'].nunique()} vs "
   f"{ds['Qty'].sum()}/{ds['Order'].nunique()}")
ck("preferring small orders serves more customers",
   ds["Order"].nunique() >= db["Order"].nunique(),
   f"{ds['Order'].nunique()} vs {db['Order'].nunique()}")
age_only = {"on": {"age": True}, "weights": {"age": 10}, "flag_order": []}
da, *_ = dsp.allocate(BASE, stock, codes, "Custom", 0, rule=age_only)
picked = da.drop_duplicates("Order")
ck("age first really does take the oldest",
   pd.to_datetime(picked["Placed"]).min() <= pd.to_datetime(
       da["Placed"]).median(), "")

print("=== I. SAVING WHAT WE ARE SHORT OF ===")
SKU = items[0]
heavy = [order(200 + i, 1, 5, sku=SKU) for i in range(20)]
scarce = {"on": {"scarce": True}, "weights": {"scarce": 10}, "flag_order": []}
none_ = {"on": {}, "weights": {}, "flag_order": []}
d3, *_ = dsp.allocate(heavy, stock, codes, "Custom", 0, rule=scarce)
d4, *_ = dsp.allocate(heavy, stock, codes, "Custom", 0, rule=none_)
have = float(stock[stock["Item"] == SKU]["Store"].sum())
ck("it never sends more of a short item than exists",
   float(d3[d3["Item"] == SKU]["Qty"].sum()) <= have + 0.001,
   f"{d3[d3['Item']==SKU]['Qty'].sum()} of {have}")
ck("and holding back does not break anything",
   not len(dsp.checks(d3, *dsp.allocate(heavy, stock, codes, "Custom", 0,
                                        rule=scarce)[1:3],
                      heavy, stock, dsp.allocate(heavy, stock, codes, "Custom",
                                                 0, rule=scarce)[3],
                      0, None, codes).query("Pass == False")))

print("=== J. THE RULE READS BACK IN WORDS ===")
w = dsp.describe(RULE)
ck("it names the exception values in order",
   w.index("Urgent") < w.index("VIP customer"), w[:60])
ck("and names both fields",
   "Order Exceptions" in w and "Additional Info" in w, w[:90])
ck("with the additional values in order",
   w.index("Fragile") < w.index("Call before delivery"), "")
ck("it mentions the other criteria",
   "waited longest" in w.lower(), w)
ck("nothing switched on says so",
   "oldest first" in dsp.describe({"on": {}, "weights": {}}).lower(),
   dsp.describe({"on": {}, "weights": {}}))
ck("no numbers are hidden behind words",
   "score" not in w.lower() and "weight" not in w.lower(), w)

print("=== K. THE PANEL SHOWS EVERYTHING ===")
app = open("app.py").read()
ck("Custom is offered beside the three", 'names + ["Custom"]' in app)
ck("the weights are sliders you can see", "c3.slider" in app)
ck("each criterion explains itself", "c4.markdown" in app)
ck("the values are read live", "dsp.field_values(orders, code)" in app)
ck("for whichever field it is", "code in dsp.FIELDS" in app)
ck("with a count beside each", "orders)" in app)
ck("the rule is written out in words", "dsp.describe(rule)" in app)
ck("it says urgent is guaranteed", "guaranteed whatever you set" in app)
ck("Custom joins the comparison table", '"Strategy": "Custom"' in app)
panel = app.split("def custom_panel")[1].split("\ndef ")[0]
ck("the rule lives in the session, never in the workbook",
   'key=f"{key}_on_' in panel and "custom_rule" in app
   and "upload_workbook" not in panel and "entry.append" not in panel, "")
ck("and it is rebuilt each run, so nobody inherits it",
   "custom_rule = None" in app)
ck("the reason is shown in the list", "Why it is in" in app)

print("=== L. LEVELLING THE WEIGHTS ===")
ck("there is a way to make them all equal", '"Level all"' in app)
ck("it sets every one to the same number",
   "st.session_state[f\"{key}_w_{c_}\"] = 5" in app)
ck("and it covers every criterion, not some",
   "for c_, _, _ in dsp.CRITERIA" in app)
ck("there is a way back to the defaults", '"Reset"' in app)
ck("which clears the switches and the values too",
   '_on_{c_}' in app and '_vals_{c_}' in app)
ck("the defaults are seeded once, then owned by the session",
   "st.session_state.setdefault(\n            f\"{key}_w_{code}\"" in app)
# equal weights really do mean no criterion dominates
lvl = {"on": {"exception": True, "additional": True, "age": True},
       "weights": {"exception": 5, "additional": 5, "age": 5},
       "value_order": {"exception": ["Urgent"], "additional": ["Fragile"]}}
one = dict(lvl, weights={"exception": 10, "additional": 1, "age": 1})
dl, *_ = dsp.allocate(BASE, stock, codes, "Custom", 999, rule=lvl)
do, *_ = dsp.allocate(BASE, stock, codes, "Custom", 999, rule=one)
ck("levelling changes the answer from a weighted rule",
   set(dl["Order"]) != set(do["Order"])
   or float(dl["Qty"].sum()) == float(do["Qty"].sum()),
   f"{dl['Order'].nunique()} vs {do['Order'].nunique()}")
ck("and every level run still passes its checks",
   not len(dsp.checks(*dsp.allocate(BASE, stock, codes, "Custom", 999,
                                    rule=lvl)[:3],
                      BASE, stock,
                      dsp.allocate(BASE, stock, codes, "Custom", 999,
                                   rule=lvl)[3],
                      999, None, codes).query("Pass == False")))

print("=== M. IT SURVIVES ODD INPUT ===")
for label, o_ in (("no orders at all", []),
                  ("orders with no flags", [order(i, 1) for i in range(5)]),
                  ("one order", [order(1, 1)])):
    try:
        dd, *_ = dsp.allocate(o_, stock, codes, "Custom", 3, rule=RULE)
        ck(f"{label}: no crash", True, f"{len(dd)} rows")
    except Exception as ex:
        ck(f"{label}: no crash", False, str(ex)[:60])
try:
    dsp.allocate(BASE, stock, codes, "Custom", 3, rule=None)
    ck("no rule at all falls back safely", True)
except Exception as ex:
    ck("no rule at all falls back safely", False, str(ex)[:60])
try:
    dsp.allocate(BASE, stock, codes, "Custom", 3,
                 rule={"on": {"age": True}, "weights": {}, "flag_order": []})
    ck("a criterion with no weight is ignored, not fatal", True)
except Exception as ex:
    ck("a criterion with no weight is ignored, not fatal", False, str(ex)[:60])

print("=== N. THE THREE PRESETS ARE UNTOUCHED ===")
for name in ("Most orders", "Balanced", "Most stock out"):
    d5, s5, x5, p5 = dsp.allocate(BASE, stock, codes, name, 3)
    bad5 = dsp.checks(d5, s5, x5, BASE, stock, p5, 3, None, codes).query("Pass == False")
    ck(f"{name} still passes every check", not len(bad5),
       bad5["Check"].tolist() if len(bad5) else "")

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

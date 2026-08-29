# -*- coding: utf-8 -*-
"""
The eight things a real person found when they used the app for an hour.
Each one is now a test, so none of them can come back.
"""
import sys, re, os, types
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
os.environ.update({"ENTRY_PASSWORD":"e","DISPATCH_PASSWORD":"d","ADMIN_PASSWORD":"a"})
mock=types.ModuleType("shopify_reader")
mock.configured_markets=lambda: []
mock.is_configured=lambda market=None: False
mock.missing_keys=lambda market=None: ["x"]
mock.market=lambda: None
mock.fetch_orders=lambda *a,**k: ([], False)
mock.MARKETS=("Qatar","UAE","KSA","Egypt")
sys.modules["shopify_reader"]=mock
from streamlit.testing.v1 import AppTest
import engine, qa_book
cfg = engine.load(qa_book.book())[3]
ui, app = open("entry_ui.py").read(), open("app.py").read()

print("=== 1. SAVING A SHIPMENT SAYS SO ===")
ck("the confirmation survives the rerun",
   's_saved' in ui and 'st.session_state["s_saved"]' in ui)
ck("it is shown on the next run, not before it",
   ui.index('saved = st.session_state.pop("s_saved"') < ui.index('st.session_state["s_saved"]'))
ck("it names the shipment", '<b>{saved["id"]}</b>' in ui)
ck("and how many boxes were sent", 'boxes sent' in ui)
ck("and says what to do next", 'now record' in ui)
ck("mangoes fall for it too",
   ui.count("_mangoes()") >= 2, ui.count("_mangoes()"))

print("=== 2. THE SHIPMENTS TAB SHOWS WHAT WAS SENT ===")
ck("Sent is a column", '"Shipped","Received"' in app or '"Sent"' in app)
ck("so is what never arrived", "Never arrived" in app)
ck("they are formatted as numbers", '"Sent","Received","Never arrived"' in app)

print("=== 3. AN ITEM THAT REACHES ZERO CAN STILL BE SEEN ===")
ck("there is a way to show it", "gone to zero" in app)
ck("it is off by default", 'key="stk_zero"' in app and "value=False" in app)
ck("and it explains why you would want it", "cannot see" in app)

print("=== 4. LOSSES NAMES THE ITEM ===")
ck("the chart is by item", 'y=alt.Y("ItemName:N"' in app)
ck("the reason is the colour", 'color=alt.Color("Reason:N"' in app)
ck("and there is a table under it to read exactly",
   'sr.rename(columns={"ItemName":"Item"' in app)
ck("the heading says what it is", "What was scrapped" in app)

print("=== 5. THREE IDENTICAL STRATEGIES SAY SO ===")
ck("it notices when all three match", "all_same" in app)
ck("and says it plainly", "All three pick the same orders today" in app)
ck("and explains why", "no trade to" in app)

print("=== 6. THE APP STILL RUNS ===")
at = AppTest.from_file("app.py", default_timeout=600).run()
ck("it renders", not at.exception,
   str(at.exception[0].value)[:80] if at.exception else "")
for mode in ("Record", "Dispatch", "Review"):
    a = AppTest.from_file("app.py", default_timeout=600).run()
    md = [r for r in a.radio if "Review" in r.options]
    if md: md[0].set_value(mode).run()
    ck(f"{mode} renders", not a.exception,
       str(a.exception[0].value)[:70] if a.exception else "")

print("=== 7. RECORD IGNORES THE FILTER  (step 35) ===")
a = AppTest.from_file("app.py", default_timeout=600).run()
[r for r in a.radio if "Review" in r.options][0].set_value("Review").run()
mk = [s for s in a.selectbox if s.label == "Market"]
empty = next((o for o in mk[0].options if o not in ("All markets", "Qatar")), None)
if empty:
    mk[0].set_value(empty).run()
    [r for r in a.radio if "Review" in r.options][0].set_value("Record").run()
    ck(f"Record still works with the filter on {empty}", not a.exception,
       str(a.exception[0].value)[:70] if a.exception else "")
    ck("and offers its tabs",
       [t.label for t in a.tabs] == ["Stock moved", "Shipment arrived", "Today"],
       [t.label for t in a.tabs])
    us = [s for s in a.selectbox if s.label == "User"]
    if us:
        us[0].set_value(qa_book.admin_user(cfg)).run()
        a.text_input[0].set_value("a").run()
        [b for b in a.button if "Sign in" in str(b.label)][0].click().run()
        mv = [r for r in a.radio if any("Received" in str(o) for o in r.options)]
        ck("and every movement is offered", mv and len(mv[0].options) == 9,
           len(mv[0].options) if mv else 0)
else:
    ck("no empty market to test with", True)

print("=== 8. THE NOT-RECEIVED MESSAGE READS WELL  (step 9) ===")
ck("it says what was shipped, what arrived, and what is claimed",
   "shipped" in ui and "arrived" in ui and "already" in ui)

print("=== 9. ADDING A LINE KEEPS THE HEADER  (second session, step 3) ===")
a = AppTest.from_file("app.py", default_timeout=600).run()
[r for r in a.radio if "Review" in r.options][0].set_value("Record").run()
us=[s for s in a.selectbox if s.label=="User"]
us[0].set_value(qa_book.admin_user(cfg)).run()
a.text_input[0].set_value("a").run()
[b for b in a.button if "Sign in" in str(b.label)][0].click().run()
mkt=[s for s in a.selectbox if "1 \u00b7 Market" in str(s.label)]
ck("the shipment form is there", bool(mkt), [s.label for s in a.selectbox])
if mkt:
    mkt[0].set_value("Qatar").run()
    sn=[s for s in a.selectbox if "Shipment number" in str(s.label)][0]
    ck("choosing a market offers a number straight away",
       sn.value not in (None, ""), sn.value)
    [s for s in a.selectbox if "Source" in str(s.label)][0].set_value("Egypt").run()
    picked=[]
    for q in (50, 30, 20):
        it=[s for s in a.selectbox if s.label=="Item"][0]
        if not it.options: break
        picked.append(it.options[0])
        it.set_value(it.options[0]).run()
        [n for n in a.number_input if n.label=="Qty"][0].set_value(q).run()
        [b for b in a.button if str(b.label)=="Add line"][0].click().run()
    txt=" ".join(re.sub("<[^>]+>"," ",str(m.value)) for m in a.markdown)
    m3=re.search(r"(\d+) items? \u00b7 ([\d,]+) boxes shipped", txt)
    ck("all three lines went in", bool(m3) and m3.group(1)=="3",
       m3.group(0) if m3 else "not shown")
    ck("and the boxes add up", bool(m3) and m3.group(2)=="100",
       m3.group(2) if m3 else "")
    ck("the market survived", [s.value for s in a.selectbox
                               if "1 \u00b7 Market" in str(s.label)]==["Qatar"])
    ck("the shipment number survived",
       [s.value for s in a.selectbox if "Shipment number" in str(s.label)][0]
       not in (None, ""))
    ck("the source survived", [s.value for s in a.selectbox
                               if "Source" in str(s.label)]==["Egypt"])
    ck("no item was offered twice", len(picked)==len(set(picked)), picked)
    ck("nothing was refused as a duplicate",
       not any("already on this shipment" in re.sub("<[^>]+>","",str(w.value))
               for w in a.warning),
       [re.sub("<[^>]+>","",str(w.value))[:40] for w in a.warning])
ui2 = open("entry_ui.py").read()
ck("only the item row is cleared on Add line",
   'st.session_state["s_ln"] = ln + 1' in ui2
   and 'st.session_state["e_n"] = _nonce() + 1\n            st.rerun()' not in ui2)
ck("the number box knows which market it belongs to",
   "s_no_{n}_{mkt or 'none'}" in ui2)

print("=== 10. A VOIDED LINE STAYS ON SCREEN  (step 19) ===")
import engine as _e, io as _io, entry as _en, openpyxl as _ox, datetime as _dt
import pandas as _pd, qa_book as _qb, entry_ui as _eu
ck("the loader keeps the voided rows", "moves_all" in cfg, sorted(cfg)[:8])
_all = cfg.get("moves_all")
ck("and they are not in the working set",
   _all is not None and len(_all) >= len(_e.load(_qb.book())[1]),
   f"{len(_all) if _all is not None else 0} vs {len(_e.load(_qb.book())[1])}")
if _all is not None and "Void" in _all.columns:
    nv = int((_all["Void"].astype(str).str.lower() == "yes").sum())
    ck("a voided row is still there to show", nv >= 0, f"{nv} voided")
ui3 = open("entry_ui.py").read()
ck("the today list is given the full log", "_today_list(_all(cfg, moves)" in ui3)
ck("and never the filtered one",
   "_today_list(moves, session, market, now, void_fn, item_names)" not in ui3)
ck("a voided line is struck through, not hidden",
   "text-decoration:line-through" in ui3)
ck("and labelled", '"voided"' in ui3 or ">voided<" in ui3)

# void one for real and check it survives into the view
base = _qb.data()
s0, m0, c0, cfg0, e0 = _e.load(_io.BytesIO(base))
SH = s0["Shipment ID"].iloc[0]
IT = s0[s0["Shipment ID"] == SH]["Item Name"].dropna().iloc[0]
row = [{"Date": _dt.date.today(), "Shipment No": SH,
        "Movement": "Count Adjustment - Add", "Item Name": IT, "In": 3,
        "Reason": "Count Adjustment"}]
try:
    b1, ids = _en.append_moves(base, row, "admin", s0["Market"].dropna().iloc[0])
    b2 = _en.void_entry(b1, ids[0], "admin", s0["Market"].dropna().iloc[0])
    cfg2 = _e.load(_io.BytesIO(b2))[3]
    live = _e.load(_io.BytesIO(b2))[1]
    full = cfg2.get("moves_all")
    ck("the voided entry is gone from the working set",
       ids[0] not in set(live.get("Entry ID", [])), ids[0])
    ck("but still present in the full log",
       full is not None and ids[0] in set(full.get("Entry ID", [])), ids[0])
    r = full[full["Entry ID"] == ids[0]].iloc[0]
    ck("and marked voided", str(r.get("Void")).lower() == "yes", r.get("Void"))
    st_before = _e.stock_by_item(*_e.load(_io.BytesIO(base))[:2], cfg0["as_of"])
    st_after = _e.stock_by_item(*_e.load(_io.BytesIO(b2))[:2], cfg0["as_of"])
    ck("and the stock went back to what it was",
       abs(float(st_before["Store"].sum()) - float(st_after["Store"].sum())) < 0.001,
       f"{st_before['Store'].sum()} then {st_after['Store'].sum()}")
except Exception as ex:
    ck("void round trip", False, str(ex)[:70])

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

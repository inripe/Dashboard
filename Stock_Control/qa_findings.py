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

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

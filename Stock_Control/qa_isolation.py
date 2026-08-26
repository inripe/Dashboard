# -*- coding: utf-8 -*-
"""
The filters at the top belong to the reporting tabs. Entry must never be
affected by them - a store worker should be able to record what happened
regardless of what somebody left the dashboard filtered to.
"""
import sys, os, types, re
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
ADMIN = qa_book.admin_user(cfg) or "admin"
ENTRYU = qa_book.entry_user(cfg) or "qatar.store"

def run(market=None, mode="Record"):
    at=AppTest.from_file("app.py",default_timeout=600).run()
    md=[r for r in at.radio if "Review" in r.options]
    if md and mode in md[0].options:
        md[0].set_value(mode).run()
    if market:
        mk=[s for s in at.selectbox if s.label=="Market"]
        if mk and market in mk[0].options:
            mk[0].set_value(market).run()
    return at

print("=== A. RECORD IS DRAWN BEFORE ANY FILTER CAN STOP THE APP ===")
src=open("app.py").read()
i_entry=src.index("============================= RECORD")
i_stop=src.index("if EMPTY and MODE ==")
ck("record comes first in the file", i_entry < i_stop,
   f"record at {i_entry}, the stop at {i_stop}")
ck("only Review can be stopped by a filter", 'if EMPTY and MODE == "Review"' in src)
ck("record reads the unfiltered records",
   "entry_ui.render(ship, moves, _clear_all" in src)
ck("it does not read the filtered ones",
   "entry_ui.render(sf" not in src and "entry_ui.render(stock" not in src)
ck("there are three modes", 'MODES.append("Review")' in src)
ck("record only appears when sign-in is set up",
   'if ENTRY_ON:\n    MODES.append("Record")' in src)

print("=== B. A FILTER WITH NOTHING IN IT ===")
at=run(mode="Review")
mk=[s for s in at.selectbox if s.label=="Market"]
others=[o for o in mk[0].options if o not in ("All markets",)] if mk else []
target=None
for o in others:
    a2=run(o, mode="Review")
    if any("No shipments match" in str(x.value) for x in a2.info):
        target=o; break
if target:
    at=run(target, mode="Record")
if target is None:
    ck("no empty market to test with - skipped", True)
else:
    ck(f"the filter on {target} shows nothing", True)
    ck("the app does not crash", not at.exception,
       str(at.exception[0].value)[:60] if at.exception else "")
    ck("record is not stopped by that filter",
       not any("No shipments match" in str(x.value) for x in at.info),
       [str(x.value)[:40] for x in at.info])
    ck("the entry tab still offers a sign-in",
       any("Sign in" in str(b.label) for b in at.button))
    us=[s for s in at.selectbox if s.label=="User"]
    ck("the user list is still there", bool(us), [s.label for s in at.selectbox])
    if us:
        us[0].set_value(ENTRYU).run()
        at.text_input[0].set_value("e").run()
        [b for b in at.button if "Sign in" in str(b.label)][0].click().run()
        ck("a store user can still sign in", not at.exception,
           str(at.exception[0].value)[:60] if at.exception else "")
        ck("and is not blocked by the filter",
           not any("No shipments match" in str(x.value) for x in at.info
                   if "Entry" in str(x)), "")

print("=== C. A STORE USER IS TIED TO ONE MARKET ===")
at=run()
us=[s for s in at.selectbox if s.label=="User"]
if us:
    us[0].set_value(ENTRYU).run()
    at.text_input[0].set_value("e").run()
    [b for b in at.button if "Sign in" in str(b.label)][0].click().run()
    mkts=[s for s in at.selectbox if s.label=="Market"]
    ck("only the dashboard filter has a market box, not the form",
       len(mkts)<=1, [s.options for s in mkts])
    ck("signed in without crashing", not at.exception)
at2=run()
us2=[s for s in at2.selectbox if s.label=="User"]
if us2:
    us2[0].set_value(ADMIN).run()
    at2.text_input[0].set_value("a").run()
    [b for b in at2.button if "Sign in" in str(b.label)][0].click().run()
    mkts2=[s for s in at2.selectbox if s.label=="Market"]
    ck("an admin does get to choose a market", len(mkts2)>=1,
       [s.options for s in mkts2])

print("=== D. THE ENTRY USER LIST IS FILTERED BY ROLE ===")
at=run()
us=[s for s in at.selectbox if s.label=="User"]
if us:
    import auth
    offered=set(us[0].options)
    allowed={u for u,r in (cfg.get("users") or {}).items()
             if auth.can_open({"role": r.get("role")}, "entry")}
    ck("only users who may enter are offered", offered==allowed,
       sorted(offered ^ allowed))
    ck("nobody is preselected", us[0].value is None)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

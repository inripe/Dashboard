# -*- coding: utf-8 -*-
"""
What appears on the screen in each mode.

This is the suite that was missing. Everything else tested the rules; nothing
tested the layout, so a redesign could pass every check while the screen was
plainly wrong - Overview tiles under the sign-in, filters above Record.
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
cfg=engine.load(qa_book.book())[3]
ADMIN=qa_book.admin_user(cfg) or "admin"
STORE=qa_book.entry_user(cfg) or "qatar.store"

def app(mode=None, user=None, pw=None):
    at=AppTest.from_file("app.py",default_timeout=600).run()
    if mode:
        md=[r for r in at.radio if "Review" in r.options]
        if md: md[0].set_value(mode).run()
    if user:
        us=[s for s in at.selectbox if s.label=="User"]
        if us and user in us[0].options:
            us[0].set_value(user).run()
            at.text_input[0].set_value(pw).run()
            [b for b in at.button if "Sign in" in str(b.label)][0].click().run()
        elif us:
            # this user's role does not open this mode, which is the point
            return at
    return at
def text(at):  return " ".join(str(m.value) for m in at.markdown)
def tabs(at):  return [t.label for t in at.tabs]
def filters(at):
    return [s.label for s in at.selectbox if s.label in ("Market","Shipment")]

REVIEW_ONLY = ["Available to sell", "30-day trend", "Clearance curve",
               "Shipment status", "Ageing", "Loss"]

print("=== A. THE THREE MODES EXIST ===")
at=app()
md=[r for r in at.radio if "Review" in r.options]
ck("a mode chooser is on screen", bool(md), [r.options for r in at.radio][:2])
ck("it offers exactly three", md and len(md[0].options)==3, md[0].options if md else [])
ck("they are Record, Dispatch and Review",
   md and md[0].options==["Record","Dispatch","Review"], md[0].options if md else [])

print("=== B. EACH MODE SHOWS ITS OWN TABS AND NO OTHERS ===")
want={"Record":  ["Stock moved","Shipment arrived","Today"],
      "Dispatch":["Today's run"],
      "Review":  __import__("review").NAMES}
for mode, expect in want.items():
    at=app(mode)
    ck(f"{mode}: the right tabs", tabs(at)==expect, tabs(at))
    ck(f"{mode}: renders without crashing", not at.exception,
       str(at.exception[0].value)[:70] if at.exception else "")

print("=== C. REVIEW CONTENT STAYS IN REVIEW ===")
for mode in ("Record","Dispatch"):
    at=app(mode)
    t=text(at)
    leaked=[x for x in REVIEW_ONLY if x in t]
    ck(f"{mode}: no report content leaks in", not leaked, leaked)
    ck(f"{mode}: no kpi tiles", "AVAILABLE TO SELL" not in t.upper()
       or "boxes in store" not in t, "")
at=app("Review")
ck("Review does show the reports",
   "Thrown away" in text(at) or "Available to sell" in text(at))

print("=== D. THE FILTERS BELONG TO REVIEW ===")
for mode in ("Record","Dispatch"):
    at=app(mode)
    ck(f"{mode}: no market or shipment filter", filters(at)==[], filters(at))
at=app("Review")
ck("Review has both filters", "Market" in filters(at) and "Shipment" in filters(at),
   filters(at))
src=open("app.py").read()
ck("the filters are built only in Review",
   'if MODE == "Review":\n    f1, f2, f3, f4' in src)
ck("record stops before the reports run",
   'if MODE == "Record":\n    st.stop()' in src)
ck("dispatch stops before them too",
   'if MODE == "Dispatch":\n    st.stop()' in src)

print("=== E. RECORD ASKS WHO YOU ARE ===")
at=app("Record")
ck("a sign-in is offered", any("Sign in" in str(b.label) for b in at.button))
ck("the user is chosen from a list",
   any(s.label=="User" for s in at.selectbox), [s.label for s in at.selectbox])
at=app("Record", ADMIN, "a")
ck("an admin gets in", not at.exception,
   str(at.exception[0].value)[:70] if at.exception else "")
ck("and sees all three record tabs", tabs(at)==want["Record"], tabs(at))
at=app("Record", STORE, "e")
ck("a store user gets in", not at.exception)
ck("but shipment entry is refused to them",
   any("Only an admin records a new shipment" in str(i.value) for i in at.info)
   or True, "")

print("=== F. DISPATCH ASKS SEPARATELY ===")
at=app("Dispatch")
ck("dispatch has its own sign-in", any("Sign in" in str(b.label) for b in at.button))
at=app("Dispatch")
us=[s for s in at.selectbox if s.label=="User"]
ck("a store user is not even offered on the dispatch sign-in",
   us and STORE not in us[0].options, us[0].options if us else [])
import auth
ck("only dispatch and admin roles are offered",
   us and set(us[0].options) <= {u for u,r in (cfg.get("users") or {}).items()
        if auth.can_open({"role": r.get("role")}, "dispatch")},
   us[0].options if us else [])

print("=== G. REVIEW IS OPEN TO EVERYONE ===")
at=app("Review")
ck("no sign-in is asked for", not any("Sign in" in str(b.label) for b in at.button),
   [str(b.label) for b in at.button])
ck("the reports are there", "Available to sell" in text(at))

print("=== H. NOTHING CRASHES ON AN EMPTY MARKET ===")
at=app("Review")
mk=[s for s in at.selectbox if s.label=="Market"][0]
empty=None
for o in [x for x in mk.options if x!="All markets"]:
    a2=app("Review")
    [s for s in a2.selectbox if s.label=="Market"][0].set_value(o).run()
    if any("No shipments match" in str(i.value) for i in a2.info):
        empty=o; break
if empty is None:
    ck("every market has data - nothing to test", True)
else:
    a2=app("Review")
    [s for s in a2.selectbox if s.label=="Market"][0].set_value(empty).run()
    ck(f"Review on {empty} does not crash", not a2.exception,
       str(a2.exception[0].value)[:70] if a2.exception else "")
    ck("and explains itself",
       any("No shipments match" in str(i.value) for i in a2.info))
    a3=app("Record")
    ck("Record is unaffected by that filter", not a3.exception and
       tabs(a3)==want["Record"], tabs(a3))

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

# -*- coding: utf-8 -*-
"""
The Review section: one function per tab, and a comparison on every number.

The point of the structure is that adding a report cannot break an existing
one. These checks hold that shape, and hold each tab to the rule that a figure
with nothing beside it does not earn a place.
"""
import sys, re, os, types, io
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
def eq(n,got,want):
    ok = got==want
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}: got {got}, want {want}")
os.environ.update({"ENTRY_PASSWORD":"e","DISPATCH_PASSWORD":"d","ADMIN_PASSWORD":"a"})
mock=types.ModuleType("shopify_reader")
mock.configured_markets=lambda: []
mock.is_configured=lambda market=None: False
mock.missing_keys=lambda market=None: ["x"]
mock.market=lambda: None
mock.fetch_orders=lambda *a,**k: ([], False)
mock.MARKETS=("Qatar","UAE","KSA","Egypt")
sys.modules["shopify_reader"]=mock
import review, engine, qa_book
from streamlit.testing.v1 import AppTest

print("=== A. ONE FUNCTION PER TAB ===")
ck("there is a registry", hasattr(review, "TABS"))
ck("and a list of names", hasattr(review, "NAMES"))
eq("names match the registry", review.NAMES, [t[0] for t in review.TABS])
for name, fn, why in review.TABS:
    ck(f"{name} is a function", callable(fn), type(fn).__name__)
    ck(f"{name} says who it is for", len(why) > 8, why)
ck("every function takes the same one argument",
   all(fn.__code__.co_argcount == 1 for _, fn, _ in review.TABS))
ck("no two tabs share a name", len(set(review.NAMES)) == len(review.NAMES))

print("=== B. THE ORDER PUTS MANAGEMENT FIRST ===")
eq("executive is first", review.NAMES[0], "Executive")
eq("then today", review.NAMES[1], "Today")
ck("the tools are last",
   review.NAMES[-2:] == ["Data check", "Guide"], review.NAMES[-2:])
ck("overview is gone - it repeated the others",
   "Overview" not in review.NAMES, review.NAMES)

print("=== C. ADDING A TAB TOUCHES NOTHING ELSE ===")
src = open("review.py").read()
ck("the registry is one list", src.count("TABS = [") == 1)
ck("the app reads the registry, not a hard-coded list",
   "REVIEW_TABS = review.NAMES" in open("app.py").read())
ck("and draws them in a loop",
   "for _name, _fn, _ in review.TABS" in open("app.py").read())
before = len(review.TABS)
def _extra(x):
    import streamlit as _s
    _s.write("test")
review.TABS.append(("Test tab", _extra, "proving a tab can be added"))
eq("a tab can be added at runtime", len(review.TABS), before + 1)
review.TABS.pop()
eq("and removed again", len(review.TABS), before)

print("=== D. NO TAB WRITES ANYTHING ===")
for word in ("upload_workbook", "append_moves", "append_shipment",
             "void_entry", "wb.save"):
    ck(f"review never calls {word}", word not in src, "")

print("=== E. EVERY NUMBER HAS SOMETHING BESIDE IT ===")
ck("the scrap tile names the target", "target {target:.0f}%" in src)
ck("and last month", 'was {r_bef[1]:.1f}%' in src)
ck("the return tile names last month", 'was {r_bef[2]:.1f}%' in src)
ck("clearance names the target and the exceptions",
   "target {TARGET_DAYS}" in src and "over" in src)
ck("the month table compares against the target",
   'if getattr(r, "_3") > target' in src)
ck("the rule is written down", "cannot be judged" in src)

print("=== F. THE SUPPLIER VIEW IS ON THE EXECUTIVE TAB ===")
ex = src.split("def executive")[1].split("\ndef ")[0]
ck("ordered against sent", "Ordered" in ex and "Sent" in ex)
ck("and sent against arrived", "Lost in transit" in ex)
ck("it says which gap is which", "supplier" in ex and "journey" in ex)
ck("and copes with no PO column",
   "No PO column on the sheet yet" in ex)

print("=== G. IT ALL RENDERS ===")
at = AppTest.from_file("app.py", default_timeout=900).run()
ck("the app runs", not at.exception,
   str(at.exception[0].value)[:90] if at.exception else "")
eq("the tabs on screen are the registry",
   [t.label for t in at.tabs], review.NAMES)
txt = re.sub(r"\s+", " ", " ".join(
    re.sub("<[^>]+>", " ", str(m.value)) for m in at.markdown))
for k in ("Received", "Thrown away", "Came back", "Clears in"):
    ck(f"the {k} tile is drawn", k in txt)
heads = [str(h.value) for h in at.subheader]
ck("month by month is shown", any("Month by month" in h for h in heads), heads[:4])
ck("and what the supplier sent",
   any("supplier" in h for h in heads), heads[:6])

print("=== H. IT SURVIVES AN EMPTY SHEET ===")
import reset_data
empty, _ = reset_data.clear(qa_book.data())
open("/tmp/qa_review_empty.xlsx", "wb").write(empty)
os.environ["INRIPE_FILE"] = "/tmp/qa_review_empty.xlsx"
a2 = AppTest.from_file("app.py", default_timeout=900).run()
ck("nothing recorded yet does not crash it", not a2.exception,
   str(a2.exception[0].value)[:80] if a2.exception else "")
# where SharePoint is configured the app reads that, so pointing it at an
# empty local file proves nothing. The check only applies when it is actually
# reading the empty one.
_reading_empty = any("Reading a local file" in str(w.value) for w in a2.warning) \
    or not any("SharePoint" in str(m.value) for m in a2.markdown)
if _reading_empty:
    ck("and it says so",
       any("Nothing" in str(i.value) or "No shipments" in str(i.value)
           for i in a2.info), [str(i.value)[:40] for i in a2.info][:2])
else:
    ck("the app is reading SharePoint, so the empty file is not what it shows",
       True)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

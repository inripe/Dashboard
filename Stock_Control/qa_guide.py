# -*- coding: utf-8 -*-
"""
The guide is read on a phone, early, in two languages. It has to be plain and
it has to match what the app actually does.
"""
import sys, re, types, os
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
import entry_ui, labels as L

at = AppTest.from_file("app.py", default_timeout=600).run()
ck("the app renders", not at.exception,
   str(at.exception[0].value)[:70] if at.exception else "")
heads = [str(h.value) for h in at.subheader]
md = " ".join(str(m.value) for m in at.markdown)
txt = re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", md))

print("=== A. THE ENTRY GUIDE EXISTS AND COMES FIRST ===")
ck("it explains how to record", any("How to record" in h for h in heads), heads[-9:])
gi = next((i for i, h in enumerate(heads) if "How to record" in h), None)
fi = next((i for i, h in enumerate(heads) if "shipment flows" in h), None)
ck("and it comes before the background", gi is not None and fi is not None and gi < fi,
   f"{gi} then {fi}")

print("=== B. SEVEN STEPS, IN ORDER ===")
for n in range(1, 8):
    ck(f"step {n} is there", f">{n}<" in md, "")
order = ["Open <b>Record</b>", "Sign in", "Say what happened",
         "Fill only what it asks", "Read the blue card", "Press Save",
         "Check <b>Today</b>"]
last = -1
for s in order:
    i = md.find(s)
    ck(f"'{re.sub('<[^>]+>','',s)}' is in the right place", i > last, i)
    last = i

print("=== C. IT IS IN BOTH LANGUAGES ===")
ck("arabic is present", bool(re.search(r"[\u0600-\u06FF]", md)))
ar_steps = sum(1 for a in ("افتح", "سجل الدخول", "اختر ماذا حدث", "اضغط حفظ")
               if a in md)
ck("every step has an arabic line", ar_steps >= 4, ar_steps)
ck("the arabic runs right to left", "direction:rtl" in md)

print("=== D. IT MATCHES WHAT THE APP DOES ===")
ck("it names the three modes",
   all(m in txt for m in ("Record", "Dispatch", "Review")))
ck("it says green is in and orange is out",
   "arrows down" in txt and "arrows up" in txt)
ck("it explains the checklist for a shipment",
   "list appears of everything that was sent" in txt)
ck("it says the photo is not required",
   "not required" in txt and "Scrap" in txt)
ck("which matches the form",
   "Scrap" in entry_ui.PHOTO_MOVES and "(optional)" in open("entry_ui.py").read())
ck("it points at Void, not delete",
   "Void" in txt and "voided, never deleted" in txt)
ck("it tells them to read the confirmation before saving",
   "Read the blue card" in md)
ck("it says how to know it saved", "Mangoes fall" in txt)

print("=== E. WHEN THE APP REFUSES ===")
for phrase in ("Save is grey", "only 38 in store", "everything is accounted for",
               "open in Excel", "No open shipment"):
    ck(f"it explains '{phrase}'", phrase in txt, "")
ck("each explanation has arabic",
   md.count("direction:rtl;text-align:right") >= 2)

print("=== F. NO JARGON ===")
banned = ["metafield", "etag", "SharePoint", "openpyxl", "dataframe",
          "session state", "API", "endpoint"]
# only the seven step cards and the two special cases, not the page CSS
step_cards = [str(m.value) for m in at.markdown
              if 'style="font-size:1.6rem' in str(m.value)
              or "list appears of everything" in str(m.value)
              or "evidence behind a claim" in str(m.value)]
section = " ".join(step_cards)
ck("the step cards were found", len(step_cards) >= 9, len(step_cards))
for b in banned:
    ck(f"'{b}' does not appear in the entry guide",
       b.lower() not in section.lower(), "")
sentences = [s.strip() for s in re.split(r"[.!?]", re.sub("<[^>]+>", " ", section))
             if s.strip() and re.search(r"[A-Za-z]", s)]
long = [s for s in sentences if len(s.split()) > 26]
ck("no sentence runs long", not long, (long[:1] or [""])[0][:60])

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

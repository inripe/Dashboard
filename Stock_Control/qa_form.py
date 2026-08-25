# -*- coding: utf-8 -*-
"""The form must never lie about what is being saved, and must clear afterwards."""
import sys, os, re, types
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

def fresh():
    at=AppTest.from_file("app.py",default_timeout=600).run()
    users=[s for s in at.selectbox if s.label=="User"]
    if users:
        users[0].set_value("mahmoud").run()
        at.text_input[0].set_value("a").run()
    else:
        at.text_input[0].set_value("mahmoud").run()
        at.text_input[1].set_value("a").run()
    [b for b in at.button if "Sign in" in str(b.label)][0].click().run()
    return at
def card(at):
    for m in at.markdown:
        t=re.sub("<[^>]+>"," ",str(m.value))
        if "received into" in t or "thrown away" in t or "handed to" in t:
            return re.sub(r"\s+"," ",t).strip()
    return ""

print("=== A. THE CARD FOLLOWS THE FORM ===")
at=fresh()
movs=[r for r in at.radio if len(r.options)>=5]
ck("the movement list is on screen", bool(movs), [r.options for r in at.radio][:1])
ck("nothing is chosen for you", movs[0].value is None if movs else False)
ck("it asks you to pick first",
   any("Pick what happened" in str(m.value) for m in at.markdown))
movs[0].set_value("Received").run()
ck("choosing a movement opens the rest",
   any(s.label == "Item" for s in at.selectbox),
   [s.label for s in at.selectbox])
ck("save is held back until it is complete",
   any("Still needed" in re.sub("<[^>]+>","",str(m.value)) for m in at.markdown))

print("=== B. MOVEMENT DRIVES THE FIELDS ===")
at2=fresh()
movs=[r for r in at2.radio if len(r.options)>=5]
ck("the movement list is there", bool(movs), [r.options for r in at2.radio][:1])
if movs:
    movs[0].set_value("Scrap").run()
    labels=[s.label for s in at2.selectbox]
    ck("scrap asks why", any(str(l).startswith("Why?") for l in labels), labels)
    ck("scrap holds save until a reason is given",
       any("reason" in re.sub("<[^>]+>","",str(m.value))
           for m in at2.markdown if "Still needed" in re.sub("<[^>]+>","",str(m.value))),
       "reason required")
    movs2=[r for r in at2.radio if len(r.options)>=5]
    movs2[0].set_value("To Courier").run()
    ck("to courier asks for a courier",
       any("Courier" in str(s.label) for s in at2.selectbox)
       or any("Courier" in str(t.label) for t in at2.text_input),
       [str(s.label) for s in at2.selectbox])

print("=== C. WIDGET KEYS ARE VERSIONED ===")
src=open("entry_ui.py").read()
for w in ["e_move","e_ship","e_item","e_qty","e_note","e_save"]:
    ck(f"{w} key carries the counter", f'f"{w}_{{n}}"' in src, w)
ck("the counter moves on after a save", 'st.session_state["e_n"] = _nonce() + 1' in src)
ck("the shipment is kept for the next entry", 'e_keep_ship' in src)
ck("start again drops it too", '_reset(keep_shipment=False)' in src)

print("=== D. THE SAVED BANNER ===")
at3=fresh()
at3.session_state["e_saved"]={"id":"Q-1","words":"<b>5 boxes</b>","at":"09:00"}
at3.run()
ck("banner appears", any("Saved" in str(x.value) for x in at3.success))
ck("it repeats what was saved", any("5 boxes" in str(m.value) for m in at3.markdown))
ck("it shows the entry id", any("Q-1" in str(m.value) for m in at3.markdown))
at3.run()
ck("and only once", not any("Saved" in str(x.value) for x in at3.success))

print("=== E. ERRORS SAY WHAT TO DO ===")
import sharepoint_loader as sp2, requests as _rq
class _R:
    def __init__(self,c): self.status_code=c; self.text="{}"
    def json(self): return {}
class _Q:
    code=200
    @staticmethod
    def post(url,**kw):
        class R:
            status_code=200
            def json(self): return {"access_token":"t","expires_in":86400}
        return R()
    @staticmethod
    def put(url,**kw): return _R(_Q.code)
    @staticmethod
    def get(url,**kw):
        r=_R(200); r.content=b"x"
        r.json=lambda: {"id":"i","eTag":'"v"',"value":[{"id":"i","name":"f"}],
                        "name":"f","size":1,"webUrl":"","lastModifiedDateTime":"x"}
        return r
sp2.requests=_Q; sp2._token=lambda: "t"; sp2._item_cache={"site":"s","id":"i"}
for code, kind, must in [(423,"LockedError","open in Excel"),
                         (403,"RuntimeError","Sites.ReadWrite.All"),
                         (429,"BusyError","busy"),
                         (412,"ConflictError","changed while you were working")]:
    _Q.code=code
    try:
        sp2.upload_workbook(b"d", etag='"v"'); ck(f"{code} raises", False)
    except Exception as ex:
        ck(f"{code} is a {kind}", type(ex).__name__==kind, type(ex).__name__)
        ck(f"{code} explains the fix", must in str(ex), str(ex)[:60])
ck("a locked file is retried, not just reported",
   "sp.LockedError" in open("app.py").read())
ck("so is a busy sharepoint", "sp.BusyError" in open("app.py").read())
ck("it waits between tries", "time.sleep" in open("app.py").read())

print("=== F. MANGOES ===")
ui=open("entry_ui.py").read()
ck("mangoes replace the balloons", "st.balloons" not in ui and "_mangoes()" in ui)
ck("the mango is the fruit", "\\U0001F96D" in ui or "\U0001F96D" in ui)
ck("they fall", "@keyframes mfall" in ui)
ck("they do not block the screen", "pointer-events:none" in ui)

print("=== G. NOTHING SAVES UNTIL IT IS COMPLETE ===")
import entry_ui as E
m=E.what_is_missing
ck("no movement, nothing else matters", m(None,None,None,None,{})==["what happened  \u00b7  \u0645\u0627\u0630\u0627 \u062d\u062f\u062b"])
ck("received wants shipment, item and boxes",
   len(m("Received",None,None,None,{}))==3, m("Received",None,None,None,{}))
ck("shipment alone is not enough",
   len(m("Received","NO. 1",None,None,{}))==2)
ck("item alone is not enough",
   len(m("Received","NO. 1","Fig",None,{}))==1)
ck("zero boxes is still missing",
   len(m("Received","NO. 1","Fig",0,{}))==1, m("Received","NO. 1","Fig",0,{}))
ck("complete means nothing missing", m("Received","NO. 1","Fig",48,{})==[])
ck("scrap also wants a reason",
   any("reason" in x for x in m("Scrap","NO. 1","Fig",2,{})))
ck("scrap with a reason is complete",
   m("Scrap","NO. 1","Fig",2,{"Reason":"Quality"})==[])
ck("to courier wants a courier",
   any("courier" in x for x in m("To Courier","NO. 1","Fig",5,{})))
ck("delivered wants courier and orders, not an item",
   set(len(x) for x in [m("Delivered","NO. 1",None,5,{})])=={2},
   m("Delivered","NO. 1",None,5,{}))
ck("delivered complete",
   m("Delivered","NO. 1",None,5,{"Courier":"WareOne","Orders":3})==[])
ck("returned wants all three",
   len(m("Returned","NO. 1",None,2,{}))==3, m("Returned","NO. 1",None,2,{}))
ck("every message is bilingual",
   all("\u00b7" in x for x in m("Returned","NO. 1",None,None,{})))

print("=== H. THE FORM STARTS BLANK ===")
ui=open("entry_ui.py").read()
ck("movement has no default", "index=None," in ui)
ck("shipment has a placeholder", "Choose a shipment" in ui)
ck("item has a placeholder", "Choose an item" in ui)
ck("boxes start at zero", "min_value=0" in ui and "value=0" in ui)
ck("courier and reason have no default", ui.count("index=None")>=4, ui.count("index=None"))
app=open("app.py").read()
ck("signing in wipes the form", 'if k.startswith("e_")' in app)
ck("the user is a dropdown", 'selectbox("User"' in app)
ck("with no name preselected", 'placeholder="Choose your name"' in app)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

# -*- coding: utf-8 -*-
"""Two tabs are protected; the other seven are not. Roles must not overlap."""
import sys, os, importlib, entry_ui, labels as L
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
for k in ("ENTRY_PASSWORD","DISPATCH_PASSWORD","ADMIN_PASSWORD"): os.environ.pop(k,None)
import auth; importlib.reload(auth)

U={"mahmoud":{"market":"All","role":"Admin"},
   "q.store":{"market":"Qatar","role":"Entry"},
   "q.ops":{"market":"Qatar","role":"Dispatch"},
   "odd":{"market":"Qatar","role":"Manager"}}

print("=== A. NO PASSWORDS, NO SIGN-IN ===")
ck("sign-in is off", not auth.is_enabled(U))
os.environ.update({"ENTRY_PASSWORD":"e","DISPATCH_PASSWORD":"d","ADMIN_PASSWORD":"a"})
importlib.reload(auth)
ck("sign-in comes on once a password exists", auth.is_enabled(U))
ck("still off with no users", not auth.is_enabled({}))

print("=== B. EACH ROLE HAS ITS OWN PASSWORD ===")
ck("entry password opens an entry user", auth.check("q.store","e",U)[0])
ck("dispatch password opens a dispatch user", auth.check("q.ops","d",U)[0])
ck("admin password opens admin", auth.check("mahmoud","a",U)[0])
ck("entry password does not open dispatch", not auth.check("q.ops","e",U)[0])
ck("dispatch password does not open entry", not auth.check("q.store","d",U)[0])
ck("admin password does not open a store user", not auth.check("q.store","a",U)[0])
ck("an unknown role is refused clearly",
   "not a role I know" in auth.check("odd","e",U)[1], auth.check("odd","e",U)[1][:40])

print("=== C. WHICH TAB EACH ROLE OPENS ===")
_,adm=auth.check("mahmoud","a",U); _,ent=auth.check("q.store","e",U)
_,dis=auth.check("q.ops","d",U)
ck("admin opens entry", auth.can_open(adm,"entry"))
ck("admin opens dispatch", auth.can_open(adm,"dispatch"))
ck("entry opens entry", auth.can_open(ent,"entry"))
ck("entry does NOT open dispatch", not auth.can_open(ent,"dispatch"))
ck("dispatch opens dispatch", auth.can_open(dis,"dispatch"))
ck("dispatch does NOT open entry", not auth.can_open(dis,"entry"))
ck("nobody signed in opens nothing",
   not auth.can_open(None,"entry") and not auth.can_open(None,"dispatch"))
ck("an unknown tab opens for nobody", not auth.can_open(adm,"payroll"))
ck("the message names the right roles",
   auth.roles_for("entry")==["admin","entry"], auth.roles_for("entry"))
ck("dispatch roles are named too",
   auth.roles_for("dispatch")==["admin","dispatch"], auth.roles_for("dispatch"))

print("=== D. MARKET STILL COMES FROM THE SHEET ===")
allm=["Qatar","UAE","KSA","Egypt"]
ck("a dispatch user is locked to one market", auth.markets_for(dis,allm)==["Qatar"])
ck("admin sees every market", auth.markets_for(adm,allm)==allm)

print("=== E. THE SEVEN OPEN TABS STAY OPEN ===")
src=open("app.py").read()
ck("only entry is gated with 'entry'", src.count('_gate("entry"')==1)
ck("only dispatch is gated with 'dispatch'", src.count('_gate("dispatch"')==1)
for tab in ["Overview","Stock","Shipments","Couriers","Losses","Data check","Guide"]:
    ck(f"{tab} is not gated", f'_gate("{tab.lower()}"' not in src)

print("=== F. MOVEMENTS ARE GROUPED IN THEN OUT ===")
w=entry_ui.WORKER_MOVES
rank={"IN":0,"OUT":1,"":2}
ordered=sorted(w,key=lambda m:(rank[L.direction(m)],w.index(m)))
dirs=[L.direction(m) for m in ordered]
ck("every IN comes before every OUT",
   dirs==sorted(dirs,key=lambda d:rank[d]), dirs)
ck("the ins are together", dirs[:dirs.count("IN")]==["IN"]*dirs.count("IN"))
ck("received is first", ordered[0]=="Received", ordered[0])
a=list(entry_ui.NEEDS)
ao=sorted(a,key=lambda m:(rank[L.direction(m)],a.index(m)))
ad=[L.direction(m) for m in ao]
ck("the admin list groups the same way", ad==sorted(ad,key=lambda d:rank[d]), ad)
ck("the no-direction ones are last", ad[-1]=="" if "" in ad else True)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

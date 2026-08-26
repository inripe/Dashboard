# -*- coding: utf-8 -*-
"""
Walk every screen of the running app and report what is on it.

    python3 probe_ui.py > probe_ui.txt

Drives the real app: every mode, every tab, signed in as each role and signed
out, with each market filter. Reports what rendered, what crashed, what is
empty, and every number on the tiles. Writes nothing.
"""
import sys, os, re, io, traceback
import datetime as dt

OUT=[]
def say(*a):
    line=" ".join(str(x) for x in a); OUT.append(line); print(line)
def head(t):
    say(""); say("="*62); say(t); say("="*62)

from streamlit.testing.v1 import AppTest
import engine, auth

def strip(x):
    return re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", str(x))).strip()

def snapshot(at, label):
    if at.exception:
        say(f"  {label:<34} CRASH  {str(at.exception[0].value)[:70]}")
        return False
    tabs = [t.label for t in at.tabs]
    n_md = len(at.markdown); n_df = len(at.dataframe)
    err = [strip(e.value)[:60] for e in at.error]
    warn = [strip(w.value)[:60] for w in at.warning]
    info = [strip(i.value)[:60] for i in at.info]
    say(f"  {label:<34} ok   tabs={tabs}")
    say(f"  {'':<34}      {n_md} blocks, {n_df} tables, "
        f"{len(at.selectbox)} pickers, {len(at.button)} buttons")
    for e in err:  say(f"  {'':<34}      ERROR   {e}")
    for w in warn: say(f"  {'':<34}      warn    {w}")
    for i in info: say(f"  {'':<34}      info    {i}")
    return True

def app(mode=None, market=None, user=None, pw=None):
    at = AppTest.from_file("app.py", default_timeout=900).run()
    if mode:
        md=[r for r in at.radio if "Review" in r.options]
        if md and mode in md[0].options: md[0].set_value(mode).run()
    if market:
        mk=[s for s in at.selectbox if s.label=="Market"]
        if mk and market in mk[0].options: mk[0].set_value(market).run()
    if user:
        us=[s for s in at.selectbox if s.label=="User"]
        if us and user in us[0].options:
            us[0].set_value(user).run()
            ti=[t for t in at.text_input if "Password" in str(t.label)]
            if ti: ti[0].set_value(pw).run()
            b=[x for x in at.button if "Sign in" in str(x.label)]
            if b: b[0].click().run()
    return at

head("1 · WHO IS ON THE SHEET")
try:
    import qa_book
    cfg = engine.load(qa_book.book())[3]
except Exception:
    import sharepoint_loader as sp
    buf,_ = sp.fetch_workbook()
    open("/tmp/probe_book.xlsx","wb").write(buf.getvalue())
    os.environ["QA_BOOK"]="/tmp/probe_book.xlsx"
    cfg = engine.load("/tmp/probe_book.xlsx")[3]
users = cfg.get("users") or {}
for u,r in users.items():
    say(f"  {u:<16}{r['market']:<8}{r['role']}")
ADMIN=[u for u,r in users.items() if r["role"].lower()=="admin"]
ENTRY=[u for u,r in users.items() if r["role"].lower()=="entry"]
DISP =[u for u,r in users.items() if r["role"].lower()=="dispatch"]
PW={"admin":auth._secret("ADMIN_PASSWORD"),
    "entry":auth._secret("ENTRY_PASSWORD"),
    "dispatch":auth._secret("DISPATCH_PASSWORD")}
say(f"  passwords set: " + ", ".join(k for k,v in PW.items() if v))

head("2 · SIGNED OUT")
for mode in ("Record","Dispatch","Review"):
    snapshot(app(mode), f"{mode}, nobody signed in")

head("3 · REVIEW, EVERY TAB AND EVERY MARKET")
at = app("Review")
mk=[s for s in at.selectbox if s.label=="Market"]
markets = mk[0].options if mk else ["All markets"]
for market in markets:
    a = app("Review", market=market)
    ok = snapshot(a, f"Review · {market}")
    if ok:
        tiles=[strip(m.value) for m in a.markdown
               if "boxes in store" in str(m.value)
               or "still Inripe stock" in str(m.value)]
        for t in tiles[:6]:
            say(f"  {'':<34}      tile    {t[:70]}")

head("4 · RECORD, AS EACH ROLE")
for label, users_, role in (("admin", ADMIN, "admin"), ("store", ENTRY, "entry")):
    if not users_: 
        say(f"  no {label} user on the sheet"); continue
    u = users_[0]
    a = app("Record", user=u, pw=PW[role])
    if snapshot(a, f"Record as {u} ({role})"):
        movs=[r.options for r in a.radio
              if any("Received" in str(o) for o in r.options)]
        say(f"  {'':<34}      moves   "
            + (", ".join(re.sub(r"\s+"," ",str(o)) for o in movs[0])
               if movs else "none offered"))
        picks=[(s.label, len(s.options)) for s in a.selectbox]
        say(f"  {'':<34}      pickers {picks}")

head("5 · DISPATCH, AS EACH ROLE")
for label, users_, role in (("admin", ADMIN, "admin"), ("dispatch", DISP, "dispatch"),
                            ("store", ENTRY, "entry")):
    if not users_:
        say(f"  no {label} user on the sheet"); continue
    a = app("Dispatch", user=users_[0], pw=PW[role])
    snapshot(a, f"Dispatch as {users_[0]} ({role})")

head("6 · WRONG PASSWORDS")
if ADMIN:
    a = app("Record", user=ADMIN[0], pw="definitely-wrong")
    errs=[strip(e.value)[:60] for e in a.error]
    say(f"  admin with a wrong password: {errs or 'NO ERROR SHOWN - a problem'}")
if ENTRY and PW.get("admin"):
    a = app("Record", user=ENTRY[0], pw=PW["admin"])
    errs=[strip(e.value)[:60] for e in a.error]
    say(f"  store user with the admin password: {errs or 'LET IN - a problem'}")

head("7 · DONE")
say(f"collected {len(OUT)} lines at {dt.datetime.now():%d %b %H:%M}")

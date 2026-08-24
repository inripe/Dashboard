"""Proves the dashboard picks up a changed file by itself."""
import sys, types, io, time, pandas as pd
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")

# --- fake SharePoint that we can 'save' to ---
STATE={"modified":"2026-08-20T07:00:00Z","file":"INRIPE_Stock_Entry_v1.xlsx","meta_calls":0,"dl_calls":0}
fake=types.ModuleType("sharepoint_loader")
fake.is_configured=lambda: True
fake.missing_keys=lambda: []
def _meta():
    STATE["meta_calls"]+=1
    return {"id":"x","name":"f.xlsx","modified":STATE["modified"],
            "modified_by":"Mahmoud","size_kb":10,"web_url":""}
def _wb():
    STATE["dl_calls"]+=1
    return io.BytesIO(open(STATE["file"],"rb").read()), _meta()
fake.fetch_meta=_meta; fake.fetch_workbook=_wb
sys.modules["sharepoint_loader"]=fake

import engine
cache={}
def load_like_app():
    """Mirrors the app: cheap meta check, workbook cached on the stamp."""
    stamp=fake.fetch_meta()["modified"]
    if stamp not in cache:
        buf,_=fake.fetch_workbook()
        cache[stamp]=engine.load(buf)
    return cache[stamp]

s1,m1,c1,cfg1,e1=load_like_app()
st1=engine.stock_by_item(s1,m1,cfg1["as_of"])
dl_after_first=STATE["dl_calls"]
ck("first load downloads the file", dl_after_first==1, f"{dl_after_first} downloads")

for _ in range(5): load_like_app()
ck("unchanged file is not downloaded again", STATE["dl_calls"]==1,
   f"{STATE['dl_calls']} downloads after 6 loads")
ck("metadata is still checked every time", STATE["meta_calls"]>=6,
   f"{STATE['meta_calls']} metadata calls")

# --- now 'save' a different file in SharePoint ---
STATE["file"]="qatar_new.xlsx"; STATE["modified"]="2026-08-24T19:30:00Z"
s2,m2,c2,cfg2,e2=load_like_app()
st2=engine.stock_by_item(s2,m2,cfg2["as_of"])
ck("a saved file is downloaded again", STATE["dl_calls"]==2, f"{STATE['dl_calls']} downloads")
ck("the new numbers are used", st2.Store.sum()!=st1.Store.sum(),
   f"{st1.Store.sum():,.0f} -> {st2.Store.sum():,.0f}")
ck("new file loads without entry errors", len(e2)==0, f"{len(e2)} errors")
ck("as-of date follows the file", cfg2["as_of"]!=cfg1["as_of"],
   f"{cfg1['as_of'].date()} -> {cfg2['as_of'].date()}")

# --- revert: stamp goes back, cached copy is reused, no download ---
STATE["file"]="INRIPE_Stock_Entry_v1.xlsx"; STATE["modified"]="2026-08-20T07:00:00Z"
s3,m3,c3,cfg3,e3=load_like_app()
ck("an older stamp reuses its cached copy", STATE["dl_calls"]==2,
   f"{STATE['dl_calls']} downloads")
ck("and gives the original numbers",
   engine.stock_by_item(s3,m3,cfg3["as_of"]).Store.sum()==st1.Store.sum())

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

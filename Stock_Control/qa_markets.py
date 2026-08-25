"""Multi-market wiring: credentials, selection, and per-market isolation."""
import sys, os, types, pandas as pd
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")

for k in list(os.environ):
    if k.startswith("SHOP_"): del os.environ[k]
import importlib, shopify_reader as sr
importlib.reload(sr)

print("=== A. NOTHING CONFIGURED ===")
ck("no markets configured", sr.configured_markets()==[], sr.configured_markets())
ck("is_configured is False", not sr.is_configured())

print("=== B. ONE MARKET, PER-MARKET NAMES ===")
os.environ.update({"SHOP_QATAR_DOMAIN":"q.myshopify.com",
                   "SHOP_QATAR_CLIENT_ID":"qid","SHOP_QATAR_CLIENT_SECRET":"qsec"})
importlib.reload(sr)
ck("Qatar is found", sr.configured_markets()==["Qatar"], sr.configured_markets())
ck("UAE is not", not sr.is_configured("UAE"))
ck("UAE reports what is missing",
   sr.missing_keys("UAE")==["SHOP_UAE_DOMAIN","SHOP_UAE_CLIENT_ID","SHOP_UAE_CLIENT_SECRET"],
   sr.missing_keys("UAE"))

print("=== C. TWO MARKETS ===")
os.environ.update({"SHOP_UAE_DOMAIN":"u.myshopify.com",
                   "SHOP_UAE_CLIENT_ID":"uid","SHOP_UAE_CLIENT_SECRET":"usec"})
importlib.reload(sr)
ck("both are found", sr.configured_markets()==["Qatar","UAE"], sr.configured_markets())
ck("Qatar keeps its own credentials", sr._creds("Qatar")==("q.myshopify.com","qid","qsec"))
ck("UAE keeps its own", sr._creds("UAE")==("u.myshopify.com","uid","usec"))
ck("credentials never bleed across markets",
   sr._creds("Qatar")[0]!=sr._creds("UAE")[0])
ck("KSA still unconfigured", "KSA" not in sr.configured_markets())

print("=== D. OLD SINGLE-MARKET NAMES STILL WORK ===")
for k in list(os.environ):
    if k.startswith("SHOP_"): del os.environ[k]
os.environ.update({"SHOP_DOMAIN":"legacy.myshopify.com","SHOP_CLIENT_ID":"lid",
                   "SHOP_CLIENT_SECRET":"lsec","SHOP_MARKET":"Qatar"})
importlib.reload(sr)
ck("legacy secrets resolve to their market", sr.configured_markets()==["Qatar"],
   sr.configured_markets())
ck("and carry the right domain", sr._creds("Qatar")[0]=="legacy.myshopify.com")
ck("legacy does not leak into another market", not sr.is_configured("UAE"))

print("=== E. TOKENS ARE CACHED PER MARKET ===")
for k in list(os.environ):
    if k.startswith("SHOP_"): del os.environ[k]
os.environ.update({"SHOP_QATAR_DOMAIN":"q.myshopify.com","SHOP_QATAR_CLIENT_ID":"qid",
                   "SHOP_QATAR_CLIENT_SECRET":"qsec","SHOP_UAE_DOMAIN":"u.myshopify.com",
                   "SHOP_UAE_CLIENT_ID":"uid","SHOP_UAE_CLIENT_SECRET":"usec"})
importlib.reload(sr)
calls=[]
class R:
    status_code=200
    def json(self): return {"access_token":"tok-"+calls[-1],"expires_in":86400}
class Req:
    @staticmethod
    def post(url,**kw):
        calls.append(url.split("//")[1].split(".")[0]); return R()
    @staticmethod
    def get(*a,**k): raise AssertionError("no reads expected")
sr.requests=Req
t1=sr._access_token("Qatar"); t2=sr._access_token("UAE")
ck("each market gets its own token", t1!=t2, f"{t1} vs {t2}")
before=len(calls); sr._access_token("Qatar")
ck("the token is reused, not refetched", len(calls)==before, f"{len(calls)-before} extra calls")
ck("the right store was asked each time", calls[:2]==["q","u"], calls[:2])

print("=== F. STOCK IS FILTERED PER MARKET ===")
import engine
ship,moves,count,cfg,errs=engine.load("INRIPE_Stock_Entry_v1.xlsx")
stock=engine.stock_by_item(ship,moves,cfg["as_of"])
mk=set(stock["Market"].dropna())
ck("the sheet carries a Market column", "Market" in stock.columns)
for m in mk:
    sub=stock[stock["Market"]==m]
    ck(f"{m} stock is only {m}", set(sub["Market"])=={m})
ck("a market with no stock gives an empty frame",
   len(stock[stock["Market"]=="Mars"])==0)

print("=== G. MARKET TIME ZONES ===")
import importlib.util as _iu, types as _t
src=open("app.py").read()
i=src.index("MARKET_TZ = {"); j=src.index("@st.cache_data(ttl=300, show_spinner=\"Loading data\u2026\")")
mod=_t.ModuleType("tzbit"); mod.pd=pd
exec(compile(src[i:j],"tzbit","exec"), mod.__dict__)
U="2026-08-25T14:28:00Z"
ck("every market has a zone", set(mod.MARKET_TZ)=={"Qatar","UAE","KSA","Egypt"},
   sorted(mod.MARKET_TZ))
q,_=mod.in_market_time(U,"Qatar"); u,_=mod.in_market_time(U,"UAE")
e,_=mod.in_market_time(U,"Egypt"); k,_=mod.in_market_time(U,"KSA")
ck("Qatar is UTC+3", q.endswith("17:28"), q)
ck("UAE is UTC+4", u.endswith("18:28"), u)
ck("KSA is UTC+3", k.endswith("17:28"), k)
ck("Egypt is UTC+3 in summer", e.endswith("17:28"), e)
ck("UAE reads an hour later than Qatar", u!=q, f"{u} vs {q}")
lbl=mod.in_market_time(U,"Qatar")[1]
ck("the label names the market", lbl=="Qatar time", lbl)
x,xl=mod.in_market_time(U,"Mars")
ck("an unknown market falls back to UTC", xl=="UTC" and x.endswith("14:28"), f"{x} {xl}")
ck("None does not crash", mod.in_market_time(None,"Qatar")[0]=="unknown")
naive,_=mod.in_market_time(pd.Timestamp("2026-08-25 14:28:00"),"UAE")
ck("a naive timestamp is treated as UTC", naive.endswith("18:28"), naive)
aware,_=mod.in_market_time(pd.Timestamp("2026-08-25 14:28:00", tz="UTC"),"UAE")
ck("an aware timestamp converts the same way", aware==naive, f"{aware} vs {naive}")
winter,_=mod.in_market_time("2026-01-15T14:28:00Z","Egypt")
ck("Egypt shifts with daylight saving", winter.endswith("16:28"), winter)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

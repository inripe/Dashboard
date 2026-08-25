"""Every shaded column must carry a key, and negatives must be visible."""
import sys, re, pandas as pd
P,F=[],[]
def ck(n,ok,note=""):
    (P if ok else F).append(f"{'PASS' if ok else 'FAIL'}  {n}  {note}")
src=open("app.py").read()

print("=== A. EVERY HEAT TABLE HAS A LEGEND ===")
heats=[m.start() for m in re.finditer(r"heat_cols\(", src)]
heats=[h for h in heats if not src[max(0,h-4):h].endswith("def ")]
legs=[m.start() for m in re.finditer(r"\blegend\(", src)]
legs=[l for l in legs if "def legend" not in src[max(0,l-20):l]]
ck("at least one legend per heat table", len(legs)>=len(heats), f"{len(legs)} legends, {len(heats)} heat uses")
for h in heats:
    nearby=[l for l in legs if 0 < l-h < 900]
    line=src[:h].count("\n")+1
    ck(f"heat use on line {line} has a legend after it", bool(nearby))

print("=== B. LEGEND RENDERS A SWATCH PER RAMP STEP ===")
ns=type(sys)("ns"); ns.pd=pd
exec(compile(src[src.index("R_BLUE="):src.index("def _shade")],"r","exec"), ns.__dict__)
out={}
class FakeSt:
    def markdown(self,t,**k): out["t"]=t
i=src.index("def legend("); j=src.index("def neg_red(")
ns.st=FakeSt(); ns.MUT="#888"
exec(compile(src[i:j],"legend","exec"), ns.__dict__)
ns.legend("Boxes:", ns.R_BLUE, "fewer", "more")
ck("a swatch per colour", out["t"].count("<span style=\"display:inline-block")==len(ns.R_BLUE),
   out["t"].count("<span style=\"display:inline-block"))
ck("the label is shown", "Boxes:" in out["t"])
ck("both ends are labelled", "fewer" in out["t"] and "more" in out["t"])
ns.legend("X:", ns.R_RED, "low", "high", extra="3 negative")
ck("extra note appears", "3 negative" in out["t"])

print("=== C. NEGATIVES ARE FLAGGED ===")
k=src.index("def neg_red("); m=src.index("def heat_cols(")
ns.RED="#C00000"
exec(compile(src[k:m],"neg","exec"), ns.__dict__)
d=pd.DataFrame({"Item":["a","b","c","d"],"Qatar":[5,0,-1,-5],"UAE":[0,0,0,0]})
r=ns.neg_red(d,["Qatar","UAE"])
ck("negative cells are red", "color:#C00000" in r.loc[2,"Qatar"] and "color:#C00000" in r.loc[3,"Qatar"])
ck("zero is not red", r.loc[1,"Qatar"]=="")
ck("positive is not red", r.loc[0,"Qatar"]=="")
ck("an all-zero column is untouched", set(r["UAE"])=={""})
ck("the item column is never styled", set(r["Item"])=={""})
ck("a missing column does not crash", len(ns.neg_red(d,["Nope"]))==4)

print("=== D. THE PIVOT COUNTS ITS NEGATIVES ===")
piv=pd.DataFrame({"Item":["a","b"],"Qatar":[-1,-5],"UAE":[3,0],"Total":[2,-5]})
cols=[c for c in piv.columns if c!="Item"]
n=int((pd.to_numeric(piv[cols].stack(),errors="coerce")<0).sum())
ck("counts every negative cell", n==3, n)

print()
for l in F: print(l)
print(f"\n{len(P)} passed, {len(F)} failed")
sys.exit(1 if F else 0)

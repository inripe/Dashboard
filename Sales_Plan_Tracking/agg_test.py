"""Does forecasting at a coarser grain beat a trailing mean?

Per-product daily counts are mostly Poisson noise on a handful of units, so
MAE at that grain measures randomness, not skill. Market and category series
are the same demand with the noise averaged out.
"""
import numpy as np, pandas as pd
import forecast_engine as fe

def agg_backtest(lines, by, horizon=14, folds=4, year=2026):
    d = fe.daily_units(lines, year)
    if by == "market":
        s = d.groupby(["market","date"],observed=True)["units"].sum().reset_index()
        keys=["market"]
    elif by == "group":
        d["group"]=d["product"].map(lambda p:str(p).split()[0])
        s=d.groupby(["market","group","date"],observed=True)["units"].sum().reset_index()
        keys=["market","group"]
    else:
        s=d.groupby(["date"],observed=True)["units"].sum().reset_index(); keys=[]
    last=s["date"].max(); out=[]
    for k in range(folds,0,-1):
        cut=last-pd.Timedelta(days=horizon*k)
        tr=s[s["date"]<=cut]; te=s[(s["date"]>cut)&(s["date"]<=cut+pd.Timedelta(days=horizon))]
        if tr.empty or te.empty: continue
        # naive: trailing 21d mean per key
        if keys:
            nv=(tr.sort_values("date").groupby(keys,observed=True)["units"]
                .apply(lambda x:x.tail(21).mean()).rename("naive").reset_index())
            te=te.merge(nv,on=keys,how="left")
            # seasonal-naive: same weekday mean over trailing 28d
            tr2=tr.copy(); tr2["wd"]=tr2["date"].dt.dayofweek
            sn=(tr2[tr2["date"]>cut-pd.Timedelta(days=28)]
                .groupby(keys+["wd"],observed=True)["units"].mean()
                .rename("snaive").reset_index())
            te["wd"]=te["date"].dt.dayofweek
            te=te.merge(sn,on=keys+["wd"],how="left")
        else:
            te["naive"]=tr["units"].tail(21).mean()
            tr2=tr.copy(); tr2["wd"]=tr2["date"].dt.dayofweek
            sn=tr2[tr2["date"]>cut-pd.Timedelta(days=28)].groupby("wd")["units"].mean()
            te["snaive"]=te["date"].dt.dayofweek.map(sn)
        te=te.fillna({"naive":0,"snaive":0})
        out.append(dict(fold=folds-k+1,n=len(te),actual=te["units"].sum(),
            mae_naive=(te["units"]-te["naive"]).abs().mean(),
            mae_snaive=(te["units"]-te["snaive"]).abs().mean()))
    return pd.DataFrame(out)

if __name__=="__main__":
    import plan_engine as pe
    from data_loader import load_plan, load_actuals_any
    raw,fx,_,al,cl=load_plan(); p=pe.attach_fx(pe.derive(raw),fx)
    a,m,lines=load_actuals_any(2026,cl,p)
    for by in ("total","market","group"):
        r=agg_backtest(lines,by)
        if len(r):
            print(f"\n=== grain: {by} ===")
            print(r.round(2).to_string(index=False))
            print(f"  seasonal-naive vs naive: {1-r.mae_snaive.mean()/r.mae_naive.mean():+.0%}")

"""What the close-out sees for KSA July, line by line."""
import pandas as pd
import metrics_engine as me, plan_engine as pe
from data_loader import load_plan, load_actuals_any

raw, fx, _, al, cl = load_plan()
p = pe.attach_fx(pe.derive(raw), fx)
a, m, lines = load_actuals_any(2026, cl, p)

scope = me.Scope(2026, "KSA", "July")
full = me.Scope(2026, "KSA", None)
d = me.attach_cost(me.prepare(lines, full), cl, p)

ff = pd.to_datetime(d["fulfilled_at"], utc=True, errors="coerce",
                    format="mixed").dt.tz_localize(None)
deliv = ff.where(ff.notna(), d["ts"])
start = pd.Timestamp(scope.start); end = pd.Timestamp(scope.end) + pd.Timedelta(days=1)

is_del = d["state"].eq("delivered")
del_in = is_del & (deliv >= start) & (deliv < end)
is_paid = d["cash"].eq("collected")

print(f"lines in full-year scope        {len(d):,}")
print(f"state = delivered               {int(is_del.sum()):,}")
print(f"  with a real fulfilled_at      {int((is_del & ff.notna()).sum()):,}")
print(f"delivered dated inside July     {int(del_in.sum()):,}")
print(f"  boxes                         {d.loc[del_in,'units'].sum():,.0f}")
print(f"  revenue                       {d.loc[del_in,'revenue'].sum():,.0f}")
print(f"  of which marked paid          {int((del_in & is_paid).sum()):,}")
print(f"  of which owed                 {int((del_in & ~is_paid).sum()):,}")
print(f"    owed revenue                {d.loc[del_in & ~is_paid,'revenue'].sum():,.0f}")

print("\nby fulfilment status, orders placed in July:")
jul = d[(d['ts'] >= start) & (d['ts'] < end)]
print(jul.groupby(['fulfillment_status','state'], observed=True)
      .agg(lines=('units','size'), boxes=('units','sum')).to_string())

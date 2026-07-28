# DM Tracking v6 — deployment note

## Files (all go in `Digital_Marketing/DM_Tracking/`)
| File | Role |
|---|---|
| `app.py` | Streamlit UI. Presentation only. **Replaces** the existing app.py. |
| `dm_engine.py` | All arithmetic. No Streamlit import, so it is testable standalone. **New.** |
| `validate.py` | One-command proof the numbers are right. **New, optional.** |

Entrypoint stays `Digital_Marketing/DM_Tracking/app.py`. No new dependencies.

## Verify
```bash
cd Digital_Marketing/DM_Tracking
python validate.py
```
Expect `RESULT: ALL ENGINE CHECKS PASS`.

## No changes needed to the Excel
Nothing in P4 or T3 needs editing. The workbook is internally consistent.

The model has no price or AOV concept — P1 records that it was removed, and Target Units
and Target Revenue are independent entries in P4. The dashboard therefore treats revenue
attainment and unit attainment as separate scores against separate assumptions, and does
not compare them with each other. A gap between the two is not an error.

## What changed vs v5
- **S0 Data integrity** (new): 9 reconciliation checks run on load — totals, coverage,
  target presence, channel roll-up, basket size. All currently pass.
- **Polarity**: overspend and CAC overruns can no longer render green.
- **Basis**: every percentage states what it is measured against; S1 has a
  `Scored against` column.
- **Missing is not zero**: blanks show `n/a` in grey and are never scored as 0% and red.
- **Momentum**: last 7 days vs the 7 before, replacing first-half vs second-half.
  July reads accelerating (117/day vs 86/day); v5 reported it as slowing.
- **Rounding**: one decimal on K/M, so 2,918 and 3,345 no longer both read "3K".
- **S6**: true delta, defaults to last 7 days vs previous 7. Identical periods read 0%.
- **S7**: separates days reported from days with orders. All three markets reported
  all 27 days; v5's "KSA 23 days" was counting non-zero order days only.
- **S8**: CR% is API orders ÷ API messages, matching S1 and S5.
- **Trend arrows**: one shared definition, so panels cannot disagree.
- **Layout**: explicit table heights stop the last row clipping.

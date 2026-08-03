# Inripe DM dashboard V2

Reads `DM_Model_2026_V3_5.xlsx` live from SharePoint:
Documents > Dashboards > DM.

Replaces the two apps in `DM_Dashboard/`, which keep running until this one is
confirmed.

## Files — all in `Digital_Marketing/DM_Dashboard_V2/`

| File | Role |
|---|---|
| `app.py` | Entry point. Presentation only. |
| `dm_engine.py` | Every calculation. No Streamlit import, so it can be verified alone. |
| `audit.py` | Recomputes every figure from the sheet and compares. Run before each deploy. |
| `sharepoint_loader.py` | Live workbook over Microsoft Graph. |

## Deploy

1. Push the folder.
2. Streamlit Cloud, new app, main file `Digital_Marketing/DM_Dashboard_V2/app.py`.
3. Secrets: the six `SP_` keys plus `DM_PASSWORD`.
   `SP_FILE_NAME` must be `DM_Model_2026_V3_5.xlsx` and `SP_FOLDER_PATH`
   `Dashboards/DM`.
4. Confirm it loads, then delete the old app.

## Before every deploy

```bash
python3 audit.py
```

Expect `ALL CHECKS PASS`. One warning is expected while Egypt reports fewer
days than the rest.

## Structure

    Overview      always visible. Headline, health, four cards, run rate,
                  where the gap is, where the next dirham goes.
    Performance   market and channel, plan vs actual, with the daily trend.
    Comparison    period A vs period B, presets and free dates.
    Efficiency    what an order costs, and whether spend drives orders.
    Data          coverage, plausibility, and whether the ceiling held.

## What the engine enforces

- Missing is not zero. Nulls show n/a in grey, never scored as 0%.
- Every percentage states its basis. Paced plan and month plan both appear.
- Paced plan = month plan x days elapsed / days in month. Ratios are never paced.
- Spend and budget carry no verdict. CPA and ROAS judge what the spend bought.
- Plausibility guard: an impossible value reads "check data", never green.
- Revenue converts to AED; spend converts only where R1. Setup says the market
  spends in its own currency.
- Plan budget is a ceiling on actual spend, and a breach is called out.
- ROAS is revenue divided by spend. Always.
- Nothing names a market or channel. Add either to the workbook and it appears.
- Meta is planned once and reported as Meta API and Meta Ecom. Selecting both
  does not count the single Meta plan twice.
- Capacity is messages x CR% x uptime, and delivery carries no uptime haircut.
  The decomposition therefore measures against reachable capacity, or a market
  on plan for both factors would read as over-delivering.
- AOV is reported because it is observed. It is never used to derive anything;
  ROAS is revenue divided by spend.

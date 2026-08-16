# Inripe stock control dashboard

Streamlit app. Reads `INRIPE_Stock_Entry_v1.xlsx` and renders five tabs:
Overview · Stock · Shipments · Couriers · Losses & check.

## Run locally
```
pip install -r requirements.txt
streamlit run app.py
```

## Files
| File | Role |
|---|---|
| `app.py` | The five tabs. Layout only. |
| `engine.py` | All calculations. Single source of truth. |
| `INRIPE_Stock_Entry_v1.xlsx` | Data entry file — the only thing that gets edited |

## Deploy
1. Push this folder to `inripe/Dashboard` (or its own repo)
2. Streamlit Community Cloud → new app → point at `app.py`
3. The Excel file is read from the repo root

## Switch to SharePoint later
Only `engine.load()` changes. Everything else stays.
Set `INRIPE_FILE` env var, or replace the path with a SharePoint fetch
using the Inripe-Streamlit Azure app (tenant b9e3ccd2).

## Settings
Live on the MASTER sheet of the Excel file, not in code:
As-Of Date · Courier holding limit · Clearance target · Loss % target · Count variance tolerance

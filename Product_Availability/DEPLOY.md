# Inripe Availability Dashboard — build and deploy

Follow in order. Do not skip step 6.

---

## 1 · Folder on the Mac

Terminal:

```bash
mkdir -p ~/Projects/inripe-availability
cd ~/Projects/inripe-availability
```

## 2 · Put the files in

Copy these seven into that folder:

```
app.py
availability_engine.py
calendar_engine.py
data_loader.py
audit.py
requirements.txt
Inripe_Product_Master.xlsx
```

## 3 · Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If `python3` is missing: `brew install python@3.13`

## 4 · Run the audit

```bash
python audit.py Inripe_Product_Master.xlsx 2026
```

Expect `CLEAN — safe to deploy`. Anything else, stop and fix.

## 5 · Run locally

```bash
streamlit run app.py
```

Opens on `http://localhost:8501`. Check every tab and every selector.
`Ctrl+C` to stop.

## 6 · Ignore file — before any commit

```bash
cat > .gitignore <<'EOF'
.venv/
__pycache__/
.streamlit/secrets.toml
*.xlsx
.DS_Store
EOF
```

`*.xlsx` and `secrets.toml` must never reach GitHub. The repo is public
and holds code only.

## 7 · Git repo

```bash
git init
git add .
git commit -m "Availability layer: engines, audit, app"
```

Confirm no Excel and no secrets went in:

```bash
git ls-files
```

## 8 · Push with GitHub Desktop

1. GitHub Desktop → File → Add Local Repository → pick the folder
2. Publish repository → name `inripe-availability` → **uncheck** Keep this code private
3. Publish

Or reuse `inripe/Dashboard` and put everything under a
`Product_Availability/` subfolder, same as your DM dashboards.

## 9 · Deploy on Streamlit Cloud

1. share.streamlit.io → New app
2. Repository: your repo · Branch: `main` · Main file: `app.py`
   (or `Product_Availability/app.py` if you used a subfolder)
3. Deploy

First build takes 2–4 minutes.

## 10 · Excel file in production

The repo has no Excel file, so pick one:

**A · GitHub hosting** — same as your DM dashboards. Commit the workbook
to a separate private repo or a data folder and point `LOCAL` in
`data_loader.py` at it.

**B · SharePoint via Graph** — the real target. In Streamlit Cloud →
your app → Settings → Secrets, paste:

```toml
[sharepoint]
tenant_id = "..."
client_id = "..."
client_secret = "..."
hostname = "inripe.sharepoint.com"
site_path = "/sites/YourSite"
file_path = "Shared Documents/Inripe_Product_Master.xlsx"
```

`data_loader.py` uses SharePoint automatically when these exist and
falls back to the local file when they don't. No code change needed.

Requires an Azure app registration with `Sites.Read.All`
(application permission) and admin consent.

---

## Daily loop after this

```bash
cd ~/Projects/inripe-availability
source .venv/bin/activate
python audit.py Inripe_Product_Master.xlsx 2026   # must be CLEAN
streamlit run app.py                              # eyeball it
```

Then commit and push in GitHub Desktop. Streamlit Cloud redeploys
automatically.

**Never push an unaudited change.**

---

## If something breaks

| Symptom | Cause |
|---|---|
| `ModuleNotFoundError` | venv not active — `source .venv/bin/activate` |
| `Could not load the product master` | Excel missing, or SharePoint secrets wrong |
| Audit fails on B or C | a season window in the sheet is invalid |
| Audit fails on D | engine and recompute disagree — a real bug, do not deploy |
| App loads but is empty | wrong year, or every market column set to N |
| Streamlit Cloud build fails | check `requirements.txt` reached the repo |

Data refresh is cached for 10 minutes. Use the app menu → Rerun to force it.

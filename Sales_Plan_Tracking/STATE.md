# Inripe Sales Tracking — state as of 30 Jul 2026

Audit: **40 checks, 0 failures.** Everything below is live and working.

---

## The eight files

Local folder: `Dashboard/Sales_Plan_Tracking`

| File | What it does | Status |
|---|---|---|
| `app.py` | Dashboard. Presentation only. | live |
| `audit.py` | 40 checks. Run before every deploy. | live |
| `plan_engine.py` | Plan derivation, FX, pacing, rollups. | live |
| `variance_engine.py` | Plan vs actual, bridge, dated cost, segments, findings. | live |
| `data_loader.py` | Plan from SharePoint, actuals from Shopify. | live |
| `sharepoint_loader.py` | Graph reader. Fetches by path, falls back to search. | live |
| `shopify_loader.py` | All four stores. Kg per box, 3-way channel, agent. | live |
| `forecast_engine.py` | Statistical forecast. **Built, tested, NOT in use.** | shelved |

`agg_test.py` is a one-off diagnostic. Keep it for re-testing later.

---

## Configuration

`.streamlit/secrets.toml` holds:

```
SP_TENANT_ID, SP_CLIENT_ID, SP_CLIENT_SECRET
SP_HOSTNAME    = gloabl.sharepoint.com
SP_SITE_PATH   = LT-PerformanceManagement
SP_FILE_NAME   = Sales_Plan_2026_V3.xlsx
SP_FOLDER_PATH = Dashboards/Sales_Plan

[shopify.UAE] [shopify.KSA] [shopify.QA] [shopify.EG]
  shop, client_id, client_secret
```

`.streamlit/config.toml` holds the theme. Blue header, white background.

Four Shopify custom apps, one per store, scopes
`read_all_orders, read_orders, read_products`. Auth is the client credentials
grant, so there is no long-lived token stored anywhere.

**Open action: the Azure client secret and all four Shopify secrets were
pasted into a chat and should be rotated.**

---

## The workbook

`Sales_Plan_2026_V3.xlsx` in `Documents / Dashboards / Sales_Plan`.

| Sheet | Contents |
|---|---|
| Plan | 762 rows. product_id, category, store_product_name, inhouse_product_name, market, currency, month, plan_units, plan_price_lc, plan_cogs_unit_lc |
| Cost_Log | Append-only dated cost. Currently empty, so margin runs at plan cost |
| FX | Rate to AED per month. **Still placeholders** |
| Aliases | 14 rows. Recovered 185,465 of previously unattributed revenue |

`store_product_name` is the join key and must match Shopify exactly.
`inhouse_product_name` is display only and may be blank.

---

## Store cleanup, done

Eight renames so every store name reaches a plan product:

| Store | Change |
|---|---|
| KSA | Mango Heidi → Mango Riyadh · Mango Keitt → Mango Cleopatra |
| UAE | Mango Heidi → Mango Dubai · Mango Keitt → Mango Cleopatra · Timour Mango → Mango Timour · Grapes White → Grapes Banati |
| QA | Mango Heidi → Mango Doha · Mango Keitt → Mango Cleopatra |
| EG | Prickly Pear → Fig Shouki |

One product, four shopfront names: P025 is Heidi in Egypt, Dubai in UAE,
Doha in Qatar, Riyadh in KSA. P027 is Keitt in Egypt, Cleopatra in the GCC.

**Outstanding:** Qatar's Grapes White may still need renaming to Grapes
Banati — the Shopify connection dropped before it was confirmed.

---

## Current data

| Market | Orders | Boxes | Revenue | Months |
|---|---|---|---|---|
| UAE | 4,561 | 11,798 | AED 1,111,470 | Jan–Jul |
| QA | 2,329 | 6,332 | QAR 611,520 | Jan–Jul |
| KSA | 495 | 1,150 | SAR 122,605 | July |
| EG | 181 | 608 | EGP 285,820 | July |

Plan: 107,266 units, AED 10.9M, 41.6% CM at placeholder FX.

285 cancelled and 48 refunded/voided orders excluded, not zeroed.
1,908 orders had a line title differing from the catalogue name, all resolved.

---

## Why the forecast is shelved

`forecast_engine.py` is complete: pooled weekday factors, pooled season
curves per fruit group, de-seasonalised level, damped trend, quantiles from
backtest residuals, and a four-fold backtest against a trailing mean.

On synthetic data with a known answer it recovered the truth — weekday
factors within 0.05, the season arc reconstructed cleanly, and it beat the
naive baseline by 16%.

On the real data it does not. The backtest says so:

```
fold 1  actual   617   forecast   405
fold 3  actual 2,514   forecast   471
fold 4  actual 4,564   forecast 3,861
model does NOT beat a trailing mean (-6%)
```

Fold 3 is the diagnosis. Training ends 2 July; mango season starts in July.
At the cut, most mango products had almost no history. Nothing forecasts a
season launch it has never seen.

A separate test confirmed there is no rescue at coarser grain — a
seasonal-naive baseline lost to a plain trailing mean at every level:
−7% total, −18% per market, −5% per fruit group.

So it is built, tested, and deliberately not used. Shipping it would have
produced authoritative-looking numbers worse than an average.

**When to revisit:** after the WooCommerce migration brings 2024 and 2025,
or after this mango season completes around November. Re-run
`python agg_test.py` and the backtest. If it beats naive, switch it on.

---

## What replaces it

Plan-anchored projection, three variants, each with its assumption stated:

| Basis | Assumption |
|---|---|
| Plan | the rest of the month runs to plan |
| Attainment-adjusted | the rest runs at the rate achieved so far |
| Run rate | the recent daily rate continues |

Plus the open order pipeline, which is committed rather than forecast.

---

## Dashboard

**Executive block** — three generated findings ranked by money at stake.

**Row 1** — Units · Orders · Revenue · CM · CM%, each against plan.
The Orders card derives an implied plan order count from plan units at the
achieved basket, which splits a unit gap into fewer orders versus smaller
baskets. For KSA July: 809 boxes from order count, zero from basket.

**Row 2** — Concentration · Cancellation · Price realisation · Revenue at
risk · Landing estimate.

**Nine tabs** — Attainment, Comparison, Margin bridge, Cost & margin,
Price realisation, Portfolio, Where demand came from, Order quality,
Exceptions.

---

## Agreed but not yet built

**Price simulator.** Break-even volume rather than predicted volume: cut
Mango Fas 10% in Qatar and you need +29% units to hold CM. Exact arithmetic,
no estimation. Does not need elasticity.

**Price advisor.** Rules on margin arithmetic: below cost, realisation gap,
cost moved but price did not, CM per box ranking, thin margin at volume.
Each with the amount at stake. Will not name an optimal price — that needs
elasticity, and elasticity needs price variation not confounded with season.

**Dashboard fixes identified in critique:**
- Every segment view needs a time axis. Concentration, city, channel and
  customer type are all snapshots with no direction
- Kilos everywhere. You air-freight; capacity is kg and boxes run 1.5 to 9 kg
- Cancellation against order-to-fulfilment lag. You said customers give up
  while waiting for container fill, so cancellation is caused, not random
- Repeat rate and time-to-second-order
- Discount rate by product and channel — captured, never shown
- Weekly view. Everything is monthly; perishables run weekly
- Customer concentration, not just product
- Redundancy to cut: duplicate month tables, three charts plus three tables
  in the demand tab, concentration table duplicating the heatmap

---

## Known data issues

| Issue | Detail |
|---|---|
| FX placeholders | 0.98 SAR, 1.008 QAR, 0.076 EGP. Every AED figure moves when replaced |
| No Cost_Log | Margin is plan-cost only. Cost movement invisible |
| Grapes Red UAE | Jan and Feb priced below cost. −3.7% CM |
| 10 rows under 10% CM | |
| 15 products sold in unplanned months | Plan is missing rows |
| Egypt store | Berries Spain and Apple Baladi were being created |

---

## Daily use

```bash
cd "~/Library/CloudStorage/OneDrive-Inripe/inripe/Dashboard/Sales_Plan_Tracking"
source .venv/bin/activate
python audit.py          # must print CLEAN
streamlit run app.py     # first load takes 1-2 min, then cached 15 min
```

Nothing to update by hand. The plan comes from SharePoint, actuals from the
Shopify API. Edit the workbook and refresh.

**Not yet deployed to Streamlit Cloud.** Agreed sequence: finish locally,
make the GitHub repo private, then deploy once. A public app would expose
margins and customer cities.

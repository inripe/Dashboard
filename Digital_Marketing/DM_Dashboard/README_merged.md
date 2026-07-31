# DM Dashboard — unified app

One app, two views. Replaces the two separate Streamlit apps.

## Files — all in one new folder `Digital_Marketing/DM_Dashboard/`

| File | Role |
|---|---|
| `main.py` | **Entry point.** Page config, access gate, view switcher. |
| `tracking_view.py` | Tracking dashboard. Exposes `render()`. |
| `planning_view.py` | Planning dashboard. Exposes `render()`. |
| `dm_engine.py` | All tracking arithmetic. |
| `sharepoint_loader.py` | Live workbook from SharePoint. |
| `audit_v7.py` | Run before every deploy. |

## Deploy

1. Push the folder.
2. In Streamlit Cloud, point **one** app at `Digital_Marketing/DM_Dashboard/main.py`.
3. Copy the secrets across to it (same 6 SP_ keys, plus DM_PASSWORD if used).
4. Confirm both views load, then delete the two old apps.

Keep the old apps running until the new one is confirmed. Nothing is deleted
from the repo, so they keep working throughout.

## Why a radio switcher, not st.tabs

`st.tabs` renders every tab's contents on every rerun. With two full dashboards
that means building both on each click. The switcher renders only the view being
looked at.

## Fixed during the merge

- **Planning error path.** `load_data()` returned two values where three were
  unpacked, so a missing workbook raised `not enough values to unpack` instead
  of the intended message. Pre-existing in planning v4; only reachable when no
  workbook is found, which is why it never surfaced.
- **`st.stop()` inside the views.** Stopping inside a view would have taken the
  whole app down, switcher included. Both views now return instead.
- **Duplicate headers.** Each view drew its own banner; the switcher supplies
  one, so the views now show only a slim freshness line.

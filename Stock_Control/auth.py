"""
Who is using the dashboard.

Users live on MASTER so you control access by editing the sheet.
Passwords live in Streamlit secrets, never in the workbook.

    ENTRY_PASSWORD    = "for the store users"
    DISPATCH_PASSWORD = "for whoever runs dispatch"
    ADMIN_PASSWORD    = "yours - opens both"

A user's market comes from the sheet, not from a dropdown - that removes a
whole class of entry error and makes the audit trail mean something.
"""
from __future__ import annotations
import os


def _secret(key):
    v = os.environ.get(key)
    if v:
        return v.strip()
    try:
        import streamlit as st
        v = st.secrets.get(key)
        return v.strip() if isinstance(v, str) else v
    except Exception:
        return None


ROLE_PASSWORD = {"admin": "ADMIN_PASSWORD",
                 "entry": "ENTRY_PASSWORD",
                 "dispatch": "DISPATCH_PASSWORD"}

# which roles may open which protected tab
ROLE_TABS = {"admin": {"entry", "dispatch"},
             "entry": {"entry"},
             "dispatch": {"dispatch"}}


def is_enabled(users):
    """Sign-in is available once users exist and at least one password is set."""
    return bool(users) and any(_secret(k) for k in ROLE_PASSWORD.values())


def can_open(session, tab):
    """tab is 'entry' or 'dispatch'."""
    if not session:
        return False
    return tab in ROLE_TABS.get(str(session.get("role", "")).strip().lower(), set())


def roles_for(tab):
    return sorted(r for r, tabs in ROLE_TABS.items() if tab in tabs)


def check(username, password, users):
    """Returns (ok, user record or reason)."""
    u = str(username or "").strip().lower()
    rec = users.get(u)
    if not rec:
        return False, "That user is not on the list, or is not active."
    role = str(rec.get("role", "")).strip().lower()
    key = ROLE_PASSWORD.get(role)
    if not key:
        return False, (f"'{rec.get('role')}' is not a role I know. Use Admin, "
                       f"Entry or Dispatch on the MASTER sheet.")
    want = _secret(key)
    if not want:
        return False, f"No password is set for this role. Add {key} to the app secrets."
    if str(password or "") != str(want):
        return False, "Wrong password."
    return True, {"user": u, "market": rec["market"], "role": rec["role"]}


def markets_for(session, all_markets):
    """Admin sees every market. Everyone else sees exactly one."""
    if not session:
        return []
    if str(session.get("role", "")).lower() == "admin" \
            or str(session.get("market", "")).lower() == "all":
        return list(all_markets)
    return [session["market"]] if session["market"] in all_markets else []


def can_void(session, row_user, row_date, today):
    """Own row, same day. Anything older goes to an admin."""
    if not session:
        return False
    if str(session.get("role", "")).lower() == "admin":
        return True
    if str(row_user or "").lower() != str(session.get("user", "")).lower():
        return False
    d = row_date.date() if hasattr(row_date, "date") else row_date
    t = today.date() if hasattr(today, "date") else today
    return d == t

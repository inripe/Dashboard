"""The Entry tab. Phone first: one question per step, plain words, no jargon."""
from __future__ import annotations
import pandas as pd
import streamlit as st
import entry, auth, labels as L

# what a store worker may record. Anything else is admin work.
WORKER_MOVES = ["Received", "Scrap", "To Courier", "Delivered", "Returned"]
NEEDS = {  # movement -> which extra fields the form must ask for
    "Received":            {"item": True,  "dir": "In"},
    "Scrap":               {"item": True,  "dir": "Out", "reason": True},
    "To Courier":          {"item": True,  "dir": "Out", "courier": True},
    "Delivered":           {"item": False, "dir": "Out", "courier": True, "orders": True},
    "Returned":            {"item": False, "dir": "In",  "courier": True, "orders": True,
                            "reason": True},
    "Return to Saleable":  {"item": True,  "dir": "In"},
    "Return to Scrap":     {"item": True,  "dir": "Out", "reason": True},
    "Orders Assigned":     {"item": False, "dir": None,  "orders": True},
    "Courier Handover":    {"item": False, "dir": None,  "courier": True, "orders": True},
    "Count Adjustment - Add":    {"item": True, "dir": "In",  "reason": True},
    "Count Adjustment - Remove": {"item": True, "dir": "Out", "reason": True},
}


def _mangoes():
    """A shower of mangoes instead of balloons. Small thing, but the people
    using this all day are the ones it is for."""
    import random
    drops = []
    for i in range(26):
        left = random.uniform(0, 97)
        delay = random.uniform(0, 1.6)
        dur = random.uniform(2.6, 4.4)
        size = random.uniform(20, 40)
        spin = random.choice((-40, -20, 20, 40))
        drops.append(
            f'<span style="position:absolute;left:{left:.1f}%;top:-60px;'
            f'font-size:{size:.0f}px;animation:mfall {dur:.2f}s linear '
            f'{delay:.2f}s 1 forwards;--spin:{spin}deg">\U0001F96D</span>')
    st.markdown(
        '<style>@keyframes mfall{from{transform:translateY(0) rotate(0)}'
        'to{transform:translateY(105vh) rotate(var(--spin))}}</style>'
        '<div style="position:fixed;inset:0;pointer-events:none;z-index:9999;'
        'overflow:hidden">' + "".join(drops) + '</div>',
        unsafe_allow_html=True)


def _nonce():
    """Widget keys carry a counter. Bumping it after a save gives Streamlit
    brand new widgets, which is the only reliable way to clear them - deleting
    the session keys alone leaves the old value on screen."""
    return st.session_state.get("e_n", 0)


def what_is_missing(mv, sid, item, qty, extras):
    """Everything the chosen movement needs but has not been given.
    Save is off while this is not empty."""
    spec = NEEDS.get(mv, {})
    out = []
    if not mv:
        return ["what happened  ·  ماذا حدث"]
    if not sid:
        out.append("shipment  ·  الشحنة")
    if spec.get("item") and not item:
        out.append("item  ·  الصنف")
    if spec.get("dir") and not qty:
        out.append("number of boxes  ·  عدد الصناديق")
    if spec.get("courier") and not (extras or {}).get("Courier"):
        out.append("courier  ·  المندوب")
    if spec.get("reason") and not (extras or {}).get("Reason"):
        out.append("reason  ·  السبب")
    if spec.get("orders") and not (extras or {}).get("Orders"):
        out.append("number of orders  ·  عدد الطلبات")
    return out


def _reset(keep_shipment=True):
    keep = st.session_state.get(f"e_ship_{_nonce()}") if keep_shipment else None
    for k in list(st.session_state):
        if k.startswith("e_") and k not in ("e_n", "e_saved", "e_keep_ship"):
            st.session_state.pop(k, None)
    st.session_state["e_n"] = _nonce() + 1
    if keep:
        st.session_state["e_keep_ship"] = keep


def open_shipments(ship, clear, market):
    """Only shipments still open in this market, newest first."""
    live = clear[(clear["Market"] == market) & (clear["Cleared"] == "No")]["Shipment"]
    s = ship[ship["Shipment ID"].isin(set(live)) & (ship["Market"] == market)]
    order = (s.groupby("Shipment ID")["Arrival Date"].min()
              .sort_values(ascending=False))
    return [(sid, d) for sid, d in order.items()]


def items_in(ship, shipment):
    return sorted(ship[ship["Shipment ID"] == shipment]["Item Name"].dropna().unique())


def available(stock, shipment, item):
    r = stock[(stock["Shipment"] == shipment) & (stock["ItemName"] == item)] \
        if "ItemName" in stock.columns else \
        stock[(stock["Shipment"] == shipment)]
    return float(r["Store"].sum()) if len(r) else 0.0


def render(ship, moves, clear, stock, cfg, session, save_fn, void_fn,
           item_names=None):
    """save_fn(rows, market) -> list of entry ids.  void_fn(entry_id, market)."""
    n = _nonce()
    # every active market, not only those that already have a shipment, so a
    # new market is visible and the reason it cannot be used is explained
    all_markets = sorted(cfg.get("markets") or []) or \
        sorted(ship["Market"].dropna().unique())
    market = session["market"] if str(session.get("market", "")).lower() != "all" \
        else st.selectbox("Market", all_markets, key=f"e_market_{n}")
    now = entry.market_now(market)
    st.markdown(f'<div class="card" style="border-left:3px solid {"#2E75B6"}">'
                f'<b>{market}</b> &nbsp;&middot;&nbsp; {session["user"]}'
                f'<div class="note">{now:%A %d %B} &nbsp;&middot;&nbsp; '
                f'{market} time</div></div>', unsafe_allow_html=True)

    saved = st.session_state.pop("e_saved", None)
    if saved:
        st.success("Saved  /  تم الحفظ")
        st.markdown(
            f'<div class="card" style="border-left:3px solid #1D9E75;'
            f'background:#F2FBF6">{saved["words"]}'
            f'<div class="note">{saved["at"]} &nbsp;&middot;&nbsp; '
            f'{saved["id"]} &nbsp;&middot;&nbsp; it is in the Today list below, '
            f'with a Void button if it was wrong</div></div>',
            unsafe_allow_html=True)
        _mangoes()

    opens = open_shipments(ship, clear, market)
    if not opens:
        has_any = market in set(ship["Market"].dropna())
        st.warning(
            (f"Every {market} shipment is fully cleared, so there is nothing to "
             f"record against. Add the new shipment first."
             if has_any else
             f"{market} has no shipment yet. Switch to New shipment above and "
             f"create one - movements are always recorded against a shipment.")
            + f"\n\n{market}: لا توجد شحنة مفتوحة")
        _today_list(moves, session, market, now, void_fn, item_names)
        return

    moves_allowed = (WORKER_MOVES if str(session.get("role", "")).lower() != "admin"
                     else list(NEEDS))
    # all the IN movements first, then all the OUT ones, then the rest
    _rank = {"IN": 0, "OUT": 1, "": 2}
    moves_allowed = sorted(moves_allowed,
                           key=lambda m: (_rank[L.direction(m)],
                                          moves_allowed.index(m)))

    # ---------- step 1 ----------
    st.markdown(f"**1 · {L.t('What happened?')}**")
    mv = st.radio("Movement", moves_allowed, key=f"e_move_{n}",
                  format_func=L.move, index=None,
                  horizontal=False, label_visibility="collapsed")
    mv = st.session_state.get(f"e_move_{n}", mv)
    if not mv:
        st.markdown('<div class="note">Pick what happened to see the rest of '
                    'the form.  &nbsp;·&nbsp;  اختر ماذا حدث</div>',
                    unsafe_allow_html=True)
        _today_list(moves, session, market, now, void_fn, item_names)
        return
    spec = NEEDS.get(mv, {})

    # ---------- step 2 ----------
    st.markdown(f"**2 · {L.t('Which shipment?')}**")
    labels = {sid: f"{sid} · arrived {pd.Timestamp(d):%d %b}" for sid, d in opens}
    _ids = [s for s, _ in opens]
    _keep = st.session_state.get("e_keep_ship")
    sid = st.selectbox("Shipment", _ids,
                       index=_ids.index(_keep) if _keep in _ids else None,
                       format_func=lambda s: labels[s], key=f"e_ship_{n}",
                       placeholder="Choose a shipment  ·  اختر الشحنة",
                       label_visibility="collapsed")

    item = None
    if spec.get("item"):
        st.markdown(f"**3 · {L.t('Which item?')}**")
        opts = items_in(ship, sid) if sid else []
        if sid and not opts:
            st.warning("That shipment has no items listed.")
        item = st.selectbox("Item", opts, key=f"e_item_{n}", index=None,
                            disabled=not opts,
                            placeholder=("Choose an item  ·  اختر الصنف" if opts
                                         else "Pick a shipment first"),
                            label_visibility="collapsed")
        item = st.session_state.get(f"e_item_{n}", item)

    qty = None
    if spec.get("dir"):
        _n = 4 if spec.get('item') else 3
        _dir = L.direction(mv)
        _word = ("boxes IN  /  صندوق داخل" if _dir == "IN"
                 else "boxes OUT  /  صندوق خارج")
        st.markdown(f"**{_n} · {L.t('How many boxes?')}**")
        st.markdown(f'<div class="note" style="margin-top:-.4rem">{_word}</div>',
                    unsafe_allow_html=True)
        qty = st.number_input("Boxes", min_value=0, max_value=100000, step=1,
                              value=0, key=f"e_qty_{n}",
                              label_visibility="collapsed")
        qty = st.session_state.get(f"e_qty_{n}", qty)
        if spec["dir"] == "Out" and item:
            have = available(stock, sid, item)
            st.markdown(f'<div class="note">{have:,.0f} in store for this shipment '
                        f'and item.</div>', unsafe_allow_html=True)

    extras = {}
    if spec.get("courier"):
        cs = cfg.get("couriers_by_market", {}).get(market, [])
        extras["Courier"] = (st.selectbox(L.t("Courier"), cs, index=None,
                                          placeholder="Choose  ·  اختر",
                                          key=f"e_courier_{n}") if cs
                             else st.text_input(L.t("Courier"), key=f"e_courier_{n}"))
    if spec.get("orders"):
        extras["Orders"] = st.number_input(L.t("How many orders?"), min_value=0,
                                           step=1, value=0, key=f"e_orders_{n}")
    if spec.get("reason"):
        rs = cfg.get("reasons", [])
        extras["Reason"] = (st.selectbox(L.t("Why?"), rs, index=None,
                                         placeholder="Choose  ·  اختر",
                                         key=f"e_reason_{n}") if rs
                            else st.text_input(L.t("Why?"), key=f"e_reason_{n}"))
    note = st.text_input(L.t("Note (optional)"), key=f"e_note_{n}")

    # ---------- confirm ----------
    row = {"Date": now.date(), "Shipment No": sid, "Movement": mv}
    if item:
        row["Item Name"] = item
    if qty and spec.get("dir"):
        row[spec["dir"]] = int(qty)
    for k, v in extras.items():
        if v not in (None, "", 0) or (k == "Orders" and v):
            row[k] = v
    if note:
        row["Note"] = note

    missing = what_is_missing(mv, sid, item, qty, extras)

    words = _sentence(row, mv, market, session["user"])
    st.markdown(f"**{L.t('Check before saving')}**")
    if missing:
        st.markdown(
            f'<div class="card" style="border-left:3px solid #C08A28;'
            f'background:#FFFBF2">Still needed: <b>{", ".join(missing)}</b>'
            f'<div class="note">Save stays off until every one is filled.</div>'
            f'</div>', unsafe_allow_html=True)
        c1, c2 = st.columns([1, 1])
        c1.button(L.t("Save"), disabled=True, key=f"e_save_{n}")
        if c2.button(L.t("Start again"), key=f"e_clear_{n}"):
            _reset(keep_shipment=False)
            st.rerun()
        _today_list(moves, session, market, now, void_fn, item_names)
        return
    st.markdown(f'<div class="card" style="border-left:3px solid #2E75B6;'
                f'font-size:1.02rem;line-height:1.65">{words}</div>',
                unsafe_allow_html=True)

    c1, c2 = st.columns([1, 1])
    if c1.button(L.t("Save"), type="primary", key=f"e_save_{n}"):
        try:
            with st.spinner("Saving…"):
                ids = save_fn([row], market)
            st.session_state["e_saved"] = {
                "id": ids[0] if ids else "",
                "words": words,
                "at": now.strftime("%H:%M")}
            _reset()
            st.rerun()
        except Exception as ex:
            st.error(str(ex))
    if c2.button(L.t("Start again"), key=f"e_clear_{n}"):
        _reset(keep_shipment=False)
        st.rerun()

    _today_list(moves, session, market, now, void_fn, item_names)


def _sentence(row, mv, market, user):
    """Plain words, not field names. This is what catches the mistakes."""
    n = row.get("In") or row.get("Out")
    item = row.get("Item Name")
    sid = row.get("Shipment No")
    ar = L.MOVES.get(mv, ("", ""))[1]
    if mv == "Received":
        s = f"<b>{n} boxes</b> of <b>{item}</b> received into <b>{sid}</b>"
    elif mv == "Scrap":
        s = f"<b>{n} boxes</b> of <b>{item}</b> thrown away from <b>{sid}</b>"
    elif mv == "To Courier":
        s = (f"<b>{n} boxes</b> of <b>{item}</b> from <b>{sid}</b> handed to "
             f"<b>{row.get('Courier')}</b>")
    elif mv == "Delivered":
        s = (f"<b>{n} boxes</b> from <b>{sid}</b> delivered to customers by "
             f"<b>{row.get('Courier')}</b>")
    elif mv == "Returned":
        s = (f"<b>{n} boxes</b> came back from <b>{row.get('Courier')}</b> "
             f"to <b>{sid}</b>")
    else:
        s = f"<b>{mv}</b> · <b>{n or ''}</b> · <b>{sid}</b>"
    if row.get("Orders"):
        s += f", covering <b>{int(row['Orders'])} orders</b>"
    if row.get("Reason"):
        s += f" &mdash; {row['Reason']}"
    d = L.direction(mv)
    tag = ("\u2193 IN  \u2014 stock goes up" if d == "IN"
           else ("\u2191 OUT  \u2014 stock goes down" if d == "OUT" else ""))
    return (s + (f'<div style="font-size:.92rem;direction:rtl;text-align:right;'
                 f'margin-top:.35rem">{ar} \u00b7 <b>{n or ""}</b> \u00b7 {sid}</div>'
                 if ar else "")
            + f'<div class="note">{tag}</div>'
            + f'<div class="note">{market} · today · by {user}</div>')


def _today_list(moves, session, market, now, void_fn, item_names=None):
    """What this person entered today, so nobody wonders whether it saved."""
    st.write("")
    st.markdown(f"**{L.t('Today')}**")
    need = ("Entered at", "Entered by", "Entry ID", "Movement", "Shipment")
    missing = [c for c in need if c not in moves.columns]
    if missing:
        st.markdown(f'<div class="note">Nothing entered through the app yet.</div>',
                    unsafe_allow_html=True)
        return
    m = moves.copy()
    m["Entered at"] = pd.to_datetime(m["Entered at"], errors="coerce")
    m = m[m["Entered at"].notna()]
    if "Market" in m.columns:
        m = m[m["Market"] == market]
    m = m[m["Entered at"].dt.date == now.date()]
    if str(session.get("role", "")).lower() != "admin":
        m = m[m["Entered by"].astype(str).str.lower()
              == str(session["user"]).lower()]
    if not len(m):
        st.markdown('<div class="note">Nothing entered yet today.</div>',
                    unsafe_allow_html=True)
        return
    for _, r in m.sort_values("Entered at", ascending=False).iterrows():
        qty = int(r.get("Qty", 0) or 0)
        item = r.get("Item Name") or ""
        if not item and item_names:
            item = item_names.get(r.get("Item", ""), "")
        eid = r.get("Entry ID")
        voided = str(r.get("Void") or "").strip().lower() == "yes"
        c1, c2 = st.columns([5, 1])
        style = ("opacity:.45;text-decoration:line-through" if voided else "")
        c1.markdown(
            f'<div style="font-size:.85rem;padding:.3rem 0;{style}">'
            f'<span style="color:#8A94A6">{r["Entered at"]:%H:%M}</span> &nbsp; '
            f'{L.move(r["Movement"])} &nbsp;<b>{qty}</b> {item} '
            f'<span style="color:#8A94A6">&middot; {r["Shipment"]}</span></div>',
            unsafe_allow_html=True)
        if voided:
            c2.markdown('<div class="note" style="padding-top:.35rem">voided</div>',
                        unsafe_allow_html=True)
        elif eid and auth.can_void(session, r.get("Entered by"),
                                   r["Entered at"], now):
            if c2.button(L.t("Void"), key=f"v_{eid}"):
                try:
                    void_fn(eid, market)
                    st.rerun()
                except Exception as ex:
                    st.error(str(ex))


def render_shipment(ship, cfg, session, save_fn):
    """Admin only. A shipment is what was SENT - what arrives is recorded
    separately by the store, so the difference stays visible."""
    import datetime as dt
    # from the MASTER markets table, not from shipments already on the sheet -
    # otherwise a market can never receive its first shipment
    markets = sorted(cfg.get("markets") or [])
    if not markets:
        markets = sorted(ship["Market"].dropna().unique())
    if not markets:
        st.warning("No active market on the MASTER sheet. Add one to the "
                   "Markets table with Active = Yes.")
        return
    n = _nonce()
    st.markdown("**New shipment  ·  شحنة جديدة**")
    st.markdown('<div class="note">This records what was <b>sent</b>. The store '
                'records what <b>arrives</b> as Received, and anything damaged '
                'as Scrap. The gap between the two is your transit loss, so do '
                'not enter the arrived figure here.</div>',
                unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    nxt = st.session_state.get("s_no") or "…"
    sid = c1.text_input("Shipment number  ·  رقم الشحنة", value=nxt, key=f"s_no_{n}")
    mkt = c2.selectbox("Market  ·  السوق", markets, index=None,
                       placeholder="Choose", key=f"s_mkt_{n}")
    arr = c3.date_input("Arrival date  ·  تاريخ الوصول",
                        value=dt.date.today(), key=f"s_arr_{n}")
    src = st.selectbox("Source  ·  المصدر", ["Egypt", "Local"], index=None,
                       placeholder="Choose", key=f"s_src_{n}")

    items = sorted((cfg.get("item_names") or {}).values())
    st.markdown("**Items and quantities  ·  الأصناف والكميات**")
    lines = st.session_state.setdefault("s_lines", [])
    a, b, c = st.columns([3, 1, 1])
    it = a.selectbox("Item", items, index=None, placeholder="Choose an item",
                     key=f"s_item_{n}", label_visibility="collapsed")
    qt = b.number_input("Qty", min_value=0, step=1, value=0,
                        key=f"s_qty_{n}", label_visibility="collapsed")
    c.markdown('<div style="height:.1rem"></div>', unsafe_allow_html=True)
    if c.button("Add line", key=f"s_add_{n}"):
        if not it or not qt:
            st.warning("Pick an item and a quantity first.")
        elif any(x["Item Name"] == it for x in lines):
            st.warning(f"{it} is already on this shipment.")
        else:
            lines.append({"Item Name": it, "Shipped Qty": int(qt)})
            st.session_state["s_n"] = n + 1
            st.session_state["e_n"] = _nonce() + 1
            st.rerun()

    if lines:
        df = pd.DataFrame(lines)
        st.dataframe(df, hide_index=True)
        st.markdown(f'<div class="note">{len(lines)} item'
                    f'{"s" if len(lines) != 1 else ""} · '
                    f'{sum(x["Shipped Qty"] for x in lines):,} boxes shipped</div>',
                    unsafe_allow_html=True)
        d1, d2 = st.columns([1, 1])
        if d2.button("Clear the lines", key=f"s_clr_{n}"):
            st.session_state["s_lines"] = []
            st.rerun()

    missing = []
    if not sid or sid == "…":
        missing.append("shipment number")
    if not mkt:
        missing.append("market")
    if not src:
        missing.append("source")
    if not lines:
        missing.append("at least one item")
    if missing:
        st.markdown(f'<div class="card" style="border-left:3px solid #C08A28;'
                    f'background:#FFFBF2">Still needed: <b>{", ".join(missing)}'
                    f'</b></div>', unsafe_allow_html=True)
        st.button("Save shipment", disabled=True, key=f"s_save_{n}")
        return

    st.markdown(f'<div class="card" style="border-left:3px solid #2E75B6">'
                f'<b>{sid}</b> to <b>{mkt}</b>, arriving <b>{arr:%d %b %Y}</b>, '
                f'from <b>{src}</b><br><b>{len(lines)}</b> items, '
                f'<b>{sum(x["Shipped Qty"] for x in lines):,}</b> boxes shipped'
                f'<div class="note">The store will record what actually '
                f'arrives.</div></div>', unsafe_allow_html=True)
    if st.button("Save shipment", type="primary", key=f"s_save_{n}"):
        rows = [{"Shipment No": sid, "Market": mkt, "Arrival Date": arr,
                 "Source": src, **ln} for ln in lines]
        try:
            with st.spinner("Saving…"):
                made = save_fn(rows, mkt)
            st.session_state["s_lines"] = []
            st.session_state.pop("s_no", None)
            st.session_state["e_n"] = _nonce() + 1
            st.success(f"Saved  ·  {made}")
            _mangoes()
            st.rerun()
        except Exception as ex:
            st.error(str(ex))

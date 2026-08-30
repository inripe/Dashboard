# -*- coding: utf-8 -*-
"""
Run every check in one go.

    python3 qa_all.py                  against the workbook the app uses
    python3 qa_all.py --live           against the live SharePoint copy
    python3 qa_all.py --book FILE      against a particular file

Each suite runs on its own so one failure never hides another.
"""
import subprocess, sys, os, time, io

SUITES = [
    ("sheet",      "qa.py",           "the workbook adds up"),
    ("dispatch",   "qa_dispatch.py",  "allocation, strategies, the age cap"),
    ("markets",    "qa_markets.py",   "four stores, four time zones"),
    ("legends",    "qa_legend.py",    "no colour without a key"),
    ("writer",     "qa_entry.py",     "append only, never edit or delete"),
    ("write path", "qa_write.py",     "two people saving at once"),
    ("entry rules","qa_entry_ui.py",  "what a store user may pick"),
    ("form",       "qa_form.py",      "the form never lies about what it saves"),
    ("labels",     "qa_labels.py",    "in / out and arabic on every movement"),
    ("access",     "qa_access.py",    "three roles, two protected tabs"),
    ("shipments",  "qa_shipment.py",  "sent is not the same as arrived"),
    ("integrity",  "qa_integrity.py", "the seams between all of it"),
    ("cleaner",    "qa_clean.py",     "removes only lines with no movements"),
    ("quantities", "qa_quantities.py","nothing goes out that is not there"),
    ("isolation",  "qa_isolation.py", "entry ignores the dashboard filters"),
    ("modes",      "qa_modes.py",     "each mode shows its own screen and no other"),
    ("review",     "qa_review.py",    "one function per tab, a comparison on every number"),
    ("reports",    "qa_reports.py",   "couriers, counts, clearance and today"),
    ("duplicates", "qa_dupes.py",     "the same entry twice is caught and voided"),
    ("names",      "qa_names.py",     "no retired movement name survives anywhere"),
    ("balance",    "qa_balance.py",   "shipped always equals received plus missing"),
    ("versioning", "qa_versioning.py","no save goes out without a version tag"),
    ("received",   "qa_received.py",  "sixteen items checked in one pass"),
    ("photo",      "qa_photo.py",     "a write-off needs evidence"),
    ("guide",      "qa_guide.py",     "the guide is plain and matches the app"),
    ("findings",   "qa_findings.py",  "what a real person found, so it cannot return"),
    ("custom",     "qa_custom.py",    "your own dispatch rule, nothing hidden"),
    ("reset",      "qa_reset.py",     "clearing data leaves MASTER whole"),
]


def fetch_live():
    import sharepoint_loader as sp
    buf, meta = sp.fetch_workbook()
    path = "/tmp/qa_live.xlsx"
    open(path, "wb").write(buf.getvalue())
    print(f"live workbook: {meta['name']} · saved {meta['modified']} · "
          f"{meta['size_kb']} KB\n")
    return path


def main():
    args = sys.argv[1:]
    book = None
    if "--book" in args:
        book = args[args.index("--book") + 1]
    elif "--live" in args or not any(
            os.path.exists(p) for p in ("INRIPE_Stock_Entry_v1.xlsx",
                                        "INRIPE_Stock_Entry_v3.xlsx")):
        # no workbook here, so there is nothing to test against but the live one
        book = fetch_live()
    env = dict(os.environ)
    env.setdefault("ENTRY_PASSWORD", "qa")
    env.setdefault("DISPATCH_PASSWORD", "qa")
    env.setdefault("ADMIN_PASSWORD", "qa")
    if book:
        env["QA_BOOK"] = book
        import shutil
        shutil.copy(book, "INRIPE_Stock_Entry_v1.xlsx")
        print(f"testing against {book}")
        import qa_book as _qb
        _used = _qb.book()
        if _used != book:
            _n = len(open(_used, "rb").read()) / 1024
            print(f"  the sheet is large, so the rule suites use its last few "
                  f"shipments ({_n:,.0f} KB).")
            print(f"  MASTER is whole, and the workbook itself is still "
                  f"checked in full by the first suite.")
            print(f"  QA_FULL=1 to test against all of it.")
        print()

    width = max(len(n) for n, _, _ in SUITES) + 2
    total_p = total_f = 0
    failed = []
    t0 = time.time()
    for name, script, what in SUITES:
        if not os.path.exists(script):
            continue   # a suite for a tool that is no longer here
        t = time.time()
        r = subprocess.run([sys.executable, script], capture_output=True,
                           text=True, env=env)
        out = (r.stdout or "") + (r.stderr or "")
        last = [l for l in out.strip().splitlines() if "passed," in l]
        p = f = 0
        if last:
            try:
                p = int(last[-1].split()[0]); f = int(last[-1].split()[2])
            except (ValueError, IndexError):
                pass
        total_p += p; total_f += f
        mark = "ok  " if f == 0 and r.returncode == 0 else "FAIL"
        print(f"  {mark}  {name:<{width}} {p:>4} checks   "
              f"{time.time()-t:>5.1f}s   {what}")
        if f or r.returncode:
            failed.append((name, out))
    print()
    print(f"  {total_p} checks passed, {total_f} failed, "
          f"{time.time()-t0:.0f}s")
    if failed:
        print("\n" + "=" * 62)
        for name, out in failed:
            print(f"\n{name}")
            for line in out.splitlines():
                if line.startswith("FAIL") or "Error" in line:
                    print("   ", line)
        print("=" * 62)
        return 1
    print("\n  Nothing is broken.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
Everything, in one run.

    python3 validate.py

Writes validate.txt. Send me that file and nothing else.

  1  the test suites, against your live workbook
  2  a probe of what I cannot reach: shopify, sharepoint, the environment
  3  every screen, as every kind of user
  4  six full seasons of trading against a copy, checking the ledger after
     every single action

Your live workbook is read, never written. Shopify is read, never written.
"""
import subprocess, sys, os, time, datetime as dt

PARTS = [
    ("suites",     ["qa_all.py", "--live"], "every rule, against your live sheet"),
    ("probe",      ["probe.py"],            "shopify, sharepoint, the workbook"),
    ("screens",    ["probe_ui.py"],         "every screen, as every role"),
    ("simulation", ["simulate.py"],         "six seasons of trading"),
]
NOISE = ("use_container_width", "ScriptRunContext", "Session state does not",
         "will be removed after", "For `use_container_width",
         "Please replace `use_container_width", "missing ScriptRunContext")


def main():
    lines = []
    def out(s=""):
        lines.append(s); print(s)
    out("INRIPE stock control · full validation")
    out(f"{dt.datetime.now():%d %b %Y %H:%M}")
    verdicts = []
    for name, cmd, what in PARTS:
        if not os.path.exists(cmd[0]):
            out(f"\n[{name}] {cmd[0]} is missing - skipped"); continue
        print(f"\n{name}: {what} …", file=sys.stderr)
        t = time.time()
        r = subprocess.run([sys.executable] + cmd, capture_output=True, text=True)
        body = (r.stdout or "")
        for ln in body.split("\n"):
            if any(n in ln for n in NOISE):
                continue
            lines.append(ln); print(ln)
        if r.returncode:
            for ln in (r.stderr or "").strip().split("\n")[-8:]:
                lines.append("  stderr: " + ln); print("  stderr:", ln)
        verdicts.append((name, r.returncode, time.time() - t))
    out(""); out("=" * 64); out("SUMMARY"); out("=" * 64)
    for name, rc, secs in verdicts:
        out(f"  {'ok  ' if rc == 0 else 'FAIL'}  {name:<12}{secs:>6.0f}s")
    bad = [n for n, rc, _ in verdicts if rc]
    out("")
    out("  Nothing is broken." if not bad
        else "  Look at: " + ", ".join(bad))
    open("validate.txt", "w").write("\n".join(lines))
    print(f"\n\nwritten to validate.txt · {len(lines)} lines · send me that file",
          file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

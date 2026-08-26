# -*- coding: utf-8 -*-
"""
Everything I cannot reach from here, in one pass.

    python3 probe_all.py

Writes probe.txt. Send me that file and nothing else.

It reads your live workbook, all four Shopify stores, and walks every screen of
the app as each kind of user. The workbook is written back byte-identical to
prove writing works; nothing else is changed and nothing is deleted.
"""
import subprocess, sys, os, datetime as dt

PARTS = [("data", "probe.py",    "workbook, shopify, sharepoint, dispatch"),
         ("ui",   "probe_ui.py", "every screen, as every role")]

def main():
    lines = []
    def out(s=""):
        lines.append(s); print(s)
    out("INRIPE stock control · probe")
    out(f"{dt.datetime.now():%d %b %Y %H:%M}")
    for name, script, what in PARTS:
        if not os.path.exists(script):
            out(f"\n[{name}] {script} is missing - skipped")
            continue
        print(f"\ncollecting {name} ({what}) …", file=sys.stderr)
        r = subprocess.run([sys.executable, script], capture_output=True, text=True)
        body = (r.stdout or "")
        noise = ("use_container_width", "ScriptRunContext", "Session state does not",
                 "will be removed after", "For `use_container_width",
                 "Please replace `use_container_width")
        for ln in body.split("\n"):
            if any(n in ln for n in noise):
                continue
            lines.append(ln); print(ln)
        if r.returncode:
            tail = (r.stderr or "").strip().split("\n")[-6:]
            for ln in tail:
                lines.append("  stderr: " + ln); print("  stderr:", ln)
    open("probe.txt", "w").write("\n".join(lines))
    print(f"\n\nwritten to probe.txt · {len(lines)} lines · send me that file",
          file=sys.stderr)

if __name__ == "__main__":
    main()

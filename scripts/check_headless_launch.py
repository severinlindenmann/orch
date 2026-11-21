#!/usr/bin/env python3
"""Every browser a script starts goes through the shared helper (ORCH-615, stdlib only).

Without '--use-mock-keychain' and '--password-store=basic' a headless Chromium on macOS asks the keychain, and the
person at the computer gets a password window ("headless_shell wants to use ... Chromium Safe Storage").
e2e/headless.cjs and e2e/headless.py always add both. This check fails when a JavaScript or Python file in the
repository:
  - calls a Playwright/Puppeteer launch (launch, launchPersistentContext, launch_persistent_context, launchServer,
    launch_server) on anything other than the helper, or
  - starts a Chrome binary itself with '--headless' and does not name both options.
Shipped add-on code cannot import a file of the repository; the few such files are listed in SHIPPED below and must
name both options themselves.

Usage: check_headless_launch.py [--repo DIR]
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

OPTIONS = ("--use-mock-keychain", "--password-store=basic")
HELPERS = {"e2e/headless.cjs", "e2e/headless.py"}
# Shipped with an add-on or the orch package: they keep their own copy of the two options (checked here).
SHIPPED = {
    "workspace-addons/dashboard/clickthrough/run.cjs",
}
# This check and its test name the patterns on purpose.
SKIP = {"scripts/check_headless_launch.py", "brand/tests/test_headless_launch.py"}
SUFFIXES = {".js", ".cjs", ".mjs", ".ts", ".py"}
BROWSER = re.compile(r"playwright|puppeteer|chromium|webkit|firefox", re.IGNORECASE)
LAUNCH = re.compile(
    r"(?<![\w$.])((?:[\w$]+\s*\.\s*)*?[\w$]+)\s*\.\s*"
    r"(launch|launchPersistentContext|launch_persistent_context|launchServer|launch_server)\s*\("
)
HEADLESS_FLAG = re.compile(r"""["']--headless(?:=[\w]+)?["']""")


def problems(rel: str, text: str) -> list[str]:
    """What is wrong in one file (empty when it is fine)."""
    if rel in HELPERS or rel in SKIP or Path(rel).suffix not in SUFFIXES or not BROWSER.search(text):
        return []
    has_options = all(o in text for o in OPTIONS)
    out = []
    for m in LAUNCH.finditer(text):
        receiver = re.sub(r"\s+", "", m.group(1))
        if receiver == "headless" or receiver.endswith(".headless"):
            continue
        if rel in SHIPPED and has_options:
            continue
        line = text.count("\n", 0, m.start()) + 1
        out.append(f"{rel}:{line}: {receiver}.{m.group(2)}(...) starts a browser without the shared helper; "
                   f"use headless.{'launchPersistent' if 'ersistent' in m.group(2) else 'launch'}(...) from "
                   f"e2e/headless.{'py' if rel.endswith('.py') else 'cjs'}")
    if HEADLESS_FLAG.search(text) and not has_options:
        line = text.count("\n", 0, HEADLESS_FLAG.search(text).start()) + 1
        out.append(f"{rel}:{line}: starts Chrome with --headless but does not name {OPTIONS[0]} and {OPTIONS[1]}")
    return out


def files(repo: Path) -> list[str]:
    try:
        listed = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True)
        names = listed.stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        names = [str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file()]
    return sorted(n for n in names if Path(n).suffix in SUFFIXES and "node_modules/" not in n)


def check(repo: Path) -> list[str]:
    out = []
    for rel in files(repo):
        try:
            text = (repo / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out += problems(rel, text)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    found = check(Path(ap.parse_args(argv).repo))
    for p in found:
        print(p)
    if found:
        print(f"\n{len(found)} browser start(s) without the keychain options. See e2e/headless.cjs (ORCH-615).")
        return 1
    print("Every browser start goes through the shared helper.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

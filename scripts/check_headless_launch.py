#!/usr/bin/env python3
"""Every browser a script starts goes through the shared helper (ORCH-615, stdlib only).

Without '--use-mock-keychain' and '--password-store=basic' a headless Chromium on macOS asks the keychain, and the
person at the computer gets a password window ("headless_shell wants to use ... Chromium Safe Storage").
e2e/headless.cjs and e2e/headless.py always add both. This check fails when a JavaScript or Python file in the
repository:
  - calls a Playwright/Puppeteer launch (launch, launchPersistentContext, launch_persistent_context, launchServer,
    launch_server) on anything other than the helper, or
  - starts a Chrome binary itself with '--headless' and does not name both options, or
  - gives a browser a profile folder: launchPersistentContext / launch_persistent_context, userDataDir /
    user_data_dir, or '--user-data-dir' (ORCH-1101). The headless shell ignores '--use-mock-keychain' once it
    keeps a profile on disk and macOS asks the owner for the keychain password (seen 20 Nov, release walk).
    Use launch() + newContext() (cookies in memory); keep a sign-in in a storageState file. Only the files in
    FULL_CHROME may name a profile folder: they start the full Chrome browser, which honours the mock keychain.
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
    "workspace-addons/browse/src/orch_browse/broker.py",
}
# Start the full Google Chrome / Chrome for Testing (never the headless shell) with a throwaway profile folder and both
# options; the full browser honours '--use-mock-keychain' (watcher log 20-21 Nov: no prompt from them).
FULL_CHROME = {"workspace/src/orch/cli_shot.py", "workspace/tests/test_shot.py"}
# This check and its test name the patterns on purpose.
SKIP = {"scripts/check_headless_launch.py", "brand/tests/test_headless_launch.py"}
SUFFIXES = {".js", ".cjs", ".mjs", ".ts", ".py", ".sh"}
BROWSER = re.compile(r"playwright|puppeteer|chromium|chrome|headless_shell|webkit|firefox", re.IGNORECASE)
LAUNCH = re.compile(
    r"(?<![\w$.])((?:[\w$]+\s*\.\s*)*?[\w$]+)\s*\.\s*"
    r"(launch|launchPersistentContext|launch_persistent_context|launchServer|launch_server)\s*\("
)
HEADLESS_FLAG = re.compile(r"""["']--headless(?:=[\w]+)?["']""")
PROFILE = re.compile(r"launchPersistentContext|launch_persistent_context|\blaunchPersistent\b|\blaunch_persistent\b"
                     r"|\buserDataDir\b|\buser_data_dir\b|--user-data-dir")


def problems(rel: str, text: str) -> list[str]:
    """What is wrong in one file (empty when it is fine)."""
    if rel in HELPERS or rel in SKIP or Path(rel).suffix not in SUFFIXES or not BROWSER.search(text):
        return []
    out = []
    if rel not in FULL_CHROME:
        for m in PROFILE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            out.append(f"{rel}:{line}: {m.group(0)} gives the browser a profile folder; the headless shell then asks "
                       f"the macOS keychain. Use launch() + newContext() (a storageState file for a sign-in)")
    if Path(rel).suffix == ".sh":
        return out
    has_options = all(o in text for o in OPTIONS)
    for m in LAUNCH.finditer(text):
        receiver = re.sub(r"\s+", "", m.group(1))
        if m.group(2) in ("launchPersistentContext", "launch_persistent_context"):
            continue  # already named above as a profile folder
        if receiver == "headless" or receiver.endswith(".headless"):
            continue
        if rel in SHIPPED and has_options:
            continue
        line = text.count("\n", 0, m.start()) + 1
        out.append(f"{rel}:{line}: {receiver}.{m.group(2)}(...) starts a browser without the shared helper; "
                   f"use headless.launch(...) from "
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
        print(f"\n{len(found)} browser start(s) that can ask the keychain. See e2e/headless.cjs (ORCH-615, ORCH-1101).")
        return 1
    print("Every browser start goes through the shared helper.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

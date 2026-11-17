"""`orch shot`: screenshots of a page or file at one or more widths, with a browser that never touches the
keychain. Helpers use this instead of writing their own script, so no "Chromium Safe Storage" password
window appears on the person's screen."""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from orch.errors import Refused

# The two options that keep the macOS keychain (and its password window) out of it, plus a clean headless run.
SAFE_FLAGS = (
    "--headless=new",
    "--use-mock-keychain",
    "--password-store=basic",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-gpu",
    "--hide-scrollbars",
)
DEFAULT_WIDTHS = (1280, 1920, 390)
_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
    "~/.cache/ms-playwright/chromium-*/chrome-linux/chrome",
)


def add_parsers(sub, common) -> None:
    x = sub.add_parser(
        "shot", parents=[common], help="screenshots of a page or file, with no keychain window"
    )
    x.add_argument("target", help="an address (http://...) or an HTML file")
    x.add_argument("--width", default=",".join(map(str, DEFAULT_WIDTHS)), metavar="W[,W...]")
    x.add_argument("--height", type=int, metavar="PX", help="default 800 (1080 at 1920, 844 under 500 wide)")
    x.add_argument("--out", default=".", metavar="FOLDER", help="folder for the pictures")
    x.add_argument("--name", default="shot", help="start of each file name")
    x.add_argument("--wait", type=int, default=8, metavar="SEC", help="longest wait for the page to settle")


def find_browser() -> str:
    env = os.environ.get("ORCH_SHOT_BROWSER")
    if env and os.access(env, os.X_OK):
        return env
    for c in _CANDIDATES:
        for p in sorted(glob.glob(os.path.expanduser(c))):
            if os.access(p, os.X_OK):
                return p
    for n in ("google-chrome", "chromium", "chromium-browser"):
        if w := shutil.which(n):
            return w
    raise Refused("No Chrome or Chromium found. Set ORCH_SHOT_BROWSER to its path.")


def parse_widths(text: str) -> list[int]:
    try:
        w = [int(p) for p in text.split(",") if p.strip()]
    except ValueError:
        raise Refused(f"'{text}' is not a list of widths like 1280,390.") from None
    if not w or any(not 200 <= n <= 4000 for n in w):
        raise Refused("Widths must be between 200 and 4000.")
    return w


def target_url(target: str) -> str:
    if target.startswith(("http://", "https://", "file://")):
        return target
    p = Path(target).expanduser()
    if not p.is_file():
        raise Refused(f"No such file: {target}")
    return p.resolve().as_uri()


def command(browser: str, profile: str, url: str, out: Path, width: int, height: int, wait: int) -> list[str]:
    return [
        browser,
        *SAFE_FLAGS,
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={wait * 1000}",
        f"--screenshot={out}",
        url,
    ]


def shoot(
    target: str, widths: list[int], out_dir: Path, name: str, height: int | None, wait: int
) -> list[Path]:
    url = target_url(target)
    browser = find_browser()
    out_dir.mkdir(parents=True, exist_ok=True)
    # One profile for the whole run (a sign-in link in the address is spent once; the cookie it sets
    # then carries the later widths); removed by its exact path at the end.
    profile = tempfile.mkdtemp(prefix="orch-shot-")
    done: list[Path] = []
    try:
        for w in widths:
            out = (out_dir / f"{name}-{w}.png").resolve()
            h = height or (844 if w < 500 else 1080 if w >= 1900 else 800)
            cmd = command(
                browser, profile, url if not done else re.sub(r"#launch=.*$", "", url), out, w, h, wait
            )
            try:
                subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=wait + 60)
            except subprocess.TimeoutExpired:
                pass
            if not out.is_file() or out.stat().st_size == 0:
                raise Refused(f"No picture was made for {url} at {w} wide.")
            done.append(out)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    return done


def dispatch(args, root: Path) -> bool:
    if args.cmd != "shot":
        return False
    files = shoot(args.target, parse_widths(args.width), Path(args.out), args.name, args.height, args.wait)
    if getattr(args, "json", False):
        import json

        print(json.dumps({"files": [str(f) for f in files]}))
    else:
        print("\n".join(str(f) for f in files))
    return True

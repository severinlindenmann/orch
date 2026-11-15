#!/usr/bin/env python3
"""R6.2 style lint (stdlib only): no new .css files, <style> blocks or hex colour literals outside the master.

Exempt: the master (workspace/src/orch_ui/static), brand/ and generated token files.
Everything else is counted per file and compared to brand/tests/style_allowlist.json
({file: {"hex": n, "style": n}}). A file fails when it has MORE than listed, or is a new .css file / not listed.
`python scripts/check_style.py --update` rewrites the allowlist (only lower the numbers, never raise them).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "brand/tests/style_allowlist.json"
EXEMPT_PREFIX = (
    "workspace/src/orch_ui/static/",
    "brand/",
    "workspace/src/orch/templates/",  # starter files of the USER's own app (publish), not orch's look
    "workspace-addons/dashboard/mockup/previews/assets/",  # sample user content shown inside a file preview
    "workspace-addons/dashboard/mockup/ticket/assets/",  # sample user report shown inside a ticket mockup
)
EXEMPT_FILES = {
    "mobile/OrchMobileTests/Fixtures/tokens.css",  # copy of the generated tokens
    # generated colour DATA for the workspace look picker (contracts/look.json), not styling
    "workspace-addons/dashboard/src/orch_dashboard/web/look-colors.css",  # tools/gen_look_icons.py
    "workspace-addons/dashboard/src/orch_dashboard/web/look-icons.js",  # tools/gen_look_icons.py
    "relay/web/look-data.js",  # scripts/gen_look_web.py
    "relay/web/look-bundle.js",  # scripts/gen_look_web.py
    "publish/web/look-data.js",  # scripts/gen_look_web.py
    "publish/web/look-bundle.js",  # scripts/gen_look_web.py
    "workspace-addons/dashboard/mockup/previews/viewer-html.html",  # a sample user web page inside the preview mockup
}
EXEMPT_TESTS = ("/tests/", ".test.js")  # tests may plant hex colours and <style> to check the lint and the CSP
EXTS = {".css", ".html", ".js", ".swift"}
HEX = re.compile(r"(?<![\w&/#-])(?<!href=\")(?<!href=')(?<!href:')(?<!href:\")#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![\w-])")
STYLE = re.compile(r"<style\b", re.I)


COMMENT = re.compile(r"/\*.*?\*/|<!--.*?-->|(?:^|(?<=\s))//[^\n]*", re.S)


def count(text: str) -> dict:
    """Comments are skipped: an issue reference like "(#825)" in a comment is not a colour."""
    code = COMMENT.sub(" ", text)
    return {"hex": len(HEX.findall(code)), "style": len(STYLE.findall(code))}


def scan(root: Path = ROOT) -> dict:
    files = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")
    out = {}
    for f in files:
        if not f or Path(f).suffix not in EXTS or f.startswith(EXEMPT_PREFIX) or f in EXEMPT_FILES or any(x in f for x in EXEMPT_TESTS):
            continue
        p = root / f
        if not p.is_file():
            continue
        c = count(p.read_text(errors="ignore"))
        if c["hex"] or c["style"] or f.endswith(".css"):
            out[f] = c
    return out


def violations(current: dict, allowed: dict) -> list[str]:
    bad = []
    for f, c in sorted(current.items()):
        a = allowed.get(f)
        if a is None:
            bad.append(f"{f}: new file with {c['hex']} hex colours, {c['style']} <style> blocks")
            continue
        for k in ("hex", "style"):
            if c[k] > a.get(k, 0):
                bad.append(f"{f}: {c[k]} {k} (allowed {a.get(k, 0)})")
    return bad


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cur = scan()
    if "--update" in argv:
        ALLOWLIST.write_text(json.dumps(cur, indent=1, sort_keys=True) + "\n")
        print(f"wrote {len(cur)} files")
        return 0
    bad = violations(cur, json.loads(ALLOWLIST.read_text()))
    for b in bad:
        print(b)
    if bad:
        print("R6.2: build the look in workspace/src/orch_ui/static (tokens, components), not in page css, <style> blocks or hex colours.")
        return 1
    print("style lint ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

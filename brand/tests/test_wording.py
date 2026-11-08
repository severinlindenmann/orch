"""Fail when a "never use" word (docs/wording.md) is added to a UI string file.

Today's hits are listed in wording_allowlist.json (file -> word -> count), so the test is green now and every new hit fails.
`python brand/tests/test_wording.py` prints the todo list (all current hits) for the lanes that own those files.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).with_name("wording_allowlist.json")

NEVER = [
    "Request", "Requests", "Job", "Issue", "Todo", "Subtask", "Epic", "Inbox", "Over to you", "Approval",
    "Sign-off", "Recommended", "Evidence", "Artifact", "Scheduler", "Cron", "Schedule", "Bot", "NetBird",
    "Peer", "Node",
]  # fmt: skip
WORD = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted(map(re.escape, NEVER), key=len, reverse=True)) + r")(?![A-Za-z])")

UI_GLOBS = [
    "workspace-addons/*/src/**/web/*.js",
    "workspace-addons/*/src/**/web/*.html",
    "workspace/src/orch_ui/static/*.js",
    "workspace/src/orch_ui/static/*.html",
    "workspace/src/orch_ui/static/*.css",
    "mobile/OrchMobile/Views/*.swift",
    "relay/web/*.html",
    "publish/web/*.html",
]
# "quoted string" or >tag text<. Comments and identifiers are not UI text.
STRING = re.compile(r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`|>([^<>]+)<")
# code that is not shown: skip files that only hold kit internals
SKIP_FILES = {"workspace/src/orch_ui/static/tokens.css", "workspace/src/orch_ui/static/icons.js"}


def ui_files():
    seen = set()
    for g in UI_GLOBS:
        for p in sorted(ROOT.glob(g)):
            rel = p.relative_to(ROOT).as_posix()
            if p.is_file() and rel not in SKIP_FILES and rel not in seen:
                seen.add(rel)
                yield rel, p


def hits() -> dict[str, Counter]:
    out: dict[str, Counter] = {}
    for rel, p in ui_files():
        c: Counter = Counter()
        for line in p.read_text(errors="ignore").splitlines():
            if line.lstrip().startswith(("//", "/*", "*", "<!--")):
                continue
            for m in STRING.finditer(line):
                for w in WORD.findall(m.group(0)):
                    c[w] += 1
        if c:
            out[rel] = c
    return out


def test_no_new_never_words():
    allowed = json.loads(ALLOWLIST.read_text())
    new = []
    for rel, c in hits().items():
        for w, n in c.items():
            if n > allowed.get(rel, {}).get(w, 0):
                new.append(f"{rel}: '{w}' x{n} (allowed {allowed.get(rel, {}).get(w, 0)})")
    assert not new, "words from docs/wording.md 'never use':\n" + "\n".join(new)


def test_wording_table_lists_every_never_word():
    table = (ROOT / "docs" / "wording.md").read_text()
    for w in NEVER:
        assert w.replace("Requests", "Request") in table, f"{w} missing from docs/wording.md"


def test_allowlist_has_no_stale_entries():
    allowed = json.loads(ALLOWLIST.read_text())
    now = hits()
    stale = [f"{rel}: {w}" for rel, ws in allowed.items() for w, n in ws.items() if now.get(rel, {}).get(w, 0) < n]
    assert not stale, "lower these in wording_allowlist.json (good news, words were removed):\n" + "\n".join(stale)


def todo() -> str:
    lines = [f"{rel}: " + ", ".join(f"{w} x{n}" for w, n in sorted(c.items())) for rel, c in hits().items()]
    return "\n".join(lines) or "(none)"


if __name__ == "__main__":
    if "--write-allowlist" in sys.argv:
        ALLOWLIST.write_text(json.dumps({r: dict(c) for r, c in hits().items()}, indent=1, sort_keys=True) + "\n")
    print(todo())

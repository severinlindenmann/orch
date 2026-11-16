"""Fail when a "never use" word (docs/wording.md) is added to a UI string file or to text in orch's Python code.

Python files (the CLI and the add-ons print what they hold) count every string literal except docstrings and
lowercase keys, flags and patterns kept for data compatibility (`"proof"`, `"--proof-target"`, `"a|b|proof"`).
"proof" is also caught in lowercase ("No proof yet"); the screen word is Evidence.

Today's hits are listed in wording_allowlist.json (file -> word -> count), so the test is green now and every new hit fails.
`python brand/tests/test_wording.py` prints the todo list (all current hits) for the lanes that own those files.
"""

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).with_name("wording_allowlist.json")

NEVER = [
    "Request", "Requests", "Job", "Issue", "Todo", "Subtask", "Inbox", "Over to you", "Approval",
    "Sign-off", "Recommended", "Proof", "Artifact", "Scheduler", "Cron", "Schedule", "Bot", "NetBird",
    "Peer", "Node", "Sign", "Signed", "Signature", "signed", "signature",
]  # fmt: skip
# "Issue" alone is banned; an outside item keeps its tool's own word ("GitHub issue", "Jira Issue"): see wording.md
TOOLS = ("GitHub", "GitLab", "Jira", "Linear", "Trello")
_ISSUE = "".join(f"(?<!{t} )" for t in TOOLS) + "Issue"
# the page login keeps its words ("Sign in", "signed out"): only confirming a choice must not use them
_LOGIN = r"(?![ -]?(?:in|out|up|on)(?![A-Za-z]))"
_SPECIAL = {"Issue": _ISSUE, "Sign": "Sign" + _LOGIN, "Signed": "Signed" + _LOGIN, "signed": "signed" + _LOGIN}
WORD = re.compile(
    r"(?<![A-Za-z])("
    + "|".join(sorted((_SPECIAL.get(w, re.escape(w)) for w in NEVER), key=len, reverse=True))
    + r")(?![A-Za-z])"
)
# lowercase never-words that are only ever the screen word in a sentence; a key-like neighbour (proof-chip,
# task_proof, proof.js) is code, not text
LOWER = re.compile(r"(?<![A-Za-z_.-])(proofs?)(?![A-Za-z_-]|\.\w)")
# a string with no space made of lowercase key characters is a data key, flag, class or pattern, not text
KEYLIKE = re.compile(r"[a-z0-9_.:/|\\-]*")

UI_GLOBS = [
    "workspace-addons/*/src/**/web/*.js",
    "workspace-addons/*/src/**/web/pages/*.js",
    "workspace-addons/*/src/**/web/*.html",
    "workspace/src/orch_ui/static/*.js",
    "workspace/src/orch_ui/static/*.html",
    "workspace/src/orch_ui/static/*.css",
    "mobile/OrchMobile/Views/*.swift",
    "relay/web/*.html",
    "publish/web/*.html",
]
PY_GLOBS = ["workspace/src/**/*.py", "workspace-addons/*/src/**/*.py"]
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


def py_files():
    seen = set()
    for g in PY_GLOBS:
        for p in sorted(ROOT.glob(g)):
            rel = p.relative_to(ROOT).as_posix()
            if p.is_file() and rel not in seen:
                seen.add(rel)
                yield rel, p


def never_words(text: str) -> list[str]:
    """The never-words in one piece of shown text (a string's content, quotes allowed around it)."""
    if KEYLIKE.fullmatch(text.strip("\"'`")):
        return []
    return WORD.findall(text) + LOWER.findall(text)


def py_strings(source: str) -> list[str]:
    """Every string literal of a Python file (f-string parts too), docstrings left out."""
    tree = ast.parse(source)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docs.add(id(first.value))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
    ]


def hits() -> dict[str, Counter]:
    out: dict[str, Counter] = {}
    for rel, p in ui_files():
        c: Counter = Counter()
        for line in p.read_text(errors="ignore").splitlines():
            if line.lstrip().startswith(("//", "/*", "*", "<!--")):
                continue
            for m in STRING.finditer(line):
                c.update(never_words(m.group(1) if m.group(1) is not None else m.group(0)))
        if c:
            out[rel] = c
    for rel, p in py_files():
        c = Counter(w for text in py_strings(p.read_text(errors="ignore")) for w in never_words(text))
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


def test_issue_is_allowed_only_with_a_tool_name_in_front():
    assert WORD.findall('"GitHub Issue" "Jira Issue 4"') == []
    assert WORD.findall('"Issue" "New Issue"') == ["Issue", "Issue"]


def test_python_text_is_checked_but_keys_and_docstrings_are_not():
    src = '"""Proof files: the docstring is not shown."""\nKEY = "proof"\nFLAG = "--proof-target"\n'
    src += 'def f(n):\n    """No proof here either."""\n    return f"Proof: {n}" + "A proof file is too big."\n'
    assert sorted(w for t in py_strings(src) for w in never_words(t)) == ["Proof", "proof"]


def test_lowercase_proof_only_as_a_word():
    assert never_words("No proof yet") == ["proof"] and never_words("done only with proof.") == ["proof"]
    assert never_words("chip proof-chip") == [] and never_words("task_proof") == [] and never_words("proof.js") == []


def test_confirm_words_replace_the_old_ones():
    assert WORD.findall('"Sign" "Signed. Saved." "Needs your signature" "You have signed this"') == ["Sign", "Signed", "signature", "signed"]
    assert WORD.findall('"Sign in" "Signed out" "signed in as Mia" "Sign-in" "Confirm" "Needs your OK" "design" "assigned"') == []

"""Which members of a red queue group touch what failed (ORCH-558). No AI call, no GitHub call.

A red group used to be split in halves, blindly: a group of 10 with one bad pull request took about four more
runs of the full suite. Now the failed checks' names are compared with the files each member changes: the words
of a check name (`addons / dashboard-clickthroughs` -> addons, dashboard, clickthroughs) against the words of each
changed path (`workspace-addons/dashboard/src/x.js` -> workspace, addons, dashboard, src, x, js). The members with
the most shared words are the suspects; the runner checks the others together first (they merge on green) and the
suspects after. No member shares a word, or every member shares the same number: the runner splits in halves.

The failed tests come first (ORCH-1118): 'addons / dashboard-clickthroughs' shares 'dashboard' with every member
that touches the dashboard, so the test files the failed jobs' logs name (`FAILED tests/test_sessions.py::...`,
`FAILED  Relay: ... (m-relay-chat.cjs, 34.9s)`) are compared first; only when they tell nobody apart do the
check names decide.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_WORD = re.compile(r"[a-z0-9]+")
# words of check names that say nothing about where the failure is
NOISE = frozenset(
    {"test", "tests", "check", "checks", "job", "jobs", "ci", "run", "ubuntu", "macos", "windows", "latest",
     "linux", "part", "parts", "the", "and", "of", "src", "py", "js", "cjs", "mjs", "md", "json", "toml"}
)  # fmt: skip
# a line of a failed job's log that reports a failure (pytest -rfE, node --test, the dashboard click-throughs);
# `gh run view --log-failed` puts "<job>\t<step>\t<time> " in front of each line
_FAILED_LINE = re.compile(r"^(?:[^\t\n]*\t[^\t\n]*\t\S+ )?\s*(?:FAILED|ERROR|not ok|✖)\s.*$", re.MULTILINE)
_TEST_FILE = re.compile(r"[\w./-]*?([\w-]+\.(?:py|cjs|mjs|js|ts|swift))\b")


def words(text: str) -> frozenset[str]:
    return frozenset(w for w in _WORD.findall(text.lower()) if len(w) >= 3 and w not in NOISE)


def score(failed: Iterable[str], paths: Iterable[str]) -> int:
    """How many words the failed checks share with the changed paths."""
    want = frozenset().union(*(words(c) for c in failed)) if failed else frozenset()
    have = frozenset().union(*(words(p) for p in paths)) if paths else frozenset()
    return len(want & have)


def failed_tests(log: str, most: int = 20) -> list[str]:
    """The test file names a failed job's log names on its failure lines, in order, each once."""
    out: list[str] = []
    for line in _FAILED_LINE.findall(log or ""):
        for name in _TEST_FILE.findall(line):
            if name not in out:
                out.append(name)
    return out[:most]


def first_failure(log: str, most: int = 160) -> str:
    """The first failure line of a failed job's log, without gh's job/step/time prefix (ORCH-1377): the test the
    queue names when a pull request leaves for its own checks. '' when the log names none."""
    m = _FAILED_LINE.search(log or "")
    if not m:
        return ""
    line = re.sub(r"^[^\t\n]*\t[^\t\n]*\t\S+ ", "", m.group(0)).strip()
    return " ".join(line.split())[:most]


_PY_FROM = re.compile(r"^[ \t]*from[ \t]+([\w.]+)[ \t]+import[ \t]+(\([^)]*\)|[\w \t,]+)", re.MULTILINE)
_PY_IMPORT = re.compile(r"^[ \t]*import[ \t]+([\w.]+(?:[ \t]*,[ \t]*[\w.]+)*)[ \t]*(?:#.*)?$", re.MULTILINE)
_JS_FROM = re.compile(r"""(?:require\(\s*|\bfrom\s+|\bimport\s*\(?\s*)['"]([^'"]+)['"]""")


def imports(source: str) -> list[str]:
    """What a test file imports, as module paths without extension ('orch/reads', 'orch_dashboard/views',
    'helpers'): Python `from a.b import c, d` gives a/b, a/b/c and a/b/d; `import a.b` gives a/b; JavaScript
    require/import of './x.js' gives x (its file name only)."""
    out: list[str] = []

    def add(stem: str) -> None:
        stem = stem.strip("/")
        if stem and stem not in out:
            out.append(stem)

    for mod, names in _PY_FROM.findall(source or ""):
        base = mod.lstrip(".").replace(".", "/")
        add(base)
        for n in names.strip("()").replace("\n", ",").split(","):
            n = n.strip().split(" as ")[0].strip()
            if n.isidentifier():
                add(f"{base}/{n}" if base else n)
    for mods in _PY_IMPORT.findall(source or ""):
        for m in mods.split(","):
            add(m.strip().split(" as ")[0].replace(".", "/"))
    for spec in _JS_FROM.findall(source or ""):
        if spec.startswith("."):
            add(re.sub(r"\.(c|m)?js$|\.ts$", "", spec.rsplit("/", 1)[-1]))
    return out


def _stem(path: str) -> str:
    stem = re.sub(r"\.(py|cjs|mjs|js|ts)$", "", path)
    return stem.removesuffix("/__init__")


def _touches(paths: Iterable[str], tests: Iterable[str], mods: Iterable[str]) -> bool:
    """A changed path is one of the failing test files, or a module the failing suites import."""
    tests, mods = set(tests), list(mods)
    for p in paths:
        if p in tests:
            return True
        s = _stem(p)
        if any(s == m or s.endswith("/" + m) for m in mods):
            return True
    return False


def suspects(
    failed: Iterable[str],
    members: list[tuple[str, list[str]]],
    tests: Iterable[str] = (),
    sources: dict[str, str] | None = None,
) -> list[str]:
    """The keys of the suspects of a red group. First the members that change a failing test file or a module
    the failing suites import (sources: {test path: its text}, ORCH-1377: a core change in reads.py broke the
    dashboard add-on's tests twice while the word guess blamed the dashboard member); else those that touch
    the failed tests' words most, else the failed checks' words most; [] when that tells nothing apart."""
    if sources and len(members) >= 2:
        mods = [m for text in sources.values() for m in imports(text)]
        hit = [k for k, paths in members if _touches(paths, sources, mods)]
        if hit and len(hit) < len(members):
            return hit
    picked = _pick([t for t in tests if t], members)
    return picked or _pick([c for c in failed if c], members)


def _pick(failed: list[str], members: list[tuple[str, list[str]]]) -> list[str]:
    if not failed or len(members) < 2:
        return []
    got = {k: score(failed, paths) for k, paths in members}
    top = max(got.values())
    picked = [k for k, s in got.items() if s == top]
    if top == 0 or len(picked) == len(members):
        return []
    return picked

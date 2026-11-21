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


def suspects(
    failed: Iterable[str], members: list[tuple[str, list[str]]], tests: Iterable[str] = ()
) -> list[str]:
    """The keys of the members that touch the failed tests most, else the failed checks most; [] when that
    tells nothing apart (no failed name, no member shares a word, or every member shares as many)."""
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

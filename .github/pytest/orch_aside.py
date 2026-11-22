"""Tests a person set aside (ORCH-455): still run and shown, but an expected failure, not a red run.

The pull-requests add-on finds a test that fails the same way on 3 or more unrelated pull requests within an hour,
opens one issue and asks a person on a "Broken test" ticket. A yes writes the repository's Actions variable
ORCH_ASIDE, a JSON list of {check, test, issue}; the workflows hand it to every pytest run with this plugin
(PYTEST_PLUGINS=orch_aside, PYTHONPATH=.github/pytest). Each listed pytest test (`path::name`, several joined by
" + ") is marked xfail(strict=False): it still runs, shows as XFAIL (or XPASS once fixed) and no longer fails the
run. Closing the issue takes it off the list. No variable, an empty one or one that cannot be read: nothing
changes. Node tests and checks without a pytest test name are not covered here.
"""

from __future__ import annotations

import json
import os

import pytest


def aside(raw: str | None = None) -> dict[str, str]:
    """The set-aside pytest tests from ORCH_ASIDE: {test: issue}."""
    try:
        rows = json.loads(os.environ.get("ORCH_ASIDE", "") if raw is None else raw or "[]")
    except ValueError:
        return {}
    out: dict[str, str] = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        for t in str(r.get("test") or "").split(" + "):
            t = t.strip()
            if "::" in t and ".py::" in t:
                out[t] = str(r.get("issue") or "")
    return out


def matches(nodeid: str, test: str) -> bool:
    """The same test, also when one of them was named from another folder (`tests/a.py::t` vs `a.py::t`)."""
    return nodeid == test or nodeid.endswith("/" + test) or test.endswith("/" + nodeid)


def pytest_collection_modifyitems(config, items):
    tests = aside()
    for item in items if tests else []:
        for test, issue in tests.items():
            if matches(item.nodeid, test):
                why = f"set aside until {issue or 'its issue'} is fixed (ORCH-455)"
                item.add_marker(pytest.mark.xfail(reason=why, strict=False))
                break


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Shown in every run's log while something is set aside (with xdist the workers mark, this names)."""
    tests = aside()
    if tests:
        terminalreporter.write_line(
            f"set aside (ORCH-455: still run, an expected failure): {', '.join(sorted(tests)[:10])}"
        )

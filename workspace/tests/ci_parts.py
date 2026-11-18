"""CI parts and per-test time budgets (ORCH-315). Hooked in from conftest.py.

`--part K/N` runs only part K of N of the collected tests, so CI can split the suite over N jobs that each
stay under 15 minutes. A test belongs to the part picked by a hash of its node id: the same test always lands
in the same part, every test lands in exactly one part, and the parts hold about the same number of tests.
Every xdist worker collects the same tests and so drops the same ones.

`--budget S` (or ORCH_TEST_BUDGET=S) fails a test whose call took longer than S seconds, even when it passed:
a slow test gets faster or says why it may take longer with @pytest.mark.budget(N). Off when unset. The hang
guard stays pytest-timeout (pyproject.toml): it stops a test, the budget only judges one that finished.
"""

from __future__ import annotations

import hashlib
import os

import pytest

# read once at start: a test that sets ORCH_TEST_BUDGET for a child run never changes this run's budget
_BUDGET = pytest.StashKey[float | None]()


def parse_part(text: str) -> tuple[int, int]:
    """'2/4' -> (2, 4). Refuses anything else with a plain message."""
    try:
        k, n = (int(x) for x in text.split("/"))
    except ValueError:
        raise pytest.UsageError(f"--part wants K/N such as 2/4, got {text!r}") from None
    if n < 1 or not 1 <= k <= n:
        raise pytest.UsageError(f"--part {text}: K must be between 1 and N")
    return k, n


def part_of(nodeid: str, n: int) -> int:
    """The part (1..n) a test belongs to; stable across runs, machines and Python versions."""
    h = int.from_bytes(hashlib.sha256(nodeid.encode("utf-8")).digest()[:8], "big")
    return h % n + 1


def budget_seconds(config: pytest.Config) -> float | None:
    raw = config.getoption("--budget") or os.environ.get("ORCH_TEST_BUDGET") or ""
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise pytest.UsageError(f"--budget wants seconds, got {raw!r}") from None
    return value if value > 0 else None


def addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("orch CI")
    group.addoption("--part", default=None, help="run only part K of N of the tests, such as 2/4")
    group.addoption(
        "--budget", default=None, help="fail a test whose call takes longer than this many seconds"
    )


def configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "budget(seconds): this test may take up to that many seconds")
    if config.getoption("--part"):
        parse_part(config.getoption("--part"))  # a wrong value stops the run before collection
    config.stash[_BUDGET] = budget_seconds(config)


def select_part(config: pytest.Config, items: list[pytest.Item]) -> None:
    text = config.getoption("--part")
    if not text:
        return
    k, n = parse_part(text)
    keep, drop = [], []
    for item in items:
        (keep if part_of(item.nodeid, n) == k else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


def over_budget(item: pytest.Item, duration: float) -> str | None:
    """The failure text when a passed call took longer than its budget, else None."""
    limit = item.config.stash.get(_BUDGET, None)
    if limit is None:
        return None
    mark = item.get_closest_marker("budget")
    if mark and mark.args:
        limit = float(mark.args[0])
    if duration <= limit:
        return None
    return (
        f"{item.nodeid} took {duration:.1f} s, over its time budget of {limit:g} s. "
        "Make it faster, or mark it @pytest.mark.budget(<seconds>) with a comment why it needs longer."
    )


def judge(item: pytest.Item, report: pytest.TestReport) -> None:
    if report.when != "call" or not report.passed:
        return
    text = over_budget(item, report.duration)
    if text:
        report.outcome = "failed"
        report.longrepr = text

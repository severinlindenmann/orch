"""CI parts and per-test time budgets (ORCH-315). Hooked in from conftest.py.

`--part K/N` runs only part K of N of the collected tests, so CI can split the suite over N jobs that each
stay under 15 minutes. A test belongs to the part picked by a hash of its node id: the same test always lands
in the same part, every test lands in exactly one part, and the parts hold about the same number of tests.
Every xdist worker collects the same tests and so drops the same ones.

`--part-times FILE` (ORCH-1050) splits by measured time instead of by count: the hash put most of the 60-110 s
bring-back tests into Windows part 12 of 16 (14-15 min of a 15-minute limit while part 1 took 3 min). With the
file the tests are dealt out slowest first, each to the part with the least time so far (ties to the lower
part, then by node id): still every test in exactly one part and the same answer on every worker, as the order
only depends on the times and the node ids. A test the file does not know counts its `default_s`.
`--times-out FILE` writes how long every test of this run took (setup + call + teardown, the controller only)
so CI can keep the file current:
`python tests/ci_parts.py merge tests/ci_times_windows.json <downloaded files...>`.

`--budget S` (or ORCH_TEST_BUDGET=S) fails a test whose call took longer than S seconds, even when it passed:
a slow test gets faster or says why it may take longer with @pytest.mark.budget(N). Off when unset. The hang
guard stays pytest-timeout (pyproject.toml): it stops a test, the budget only judges one that finished.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

# read once at start: a test that sets ORCH_TEST_BUDGET for a child run never changes this run's budget
_BUDGET = pytest.StashKey[float | None]()
KEEP_S = 1.0  # `merge` keeps tests at least this slow by name; the others count as the file's default_s
MIN_DEFAULT_S = 0.05  # never 0: unknown tests at 0 s would all land in the same part


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
    group.addoption(
        "--part-times", default=None, help="split --part by the measured seconds in this JSON file"
    )
    group.addoption("--times-out", default=None, help="write every test's seconds to this JSON file")


def configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "budget(seconds): this test may take up to that many seconds")
    if config.getoption("--part"):
        parse_part(config.getoption("--part"))  # a wrong value stops the run before collection
    config.stash[_BUDGET] = budget_seconds(config)
    if config.getoption("--times-out"):
        config.pluginmanager.register(TimesOut(config.getoption("--times-out")), "orch-times-out")
    if config.getoption("--part-times"):
        read_times(config.getoption("--part-times"))  # a broken file stops the run before collection


def read_times(path: str | Path) -> tuple[dict[str, float], float]:
    """({node id: seconds}, default seconds) from a --part-times file; refuses a broken one plainly."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        tests = {str(k): float(v) for k, v in data["tests"].items()}
        default = float(data["default_s"])
        if default <= 0 or any(v < 0 for v in tests.values()):
            raise ValueError("default_s must be above 0 and no time below 0")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise pytest.UsageError(f"--part-times {path}: not a time file ({e})") from None
    return tests, default


def parts_by_time(nodeids: list[str], n: int, times: dict[str, float], default: float) -> dict[str, int]:
    """{node id: part 1..n}: slowest first, each to the part with the least time so far."""
    load = [0.0] * n
    out: dict[str, int] = {}
    for nodeid in sorted(set(nodeids), key=lambda x: (-times.get(x, default), x)):
        k = min(range(n), key=lambda i: (load[i], i))
        load[k] += times.get(nodeid, default)
        out[nodeid] = k + 1
    return out


def select_part(config: pytest.Config, items: list[pytest.Item]) -> None:
    text = config.getoption("--part")
    if not text:
        return
    k, n = parse_part(text)
    by_time = None
    if config.getoption("--part-times"):
        by_time = parts_by_time([i.nodeid for i in items], n, *read_times(config.getoption("--part-times")))
    keep, drop = [], []
    for item in items:
        part = by_time[item.nodeid] if by_time is not None else part_of(item.nodeid, n)
        (keep if part == k else drop).append(item)
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


class TimesOut:
    """--times-out: sums each test's report seconds (on the controller, xdist sends it every worker's reports)
    and writes them at the end of the session; an xdist worker writes nothing."""

    def __init__(self, path: str):
        self.path, self.times = Path(path), {}

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.times[report.nodeid] = self.times.get(report.nodeid, 0.0) + float(report.duration or 0.0)

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        if hasattr(session.config, "workerinput"):
            return
        times = {k: round(v, 3) for k, v in sorted(self.times.items())}
        self.path.write_text(json.dumps(times, indent=0, ensure_ascii=True) + "\n", encoding="utf-8")


def merge(out: Path, sources: list[Path]) -> dict:
    """A --part-times file from --times-out files of one system (every part of one or more runs): each test
    its mean seconds; tests under KEEP_S are dropped by name and their median is the default."""
    seen: dict[str, list[float]] = {}
    for src in sources:
        for k, v in json.loads(src.read_text(encoding="utf-8")).items():
            seen.setdefault(str(k), []).append(float(v))
    mean = {k: sum(v) / len(v) for k, v in seen.items()}
    small = sorted(v for v in mean.values() if v < KEEP_S)
    data = {
        "about": "Seconds per test on this system, for --part-times (tests/ci_parts.py, ORCH-1050).",
        "default_s": max(MIN_DEFAULT_S, round(small[len(small) // 2], 2)) if small else 0.5,
        "tests": {k: round(v, 1) for k, v in sorted(mean.items()) if v >= KEEP_S},
    }
    out.write_text(json.dumps(data, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
    return data


def judge(item: pytest.Item, report: pytest.TestReport) -> None:
    if report.when != "call" or not report.passed:
        return
    text = over_budget(item, report.duration)
    if text:
        report.outcome = "failed"
        report.longrepr = text


if __name__ == "__main__":  # python tests/ci_parts.py merge <out.json> <times-out files...>
    if len(sys.argv) < 4 or sys.argv[1] != "merge":
        sys.exit("usage: python tests/ci_parts.py merge <out.json> <times-out files...>")
    d = merge(Path(sys.argv[2]), [Path(x) for x in sys.argv[3:]])
    print(f"{sys.argv[2]}: {len(d['tests'])} tests by name, the rest {d['default_s']} s each")

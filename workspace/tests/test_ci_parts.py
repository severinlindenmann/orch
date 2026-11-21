"""--part K/N and the per-test time budget (ci_parts.py, ORCH-315)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import ci_parts
import pytest


def test_every_test_lands_in_exactly_one_part_and_the_parts_are_even():
    ids = [f"tests/test_x{i % 40}.py::test_{i}" for i in range(4000)]
    for n in (1, 2, 4, 6):
        sizes = [0] * n
        for nodeid in ids:
            p = ci_parts.part_of(nodeid, n)
            assert 1 <= p <= n
            sizes[p - 1] += 1
        assert sum(sizes) == len(ids)
        assert max(sizes) - min(sizes) < len(ids) / n * 0.15, sizes


def test_a_test_keeps_its_part():
    assert ci_parts.part_of("tests/test_a.py::test_b", 4) == ci_parts.part_of("tests/test_a.py::test_b", 4)


@pytest.mark.parametrize("bad", ["", "2", "0/4", "5/4", "a/b", "1/0", "1/2/3"])
def test_a_wrong_part_is_refused(bad):
    with pytest.raises(pytest.UsageError):
        ci_parts.parse_part(bad)


def _run(tmp_path, body: str, *args: str, budget: str | None = None) -> subprocess.CompletedProcess:
    """A tiny suite in its own folder with the same hooks as tests/conftest.py."""
    (tmp_path / "conftest.py").write_text(
        textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(Path(ci_parts.__file__).parent)!r})
            import ci_parts
            import pytest

            def pytest_addoption(parser):
                ci_parts.addoption(parser)

            def pytest_configure(config):
                ci_parts.configure(config)

            def pytest_collection_modifyitems(config, items):
                ci_parts.select_part(config, items)

            @pytest.hookimpl(hookwrapper=True)
            def pytest_runtest_makereport(item, call):
                outcome = yield
                ci_parts.judge(item, outcome.get_result())
            """
        )
    )
    (tmp_path / "test_tiny.py").write_text(textwrap.dedent(body))
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", *args],
        cwd=tmp_path,
        env={k: v for k, v in os.environ.items() if k != "ORCH_TEST_BUDGET"}
        | ({"ORCH_TEST_BUDGET": budget} if budget else {}),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_parts_together_run_every_test_once(tmp_path):
    body = "\n".join(f"def test_{i}():\n    pass\n" for i in range(30))
    total = 0
    for k in (1, 2, 3):
        r = _run(tmp_path, body, "--part", f"{k}/3")
        assert r.returncode == 0, r.stdout + r.stderr
        total += int(r.stdout.split(" passed")[0].split()[-1])
    assert total == 30


def test_a_wrong_part_stops_the_run(tmp_path):
    r = _run(tmp_path, "def test_a():\n    pass\n", "--part", "4/3")
    assert r.returncode != 0
    assert "K must be between 1 and N" in r.stderr


SLOW = """
import time
import pytest

def test_quick():
    pass

def test_slow():
    time.sleep(0.6)

@pytest.mark.budget(5)
def test_slow_with_its_own_budget():
    time.sleep(0.6)
"""


def test_a_test_over_its_budget_fails_and_says_how_to_fix_it(tmp_path):
    r = _run(tmp_path, SLOW, "--budget", "0.3")
    assert r.returncode == 1, r.stdout
    assert "1 failed, 2 passed" in r.stdout
    assert "test_slow took" in r.stdout and "over its time budget of 0.3 s" in r.stdout
    assert "@pytest.mark.budget" in r.stdout


def test_no_budget_means_no_limit(tmp_path):
    r = _run(tmp_path, SLOW)
    assert r.returncode == 0, r.stdout
    assert "3 passed" in r.stdout


def test_the_budget_can_come_from_the_environment(tmp_path):
    r = _run(tmp_path, SLOW, budget="0.3")
    assert "1 failed, 2 passed" in r.stdout


# ---- split by measured time (--part-times, ORCH-1050)


def test_the_time_split_puts_every_test_in_one_part_and_evens_the_time():
    ids = [f"tests/test_x{i % 40}.py::test_{i}" for i in range(2000)]
    times = {ids[i]: 100.0 for i in range(0, 160, 10)} | {ids[i]: 30.0 for i in range(1, 400, 7)}
    for n in (1, 4, 20):
        got = ci_parts.parts_by_time(ids, n, times, 0.5)
        assert set(got) == set(ids) and all(1 <= p <= n for p in got.values())
        load = [0.0] * n
        for nodeid, p in got.items():
            load[p - 1] += times.get(nodeid, 0.5)
        assert max(load) - min(load) <= 100.0, load  # never more apart than the slowest single test


def test_the_time_split_does_not_depend_on_the_collection_order():
    ids = [f"tests/test_x.py::test_{i}" for i in range(300)]
    times = {ids[i]: float(i % 13) for i in range(0, 300, 3)}
    assert ci_parts.parts_by_time(ids, 7, times, 0.5) == ci_parts.parts_by_time(ids[::-1], 7, times, 0.5)


def test_the_slow_tests_no_longer_pile_up_in_one_part():
    """By hash, part 12 of 16 got most of the slow bring-back tests (releases 35 and 38)."""
    ids = [f"tests/test_bring_back.py::test_{i}" for i in range(40)] + [
        f"tests/test_o.py::t{i}" for i in range(800)
    ]
    times = {i: 90.0 for i in ids[:40]}
    got = ci_parts.parts_by_time(ids, 20, times, 0.5)
    per_part = [sum(1 for i in ids[:40] if got[i] == k) for k in range(1, 21)]
    assert per_part == [2] * 20


def _times_file(tmp_path, tests, default=0.5):
    p = tmp_path / "times.json"
    p.write_text(json.dumps({"default_s": default, "tests": tests}))
    return p


def test_the_parts_by_time_together_run_every_test_once_and_write_their_times(tmp_path):
    body = "import time\n" + "\n".join(
        f"def test_{i}():\n    time.sleep({0.2 if i < 3 else 0})\n" for i in range(12)
    )
    times = _times_file(tmp_path, {f"test_tiny.py::test_{i}": 10.0 for i in range(3)})
    total, slow_parts = 0, []
    for k in (1, 2, 3):
        out = tmp_path / f"out{k}.json"
        r = _run(tmp_path, body, "--part", f"{k}/3", "--part-times", str(times), "--times-out", str(out))
        assert r.returncode == 0, r.stdout + r.stderr
        total += int(r.stdout.split(" passed")[0].split()[-1])
        got = json.loads(out.read_text())
        slow_parts.append(sum(1 for i in range(3) if f"test_tiny.py::test_{i}" in got))
        assert all(v >= 0 for v in got.values())
    assert total == 12 and slow_parts == [1, 1, 1]  # one slow test in each part


def test_a_broken_time_file_stops_the_run(tmp_path):
    bad = tmp_path / "times.json"
    bad.write_text("{not json")
    r = _run(tmp_path, "def test_a():\n    pass\n", "--part", "1/2", "--part-times", str(bad))
    assert r.returncode != 0 and "not a time file" in r.stderr


def test_merge_keeps_the_slow_tests_by_name_and_the_rest_as_the_default(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"t::slow": 40.0, "t::quick": 0.2, "t::mid": 0.4}))
    b.write_text(json.dumps({"t::slow": 60.0, "t::other": 0.6}))
    out = tmp_path / "times.json"
    data = ci_parts.merge(out, [a, b])
    assert data["tests"] == {"t::slow": 50.0} and data["default_s"] == 0.4
    assert ci_parts.read_times(out) == ({"t::slow": 50.0}, 0.4)


def test_the_windows_time_file_reads():
    tests, default = ci_parts.read_times(Path(ci_parts.__file__).parent / "ci_times_windows.json")
    assert len(tests) > 100 and 0 < default < 5
    assert max(tests.values()) < 300  # pytest-timeout stops a test at 300 s


def test_merge_never_writes_a_default_of_0(tmp_path):
    a = tmp_path / "a.json"
    a.write_text(json.dumps({f"t::q{i}": 0.0 for i in range(50)} | {"t::slow": 9.0}))
    data = ci_parts.merge(tmp_path / "times.json", [a])
    assert data["default_s"] == ci_parts.MIN_DEFAULT_S


def test_a_time_file_with_a_default_of_0_is_refused(tmp_path):
    with pytest.raises(pytest.UsageError):
        ci_parts.read_times(_times_file(tmp_path, {}, default=0))

"""--part K/N and the per-test time budget (ci_parts.py, ORCH-315)."""

from __future__ import annotations

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

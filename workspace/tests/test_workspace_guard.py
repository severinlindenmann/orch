"""The test session never writes into the workspace it was started from (17 Nov: a helper's test run put
'T', 'Do the thing' and 'Export' into the real ticket list: the helper's ORCH_ROOT reached the tests)."""

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _outer(tmp_path: Path) -> Path:
    ws = tmp_path / "realws"
    (ws / ".orch" / "tickets").mkdir(parents=True)
    return ws


def _inner(outer: Path, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "ORCH_TEST_"))}
    env.update(
        ORCH_ROOT=str(outer), ORCH_RUN="r_helper", ORCH_TICKET="t_helper", ORCH_AGENT="claude", **extra
    )
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(HERE / "workspace_probe.py")],
        env=env, cwd=HERE.parent, capture_output=True, text=True, timeout=120,
    )  # fmt: skip


def test_a_helpers_orch_root_never_reaches_the_tests(tmp_path):
    outer = _outer(tmp_path)
    r = _inner(outer)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2 passed" in r.stdout
    assert list((outer / ".orch" / "tickets").iterdir()) == []  # nothing landed in the helper's workspace


def test_a_test_that_walks_into_the_outer_workspace_fails(tmp_path):
    outer = _outer(tmp_path)
    r = _inner(outer, PROBE_WALK_IN="1", PROBE_OUTER=str(outer))
    assert r.returncode != 0, r.stdout
    assert "the workspace this test run was started from" in r.stdout
    assert list((outer / ".orch" / "tickets").iterdir()) == []


def test_outer_workspaces_are_orch_root_and_the_store_above_the_start_folder(tmp_path, monkeypatch):
    import conftest

    above = tmp_path / "above"
    (above / ".orch").mkdir(parents=True)
    deep = above / "repo" / "workspace"
    deep.mkdir(parents=True)
    env_ws = _outer(tmp_path)
    (tmp_path / "plain").mkdir()
    got = conftest._outer_workspaces({"ORCH_ROOT": str(env_ws)}, deep)
    assert got == [env_ws.resolve(), above.resolve()]
    assert conftest._outer_workspaces({"ORCH_ROOT": str(tmp_path / "plain")}, tmp_path / "plain") == []
    assert conftest._outer_workspaces({}, tmp_path / "plain") == []


def test_the_helper_variables_are_gone_in_every_test():
    for k in ("ORCH_ROOT", "ORCH_RUN", "ORCH_TICKET", "ORCH_AGENT"):
        assert k not in os.environ, k

import sys
from pathlib import Path

import pytest

# The add-on runs inside orch's own Python: core is importable in this standalone test env.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "workspace" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# No test may touch the real ~/.orch-tool: autouse private HOME/ORCH_HOME + a session guard (shared helper).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _orch_test_guard import check_real_home, isolated_orch_home  # noqa: F401


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A fresh workspace with one ticket; returns (root, ticket)."""
    import os

    from orch import addons, cli, winfinish

    home = Path(os.environ["HOME"])  # the guard's private home: ORCH_HOME is under it
    monkeypatch.setattr(addons, "real_home", lambda: home)
    monkeypatch.setattr(winfinish, "needed", lambda: False)
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.chdir(root)
    assert cli.main(["init", "--yes"]) == 0
    from orch import tickets

    t = tickets.list_all(root)
    if not t:
        assert cli.main(["ticket", "new", "Bake the bread"]) == 0
        t = tickets.list_all(root)
    return root, t[0]

"""Settings line "Copies on this computer": the number is the live registry, never a cached older count."""

import json
import time

from orch_dashboard import data


def _register(root, tids, base):
    reg = {}
    for t in tids:
        p = base / t
        p.mkdir(parents=True)
        reg[t] = {"paths": [{"path": str(p), "branch": f"orch/{t}", "base": "a" * 40, "sub": ""}]}
    f = root / ".orch" / "run" / "worktrees.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"schema": "orch.worktrees/1", "tickets": reg}), encoding="utf-8")


def _wait_counted(root):
    for _ in range(100):
        e = data._DISK.get(str(root))
        if e and not e["busy"] and e["val"] is not None:
            return
        time.sleep(0.05)


def test_the_copies_count_is_live_while_the_size_walk_is_cached(ws, tmp_path):
    data.copies_disk_forget(ws)
    _register(ws, ["t_aaaaaa", "t_bbbbbb"], tmp_path / "copies")
    first = data.copies_disk(ws)  # first call: the walk starts, the count is already live
    assert first is None or first["copies"] == 2
    _wait_counted(ws)
    assert data.copies_disk(ws)["copies"] == 2
    _register(
        ws, ["t_aaaaaa", "t_bbbbbb", "t_cccccc"], tmp_path / "copies2"
    )  # a third copy appears within the TTL
    assert data.copies_disk(ws)["copies"] == 3  # not the cached 2
    data.copies_disk_forget(ws)


def test_a_count_that_fails_reads_as_none_not_a_stuck_line(ws, monkeypatch):
    """The settings line must never stay at "..." for good: when the walk fails, the page gets a real empty state."""
    from orch import worktrees

    def boom(*a, **k):
        raise OSError("no")

    data.copies_disk_forget(ws)
    monkeypatch.setattr(worktrees, "usage", boom)
    monkeypatch.setattr(worktrees, "count", boom)
    data.copies_disk(ws)
    _wait_counted(ws)
    got = data.copies_disk(ws)
    assert got is not None and got["copies"] == 0 and got["stuck"] == [] and got["orphaned"] == []
    data.copies_disk_forget(ws)

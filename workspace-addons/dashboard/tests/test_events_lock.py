from orch_dashboard.events import Revisions


def test_signature_is_computed_outside_the_lock(tmp_path):
    seen = []

    class Probe(Revisions):
        def signature(self):
            seen.append(self.condition._is_owned())
            return f"r{len(seen)}"

    rev = Probe(tmp_path)
    assert rev.join()
    try:
        with rev.condition:
            rev.condition.wait_for(lambda: len(seen) >= 3, timeout=5)
    finally:
        rev.leave()
        rev.close()
    assert len(seen) >= 3 and not any(seen)
    assert rev.rev != "r1"  # the watcher published a newer revision


def test_a_slow_scan_waits_longer_a_quick_one_keeps_the_quarter_second():
    """ORCH-609: a big workspace's scan (10-30 ms) no longer runs four times a second."""
    from orch_dashboard.events import WAIT_MAX, WAIT_MIN, next_wait

    assert next_wait(0.001) == WAIT_MIN == 0.25
    assert 0.25 < next_wait(0.01) <= 0.5
    assert next_wait(1.0) == WAIT_MAX


def test_json_rows_reads_like_os_walk(tmp_path):
    import os

    from orch_dashboard.events import json_rows

    (tmp_path / "top").mkdir()
    (tmp_path / "top" / "a.json").write_text("{}")
    (tmp_path / "top" / "b.log").write_text("x")
    (tmp_path / "top" / "deep" / "er").mkdir(parents=True)
    (tmp_path / "top" / "deep" / "er" / "c.json").write_text("{}")
    (tmp_path / "away").mkdir()
    (tmp_path / "away" / "d.json").write_text("{}")
    try:
        os.symlink(tmp_path / "away", tmp_path / "top" / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pass  # no symlinks here (Windows without the right): the rest still counts
    nested, flat = [], []
    json_rows(tmp_path / "top", True, nested)
    json_rows(tmp_path / "top", False, flat)
    json_rows(tmp_path / "missing", True, flat)  # a missing folder adds nothing
    names = lambda rows: sorted(os.path.relpath(r[0], tmp_path / "top") for r in rows)
    assert names(nested) == ["a.json", os.path.join("deep", "er", "c.json")]  # not through the symlink
    assert names(flat) == ["a.json"]


def test_a_folder_that_fails_while_read_is_skipped(tmp_path, monkeypatch):
    """A read error in the middle of a folder must not end the watcher (os.walk skipped such a folder too)."""
    import orch_dashboard.events as mod

    class Broken:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def __iter__(self):
            return self

        def __next__(self):
            raise OSError("folder read failed")

    monkeypatch.setattr(mod.os, "scandir", lambda _p: Broken())
    rows = []
    mod.json_rows(tmp_path, True, rows)
    assert rows == []

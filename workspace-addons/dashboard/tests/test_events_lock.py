from orch_dashboard.events import Revisions


def test_signature_is_computed_outside_the_lock(tmp_path):
    seen = []

    class Probe(Revisions):
        def fingerprint(self):
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


def _files_state(root):
    """What the watcher saw of the files when a page joined (its `seen` mark)."""
    rev = Revisions(root)
    assert rev.join()
    try:
        return rev.seen
    finally:
        rev.leave()
        rev.close()


def test_ticket_index_cache_is_not_a_change(tmp_path):
    """The core's ticket index (.orch/run/ticket-index.json) is rewritten by the reads a build makes: counted as a
    change, every build would start the next one (ORCH-521). A run record or a ticket file still counts."""
    run = tmp_path / ".orch" / "run"
    run.mkdir(parents=True)
    (tmp_path / ".orch" / "tickets").mkdir()
    before = _files_state(tmp_path)
    (run / "ticket-index.json").write_text('{"version": 1, "files": {}}')
    assert _files_state(tmp_path) == before
    (run / "r_abc.json").write_text("{}")
    after_run = _files_state(tmp_path)
    assert after_run != before
    (tmp_path / ".orch" / "tickets" / "t_abcdef.json").write_text("{}")
    assert _files_state(tmp_path) != after_run

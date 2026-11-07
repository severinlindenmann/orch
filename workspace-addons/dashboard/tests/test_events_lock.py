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

"""The revision watcher's look at the files (ORCH-522): what counts as a change, and what a page request costs."""

import json
import os

from orch_dashboard.events import Revisions


def _ws(tmp_path):
    for d in ("tickets", "chat", "inbox", "run/tickets", "run/needs-cache"):
        (tmp_path / ".orch" / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / ".orch" / "tickets" / "t_aaaaaa.json").write_text('{"id": "t_aaaaaa"}')
    return tmp_path


def _touch(path, text):
    path.write_text(text)
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))  # a later time even on a coarse clock


def test_caches_a_build_writes_itself_are_no_change(tmp_path):
    root = _ws(tmp_path)
    rev = Revisions(root)
    before = rev.fingerprint()
    run = root / ".orch" / "run"
    # every build wrote these (a "last seen" time, the ticket index, add-on needs): each write started the next build
    _touch(run / "last-seen.json", json.dumps({"focus": "2026-11-19T01:00:00Z"}))
    _touch(run / "ticket-index.json", "{}")
    _touch(run / "pull-checks.json", "{}")
    _touch(run / "usage-cache.json", "{}")
    _touch(run / "needs-cache" / "focus.json", "[]")
    assert rev.fingerprint() == before


def test_tickets_runs_and_chat_still_count(tmp_path):
    root = _ws(tmp_path)
    rev = Revisions(root)
    seen = {rev.fingerprint()}
    for path, text in (
        (root / ".orch" / "tickets" / "t_aaaaaa.json", '{"id": "t_aaaaaa", "title": "changed"}'),
        (root / ".orch" / "tickets" / "t_bbbbbb.json", '{"id": "t_bbbbbb"}'),
        (root / ".orch" / "run" / "tickets" / "t_aaaaaa.json", "{}"),
        (root / ".orch" / "chat" / "2026-11-19.json", "[]"),
        (root / ".orch" / "inbox" / "m1.json", "{}"),
    ):
        _touch(path, text)
        sig = rev.fingerprint()
        assert sig not in seen, path
        seen.add(sig)


def test_ticket_artifacts_are_no_change(tmp_path):
    root = _ws(tmp_path)
    rev = Revisions(root)
    before = rev.fingerprint()
    art = root / ".orch" / "tickets" / "t_aaaaaa" / "artifacts"
    art.mkdir(parents=True)
    (art / "report.json").write_text("{}")
    assert rev.fingerprint() == before


def test_a_page_request_uses_the_watchers_last_look(tmp_path):
    root = _ws(tmp_path)
    looks = []

    class Counted(Revisions):
        def fingerprint(self):
            looks.append(1)
            return super().fingerprint()

    rev = Counted(root)
    assert rev.current() == rev.fingerprint()  # no watcher: a new look each time
    assert len(looks) == 2
    assert rev.join()
    try:
        with rev.condition:
            rev.condition.wait_for(lambda: rev.seen, timeout=5)
        n = len(looks)
        for _ in range(20):
            assert rev.current() == rev.seen
        assert len(looks) - n <= 2  # only the watcher's own looks, not one per request
    finally:
        rev.leave()
        rev.close()

"""ORCH-149: after an idle hour the tool's prompt cache is gone. A long conversation is then started fresh
from the ticket (re-reading it would cost more); a short or recent one is resumed."""

import os
import time

import pytest

from orch import adapters, runs, tickets

SID = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"


@pytest.fixture
def transcript(proj, tmp_path, monkeypatch):
    f = tmp_path / "conv.jsonl"
    monkeypatch.setattr(adapters, "transcript_path", lambda name, sid, root, environ=None, folder=None: f)
    monkeypatch.setattr(adapters, "transcript_exists", lambda *a, **k: True)

    def make(size, idle_minutes):
        f.write_bytes(b"x" * size)
        t = time.time() - idle_minutes * 60
        os.utime(f, (t, t))
        return f

    return make


def _plan(proj, tid):
    tickets.record_session(proj, tid, "claude", SID, runs.host())
    return runs.plan(proj, tid, agent="claude")


def test_a_long_conversation_idle_over_the_hour_starts_fresh(proj, new_ticket, transcript):
    tid = new_ticket()
    transcript(runs.LONG_CONVERSATION_BYTES + 1, 61)
    p = _plan(proj, tid)
    assert p["resumed"] is False and p["session"] != SID
    assert "cache is gone" in p["fresh_why"] and "cache is gone" in p["note"]


def test_a_long_conversation_used_recently_is_resumed(proj, new_ticket, transcript):
    tid = new_ticket()
    transcript(runs.LONG_CONVERSATION_BYTES + 1, 30)
    p = _plan(proj, tid)
    assert p["resumed"] is True and p["session"] == SID and p["fresh_why"] is None


def test_a_short_conversation_idle_for_hours_is_resumed(proj, new_ticket, transcript):
    tid = new_ticket()
    transcript(1000, 300)
    assert _plan(proj, tid)["resumed"] is True


def test_unknown_size_resumes(proj, monkeypatch):
    monkeypatch.setattr(adapters, "transcript_path", lambda *a, **k: None)
    assert runs._long_and_cold(proj, "claude", SID, proj) is False

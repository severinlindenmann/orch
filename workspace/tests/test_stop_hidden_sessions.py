"""`orch stop` also ends the live sessions of tickets a person can not see (Chat/General, waiting input)."""

import os
import secrets
import shutil

import pytest

from orch import runs, runs_live, tickets

pytestmark = pytest.mark.skipif(
    os.name == "nt" or not shutil.which("tmux"), reason="live sessions need tmux (not on Windows)"
)


def _new(proj, name):
    r = runs_live.tmux(proj, "new-session", "-d", "-s", name, "--", "sleep", "300")
    assert r.returncode == 0, r.stderr


def test_stop_ends_chat_helper_and_pending_sessions_by_exact_name(proj, monkeypatch):
    sock = "orch-test-" + secrets.token_hex(4)  # a private tmux server, killed by that exact name
    monkeypatch.setattr(runs_live, "socket_name", lambda root: sock)
    try:
        general = tickets.ensure_general(proj, "human:t")
        pend = "t_pending01"
        other = "t_someoneelse"
        d = runs.run_dir(proj) / "pending"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{pend}.jsonl").write_text("", encoding="utf-8")
        for name in (general, pend, other):
            _new(proj, name)
        got = runs_live.stop_hidden(proj)
        assert sorted(got) == sorted([general, pend])
        assert not runs_live.session_exists(proj, general)
        assert not runs_live.session_exists(proj, pend)
        assert runs_live.session_exists(proj, other)  # any other session is left alone
        assert runs_live.stop_hidden(proj) == []
    finally:
        runs_live.tmux(proj, "kill-server")

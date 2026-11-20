"""A page server a helper started is watch-only; only a person's start replaces it (r-1119-1255)."""

from orch import adapters, pagesession


def _clean(monkeypatch):
    import os

    for k, v in list(os.environ.items()):
        if adapters.detect_env({k: v}):
            monkeypatch.delenv(k, raising=False)


def test_started_watch_only_follows_the_agent_rule():
    assert pagesession.started_watch_only({"ORCH_AGENT": "claude"}) is True
    assert pagesession.started_watch_only({"PATH": "/usr/bin"}) is False


def test_only_a_persons_start_restarts_a_watch_only_server(monkeypatch):
    _clean(monkeypatch)
    assert pagesession.restart_watch_only({"watch_only": True}) is True
    for rec in (None, {}, {"watch_only": False}, {"watch_only": "yes"}, []):
        assert pagesession.restart_watch_only(rec) is False  # an older record without the flag stays as it is
    monkeypatch.setenv("ORCH_AGENT", "claude")
    assert pagesession.restart_watch_only({"watch_only": True}) is False  # a helper's start stays watch-only


def test_the_words_name_the_cause_and_the_way_out():
    msg = pagesession.WATCH_ONLY_MSG
    assert "watch-only" in msg and "orch start" in msg and "already used" not in msg

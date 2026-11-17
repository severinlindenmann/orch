"""An open page that nobody clicks must not start processes: the cached state is rebuilt when a watched file
changed (or by the slow safety refresh), not on every poll (e2e 15 Nov: 200-380 orch processes a minute)."""

import json
import time
import urllib.request


def _get(base, path="/api/state"):
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return json.loads(r.read())


def _calls(act_orch):
    f = act_orch.parent / "calls.jsonl"
    return len(f.read_text().splitlines()) if f.exists() else 0


def test_polls_without_a_change_start_no_process(act_server, act_orch):
    _get(act_server)  # the first build
    first = _calls(act_orch)
    assert first > 0
    for _ in range(6):
        time.sleep(0.5)
        _get(act_server)
    assert _calls(act_orch) == first


def test_a_cache_older_than_the_old_limit_is_not_rebuilt_without_a_change(act_server, act_orch):
    from orch_dashboard import state_cache

    assert state_cache.SAFETY_AGE >= 30
    _get(act_server)
    first = _calls(act_orch)
    time.sleep(state_cache.MAX_AGE + 0.5)
    _get(act_server)
    time.sleep(0.5)
    assert _calls(act_orch) == first


def test_a_new_chat_or_inbox_file_is_picked_up_at_once(act_server, act_orch, ws):
    _get(act_server)
    first = _calls(act_orch)
    inbox = ws / ".orch" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "m_new0000000000001.json").write_text("{}")
    _get(act_server)  # answers with the copy at once and starts the build in the background
    deadline = time.monotonic() + 5
    while _calls(act_orch) == first and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _calls(act_orch) > first

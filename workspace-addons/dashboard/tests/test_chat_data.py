"""Chat data for the dashboard (former General): state.chat, the History endpoints (read only), the say action."""

import json
import sys
import threading
import urllib.error
import urllib.request

import pytest

from orch_dashboard import actions
from orch_dashboard.data import load_chat, load_chat_day, load_chat_days, load_state
from orch_dashboard.server import make_server

STATUS = {
    "helper": "Pilatus helper",
    "ticket": "t_chat0001",
    "day": "2026-11-08",
    "messages": [{"id": "m_a", "by": "you", "via": "phone", "text": "hi", "refs": []}],
    "activity": {"day": "2026-11-08", "phone_today": 1, "from_workspaces": {"Home": 2}, "running": 3},
    "days": [{"day": "2026-11-07", "count": 4, "last": "bye"}],
}


@pytest.fixture
def orch(tmp_path):
    f = tmp_path / "orch"
    f.write_text(f"""#!{sys.executable}
import json, sys
a = sys.argv[1:]
if a[:2] == ["chat", "status"]: print(json.dumps({json.dumps(STATUS)}))
elif a[:2] == ["chat", "days"]: print(json.dumps({json.dumps(STATUS["days"])}))
elif a[:2] == ["chat", "day"]: print(json.dumps({{"day": a[2], "today": False, "messages": [{{"id": "m_o", "text": "old"}}]}}))
else: sys.exit(2)
""")
    f.chmod(0o755)
    return str(f)


def test_chat_data_is_read_through_the_orch_command(ws, orch):
    assert load_chat(ws, orch)["activity"]["running"] == 3
    assert load_chat_days(ws, orch)[0]["day"] == "2026-11-07"
    assert load_chat_day(ws, orch, "2026-11-07")["messages"][0]["text"] == "old"
    assert load_chat_day(ws, orch, "../../etc") is None
    assert load_chat(ws, None) is None  # no orch command: no chat, no crash


def test_state_carries_chat_with_addons_only(ws, orch):
    assert load_state(ws, orch_bin=orch)["chat"]["helper"] == "Pilatus helper"


def test_history_endpoints_are_read_only(ws, orch):
    srv = make_server(ws, 0, orch_bin=orch)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert json.loads(urllib.request.urlopen(base + "/api/chat/days").read())[0]["count"] == 4
        d = json.loads(urllib.request.urlopen(base + "/api/chat/day/2026-11-07").read())
        assert d["messages"][0]["text"] == "old"
        for bad in ("/api/chat/day/x", "/api/chat/day/2026-11-07/../x", "/api/chat/day/2026-1-7"):
            with pytest.raises(urllib.error.HTTPError):
                urllib.request.urlopen(base + bad)
        req = urllib.request.Request(base + "/api/chat/days", method="POST", data=b"x")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code in (403, 405)
    finally:
        srv.shutdown()
        srv.server_close()


def test_say_action_builds_one_fixed_command():
    argv = actions.build_argv("chat.say", {"text": "Bitte den Bericht"})
    assert argv[:2] == ["chat", "say"] and argv[-2:] == ["--", "Bitte den Bericht"] and "--by" in argv
    with pytest.raises(actions.BadRequest):
        actions.build_argv("chat.say", {"text": "x", "by": "human:other"})
    with pytest.raises(actions.BadRequest):
        actions.build_argv("chat.say", {"text": ""})

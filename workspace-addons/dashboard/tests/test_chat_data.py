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
    "messages": [{"id": "m_a", "by": "you", "via": "phone", "text": "hi", "convo_start": True, "moved_to": {"id": "t_fish", "key": "FS-1", "title": "Fish"}, "refs": [{"kind": "proposal", "title": "Fish", "made": {"id": "t_fish", "key": "FS-1"}}]}],
    "activity": {"day": "2026-11-08", "phone_today": 1, "from_workspaces": {"Home": 2}, "running": 3},
    "days": [{"day": "2026-11-07", "count": 4, "last": "bye"}],
}


@pytest.fixture
def orch(tmp_path):
    f = tmp_path / "orch"
    f.write_text(f"""#!{sys.executable}
import json, sys
a = sys.argv[1:]
if a[:2] == ["chat", "status"]: print(json.dumps({STATUS!r}))
elif a[:2] == ["chat", "days"]: print(json.dumps({json.dumps(STATUS["days"])}))
elif a[:2] == ["chat", "day"]: print(json.dumps({{"day": a[2], "today": False, "messages": [{{"id": "m_o", "text": "old"}}]}}))
else: sys.exit(2)
""")
    f.chmod(0o755)
    return str(f)


def test_chat_data_is_read_through_the_orch_command(ws, orch):
    assert load_chat(ws, orch)["activity"]["running"] == 3
    assert load_chat(ws, orch)["messages"] == STATUS["messages"]
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


def test_chat_say_goes_through_the_act_fence(act_server, act_orch):
    from .test_act import acts, post

    body = {"op": "chat.say", "args": {"text": "from a web page"}}
    port = act_server.rsplit(":", 1)[1]
    for h in (
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": None},
        {"Host": "evil.example:" + port},
        {"Sec-Fetch-Site": "cross-site"},
    ):
        assert post(act_server, body, h)[0] in (400, 403, 421), h
    assert post(act_server, {}, raw="x", headers={"Content-Type": "text/plain"})[0] == 415
    assert [
        c for c in acts(act_orch) if c[:2] != ["chat", "status"]
    ] == []  # nothing reached the orch command
    assert post(act_server, body)[0] == 200  # the page itself (same origin, JSON) can write
    assert [c[:2] for c in acts(act_orch) if c[:2] != ["chat", "status"]] == [["chat", "say"]]


# Workspace DMs keep the same action fence and CLI-only reads.
def test_workspace_dm_action_validation():
    ws = "ws_abcdefghij"
    argv = actions.build_argv("chat.send_ws", {"workspace": ws, "text": "--literal"})
    assert argv[:3] == ["chat", "send", ws]
    assert argv[-2:] == ["--", "--literal"]
    for args in (
        {"workspace": "ph_abcdefghij", "text": "hi"},
        {"workspace": "../x", "text": "hi"},
        {"workspace": ws, "text": "x" * 2001},
        {"workspace": ws, "text": ""},
        {"workspace": ws, "text": "hi", "by": "agent:x"},
    ):
        with pytest.raises(actions.BadRequest):
            actions.build_argv("chat.send_ws", args)


def test_workspace_dm_reads_and_endpoints(ws, orch, monkeypatch):
    from orch_dashboard import data

    contact = {"ws": "ws_abcdefghij", "name": "Home", "can": {"chat": True, "tasks": False, "files": True}}
    calls = []

    def command(binary, argv, root):
        calls.append(argv)
        return [contact] if argv[1] == "contacts" else {**contact, "messages": []}

    monkeypatch.setattr(data, "run_orch", command)
    assert data.load_chat_contacts(ws, orch) == [contact]
    assert data.load_chat_thread(ws, orch, contact["ws"])["messages"] == []
    assert data.load_chat_thread(ws, orch, "../secret") is None
    assert calls == [["chat", "contacts", "--json"], ["chat", "thread", contact["ws"], "--json"]]
    srv = make_server(ws, 0, orch_bin=orch)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert json.loads(urllib.request.urlopen(base + "/api/chat/contacts").read()) == [contact]
        assert (
            json.loads(urllib.request.urlopen(base + "/api/chat/thread/" + contact["ws"]).read())["ws"]
            == contact["ws"]
        )
        for bad in ("ph_abcdefghij", "ws_short", "../secret"):
            with pytest.raises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "/api/chat/thread/" + bad)
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("operation,command", [("chat.send_ws", "send"), ("chat.sync_ws", "sync")])
def test_dm_actions_go_through_the_act_fence(act_server, act_orch, operation, command):
    from .test_act import acts, post

    body = {"op": operation, "args": {"workspace": "ws_abcdefghij"}}
    if command == "send":
        body["args"]["text"] = "from a web page"
    port = act_server.rsplit(":", 1)[1]
    for h in (
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": None},
        {"Host": "evil.example:" + port},
        {"Sec-Fetch-Site": "cross-site"},
    ):
        assert post(act_server, body, h)[0] in (400, 403, 421), h
    assert post(act_server, {}, raw="x", headers={"Content-Type": "text/plain"})[0] == 415
    assert [
        c for c in acts(act_orch) if c[:2] != ["chat", "status"]
    ] == []  # nothing reached the orch command
    assert post(act_server, body)[0] == 200  # the page itself (same origin, JSON) can write
    assert [c[:2] for c in acts(act_orch) if c[:2] != ["chat", "status"]] == [["chat", command]]


def test_dm_client_id_and_optional_sync():
    assert actions.build_argv("chat.sync_ws", {})[:2] == ["chat", "sync"]
    args = {"workspace": "ws_abcdefghij", "text": "hi", "client_id": "m_abcdefghijklmnop"}
    argv = actions.build_argv("chat.send_ws", args)
    assert argv[argv.index("--client-id") + 1] == args["client_id"]
    for bad in ("m_bad", "../x", 123):
        with pytest.raises(actions.BadRequest):
            actions.build_argv("chat.send_ws", {**args, "client_id": bad})

"""Workspace DMs: permissions, durable sends, inbox isolation, and helper default deny."""

import pytest

from orch import chat, cli, net, relay, tickets
from orch.errors import Refused

WS = "ws_abcdefghij"
OTHER = "ws_0123456789"
MID = "m_abcdefghijklmnop"


@pytest.fixture
def dm(tmp_path, monkeypatch):
    directory = {
        "workspaces": [{"id": WS, "name": "Home", "can_send": {"text": True, "files": True}}],
        "phones": [{"id": "ph_abcdefghij", "name": "Phone", "can_send": {"text": True}}],
    }
    monkeypatch.setattr(relay, "_read_dir", lambda root: directory)
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    monkeypatch.setattr(tickets, "current_actor", lambda by=None: by or "human:me")
    return tmp_path, directory


@pytest.mark.parametrize(
    "flags,expected",
    [
        (None, (False, False, False)),
        ([], (False, False, False)),
        ({"text": "yes", "files": 1, "start": []}, (False, False, False)),
        ({"text": True, "files": True, "delegate": True}, (True, True, True)),
        ({"start": True}, (False, True, False)),
    ],
)
def test_permission_mapping(flags, expected):
    assert tuple(chat.can_of(flags).values()) == expected


def test_contacts_only_workspaces_and_malformed(dm, monkeypatch):
    root, directory = dm
    assert chat.contacts(root) == [
        {"ws": WS, "name": "Home", "can": {"chat": True, "tasks": False, "files": True}}
    ]
    for bad in (None, [], {"workspaces": None}, {"workspaces": [None, {"id": WS}], "phones": None}):
        monkeypatch.setattr(relay, "_read_dir", lambda root, value=bad: value)
        assert all(not any(c["can"].values()) for c in chat.contacts(root))


@pytest.mark.parametrize("target", ["ph_abcdefghij", OTHER, "../../secret"])
def test_non_contact_refused(dm, target):
    with pytest.raises(Refused, match="You may not message"):
        chat.dm_send(dm[0], target, "hello")


def test_no_chat_or_agent_refused(dm, monkeypatch):
    root, directory = dm
    directory["workspaces"][0]["can_send"] = {"files": True}
    with pytest.raises(Refused, match="You may not message Home"):
        chat.dm_send(root, WS, "hello")
    directory["workspaces"][0]["can_send"] = {"text": True}
    monkeypatch.setattr(tickets, "agent_tool", lambda: "codex")
    with pytest.raises(Refused, match="Only a person"):
        chat.dm_send(root, WS, "hello", by="human:fake")
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    with pytest.raises(Refused, match="Only a person"):
        chat.dm_send(root, WS, "hello", by="agent:fake")
    assert not (root / ".orch/chat/dm").exists()


@pytest.mark.parametrize("text", ["", "  ", "x" * 2001])
def test_text_limits(dm, text):
    with pytest.raises(Refused):
        chat.dm_send(dm[0], WS, text)


def test_record_before_send_plain_call_and_offline_recheck(dm, monkeypatch):
    root, _ = dm
    outbox = root / ".orch/outbox" / (MID + ".json")

    def send(root_arg, ws, text):
        assert (root_arg, ws, text) == (root, WS, "hello")
        assert chat.dm_thread(root, WS)["messages"][0]["state"] == "sending"
        net.write_json(outbox, {"id": MID}, True)
        return {"id": MID, "sent": False}

    monkeypatch.setattr(relay, "send_text", send)
    entry = chat.dm_send(root, WS, "hello")
    assert entry["state"] == "sending"
    assert chat.dm_thread(root, WS)["messages"][0]["state"] == "sending"
    outbox.unlink()
    assert chat.dm_thread(root, WS)["messages"][0]["state"] == "delivered"
    monkeypatch.setattr(relay, "send_text", lambda *args: {"id": MID})
    assert chat.dm_send(root, WS, "accepted")["state"] == "delivered"


def test_refusal_is_saved_and_cleaned(dm, monkeypatch):
    root, _ = dm
    reason = "No\x1b<!--secret-->" + "x" * 300

    def refuse(*args):
        raise Refused(reason)

    monkeypatch.setattr(relay, "send_text", refuse)
    entry = chat.dm_send(root, WS, "hello")
    assert entry["state"] == "failed"
    assert entry["error"] == relay.clean_untrusted(reason, 200)
    assert chat.dm_thread(root, WS)["messages"] == [entry]


def test_inbox_clean_idempotent_sorted_and_isolated(dm):
    root, _ = dm
    text = "<b>hi</b>\x1b[31m<!--hidden-->" + "x" * 2100
    for i, (peer, body, kind) in enumerate(
        [
            (WS, {"text": text}, "text"),
            (OTHER, {"text": "private"}, "text"),
            (WS, {"text": "group", "group": {"id": "g"}}, "text"),
            (WS, {"text": "update", "update": {"kind": "note"}}, "text"),
            (WS, {"text": "file"}, "file"),
            (WS, {"text": "earlier"}, "text"),
        ]
    ):
        net.write_json(
            root / ".orch/inbox" / f"m_{i}.json",
            {
                "id": f"m_{i}",
                "type": kind,
                "from": peer,
                "body": body,
                "created_at": f"2026-11-09T10:00:0{5 - i}Z",
            },
            True,
        )
    msgs = chat.dm_thread(root, WS)["messages"]
    assert [m["text"] for m in msgs] == ["earlier", relay.clean_untrusted(text, 2000)]
    assert chat.dm_thread(root, WS)["messages"] == msgs
    with pytest.raises(Refused):
        chat.dm_thread(root, "../" + OTHER)


def test_store_cap(dm):
    root, _ = dm
    net.write_json(
        chat._dm_path(root, WS),
        {
            "messages": [
                {"id": str(i), "at": f"2026-01-01T00:{i // 60:02}:{i % 60:02}Z", "text": "x"}
                for i in range(510)
            ]
        },
        True,
    )
    assert len(chat.dm_thread(root, WS)["messages"]) == 500
    assert chat.dm_thread(root, WS)["messages"][0]["id"] == "10"


@pytest.mark.parametrize("sub,args", [("contacts", []), ("thread", [WS]), ("send", [WS, "hello"])])
def test_helper_default_denies_new_commands(dm, monkeypatch, sub, args):
    parsed = cli.build_parser(show_all=True).parse_args(["chat", sub, *args, "--json"])
    monkeypatch.setattr(chat, "is_helper", lambda root: True)
    assert ("chat", sub) not in chat.HELPER_COMMANDS
    with pytest.raises(Refused, match="Chat helper cannot"):
        chat.guard(dm[0], parsed)


def test_cli_dispatch(dm, monkeypatch, capsys):
    from orch import cli_chat

    monkeypatch.setattr(relay, "send_text", lambda *args: {"id": MID})
    for command in (["contacts"], ["send", WS, "hi"], ["thread", WS]):
        args = cli.build_parser(show_all=True).parse_args(["chat", *command, "--json"])
        assert cli_chat.dispatch(args, dm[0])
        assert WS in capsys.readouterr().out or command[0] == "send"


def test_thread_cannot_read_another_workspaces_store(dm):
    root, directory = dm
    directory["workspaces"].append({"id": OTHER, "name": "Other"})
    other = chat._dm_path(root, OTHER)
    net.write_json(other, {"ws": OTHER, "messages": [{"text": "private"}]}, True)
    path = chat._dm_path(root, WS)
    path.symlink_to(other)
    with pytest.raises(Refused, match="must not be a link"):
        chat.dm_thread(root, WS)
    path.unlink()
    net.write_json(path, {"ws": OTHER, "messages": [{"text": "private"}]}, True)
    assert chat.dm_thread(root, WS)["messages"] == []


def test_thread_sorts_actual_instants(dm):
    root, _ = dm
    net.write_json(
        chat._dm_path(root, WS),
        {
            "ws": WS,
            "messages": [
                {"id": "later", "at": "2026-11-09T09:00:00Z", "text": "later"},
                {"id": "earlier", "at": "2026-11-09T10:00:00+02:00", "text": "earlier"},
            ],
        },
        True,
    )
    assert [m["id"] for m in chat.dm_thread(root, WS)["messages"]] == ["earlier", "later"]

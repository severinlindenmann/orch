"""Workspace DMs: permissions, durable sends, inbox isolation, and helper default deny."""

import json
import os

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
        {
            "ws": WS,
            "name": "Home",
            "can": {"chat": True, "tasks": False, "files": True},
            "count": 0,
            "last_at": "",
        }
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
    assert chat.dm_sync(root, WS)["messages"][0]["state"] == "sending"
    relay._record_posted(root, MID)
    assert chat.dm_thread(root, WS)["messages"][0]["state"] == "sending"
    assert chat.dm_sync(root, WS)["messages"][0]["state"] == "delivered"
    monkeypatch.setattr(relay, "send_text", lambda *args: {"id": MID, "sent": True})
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


@pytest.mark.parametrize("all_contacts", [False, True])
def test_inbox_clean_idempotent_sorted_and_isolated(dm, all_contacts):
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
                "id": f"m_{i:016d}",
                "type": kind,
                "from": peer,
                "body": body,
                "created_at": f"2026-11-09T10:00:0{5 - i}Z",
            },
            True,
        )
    assert chat.dm_read(root, WS)["messages"] == []
    if all_contacts:
        chat.dm_sync_all(root)
    msgs = chat.dm_sync(root, WS)["messages"]
    assert [m["text"] for m in msgs] == [relay.clean_untrusted(text, 2000), "earlier"]  # arrival order
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


@pytest.mark.parametrize(
    "sub,args", [("contacts", []), ("thread", [WS]), ("sync", []), ("sync", [WS]), ("send", [WS, "hello"])]
)
def test_helper_default_denies_new_commands(dm, monkeypatch, sub, args):
    parsed = cli.build_parser(show_all=True).parse_args(["chat", sub, *args, "--json"])
    monkeypatch.setattr(chat, "is_helper", lambda root: True)
    assert ("chat", sub) not in chat.HELPER_COMMANDS
    with pytest.raises(Refused, match="Chat helper cannot"):
        chat.guard(dm[0], parsed)


def test_cli_dispatch(dm, monkeypatch, capsys):
    from orch import cli_chat

    monkeypatch.setattr(relay, "send_text", lambda *args: {"id": MID, "sent": True})
    for command in (["contacts"], ["send", WS, "hi"], ["thread", WS], ["sync", WS]):
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


def test_thread_keeps_append_order_not_a_peer_clock(dm):
    root, _ = dm
    net.write_json(
        chat._dm_path(root, WS),
        {
            "ws": WS,
            "messages": [{"id": "a", "at": "2026-11-09T09:00:00Z", "text": "a"}, {"id": "b", "text": "b"}],
        },
        True,
    )
    assert [m["id"] for m in chat.dm_thread(root, WS)["messages"]] == ["a", "b"]


def test_hostile_look(dm):
    from orch import look

    root, directory = dm
    row = directory["workspaces"][0]
    for bad in (
        {"icon": look.ICON_IDS[0], "color": "red;background:url(//x)"},
        {"icon": "x" * 100000, "color": "x" * 100000},
        {"url": "//x"},
    ):
        row["look"] = bad
        assert "look" not in chat.contacts(root)[0]
    row["look"] = {"icon": look.ICON_IDS[0], "color": look.COLOR_IDS[0], "url": "//x", "extra": "x" * 100000}
    assert chat.contacts(root)[0]["look"] == {"icon": look.ICON_IDS[0], "color": look.COLOR_IDS[0]}


@pytest.mark.parametrize("all_contacts", [False, True])
def test_pure_reads_and_inbox_limits(dm, all_contacts):
    root, _ = dm
    inbox = root / ".orch/inbox"
    for i, mid in enumerate([MID, 'x"]', "m_short"]):
        net.write_json(
            inbox / f"m_{i}.json", {"id": mid, "from": WS, "type": "text", "body": {"text": "hi"}}, True
        )
    net.write_json(
        inbox / "m_large.json",
        {"id": "m_0123456789abcdef", "from": WS, "type": "text", "body": {"text": "x" * 65536}},
        True,
    )
    before = {p: p.stat().st_mtime_ns for p in root.rglob("*")}
    assert chat.dm_read(root, WS)["messages"] == []
    chat.contacts(root)
    assert before == {p: p.stat().st_mtime_ns for p in root.rglob("*")}
    if all_contacts:
        chat.dm_sync_all(root)
        assert [m["id"] for m in chat.dm_read(root, WS)["messages"]] == [MID]
    else:
        assert [m["id"] for m in chat.dm_sync(root, WS)["messages"]] == [MID]


def test_inbox_directory_links(dm, tmp_path):
    root, _ = dm
    outside = tmp_path / "outside" / ".orch"
    net.write_json(
        outside / "m_test.json", {"id": MID, "from": WS, "type": "text", "body": {"text": "forged"}}, True
    )
    (root / ".orch").mkdir()
    (root / ".orch/inbox").symlink_to(outside, target_is_directory=True)
    assert chat.dm_sync(root, WS)["messages"] == []
    linked = root / "linked"
    linked.mkdir()
    (linked / ".orch").symlink_to(root / ".orch", target_is_directory=True)
    assert list(chat._dm_inbox(linked)) == []
    chat.dm_sync_all(root)
    assert chat.dm_read(root, WS)["messages"] == []
    with pytest.raises(Refused):
        chat.dm_sync_all(linked)


def test_newest_500_inbox_files(dm):
    import os

    root, _ = dm
    for i in range(505):
        path = root / ".orch/inbox" / f"m_{i:016d}.json"
        net.write_json(path, {"id": path.stem, "from": WS, "type": "text", "body": {"text": str(i)}})
        os.utime(path, (i + 1, i + 1))
    assert {m["body"]["text"] for m in chat._dm_inbox(root)} == {str(i) for i in range(5, 505)}


def test_cli_spoof_and_sync_person_only(dm, monkeypatch):
    from orch import cli_chat

    monkeypatch.setattr(tickets, "agent_tool", lambda: "codex")
    for command in (["send", WS, "hi"], ["sync", WS]):
        args = cli.build_parser(show_all=True).parse_args(["chat", *command, "--by", "human:x"])
        with pytest.raises(Refused, match="Only a person"):
            cli_chat.dispatch(args, dm[0])


def test_retry_replaces_failed_entry(dm, monkeypatch):
    root, _ = dm

    def fail(*args):
        raise Refused("offline")

    monkeypatch.setattr(relay, "send_text", fail)
    failed = chat.dm_send(root, WS, "hello")
    monkeypatch.setattr(relay, "send_text", lambda *args: {"id": MID, "sent": True})
    sent = chat.dm_send(root, WS, "hello", retry=failed["id"])
    assert chat.dm_read(root, WS)["messages"] == [sent]
    with pytest.raises(Refused):
        chat.dm_send(root, WS, "hello", retry=failed["id"])


def test_relay_flush_records_only_successful_posts(dm, monkeypatch):
    root, _ = dm
    monkeypatch.setattr(relay, "apply_allow_answers", lambda root: None)
    path = root / ".orch/outbox" / f"{MID}.json"
    net.write_json(path, {"id": MID}, True)

    def reject(*args):
        error = Refused("permission denied")
        error.status = 403
        raise error

    monkeypatch.setattr(relay, "_post_message", reject)
    relay.resend_outbox(root)
    assert MID not in relay.posted_ids(root)
    net.write_json(path, {"id": MID}, True)
    monkeypatch.setattr(relay, "_post_message", lambda *args: None)
    assert relay.resend_outbox(root)["sent"] == [MID]
    assert MID in relay.posted_ids(root)
    assert not path.exists()


def test_relay_immediate_post_ack(dm, monkeypatch):
    from orch import relay_view

    root, _ = dm
    monkeypatch.setattr(relay, "_cfg", lambda root: {"workspace": OTHER})
    monkeypatch.setattr(relay_view, "record_sent", lambda *args: None)
    monkeypatch.setattr(relay, "_post_message", lambda *args: None)
    msg = relay._message(root, WS, "text", {"text": "hi"})
    assert msg["sent"] is True
    assert msg["id"] in relay.posted_ids(root)

    def offline(*args):
        raise Refused("offline")

    monkeypatch.setattr(relay, "_post_message", offline)
    queued = relay._message(root, WS, "text", {"text": "later"})
    assert queued["sent"] is False
    assert queued["id"] not in relay.posted_ids(root)


def test_record_posted_never_raises_and_ignores_links(tmp_path, monkeypatch):
    from orch import relay

    root = tmp_path / "w"
    (root / ".orch").mkdir(parents=True)
    monkeypatch.setattr(relay.net, "write_json", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    relay._record_posted(root, "m_abcdefghijklmnop")  # must not raise
    real = tmp_path / "elsewhere"
    real.mkdir()
    link = tmp_path / "l"
    (link).mkdir()
    (link / ".orch").symlink_to(real)
    assert relay._posted_path(link) is None
    assert relay.posted_ids(link) == []


def test_contacts_and_thread_are_person_only(dm, monkeypatch):
    from orch import cli_chat

    monkeypatch.setattr(tickets, "agent_tool", lambda: "codex")
    for command in (["contacts"], ["thread", WS]):
        for extra in ([], ["--by", "human:x"]):
            args = cli.build_parser(show_all=True).parse_args(["chat", *command, *extra])
            with pytest.raises(Refused, match="Only a person"):
                cli_chat.dispatch(args, dm[0])
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    args = cli.build_parser(show_all=True).parse_args(["chat", "contacts", "--by", "agent:x", "--json"])
    with pytest.raises(Refused, match="Only a person"):
        cli_chat.dispatch(args, dm[0])
    args = cli.build_parser(show_all=True).parse_args(["chat", "contacts", "--json"])
    assert cli_chat.dispatch(args, dm[0])


def test_client_id_is_idempotent(dm, monkeypatch):
    root, _ = dm
    calls = []
    monkeypatch.setattr(relay, "send_text", lambda *args: calls.append(args) or {"id": MID, "sent": True})
    first = chat.dm_send(root, WS, "hello", client_id=MID)
    assert chat.dm_send(root, WS, "hello", client_id=MID) == first
    with pytest.raises(Refused):
        chat.dm_send(root, WS, "different", client_id=MID)
    assert first["id"] == MID
    assert len(calls) == 1
    assert chat.dm_read(root, WS)["messages"] == [first]
    with pytest.raises(Refused):
        chat.dm_send(root, WS, "hello", client_id="m_bad")


def test_round_trip_sync_all(dm, monkeypatch):
    a, _ = dm
    b = a / "receiver"
    monkeypatch.setattr(
        relay,
        "_read_dir",
        lambda root: {"workspaces": [{"id": WS if root == a else OTHER, "can_send": {"text": True}}]},
    )

    def send(root, ws, text):
        net.write_json(
            b / ".orch/inbox" / f"{MID}.json",
            {
                "id": MID,
                "from": OTHER,
                "type": "text",
                "body": {"text": text},
                "created_at": "2026-11-09T10:00:00Z",
            },
            True,
        )
        return {"id": MID, "sent": False}

    monkeypatch.setattr(relay, "send_text", send)
    chat.dm_send(a, WS, "hello", client_id=MID)
    relay._record_posted(a, MID)
    chat.dm_sync_all(a)
    chat.dm_sync_all(b)
    assert chat.dm_read(a, WS)["messages"][0]["state"] == "delivered"
    received = chat.dm_read(b, OTHER)["messages"]
    assert len(received) == 1 and received[0]["by"] == OTHER and received[0]["text"] == "hello"
    path = chat._dm_path(b, OTHER)
    before = path.stat().st_mtime_ns
    chat.dm_sync_all(b)
    assert path.stat().st_mtime_ns == before
    assert chat.contacts(b)[0]["count"] == 1
    assert chat.contacts(b)[0]["last_at"] == received[0]["at"]
    assert path.stat().st_mtime_ns == before


def test_cli_pure_and_all(dm, capsys, monkeypatch):
    from orch import cli_chat

    root, _ = dm
    net.write_json(
        root / ".orch/inbox" / f"{MID}.json",
        {"id": MID, "from": WS, "type": "text", "body": {"text": "hello"}},
        True,
    )

    def run(*command):
        cli_chat.dispatch(cli.build_parser(show_all=True).parse_args(["chat", *command, "--json"]), root)
        return capsys.readouterr().out

    before = {p: p.stat().st_mtime_ns for p in root.rglob("*")}
    assert '"messages": []' in run("thread", WS)  # read-only by default
    assert before == {p: p.stat().st_mtime_ns for p in root.rglob("*")}
    assert "hello" in run("thread", WS, "--sync")
    run("sync")
    monkeypatch.setattr(tickets, "agent_tool", lambda: "codex")
    with pytest.raises(Refused):
        run("sync", "--by", "human:spoof")


def test_sync_all_scans_once_for_multiple_contacts(dm, monkeypatch):
    root, directory = dm
    directory["workspaces"].append({"id": OTHER})
    scanned = []

    def inbox(root):
        scanned.append(root)
        return iter(
            [
                {"id": f"m_{i:016d}", "from": ws, "type": "text", "body": {"text": ws}}
                for i, ws in enumerate((WS, OTHER))
            ]
        )

    monkeypatch.setattr(chat, "_dm_inbox", inbox)
    chat.dm_sync_all(root)
    assert scanned == [root]
    for ws in (WS, OTHER):
        assert chat.dm_read(root, ws)["messages"][0]["text"] == ws


def test_retry_cli_client_id(dm, monkeypatch, capsys):
    import json

    from orch import cli_chat

    root, _ = dm
    monkeypatch.setattr(relay, "send_text", lambda *a: (_ for _ in ()).throw(Refused("offline")))
    failed = chat.dm_send(root, WS, "keep me", client_id=MID)
    assert failed["state"] == "failed" and failed["error"] == "offline"
    monkeypatch.setattr(relay, "send_text", lambda *a: {"id": MID, "sent": True})
    args = cli.build_parser(show_all=True).parse_args(
        ["chat", "send", WS, "keep me", "--retry", MID, "--client-id", "m_0123456789abcdef", "--json"]
    )
    cli_chat.dispatch(args, root)
    entry = json.loads(capsys.readouterr().out)
    assert entry["state"] == "delivered"
    assert entry["id"] == "m_0123456789abcdef"
    assert chat.dm_read(root, WS)["messages"] == [entry]


def test_idempotent_only_for_my_own_message_and_relay_id_is_separate(dm, monkeypatch):
    root, _ = dm
    cid = "m_abcdefghij012345"
    sent = []
    monkeypatch.setattr(relay, "send_text", lambda *a, **k: sent.append(a) or {"id": MID, "sent": True})
    first = chat.dm_send(root, WS, "hello", client_id=cid)
    assert first["relay_id"] != first["id"] == cid
    assert chat.dm_send(root, WS, "hello", client_id=cid)["id"] == cid and len(sent) == 1
    with pytest.raises(Refused):  # same id, other text
        chat.dm_send(root, WS, "something else", client_id=cid)
    peer = "m_peermessage00001"
    net.write_json(
        root / ".orch/inbox" / f"{peer}.json",
        {"id": peer, "from": WS, "type": "text", "body": {"text": "hi"}},
        True,
    )
    chat.dm_sync(root, WS)
    with pytest.raises(Refused):  # a peer's imported id is never "my message"
        chat.dm_send(root, WS, "hi", client_id=peer)
    assert len(sent) == 1


def test_a_peer_clock_never_orders_or_evicts(dm):
    root, _ = dm
    net.write_json(
        chat._dm_path(root, WS),
        {
            "ws": WS,
            "messages": [
                {
                    "id": "m_own0000000000001",
                    "at": "2026-11-09T10:00:00Z",
                    "by": "you",
                    "text": "mine",
                    "state": "delivered",
                }
            ],
        },
        True,
    )
    for n in range(520):
        mid = f"m_future{n:010d}"
        net.write_json(
            root / ".orch/inbox" / f"{mid}.json",
            {
                "id": mid,
                "from": WS,
                "type": "text",
                "created_at": "2999-01-01T00:00:00Z",
                "body": {"text": f"t{n}"},
            },
            True,
        )
    chat.dm_sync(root, WS)
    msgs = chat.dm_read(root, WS)["messages"]
    assert len(msgs) <= 500
    imported = [m for m in msgs if m["by"] == WS]
    assert imported and all(not m["at"].startswith("2999") for m in imported)
    assert all(m["peer_at"].startswith("2999") for m in imported)
    assert not msgs[-1]["at"].startswith("2999")


def test_thread_and_sync_are_not_helper_commands():
    for pair in (("chat", "thread"), ("chat", "sync"), ("chat", "contacts"), ("chat", "send")):
        assert pair not in chat.HELPER_COMMANDS


def test_600_inbound_texts_keep_the_newest_500_and_a_second_sync_imports_nothing(dm):
    root, _ = dm
    for n in range(600):
        mid = f"m_flood{n:011d}"
        net.write_json(
            root / ".orch/inbox" / f"{mid}.json",
            {"id": mid, "from": WS, "type": "text", "body": {"text": f"t{n}"}},
            True,
        )
        os.utime(root / ".orch/inbox" / f"{mid}.json", (1_700_000_000 + n, 1_700_000_000 + n))
    chat.dm_sync(root, WS)
    first = chat.dm_read(root, WS)["messages"]
    assert len(first) == 500
    assert [m["text"] for m in first][-1] == "t599"  # the newest inbox files, appended in import order
    chat.dm_sync(root, WS)
    chat.dm_sync_all(root)
    again = chat.dm_read(root, WS)["messages"]
    assert [m["id"] for m in again] == [m["id"] for m in first]  # nothing re-imported, nothing resurrected
    stored = json.loads(chat._dm_path(root, WS).read_text())
    assert len(stored["seen"]) >= 500 and set(m["id"] for m in first) <= set(stored["seen"])


def test_corrupt_thread_file_fails_closed_and_other_threads_still_sync(dm, monkeypatch, capsys):
    root, directory = dm
    directory["workspaces"].append({"id": OTHER, "can_send": {"text": True}})
    seen_id = "m_seenbefore0000001"
    net.write_json(
        chat._dm_path(root, WS),
        {"ws": WS, "messages": [], "seen": [seen_id]},
        True,
    )
    net.write_json(
        root / ".orch/inbox" / f"{seen_id}.json",
        {"id": seen_id, "from": WS, "type": "text", "body": {"text": "old"}},
        True,
    )
    net.write_json(
        root / ".orch/inbox" / "m_other0000000000a.json",
        {"id": "m_other0000000000a", "from": OTHER, "type": "text", "body": {"text": "fresh"}},
        True,
    )
    chat._dm_path(root, WS).write_text("{ not json", encoding="utf-8")
    with pytest.raises(Refused):
        chat.dm_read(root, WS)
    chat.dm_sync_all(root)
    assert (
        chat._dm_path(root, WS).read_text(encoding="utf-8") == "{ not json"
    )  # untouched, nothing re-imported
    assert [m["text"] for m in chat.dm_read(root, OTHER)["messages"]] == ["fresh"]
    assert "skipped" in capsys.readouterr().err
    with pytest.raises(Refused):
        chat.dm_send(root, WS, "hi")
    assert [c["ws"] for c in chat.contacts(root)].count(WS) == 1  # the list still works (count 0)


def _pull_with(monkeypatch, root, messages):
    calls = []

    def api(r, method, path, body=None, timeout=60):
        calls.append((method, path))
        return 200, ({"items": messages} if method == "GET" else {})

    monkeypatch.setattr(relay, "_api", api)
    return relay._pull(root, 0)


def test_the_normal_pull_puts_a_workspace_text_into_its_thread_with_the_senders_time(tmp_path, monkeypatch):
    b = tmp_path
    monkeypatch.setattr(
        relay,
        "_read_dir",
        lambda root: {"workspaces": [{"id": OTHER, "name": "Pilatus", "can_send": {"text": True}}]},
    )
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    sent = chat.tickets.now()  # a plausible sender time: now
    msg = {
        "id": MID,
        "from": OTHER,
        "to": WS,
        "type": "text",
        "body": {"text": "[R] hello"},
        "created_at": sent,
        "schema": "orch.msg/1",
    }
    _pull_with(monkeypatch, b, [msg])
    # nobody opened Chat, nobody synced: the read-only thread already has it, once
    thread = chat.dm_read(b, OTHER)["messages"]
    assert [m["text"] for m in thread] == ["[R] hello"] and thread[0]["by"] == OTHER
    assert thread[0]["shown_at"] == sent and thread[0]["peer_at"] == sent
    _pull_with(monkeypatch, b, [])  # the next pull imports nothing again
    assert len(chat.dm_read(b, OTHER)["messages"]) == 1


def test_display_time_is_the_senders_only_when_sane(tmp_path):
    arrival = "2026-11-09T12:00:00Z"
    assert chat._shown_at("2026-11-09T11:59:00Z", arrival, []) == "2026-11-09T11:59:00Z"
    assert chat._shown_at("2026-11-09T12:04:00Z", arrival, []) == "2026-11-09T12:04:00Z"  # within 5 min ahead
    assert chat._shown_at("2026-11-09T12:06:00Z", arrival, []) == arrival  # too far in the future
    assert chat._shown_at("2999-01-01T00:00:00Z", arrival, []) == arrival
    earlier = [{"at": "2026-11-09T11:30:00Z", "shown_at": "2026-11-09T11:58:00Z"}]
    assert chat._shown_at("2026-11-09T11:40:00Z", arrival, earlier) == arrival  # before the previous message
    assert chat._shown_at("nonsense", arrival, []) == arrival
    assert chat._shown_at(None, arrival, []) == arrival


def test_an_agent_session_pull_never_imports(tmp_path, monkeypatch):
    monkeypatch.setattr(
        relay,
        "_read_dir",
        lambda root: {"workspaces": [{"id": OTHER, "name": "P", "can_send": {"text": True}}]},
    )
    monkeypatch.setattr(tickets, "agent_tool", lambda: "codex")
    msg = {
        "id": MID,
        "from": OTHER,
        "to": WS,
        "type": "text",
        "body": {"text": "hi"},
        "created_at": chat.tickets.now(),
    }
    _pull_with(monkeypatch, tmp_path, [msg])
    assert not chat._dm_path(tmp_path, OTHER).exists()
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    second = {**msg, "id": "m_secondmsg0000001", "body": {"text": "again"}}
    _pull_with(
        monkeypatch, tmp_path, [second]
    )  # the workspace's own next pull (with a workspace text) catches up
    monkeypatch.setattr(tickets, "current_actor", lambda by=None: by or "human:me")
    assert sorted(m["text"] for m in chat.dm_read(tmp_path, OTHER)["messages"]) == ["again", "hi"]


def test_import_runs_only_for_saved_workspace_texts_never_blocks_and_logs_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        relay,
        "_read_dir",
        lambda root: {"workspaces": [{"id": OTHER, "name": "P", "can_send": {"text": True}}]},
    )
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    calls = []
    real = chat._dm_sync_contacts
    monkeypatch.setattr(chat, "_dm_sync_contacts", lambda *a, **k: calls.append(k) or real(*a, **k))
    phone = {"id": MID, "from": "ph_abcdefghij", "type": "text", "body": {"text": "x"}}
    group_free_ws_file = {"id": "m_filemessage00001", "from": OTHER, "type": "file", "body": {}}
    chat.dm_import_on_pull(tmp_path, [phone, group_free_ws_file])
    assert calls == []  # no workspace text saved: nothing to do
    ws_text = {"id": "m_wstext000000001a", "from": OTHER, "type": "text", "body": {"text": "hi"}}
    chat.dm_import_on_pull(tmp_path, [ws_text])
    assert calls == [{"wait": 0.3}]
    # a busy chat lock skips the cycle quietly and fast
    import time

    lock = tickets.tickets_dir(tmp_path) / ".lock-chat"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("x")
    started = time.monotonic()
    chat.dm_import_on_pull(tmp_path, [ws_text])
    assert time.monotonic() - started < 3 and capsys.readouterr().err == ""
    lock.unlink()
    # a failure is logged, but only once per 10 minutes
    monkeypatch.setattr(chat, "_contacts_list", lambda root: (_ for _ in ()).throw(RuntimeError("boom")))
    chat._DM_IMPORT_LOGGED[0] = 0.0
    chat.dm_import_on_pull(tmp_path, [ws_text])
    chat.dm_import_on_pull(tmp_path, [ws_text])
    assert capsys.readouterr().err.count("could not import") == 1


def test_display_time_clamps(tmp_path):
    arrival = "2026-11-09T12:00:00Z"
    assert chat._shown_at("2026-11-08T11:00:00Z", arrival, []) == arrival  # more than 24 h before arrival
    assert chat._shown_at("1970-01-01T00:00:00Z", arrival, []) == arrival
    assert chat._shown_at("2026-11-08T13:00:00Z", arrival, []) == "2026-11-08T13:00:00Z"

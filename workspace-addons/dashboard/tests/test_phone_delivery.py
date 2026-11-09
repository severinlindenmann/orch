import json

import pytest

from orch_dashboard.data import load_tickets

AT = "2026-11-08T10:20:30Z"


def question(ws):
    return next(t for t in load_tickets(ws)[0] if t["id"] == "t_7k3f9q")["questions"][0]


def save(ws, name, value):
    p = ws / ".orch" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value))
    return p


def sent(ws, delivered=None, to="phones", ticket="t_7k3f9q"):
    qid = question(ws)["id"]
    save(ws, "secrets/questions-sent.json", {
        "m_test": {"ticket": ticket, "question_id": qid, "to": to},
    })
    p = save(ws, "run/relay/sent.jsonl", {
        "id": "m_test", "type": "question", "to": to,
        "delivered_at": delivered, "preview": "PRIVATE", "token": "SECRET",
    })
    return p


def test_phone_delivery_defaults(ws):
    q = question(ws)
    assert q["sent_to_phone"] is False
    assert q["delivered"] is None


@pytest.mark.parametrize("at", [None, AT, "SECRET", 123, {}, "2026-99-99T10:20:30Z"])
def test_phone_delivery_local_sent_record(ws, at):
    sent(ws, at)
    q = question(ws)
    assert q["sent_to_phone"] is True
    assert q["delivered"] == (AT if at == AT else None)
    assert "PRIVATE" not in json.dumps(q) and "SECRET" not in json.dumps(q)
    assert "m_test" not in json.dumps(q)


@pytest.mark.parametrize("to,ticket", [("ws_other", "t_7k3f9q"), ("phones", "t_other")])
def test_phone_delivery_does_not_match_other_recipient_or_ticket(ws, to, ticket):
    sent(ws, AT, to, ticket)
    assert question(ws)["sent_to_phone"] is False
    assert question(ws)["delivered"] is None


def test_phone_delivery_outbox_message(ws):
    qid = question(ws)["id"]
    save(ws, "outbox/m_queued.json", {
        "schema": "orch.msg/1", "id": "m_queued", "type": "question", "to": "phones",
        "ticket": "t_7k3f9q", "body": {"question_id": qid},
    })
    assert question(ws)["sent_to_phone"] is True
    assert question(ws)["delivered"] is None


@pytest.mark.parametrize("bad", [None, [], "bad", {"m_test": []}])
def test_phone_delivery_bad_mapping(ws, bad):
    sent(ws, AT)
    save(ws, "secrets/questions-sent.json", bad)
    assert question(ws)["sent_to_phone"] is False


def test_phone_delivery_bad_log_and_symlink(ws, tmp_path):
    p = sent(ws, AT)
    p.write_text('{broken\n[]\n')
    assert question(ws)["sent_to_phone"] is False
    target = tmp_path / "private.jsonl"
    target.write_text(json.dumps({"id": "m_test", "to": "phones", "type": "question", "delivered_at": AT}))
    p.unlink()
    p.symlink_to(target)
    assert question(ws)["sent_to_phone"] is False


def test_phone_delivery_no_network_or_command(ws, monkeypatch):
    import socket
    import subprocess

    def forbidden(*args, **kwargs):
        pytest.fail("Reading delivery must use local files only")

    sent(ws, AT)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    assert question(ws)["delivered"] == AT


def test_phone_delivery_http_state(ws, server):
    import urllib.request

    sent(ws, AT)
    with urllib.request.urlopen(server + "/api/state") as response:
        state = json.load(response)
    q = next(t for t in state["tickets"] if t["id"] == "t_7k3f9q")["questions"][0]
    assert q["sent_to_phone"] is True
    assert q["delivered"] == AT

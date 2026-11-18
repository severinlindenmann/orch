"""The workspace side of the notebook (ORCH-649): ask, reply through the normal inbox pull, checks again
here, status."""

import json
import re
import time

import pytest
from fakes import WS

from orch import relay_notebook as rn

NB = "nb_abcdefghij"


def connect(run, srv):
    return run("relay", "connect", srv.url, "--workspace", WS, "--token", srv.token)


@pytest.fixture
def nbrel(proj, run, rel):
    rel.notebook = {
        "id": NB,
        "name": "MacBook",
        "paired": True,
        "last_seen": rn._iso(time.time()),
        "online": True,
        "waiting": 0,
    }
    rel.route(
        "GET", "/v1/notebooks", lambda m, q, b: (200, {"items": [rel.notebook] if rel.notebook else []})
    )
    connect(run, rel)
    return rel


def reply(aid, text=None, ok=True, refused=None, frm=NB, mid="m_reply00000000001"):
    nb = {"kind": "reply", "ok": ok}
    if text is not None:
        nb["text"] = text
    if refused:
        nb["refused"] = refused
    return {
        "schema": "orch.msg/1",
        "id": mid,
        "from": frm,
        "to": WS,
        "type": "notebook",
        "created_at": "2026-11-18T10:00:05Z",
        "reply_to": aid,
        "body": {"notebook": nb},
    }


def test_ask_saves_first_then_sends_a_valid_ask(proj, run, nbrel):
    code, out, err = run("relay", "notebook", "ask", "notes", "find", "--arg", "words=budget", "--wait", "0")
    assert code == 0, err
    assert "Waiting for the notebook" in out
    aid = re.search(r"\[(m_[a-z0-9]{16})\]", out).group(1)
    sent = [m for m in nbrel.sent if m["type"] == "notebook"]
    assert len(sent) == 1 and sent[0]["id"] == aid and sent[0]["to"] == NB
    body = sent[0]["body"]["notebook"]
    assert body["kind"] == "ask" and body["args"] == {"words": "budget"} and "ticket" not in sent[0]
    rec = json.loads((proj / ".orch/local/notebook/asks" / f"{aid}.json").read_text())
    assert rec["state"] == "waiting" and rec["way"] == "notes"


def test_reply_arrives_through_the_inbox_and_lands_on_the_ticket(proj, run, nbrel, new_ticket):
    tid = new_ticket()
    code, out, _ = run(
        "relay", "notebook", "ask", "notebook", "ping", "--ticket", tid, "--wait", "0", "--json"
    )
    aid = json.loads(out)["id"]
    nbrel.inbox.append(reply(aid, "Notebook here"))
    code, out, _ = run("relay", "notebook", "show", aid, "--wait", "5")
    assert code == 0
    assert "Notebook here" in out and rn.DATA_NOTE in out
    hist = json.loads((proj / f".orch/tickets/{tid}.json").read_text())["history"]
    assert any("Answer from your notebook" in h.get("text", "") for h in hist)


def test_reply_checked_again_secrets_and_strangers(proj, run, nbrel):
    _, out, _ = run("relay", "notebook", "ask", "notes", "find", "--wait", "0", "--json")
    aid = json.loads(out)["id"]
    nbrel.inbox.append(reply(aid, "password = hunter2-very-secret-Value-123", mid="m_reply00000000002"))
    rec = rn.wait(proj, aid, 5)
    assert (
        rec["state"] == "answered"
        and rec["reply"]["ok"] is False
        and rec["reply"]["refused"] == rn.SECRET_REFUSED
    )
    assert "hunter2" not in json.dumps(rec)
    # an answer from another notebook, or for no request, is dropped
    _, out, _ = run("relay", "notebook", "ask", "notes", "find", "--wait", "0", "--json")
    aid2 = json.loads(out)["id"]
    nbrel.inbox.append(reply(aid2, "x", frm="nb_otherother", mid="m_reply00000000003"))
    nbrel.inbox.append(reply("m_nothing000000000", "x", mid="m_reply00000000004"))
    rn.wait(proj, aid2, 2)
    assert rn.get(proj, aid2)["state"] == "waiting"


def test_refused_reply_and_expiry(proj, run, nbrel):
    _, out, _ = run("relay", "notebook", "ask", "mail", "send", "--wait", "0", "--json")
    aid = json.loads(out)["id"]
    nbrel.inbox.append(
        reply(aid, ok=False, refused="The notebook has no way in called mail.", mid="m_reply00000000005")
    )
    code, out, _ = run("relay", "notebook", "show", aid, "--wait", "5")
    assert "Refused: The notebook has no way in called mail." in out
    _, out, _ = run("relay", "notebook", "ask", "notes", "find", "--wait", "0", "--json")
    aid = json.loads(out)["id"]
    p = proj / ".orch/local/notebook/asks" / f"{aid}.json"
    rec = json.loads(p.read_text())
    rec["expires_at"] = rn._iso(time.time() - 1)
    p.write_text(json.dumps(rec))
    _, out, _ = run("relay", "notebook", "show", aid)
    assert "Expired" in out


def test_ask_refuses_bad_names_and_no_notebook(proj, run, nbrel):
    code, _, err = run("relay", "notebook", "ask", "../x", "find")
    assert code == 2 and "short names" in err
    code, _, err = run("relay", "notebook", "ask", "notes", "find", "--arg", "nope")
    assert code == 2 and "NAME=TEXT" in err
    nbrel.notebook = None
    (proj / ".orch/local/notebook/info.json").unlink(missing_ok=True)
    code, _, err = run("relay", "notebook", "ask", "notes", "find")
    assert code == 2 and "relay admin page" in err


def test_status_connected_asleep_and_stopped(proj, run, nbrel):
    nbrel.inbox.append(
        {
            "schema": "orch.msg/1",
            "id": "m_status0000000001",
            "from": NB,
            "to": WS,
            "type": "notebook",
            "created_at": "2026-11-18T10:01:00Z",
            "body": {
                "notebook": {
                    "kind": "status",
                    "ways": [
                        {"way": "notebook", "name": "Notebook", "ok": True},
                        {"way": "teams", "name": "Teams", "ok": False, "problem": "The sign-in page showed."},
                    ],
                }
            },
        }
    )
    run("relay", "inbox")
    st = rn.status(proj)
    assert st["state"] == "connected" and [w["name"] for w in st["stopped"]] == ["Teams"]
    code, out, _ = run("relay", "notebook", "status")
    assert "MacBook is connected." in out and "Teams: the way in stopped working" in out
    # no call from the notebook for more than 2 minutes = asleep, with what waits
    nbrel.notebook = {
        **nbrel.notebook,
        "last_seen": rn._iso(time.time() - 600),
        "online": False,
        "waiting": 2,
    }
    st = rn.status(proj, now=time.time())
    assert st["state"] == "connected"  # the cached answer is still fresh
    rn.info(proj, fresh=True)
    st = rn.status(proj)
    assert st["state"] == "asleep" and st["waiting"] == 2
    code, out, _ = run("relay", "notebook", "status")
    assert "is asleep" in out and "2 requests wait" in out
    nbrel.notebook = {**nbrel.notebook, "paired": False}
    rn.info(proj, fresh=True)
    assert rn.status(proj)["state"] == "waiting_first"
    nbrel.notebook = None
    rn.info(proj, fresh=True)
    assert rn.status(proj)["state"] == "none"


def test_status_message_is_cleaned(proj, run, nbrel):
    nbrel.inbox.append(
        {
            "schema": "orch.msg/1",
            "id": "m_status0000000002",
            "from": NB,
            "to": WS,
            "type": "notebook",
            "created_at": "2026-11-18T10:01:00Z",
            "body": {
                "notebook": {
                    "kind": "status",
                    "ways": [
                        {"way": "../bad", "name": "Bad", "ok": False},
                        {"way": "mail", "name": "Mail‮", "ok": False, "problem": "x" * 900},
                    ],
                }
            },
        }
    )
    run("relay", "inbox")
    st = rn.status(proj)
    assert [w["way"] for w in st["ways"]] == ["mail"]
    assert "‮" not in st["ways"][0]["name"] and len(st["ways"][0]["problem"]) <= 300

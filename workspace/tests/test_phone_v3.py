# ruff: noqa: E501
"""Phone app v3, workspace side: acks and working updates, the hidden General conversation, `relay topic`,
attachments / voice / location / feedback in, the speak hint, artifact ids, question previews and scope
(contracts/relay-api.md "Phone app v3", message.schema.json, vectors/phone-v3-v1.json)."""

import json
from pathlib import Path

import jsonschema
import pytest
from fakes import WS

from orch import phone_view, runs

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
PHONE = "ph_iphone0001"
M1 = "m_phone00000000a01"[:18]
GEN = "m_g3n3ral0000000a1"


def _drop_unicode_props(node):
    """Python's re has no \\p{..}: the update.title character rule is checked by the relay, not here."""
    if isinstance(node, dict):
        skip = ("pattern", "not") if "\\p{" in str(node.get("pattern", "")) else ()
        return {k: _drop_unicode_props(v) for k, v in node.items() if k not in skip}
    if isinstance(node, list):
        return [_drop_unicode_props(v) for v in node]
    return node


def _schema():
    raw = json.loads((CONTRACTS / "message.schema.json").read_text())
    return jsonschema.Draft202012Validator(
        _drop_unicode_props(raw), format_checker=jsonschema.FormatChecker()
    )


def msg(mid, body, **kw):
    return {
        "schema": "orch.msg/1",
        "id": mid,
        "from": PHONE,
        "to": WS,
        "type": "text",
        "created_at": "2026-11-06T10:00:00Z",
        "body": body,
        **kw,
    }


@pytest.fixture
def conn(proj, run, rel):
    rel.snapshot["workspaces"]["phones"] = [
        {"id": PHONE, "name": "Marco's iPhone", "online": True, "last_seen": None}
    ]
    assert run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)[0] == 0
    return rel


def tickets_listed(run):
    return json.loads(run("ticket", "list", "--json")[1])


def acks(rel):
    return [m for m in rel.sent if m["body"].get("update", {}).get("kind") == "ack"]


def check_sent_valid(rel):
    v = _schema()
    for m in rel.sent:
        errs = [f"{list(e.path)}: {e.message}" for e in v.iter_errors(m)]
        assert not errs, (m, errs)


def test_general_text_goes_to_a_hidden_ticket_and_is_acked_in_general(proj, run, conn):
    conn.inbox.append(msg(GEN, {"text": "Kannst du die Zahlen pruefen?", "general": True}))
    out = run("relay", "inbox")[1]
    assert "General" in out
    assert tickets_listed(run) == [], "General is never listed"
    from orch import tickets

    gid = tickets.general_id(proj)
    g = tickets.load(proj, gid)
    assert g["general"] is True and "key" not in g
    assert any("Kannst du die Zahlen" in h["text"] for h in g["history"])
    assert len(runs.undelivered(proj, gid)) == 1
    (a,) = acks(conn)
    assert a["body"]["general"] is True and "ticket" not in a and a["reply_to"] == GEN
    check_sent_valid(conn)
    # the same text again: one ticket, one ack
    conn.acked.clear()
    run("relay", "inbox")
    assert len(acks(conn)) == 1 and tickets.general_id(proj) == gid


def test_agent_reply_from_general_has_no_ticket_and_only_ack_working(proj, run, conn):
    from orch import tickets

    conn.inbox.append(msg(GEN, {"text": "hi", "general": True}))
    run("relay", "inbox")
    gid = tickets.general_id(proj)
    code, out, _ = run("relay", "send", PHONE, "Hallo!", "--ticket", gid, "--json")
    assert code == 0
    sent = conn.sent[-1]
    assert sent["body"]["general"] is True and "ticket" not in sent and "key" not in sent
    assert run("relay", "send", PHONE, "x", "--ticket", gid, "--update", "result")[0] == 2
    check_sent_valid(conn)


def test_new_topic_is_acked_with_ticket_and_key(proj, run, conn):
    conn.inbox.append(msg(M1, {"text": "Offerte ablegen"}))
    run("relay", "inbox")
    (t,) = tickets_listed(run)
    (a,) = acks(conn)
    assert a["ticket"] == t["id"] and a["key"] == t["key"] and a["reply_to"] == M1
    check_sent_valid(conn)


def test_working_update_once_when_the_agent_has_the_text(proj, run, new_ticket, conn):
    tid = new_ticket("Weekly report")
    conn.inbox.append(msg(M1, {"text": "More please"}, ticket=tid))
    run("relay", "inbox")
    assert not [m for m in conn.sent if m["body"].get("update", {}).get("kind") == "working"]
    (item,) = runs.undelivered(proj, tid)
    runs.mark_delivered(proj, tid, [item["id"]])
    run("relay", "inbox")
    run("relay", "inbox")
    w = [m for m in conn.sent if m["body"].get("update", {}).get("kind") == "working"]
    assert len(w) == 1 and w[0]["reply_to"] == M1 and w[0]["ticket"] == tid
    check_sent_valid(conn)


def test_working_for_general_has_no_ticket(proj, run, conn):
    from orch import tickets

    conn.inbox.append(msg(GEN, {"text": "hi", "general": True}))
    run("relay", "inbox")
    gid = tickets.general_id(proj)
    runs.mark_delivered(proj, gid, [runs.undelivered(proj, gid)[0]["id"]])
    run("relay", "inbox")
    w = [m for m in conn.sent if m["body"].get("update", {}).get("kind") == "working"]
    assert len(w) == 1 and w[0]["body"]["general"] is True and "ticket" not in w[0]
    check_sent_valid(conn)


def test_working_for_a_new_topic_once_its_run_exists(proj, run, conn):
    conn.inbox.append(msg(M1, {"text": "Offerte"}))
    run("relay", "inbox")
    (t,) = tickets_listed(run)
    assert not [m for m in conn.sent if m["body"].get("update", {}).get("kind") == "working"]
    runs.claim(proj, t["id"], "agent:claude", "claude")
    run("relay", "inbox")
    w = [m for m in conn.sent if m["body"].get("update", {}).get("kind") == "working"]
    assert len(w) == 1 and w[0]["reply_to"] == M1 and w[0]["ticket"] == t["id"]


def test_topic_from_a_general_message(proj, run, conn):
    from orch import tickets

    conn.inbox.append(msg(GEN, {"text": "Bitte Rechnung CSV exportieren", "general": True}))
    run("relay", "inbox")
    code, out, err = run("relay", "topic", "--from", GEN, "CSV export", "--json")
    assert code == 0, err
    r = json.loads(out)
    (t,) = tickets_listed(run)
    assert t["id"] == r["ticket"] and t["title"] == "CSV export"
    assert any("Bitte Rechnung CSV exportieren" in h["text"] for h in t["history"])
    topic_ack = acks(conn)[-1]
    assert topic_ack["ticket"] == t["id"] and topic_ack["key"] == t["key"] and topic_ack["reply_to"] == GEN
    assert "title" in topic_ack["body"]["update"]
    assert run("relay", "topic", "--from", GEN, "Again")[0] == 2, "one message starts one ticket"
    assert tickets.general_id(proj) not in [x["id"] for x in tickets_listed(run)]
    check_sent_valid(conn)


def test_topic_refuses_what_is_not_a_phone_text(proj, run, conn):
    conn.inbox.append({**msg("m_ws000000000000a1", {"text": "hello"}), "from": "ws_reports001"})
    run("relay", "inbox")
    assert run("relay", "topic", "--from", "m_ws000000000000a1", "T")[0] == 2


def test_attachments_voice_location_in_a_ticket(proj, run, new_ticket, conn):
    tid = new_ticket("Receipts")
    conn.blobs["b_ph0ne1mage000001"] = b"\xff\xd8jpeg"
    conn.blobs["b_ph0nef1le0000002"] = b"%PDF"
    body = {
        "text": "Beleg",
        "attachments": [
            {
                "blob_id": "b_ph0ne1mage000001",
                "kind": "image",
                "name": "../../.evil.jpg",
                "size": 6,
                "mime": "image/jpeg",
            },
            {
                "blob_id": "b_ph0nef1le0000002",
                "kind": "file",
                "name": "Offerte.pdf",
                "size": 4,
                "mime": "application/pdf",
            },
        ],
        "voice": {
            "blob_id": "b_ph0ne1mage000001",
            "transcript": "Das ist ein Test",
            "lang": "de-CH",
            "lang_source": "setting",
        },
        "location": {"lat": 47.05, "lon": 8.31, "label": "Luzern"},
    }
    conn.inbox.append(msg(M1, body, ticket=tid))
    run("relay", "inbox")
    t = json.loads(run("ticket", "show", tid, "--json")[1])
    text = next(h["text"] for h in t["history"] if h["text"].startswith("From Marco"))
    folder = proj / ".orch" / "tickets" / tid / "files"
    assert sorted(p.name for p in folder.iterdir()) == ["Offerte.pdf", "evil.jpg"], "no dots, no path"
    assert f".orch/tickets/{tid}/files/Offerte.pdf" in text and "Beleg" in text
    assert 'Voice message (de-CH): "Das ist ein Test"' in text
    assert (
        "Location: 47.05000, 8.31000 (Luzern)" in text
        and "https://maps.apple.com/?ll=47.05%2C8.31&q=Luzern" in text
    )
    assert (folder / "Offerte.pdf").read_bytes() == b"%PDF"
    assert not list((proj / ".orch" / "tickets").glob("*evil*")) and not (proj / ".evil.jpg").exists()


def test_attachment_that_cannot_be_fetched_is_said_so(proj, run, new_ticket, conn):
    tid = new_ticket("X")
    body = {
        "attachments": [
            {
                "blob_id": "b_missing0000000001",
                "kind": "file",
                "name": "a.pdf",
                "size": 3,
                "mime": "application/pdf",
            }
        ]
    }
    conn.inbox.append(msg(M1, body, ticket=tid))
    run("relay", "inbox")
    t = json.loads(run("ticket", "show", tid, "--json")[1])
    assert any("could not be downloaded" in h["text"] for h in t["history"])


def put_evidence(proj, tid, evs):
    from orch import tickets

    def op(t):
        t["checklist"] = [{"id": "c1", "text": "Do", "done": True, "evidence": evs}]

    tickets.apply_op(proj, tid, op)


def test_feedback_approve_and_pins(proj, run, new_ticket, conn):
    tid = new_ticket("Landing page")
    url = "https://pages.example.ch/f/f_0123456789abcdef"
    put_evidence(proj, tid, [{"type": "url", "ref": url, "title": "Landing page", "role": "result"}])
    aid = phone_view.artifact_id("url", url)
    ok = {"artifact_id": aid, "artifact_rev": "f_0123456789abcdef", "verdict": "approve", "pins": []}
    conn.inbox.append(msg(M1, {"feedback": ok}, ticket=tid))
    changes = {
        "artifact_id": aid,
        "artifact_rev": "f_0123456789abcdef",
        "verdict": "changes",
        "pins": [
            {
                "n": 1,
                "anchor": {"type": "html", "quote": "Jetzt buchen", "offset": 120, "viewport_w": 390},
                "text": "Button zu klein",
            },
            {
                "n": 2,
                "anchor": {"type": "image", "x": 0.4, "y": 0.5},
                "voice_blob_id": "b_ph0ne1mage000001",
                "transcript": "Farbe aendern",
            },
        ],
    }
    conn.inbox.append(msg("m_phone00000000a02", {"feedback": changes}, ticket=tid))
    run("relay", "inbox")
    lines = [h["text"] for h in json.loads(run("ticket", "show", tid, "--json")[1])["history"]]
    joined = "\n".join(lines)
    assert "Feedback on Landing page (f_0123456789): \U0001f44d Looks good" in joined
    assert '1. "Jetzt buchen": Button zu klein' in joined
    assert "2. the picture at 40% across, 50% down: Farbe aendern" in joined


def test_artifact_ids_match_the_vector():
    vec = json.loads((CONTRACTS / "vectors" / "phone-v3-v1.json").read_text())["artifact_ids"]
    for a in vec:
        assert phone_view.artifact_id(a["source"], a["ref"]) == a["id"]


def test_attachments_have_stable_ids_and_html_pr_commit_kinds(proj, run, new_ticket):
    from orch import tickets

    tid = new_ticket("Ship it")
    page = "https://pages.example.ch/f/f_0123456789abcdef"
    pr = "https://github.com/acme/pilatus/pull/42"
    commit = "https://github.com/acme/pilatus/commit/9fceb02d0ae598e95dc970b74767f19372d61af8"
    put_evidence(
        proj,
        tid,
        [
            {"type": "url", "ref": page, "role": "result"},
            {"type": "pr", "ref": pr, "role": "result"},
            {"type": "commit", "ref": commit, "role": "check"},
        ],
    )
    atts = phone_view.attachments(proj, tickets.load(proj, tid), None, upload=False)
    by_url = {a["url"]: a for a in atts}
    assert by_url[page]["kind"] == "html" and by_url[page]["rev"] == "f_0123456789abcdef"
    assert (by_url[pr]["kind"], by_url[pr]["id"]) == ("pr", "a_9b27f17f5357")
    assert (
        by_url[commit]["kind"] == "commit"
        and by_url[commit]["rev"] == "9fceb02d0ae598e95dc970b74767f19372d61af8"
    )
    assert by_url[page]["id"] == phone_view.artifact_id("url", page)


def test_speak_hint_and_language(proj, run, new_ticket, conn):
    tid = new_ticket("Report")
    code, out, err = run(
        "relay",
        "send",
        PHONE,
        "Die Zahlen sind nicht gut und wir haben ein Problem.",
        "--ticket",
        tid,
        "--speak",
        "--summary",
        "Kurz: Problem.",
    )
    assert code == 0, err
    assert conn.sent[-1]["body"]["speak"] == {"lang": "de", "summary": "Kurz: Problem."}
    run(
        "relay",
        "send",
        PHONE,
        "The numbers are fine and this is the report for you.",
        "--ticket",
        tid,
        "--speak",
    )
    assert conn.sent[-1]["body"]["speak"] == {"lang": "en"}
    # the last voice message of the ticket decides (Swiss German -> de)
    conn.inbox.append(
        msg(
            M1,
            {
                "voice": {
                    "blob_id": "b_ph0ne1mage000001",
                    "transcript": "ok",
                    "lang": "de-CH",
                    "lang_source": "setting",
                }
            },
            ticket=tid,
        )
    )
    run("relay", "inbox")
    run("relay", "send", PHONE, "Everything is fine.", "--ticket", tid, "--speak")
    assert conn.sent[-1]["body"]["speak"]["lang"] == "de"
    assert run("relay", "send", PHONE, "x", "--summary", "y")[0] == 2, "--summary needs --speak"
    check_sent_valid(conn)


def test_question_previews_and_scope(proj, run, new_ticket, conn):
    tid = new_ticket("Mail")
    aid = "a_9b27f17f5357"
    code, out, err = run(
        "ask",
        tid,
        "Send it?",
        "--option",
        "A",
        "--option",
        "B",
        "--phone",
        "--preview",
        f"A={aid}",
        "--by",
        "human:t",
    )
    assert code == 0, err
    q = next(m for m in conn.sent if m["type"] == "question")
    assert q["body"]["previews"] == {"A": aid}
    run(
        "ask",
        tid,
        "Allow?",
        "--option",
        "Once",
        "--option",
        "Always",
        "--option",
        "No",
        "--phone",
        "--scope",
        "sending to anna@pilatus.ch",
        "--by",
        "human:t",
    )
    q2 = [m for m in conn.sent if m["type"] == "question"][-1]
    assert q2["body"]["scope"] == "sending to anna@pilatus.ch"
    assert (
        run(
            "ask",
            tid,
            "Third?",
            "--option",
            "A",
            "--phone",
            "--preview",
            "Z=a_9b27f17f5357",
            "--by",
            "human:t",
        )[0]
        == 2
    )
    assert run("ask", tid, "Fourth?", "--option", "A", "--phone", "--scope", "x", "--by", "human:t")[0] == 2
    assert run("ask", tid, "Fifth?", "--option", "A", "--scope", "x", "--by", "human:t")[0] == 2
    check_sent_valid(conn)


def test_general_ticket_is_not_in_needs_or_dashboard_lists(proj, run, conn):
    from orch import tickets

    conn.inbox.append(msg(GEN, {"text": "hi", "general": True}))
    run("relay", "inbox")
    gid = tickets.general_id(proj)
    assert gid not in [t["id"] for t in tickets.list_all(proj)]
    assert gid in [t["id"] for t in tickets.list_all(proj, include_general=True)]
    assert "General" not in run("ticket", "list")[1]

"""Ask another workspace at a stop (#816 A): the act, its refusals, the secret scan, what the page derives."""

import json
from pathlib import Path

import pytest
from test_flow import autopilot_order, core, edit, started, stop_file, waiting_stop

from orch_factory import ask, pageapi
from orch_factory.store import Refused, Store

WS = "ws_design0001"
PNG = b"\x89PNG\r\n\x1a\nfake"


def reach(ws, *entries):
    entries = entries or (
        {
            "id": WS,
            "name": "Design",
            "description": "Pictures and layout",
            "can_send": {"text": True},
            "accepts_from": {"text": True},
        },
    )
    folder = ws / ".agents" / "skills" / "orch-relay"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "workspaces.json").write_text(json.dumps({"workspaces": list(entries)}))


def stop_with_pictures(ws, run, secret=False):
    """A started order at its build stop with two items; item 0 has before and after pictures."""
    order, _ = started(ws, run)
    run("next", order)
    tid = run("crew", "add", order, "booking-form")["ticket"]
    edit(ws, tid, lambda t: t.update(status="done"))
    items = [
        {"title": "Sign layout", "tag": "taste", "before": "before.png", "after": "after.png"},
        {"title": "Poster", "tag": "taste", "before": "poster.png"},
    ]
    q = run("stop", order, "--file", "-", data=stop_file("build", *items))["question"]
    folder = Store(ws).path(f"stops/{order}")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "before.png").write_bytes(PNG)
    (folder / "after.png").write_bytes(PNG + (b"SECRET" if secret else b""))
    (folder / "poster.png").write_bytes(PNG)
    return order, q


def calls(ws):
    return [json.loads(x)["args"] for x in (ws / "calls.jsonl").read_text().splitlines()]


def asks(ws, order):
    return [
        t for t in core(ws, "ticket", "list", "--all") if t["ext"].get("factory", {}).get("role") == "ask"
    ]


def target(order, n=1, items="0", w=WS):
    return f"{order}:s{n}:{w}:{items}"


def test_ask_sends_only_the_ticked_item(ws, run):
    reach(ws)
    order, _ = stop_with_pictures(ws, run)
    out = run("act", "ask", target(order), "--by", "human:anna")
    assert out["state"] == "delivered" and out["items"] == 1 and out["pictures"] == 2
    [sub] = asks(ws, order)
    assert sub["parent"] == order and sub["title"] == "Your view: Online booking page · Build"
    assert sub["ext"]["factory"] == {"role": "ask", "order": order, "stop": 1, "ws": WS}
    assert sub["summary"] == "Online booking page · Build: what would you change before this ships?"
    assert [c["text"] for c in sub["checklist"]] == ["Sign layout"]  # item 1 was not ticked
    [question] = sub["questions"]
    assert question["kind"] is None and question["text"] == ask.QUESTION  # an information question
    sent = [c for c in calls(ws) if c[:3] == ["relay", "group", "share"]]
    assert [c[3] for c in sent] == [sub["id"]] * 2 and all("--click" in c for c in sent)
    assert {c[4].rsplit("/", 1)[1] for c in sent} == {"before.png", "after.png"}  # poster.png stays here
    assert not any("poster" in " ".join(c) for c in calls(ws) if c[:2] != ["ticket", "show"])
    assert any(c[:3] == ["relay", "group", "ask"] for c in calls(ws))
    parent = core(ws, "ticket", "show", order)
    assert any(h["text"] == "Asked Design for a view on Build" for h in parent["history"])
    rows = Store(ws).journal_read()
    row = rows[-1]
    assert row["type"] == "asked" and "q" not in row and "file" not in row and row["order"] == order


def test_ask_by_a_person_only(ws, run):
    reach(ws)
    order, _ = stop_with_pictures(ws, run)
    for who in ("agent:helper", None):
        extra = ["--by", who] if who else []
        assert run("act", "ask", target(order), *extra, code=2)["code"] == "refused"
    assert asks(ws, order) == []


def test_refusals(ws, run):
    reach(ws)
    order, _ = stop_with_pictures(ws, run)
    bad = lambda t, code="not_allowed": run("act", "ask", t, "--by", "human:anna", code=2)["code"] == code
    assert bad(target(order, n=2))  # that stop is not open
    assert bad(target(order, w="ws_other00001"))  # not reachable for groups
    assert bad(target(order, items="5"), "invalid")
    assert bad("nonsense", "invalid")
    run("act", "ask", target(order), "--by", "human:anna")
    assert bad(target(order, items="1"), "conflict")  # an open ask of this stop to the same workspace
    assert len(asks(ws, order)) == 1


def test_not_reachable_when_the_relay_is_off_or_one_way(ws, run):
    order, _ = stop_with_pictures(ws, run)  # no workspace list at all
    assert ask.reach(ws) == []
    reach(ws, {"id": WS, "name": "Design", "can_send": {"text": True}, "accepts_from": {"text": False}})
    assert ask.reach(ws) == []
    assert run("act", "ask", target(order), "--by", "human:anna", code=2)["code"] == "not_allowed"


def test_a_secret_in_a_picture_sends_nothing(ws, run):
    reach(ws)
    order, _ = stop_with_pictures(ws, run, secret=True)
    out = run("act", "ask", target(order), "--by", "human:anna", code=2)
    assert "after.png" in out["error"] and "password" in out["error"] and "nothing was sent" in out["error"]
    assert asks(ws, order) == []  # not even the small ticket
    assert not any(c[:2] == ["relay", "group"] or c[:1] == ["relay"] for c in calls(ws))
    # without that item's pictures, the same ask goes (item 1 has a clean picture)
    assert run("act", "ask", target(order, items="1"), "--by", "human:anna")["pictures"] == 1


def test_no_pictures_flag(ws, run):
    reach(ws)
    order, _ = stop_with_pictures(ws, run)
    out = run("ask", order, "1", WS, "--item", "0", "--no-pictures", "--by", "human:anna")
    assert out["pictures"] == 0
    assert not any(c[:3] == ["relay", "group", "share"] for c in calls(ws))


def test_a_failed_send_is_a_failed_ask_not_a_stuck_one(ws, run):
    reach(ws)
    order, _ = stop_with_pictures(ws, run)
    (ws / "fail-group").write_text("x")
    run("act", "ask", target(order), "--by", "human:anna", code=2)
    view = pageapi.order(ws, order)["stops"][0]
    assert [a["state"] for a in view["asks"]] == ["failed"] and view["autopilot_waits"] is False
    (ws / "fail-group").unlink()
    run("act", "ask", target(order), "--by", "human:anna")  # Send again: the failed one does not block it
    states = [a["state"] for a in pageapi.order(ws, order)["stops"][0]["asks"]]
    assert sorted(states) == ["delivered", "failed"]


def test_offline_workspace_is_queued_then_delivered(ws, run):
    reach(ws)
    order, _ = stop_with_pictures(ws, run)
    (ws / "kept-ask").write_text("x")
    assert run("act", "ask", target(order), "--by", "human:anna")["state"] == "queued"
    (ws / "outbox.json").write_text(json.dumps([{"id": "m_1", "to": WS, "type": "question"}]))
    assert pageapi.order(ws, order)["stops"][0]["asks"][0]["state"] == "queued"
    (ws / "outbox.json").write_text("[]")  # the relay took it
    assert pageapi.order(ws, order)["stops"][0]["asks"][0]["state"] == "delivered"


def test_replies_are_cleaned_untrusted_text_and_never_the_stop_answer(ws, run):
    reach(ws)
    order, stop_q = stop_with_pictures(ws, run)
    run("act", "ask", target(order), "--by", "human:anna")
    [sub] = asks(ws, order)
    core(
        ws,
        "answer",
        sub["id"],
        "q1",
        "Keep the date visible\n\u202eline 2\nline 3\nline 4",
        "--by",
        "agent:Design",
    )
    row = pageapi.order(ws, order)["stops"][0]["asks"][0]
    assert row["state"] == "answered" and row["ws_name"] == "Design"
    [reply] = row["replies"]
    assert reply["by"] == "helper" and reply["more"] is True
    assert reply["text"].splitlines() == ["Keep the date visible", "line 2", "line 3"]
    # their answer, even on the stop question id, never decides the stop
    core(ws, "answer", order, stop_q, "Send back", "--by", "agent:Design")
    state = pageapi.order(ws, order)
    assert state["stops"][0]["state"] == "ignored" and state["stops"][0]["answer"] is None
    # a group text of theirs is a reply of its own ("person"), never "helper"
    edit(
        ws,
        sub["id"],
        lambda t: t["history"].append(
            {
                "at": "2026-11-15T10:00:00Z",
                "by": "agent:Design",
                "text": "Group: Maybe bigger",
                "chat_message": True,
            }
        ),
    )
    replies = pageapi.order(ws, order)["stops"][0]["asks"][0]["replies"]
    assert [(r["by"], r["text"]) for r in replies] == [("helper", reply["text"]), ("person", "Maybe bigger")]


def test_answering_the_stop_closes_its_ask(ws, run):
    reach(ws)
    order, q = stop_with_pictures(ws, run)
    run("act", "ask", target(order), "--by", "human:anna")
    [sub] = asks(ws, order)
    assert core(ws, "ticket", "show", sub["id"])["status"] == "open"
    core(ws, "answer", order, q, "Continue", "--by", "human:anna")
    run("next", order)
    assert core(ws, "ticket", "show", sub["id"])["status"] == "dropped"
    assert pageapi.order(ws, order)["stops"][0]["asks"][0]["state"] == "closed"


def test_autopilot_never_decides_a_stop_you_asked_about(ws, run):
    reach(ws)
    autopilot_order(ws, run)
    order, q = waiting_stop(ws, run, {"title": "Wording", "tag": "routine"})
    run("act", "ask", target(order, items="0"), "--by", "human:anna")
    out = run("decide", order, q, "--answer", "Continue", "--why", "Fine", code=2)
    assert out["code"] == "not_allowed" and "you decide it" in out["error"]
    view = pageapi.order(ws, order)["stops"][0]
    assert view["autopilot_waits"] is True


def test_ask_sub_tickets_are_not_unknown_sub_tickets_and_rows_without_q_are_skipped(ws, run):
    reach(ws)
    order, _ = stop_with_pictures(ws, run)
    run("act", "ask", target(order), "--by", "human:anna")
    result = run("reconcile")["orders"][0]
    assert not any("is not a crew ticket" in p for p in result["problems"]) and result["problems"] == []
    assert run("next", order)["step"] == "wait"  # entries() reads the journal with the ask row in it


def test_reach_and_scan_pages(ws, run):
    reach(
        ws,
        {
            "id": WS,
            "name": "Design",
            "description": "x" * 300,
            "can_send": {"text": True},
            "accepts_from": {"text": True},
        },
    )
    order, _ = stop_with_pictures(ws, run, secret=True)
    [row] = pageapi.reach(ws)
    assert row["ws"] == WS and row["name"] == "Design" and len(row["description"]) <= 120
    scanned = pageapi.scan(ws, order, 1)
    first, second = scanned["items"]
    assert first["title"] == "Sign layout"
    assert {f["name"]: f["ok"] for f in first["files"]} == {"before.png": True, "after.png": False}
    assert "password" in next(f["why"] for f in first["files"] if not f["ok"])
    assert second["files"] == [{"name": "poster.png", "ok": True}]
    assert pageapi.scan(ws, order, 7) is None and pageapi.scan(ws, "nonsense", 1) is None
    assert asks(ws, order) == [] and not any(c[:1] == ["relay"] for c in calls(ws))  # read only


def test_target_shape():
    assert ask.parse_target("t_abc123:s2:ws_abc123:0,2") == ("t_abc123", 2, "ws_abc123", [0, 2])
    assert ask.parse_target("t_abc123:s2:ws_abc123:-")[3] == []
    for bad in ("t_abc123:s0:ws_abc123:0", "t_abc123:s1:ws_abc123:", "t_abc123:s1:ws_abc123:0;1", "x"):
        with pytest.raises(Refused) as error:
            ask.parse_target(bad)
        assert error.value.code == "invalid"


def test_manifest_has_the_ask_act():
    text = (Path(ask.__file__).parent / "orch-addon.toml").read_text()
    assert "[acts.ask]" in text and 'who = "people"' in text


def test_a_failure_after_the_card_went_out_says_what_went_out(ws, run):
    reach(ws)
    order, _ = stop_with_pictures(ws, run)
    (ws / "fail-share-after").write_text("1")  # the card and one picture go, the second picture is refused
    out = run("act", "ask", target(order), "--by", "human:anna")
    assert out["state"] == "partial" and "nothing" not in out["said"].lower()
    assert "the card" in out["said"] and "1 of 2 pictures" in out["said"]
    row = pageapi.order(ws, order)["stops"][0]["asks"][0]
    assert row["state"] == "partial" and "1 of 2 pictures" in row["note"]
    (ws / "fail-share-after").unlink()
    assert (
        run("act", "ask", target(order), "--by", "human:anna")["state"] == "delivered"
    )  # Send again is allowed


def test_offline_relay_queues_the_pictures_and_the_question_for_later(ws, run):
    reach(ws)
    order, _ = stop_with_pictures(ws, run)
    (ws / "offline-share").write_text("x")
    out = run("act", "ask", target(order), "--by", "human:anna")
    assert out["state"] == "queued"
    [sub] = asks(ws, order)
    assert sub["status"] == "open" and any(c[:3] == ["relay", "group", "add"] for c in calls(ws))
    assert not any(
        c[:3] == ["relay", "group", "ask"] for c in calls(ws)
    )  # the question waits for the pictures
    assert pageapi.order(ws, order)["stops"][0]["asks"][0]["state"] == "queued"
    run("watch", "--once")  # still offline: nothing changes, nothing is sent twice
    assert sum(1 for c in calls(ws) if c[:3] == ["relay", "group", "add"]) == 1
    (ws / "offline-share").unlink()
    run("watch", "--once")  # the relay is back: the watcher's pass finishes the ask
    assert sum(1 for c in calls(ws) if c[:3] == ["relay", "group", "share"] and c[3] == sub["id"]) >= 2
    assert sum(1 for c in calls(ws) if c[:3] == ["relay", "group", "ask"]) == 1
    assert sum(1 for c in calls(ws) if c[:3] == ["relay", "group", "add"]) == 1  # the card is not sent again
    assert pageapi.order(ws, order)["stops"][0]["asks"][0]["state"] == "delivered"
    run("watch", "--once")
    assert sum(1 for c in calls(ws) if c[:3] == ["relay", "group", "ask"]) == 1


def test_the_preview_is_what_is_sent(ws, run):
    reach(ws)
    order, _ = stop_with_pictures(ws, run)
    shown = pageapi.scan(ws, order, 1)
    run("act", "ask", target(order, items="0,1"), "--by", "human:anna")
    [sub] = asks(ws, order)
    assert (
        shown["title"] == sub["title"]
        and shown["line"] == sub["summary"]
        and shown["question"] == sub["questions"][0]["text"]
    )
    assert [i["check"] for i in shown["items"]] == [c["text"] for c in sub["checklist"]]


def test_the_scan_gets_bytes(ws, run, monkeypatch):
    reach(ws)
    order, _ = stop_with_pictures(ws, run)
    seen = []
    real = ask.orchcli.call
    monkeypatch.setattr(ask.orchcli, "call", lambda *a, **k: (seen.append((a, k)), real(*a, **k))[1])
    assert pageapi.scan(ws, order, 1)
    scans = [k for a, k in seen if a[1:3] == ("secret", "scan")]
    assert scans and all(isinstance(k["data"], bytes) for k in scans)
    import subprocess

    captured = {}
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: (captured.update(k), subprocess.CompletedProcess(a, 0, b"{}", b""))[1],
    )
    ask.orchcli.call(ws, "secret", "scan", data=b"\x89PNG")
    assert captured["input"] == b"\x89PNG" and captured["text"] is False

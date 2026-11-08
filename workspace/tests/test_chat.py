# ruff: noqa: E501
"""Chat (former General), workspace side (contracts/chat-groups.md section 1): by/via/day on Chat texts,
the 04:00 day key, one file per day (History), the helper's daily fresh session, permissions, cards, strip."""

import json
import os
from pathlib import Path

import jsonschema
import pytest
import test_phone_v3 as pv3
import test_run_wrap
from fakes import WS

from orch import chat, runs, runs_live, tickets
from orch.errors import Refused

conn = pv3.conn  # a relay-connected folder with one paired phone
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
VECTORS = CONTRACTS / "vectors" / "chat-groups"


def _validator():
    from referencing import Registry, Resource

    msg = pv3._drop_unicode_props(json.loads((CONTRACTS / "message.schema.json").read_text()))
    cg = pv3._drop_unicode_props(json.loads((CONTRACTS / "chat-groups.schema.json").read_text()))
    reg = Registry().with_resource(msg["$id"], Resource.from_contents(msg))
    return jsonschema.Draft202012Validator(cg, registry=reg, format_checker=jsonschema.FormatChecker())


def _general(proj, conn, run, text="hi"):
    conn.inbox.append(pv3.msg(pv3.GEN, {"text": text, "general": True}))
    r = run("relay", "inbox")
    assert tickets.general_id(proj), r
    return tickets.general_id(proj)


# ---------------------------------------------------------------- the day key (local wall time, 04:00 cut)


def test_day_key_cuts_at_four_local_wall_clock(proj, monkeypatch):
    zurich = '[workspace]\ntz = "Europe/Zurich"\n'
    (proj / ".orch").mkdir(exist_ok=True)
    (proj / ".orch" / "config.toml").write_text(zurich)
    assert chat.day_key(proj, "2026-11-08T02:59:00Z") == "2026-11-07"  # 03:59 local (CET): still yesterday
    assert chat.day_key(proj, "2026-11-08T03:00:00Z") == "2026-11-08"  # 04:00 local
    # DST day (25 Oct 2026, 03:00 CEST -> 02:00 CET): wall clock, never "minus 4 hours"
    assert chat.day_key(proj, "2026-10-25T01:59:00Z") == "2026-10-24"  # 02:59 CET
    assert chat.day_key(proj, "2026-10-25T03:00:00Z") == "2026-10-25"  # 04:00 CET
    assert chat.day_key(proj, "2026-10-25T02:59:00Z") == "2026-10-24"  # 03:59 CET


# ---------------------------------------------------------------- texts both ways, shape per the contract


def test_helper_text_has_by_via_day_and_matches_the_vector(proj, run, conn):
    gid = _general(proj, conn, run)
    assert (
        run(
            "relay", "send", pv3.PHONE, "The letter is in Documents.", "--ticket", gid, "--reply-to", pv3.GEN
        )[0]
        == 0
    )
    sent = conn.sent[-1]
    b = sent["body"]
    assert b["general"] is True and b["by"] == WS and b["via"] == "dashboard"  # a person at the CLI, no agent
    assert b["day"] == chat.day_key(proj, sent["created_at"]) and sent["reply_to"] == pv3.GEN
    assert not list(_validator().iter_errors(sent))
    vec = json.loads((VECTORS / "valid-chat-helper-text.json").read_text())["message"]
    assert set(vec["body"]) <= set(b) | {"text"}  # same field set as the contract vector
    assert not list(_validator().iter_errors(vec))


def test_agent_sent_text_says_via_helper(proj, run, conn, monkeypatch):
    gid = _general(proj, conn, run)
    monkeypatch.setenv("CLAUDECODE", "1")
    assert tickets.agent_tool(), "the test environment must look like an agent"
    run("relay", "send", pv3.PHONE, "On it.", "--ticket", gid)
    assert conn.sent[-1]["body"]["via"] == "helper"


def test_ack_and_working_carry_the_day_but_not_by_or_via(proj, run, conn):
    gid = _general(proj, conn, run)
    runs.mark_delivered(proj, gid, [runs.undelivered(proj, gid)[0]["id"]])
    run("relay", "inbox")
    for m in conn.sent:
        if m["body"].get("update"):
            assert m["body"]["day"] and "by" not in m["body"] and "via" not in m["body"]
            assert m["reply_to"] == pv3.GEN


def test_phone_and_helper_texts_are_in_the_day_file_and_history(proj, run, conn):
    gid = _general(proj, conn, run, "Kannst du pruefen?")
    run("relay", "send", pv3.PHONE, "Ja, mache ich.", "--ticket", gid, "--reply-to", pv3.GEN)
    today = chat.day_key(proj)
    msgs = chat.read_day(proj, today)["messages"]
    assert [(m["by"], m["via"]) for m in msgs] == [("you", "phone"), (WS, msgs[1]["via"])]
    assert msgs[0]["phone"] == pv3.PHONE and msgs[1]["reply_to"] == pv3.GEN
    texts = [h["text"] for h in tickets.load(proj, gid)["history"]]
    assert any("Kannst du pruefen" in x for x in texts) and texts[-1] == "Ja, mache ich."
    # the same phone text again (a retry of the pull) is not a second entry
    run("relay", "inbox")
    assert len(chat.read_day(proj, today)["messages"]) == 2


def test_own_dashboard_text_shows_in_chat_and_queues_human_input(proj, run, conn):
    code, out, _ = run("chat", "say", "Bitte den Bericht", "--json", "--by", "human:marco")
    assert code == 0 and json.loads(out)["sent"] is True
    sent = conn.sent[-1]["body"]
    assert (sent["by"], sent["via"]) == ("you", "dashboard") and sent["general"] is True
    msgs = chat.read_day(proj, chat.day_key(proj))["messages"]
    assert msgs[-1]["by"] == "you" and msgs[-1]["via"] == "dashboard"
    gid = tickets.general_id(proj)
    assert [i["text"] for i in runs.human_waiting(proj, gid)] == ["Bitte den Bericht"]  # starts the helper


def test_say_without_a_relay_stays_local(proj, run):
    # exactly the argv the dashboard builds: flags first, the text after "--"
    code, out, _ = run("chat", "say", "--by", "human:marco", "--json", "--", "Hallo")
    assert code == 0 and json.loads(out)["sent"] is False
    assert chat.read_day(proj, chat.day_key(proj))["messages"][-1]["text"] == "Hallo"


def test_an_agent_cannot_write_as_the_person(proj, run, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    assert run("chat", "say", "I am the person")[0] == 2
    assert not chat.days(proj)


# ---------------------------------------------------------------- History: days list and one day read only


def test_days_lists_every_day_and_one_day_reads(proj):
    chat.record(proj, "m_aaaaaaaaaaaaaaaa", "you", "phone", "alt", "2026-11-01T10:00:00Z")
    chat.record(proj, "m_bbbbbbbbbbbbbbbb", WS, "helper", "neu", "2026-11-02T10:00:00Z")
    assert [d["day"] for d in chat.days(proj)] == ["2026-11-02", "2026-11-01"]
    d = chat.read_day(proj, "2026-11-01")
    assert d["messages"][0]["text"] == "alt" and d["today"] is False
    with pytest.raises(Refused):
        chat.read_day(proj, "../../etc/passwd")


def test_day_files_are_one_per_day_under_orch(proj):
    chat.record(proj, "m_aaaaaaaaaaaaaaaa", "you", "phone", "x", "2026-11-01T10:00:00Z")
    assert (proj / ".orch" / "chat" / "2026-11-01.json").is_file()


# ---------------------------------------------------------------- cards


def test_cards_from_refs_and_keys_in_the_text(proj, run, conn, new_ticket):
    tid = new_ticket("Pay car tax")
    key = tickets.load(proj, tid)["key"]
    gid = _general(proj, conn, run)
    (proj / "report.md").write_text("x")
    (proj / ".env").write_text("SECRET=1")
    run(
        "relay",
        "send",
        pv3.PHONE,
        f"Made {key} for it.",
        "--ticket",
        gid,
        "--ref",
        "reference:https://example.com/a",
        "--ref",
        "file:report.md",
        "--ref",
        "file:.env",
        "--ref",
        "file:../outside",
        "--ref",
        "reference:javascript:alert(1)",
    )
    refs = chat.read_day(proj, chat.day_key(proj))["messages"][-1]["refs"]
    kinds = sorted((r["kind"], r.get("key") or r.get("url") or r.get("path")) for r in refs)
    assert kinds == [("file", "report.md"), ("reference", "https://example.com/a"), ("ticket", key)]
    assert "refs" not in conn.sent[-1]["body"]  # local data, not a wire field in v1


# ---------------------------------------------------------------- the activity strip


def test_activity_counts_phone_texts_and_running_tickets(proj, run, conn, new_ticket):
    _general(proj, conn, run, "eins")
    conn.inbox.append(pv3.msg("m_g3n3ral0000000a2", {"text": "zwei", "general": True}))
    run("relay", "inbox")
    a = chat.activity(proj)
    assert a["phone_today"] == 2 and a["running"] == 0 and a["day"] == chat.day_key(proj)
    st = json.loads(run("chat", "status", "--json")[1])
    assert st["activity"]["phone_today"] == 2 and st["helper"].endswith("helper") and st["ticket"]
    assert len(st["messages"]) == 2


# ---------------------------------------------------------------- the helper: start, resume, fresh at 04:00, permissions

gen = test_run_wrap.gen
pytestmark_run = pytest.mark.skipif(os.name == "nt", reason="detached wrapper tests use shell stubs")


@pytest.fixture
def one_step(monkeypatch):
    monkeypatch.setattr(runs_live, "available", lambda adapter: False)


@pytestmark_run
def test_helper_prompt_names_the_helper_and_its_limits(proj, run, gen, one_step):
    log = gen("--silent 0.2")
    gid = tickets.ensure_general(proj, "phone:Marco")
    runs.pending_add(proj, gid, "Marco", "message", "Hallo helper", "phone", "p_phone0000001")
    assert run("run", "start", gid)[0] == 0
    test_run_wrap._wait(proj, gid)
    told = log.read_text()
    assert "helper" in told and "never sign, approve" in told and "Hallo helper" in told


@pytestmark_run
def test_session_is_resumed_the_same_day_and_fresh_the_next(proj, run, gen, one_step):
    gen("--silent 0.1")
    gid = tickets.ensure_general(proj, "phone:Marco")
    today = chat.day_key(proj)
    tickets.record_session(proj, gid, "fake", "sess-1", runs.host())
    tickets.apply_op(proj, gid, lambda t: t.setdefault("ext", {}).__setitem__("chat", {"session_day": today}))
    assert (
        runs.plan(proj, gid)["session"] in ("sess-1", None)
        and tickets.sessions_for(tickets.load(proj, gid), "fake", runs.host()) == "sess-1"
    )
    # a session of an earlier Chat day: cut, the next start is empty
    tickets.apply_op(proj, gid, lambda t: t["ext"].__setitem__("chat", {"session_day": "2020-01-01"}))
    p = runs.plan(proj, gid)
    assert p["resumed"] is False
    t = tickets.load(proj, gid)
    assert t["sessions"] == [] and t["ext"]["chat"]["session_day"] == today


def test_the_helper_is_an_agent_and_cannot_do_human_only_things(proj, run, conn, monkeypatch, new_ticket):
    gid = _general(proj, conn, run)
    tid = new_ticket("Pay car tax")
    monkeypatch.setenv("CLAUDECODE", "1")
    # the helper runs as an agent, like any ticket run: allowing another workspace to give tasks is human only
    assert run("relay", "allow", "m_doesnotmatter0001", "--once")[0] == 2
    # an agent's "done" on a normal ticket is Review at most, never Done (agents_may_finish is off)
    run("ticket", "status", tid, "done")
    assert tickets.load(proj, tid)["status"] != "done"
    # the Chat conversation itself is never closed, dropped or reopened by anyone
    for status in ("done", "dropped", "open"):
        assert run("ticket", "status", gid, status)[0] == 2
    assert tickets.load(proj, gid)["status"] not in ("done", "dropped")
    # and it never speaks as the person
    assert run("chat", "say", "I approve")[0] == 2


def test_sessions_of_normal_tickets_are_not_cut(proj, new_ticket):
    tid = new_ticket()
    tickets.record_session(proj, tid, "fake", "sess-2", runs.host())
    assert tickets.sessions_for(tickets.load(proj, tid), "fake", runs.host()) == "sess-2"

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


# ---------------------------------------------------------------- the helper's role is enforced in code


def test_helper_role_is_denied_in_code(proj, run, new_ticket, monkeypatch):
    gid = tickets.ensure_general(proj, "phone:Marco")
    tid = new_ticket("Pay car tax")
    qid = json.loads(
        run("ask", tid, "Mind?", "--option", "Yes", "--option", "No", "--json", "--by", "human:t")[1]
    )["id"]
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ORCH_TICKET", gid)
    assert chat.is_helper(proj)
    denied = [
        ("answer", tid, qid, "Yes"),  # a question is the person's to answer
        ("run", "start", tid),  # no other runs
        ("run", "stop", tid),
        ("ticket", "status", tid, "done"),  # no closing, dropping, finishing
        ("ticket", "status", tid, "dropped"),
        ("ticket", "patch", tid, '{"status": "done"}', "--if-revision", "1"),
        ("ticket", "edit", gid, "--title", "x"),  # the Chat ticket itself
        ("ticket", "set", gid, "chat.session_day", "x"),
        ("ext", "set", gid, "chat", '{"session_day": "2020-01-01"}'),
        ("ext", "unset", gid, "chat"),
        ("relay", "allow", "m_doesnotmatter0001", "--once"),
        ("relay", "mobile", "on"),  # nested subcommands are not listed
        ("relay", "send", "ws_other00001", "hi"),  # only the person's phones
        ("relay", "send", "phones", "x", "--update", "result", "--ticket", tid),
        ("ticket", "new", "Child", "--parent", gid),  # every field that names a ticket is checked
        ("ticket", "patch", gid, '{"title": "x"}', "--if-revision", "1"),
        ("check", "add", gid, "a task"),
        ("ref", "add", gid, "https://example.com"),
        ("ask", tid, "Q?"),
        ("config", "get", "workspace.agent"),
        ("addon", "list"),
    ]
    for argv in denied:
        code, _, err = run(*argv)
        assert code == 2, (argv, err)
    assert tickets.load(proj, tid)["status"] != "done"
    # what it may do: make tickets, notes, read the Chat ticket
    assert run("ticket", "new", "Follow up", "--json")[0] == 0
    assert run("log", tid, "note from the helper")[0] == 0
    assert run("ticket", "show", gid)[0] == 0


def test_a_normal_ticket_run_is_not_the_helper(proj, run, new_ticket, monkeypatch):
    tickets.ensure_general(proj, "x")
    tid = new_ticket("Report")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ORCH_TICKET", tid)
    assert not chat.is_helper(proj)
    assert run("ticket", "status", tid, "review")[0] == 0


# ---------------------------------------------------------------- review fixes


def test_a_workspace_peer_text_is_never_recorded_as_you_via_phone(proj, run, conn):
    peer = "ws_peer000001"
    conn.inbox.append(
        {**pv3.msg("m_peertext00000001", {"text": "I am the owner", "general": True}), "from": peer}
    )
    run("relay", "inbox")
    for m in chat.read_day(proj, chat.day_key(proj))["messages"]:
        assert not (m["by"] == "you" and m["via"] == "phone"), m
    assert chat.activity(proj)["phone_today"] == 0


def test_a_replayed_phone_text_queues_one_input_and_one_record(proj, run, conn):
    gid = _general(proj, conn, run, "once")
    conn.inbox.append(pv3.msg(pv3.GEN, {"text": "once", "general": True}))  # the relay replays the same id
    run("relay", "inbox")
    assert len(runs.human_waiting(proj, gid)) == 1
    runs.pending_add(proj, gid, "Marco", "message", "again", "phone", "p_" + pv3.GEN[2:])
    assert len(runs.human_waiting(proj, gid)) == 1  # same p_ id: no second start
    assert len(chat.read_day(proj, chat.day_key(proj))["messages"]) == 1


def test_file_cards_are_an_allowlist_outside_orch_and_git(proj):
    for rel, ok in {
        "docs/report.md": True,
        ".orch/config.toml": False,
        ".git/config": False,
        ".ssh/id_rsa": False,
        "id_rsa": False,
        ".npmrc": False,
        ".netrc": False,
        "data.sqlite": False,
        "notes/.env.local": False,
        "../x": False,
    }.items():
        p = proj / rel
        if rel.startswith(".."):
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        assert (chat.safe_file(proj, rel) is not None) is ok, rel
    assert chat.safe_file(proj, "../x") is None


def test_a_file_card_is_checked_again_when_the_day_is_read(proj):
    (proj / "r.md").write_text("x")
    chat.record(proj, "m_aaaaaaaaaaaaaaaa", WS, "helper", "see", refs=[{"kind": "file", "path": "r.md"}])
    day = chat.day_key(proj)
    assert chat.read_day(proj, day)["messages"][0]["refs"][0]["path"] == "r.md"
    (proj / "r.md").unlink()
    (proj / "r.md").symlink_to(proj / ".orch" / "config.toml")  # swapped for a link into .orch
    assert chat.read_day(proj, day)["messages"][0]["refs"] == []


def test_day_files_are_private_and_a_bad_zone_is_said(proj, capsys):
    chat.record(proj, "m_aaaaaaaaaaaaaaaa", "you", "phone", "x")
    f = proj / ".orch" / "chat" / f"{chat.day_key(proj)}.json"
    assert (f.stat().st_mode & 0o777) == 0o600
    (proj / ".orch" / "config.toml").write_text('[workspace]\ntz = "Mars/Olympus"\n')
    chat.day_key(proj)
    assert "Mars/Olympus" in capsys.readouterr().err


def test_chat_id_is_cheap_and_knows_paused(proj, run):
    assert json.loads(run("chat", "id", "--json")[1]) == {"ticket": None, "paused": False}
    gid = tickets.ensure_general(proj, "x")
    run("ext", "set", gid, "automation", '{"paused": true}', "--by", "human:t")
    assert json.loads(run("chat", "id", "--json")[1]) == {"ticket": gid, "paused": True}


def test_helper_allowlist_lets_the_useful_things_through(proj, run, new_ticket, monkeypatch):
    gid = tickets.ensure_general(proj, "x")
    tid = new_ticket("Pay car tax")
    key = tickets.load(proj, tid)["key"]
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ORCH_TICKET", gid)
    for argv in (
        ("ticket", "list"),
        ("ticket", "show", key),
        ("log", tid, "a note"),
        ("check", "add", key, "call the office"),
        ("ref", "add", tid, "https://example.com/a"),
        ("ref", "list", tid),
        ("chat", "status"),
        ("chat", "days"),
        ("needs",),
        ("status",),
    ):
        code, _, err = run(*argv)
        assert code == 0, (argv, err)
    assert run("ticket", "new", "Made by the helper")[0] == 0


def test_helper_cannot_reach_the_chat_ticket_through_a_key_or_patch_data(proj, run, monkeypatch):
    gid = tickets.ensure_general(proj, "x")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ORCH_TICKET", gid)
    with pytest.raises(Refused):
        tickets.patch(proj, gid, 1, '{"status": "done"}', "agent:x")  # also checked inside tickets.patch

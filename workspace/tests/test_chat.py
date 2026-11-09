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


def test_say_works_in_a_git_folder(proj, run):
    """fb31: in a git project the Chat file under .orch/chat was refused ("git would not leave ... alone"), so
    "Message Pilatus" always said "Could not send your message", with or without relay and publish."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    code, out, err = run("chat", "say", "--by", "human:marco", "--json", "--", "Hallo")
    assert code == 0, (out, err)
    assert chat.read_day(proj, chat.day_key(proj))["messages"][-1]["text"] == "Hallo"
    ignored = subprocess.run(["git", "check-ignore", "-q", ".orch/chat/x.json"], cwd=proj)
    assert ignored.returncode == 0  # the Chat texts are private, never committed


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


# ---------------------------------------------------------------- the delta review: per-command arguments, run hooks, cards


def _helper(proj, monkeypatch, run_id="r_helper0001"):
    gid = tickets.ensure_general(proj, "x")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ORCH_TICKET", gid)
    monkeypatch.setenv("ORCH_RUN", run_id)
    return gid


def test_update_is_not_exempt_and_by_phone_and_extras_are_refused(proj, run, new_ticket, monkeypatch):
    tid = new_ticket("Pay car tax")
    _helper(proj, monkeypatch)
    for argv in (
        ("update",),
        ("log", tid, "x", "--by", "human:marco"),  # never writes as the person
        ("check", "add", tid, "x", "--by", "human:marco"),
        ("ticket", "new", "T", "--by", "human:marco"),
        ("ref", "add", tid, "https://example.com", "--by", "human:marco"),
        ("ticket", "new", "T", "--ext", 'x={"a": 1}'),
        ("ticket", "list", "--by", "human:marco"),
        ("relay", "send", "phones", "x", "--file", "report.md"),
        ("run", "send", tid, "go"),
        ("ticket", "show", "NOPE-1"),  # does not resolve: refused, not skipped
    ):
        assert run(*argv)[0] == 2, argv
    # without --by the actor is forced to the agent whatever it would claim
    run("log", tid, "note from the helper")
    assert tickets.load(proj, tid)["history"][-1]["by"].startswith("agent:")


def test_run_hooks_only_for_the_chat_ticket_and_the_helpers_own_run(proj, run, new_ticket, monkeypatch):
    tid = new_ticket("Other")
    gid = _helper(proj, monkeypatch)
    for argv in (
        ("run", "done", tid),
        ("run", "release", tid),
        ("run", "claim", tid),
        ("run", "event", "--kind", "session", "--run", "r_someoneelse"),
        ("run", "release", gid, "--run", "r_someoneelse"),
    ):
        code, _, err = run(*argv)
        assert code == 2 and "cannot do that" in err, (argv, err)
    # the Chat ticket with its own run id passes the guard (what happens then is the run code's business)
    from types import SimpleNamespace

    chat.guard(proj, SimpleNamespace(cmd="run", sub="release", ticket=gid, run="r_helper0001", json=False))
    chat.guard(proj, SimpleNamespace(cmd="run", sub="event", ticket=None, run=None, kind="idle", json=False))


def test_helper_relay_send_is_plain_text_to_a_paired_phone_with_safe_cards(proj, run, conn, monkeypatch):
    gid = _general(proj, conn, run)
    run("relay", "refresh")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ORCH_TICKET", gid)
    ok = run(
        "relay",
        "send",
        pv3.PHONE,
        "Done.",
        "--ticket",
        gid,
        "--reply-to",
        pv3.GEN,
        "--ref",
        "reference:https://example.com",
    )
    assert ok[0] == 0, ok
    for argv in (
        ("relay", "send", "ph_notpaired01", "x", "--ticket", gid),
        ("relay", "send", "ws_other00001", "x"),
        ("relay", "send", pv3.PHONE, "x", "--update", "result", "--ticket", gid),
        ("relay", "send", pv3.PHONE, "x", "--ticket", gid, "--ref", "file:.env"),
        ("relay", "send", pv3.PHONE, "x", "--ticket", gid, "--ref", "file:.orch/config.toml"),
        ("relay", "send", pv3.PHONE, "x", "--ticket", "t_otherticket1"),
    ):
        assert run(*argv)[0] == 2, argv


def test_hard_linked_and_more_secret_files_are_no_cards(proj):
    (proj / "doc.txt").write_text("x")
    import os

    os.link(proj / "doc.txt", proj / "copy.txt")
    assert chat.safe_file(proj, "doc.txt") is None and chat.safe_file(proj, "copy.txt") is None  # two names
    for rel in (".kube/config", ".docker/config.json", ".pgpass", ".htpasswd", "web/.htpasswd"):
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_text("x")
        assert chat.safe_file(proj, rel) is None, rel
    (proj / "ok.md").write_text("hello")
    assert chat.read_file(proj, "ok.md") == b"hello"
    assert chat.read_file(proj, ".kube/config") is None


def test_a_hand_edited_day_file_never_crashes_a_read(proj):
    chat.record(proj, "m_aaaaaaaaaaaaaaaa", "you", "phone", "x")
    f = proj / ".orch" / "chat" / f"{chat.day_key(proj)}.json"
    d = json.loads(f.read_text())
    d["messages"] += ["junk", 5, {"id": "m_b", "text": "y", "refs": ["junk", {"kind": "file", "path": 7}]}]
    f.write_text(json.dumps(d))
    out = chat.read_day(proj, d["day"])["messages"]
    assert [m["id"] for m in out] == ["m_aaaaaaaaaaaaaaaa", "m_b"] and out[1]["refs"] == []
    assert chat.days(proj)


def test_chat_id_works_for_the_host_even_though_chat_is_a_hidden_command(proj, run):
    assert run("chat", "id", "--json")[0] == 0
    with pytest.raises(SystemExit):
        run("--help-all")


# ---------------------------------------------------------------- third review round


def test_helper_writes_need_a_named_ticket_and_no_owner_or_odd_options(proj, run, new_ticket, monkeypatch):
    tid = new_ticket("Pay car tax")
    gid = _helper(proj, monkeypatch)
    for argv in (
        ("ticket", "new", "T", "--owner", "someone"),
        ("ticket", "new", "T", "--parent", gid),
        ("init",),  # init is guarded too
        ("run", "claim", gid, "--agent", "evil"),
        ("run", "claim", gid, "--session", "s1"),
        ("ref", "add", tid, "file:~/.ssh/id_rsa", "--kind", "file"),
        ("ref", "add", tid, "../x", "--kind", "file"),
        ("ref", "add", tid, "/etc/passwd"),
        ("ref", "add", tid, ".orch/config.toml"),
    ):
        assert run(*argv)[0] == 2, argv
    (proj / "plan.md").write_text("x")
    assert (
        run("ref", "add", tid, "plan.md")[0] == 0 and run("ref", "add", tid, "https://example.com/p")[0] == 0
    )
    from types import SimpleNamespace

    with pytest.raises(Refused):  # a write with no ticket named
        chat.guard(proj, SimpleNamespace(cmd="log", sub=None, id=None, text="x", json=False))
    chat.guard(
        proj,
        SimpleNamespace(
            cmd="run", sub="event", ticket=None, run=None, kind="idle", session_id=None, json=False
        ),
    )
    with pytest.raises(Refused):  # 0 is a given value, not "unset"
        chat.guard(proj, SimpleNamespace(cmd="status", sub=None, json=False, pid=0))


def test_relay_topic_makes_a_ticket_and_is_not_a_read(proj):
    assert chat.HELPER_COMMANDS[("relay", "topic")][0] == "plain"


def test_more_secret_files_and_a_swap_between_check_and_read(proj):
    for rel in (
        "db.sqlite-wal",
        "db.sqlite-shm",
        "db.sqlite-journal",
        "terraform.tfstate",
        "terraform.tfstate.backup",
        ".bash_history",
        "cfg/auth.json",
    ):
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_text("x")
        assert chat.safe_file(proj, rel) is None, rel
    (proj / "a.md").write_text("hello")
    assert chat.read_file(proj, "a.md") == b"hello"
    (proj / "big.md").write_text("x" * 100)
    assert chat.read_file(proj, "big.md", 10) is None


def test_ref_add_is_normalised_like_ref_add_and_symlinked_folders_are_refused(
    proj, run, new_ticket, monkeypatch
):
    tid = new_ticket("Pay car tax")
    (proj / "docs").mkdir()
    (proj / "docs" / "a.md").write_text("x")
    (proj / "plan.md").write_text("x")
    secret = proj / ".orch" / "keep"
    secret.mkdir(parents=True, exist_ok=True)
    (secret / "s.md").write_text("secret")
    (proj / "linked").symlink_to(secret)  # a folder that points into .orch
    _helper(proj, monkeypatch)
    for target in (
        "..\\outside.md",
        "docs\\..\\..\\x.md",
        "../x",
        "C:\\Users\\x\\id_rsa",
        "/etc/passwd",
        "docs/../.orch/config.toml",
        "linked/s.md",
        "plan.md:0",
    ):
        assert run("ref", "add", tid, target)[0] == 2, target
    assert run("ref", "add", tid, "docs\\a.md")[0] == 0  # backslashes mean the same file, as for the person
    assert run("ref", "add", tid, "plan.md:3")[0] == 0
    assert chat.read_file(proj, "linked/s.md") is None and chat.helper_safe_file(proj, "linked/s.md") is None
    assert chat.read_file(proj, "docs\\a.md") == b"x"


# ---------------------------------------------------------------- fourth round


def test_people_keep_the_old_file_card_rule_the_helper_gets_the_strict_one(proj):
    (proj / "docs").mkdir()
    (proj / "docs" / "a.md").write_text("x")
    (proj / "~odd.md").write_text("x")
    assert chat.safe_file(proj, "docs/a.md") == "docs/a.md"
    assert chat.safe_file(proj, "~odd.md") == "~odd.md"  # a POSIX name a person may use
    assert chat.helper_safe_file(proj, "~odd.md") is None
    assert chat.helper_safe_file(proj, "docs\\a.md") == "docs/a.md"
    assert chat.helper_safe_file(proj, "docs/../docs/a.md") == "docs/a.md"
    assert chat.helper_safe_file(proj, "../x") is None and chat.helper_safe_file(proj, "/etc/hosts") is None


def test_options_are_compared_with_the_parsers_own_defaults(proj, monkeypatch):
    from types import SimpleNamespace

    _helper(proj, monkeypatch)
    # ticket list --all is a store_true flag: its default False is "not given", True is given (and allowed here)
    chat.guard(proj, SimpleNamespace(cmd="ticket", sub="list", status=None, all=False, json=False, by=None))
    chat.guard(proj, SimpleNamespace(cmd="ticket", sub="list", status=None, all=True, json=False, by=None))
    with pytest.raises(Refused):  # --by differs from its default None
        chat.guard(
            proj, SimpleNamespace(cmd="ticket", sub="list", status=None, all=False, json=False, by="human:x")
        )
    with pytest.raises(Refused):  # an option the command does not list, even set to its "false" value
        chat.guard(
            proj,
            SimpleNamespace(
                cmd="ticket", sub="list", status=None, all=False, json=False, by=None, fresh=True
            ),
        )


def test_ref_add_kinds_are_an_allowlist(proj, run, new_ticket, monkeypatch):
    tid = new_ticket("A")
    other = new_ticket("B")
    (proj / "ok.md").write_text("x")
    tickets.ensure_general(proj, "x")
    _helper(proj, monkeypatch)
    assert run("ref", "add", tid, "https://example.com/x", "--kind", "github:pr")[0] == 0
    assert run("ref", "add", tid, other)[0] == 0
    assert run("ref", "add", tid, "ok.md")[0] == 0
    assert run("ref", "add", tid, f"artifact:{other}/x.md")[0] == 2
    assert run("ref", "add", tid, tid)[0] == 2  # itself


def test_read_file_returns_none_for_any_error(proj, monkeypatch):
    (proj / "ok.md").write_text("hello")
    from orch import safefile

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(safefile, "open_file_ref", boom)
    assert chat.read_file(proj, "ok.md") is None


def test_init_and_the_guard_work_in_an_empty_folder(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ORCH_TICKET", "t_somethingelse")
    chat.guard(tmp_path, SimpleNamespace(cmd="init", sub=None, json=False))  # no .orch here: must not raise
    monkeypatch.delenv("ORCH_TICKET")
    chat.guard(tmp_path, SimpleNamespace(cmd="init", sub=None, json=False))


def test_the_run_claim_the_wrapper_may_need_still_passes_for_the_helper(proj, monkeypatch):
    from types import SimpleNamespace

    gid = _helper(proj, monkeypatch)
    monkeypatch.setenv("ORCH_AGENT", "fake")
    ns = dict(cmd="run", sub="claim", ticket=gid, agent="fake", pid=123, json=False, by=None, mode=None)
    ns.pop("mode")
    chat.guard(proj, SimpleNamespace(**ns, session=None, text=None, take_over=False))
    with pytest.raises(Refused):
        chat.guard(proj, SimpleNamespace(**ns, session="s1", text=None, take_over=False))
    with pytest.raises(Refused):
        chat.guard(proj, SimpleNamespace(**ns, session=None, text=None, take_over=True))


def test_cards_keep_the_rule_of_whoever_added_them(proj, monkeypatch):
    secret = proj / ".orch" / "keep"
    secret.mkdir(parents=True, exist_ok=True)
    (proj / "real").mkdir()
    (proj / "real" / "r.md").write_text("fine")
    (proj / "linked").symlink_to(proj / "real")  # a symlinked folder inside the workspace
    # a person adds it: kept (person rule), and it opens
    person = chat.clean_refs(proj, [{"kind": "file", "path": "linked/r.md"}])
    assert person and person[0]["added_by"] == "person"
    assert chat.read_file(proj, "linked/r.md", added_by="person") == b"fine"
    chat.record(
        proj, "m_aaaaaaaaaaaaaaaa", "you", "dashboard", "see", refs=[{"kind": "file", "path": "linked/r.md"}]
    )
    assert (
        chat.read_day(proj, chat.day_key(proj))["messages"][0]["refs"][0]["path"] == "real/r.md"
    )  # stored as the real path
    # the helper cannot add it, and a helper-marked card in such a folder is dropped when read
    tickets.ensure_general(proj, "x")
    _helper(proj, monkeypatch)
    assert chat.clean_refs(proj, [{"kind": "file", "path": "linked/r.md"}]) == []
    assert chat.read_file(proj, "linked/r.md", added_by="helper") is None
    assert chat.read_file(proj, "linked/r.md") is None  # no mark: strict
    f = proj / ".orch" / "chat" / f"{chat.day_key(proj)}.json"
    d = json.loads(f.read_text())
    d["messages"][0]["refs"][0].update(added_by="helper", path="linked/r.md")
    f.write_text(json.dumps(d))
    assert chat.read_day(proj, d["day"])["messages"][0]["refs"] == []
    # a person's card never reaches .orch, whatever the link
    (proj / "toorch").symlink_to(secret)
    (secret / "s.md").write_text("secret")
    assert chat.read_file(proj, "toorch/s.md", added_by="person") is None


def test_ref_add_web_needs_http_and_no_ref_to_the_chat_ticket(proj, run, new_ticket, monkeypatch):
    tid = new_ticket("A")
    gid = tickets.ensure_general(proj, "x")
    _helper(proj, monkeypatch)
    for target in ("file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)", gid):
        assert run("ref", "add", tid, target)[0] == 2, target
    assert run("ref", "add", tid, "https://example.com/ok")[0] == 0


# ---------------------------------------------------------------- the Chat ticket is never finished; helper stays in orch


def test_general_never_leaves_its_status_by_any_path(proj, conn, run):
    gid = _general(proj, conn, run)
    before = tickets.load(proj, gid)["status"]
    for by in ("agent:claude", "human:me"):
        for status in ("done", "review", "dropped", "active", "open"):
            with pytest.raises(Refused):
                tickets.set_status(proj, gid, status, by)  # `orch done` and set_status
    rev = tickets.load(proj, gid)["revision"]
    with pytest.raises(Refused):
        tickets.patch(proj, gid, rev, json.dumps({"status": "review"}), "human:me")
    with pytest.raises(Refused):
        tickets.patch(proj, gid, rev, json.dumps({"status": "done"}), "agent:claude")
    t = tickets.load(proj, gid)
    assert t["status"] == before


def test_general_is_not_touched_by_the_run_wrapper_hooks(proj, conn, run):
    gid = _general(proj, conn, run)
    t0 = tickets.load(proj, gid)
    n = len(t0["history"])
    tickets.mark_working(proj, gid, "agent:relay", "Claude")
    tickets.agent_stopped(proj, gid, "agent:relay")
    tickets.wait_for_start(proj, gid, "no sign-in", "agent:relay")
    t1 = tickets.load(proj, gid)
    assert (t1["status"], len(t1["history"])) == (t0["status"], n)


def test_only_real_messages_carry_chat_message(proj, conn, run):
    gid = _general(proj, conn, run, "hello there")
    tickets.apply_op(proj, gid, lambda t: tickets.add_history(t, "agent:x", "Claude started"))
    hist = tickets.load(proj, gid)["history"]
    flagged = [e["text"] for e in hist if e.get("chat_message") is True]
    assert "Claude started" not in flagged and flagged


def test_helper_prompt_and_skill_stay_inside_orch(proj):
    gid = tickets.ensure_general(proj, "phone:Marco")
    prompt = chat.helper_prompt(proj, tickets.load(proj, gid), [], "")
    skill = (Path(__file__).resolve().parents[1] / "skills" / "orch" / "SKILL.md").read_text()
    for text in (prompt, skill):
        assert "only use orch tools and the files in this workspace" in text
        assert "connectors" in text


def test_general_may_still_wait_or_be_ready(proj, conn, run):
    gid = _general(proj, conn, run)
    for status in ("waiting", "ready"):
        assert tickets.set_status(proj, gid, status, "human:me")["status"] == status


def test_an_inbound_phone_text_in_general_carries_the_chat_flag(proj, run, conn):
    gid = _general(proj, conn, run, "hi from phone")
    hist = tickets.load(proj, gid)["history"]
    assert [e["text"] for e in hist if e.get("chat_message") is True] == [
        "From Marco's iPhone: hi from phone"
    ]
    assert "orch relay send" not in str([e["text"] for e in hist])  # no agent instruction row in History


def test_an_agent_cannot_pass_a_note_off_as_a_chat_message_by_env_via(proj, conn, run, monkeypatch):
    gid = _general(proj, conn, run)
    monkeypatch.setenv("ORCH_VIA", "phone")
    tickets.apply_op(proj, gid, lambda t: tickets.add_history(t, "agent:x", "sneaky note"))
    assert not [
        e for e in tickets.load(proj, gid)["history"] if e["text"] == "sneaky note" and e.get("chat_message")
    ]


def test_an_agent_text_to_chat_is_recorded_as_the_agent_whatever_by_says(proj, run, conn, monkeypatch):
    gid = _general(proj, conn, run)
    monkeypatch.setenv("CLAUDECODE", "1")
    run("relay", "send", pv3.PHONE, "answer", "--ticket", gid, "--by", "human:marco")
    sent = [e for e in tickets.load(proj, gid)["history"] if e["text"] == "answer"]
    assert sent and all(e["by"] == "agent:claude" and e["chat_message"] is True for e in sent)


def test_every_new_history_line_carries_the_flag(proj):
    t = {"history": []}
    tickets.add_history(t, "agent:x", "note")
    tickets.add_history(t, "human:me", "hi", chat=True)
    assert [e["chat_message"] for e in t["history"]] == [False, True]


def test_chat_ticket_and_locks_stay_out_of_git(proj, run):
    """Privacy: the General ticket holds the Chat history; neither it nor the .lock-* files may show in git."""
    import subprocess

    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True, env=env)
    code, _, _ = run("chat", "say", "Privat", "--json", "--by", "human:marco")
    assert code == 0
    gid = tickets.general_id(proj)
    assert (proj / ".orch" / "tickets" / f"{gid}.json").is_file()
    out = subprocess.run(
        ["git", "status", "--porcelain", "-uall"], cwd=proj, capture_output=True, text=True, env=env
    ).stdout
    assert ".orch/tickets" not in out, out

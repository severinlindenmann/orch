"""One write path (apply_op), new ticket fields, questions with kind/via, provenance, agent sessions."""

import json
import subprocess
import sys

import pytest

from orch import tickets


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def test_two_processes_race_both_land(proj, run, new_ticket):
    tid = new_ticket()
    for i in (1, 2, 3, 4):
        assert run("check", "add", tid, f"step {i}")[0] == 0
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "orch",
                "check",
                "done",
                tid,
                f"c{i}",
                "--note",
                f"n{i}",
                "--by",
                "agent:x",
            ],
            cwd=proj,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for i in (1, 2, 3, 4)
    ]
    outs = [p.communicate() for p in procs]
    assert [p.returncode for p in procs] == [0, 0, 0, 0], outs
    t = read(proj, tid)
    assert all(c["done"] for c in t["checklist"])
    assert t["revision"] == 1 + 4 + 4  # created, 4 adds, 4 dones: no lost update


def test_stale_expect_refused_with_current(proj, run, new_ticket):
    tid = new_ticket()
    run("check", "add", tid, "Ask finance which date format")
    assert run("check", "edit", tid, "c1", "Ask about dates", "--by", "agent:claude-code")[0] == 0
    code, out, err = run(
        "check", "edit", tid, "c1", "Mine", "--was", "Ask finance which date format", "--json"
    )
    assert code == 2 and "Refused:" in err
    j = json.loads(out)
    assert j["changed_by"] == "agent:claude-code" and j["current"]["text"] == "Ask about dates"
    assert j["revision"] == read(proj, tid)["revision"]
    assert read(proj, tid)["checklist"][0]["text"] == "Ask about dates"


def test_if_revision_on_check_edit_and_ticket_edit(proj, run, new_ticket):
    tid = new_ticket()
    run("check", "add", tid, "x")
    rev = read(proj, tid)["revision"]
    assert run("check", "edit", tid, "c1", "y", "--if-revision", str(rev - 1), "--json")[0] == 2
    assert run("ticket", "edit", tid, "--owner", "A", "--if-revision", str(rev - 1))[0] == 2
    assert run("ticket", "edit", tid, "--owner", "A", "--if-revision", str(rev))[0] == 0


def test_plain_op_lands_on_latest_revision(proj, new_ticket):
    tid = new_ticket()
    t = tickets.load(proj, tid)  # an old copy
    tickets.log(proj, tid, "one", "agent:x")
    tickets.apply_op(
        proj, tid, lambda x: x["history"].append({"at": tickets.now(), "by": "agent:x", "text": "two"})
    )
    assert t["revision"] < tickets.load(proj, tid)["revision"]
    assert [h["text"] for h in read(proj, tid)["history"]][-2:] == ["one", "two"]


def test_busy_message(proj, new_ticket, monkeypatch):
    tid = new_ticket()
    lock = proj / ".orch" / "tickets" / f".lock-{tid}"
    lock.write_text("")
    monkeypatch.setattr(tickets.time, "monotonic", iter([0, 100, 200, 300]).__next__)
    with pytest.raises(tickets.Refused, match="busy"):
        tickets.log(proj, tid, "x", "agent:x")


def test_agent_can_reorder_wont_do_steps_but_cannot_change_decisions(proj, new_ticket, monkeypatch):
    tid = new_ticket()
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    for text in ("Ask finance", "Ask sales"):
        _, step = tickets.check_add(proj, tid, text, "human:Ann")
        tickets.check_wont_do(proj, tid, step["id"], "human:Ann", "Not needed")
    before = read(proj, tid)["checklist"]
    monkeypatch.setattr(tickets, "agent_tool", lambda: "codex")

    tickets.check_move(proj, tid, "c1", "c2", "agent:codex")
    moved = read(proj, tid)
    assert moved["checklist"] == list(reversed(before))
    for edit in ({"wont_do": False}, {"reason": "Changed"}, {"by": "agent:codex"}):
        with pytest.raises(tickets.Refused, match="Only a person"):
            tickets.apply_op(proj, tid, lambda t, edit=edit: t["checklist"][0].update(edit))
        assert read(proj, tid) == moved


@pytest.mark.parametrize("agent,wont_do", [(True, True), (True, False), (False, True)])
def test_reword_step_respects_persons_wont_do(proj, new_ticket, monkeypatch, agent, wont_do):
    tid = new_ticket()
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    _, step = tickets.check_add(proj, tid, "Ask finance", "human:Ann")
    if wont_do:
        tickets.check_wont_do(proj, tid, step["id"], "human:Ann", "Not needed")
    before = read(proj, tid)
    monkeypatch.setattr(tickets, "agent_tool", lambda: "codex" if agent else None)

    def reword(ticket):
        ticket["checklist"][0]["text"] = "Ask sales"

    if agent and wont_do:
        with pytest.raises(tickets.Refused, match="Only a person"):
            tickets.apply_op(proj, tid, reword)
        assert read(proj, tid) == before
    else:
        tickets.apply_op(proj, tid, reword)
        expected = {**before["checklist"][0], "text": "Ask sales"}
        assert read(proj, tid)["checklist"][0] == expected


@pytest.mark.parametrize("reopen_original", [False, True])
def test_agent_cannot_duplicate_wont_do_step(proj, new_ticket, monkeypatch, reopen_original):
    tid = new_ticket()
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    _, step = tickets.check_add(proj, tid, "Ask finance", "human:Ann")
    tickets.check_wont_do(proj, tid, step["id"], "human:Ann", "Not needed")
    before = read(proj, tid)
    monkeypatch.setattr(tickets, "agent_tool", lambda: "codex")

    def attack(ticket):
        original = ticket["checklist"][0]
        ticket["checklist"].append(original.copy())
        if reopen_original:
            original["wont_do"] = False
            original.pop("reason", None)

    with pytest.raises(tickets.Refused, match="Duplicate checklist step ids"):
        tickets.apply_op(proj, tid, attack)
    assert read(proj, tid) == before


def test_fields_owner_due_note_summary(proj, run, validate, new_ticket):
    tid = new_ticket()
    code, out, _ = run(
        "ticket", "edit", tid, "--owner", "Severin", "--due", "2026-11-10", "--note", "Before close"
    )
    assert code == 0 and "Saved (revision" in out
    t = read(proj, tid)
    assert (t["owner"], t["due"], t["note"]) == ("Severin", "2026-11-10", "Before close")
    validate(t)
    code, _, err = run("ticket", "edit", tid, "--due", "10.11.2026")
    assert code == 2 and "due must be a date like 2026-11-10" in err
    assert run("ticket", "edit", tid, "--due", "2026-02-30")[0] == 2
    assert run("ticket", "edit", tid, "--owner", "x" * 65)[0] == 2
    assert run("ticket", "edit", tid, "--note", "x" * 2001)[0] == 2
    assert run("ticket", "edit", tid, "--owner", "")[0] == 0 and "owner" not in read(proj, tid)
    assert run("ticket", "edit", tid)[0] == 2  # nothing to change


def test_summary_and_show_first(proj, run, validate, new_ticket):
    tid = new_ticket("Q3 summary")
    n = len(read(proj, tid)["history"])
    code, out, _ = run("ticket", "summary", tid, "Draft ready, waiting for Anna")
    assert code == 0 and "Summary saved" in out
    t = read(proj, tid)
    validate(t)
    assert t["summary"] == "Draft ready, waiting for Anna" and len(t["history"]) == n  # no history spam
    shown = run("ticket", "show", tid)[1].splitlines()
    assert shown[1] == "Draft ready, waiting for Anna"
    code, _, err = run("ticket", "summary", tid, "x" * 201)
    assert code == 2 and "A summary is at most 200 characters" in err


def test_patch_new_fields_and_conflict_json(proj, run, new_ticket):
    tid = new_ticket()
    code, out, _ = run(
        "ticket", "patch", tid, '{"due": "2026-11-12", "summary": "s"}', "--if-revision", "1", "--json"
    )
    assert code == 0
    code, out, _ = run("ticket", "patch", tid, '{"due": "2026-11-13"}', "--if-revision", "1", "--json")
    j = json.loads(out)
    assert code == 2 and j["revision"] == 2 and j["current"]["due"] == "2026-11-12" and j["changed_by"]
    assert run("ticket", "patch", tid, '{"due": "bad"}', "--if-revision", "2")[0] == 2


def test_via_is_a_free_token(proj, run, validate, new_ticket):
    tid = new_ticket()
    run("ask", tid, "Which?", "--option", "A", "--option", "B")
    code, _, err = run("answer", tid, "q1", "A", "--via", "dash board")
    assert code == 2 and "via must be a short word" in err
    code, out, _ = run("answer", tid, "q1", "a", "--via", "dashboard", "--by", "human:marco")
    assert code == 0
    t = read(proj, tid)
    validate(t)
    assert t["questions"][0]["via"] == "dashboard" and t["history"][-1]["via"] == "dashboard"
    code, _, err = run("answer", tid, "q1", "B")
    assert code == 2 and "already answered" in err  # first answer wins


def test_history_via_defaults_to_cli(proj, run, validate, new_ticket):
    tid = new_ticket()
    run("log", tid, "hello")
    t = read(proj, tid)
    validate(t)
    assert t["history"][-1]["via"] == "cli"


def test_ask_kind_action_check_and_addon_note(proj, run, validate, new_ticket):
    tid = new_ticket()
    run("check", "add", tid, "Ask finance")
    code, out, _ = run(
        "ask",
        tid,
        "Retry?",
        "--kind",
        "scheduler:failure",
        "--option",
        "Try again",
        "--option",
        "Stop",
        "--action",
        '{"run": "r1"}',
        "--check",
        "c1",
        "--json",
    )
    assert code == 0
    q = json.loads(out)
    assert (q["kind"], q["action"], q["check"]) == ("scheduler:failure", {"run": "r1"}, "c1")
    validate(read(proj, tid))
    code, out, _ = run("answer", tid, "q1", "try again")
    assert code == 0 and "Answered: Try again" in out
    assert "Recorded. The scheduler acts on it when it runs." in out
    assert run("ask", tid, "x", "--kind", "Bad Kind")[0] == 2
    assert run("ask", tid, "x", "--check", "c9")[0] == 2
    assert run("ask", tid, "x", "--action", "[1]")[0] == 2


def test_plain_answer_has_no_addon_note(proj, run, new_ticket):
    tid = new_ticket()
    run("ask", tid, "Ok?", "--option", "Yes")
    assert "Recorded" not in run("answer", tid, "q1", "Yes")[1]


def test_explicit_human_by_not_refused_under_agent(proj, run, new_ticket, monkeypatch):
    tid = new_ticket()
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, _ = run("log", tid, "from a person", "--by", "human:marco")
    assert code == 0 and read(proj, tid)["history"][-1]["by"] == "human:marco"
    run("log", tid, "default")
    assert read(proj, tid)["history"][-1]["by"] == "agent:claude"


def test_sessions_record_and_find(proj, validate, new_ticket):
    tid = new_ticket()
    tickets.record_session(proj, tid, "my-agent", "s-1", "laptop")
    tickets.record_session(proj, tid, "my-agent", "s-1", "vps")
    tickets.record_session(proj, tid, "my-agent", "s-2", "laptop")  # same agent+host: updated, not added
    t = tickets.load(proj, tid)
    validate(t)
    assert len(t["sessions"]) == 2
    assert tickets.sessions_for(proj, tid, t, "my-agent", "laptop") == "s-2"
    assert tickets.sessions_for(proj, tid, t, "my-agent", "vps") == "s-1"
    assert tickets.sessions_for(proj, tid, t, "other", "laptop") is None
    assert tickets.sessions_for(proj, tid, t, "my-agent", "elsewhere") is None
    for i in range(40):
        tickets.record_session(proj, tid, "a", f"s{i}", f"h{i}")
    assert len(tickets.load(proj, tid)["sessions"]) == 32


def test_core_names_no_addon_or_tool_in_new_code():
    from pathlib import Path

    for f in ("tickets.py", "cli.py"):
        text = (Path(tickets.__file__).parent / f).read_text(encoding="utf-8").lower()
        for word in ("scheduler", "netbird", "claude", "codex"):
            assert word not in text.replace("claude_code_entrypoint", ""), (f, word)


def test_history_says_where_a_change_came_from(proj, run, monkeypatch):
    from orch import runs, tickets

    monkeypatch.setenv("ORCH_VIA", "dashboard")
    t = tickets.create(proj, "From the page", "human:t")
    assert t["history"][0]["via"] == "dashboard"
    monkeypatch.setenv("ORCH_VIA", "Bad Word!")
    t = tickets.create(proj, "Odd", "human:t")
    assert t["history"][0]["via"] == "cli"
    monkeypatch.setenv("ORCH_VIA", "dashboard")
    assert "ORCH_VIA" not in runs._agent_environ(proj)  # an agent started from the page writes as itself


@pytest.mark.parametrize(
    "text, options",
    [
        (
            "Where do I get the weekly data?",
            ["Give me the real CRM export URL (and credentials in .orch/secrets/ if needed)"],
        ),
        ("Please paste your API key", []),
        ("What's the admin password?", ["Skip"]),
        ("Send me the access token for the CRM", []),
        ("Is the key in .ORCH\\Secrets\\x?", []),
    ],
)
def test_ask_refuses_secrets(proj, run, new_ticket, text, options):
    tid = new_ticket()
    args = ["ask", tid, text] + [a for o in options for a in ("--option", o)]
    code, _, err = run(*args)
    assert code == 2
    assert "never ask for a password" in err
    assert not read(proj, tid)["questions"]


def test_ask_allows_plain_access_question(proj, run, new_ticket):
    tid = new_ticket()
    code, _, _ = run(
        "ask",
        tid,
        "Is access to the CRM set up for this workspace?",
        "--option",
        "Yes",
        "--option",
        "I will set it up myself",
    )
    assert code == 0


def test_ask_refuses_secret_in_recommended_and_action(proj, run, new_ticket):
    tid = new_ticket()
    code, _, err = run("ask", tid, "Which way?", "--recommend", "Paste your API key from .orch/secrets")
    assert code == 2 and "never ask for a password" in err
    code, _, err = run(
        "ask", tid, "Retry?", "--kind", "scheduler:failure", "--action", '{"label": "Send me the password"}'
    )
    assert code == 2 and "never ask for a password" in err
    assert not read(proj, tid)["questions"]


@pytest.mark.parametrize(
    "text",
    [
        "Is the API key already set up?",
        "Should the password reset email be HTML?",
        "Do we need a password-protected PDF?",
        "Rotate your access tokens now?",
    ],
)
def test_ask_allows_benign_auth_questions(proj, run, new_ticket, text):
    assert run("ask", new_ticket(), text)[0] == 0


@pytest.mark.parametrize(
    "text",
    [
        "Gib mir das Passwort",
        "Bitte schick mir die Zugangsdaten",
        "Please paste the PAT",
        "Give me the token",
        "Put it in the secrets folder",
        "Send me the API\u200b key",
        "\uff27ive me the password",
    ],
)
def test_ask_refuses_more_secret_forms(proj, run, new_ticket, text):
    assert run("ask", new_ticket(), text)[0] == 2


def test_refused_secret_ask_is_logged(proj, run, new_ticket):
    tid = new_ticket()
    assert run("ask", tid, "Paste your API key")[0] == 2
    assert any("refused: it asked for a secret" in h["text"] for h in read(proj, tid)["history"])


@pytest.mark.parametrize(
    "text",
    [
        "I need your API key to continue",
        "Your password please",
        "Reply with your token",
        "Which API key should I use?",
        "Ich brauche dein Passwort",
    ],
)
def test_ask_refuses_request_patterns(proj, run, new_ticket, text):
    assert run("ask", new_ticket(), text)[0] == 2


def test_ask_scans_all_action_strings_but_not_machine_keys(proj, run, new_ticket):
    tid = new_ticket()
    base = ["ask", tid, "Retry?", "--kind", "scheduler:failure", "--action"]
    assert run(*base, '{"detail": "Please paste your API key"}')[0] == 2
    assert run(*base, '{"run": "give-me-the-password", "id": "paste-the-token"}')[0] == 0


def test_ask_scans_nested_data_under_machine_keys(proj, run, new_ticket):
    base = ["ask", new_ticket(), "Retry?", "--kind", "scheduler:failure", "--action"]
    assert run(*base, '{"op": {"label": "Please paste your API key"}}')[0] == 2
    assert run(*base, '{"op": ["give me the password"]}')[0] == 2


@pytest.mark.parametrize(
    "text",
    [
        "Should I send the password reset email?",
        "Can you share the password-protected PDF?",
        "Tell me whether to rotate the tokens.",
        "What is the token expiry policy?",
        "Which type of token should we use?",
    ],
)
def test_ask_allows_more_benign_auth_questions(proj, run, new_ticket, text):
    assert run("ask", new_ticket(), text)[0] == 0


def test_ask_refuses_curly_apostrophe_and_natural_language_machine_key(proj, run, new_ticket):
    assert run("ask", new_ticket(), "What\u2019s your password?")[0] == 2
    base = ["ask", new_ticket(), "Retry?", "--kind", "scheduler:failure", "--action"]
    assert run(*base, '{"key": "paste your API key"}')[0] == 2


def test_ticket_new_plan_first_flag(proj, run):
    code, out, _ = run("ticket", "new", "Big work", "--plan-first", "--json", "--by", "human:tester")
    assert code == 0
    assert json.loads(out)["plan_first"] is True
    assert read(proj, json.loads(out)["id"])["plan_first"] is True
    plain = json.loads(run("ticket", "new", "Small", "--json", "--by", "human:tester")[1])
    assert "plan_first" not in plain


def test_plan_first_is_not_a_patchable_field():
    with pytest.raises(tickets.Refused):
        tickets.clean_field("plan_first", "true")


def test_ticket_plan_goes_in_its_own_field_not_the_note(proj, run):
    t = json.loads(
        run("ticket", "new", "Big", "--plan-first", "--note", "My words", "--json", "--by", "human:t")[1]
    )
    code, out, _ = run(
        "ticket",
        "plan",
        t["id"],
        "--goal",
        "Pay online",
        "--not-included",
        "refunds",
        "--json",
        "--by",
        "agent:claude",
    )
    assert code == 0
    got = read(proj, t["id"])
    assert got["plan"] == {"goal": "Pay online", "not_included": "refunds", "by": "agent:claude"}
    assert got["note"] == "My words"
    assert run("ticket", "plan", t["id"], "--goal", "x" * 501, "--by", "agent:claude")[0] != 0


def test_outcome_set_merge_and_clear(proj, run, new_ticket):
    tid = new_ticket()
    code = run("ticket", "outcome", tid, "--changed", "Added CSV export.", "--why", "Finance needs it")[0]
    assert code == 0
    assert read(proj, tid)["outcome"] == {"changed": "Added CSV export.", "why": "Finance needs it"}
    assert run("ticket", "outcome", tid, "--not-included", "PDF")[0] == 0
    assert read(proj, tid)["outcome"]["changed"] == "Added CSV export."
    assert read(proj, tid)["outcome"]["not_included"] == "PDF"
    assert run("ticket", "outcome", tid, "--changed", "", "--why", "", "--not-included", "")[0] == 0
    assert "outcome" not in read(proj, tid)


def test_outcome_refuses_long_and_empty(proj, run, new_ticket):
    tid = new_ticket()
    assert run("ticket", "outcome", tid, "--why", "x" * 301)[0] != 0
    assert run("ticket", "outcome", tid)[0] != 0
    assert "outcome" not in read(proj, tid)


def test_outcome_shown_by_show_on_done_only(proj, run, new_ticket):
    tid = new_ticket()
    assert run("ticket", "outcome", tid, "--changed", "Added CSV export.")[0] == 0
    assert "Changed: Added CSV export." not in run("ticket", "show", tid)[1]
    from conftest import sign_done

    sign_done(proj, tid)  # Done is a signed verdict: a raw "done" in the file would read as Review
    assert "Changed: Added CSV export." in run("ticket", "show", tid)[1]


def test_sessions_require_local_ownership(proj, new_ticket):
    tid = new_ticket()
    tickets.record_session(proj, tid, "agent", "local", "host")
    t = tickets.load(proj, tid)
    t["sessions"].insert(0, {"id": "foreign", "agent": "agent", "host": "host"})
    tickets.save(proj, t)  # incoming ticket JSON may contain a session from another machine
    assert tickets.sessions_for(proj, tid, tickets.load(proj, tid), "agent", "host") == "local"
    t["sessions"] = t["sessions"][:1]
    assert tickets.sessions_for(proj, tid, t, "agent", "host") is None
    # Neither the same id under another agent/host nor another workspace grants ownership.
    assert (
        tickets.sessions_for(
            proj,
            tid,
            {"id": tid, "sessions": [{"id": "local", "agent": "other", "host": "host"}]},
            "other",
            "host",
        )
        is None
    )
    assert tickets.sessions_for(proj / "other", tid, tickets.load(proj, tid), "agent", "host") is None


@pytest.mark.parametrize("contents", [None, "{", "{}", '[{"id":"local"}]', "\udcff"])
def test_sessions_missing_or_corrupt_record(proj, new_ticket, contents):
    tid = new_ticket()
    tickets.record_session(proj, tid, "agent", "local", "host")
    p = proj / ".orch" / "run" / "own-sessions.json"
    if contents is None:
        p.unlink()
    else:
        p.write_bytes(contents.encode("utf-8", errors="surrogateescape"))
    assert tickets.sessions_for(proj, tid, tickets.load(proj, tid), "agent", "host") is None


def test_own_sessions_bounded(proj, new_ticket):
    tid = new_ticket()
    for i in range(501):
        tickets.record_session(proj, tid, "agent", f"s{i}", "host")
    p = proj / ".orch" / "run" / "own-sessions.json"
    entries = json.loads(p.read_text())
    assert len(entries) == 500
    assert entries[0]["id"] == "s1"
    first_seen = entries[0]["first_seen"]
    tickets.record_session(proj, tid, "agent", "s1", "host")
    entries = json.loads(p.read_text())
    assert len(entries) == 500
    assert entries[-1]["first_seen"] == first_seen
    assert (
        tickets.sessions_for(
            proj,
            tid,
            {"id": tid, "sessions": [{"id": "s0", "agent": "agent", "host": "host"}]},
            "agent",
            "host",
        )
        is None
    )


def test_old_key_resolution(proj, new_ticket, run):
    from orch import config

    config.set_code(proj, "DM1")
    for _ in range(12):
        tickets.next_key(proj)
    tid = new_ticket()
    t = tickets.load(proj, tid)
    t["key"] = "DM1-15"
    t["ext"] = {"sync": {"old_keys": ["DM1-13"]}}
    tickets.save(proj, t)
    notices = []
    assert tickets.resolve(proj, "dm1-13", follow_moved=True, notice=notices.append) == tid
    assert notices == ["DM1-13 moved to DM1-15"]
    code, _, err = run("ticket", "show", "DM1-13")
    assert code == 0
    assert "DM1-13 moved to DM1-15" in err
    from orch.errors import Refused

    with pytest.raises(Refused, match="doesn't exist"):
        tickets.resolve(proj, "DM1-13", notice=notices.append)
    for args in [("show", "DM1-13"), ("set", "DM1-13", "title", "Must not change")]:
        code, out, err = run("ticket", *args, "--json")
        assert code == 2
        assert json.loads(out)["error"] == "DM1-13 moved to DM1-15; use DM1-15"
        assert "DM1-13 moved to DM1-15; use DM1-15" in err
    assert tickets.load(proj, tid) == t

    with pytest.raises(Refused, match="doesn't exist"):
        tickets.resolve(proj / "other", "DM1-13", follow_moved=True)
    other = new_ticket()
    t2 = tickets.load(proj, other)
    t2["key"] = "DM1-13"
    tickets.save(proj, t2)
    notices.clear()
    assert tickets.resolve(proj, "DM1-13", follow_moved=True, notice=notices.append) == other
    assert notices == []
    t2["key"] = "DM1-16"
    t2["ext"] = {"sync": {"old_keys": ["DM1-13"]}}
    tickets.save(proj, t2)
    with pytest.raises(Refused, match="DM1-15, DM1-16"):
        tickets.resolve(proj, "DM1-13", follow_moved=True)


def test_sessions_cannot_cross_tickets(proj, new_ticket):
    a, b = new_ticket(), new_ticket()
    tickets.record_session(proj, a, "agent", "local", "host")
    original = tickets.load(proj, a)
    copied = tickets.load(proj, b)
    copied["sessions"] = original["sessions"]
    tickets.save(proj, copied)
    assert tickets.sessions_for(proj, b, tickets.load(proj, b), "agent", "host") is None
    assert tickets.sessions_for(proj, a, original, "agent", "host") == "local"


@pytest.mark.parametrize("embedded_id", ["other", None])
def test_sessions_spoofed_ticket_id_refused(proj, new_ticket, embedded_id):
    from orch.errors import Refused

    a, b = new_ticket(), new_ticket()
    original = tickets.record_session(proj, a, "agent", "local", "host")
    copied = tickets.load(proj, b)
    key = copied["key"]
    copied["sessions"] = original["sessions"]
    if embedded_id == "other":
        copied["id"] = a
    else:
        del copied["id"]
    path = tickets.ticket_path(proj, b)
    contents = json.dumps(copied)
    path.write_text(contents, encoding="utf-8")

    # Even a caller holding unvalidated peer JSON must use the trusted file id.
    assert tickets.sessions_for(proj, b, copied, "agent", "host") is None
    with pytest.raises(Refused, match="id does not match its filename"):
        tickets.load(proj, b)
    assert tickets.list_all(proj) == [original]
    with pytest.raises(Refused, match="doesn't exist"):
        tickets.resolve(proj, key)
    assert path.read_text(encoding="utf-8") == contents
    assert tickets.load(proj, a) == original
    assert tickets.sessions_for(proj, a, original, "agent", "host") == "local"


def test_sessions_legacy_record_fails_closed(proj, new_ticket):
    tid = new_ticket()
    ticket = tickets.record_session(proj, tid, "agent", "local", "host")
    p = proj / ".orch" / "run" / "own-sessions.json"
    entries = json.loads(p.read_text())
    del entries[0]["ticket_id"]
    p.write_text(json.dumps(entries))
    assert tickets.sessions_for(proj, tid, ticket, "agent", "host") is None
    tickets.record_session(proj, tid, "agent", "local", "host")
    assert tickets.sessions_for(proj, tid, ticket, "agent", "host") == "local"


@pytest.mark.parametrize("alias", ["DM1-2", "AB-1"])
def test_old_key_unissued_or_other_prefix_refused(proj, new_ticket, alias):
    from orch import config
    from orch.errors import Refused

    config.set_code(proj, "DM1")
    tid = new_ticket()
    t = tickets.load(proj, tid)
    t["key"] = "DM1-15"
    t["ext"] = {"sync": {"old_keys": [alias]}}
    tickets.save(proj, t)
    notices = []
    with pytest.raises(Refused, match="doesn't exist"):
        tickets.resolve(proj, alias, follow_moved=True, notice=notices.append)
    assert notices == []


@pytest.mark.parametrize("general", [False, True])
def test_pre_ownership_sessions_adopted_once(proj, new_ticket, general):
    from orch import runs

    tid = new_ticket()
    ticket = tickets.load(proj, tid)
    ticket.update(general=general, sessions=[{"id": "old-local", "agent": "agent", "host": runs.host()}])
    tickets.save(proj, ticket)
    record = proj / ".orch" / "run" / "own-sessions.json"
    marker = record.with_name("own-sessions.adopted")
    assert not record.exists()
    assert tickets.sessions_for(proj, tid, ticket, "agent", runs.host()) == "old-local"
    entries = json.loads(record.read_text())
    assert len(entries) == 1
    assert entries[0] == {
        "id": "old-local",
        "agent": "agent",
        "host": runs.host(),
        "ticket_id": tid,
        "first_seen": entries[0]["first_seen"],
    }
    assert entries[0]["first_seen"]
    assert json.loads(marker.read_text()) == {"adopted": True}
    record.unlink()
    assert tickets.sessions_for(proj, tid, ticket, "agent", runs.host()) is None
    assert marker.exists()
    assert not record.exists()


def test_adoption_skips_foreign_malformed_and_mismatched_tickets(proj, new_ticket):
    from orch import runs

    tid, mismatch, malformed = (new_ticket() for _ in range(3))
    ticket = tickets.load(proj, tid)
    ticket["sessions"] = [
        {"id": "foreign", "agent": "agent", "host": runs.host() + "-other"},
        None,
        "session",
        {"id": [], "agent": "agent", "host": runs.host()},
        {"id": "missing-agent", "host": runs.host()},
        {"id": "empty-agent", "agent": "", "host": runs.host()},
        {"id": "missing-host", "agent": "agent"},
    ]
    tickets.save(proj, ticket)
    bad = tickets.load(proj, mismatch)
    bad.update(id=tid, sessions=[{"id": "copied", "agent": "agent", "host": runs.host()}])
    tickets.ticket_path(proj, mismatch).write_text(json.dumps(bad))
    bad = tickets.load(proj, malformed)
    bad["sessions"] = {"id": "not-a-list", "agent": "agent", "host": runs.host()}
    tickets.save(proj, bad)
    assert tickets._own_sessions(proj) == []
    assert (proj / ".orch" / "run" / "own-sessions.adopted").exists()


def test_adoption_serializes_with_record_session(proj, new_ticket, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from orch import runs
    from orch.errors import Refused

    tid = new_ticket()
    ticket = tickets.load(proj, tid)
    ticket["sessions"] = [{"id": "old", "agent": "agent", "host": runs.host()}]
    tickets.save(proj, ticket)
    adopting, release, recording = Event(), Event(), Event()
    write_json = tickets.net.write_json

    def paused_write(path, obj, *args, **kwargs):
        if path.name == "own-sessions.adopted":
            adopting.set()
            assert release.wait(5)
        return write_json(path, obj, *args, **kwargs)

    def record():
        recording.set()
        tickets.record_session(proj, tid, "agent", "new", runs.host())

    monkeypatch.setattr(tickets.net, "write_json", paused_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        adoption = pool.submit(tickets._own_sessions, proj)
        try:
            assert adopting.wait(5)
            writer = pool.submit(record)
            assert recording.wait(5)
            with pytest.raises(Refused):
                with tickets._locked(proj, "own-sessions", wait=0):
                    pass
            assert not writer.done()
        finally:
            release.set()
        adoption.result(timeout=5)
        writer.result(timeout=5)
    assert {s["id"] for s in tickets._own_sessions(proj)} == {"old", "new"}
    assert tickets.sessions_for(proj, tid, tickets.load(proj, tid), "agent", runs.host()) == "new"

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
    assert tickets.sessions_for(t, "my-agent", "laptop") == "s-2"
    assert tickets.sessions_for(t, "my-agent", "vps") == "s-1"
    assert tickets.sessions_for(t, "other", "laptop") is None
    assert tickets.sessions_for(t, "my-agent", "elsewhere") is None
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
    t = read(proj, tid)
    t["status"] = "done"
    (proj / ".orch" / "tickets" / f"{tid}.json").write_text(json.dumps(t), encoding="utf-8")
    assert "Changed: Added CSV export." in run("ticket", "show", tid)[1]

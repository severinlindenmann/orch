"""The "run this" card (ORCH-848): `orch ask --run`, `orch review run`, and every refusal."""

import json
from pathlib import Path

import pytest

from orch import review, runcard, tickets
from orch.errors import Refused

ME = "human:pat"


@pytest.fixture
def tk(proj, run):
    code, out, _ = run("ticket", "new", "Turn on release walks", "--json", "--by", "agent:x")
    assert code == 0
    return proj, json.loads(out)["id"]


def _ask(run, tid, command, *extra, by="agent:x"):
    return run("ask", tid, f"Run {command[:40]}?", "--run", command, *extra, "--json", "--by", by)


def _card(run, tid, command, *extra):
    code, out, err = _ask(run, tid, command, *extra)
    assert code == 0, out + err
    return json.loads(out)


def _q(root, tid, qid):
    return next(x for x in tickets.load(root, tid)["questions"] if x["id"] == qid)


def _digest(root, tid, qid):
    return tickets.question_digest(_q(root, tid, qid))


def _run_card(run, root, tid, qid, *extra, digest=None, by=ME):
    return run("review", "run", tid, qid, "--digest", digest or _digest(root, tid, qid), *extra, "--json",
               "--by", by)  # fmt: skip


# ------------------------------------------------------------------ making the card


def test_orch_setting_card_carries_orchs_own_words(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on", "--option", "Leave it off for now")
    card = q["card"]
    assert card["kind"] == "run" and card["ok_label"] == "I ran it"
    assert card["no_label"] == "Leave it off for now"
    spec = card["run"]
    assert spec["class"] == "orch" and spec["op"] == {"verb": "config.set", "key": "workflow.reviewer_look",
                                                      "value": "on"}  # fmt: skip
    assert spec["changes"] == "The Reviewer gives bigger finished work a second look"
    assert spec["undo"] == "orch config set workflow.reviewer_look off"
    assert spec["cwd"] == str(Path(root).resolve())


def test_the_helper_cannot_put_its_own_words_on_an_orch_card(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer on", "--changes", "Nothing at all")
    assert q["card"]["run"]["changes"] == "The Reviewer accepts small finished work for you"


@pytest.mark.parametrize(
    "command, words",
    [
        ("orch config set workspace.agent codex", "cannot run from a card"),
        ("orch config set workflow.reviewer maybe", "takes on or off"),
        ("orch config set workflow.reviewer on --by human:x", "cannot run from a card"),
        ("orch ticket new hello", "cannot run from a card"),
        ("/tmp/orch config set workflow.reviewer on", "by its name"),
        ("orch config set workflow.reviewer on; rm -rf ~", "no shell operators"),
        ("orch config set workflow.reviewer on && true", "no shell operators"),
        ("echo $(whoami)", "no shell operators"),
        ("ls | wc", "no shell operators"),
        ("echo hi > out.txt", "no shell operators"),
        ("echo 'open", "do not close"),
        ("echo a\nb", "control character"),
        ("echo ‮hello", "control character"),
        ("FOO=1 true", "No settings before"),
        ("sudo true", "does not run sudo"),
        ("env true", "does not run env"),
        ("bash -c true", "does not run bash"),
        ("python3 -c 'print(1)'", "does not run python3"),
        ("x" * 301, "at most 300"),
        ("no-such-program-848", "not installed"),
        ("echo AKIAIOSFODNN7EXAMPLE", "password or key"),
        ("git -c core.pager=x log", "does not run git"),
        ("find . -exec true", "does not run find"),
        ("ls -c", "starts another program"),
        ("ls -exec", "starts another program"),
        ("ls a!b", "starts another program"),
    ],
)
def test_refused_when_the_card_is_made(tk, run, command, words):
    _root, tid = tk
    code, out, err = _ask(run, tid, command, "--changes", "Something")
    assert code == 2 and words in (out + err), out + err


def test_a_command_that_is_not_orch_needs_its_change_line(tk, run):
    _root, tid = tk
    code, out, err = _ask(run, tid, "true")
    assert code == 2 and "what it changes" in out + err
    q = _card(run, tid, "true", "--changes", "Nothing", "--undo", "Nothing to undo")
    assert q["card"]["run"]["class"] == "other" and q["card"]["run"]["exe"].endswith("/true")


def test_a_program_inside_the_workspace_is_refused(tk, run):
    root, tid = tk
    tool = Path(root) / "tool.sh"
    tool.write_text("#!/bin/sh\necho hi\n")
    tool.chmod(0o755)
    code, out, err = _ask(run, tid, str(tool), "--changes", "Says hi")
    assert code == 2 and "work or temp folder" in out + err


def test_login_commands_are_marked_and_never_run_here(tk, run, person_grant):
    root, tid = tk
    q = _card(run, tid, "codex login")
    assert q["card"]["run"]["class"] == "login"
    person_grant(root)
    code, out, err = _run_card(run, root, tid, q["id"])
    assert code == 2 and "needs a terminal" in out + err
    assert _q(root, tid, q["id"])["answer"] is None


# ------------------------------------------------------------------ running it


def test_the_person_runs_it_and_the_card_answers_itself(tk, run, person_grant):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on", "--option", "Leave it off for now")
    person_grant(root)
    code, out, err = _run_card(run, root, tid, q["id"])
    assert code == 0, out + err
    res = json.loads(out)
    assert res["ok"] and res["answered"]
    done = _q(root, tid, q["id"])
    assert done["answer"] == "I ran it" and done["answered_by"] == ME
    assert done["decision"]["ran"]["exit"] == 0
    from orch import config

    assert config.reviewer_look_on(Path(root))
    log = (Path(root) / ".orch" / "logs" / "card-runs.jsonl").read_text().splitlines()
    assert json.loads(log[-1])["ok"] is True and json.loads(log[-1])["by"] == ME


def test_a_failure_leaves_the_card_open_with_the_error(tk, run, person_grant):
    root, tid = tk
    q = _card(run, tid, "false", "--changes", "Nothing")
    person_grant(root)
    code, out, _ = _run_card(run, root, tid, q["id"], "--confirmed")
    assert code == 1
    res = json.loads(out)
    assert res["ok"] is False and res["exit"] == 1 and "exit code 1" in res["error"]
    assert _q(root, tid, q["id"])["answer"] is None
    assert tickets.load(root, tid)["ext"]["runcard"][q["id"]]["exit"] == 1


def test_other_commands_need_the_confirm(tk, run, person_grant):
    root, tid = tk
    q = _card(run, tid, "echo hello", "--changes", "Says hello")
    person_grant(root)
    code, out, err = _run_card(run, root, tid, q["id"])
    assert code == 2 and "confirm it first" in out + err
    person_grant(root)
    code, out, _ = _run_card(run, root, tid, q["id"], "--confirmed")
    assert code == 0 and json.loads(out)["output"].strip() == "hello"


# ------------------------------------------------------------------ who may run it


def test_no_grant_no_run(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    code, out, err = _run_card(run, root, tid, q["id"])
    assert code == 2 and "Only the signed-in person" in out + err
    assert _q(root, tid, q["id"])["answer"] is None


def test_a_helper_with_a_grant_is_still_refused(tk, run, person_grant):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    person_grant(root)
    code, out, err = _run_card(run, root, tid, q["id"], by="agent:claude")
    assert code == 2 and "Only the signed-in person" in out + err


def test_a_helper_environment_is_refused(tk, run, person_grant, monkeypatch):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    person_grant(root)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, err = _run_card(run, root, tid, q["id"])
    assert code == 2


def test_review_answer_ok_never_answers_i_ran_it(tk, run, person_grant):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    person_grant(root)
    code, out, err = run("review", "answer", tid, q["id"], "--verdict", "ok", "--digest",
                         _digest(root, tid, q["id"]), "--json", "--by", ME)  # fmt: skip
    assert code == 2 and "click Run it now" in out + err
    assert _q(root, tid, q["id"])["answer"] is None


def test_plain_answer_cannot_claim_it_ran(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on", "--option", "Leave it off for now")
    code, out, err = run("answer", tid, q["id"], "I ran it", "--by", ME)
    assert code == 2 and "click Run it now" in out + err
    with pytest.raises(Refused):
        tickets.answer(Path(root), tid, q["id"], "yes", ME, "dashboard", person=True)


def test_the_other_answer_still_works(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on", "--option", "Leave it off for now")
    code, out, err = run("review", "answer", tid, q["id"], "--verdict", "no", "--digest",
                         _digest(root, tid, q["id"]), "--json", "--by", ME)  # fmt: skip
    assert code == 0, out + err
    assert _q(root, tid, q["id"])["answer"]


def test_the_reviewer_routine_answer_cannot_run_it(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    with pytest.raises(Refused):
        tickets.answer_for_owner(Path(root), tid, q["id"], _digest(root, tid, q["id"]), "routine")
    assert _q(root, tid, q["id"])["answer"] is None


def test_review_decide_refuses_ok_for_everyone(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    with pytest.raises(Refused):
        review.decide(Path(root), tid, q["id"], "ok", by=ME, via="phone", person=True)


# ------------------------------------------------------------------ the command shown is the command run


def test_a_changed_card_is_refused(tk, run, person_grant):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    shown = _digest(root, tid, q["id"])

    def swap(t):
        qq = next(x for x in t["questions"] if x["id"] == q["id"])
        qq["card"]["run"]["argv"] = ["orch", "config", "set", "workflow.release_merge", "on"]

    tickets.apply_op(Path(root), tid, swap, by="agent:x")
    person_grant(root)
    code, out, err = _run_card(run, root, tid, q["id"], digest=shown)
    assert code == 2 and "changed after you saw it" in out + err


def test_a_hand_edited_spec_with_a_fresh_digest_is_refused(tk, run, person_grant):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")

    def swap(t):
        qq = next(x for x in t["questions"] if x["id"] == q["id"])
        qq["card"]["run"]["argv"] = ["orch", "config", "set", "workflow.release_merge", "on"]

    tickets.apply_op(Path(root), tid, swap, by="agent:x")
    person_grant(root)
    code, out, err = _run_card(run, root, tid, q["id"])  # the digest of the edited card
    assert code == 2 and "does not match its command" in out + err


def test_an_older_policy_is_refused(tk, run, person_grant):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")

    def old(t):
        next(x for x in t["questions"] if x["id"] == q["id"])["card"]["run"]["v"] = 0

    tickets.apply_op(Path(root), tid, old, by="agent:x")
    person_grant(root)
    code, out, err = _run_card(run, root, tid, q["id"])
    assert code == 2 and "older rules" in out + err


def test_an_answered_card_does_not_run_again(tk, run, person_grant):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    person_grant(root)
    assert _run_card(run, root, tid, q["id"])[0] == 0
    person_grant(root)
    code, out, err = _run_card(run, root, tid, q["id"])
    assert code == 2 and "answered already" in out + err


def test_two_runs_at_once_are_refused(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    with runcard._Lock(Path(root), tid, q["id"]), pytest.raises(Refused, match="running already"):
        runcard.run(Path(root), tid, q["id"], _digest(root, tid, q["id"]), by=ME, person=True)


# ------------------------------------------------------------------ phone, output, timeout


def test_the_phone_runs_only_orchs_own_operations(tk, run):
    root, tid = tk
    q = _card(run, tid, "echo hello", "--changes", "Says hello")
    assert not runcard.phone_ok(_q(root, tid, q["id"]))
    with pytest.raises(Refused, match="phone runs only orch"):
        runcard.run(Path(root), tid, q["id"], _digest(root, tid, q["id"]), by=ME, person=True, via="phone",
                    confirmed=True)  # fmt: skip
    q2 = _card(run, tid, "orch config set workflow.reviewer_look on")
    assert runcard.phone_ok(_q(root, tid, q2["id"]))
    res = runcard.run(
        Path(root), tid, q2["id"], _digest(root, tid, q2["id"]), by=ME, person=True, via="phone"
    )
    assert res["ok"]


def test_a_secret_in_the_output_is_hidden(tk, run):
    root, tid = tk
    (Path(root) / "k.txt").write_text("key AKIAIOSFODNN7EXAMPLE\n")
    q = _card(run, tid, "cat k.txt", "--changes", "Prints a key")
    res = runcard.run(
        Path(root), tid, q["id"], _digest(root, tid, q["id"]), by=ME, person=True, confirmed=True
    )
    assert "AKIA" not in res["output"] and "hidden" in res["output"]
    assert "AKIA" not in json.dumps(tickets.load(root, tid))


def test_a_slow_command_is_stopped_and_stays_open(tk, run):
    root, tid = tk
    q = _card(run, tid, "sleep 30", "--changes", "Waits")
    d = _digest(root, tid, q["id"])
    res = runcard.run(Path(root), tid, q["id"], d, by=ME, person=True, confirmed=True,
                      timeout=1)  # fmt: skip
    assert res["ok"] is False and res["exit"] is None and "may have run partly" in res["error"]
    assert _q(root, tid, q["id"])["answer"] is None


def test_a_refusal_is_logged(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    with pytest.raises(Refused):
        runcard.run(Path(root), tid, q["id"], _digest(root, tid, q["id"]), by=ME, person=False)
    row = json.loads((Path(root) / ".orch" / "logs" / "card-runs.jsonl").read_text().splitlines()[-1])
    assert "signed-in person" in row["refused"]


def test_hand_edited_words_on_an_orch_card_are_refused(tk, run, person_grant):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.release_merge on")

    def words(t):
        next(x for x in t["questions"] if x["id"] == q["id"])["card"]["run"]["changes"] = "Nothing happens"

    tickets.apply_op(Path(root), tid, words, by="agent:x")
    person_grant(root)
    code, out, err = _run_card(run, root, tid, q["id"])
    assert code == 2 and "does not match its command" in out + err
    assert _q(root, tid, q["id"])["answer"] is None

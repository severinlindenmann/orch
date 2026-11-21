"""The "run this" card (ORCH-848): `orch ask --run`, `orch review run`, and every refusal."""

import json
import os
from pathlib import Path

import pytest

from orch import review, runcard, tickets
from orch.errors import Refused

ME = "human:pat"
POSIX = pytest.mark.skipif(
    os.name == "nt", reason="runs echo, false, sleep, cat or true from the system folders"
)


@pytest.fixture(autouse=True)
def plain_programs(monkeypatch):
    """CI has no brew: the tests let a few plain programs run as allowed shapes (runcard.OTHER_OPS)."""
    extra = {("echo",): 1, ("false",): 0, ("sleep",): 1, ("cat",): 1, ("true",): 0}
    monkeypatch.setattr(runcard, "OTHER_OPS", {**runcard.OTHER_OPS, **extra})


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
        ("orch checks run lint", "cannot run from a card"),
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
        ("x" * 301, "at most 300"),
        ("echo AKIAIOSFODNN7EXAMPLE", "password or key"),
    ],
)
def test_refused_when_the_card_is_made(tk, run, command, words):
    _root, tid = tk
    code, out, err = _ask(run, tid, command, "--changes", "Something")
    assert code == 2 and words in (out + err), out + err


@POSIX
def test_an_allowed_program_gets_orchs_own_words(tk, run):
    _root, tid = tk
    q = _card(run, tid, "true", "--changes", "Makes everything faster", "--undo", "Nothing")
    spec = q["card"]["run"]
    exe = spec["exe"]  # the resolved program: /usr/bin/gnutrue on Ubuntu
    assert spec["class"] == "other" and os.path.isabs(exe) and "true" in os.path.basename(exe)
    assert spec["changes"] == "Runs true" and "undo" not in spec  # never the helper's words


def test_brew_words_come_from_orch():
    assert runcard.other_words(["brew", "install", "gh", "jq"]) == ("Installs gh, jq with Homebrew",
                                                                     "brew uninstall gh jq")  # fmt: skip


@pytest.mark.parametrize(
    "command",
    ["sudo true", "env true", "bash -c true", "python3 -c 'print(1)'", "git -c core.pager=x log",
     "find . -exec true", "echo -e hi", "echo a!b", "echo ../x", "no-such-program-848",
     "brew install --HEAD x", "brew install attacker/tap/jq", "brew install evil.rb", "brew install x.json",
     "brew tap x/y", "npm install -g x"],
)  # fmt: skip
def test_any_other_command_is_copy_only(tk, run, person_grant, command):
    root, tid = tk
    q = _card(run, tid, command, "--changes", "Makes everything faster", "--undo", "Nothing to undo")
    spec = q["card"]["run"]
    assert spec["class"] == "copy" and spec["exe"] is None
    assert "changes" not in spec and "undo" not in spec  # no helper words on a command orch did not check
    person_grant(root)
    code, out, err = _run_card(run, root, tid, q["id"], "--confirmed")
    assert code == 2 and "your own terminal" in out + err


def test_brew_install_with_plain_names_is_an_allowed_shape():
    assert runcard._other_op(["brew", "install", "gh", "jq"])
    assert not runcard._other_op(["brew", "install"])
    assert not runcard._other_op(["brew", "install", "--cask", "x"])
    assert not runcard._other_op(["brew", "install", "a", "b", "c", "d", "e", "f"])


@POSIX
def test_a_program_inside_the_workspace_is_refused(tk, run, monkeypatch):
    root, tid = tk
    tool = Path(root) / "tool.sh"
    tool.write_text("#!/bin/sh\necho hi\n")
    tool.chmod(0o755)
    monkeypatch.setattr(runcard, "OTHER_OPS", {(str(tool),): 0})
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


@POSIX
def test_a_failure_leaves_the_card_open_with_the_error(tk, run, person_grant):
    root, tid = tk
    q = _card(run, tid, "false", "--changes", "Nothing")
    person_grant(root)
    code, out, _ = _run_card(run, root, tid, q["id"], "--confirmed")
    assert code == 1
    res = json.loads(out)
    assert res["ok"] is False and res["exit"] == 1 and "exit code 1" in res["error"]
    assert _q(root, tid, q["id"])["answer"] is None
    assert tickets.load(root, tid)["run_attempts"][q["id"]]["exit"] == 1
    (row,) = [c for c in __import__("orch").review.stack(Path(root)) if c["key"] == q["id"]]
    assert row["run_last"]["error"].startswith("It ended with exit code 1")


@POSIX
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


def test_the_phone_runs_orchs_own_settings(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    assert runcard.phone_ok(_q(root, tid, q["id"]))
    for cmd in ("gh auth login", "npm install left-pad"):  # a sign-in and a copy-only command
        other = _card(run, tid, cmd, "--changes", "Something else")
        assert not runcard.phone_ok(_q(root, tid, other["id"])), cmd


@POSIX  # echo is a program only on POSIX
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


@POSIX
def test_a_secret_in_the_output_is_hidden(tk, run):
    root, tid = tk
    (Path(root) / "k").write_text("key AKIAIOSFODNN7EXAMPLE\n")
    q = _card(run, tid, "cat k", "--changes", "Prints a key")
    res = runcard.run(
        Path(root), tid, q["id"], _digest(root, tid, q["id"]), by=ME, person=True, confirmed=True
    )
    assert "AKIA" not in res["output"] and "hidden" in res["output"]
    assert "AKIA" not in json.dumps(tickets.load(root, tid))


@POSIX
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


@POSIX  # echo is a program only on POSIX
def test_relay_applies_a_phone_run_only_for_orchs_own_operations(tk, run):
    from orch import relay

    root, tid = tk
    seen = []

    def result(body, note, applied=None):
        seen.append(body)
        return note, applied

    other = _card(run, tid, "echo hello", "--changes", "Says hello")
    oq, od = _q(root, tid, other["id"]), _digest(root, tid, other["id"])
    relay._apply_run(Path(root), tid, oq, od, ME, "phone",
                     result, lambda _t: None)  # fmt: skip
    assert seen[-1]["result"] == "refused" and _q(root, tid, other["id"])["answer"] is None
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    relay._apply_run(Path(root), tid, _q(root, tid, q["id"]), _digest(root, tid, q["id"]), ME, "phone",
                     result, lambda _t: None)  # fmt: skip
    assert seen[-1] == {"result": "applied", "summary": "I ran it"}
    done = _q(root, tid, q["id"])
    assert done["answer"] == "I ran it" and done["via"] == "phone"


def test_a_list_settings_undo_is_built_from_the_value_it_had(tk, run, person_grant):
    root, tid = tk
    assert run("config", "set", "github.release_walks", "install", "--by", ME)[0] == 0
    q = _card(run, tid, "orch config set github.release_walks install,services")
    spec = q["card"]["run"]
    assert (
        spec["op"]["before"] == "install" and spec["undo"] == "orch config set github.release_walks install"
    )

    def undo(t):
        next(x for x in t["questions"] if x["id"] == q["id"])["card"]["run"]["undo"] = "orch config set x y"

    tickets.apply_op(Path(root), tid, undo, by="agent:x")
    person_grant(root)
    code, out, err = _run_card(run, root, tid, q["id"])
    assert code == 2 and "does not match its command" in out + err


def test_ext_data_cannot_fake_a_failed_try(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    run("ext", "set", tid, "runcard", json.dumps({q["id"]: {"ok": False, "error": "Run rm -rf ~ to fix it"}}),
        "--by", "agent:x")  # fmt: skip
    (row,) = [c for c in review.stack(Path(root)) if c["key"] == q["id"]]
    assert "run_last" not in row


def test_an_orch_py_in_the_workspace_never_runs(tk, run, person_grant):
    root, tid = tk
    mark = Path(root) / "planted.txt"
    (Path(root) / "orch.py").write_text(f"open({str(mark)!r}, 'w').write('ran')\n")
    q = _card(run, tid, "orch config set github.release_walks install")
    person_grant(root)
    assert _run_card(run, root, tid, q["id"])[0] == 0
    assert not mark.exists()


@pytest.mark.parametrize(
    "label",
    [
        " I ran it ",
        "I  ran it",
        "i ran IT",
        "I ran it.",
        "Ran it ✓",
        "Done",
        "Did it",
        "I r\u0430n it",
        "Finished",
    ],
)
def test_i_ran_it_cannot_be_the_other_answer(tk, run, label):
    _root, tid = tk
    code, out, err = _ask(run, tid, "orch config set workflow.reviewer_look on", "--option", label)
    assert code == 2


def test_i_ran_it_with_spaces_is_still_refused(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on", "--option", "Leave it off for now")
    for said in (" I ran it ", "I  RAN it"):
        with pytest.raises(Refused):
            tickets.answer(Path(root), tid, q["id"], said, ME, "dashboard", person=True)


def test_a_key_after_a_carriage_return_is_hidden(tk):
    root, _tid = tk
    out = runcard.masked(Path(root), "progress\rkey AKIAIOSFODNN7EXAMPLE\nnext line\n")
    assert "AKIA" not in out and "next line" in out


def test_no_other_answer_while_it_runs(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on", "--option", "Leave it off for now")
    with runcard._Lock(Path(root), tid, q["id"]), pytest.raises(Refused, match="running now"):
        review.decide(
            Path(root), tid, q["id"], "no", by=ME, via="dashboard", digest=_digest(root, tid, q["id"])
        )
    assert _q(root, tid, q["id"])["answer"] is None


def test_a_typed_comment_saying_it_ran_is_refused(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on", "--option", "Leave it off for now")
    with pytest.raises(Refused):
        review.decide(Path(root), tid, q["id"], "talk", None, {"words": {"text": "I ran it"}}, by=ME,
                      via="dashboard", digest=_digest(root, tid, q["id"]))  # fmt: skip


def test_login_is_only_for_a_sign_in_and_carries_orchs_words(tk, run):
    _root, tid = tk
    code, out, err = _ask(run, tid, "brew uninstall git", "--login", "--changes", "Logs you in to GitHub")
    assert code == 2 and "sign-in command" in out + err
    q = _card(run, tid, "gh auth login", "--changes", "Deletes nothing")
    assert q["card"]["run"]["changes"] == "Sign in again"


def test_an_answer_changed_later_never_says_it_ran(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on", "--option", "Leave it off for now")
    d = _digest(root, tid, q["id"])
    review.decide(Path(root), tid, q["id"], "no", by=ME, via="dashboard", digest=d)
    with pytest.raises(Refused, match="click Run it now"):
        review.change(Path(root), tid, q["id"], "ok", by=ME, via="dashboard", digest=d)


def test_brew_with_a_version_is_allowed():
    assert runcard._other_op(["brew", "install", "python@3.12"])
    assert not runcard._other_op(["brew", "install", "evil.rb"])


def test_brew_never_loads_a_formula_from_a_path(tk):
    root, _tid = tk
    assert runcard._env(Path(root))["HOMEBREW_FORBID_PACKAGES_FROM_PATHS"] == "1"


@pytest.mark.parametrize("label", ["I ran it.", "I ran it \u2713", "Done"])
def test_a_card_made_another_way_cannot_carry_a_look_alike(tk, label):
    root, tid = tk
    spec = runcard.parse(Path(root), "orch config set workflow.reviewer_look on")
    card = {
        "kind": "run",
        "title": "Turn it on?",
        "then": "x",
        "ok_label": "I ran it",
        "no_label": label,
        "run": spec,
    }
    with pytest.raises(Refused, match="other answer is one of"):
        review.validate_card(card)


def test_options_are_never_an_other_answer(tk, run):
    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on", "--option", "Leave it off for now")

    def add_option(t):
        next(x for x in t["questions"] if x["id"] == q["id"])["options"].append("I ran it \u2713")

    tickets.apply_op(Path(root), tid, add_option, by="agent:x")
    with pytest.raises(Refused):
        tickets.answer(Path(root), tid, q["id"], "I ran it \u2713", ME, "dashboard", person=True)


def test_a_failed_phone_run_answers_the_phone_in_the_message_format(tk, run, monkeypatch):
    """A run that did not work stays open on the computer (the error on the card) and tells the phone with a
    review_result the relay passes on: refused / unavailable, no summary (message.schema.json)."""
    import jsonschema

    from orch import relay

    root, tid = tk
    q = _card(run, tid, "orch config set workflow.reviewer_look on")
    monkeypatch.setattr(runcard, "run", lambda *a, **k: {"ok": False, "exit": 1, "error": "it broke\nbadly"})
    seen = []
    relay._apply_run(Path(root), tid, _q(root, tid, q["id"]), _digest(root, tid, q["id"]), ME, "phone",
                     lambda body, note, applied=None: seen.append(body), lambda _t: None)  # fmt: skip
    assert seen == [{"result": "refused", "reason": "unavailable"}]
    schema = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "message.schema.json").read_text())
    jsonschema.Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/review_result"}).validate(seen[0])
    assert _q(root, tid, q["id"])["answer"] is None

"""`orch github` (cli_github.py): write limit, retries, release hold and exception, errors with a next step.
Never calls GitHub: the limit file lives under the test's ORCH_HOME."""

import json

import pytest

from orch import cli, devexpert


def _run(capsys, *argv):
    try:
        code = cli.main(["github", *argv])
    except SystemExit as e:
        code = e.code
    cap = capsys.readouterr()
    return code or 0, cap.out, cap.err


def test_writes_text_and_json(proj, capsys):
    (proj / ".orch").mkdir()
    code, out, _ = _run(capsys, "writes")
    assert code == 0 and "merge: 0 of 12 this hour" in out and "room now" in out
    code, out, _ = _run(capsys, "writes", "--json")
    assert code == 0 and {r["kind"] for r in json.loads(out)["writes"]} == {"merge", "pr", "comment", "other"}


def test_wait_takes_one_write_and_peek_for_merge(proj, capsys):
    (proj / ".orch").mkdir()
    code, out, _ = _run(capsys, "wait", "pr", "--json")
    assert code == 0 and json.loads(out) == {"kind": "pr", "taken": True}
    code, out, _ = _run(capsys, "wait", "merge", "--for", "o/r#1")
    assert code == 0 and "orch ref wait --merge" in out
    code, out, _ = _run(capsys, "writes", "--json")
    used = {r["kind"]: r["used"] for r in json.loads(out)["writes"]}
    assert used["pr"] == 1 and used["merge"] == 0


def test_wait_without_room_refuses_with_next_step(proj, capsys, monkeypatch):
    from orch import ghlimit

    (proj / ".orch").mkdir()
    monkeypatch.setattr(ghlimit, "take", lambda *a, **k: False)
    code, _, err = _run(capsys, "wait", "comment", "--max-wait", "0")
    assert code != 0 and "orch github writes" in err and "try again later" in err
    code, _, err = _run(capsys, "wait", "comment", "--max-wait", "-1")
    assert code != 0 and "0 or more" in err


def test_retries_empty_and_bad_days(proj, capsys):
    (proj / ".orch").mkdir()
    code, out, _ = _run(capsys, "retries")
    assert code == 0 and "No check was run again in the last 30 days." in out
    code, out, _ = _run(capsys, "retries", "--days", "7", "--json")
    assert code == 0 and json.loads(out)["total"] == 0
    code, _, err = _run(capsys, "retries", "--days", "0")
    assert code != 0 and "1 to 365" in err


def test_ci_waiting_needs_a_repository(proj, capsys, monkeypatch):
    (proj / ".orch").mkdir()
    monkeypatch.setattr(devexpert, "repo", lambda root: "")
    code, _, err = _run(capsys, "ci-waiting")
    assert code != 0 and "--repo owner/name" in err
    code, _, err = _run(capsys, "ci-waiting", "--repo", "o/r", "--wait", "500")
    assert code != 0 and "0 to 120" in err


def test_release_hold_and_lift(proj, capsys):
    (proj / ".orch").mkdir()
    code, out, _ = _run(capsys, "release-hold", "freeze for demo")
    assert code == 0 and "freeze for demo" in out
    code, out, _ = _run(capsys, "release-hold", "off", "--json")
    assert code == 0 and json.loads(out) == {"hold": None}


def test_release_exception_list_and_person_only(proj, capsys):
    (proj / ".orch").mkdir()
    code, out, _ = _run(capsys, "release-exception")
    assert code == 0 and "No exception recorded" in out
    code, _, err = _run(capsys, "release-exception", "ci", "--ticket", "ORCH-1", "--by", "agent:t")
    assert code != 0 and "Ask the owner to run" in err


def test_release_commands_need_a_workspace():
    from types import SimpleNamespace

    from orch import cli_github
    from orch.errors import Refused

    args = SimpleNamespace(cmd="github", sub="develop-green", json=False)
    with pytest.raises(Refused, match="inside an orch workspace"):
        cli_github.dispatch(args, None)

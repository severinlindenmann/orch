"""Does everything a helper needs still work (health.py, `orch logins`): a few facts and nothing else."""

import json
import os
import subprocess
from datetime import UTC, datetime

import pytest

from orch import adapters, cli_health, health, keystore, runs
from orch.errors import Refused

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
CLAUDE = {"command": ["claude", "auth", "status", "--json"], "works": "loggedIn", "ends": "loginExpiresAt"}
HIDDEN = "other-text-of-the-answer-that-must-not-appear"


def _answers(monkeypatch, stdout, seen=None, code=0):
    def fake(argv, **kw):
        if seen is not None:
            seen.append((argv, kw))
        return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr=HIDDEN)

    monkeypatch.setattr(health.subprocess, "run", fake)


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ("2026-11-17T21:24:57.990Z", "2026-11-17T21:24:57Z"),
        ("2026-11-17T22:24:57+01:00", "2026-11-17T21:24:57Z"),
        ("2026-11-17T21:24:57", "2026-11-17T21:24:57Z"),
        (1794950697, "2026-11-17T21:24:57Z"),
        (1794950697990, "2026-11-17T21:24:57Z"),
        (HIDDEN, None),
        ("x" * 41, None),
        (True, None),
        (None, None),
        ({"a": 1}, None),
    ],
)
def test_end_is_a_real_time_or_nothing(value, want):
    assert health._end(value) == want


@pytest.mark.parametrize(
    ("works", "ends", "want"),
    [
        (True, "2026-11-30T00:00:00Z", "works"),
        (True, None, "works"),
        (True, "2026-11-19T12:00:00Z", "soon"),  # exactly WARN_DAYS ahead
        (True, "2026-11-19T12:00:01Z", "works"),
        (True, "2026-11-16T12:00:00Z", "renew"),
        (False, "2026-11-30T00:00:00Z", "renew"),
        (False, None, "renew"),
        (None, None, "unreachable"),
        (None, "2026-11-17T00:00:00Z", "soon"),
    ],
)
def test_state(works, ends, want):
    assert health.state(works, ends, NOW) == want
    assert want in health.STATES


def test_ask_keeps_two_facts_and_runs_the_fixed_command(monkeypatch):
    seen = []
    doc = {
        "loggedIn": True,
        "loginExpiresAt": "2026-11-17T21:24:57.990Z",
        "email": "a@b.example",
        "other": HIDDEN,
    }
    _answers(monkeypatch, json.dumps(doc), seen)
    assert health.ask("/bin/claude", CLAUDE) == (True, "2026-11-17T21:24:57Z")
    argv, kw = seen[0]
    assert argv == ["/bin/claude", "auth", "status", "--json"]
    assert kw["stdin"] == subprocess.DEVNULL and kw["timeout"] == health.TIMEOUT
    assert kw["stderr"] == subprocess.DEVNULL  # error text is never read


@pytest.mark.parametrize("stdout", ["", "not json", "[1]", '"text"', json.dumps({"loggedIn": "yes"})])
def test_ask_unreadable_answer_is_unreachable(monkeypatch, stdout):
    _answers(monkeypatch, stdout)
    assert health.ask("/bin/claude", CLAUDE) == (None, None)


def test_ask_survives_a_tool_that_fails(monkeypatch):
    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(health.subprocess, "run", boom)
    assert health.ask("/bin/claude", CLAUDE) == (None, None)


def test_tool_without_end_field(monkeypatch):
    _answers(monkeypatch, json.dumps({"loggedIn": True}))
    assert health.ask("/bin/t", {"command": ["t", "status"], "works": "loggedIn", "ends": None}) == (
        True,
        None,
    )


@pytest.mark.parametrize(("code", "want"), [(0, True), (1, False), (4, False)])
def test_exit_code_recipe_reads_nothing_the_command_prints(monkeypatch, code, want):
    seen = []
    _answers(monkeypatch, HIDDEN, seen, code)
    assert health.ask("/bin/gh", {"command": ["gh", "auth", "status"], "works": None}) == (want, None)
    assert seen[0][1]["stdout"] == subprocess.DEVNULL and seen[0][1]["stderr"] == subprocess.DEVNULL


@pytest.mark.parametrize(
    ("name", "doc", "ok"),
    [
        ("databricks", {"label": "databricks", "command": ["databricks", "auth", "describe"]}, True),
        ("gh", {"command": ["gh", "auth", "status", "--hostname=github.com"]}, True),
        ("t", {"command": ["t", "s"], "works": "ok", "ends": "until"}, True),
        ("t", {"command": ["t", "s"], "ends": "until"}, False),  # an end time needs a JSON answer
        ("t", {"command": ["/usr/bin/t"]}, False),  # a bare tool name, found on PATH
        ("t", {"command": ["t", "$(rm -rf x)"]}, False),
        ("t", {"command": ["t", "a b"]}, False),
        ("t", {"command": "t status"}, False),
        ("t", {"command": ["bash", "-c", "x"]}, False),  # never a shell or a script runner
        ("t", {"command": ["python3", "x.py"]}, False),
        ("t", {"command": ["PowerShell.exe", "x"]}, False),
        ("t", {"command": ["python3.12", "x.py"]}, False),
        ("t", {"command": ["bash5", "x"]}, False),
        ("t", {"command": ["git", "status"]}, False),
        ("t", {"command": ["timeout", "5", "x"]}, False),
        ("t", {"command": ["databricks2", "auth", "describe"]}, True),
        ("t", {"command": []}, False),
        ("t", {"command": ["t"] * 10}, False),
        ("T!", {"command": ["t"]}, False),
        ("t", {"command": ["t"], "label": "x\nInjected"}, False),
        ("t", {"command": ["t"], "works": "a.b"}, False),
        ("wiki", {"command": ["t"], "kind": "connection"}, True),
        ("pay", {"command": ["t"], "kind": "key"}, True),
        ("t", {"command": ["t"], "kind": "secret"}, False),  # only login, connection or key
    ],
)
def test_workspace_recipe_shape(name, doc, ok):
    assert (health._recipe(name, doc) is not None) == ok


def _own(proj, checks):
    keystore.record_write(proj, "checks", {"checks": checks})


@pytest.fixture
def tools(monkeypatch):
    """claude and gh look installed; claude answers box["doc"], gh exits box["gh"]."""
    box = {"doc": {"loggedIn": True, "loginExpiresAt": "2026-11-17T21:24:57.990Z", "other": HIDDEN}, "gh": 0}
    monkeypatch.setattr(health.shutil, "which", lambda b: f"/bin/{b}" if b in ("claude", "gh") else None)

    def fake(argv, **kw):
        if argv[0] == "/bin/gh":
            return subprocess.CompletedProcess(argv, box["gh"], stdout=None, stderr=None)
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(box["doc"]), stderr=HIDDEN)

    monkeypatch.setattr(health.subprocess, "run", fake)
    return box


def test_overview_names_the_tickets_that_stop_and_leaks_nothing(proj, run, new_ticket, tools):
    tid = new_ticket("Plan the newsletter")
    other = new_ticket("Idle one")
    runs.claim(proj, tid, "agent:scheduler", "claude", pid=os.getpid())
    rows = health.overview(proj, NOW)
    assert [r["name"] for r in rows] == ["claude"]
    r = rows[0]
    assert (r["state"], r["ends_at"], r["helper"]) == ("soon", "2026-11-17T21:24:57Z", "claude")
    assert [t["id"] for t in r["stops"]] == [tid] and other not in json.dumps(rows)
    assert r["stops"][0]["title"] == "Plan the newsletter"
    assert set(r) == {
        "name",
        "label",
        "kind",
        "state",
        "ends_at",
        "helper",
        "chosen",
        "stops",
        "renew",
        "key",
    }
    assert r["renew"] is True and r["key"] is None  # orch can start the Claude Code sign-in (ORCH-46)
    assert HIDDEN not in json.dumps(rows)


def test_workspace_recipes_join_and_never_replace_a_helper_tool(proj, tools):
    _own(
        proj,
        {
            "gh": {"label": "GitHub", "command": ["gh", "auth", "status"]},
            "databricks": {"command": ["databricks", "auth", "describe"]},
            "claude": {"command": ["gh", "x"]},
            "bad": {"command": ["/bin/sh", "-c", "x"]},
        },
    )
    tools["gh"] = 1
    rows = {r["name"]: r for r in health.overview(proj, NOW)}
    assert list(rows) == ["claude", "gh", "databricks"]
    assert rows["claude"]["helper"] == "claude" and rows["claude"]["state"] == "soon"
    assert (rows["gh"]["label"], rows["gh"]["state"], rows["gh"]["stops"]) == ("GitHub", "renew", [])
    assert rows["databricks"]["state"] == "unreachable"  # set here, but the tool is missing


def test_overview_skips_helper_tools_that_are_not_installed(proj, monkeypatch):
    monkeypatch.setattr(health.shutil, "which", lambda b: None)
    assert health.overview(proj, NOW) == []


def test_recipes_in_the_project_folder_are_never_run(proj, monkeypatch):
    """Only the guarded orch home counts: a recipe file that came with the project files is ignored."""
    monkeypatch.setattr(health.shutil, "which", lambda b: f"/bin/{b}")
    for rel in ("checks.json", "local/checks.json"):
        p = proj / ".orch" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"checks": {"x": {"command": ["x"]}}}), encoding="utf-8")
    assert health.workspace_recipes(proj) == []
    _own(proj, {"x": {"command": ["x"]}})
    assert [r["name"] for r in health.workspace_recipes(proj)] == ["x"]


def test_a_damaged_record_runs_nothing(proj, monkeypatch):
    def bad(root, record):
        raise Refused("A record in the orch folder is unreadable.")

    monkeypatch.setattr(keystore, "record_read", bad)
    assert health.workspace_recipes(proj) == []


def test_check_keeps_the_last_result(proj, tools):
    assert health.last(proj) is None
    doc = health.check(proj, NOW)
    assert doc["checked_at"] == "2026-11-16T12:00:00Z"
    assert health.last(proj) == doc
    assert HIDDEN not in health._path(proj).read_text(encoding="utf-8")


def test_command_text_and_json(proj, run, new_ticket, tools):
    tid = new_ticket("Plan the newsletter")
    runs.claim(proj, tid, "agent:scheduler", "claude", pid=os.getpid())
    tools["doc"] = {"loggedIn": False, "other": HIDDEN}
    code, out, err = run("logins")
    assert code == 0, err
    label = adapters.load("claude")["label"]
    assert out.startswith(f"The {label} login no longer works. The helper cannot go on with 1 ticket: ")
    assert "Plan the newsletter" in out and "Renew or Replace on the dashboard warning" in out + err
    assert HIDDEN not in out + err
    code, out, err = run("logins", "--json")
    doc = json.loads(out)
    assert code == 0 and doc["items"][0]["state"] == "renew" and HIDDEN not in out + err


def test_command_with_nothing_set(proj, run, monkeypatch):
    monkeypatch.setattr(health.shutil, "which", lambda b: None)
    code, out, err = run("logins")
    assert code == 0 and cli_health.NONE_SET in out


@pytest.mark.parametrize(
    ("row", "want"),
    [
        ({"state": "works", "ends_at": None, "stops": [], "chosen": True}, "The Tool login works."),
        (
            {"state": "renew", "ends_at": None, "stops": [], "chosen": False, "kind": "connection"},
            "The Tool connection no longer works. Renew it.",
        ),
        (
            {"state": "unreachable", "ends_at": None, "stops": [], "chosen": True},
            "Tool did not answer, so orch cannot tell whether its login works.",
        ),
        (
            {"state": "renew", "ends_at": None, "stops": [], "chosen": True},
            "The Tool login no longer works. No new work starts until it is renewed.",
        ),
        (
            {"state": "renew", "ends_at": None, "stops": [], "chosen": False},
            "The Tool login no longer works. Renew it.",
        ),
    ],
)
def test_line(row, want):
    assert cli_health.line({"label": "Tool", **row}) == want


def test_line_soon_names_the_time_and_the_tickets():
    stops = [{"key": "DM-1", "title": "A"}, {"key": "DM-2", "title": "B"}]
    row = {
        "label": "Tool",
        "state": "soon",
        "ends_at": "2030-01-05T10:00:00Z",
        "stops": stops,
        "chosen": False,
    }
    line = cli_health.line(row)
    assert line.startswith("The Tool login runs out ") and "5 Jan" in line
    assert line.endswith(" The helper then stops on 2 tickets: DM-1 A; DM-2 B.")


def test_line_ran_out_names_the_time():
    row = {"label": "Tool", "state": "renew", "ends_at": "2020-01-05T10:00:00Z", "stops": [], "chosen": False}
    line = cli_health.line(row)
    assert line.startswith("The Tool login ran out ") and "5 Jan" in line and line.endswith("Renew it.")


@pytest.fixture
def spawned(monkeypatch):
    """soon() may start a check: record it instead of running the real tools."""
    calls = []
    monkeypatch.delenv("ORCH_NO_HEALTH_CHECK", raising=False)
    monkeypatch.setattr(health.subprocess, "Popen", lambda argv, **kw: calls.append((argv, kw)))
    return calls


def test_soon_checks_again_only_when_stale_and_not_too_often(proj, tools, spawned):
    t0 = NOW.timestamp()
    assert health.soon(proj, now=t0) is True  # never checked
    assert health.soon(proj, now=t0 + 5) is False  # one background check at a time
    argv, kw = spawned[0]
    assert argv[-2:] == ["logins", "--json"] and kw["env"]["ORCH_ROOT"] == str(proj)
    assert kw["stdout"] == subprocess.DEVNULL and kw["stdin"] == subprocess.DEVNULL
    health.check(proj, NOW)  # the background check wrote its result
    later = t0 + health.ASK_EVERY + 1
    assert health.soon(proj, now=later) is False  # fresh result: nothing to do
    assert health.soon(proj, now=later, force=True) is True  # a helper failed for lack of a login
    assert health.soon(proj, now=t0 + health.CHECK_EVERY + 200) is True  # stale again
    assert len(spawned) == 3


def test_soon_is_off_in_tests_and_never_raises(proj, monkeypatch):
    monkeypatch.setenv("ORCH_NO_HEALTH_CHECK", "1")
    assert health.soon(proj, force=True) is False
    monkeypatch.delenv("ORCH_NO_HEALTH_CHECK")

    def boom(*a, **kw):
        raise OSError("no")

    monkeypatch.setattr(health.subprocess, "Popen", boom)
    assert health.soon(proj, force=True) is False


def test_a_failed_start_for_lack_of_a_login_checks_at_once(proj, monkeypatch):
    seen = []
    monkeypatch.setattr(health, "soon", lambda root, **kw: seen.append(kw))
    (proj / "start.log").write_text("Error: not logged in\n", encoding="utf-8")
    assert runs.start_failure_reason(proj, {"agent": "", "log": "start.log"}) == "no login"
    assert seen == [{"force": True}]


def test_a_recipe_is_a_login_unless_it_says_otherwise():
    assert health._recipe("t", {"command": ["t"]})["kind"] == "login"
    assert health._recipe("t", {"command": ["t"], "kind": "key"})["kind"] == "key"
    assert all(r["kind"] == "login" for r in health.helper_recipes())

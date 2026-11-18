"""Checks a workspace sets for itself (checkfiles.py, `orch checks`, ORCH-529)."""

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

from orch import checkfiles, health, keystore
from orch.errors import Refused

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
EXPIRED = {"altyca_test", "pilatus_hub_sbox"}  # profiles whose login ran out on this computer


@pytest.fixture
def databricks(monkeypatch, tmp_path):
    """Only databricks is installed and set up (~/.databrickscfg); a profile in EXPIRED fails; the old
    all-profiles command fails because altyca_test is expired. Records every command that ran."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".databrickscfg").write_text("x")
    monkeypatch.setenv("HOME", str(home))
    for k in ("DATABRICKS_CONFIG_FILE", "GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR", "AWS_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(health.shutil, "which", lambda b: f"/bin/{b}" if b == "databricks" else None)
    ran = []

    def fake(argv, **kw):
        ran.append(argv)
        if argv[1:3] == ["auth", "profiles"]:
            doc = {"profiles": [{"name": p, "valid": p not in EXPIRED} for p in ("dev", "altyca_test")]}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(doc), stderr=None)
        profile = argv[argv.index("--profile") + 1] if "--profile" in argv else ""
        return subprocess.CompletedProcess(argv, 1 if profile in EXPIRED else 0, stdout=None, stderr=None)

    monkeypatch.setattr(health.subprocess, "run", fake)
    return ran


def _write(proj, name, doc):
    d = checkfiles.folder(proj)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")


def _warnings(rows):
    return [r for r in rows if r["state"] != "works"]


# ------------------------------------------------------------------------------------------------ acceptance


def test_no_databricks_check_no_databricks_warning(proj, databricks):
    checkfiles.init(proj)
    rows = health.overview(proj, NOW)
    assert [r["name"] for r in rows] == [] and databricks == []  # nothing ran at all


def test_one_warning_per_expired_profile_naming_its_own_fix(proj, databricks):
    checkfiles.add_from_template(proj, "databricks", "pilatus_hub_dev")
    checkfiles.add_from_template(proj, "databricks", "pilatus_hub_sbox")
    rows = health.overview(proj, NOW)
    assert {r["name"] for r in rows} == {"databricks-pilatus-hub-dev", "databricks-pilatus-hub-sbox"}
    bad = _warnings(rows)
    assert len(bad) == 1  # an expired altyca_test says nothing
    assert bad[0]["state"] == "renew" and bad[0]["label"] == "Databricks pilatus_hub_sbox"
    assert bad[0]["sign_in"] == "databricks auth login --profile pilatus_hub_sbox"
    assert all("altyca_test" not in a for argv in databricks for a in argv)


def test_without_a_check_folder_the_old_checks_run_with_a_notice(proj, databricks):
    rows = health.overview(proj, NOW)
    assert [r["name"] for r in rows] == ["databricks"] and rows[0]["state"] == "renew"
    assert "orch checks init" in checkfiles.notice(proj)
    assert health.check(proj, NOW)["notice"] == checkfiles.notice(proj)
    checkfiles.init(proj)
    assert checkfiles.notice(proj) is None and health.overview(proj, NOW) == []


# ------------------------------------------------------------------------------------------------ approval


def test_a_new_check_file_runs_only_after_approval(proj, databricks):
    doc = {"label": "Databricks dev", "command": ["databricks", "current-user", "me", "--profile", "dev"]}
    _write(proj, "db-dev", doc)
    rows = health.overview(proj, NOW)
    assert databricks == []  # nothing ran
    assert rows[0]["approve"] == "new" and rows[0]["sign_in"] == "orch checks approve db-dev"
    checkfiles.approve(proj, "db-dev", "human:Ann")
    rows = health.overview(proj, NOW)
    assert rows[0]["state"] == "works" and not rows[0].get("approve") and len(databricks) == 1


def test_a_changed_check_file_waits_for_approval_again(proj, databricks):
    _write(proj, "db-dev", {"command": ["databricks", "current-user", "me", "--profile", "dev"]})
    checkfiles.approve(proj, "db-dev", "human:Ann")
    _write(proj, "db-dev", {"command": ["databricks", "current-user", "me", "--profile", "other"]})
    rows = health.overview(proj, NOW)
    assert rows[0]["approve"] == "changed" and databricks == []
    assert checkfiles.recipes(proj) == []


def test_a_changed_script_waits_for_approval_again(proj):
    _write(proj, "api", {"script": "api.py"})
    (checkfiles.folder(proj) / "api.py").write_text("print(1)\n")
    checkfiles.approve(proj, "api", "human:Ann")
    assert [r["name"] for r in checkfiles.recipes(proj)] == ["api"]
    (checkfiles.folder(proj) / "api.py").write_text("print(2)\n")
    assert checkfiles.recipes(proj) == []


@pytest.mark.parametrize(
    "env", [{"ORCH_RUN": "r1"}, {"ORCH_AGENT": "claude"}, {"CLAUDECODE": "1"}], ids=["run", "agent", "tool"]
)
def test_an_agent_cannot_approve(proj, monkeypatch, env):
    _write(proj, "x", {"command": ["xtool", "status"]})
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(Refused, match="Only the person"):
        checkfiles.approve(proj, "x")
    monkeypatch.undo()
    with pytest.raises(Refused, match="Only the person"):
        checkfiles.approve(proj, "x", "agent:claude")


def test_approvals_live_in_the_guarded_home_not_in_the_project(proj):
    _write(proj, "x", {"command": ["xtool", "status"]})
    checkfiles.approve(proj, "x", "human:Ann")
    assert keystore.record_read(proj, "checks")["approved"]["x"] == checkfiles.digest(proj, "x")
    assert sorted(p.name for p in checkfiles.folder(proj).iterdir()) == ["x.json"]


@pytest.mark.parametrize(
    "doc",
    [
        {"command": ["bash", "-c", "true"]},  # a shell is never a check command
        {"command": ["python3", "x.py"]},
        {"script": "../x.py"},
        {"script": "x.exe"},
        {"script": "x.py", "command": ["xtool"]},
        {"command": ["xtool"], "interval": "10s"},  # under a minute
        {"command": ["xtool"], "timeout": "5m"},  # over 120 s
        {"command": ["xtool"], "requires": ["a b"]},
        {"command": ["xtool"], "kind": "magic"},
    ],
)
def test_a_bad_check_file_never_runs_and_cannot_be_approved(proj, doc):
    _write(proj, "bad", doc)
    assert checkfiles.recipes(proj) == []
    assert checkfiles.waiting_rows(proj)[0]["approve"] == "broken"
    with pytest.raises(Refused):
        checkfiles.approve(proj, "bad", "human:Ann")


def test_files_starting_with_underscore_never_run(proj):
    checkfiles.init(proj)
    assert (checkfiles.folder(proj) / "_template.json").is_file()
    assert checkfiles.entries(proj) == [] and checkfiles.parse("x", checkfiles.TEMPLATE)  # template is valid


# ------------------------------------------------------------------------------------------------ running


@pytest.mark.parametrize(
    ("value", "want"),
    [(None, 900), ("30m", 1800), ("2h", 7200), ("1d", 86400), (120, 120), ("90s", 90), ("10s", None), ("x", None)],
)
def test_interval(value, want):
    assert checkfiles.duration(value, 900, 60, 7 * 86400) == want


def test_interval_scheduling(proj, databricks):
    _write(proj, "slow", {"command": ["databricks", "current-user", "me", "--profile", "a"], "interval": "2h"})
    _write(proj, "fast", {"command": ["databricks", "current-user", "me", "--profile", "b"], "interval": "5m"})
    for n in ("slow", "fast"):
        checkfiles.approve(proj, n, "human:Ann")
    doc = health.check(proj, NOW)
    assert len(databricks) == 2 and doc["next_at"] == "2026-11-18T12:05:00Z"
    assert not health.due(proj, (NOW + timedelta(minutes=4)).timestamp())
    assert health.due(proj, (NOW + timedelta(minutes=5)).timestamp())
    health.check(proj, NOW + timedelta(minutes=6), due_only=True)
    assert [a[-1] for a in databricks[2:]] == ["b"]  # only the fast one ran again
    health.check(proj, NOW + timedelta(hours=2), due_only=True)
    assert sorted(a[-1] for a in databricks[3:]) == ["a", "b"]


def test_a_timeout_counts_as_unreachable_and_uses_the_check_s_own_limit(proj, monkeypatch):
    monkeypatch.setattr(health.shutil, "which", lambda b: f"/bin/{b}" if b == "slowtool" else None)
    seen = []

    def fake(argv, **kw):
        seen.append(kw["timeout"])
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(health.subprocess, "run", fake)
    _write(proj, "slow", {"command": ["slowtool", "status"], "timeout": "20s"})
    checkfiles.approve(proj, "slow", "human:Ann")
    rows = health.overview(proj, NOW)
    assert rows[0]["state"] == "unreachable" and seen == [20]


def test_a_missing_tool_counts_as_unreachable(proj, databricks):
    _write(proj, "gone", {"command": ["nothere", "status"]})
    _write(proj, "needs", {"command": ["databricks", "current-user", "me"], "requires": ["jq"]})
    for n in ("gone", "needs"):
        checkfiles.approve(proj, n, "human:Ann")
    rows = {r["name"]: r["state"] for r in health.overview(proj, NOW)}
    assert rows == {"gone": "unreachable", "needs": "unreachable"} and databricks == []


def test_a_script_check_gets_its_key_as_a_variable_only(proj, monkeypatch):
    monkeypatch.setattr(health, "helper_recipes", lambda: [])
    keystore.add(proj, "api-token", "token", "tok-12345678")
    _write(proj, "api", {"label": "Payments API", "kind": "key", "script": "api.py", "key": "api-token"})
    (checkfiles.folder(proj) / "api.py").write_text(
        "import os, sys\nsys.exit(0 if os.environ.get('ORCH_CHECK_KEY') == 'tok-12345678' else 3)\n"
    )
    checkfiles.approve(proj, "api", "human:Ann")
    r = checkfiles.recipes(proj)[0]
    argv, env = checkfiles.script_argv(proj, r)
    assert argv[:2] == [sys.executable, "-I"] and "tok-12345678" not in argv
    rows = health.overview(proj, NOW)
    assert rows[0]["state"] == "works" and "tok-12345678" not in json.dumps(rows)


def test_phone_rows_skip_checks_that_wait_and_treat_tool_as_login(proj, databricks):
    from orch import phone_alerts

    _write(proj, "waits", {"command": ["databricks", "x"]})
    _write(proj, "cli", {"command": ["databricks", "y"], "kind": "tool"})
    checkfiles.approve(proj, "cli", "human:Ann")
    items = health.check(proj, NOW)["items"]
    got = phone_alerts.known(proj, items)
    assert [(x["name"], x["kind"]) for x in got] == [("cli", "login")]


# ------------------------------------------------------------------------------------------------ the command


def test_checks_command(proj, run, databricks):
    code, out, _ = run("checks", "list")
    assert code == 0 and "orch checks init" in out
    code, out, _ = run("checks", "init")
    assert code == 0 and "databricks" in out
    code, out, _ = run("checks", "templates")
    assert "databricks: Databricks (one check per profile" in out
    code, out, err = run("checks", "add", "databricks")
    assert code == 2 and "--profile" in err
    code, out, _ = run("checks", "add", "databricks", "--profile", "pilatus_hub_sbox")
    assert code == 0 and "databricks auth login --profile pilatus_hub_sbox" in out
    _write(proj, "own", {"label": "Own", "command": ["databricks", "current-user", "me"]})
    code, out, _ = run("checks", "list")
    assert "own (Own): new, waits for approval: orch checks approve own" in out
    assert "databricks-pilatus-hub-sbox (Databricks pilatus_hub_sbox): renew" in out
    code, out, _ = run("checks", "approve", "own")
    assert code == 0 and "Approved own. The Own login works." in out
    code, out, _ = run("checks", "run", "own")
    assert code == 0 and out.startswith("The Own login works.")
    code, out, _ = run("checks", "remove", "own")
    assert code == 0 and not (checkfiles.folder(proj) / "own.json").exists()
    assert "own" not in keystore.record_read(proj, "checks")["approved"]
    code, out, err = run("checks", "run", "own")
    assert code == 2


def test_logins_add_may_reuse_a_built_in_name_once_the_workspace_sets_its_own(proj):
    with pytest.raises(Refused):
        health.add_recipe(proj, "databricks", {"command": ["databricks", "x"]})
    checkfiles.init(proj)
    assert health.add_recipe(proj, "databricks", {"command": ["databricks", "x"]})["name"] == "databricks"

"""Checks a workspace sets for itself (checkfiles.py, `orch checks`, ORCH-529)."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


def _ok(proj, name):
    """The person approves the content they were shown (its short hash, as orch checks list prints it)."""
    return checkfiles.approve(proj, name, "human:Ann", checkfiles.short(checkfiles.digest(proj, name)))


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


# ------------------------------------------------------------------------------------------------ approve


def test_a_new_check_file_runs_only_once_approved(proj, databricks):
    doc = {"label": "Databricks dev", "command": ["databricks", "current-user", "me", "--profile", "dev"]}
    _write(proj, "db-dev", doc)
    rows = health.overview(proj, NOW)
    assert databricks == []  # nothing ran
    assert rows[0]["approve"] == "new" and rows[0]["sign_in"] == (
        f"orch checks approve db-dev --hash {checkfiles.short(checkfiles.digest(proj, 'db-dev'))}"
    )
    _ok(proj, "db-dev")
    rows = health.overview(proj, NOW)
    assert rows[0]["state"] == "works" and not rows[0].get("approve") and len(databricks) == 1


def test_a_changed_check_file_must_be_approved_again(proj, databricks):
    _write(proj, "db-dev", {"command": ["databricks", "current-user", "me", "--profile", "dev"]})
    _ok(proj, "db-dev")
    _write(proj, "db-dev", {"command": ["databricks", "current-user", "me", "--profile", "other"]})
    rows = health.overview(proj, NOW)
    assert rows[0]["approve"] == "changed" and databricks == []
    assert checkfiles.recipes(proj) == []


def test_a_changed_script_must_be_approved_again(proj):
    _write(proj, "api", {"script": "api.py"})
    (checkfiles.folder(proj) / "api.py").write_text("print(1)\n")
    _ok(proj, "api")
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


def test_approve_without_the_hash_shows_what_it_runs_and_approves_nothing(proj):
    _write(proj, "x", {"script": "x.py", "key": "api-key"})
    (checkfiles.folder(proj) / "x.py").write_text("print(1)\n")
    h = checkfiles.short(checkfiles.digest(proj, "x"))
    with pytest.raises(Refused) as e:
        checkfiles.approve(proj, "x", "human:Ann")
    assert "the script .orch/checks/x.py, given the key api-key" in str(e.value)
    assert f"orch checks approve x --hash {h}" in str(e.value)
    with pytest.raises(Refused):
        checkfiles.approve(proj, "x", "human:Ann", h[:6])  # too short to bind the content
    assert checkfiles.recipes(proj) == []


def test_a_file_changed_after_the_person_looked_is_refused(proj):
    """The race of the security review (ORCH-538): the person reads the file and its hash, a helper swaps
    the file or its script before they press approve; approve must not take the new content."""
    _write(proj, "x", {"script": "x.py"})
    (checkfiles.folder(proj) / "x.py").write_text("print('fine')\n")
    seen = checkfiles.short(checkfiles.digest(proj, "x"))
    (checkfiles.folder(proj) / "x.py").write_text("print('bad')\n")  # swapped in between
    with pytest.raises(Refused, match="changed since you looked"):
        checkfiles.approve(proj, "x", "human:Ann", seen)
    _write(proj, "x", {"script": "y.py", "key": "admin"})
    (checkfiles.folder(proj) / "y.py").write_text("print('bad')\n")
    with pytest.raises(Refused, match="changed since you looked"):
        checkfiles.approve(proj, "x", "human:Ann", seen)
    assert checkfiles.recipes(proj) == [] and "x" not in checkfiles._approved(proj)


def test_a_file_swapped_while_orch_adds_a_template_is_not_approved(proj, monkeypatch, databricks):
    """The race of the security review (ORCH-538): a helper replaces the file orch just wrote from a template
    (with a script that gets a key) before orch records it; only orch's own bytes may count as approved."""
    real = checkfiles._write

    def racing(root, name, doc):
        raw = real(root, name, doc)
        _write(root, name, {"script": "evil.py", "key": "admin"})
        (checkfiles.folder(root) / "evil.py").write_text("print('evil')\n")
        return raw

    monkeypatch.setattr(checkfiles, "_write", racing)
    checkfiles.add_from_template(proj, "databricks", "dev")
    e = next(x for x in checkfiles.entries(proj) if x["name"] == "databricks-dev")
    assert e["status"] == "changed" and checkfiles.recipes(proj) == []


def test_an_added_template_is_approved_as_written(proj, databricks):
    r = checkfiles.add_from_template(proj, "databricks", "dev")
    assert [x["name"] for x in checkfiles.recipes(proj)] == ["databricks-dev"]
    assert r["v"] == checkfiles.digest(proj, "databricks-dev")[:16]


def test_a_badly_named_check_file_is_never_shown(proj):
    _write(proj, "bad\x1b[2Jname", {"command": ["xtool", "status"]})
    _write(proj, "Upper", {"command": ["xtool", "status"]})
    assert checkfiles.entries(proj) == [] and checkfiles.waiting_rows(proj) == []


def test_what_was_approved_lives_in_the_guarded_home_not_in_the_project(proj):
    _write(proj, "x", {"command": ["xtool", "status"]})
    _ok(proj, "x")
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
        _ok(proj, "bad")


def test_files_starting_with_underscore_never_run(proj):
    checkfiles.init(proj)
    assert (checkfiles.folder(proj) / "_template.json").is_file()
    assert checkfiles.entries(proj) == [] and checkfiles.parse("x", checkfiles.TEMPLATE)  # template is valid


# ------------------------------------------------------------------------------------------------ running


@pytest.mark.parametrize(
    ("value", "want"),
    [
        (None, 900),
        ("30m", 1800),
        ("2h", 7200),
        ("1d", 86400),
        (120, 120),
        ("90s", 90),
        ("10s", None),
        ("x", None),
    ],
)
def test_interval(value, want):
    assert checkfiles.duration(value, 900, 60, 7 * 86400) == want


def test_interval_scheduling(proj, databricks):
    _write(
        proj, "slow", {"command": ["databricks", "current-user", "me", "--profile", "a"], "interval": "2h"}
    )
    _write(
        proj, "fast", {"command": ["databricks", "current-user", "me", "--profile", "b"], "interval": "5m"}
    )
    for n in ("slow", "fast"):
        _ok(proj, n)
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
    _ok(proj, "slow")
    rows = health.overview(proj, NOW)
    assert rows[0]["state"] == "unreachable" and seen == [20]


def test_a_missing_tool_counts_as_unreachable(proj, databricks):
    _write(proj, "gone", {"command": ["nothere", "status"]})
    _write(proj, "needs", {"command": ["databricks", "current-user", "me"], "requires": ["jq"]})
    for n in ("gone", "needs"):
        _ok(proj, n)
    rows = {r["name"]: r["state"] for r in health.overview(proj, NOW)}
    assert rows == {"gone": "unreachable", "needs": "unreachable"} and databricks == []


def test_a_script_check_gets_its_key_as_a_variable_only(proj, monkeypatch):
    monkeypatch.setattr(health, "helper_recipes", lambda: [])
    keystore.add(proj, "api-token", "token", "tok-12345678")
    _write(proj, "api", {"label": "Payments API", "kind": "key", "script": "api.py", "key": "api-token"})
    (checkfiles.folder(proj) / "api.py").write_text(
        "import os, sys\n"
        "fd = os.environ.get('ORCH_CHECK_KEY_FD')\n"
        "key = os.read(int(fd), 4096).decode() if fd else os.environ.get('ORCH_CHECK_KEY')\n"
        "sys.exit(0 if key == 'tok-12345678' else 3)\n"
    )
    _ok(proj, "api")
    r = checkfiles.recipes(proj)[0]
    with checkfiles.prepared(proj, r) as (argv, env, fds):
        assert argv[:2] == [sys.executable, "-I"] and "tok-12345678" not in json.dumps(argv)
        assert str(checkfiles.folder(proj)) not in argv[2]  # a private copy runs, never the project file
        if os.name != "nt":
            assert "tok-12345678" not in json.dumps(env) and fds
    assert not Path(argv[2]).exists()  # the copy is gone afterwards
    rows = health.overview(proj, NOW)
    assert rows[0]["state"] == "works" and "tok-12345678" not in json.dumps(rows)


def test_a_script_swapped_once_approved_does_not_run(proj, monkeypatch):
    monkeypatch.setattr(health, "helper_recipes", lambda: [])
    _write(proj, "api", {"script": "api.py"})
    (checkfiles.folder(proj) / "api.py").write_text("import sys; sys.exit(0)\n")
    _ok(proj, "api")
    r = checkfiles.recipes(proj)[0]  # approved when it was read ...
    (checkfiles.folder(proj) / "api.py").write_text("import sys; sys.exit(0)  # other\n")  # ... then swapped
    with checkfiles.prepared(proj, r) as (argv, _, _):
        assert argv is None
    assert health.run_one(proj, r) == (None, None, False)


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need admin rights on Windows")
def test_a_linked_or_huge_script_is_never_read(proj, tmp_path):
    outside = tmp_path / "elsewhere.py"
    outside.write_text("print(1)\n")
    _write(proj, "linked", {"script": "linked.py"})
    (checkfiles.folder(proj) / "linked.py").symlink_to(outside)
    _write(proj, "huge", {"script": "huge.py"})
    (checkfiles.folder(proj) / "huge.py").write_bytes(b"#" * (checkfiles._FILE_MAX + 1))
    for n in ("linked", "huge"):
        assert checkfiles._load(proj, n)[2] is None
        _ok(proj, n)
    assert all(health.run_one(proj, r) == (None, None, False) for r in checkfiles.recipes(proj))


def test_phone_rows_skip_checks_that_wait_and_treat_tool_as_login(proj, databricks):
    from orch import phone_alerts

    _write(proj, "waits", {"command": ["databricks", "x"]})
    _write(proj, "cli", {"command": ["databricks", "y"], "kind": "tool"})
    _ok(proj, "cli")
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
    h = checkfiles.short(checkfiles.digest(proj, "own"))
    assert f"own (Own): new, runs databricks current-user me (content {h}), " in out
    assert f"waits until you approve it: orch checks approve own --hash {h}" in out
    assert "databricks-pilatus-hub-sbox (Databricks pilatus_hub_sbox): renew" in out
    code, out, err = run("checks", "approve", "own")
    assert code == 2 and f"--hash {h}" in err
    code, out, _ = run("checks", "approve", "own", "--hash", h)
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

import json
import os
import shutil
import socket
import time

import pytest

from orch import adapters, addons, cli_leave, diag, diag_collect, safegit, services

_REAL_UV_FAILS = cli_leave._uv_fails


@pytest.fixture(autouse=True)
def tools_found(monkeypatch):
    diag._dropped.clear()  # a process-wide counter other tests may have raised
    monkeypatch.setattr(
        adapters,
        "detect",
        lambda **_: [{"name": "claude", "label": "Claude", "found": True, "version": None}],
    )
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: f"/usr/bin/{n}")
    monkeypatch.setattr(addons, "_which_uv", lambda: "/usr/bin/uv")
    monkeypatch.setattr(cli_leave, "_uv_fails", lambda uv: None)
    plenty = type("U", (), {"free": 10**11, "total": 10**12})()  # never the real (maybe full) disk
    monkeypatch.setattr(diag_collect.shutil, "disk_usage", lambda p: plenty)


def test_fresh_init_reports_nothing_wrong(proj, run):
    assert run("init")[0] == 0
    code, out, _ = run("doctor")
    assert code == 0 and "Nothing wrong." in out.splitlines()[-2:-1], out


def test_a_missing_skill_link_is_one_problem_with_a_next_step(proj, run):
    assert run("init")[0] == 0
    link = proj / ".agents/skills/orch"
    if link.is_symlink():
        link.unlink()
    else:  # Windows has no links here: the skill is a copy of the folder
        shutil.rmtree(link)
    code, out, _ = run("doctor")
    assert code == 0 and "1 thing to fix." in out
    assert "not linked" in out and "Run: orch init" in out


def test_doctor_in_a_folder_without_orch(proj, run):
    code, out, _ = run("doctor")
    assert code == 0 and "not set up" in out and "Run: orch init" in out


def test_doctor_json(proj, run, monkeypatch):
    assert run("init")[0] == 0
    calls = []
    detect = adapters.detect
    monkeypatch.setattr(adapters, "detect", lambda **k: calls.append(1) or detect(**k))
    code, out, _ = run("doctor", "--json")
    d = json.loads(out)
    assert code == 0 and d["ok"] and d["problems"] == 0, [r for r in d["checks"] if not r["ok"]]
    assert cli_leave.TOOL
    assert len(calls) == 1


# ORCH-1970: the top real failure modes, each one problem with a one-sentence fix


def _problems(proj):
    return [r for r in cli_leave.doctor(proj)["checks"] if not r["ok"]]


def _only(proj, name):
    (r,) = [r for r in _problems(proj) if r["name"] == name]
    assert r["next"] and r["next"].count(". ") == 0 and r["next"].endswith((".", "start")), r
    return r


def test_missing_git_in_a_git_folder(proj, run, monkeypatch):
    assert run("init")[0] == 0
    (proj / ".git").mkdir(exist_ok=True)
    monkeypatch.setattr(safegit, "have_git", lambda *a, **k: False)
    assert "Install git" in _only(proj, "git")["next"]


def test_unreadable_ticket_json(proj, run):
    assert run("init")[0] == 0
    tid = json.loads(run("ticket", "new", "T", "--json")[1])["id"]
    assert not _problems(proj)
    (proj / f".orch/tickets/{tid}.json").write_text('{"id": "', encoding="utf-8")
    r = _only(proj, "ticket files")
    assert f"{tid}.json" in r["fact"] and "fix the JSON" in r["next"]


def test_stale_ticket_lock(proj, run):
    assert run("init")[0] == 0
    lock = proj / ".orch/tickets/.lock-t_abc123"
    lock.write_text("99999999 -", encoding="utf-8")
    assert not _problems(proj)  # a fresh lock is a write in progress
    old = time.time() - 600
    os.utime(lock, (old, old))
    r = _only(proj, "ticket locks")
    assert "10 min old" in r["fact"] and ".lock-t_abc123" in r["next"]


def test_port_in_use(proj, run, monkeypatch):
    assert run("init")[0] == 0
    monkeypatch.setattr(addons, "active", lambda root: {"fake": {}})
    monkeypatch.setattr(addons, "discover", lambda: {"fake": {"run": "json", "background": True}})
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        monkeypatch.setattr(services, "last_port", lambda root, name: port)
        r = _only(proj, "port of fake")
        assert f"port {port}" in r["next"]
    assert not _problems(proj)  # the other program is gone: the port is free again


def test_addon_import_error(proj, run, monkeypatch):
    assert run("init")[0] == 0
    monkeypatch.setattr(addons, "active", lambda root: {"fake": {}})
    monkeypatch.setattr(
        addons, "discover", lambda: {"fake": {"run": "orch_no_such_pkg", "background": False}}
    )
    r = _only(proj, "add-on fake")
    assert "ModuleNotFoundError" in r["fact"] and "orch addon add fake" in r["next"]
    monkeypatch.setattr(addons, "discover", lambda: {})
    assert "not installed" in _only(proj, "add-on fake")["fact"]


def test_broken_uv(proj, run, monkeypatch):
    assert run("init")[0] == 0
    monkeypatch.setattr(cli_leave, "_uv_fails", _REAL_UV_FAILS)
    bad = proj / "uv-broken"
    bad.write_text("not a program", encoding="utf-8")
    monkeypatch.setattr(addons, "_which_uv", lambda: str(bad))  # a uv left behind that does not run
    r = _only(proj, "uv")
    assert "does not run" in r["fact"] and "install line" in r["next"]
    assert _REAL_UV_FAILS(str(proj / "gone")) == "FileNotFoundError"


def test_full_disk(proj, run, monkeypatch):
    assert run("init")[0] == 0
    monkeypatch.setattr(
        diag_collect.shutil, "disk_usage", lambda p: type("U", (), {"free": 1024, "total": 10**9})()
    )
    r = _only(proj, "disk_low")
    assert r["fact"].startswith("The disk is nearly full: 0 MB free") and "Free some disk space" in r["next"]


def test_clock_skew(proj, run):
    assert run("init")[0] == 0
    tid = json.loads(run("ticket", "new", "T", "--json")[1])["id"]
    p = proj / f".orch/tickets/{tid}.json"
    t = json.loads(p.read_text(encoding="utf-8"))
    t["status"] = "active"  # the run checks look at Working tickets
    t["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
    p.write_text(json.dumps(t), encoding="utf-8")
    r = _only(proj, "clock_skew")
    assert "in the future" in r["fact"] and "date and time" in r["next"]

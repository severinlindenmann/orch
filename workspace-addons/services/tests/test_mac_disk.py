"""macOS: a workspace on an external disk (/Volumes/<disk>) and logs in the home folder (report r-1120-0610-services).

launchd cannot open a log or start a job in a folder macOS keeps from background jobs. The owner chose (20 Nov):
never refuse such a workspace, run its jobs from a home folder and warn."""

import os
import subprocess
from pathlib import Path

import pytest
from conftest import WID, jrun


@pytest.fixture
def mac(monkeypatch, tmp_path, fake):
    """A Mac with its own home folder; the fake driver answers as launchd."""
    from orch_services import store

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(store, "_platform", lambda: "darwin")
    fake.name = "launchd"
    return home


@pytest.fixture
def external(monkeypatch, ws):
    """The test workspace lies on an external disk."""
    from orch_services import cli

    monkeypatch.setattr(cli, "_external_disk", lambda p: Path(p).resolve().is_relative_to(ws.resolve()))


def _add(cli, *extra):
    return jrun(
        cli, "add", "Web preview", "--id", "web", *extra, "--", "python3", "-m", "http.server", "8000"
    )


def test_mac_logs_go_to_the_home_library(cli, fake, ws, mac):
    code, out = _add(cli)
    assert code == 0
    spec = fake.entries["web"]["spec"]
    assert spec.log == mac / "Library" / "Logs" / "orch" / WID / "web.log"
    assert spec.log.parent.is_dir()
    assert spec.cwd == ws.resolve() and "ORCH_WORKSPACE" not in spec.env  # the Mac's own disk: as before
    assert "note" not in out


def test_other_computers_keep_the_log_in_the_workspace(cli, fake, ws):
    code, _ = _add(cli)
    assert code == 0
    assert fake.entries["web"]["spec"].log == (ws / ".orch/addons/services/logs/web.log").absolute()


def test_an_external_disk_runs_from_home_and_warns_but_never_refuses(cli, fake, ws, mac, external):
    code, out = _add(cli, "--start")
    assert code == 0 and out["service"]["state"] == "running"
    spec = fake.entries["web"]["spec"]
    assert spec.cwd == mac / "Library" / "Application Support" / "orch" / WID
    assert spec.env["ORCH_WORKSPACE"] == str(ws.resolve())
    assert spec.env["ORCH_SERVICE_DIR"] == str(ws.resolve())
    assert "external disk" in out["note"] and "home folder" in out["note"] and "ORCH_WORKSPACE" in out["note"]
    assert "private network" in out["note"]
    assert "may be blocked" not in out["note"]  # python3 lives on this Mac


def test_a_program_on_the_external_disk_is_named(cli, fake, ws, mac, external):
    tool = ws / "serve"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    tool.chmod(0o755)
    code, out = jrun(cli, "add", "Tool", "--id", "tool", "--", "./serve")
    assert code == 0 and "may be blocked" in out["note"]


def test_log_reads_the_newer_of_the_home_and_the_old_workspace_log(cli, fake, ws, mac):
    from orch_services import store

    assert _add(cli)[0] == 0
    old = store.logs_dir(ws) / "web.log"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("from the old place\n", encoding="utf-8")
    new = store.log_path(ws, "web", WID)
    new.write_text("from the home log\n", encoding="utf-8")
    os.utime(old, (1_000_000_000, 1_000_000_000))
    code, out = jrun(cli, "log", "web")
    assert code == 0 and out["lines"] == ["from the home log"]
    os.utime(new, (900_000_000, 900_000_000))  # a job loaded before the move still writes the old one
    code, out = jrun(cli, "log", "web")
    assert out["lines"] == ["from the old place"]
    code, out = jrun(cli, "remove", "web")
    assert code == 0 and ".orch/addons/services/logs/web.log" in out["next"]
    code, out = _add(cli)
    assert (
        code == 0 and not old.exists() and not new.exists()
    )  # a re-added id moves both places aside (ORCH-1131)


def test_no_route_to_host_names_the_local_network(cli, fake, ws, mac, clock):
    from orch_services import store

    assert _add(cli)[0] == 0
    log = store.log_path(ws, "web", WID)
    log.write_text(
        "dial tcp 192.168.64.3:443: connect: no route to host\n", encoding="utf-8"
    )  # lowercase, as Go and curl write it
    fake.start_dies = True
    code, out = jrun(cli, "start", "web")
    assert code == 0 and "local network" in out["next"] and "private network address" in out["next"]


def test_exit_78_without_a_log_says_macos_blocked_it(cli, fake, ws, mac, clock):
    assert _add(cli)[0] == 0
    fake.start_dies = True
    fake.last_exit = lambda spec: 78
    code, out = jrun(cli, "start", "web")
    assert code == 0 and "did not let it open its log or its folder" in out["next"]


def test_exit_78_with_an_empty_new_log_still_says_macos_blocked_it(cli, fake, ws, mac, clock):
    from orch_services import store

    assert _add(cli)[0] == 0
    store.log_path(ws, "web", WID).write_text(
        "", encoding="utf-8"
    )  # launchd opened the log, then failed the folder
    fake.start_dies = True
    fake.last_exit = lambda spec: 78
    code, out = jrun(cli, "start", "web")
    assert code == 0 and "did not let it open its log or its folder" in out["next"]


def test_the_home_log_of_an_earlier_build_is_still_read_and_moved_aside(cli, fake, ws, mac):
    import hashlib
    import re

    assert _add(cli)[0] == 0
    r = ws.resolve()
    tag = hashlib.sha1(str(r).encode()).hexdigest()[:8]
    name = re.sub(r"[^A-Za-z0-9._-]", "-", r.name)
    earlier = mac / "Library" / "Logs" / "orch" / f"{name}-{tag}" / "web.log"
    earlier.parent.mkdir(parents=True, exist_ok=True)
    earlier.write_text("from the earlier home log\n", encoding="utf-8")
    code, out = jrun(cli, "log", "web")
    assert code == 0 and out["lines"] == ["from the earlier home log"]
    assert jrun(cli, "remove", "web")[0] == 0 and _add(cli)[0] == 0
    assert not earlier.exists() and list((earlier.parent / "removed").glob("web-*.log"))


@pytest.fixture
def clock(monkeypatch):
    """No real waiting for a job that does not come up."""
    from orch_services import cli

    t = [0.0]

    def mono():
        t[0] += 20
        return t[0]

    monkeypatch.setattr(cli.time, "monotonic", mono)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)


# -- the launchd driver itself, with launchctl answered here


def _launchd(monkeypatch, answers):
    from orch_services.drivers import launchd

    calls = []

    def run(self, *args):
        calls.append(args)
        out = answers.get(args[0], (0, ""))
        return subprocess.CompletedProcess(args, out[0], out[1], "")

    monkeypatch.setattr(launchd.Launchd, "_run", run)
    monkeypatch.setattr(launchd.os, "getuid", lambda: 501, raising=False)  # Windows has no getuid
    return launchd.Launchd(), calls


def _spec(home, log_dir="Library/Logs/orch/w", cwd="code"):
    from orch_services.drivers import Spec

    return Spec(
        sid="web",
        name="Web",
        workspace_id="w",
        argv=["/usr/bin/true"],
        cwd=home / cwd,
        log=home / log_dir / "web.log",
        auto=False,
    )


def test_launchd_reads_the_last_exit_code(monkeypatch, tmp_path):
    drv, _ = _launchd(
        monkeypatch, {"print": (0, "\tstate = not running\n\tlast exit code = 78: EX_CONFIG\n")}
    )
    assert drv.last_exit(_spec(tmp_path)) == 78
    drv, _ = _launchd(monkeypatch, {"print": (113, "")})
    assert drv.last_exit(_spec(tmp_path)) is None


def test_launchd_start_rewrites_the_plist_when_not_loaded(monkeypatch, tmp_path):
    # a job added before the logs moved gets the home log and folder at its next start
    import plistlib

    monkeypatch.setenv("HOME", str(tmp_path))
    drv, calls = _launchd(monkeypatch, {"print": (113, "")})
    old = _spec(tmp_path, log_dir="ws/.orch/addons/services/logs")
    drv.install(old)
    new = _spec(tmp_path, cwd="Library/Application Support/orch/w")
    drv.start(new)
    data = plistlib.loads(drv.entry_path(new).read_bytes())
    assert data["StandardOutPath"] == str(new.log) and data["WorkingDirectory"] == str(new.cwd)
    assert new.cwd.is_dir()
    assert any(c[0] == "bootstrap" for c in calls)


def test_a_failed_start_reads_the_old_log_a_loaded_job_still_writes(cli, fake, ws, mac, clock):
    from orch_services import store

    assert _add(cli)[0] == 0
    old = store.logs_dir(ws) / "web.log"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("Error: port 8000 is taken\n", encoding="utf-8")
    fake.start_dies = True
    fake.last_exit = lambda spec: 78
    code, out = jrun(cli, "start", "web")
    assert code == 0 and "port 8000 is taken" in out["next"] and "never ran" not in out["next"]


def test_launchd_status_reads_running_launching_and_not_loaded(monkeypatch, tmp_path):
    from orch_services.drivers import launchd

    monkeypatch.setattr(launchd, "_started", lambda pid: "2026-11-25T09:00:00Z")
    drv, _ = _launchd(monkeypatch, {"print": (0, "\tstate = running\n\tpid = 812\n")})
    st = drv.status(_spec(tmp_path))
    assert (st.running, st.pid, st.since) == (True, 812, "2026-11-25T09:00:00Z")
    drv, _ = _launchd(monkeypatch, {"print": (0, "\tstate = spawn scheduled\n")})
    st = drv.status(_spec(tmp_path))
    assert not st.running and st.starting
    drv, _ = _launchd(monkeypatch, {"print": (0, "\tstate = not running\n\truns = 7\n")})
    st = drv.status(_spec(tmp_path))
    assert not st.running and not st.starting and drv.runs(_spec(tmp_path)) == 7
    drv, _ = _launchd(monkeypatch, {"print": (113, "")})
    assert drv.status(_spec(tmp_path)).running is False and drv.runs(_spec(tmp_path)) is None


def test_launchd_without_a_login_session_says_so(monkeypatch, tmp_path):
    from orch_services.drivers import Unavailable

    drv, _ = _launchd(monkeypatch, {"print": (125, "")})
    drv.tool = str(tmp_path / "launchctl")
    with pytest.raises(Unavailable, match="launchctl is missing"):
        drv.check()
    (tmp_path / "launchctl").write_text("", encoding="utf-8")
    with pytest.raises(Unavailable, match="log in on this Mac's screen once"):
        drv.check()


def test_launchd_restart_of_an_unloaded_job_starts_it(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    drv, calls = _launchd(monkeypatch, {"print": (113, "")})
    drv.restart(_spec(tmp_path))
    assert ("kickstart", "-k", "gui/501/ch.orch.svc.w.web") not in calls
    assert any(c[0] == "bootstrap" for c in calls)


def test_launchd_failures_name_the_tool_line(monkeypatch, tmp_path):
    from orch_services.drivers import launchd
    from orch_services.store import Refused

    monkeypatch.setenv("HOME", str(tmp_path))

    def run(self, *args):
        rc = 5 if args[0] in ("kickstart", "bootout") else 0
        out = "\tstate = not running\n" if args[0] == "print" else ""
        return subprocess.CompletedProcess(args, rc, out, "Input/output error" if rc else "")

    monkeypatch.setattr(launchd.Launchd, "_run", run)
    monkeypatch.setattr(launchd.os, "getuid", lambda: 501, raising=False)
    drv = launchd.Launchd()
    spec = _spec(tmp_path)
    drv.install(spec)
    with pytest.raises(Refused, match=r"Could not start it \(Input/output error\)"):
        drv.start(spec)  # loaded but not running: kickstart fails
    with pytest.raises(Refused, match=r"Could not restart it \(Input/output error\)"):
        drv.restart(spec)
    with pytest.raises(Refused, match=r"Could not stop it \(Input/output error\)"):
        drv.stop(spec)  # bootout fails and the job is still loaded


def test_launchd_leaves_an_adopted_plist_alone(monkeypatch, tmp_path):
    from orch_services.drivers import Spec
    from orch_services.store import Refused

    monkeypatch.setenv("HOME", str(tmp_path))
    drv, calls = _launchd(monkeypatch, {"print": (113, "")})
    plist = tmp_path / "Library" / "LaunchAgents" / "com.jörg.web.plist"
    spec = Spec(
        sid="web",
        name="Web",
        workspace_id="w",
        argv=["/usr/bin/true"],
        cwd=tmp_path,
        log=tmp_path / "x.log",
        auto=True,
        external="com.jorg.web",
        external_path=plist,
    )
    with pytest.raises(Refused, match="orch services remove web"):
        drv.start(spec)  # its plist is gone
    plist.parent.mkdir(parents=True)
    plist.write_bytes(b"<plist>mine</plist>")
    drv.set_auto(spec)
    drv.uninstall(spec)
    assert plist.read_bytes() == b"<plist>mine</plist>"
    assert not any(c[0] == "bootout" for c in calls)


def test_launchd_plist_keeps_spaces_umlauts_and_markup_exact(tmp_path):
    import plistlib

    from orch_services.drivers import Spec, launchd

    d = tmp_path / "Jörg Müller" / "web app"
    spec = Spec(
        sid="web",
        name="Web",
        workspace_id="w",
        argv=[str(d / "run.sh"), "--title", "A & B <ü>"],
        cwd=d,
        log=d / "log file.log",
        auto=False,
        env={"GREETING": "grüezi & ciao"},
    )
    data = plistlib.loads(launchd.render(spec))
    assert data["ProgramArguments"] == spec.argv and data["WorkingDirectory"] == str(d)
    assert data["StandardErrorPath"] == str(d / "log file.log")
    assert data["EnvironmentVariables"] == {"GREETING": "grüezi & ciao"} and data["RunAtLoad"] is False

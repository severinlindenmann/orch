"""The real platform tool, once per platform: skipped unless on that platform AND ORCH_SERVICES_REAL=1.

The plist lands under the test's HOME (a temp folder). The systemd unit lands in the real account's
~/.config/systemd/user, the only folder the user service manager reads. The Windows task lands in the account's own
\\orch\\ task folder and must run as a standard user signed in on the screen. Each test removes its file or task by
its exact name at the end."""

import json
import os
import subprocess
import sys
import time

import pytest
from conftest import WID

REAL = os.environ.get("ORCH_SERVICES_REAL") == "1"
SLEEPER = [
    sys.executable if sys.platform == "win32" else "python3",
    "-u",
    "-c",
    "print('hello from the service', flush=True); import time; time.sleep(600)",
]


def _wait(cond, seconds=15.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.25)
    return cond()


def _alive(pid: int) -> bool:
    from orch_services import winproc  # never os.kill(pid, 0) on Windows: it ends the process there

    return winproc.started(pid) is not None


@pytest.fixture
def real(ws, capsys):
    from orch_services.cli import main

    def run(*argv):
        code = main(
            [*argv, "--json"]
            if "--" not in argv
            else [*argv[: argv.index("--")], "--json", *argv[argv.index("--") :]]
        )
        out = capsys.readouterr().out
        return code, json.loads(out)

    return run


def _row(real):
    code, out = real("list")
    assert code == 0, out
    return out["services"][0]


def _cycle(real, ws, disabled):
    """add, start, running, restart (new pid), auto on/off, stop, remove."""
    code, out = real("add", "Sleeper ä", "--id", "sleeper", "--", *SLEEPER)
    assert code == 0, out
    assert out["service"]["state"] == "stopped"
    code, out = real("start", "sleeper")
    assert code == 0, out
    assert _wait(lambda: _row(real)["state"] == "running"), _row(real)
    pid = _row(real)["pid"]
    assert _alive(pid)
    log = ws / ".orch/addons/services/logs/sleeper.log"
    assert _wait(lambda: log.is_file() and "hello from the service" in log.read_text(encoding="utf-8"))
    code, out = real("log", "sleeper")
    assert "hello from the service" in out["lines"]

    code, out = real("restart", "sleeper")
    assert code == 0, out
    assert _wait(lambda: _row(real).get("pid") not in (None, pid)), _row(real)
    assert _wait(lambda: not _alive(pid))

    code, out = real("auto", "sleeper", "on")
    assert code == 0 and out["service"]["auto"] is True and disabled() is False
    code, out = real("auto", "sleeper", "off")
    assert code == 0 and out["service"]["auto"] is False and disabled() is True
    assert _row(real)["state"] == "running"  # switching auto does not stop it

    pid = _row(real)["pid"]
    code, out = real("stop", "sleeper")
    assert code == 0 and out["service"]["state"] == "stopped", out
    assert _wait(lambda: not _alive(pid))
    code, out = real("remove", "sleeper")
    assert code == 0, out
    assert log.is_file()  # remove keeps the log; a re-added id moves it aside (ORCH-1131)


@pytest.mark.skipif(
    not (REAL and sys.platform == "darwin"), reason="real launchd test: macOS + ORCH_SERVICES_REAL=1"
)
def test_real_launchd(real, ws):
    from pathlib import Path

    label = f"ch.orch.svc.{WID}.sleeper"
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    domain = f"gui/{os.getuid()}"

    def disabled():
        out = subprocess.run(
            ["launchctl", "print-disabled", domain], check=False, capture_output=True, text=True
        ).stdout
        for line in out.splitlines():
            if f'"{label}"' in line:
                return "true" in line or "disabled" in line.split("=>")[-1]
        return None

    try:
        _cycle(real, ws, disabled)
        assert not plist.exists()
    finally:
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], check=False, capture_output=True)
        subprocess.run(["launchctl", "enable", f"{domain}/{label}"], check=False, capture_output=True)
        if plist.exists():
            plist.unlink()


@pytest.mark.skipif(
    not (REAL and sys.platform.startswith("linux")), reason="real systemd test: Linux + ORCH_SERVICES_REAL=1"
)
def test_real_systemd(real, ws, monkeypatch):
    import pwd
    from pathlib import Path

    # The user service manager reads only the real account's unit folder, never the test's temp HOME
    # (launchd is handed the plist path, systemd is not): the unit goes there, removed by its exact path.
    monkeypatch.setenv("HOME", pwd.getpwuid(os.getuid()).pw_dir)
    unit = f"orch-svc-{WID}-sleeper.service"
    path = Path.home() / ".config" / "systemd" / "user" / unit

    def disabled():
        out = subprocess.run(
            ["systemctl", "--user", "is-enabled", unit], check=False, capture_output=True, text=True
        )
        return out.stdout.strip() != "enabled"

    try:
        _cycle(real, ws, disabled)
        assert not path.exists()
    finally:
        subprocess.run(["systemctl", "--user", "stop", unit], check=False, capture_output=True)
        subprocess.run(["systemctl", "--user", "disable", unit], check=False, capture_output=True)
        if path.exists():
            path.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, capture_output=True)


@pytest.mark.skipif(
    not (REAL and sys.platform == "darwin"), reason="real launchd test: macOS + ORCH_SERVICES_REAL=1"
)
def test_real_launchd_job_that_ends_stays_stopped(real, ws):
    """A job that ends with exit code 0 is done: launchd does not start it again; a crash still does (ORCH-1844)."""
    from pathlib import Path

    label = f"ch.orch.svc.{WID}.once"
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    domain = f"gui/{os.getuid()}"
    log = ws / ".orch/addons/services/logs/once.log"
    mark = ws / "fail-once"
    mark.write_text("x", encoding="utf-8")
    # first run: crash (exit 3) and drop the mark; second run (launchd's restart): print and end with exit 0
    body = (
        "import os, sys; p = sys.argv[1]; print('run', flush=True); "
        "sys.exit(3 if os.path.exists(p) and not os.remove(p) else 0)"
    )
    try:
        code, out = real("add", "Once", "--id", "once", "--", "python3", "-u", "-c", body, str(mark))
        assert code == 0, out
        real("start", "once")
        assert _wait(lambda: log.is_file() and log.read_text(encoding="utf-8").count("run") >= 2, 30)
        time.sleep(15)  # launchd would have started it again within its 10 s throttle
        assert log.read_text(encoding="utf-8").count("run") == 2
        assert _row(real)["state"] == "stopped"
    finally:
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], check=False, capture_output=True)
        subprocess.run(["launchctl", "enable", f"{domain}/{label}"], check=False, capture_output=True)
        if plist.exists():
            plist.unlink()


@pytest.mark.skipif(
    not (REAL and sys.platform == "darwin"), reason="real launchd test: macOS + ORCH_SERVICES_REAL=1"
)
def test_real_found_and_adopt_on_a_mac(real, ws):
    """A throwaway LaunchAgent of its own in the sealed HOME: found, adopted, stopped, started, forgotten."""
    import plistlib
    import secrets
    from pathlib import Path

    label = f"dev.orchtest.found-{secrets.token_hex(4)}"
    agents = Path.home() / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / f"{label}.plist"
    log = Path.home() / f"{label}.log"
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{label}"
    body = plistlib.dumps(
        {
            "Label": label,
            "ProgramArguments": ["/usr/bin/python3", "-u", "-c", SLEEPER[-1]],
            "StandardOutPath": str(log),
            "RunAtLoad": True,
            "KeepAlive": True,
        }
    )
    plist.write_bytes(body)
    try:
        subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True, capture_output=True)
        fid = f"launchd:{label}"

        def item():
            code, out = real("found")
            assert code == 0, out
            return {i["id"]: i for i in out["found"]}.get(fid)

        assert _wait(lambda: (item() or {}).get("running") is True), item()
        found_pid = item()["how"]["pid"]
        code, out = real("adopt", fid, "--name", "Throwaway job")
        assert code == 0, out
        sid = out["service"]["id"]
        assert sid == "throwaway-job" and out["service"]["state"] == "running"
        assert out["service"]["pid"] == found_pid  # not restarted
        assert plist.read_bytes() == body
        assert item() is None  # managed now, no longer found

        code, out = real("stop", sid)
        assert code == 0 and out["service"]["state"] == "stopped", out
        assert _wait(lambda: not _alive(found_pid))
        code, out = real("start", sid)
        assert code == 0, out
        assert _wait(lambda: _row(real)["state"] == "running"), _row(real)
        assert _wait(lambda: log.is_file() and "hello from the service" in log.read_text(encoding="utf-8"))
        code, out = real("log", sid)
        assert "hello from the service" in out["lines"]
        assert plist.read_bytes() == body

        code, out = real("remove", sid)
        assert code == 0 and out["forgotten"] is True, out
        assert plist.read_bytes() == body
        still = subprocess.run(["launchctl", "print", target], check=False, capture_output=True)
        assert still.returncode == 0  # the job is still there
        assert (item() or {}).get("id") == fid  # found again
    finally:
        subprocess.run(["launchctl", "bootout", target], check=False, capture_output=True)
        subprocess.run(["launchctl", "enable", target], check=False, capture_output=True)
        if plist.exists():
            plist.unlink()
        if log.exists():
            log.unlink()


@pytest.mark.skipif(
    not (REAL and sys.platform.startswith("linux")), reason="real systemd test: Linux + ORCH_SERVICES_REAL=1"
)
def test_real_found_and_adopt_on_linux(real, ws, monkeypatch):
    """A throwaway user unit of its own: found, adopted, stopped, started, forgotten (unit file untouched)."""
    import pwd
    import secrets
    from pathlib import Path

    # The user service manager reads only the real account's unit folder, never the test's temp HOME.
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    monkeypatch.setenv("HOME", str(home))
    from orch_services import found

    # the real account's units are hidden from a test install (#1613); this throwaway unit is the test's own
    monkeypatch.setattr(found, "_test_home_on_real_account", lambda: False)
    unit = f"orchtest-found-{secrets.token_hex(4)}.service"
    units = home / ".config" / "systemd" / "user"
    made = [d for d in (home / ".config", home / ".config" / "systemd", units) if not d.exists()]
    units.mkdir(parents=True, exist_ok=True)
    path = units / unit
    log = ws / f"{unit}.log"
    body = (
        "[Unit]\nDescription=Throwaway test job\n\n[Service]\n"
        f'ExecStart=/usr/bin/python3 -u -c "{SLEEPER[-1]}"\n'
        f"StandardOutput=append:{log}\nRestart=on-failure\n\n[Install]\nWantedBy=default.target\n"
    ).encode()
    path.write_bytes(body)

    def sc(*a):
        return subprocess.run(["systemctl", "--user", *a], check=False, capture_output=True, text=True)

    try:
        sc("daemon-reload")
        assert sc("start", unit).returncode == 0
        fid = f"systemd:{unit}"

        def item():
            code, out = real("found")
            assert code == 0, out
            return {i["id"]: i for i in out["found"]}.get(fid)

        assert _wait(lambda: (item() or {}).get("running") is True), item()
        found_pid = item()["how"]["pid"]
        code, out = real("adopt", fid, "--name", "Throwaway job")
        assert code == 0, out
        sid = out["service"]["id"]
        assert out["service"]["state"] == "running"
        assert out["service"]["pid"] == found_pid  # not restarted
        assert path.read_bytes() == body
        assert item() is None  # managed now, no longer found

        code, out = real("stop", sid)
        assert code == 0 and out["service"]["state"] == "stopped", out
        assert _wait(lambda: not _alive(found_pid))
        code, out = real("start", sid)
        assert code == 0, out
        assert _wait(lambda: _row(real)["state"] == "running"), _row(real)
        assert _wait(lambda: log.is_file() and "hello from the service" in log.read_text(encoding="utf-8"))
        assert path.read_bytes() == body

        code, out = real("remove", sid)
        assert code == 0 and out["forgotten"] is True, out
        assert path.read_bytes() == body
        assert sc("is-active", unit).stdout.strip() == "active"  # the job is still there
        assert (item() or {}).get("id") == fid  # found again
    finally:
        sc("stop", unit)
        if path.exists():
            path.unlink()
        sc("daemon-reload")
        for d in reversed(made):
            d.rmdir()


@pytest.mark.skipif(
    not (REAL and sys.platform == "win32"), reason="real Task Scheduler test: Windows + ORCH_SERVICES_REAL=1"
)
def test_real_windows(real, ws):
    import xml.etree.ElementTree as ET

    task = f"\\orch\\orch-svc-{WID}-sleeper"
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

    def schtasks(*a):
        return subprocess.run(["schtasks", *a], check=False, capture_output=True, creationflags=0x08000000)

    def disabled():
        raw = schtasks("/Query", "/TN", task, "/XML").stdout
        # schtasks prints the XML in the console code page (or UTF-16): only ASCII tags are read here
        text = raw.decode("utf-16") if b"\x00" in raw else raw.decode("latin-1")
        root = ET.fromstring(text[text.index("<Task") :])
        on = root.find(".//t:LogonTrigger/t:Enabled", ns)  # Task Scheduler leaves out the default (true)
        return on is not None and on.text == "false"

    try:
        _cycle(real, ws, disabled)
        assert schtasks("/Query", "/TN", task).returncode != 0  # the task is gone
    finally:
        from orch_services import keeper, winproc

        run = keeper.read_run(ws / ".orch/addons/services/keeper/sleeper.json") or {}
        winproc.end(run.get("keeper"), run.get("keeper_start"))
        winproc.end(run.get("pid"), run.get("pid_start"))
        schtasks("/Delete", "/TN", task, "/F")

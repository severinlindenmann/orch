"""The real platform tool, once per platform: skipped unless on that platform AND ORCH_SERVICES_REAL=1.

The plist or unit lands under the test's HOME (a temp folder); the test removes it by its exact path at the end."""

import json
import os
import subprocess
import sys
import time

import pytest
from conftest import WID

REAL = os.environ.get("ORCH_SERVICES_REAL") == "1"
SLEEPER = ["python3", "-u", "-c", "print('hello from the service', flush=True); import time; time.sleep(600)"]


def _wait(cond, seconds=15.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.25)
    return cond()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
    assert log.is_file()


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
def test_real_systemd(real, ws):
    from pathlib import Path

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

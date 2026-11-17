"""The Linux driver through the real commands, against a fake `systemctl` on PATH (runs on any computer).

The fake keeps unit state in a JSON file and refuses a unit that has no file under ~/.config/systemd/user or was
not loaded with daemon-reload, like systemd does."""

import json
import os
import sys
from pathlib import Path

import pytest
from conftest import WID, jrun

FAKE = r"""#!{python}
import json, os, sys
from pathlib import Path
state_file = Path(os.environ["FAKE_SD_STATE"])
st = json.loads(state_file.read_text()) if state_file.exists() else {{"units": {{}}, "loaded": [], "calls": []}}
args = sys.argv[1:]
st["calls"].append(args)
def save():
    state_file.write_text(json.dumps(st))
if not args or args[0] != "--user":
    print("only --user", file=sys.stderr); save(); sys.exit(1)
verb, rest = args[1], args[2:]
units = Path(os.environ["HOME"]) / ".config/systemd/user"
if verb == "show-environment":
    save(); sys.exit(0)
if verb == "daemon-reload":
    st["loaded"] = sorted(p.name for p in units.glob("*.service")) if units.is_dir() else []
    save(); sys.exit(0)
unit = rest[0]
u = st["units"].setdefault(unit, {{"active": False, "enabled": False}})
if verb in ("start", "restart", "stop", "enable", "disable") and unit not in st["loaded"]:
    print(f"Unit {{unit}} not found.", file=sys.stderr); save(); sys.exit(5)
if verb in ("start", "restart"):
    u["active"] = True
elif verb == "stop":
    u["active"] = False
elif verb == "enable":
    u["enabled"] = True
elif verb == "disable":
    u["enabled"] = False
elif verb == "reset-failed":
    pass
elif verb == "show":
    if "--timestamp=utc" not in rest:
        print("unknown option", file=sys.stderr); save(); sys.exit(1)
    print("ActiveState=" + ("active" if u["active"] else "inactive"))
    print("MainPID=" + ("777" if u["active"] else "0"))
    print("ActiveEnterTimestamp=Tue 2026-11-17 16:19:15 UTC")
    print("InactiveEnterTimestamp=Tue 2026-11-17 15:00:00 UTC")
save()
"""

# loginctl: Linger kept in a file ("no" until enable-linger); FAKE_LG_REFUSE=1 makes enable-linger fail.
FAKE_LOGINCTL = r"""#!{python}
import os, sys
from pathlib import Path
f = Path(os.environ["FAKE_LG_STATE"])
args = sys.argv[1:]
with open(str(f) + ".calls", "a") as log:
    log.write(" ".join(args) + "\n")
if args[:1] == ["show-user"]:
    print(f.read_text().strip() if f.exists() else "no")
elif args == ["enable-linger"]:
    if os.environ.get("FAKE_LG_REFUSE") == "1":
        print("Could not enable linger: Access denied", file=sys.stderr); sys.exit(1)
    f.write_text("yes")
else:
    sys.exit(1)
"""


@pytest.fixture
def sd(tmp_path, monkeypatch, ws):
    from orch_services import drivers
    from orch_services.drivers.systemd import Systemd

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tool = bin_dir / "systemctl"
    tool.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
    tool.chmod(0o755)
    lg = bin_dir / "loginctl"
    lg.write_text(FAKE_LOGINCTL.format(python=sys.executable), encoding="utf-8")
    lg.chmod(0o755)
    monkeypatch.setenv("FAKE_LG_STATE", str(tmp_path / "linger"))
    state = tmp_path / "sd-state.json"
    monkeypatch.setenv("FAKE_SD_STATE", str(state))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}")
    monkeypatch.setattr(drivers, "get", lambda: Systemd())

    def read():
        return json.loads(state.read_text(encoding="utf-8"))

    return read


@pytest.fixture
def scli(ws, sd, capsys):
    from orch_services.cli import main

    def run(*argv):
        code = main([*argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    return run


def test_linux_start_stop_restart_and_auto(scli, sd, ws):
    unit = f"orch-svc-{WID}-web.service"
    path = Path.home() / ".config/systemd/user" / unit
    code, out = jrun(scli, "add", "Web", "--id", "web", "--", "python3", "-m", "http.server")
    assert code == 0, out
    assert path.is_file() and "WorkingDirectory=" in path.read_text(encoding="utf-8")
    assert out["service"]["state"] == "stopped" and sd()["units"][unit]["enabled"] is False

    code, out = jrun(scli, "start", "web")
    assert code == 0 and out["service"]["state"] == "running"
    assert out["service"]["since"] == "2026-11-17T16:19:15Z" and out["service"]["pid"] == 777
    code, out = jrun(scli, "stop", "web")
    assert out["service"]["state"] == "stopped" and out["service"]["since"] == "2026-11-17T15:00:00Z"
    code, out = jrun(scli, "restart", "web")
    assert out["service"]["state"] == "running"
    code, out = jrun(scli, "auto", "web", "on")
    assert code == 0 and sd()["units"][unit]["enabled"] is True
    code, out = jrun(scli, "auto", "web", "off")
    assert code == 0 and sd()["units"][unit]["enabled"] is False

    code, out = jrun(scli, "remove", "web")
    assert code == 0 and not path.exists()
    assert all(c[0] == "--user" for c in sd()["calls"])  # never the system manager, never sudo


def test_linux_refuses_when_systemctl_is_missing(ws, monkeypatch, fake, capsys, tmp_path):
    from orch_services import drivers
    from orch_services.cli import main
    from orch_services.drivers.systemd import Systemd

    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setattr(drivers, "get", lambda: Systemd())
    code = main(["add", "Web", "--id", "web", "--json", "--", "/bin/sh"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2
    assert out["error"] == "This computer cannot keep services running for you: systemctl is missing."


def test_linux_add_keeps_services_running_after_logout(scli, sd, ws, tmp_path):
    """Owner 17 Nov (ORCH-328 q2): orch switches linger on by itself, for the person's own account, in one line."""
    linger = tmp_path / "linger"
    code, out = jrun(scli, "add", "Web", "--id", "web", "--", "python3", "-m", "http.server")
    assert code == 0, out
    assert out["note"] == "Your services now keep running after you log out and start again after a restart."
    assert linger.read_text() == "yes"
    code, out = jrun(scli, "add", "Api", "--id", "api", "--", "python3", "-m", "http.server")
    assert code == 0 and "note" not in out  # already on: nothing said, nothing changed
    calls = (tmp_path / "linger.calls").read_text().splitlines()
    assert calls.count("enable-linger") == 1  # never another user's name, never sudo


def test_linux_add_still_works_when_keeping_running_is_refused(scli, sd, ws, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_LG_REFUSE", "1")
    code, out = jrun(scli, "add", "Web", "--id", "web", "--", "python3", "-m", "http.server")
    assert code == 0, out
    assert out["service"]["id"] == "web"
    assert out["note"] == "This computer did not allow it: your services stop when you log out."
    code, text, _ = scli("list")
    assert code == 0 and "web" in text

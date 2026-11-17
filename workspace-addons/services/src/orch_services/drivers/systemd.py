"""Linux: a systemd user unit in ~/.config/systemd/user, run by the person's own service manager (`--user`).

Unit orch-svc-<workspace id>-<id>.service, Restart=on-failure, output appended to the workspace log file.
Starts by itself = `systemctl --user enable` (WantedBy=default.target)."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from . import Driver, Spec, Status, Unavailable, adopted_gone, run_tool, tool_failed


def unit_name(spec: Spec) -> str:
    if spec.external:
        return spec.external
    return f"orch-svc-{spec.workspace_id}-{spec.sid}.service"


def _spec_escape(s: str) -> str:
    """systemd expands %x specifiers in every setting: a literal % is %%."""
    return s.replace("%", "%%")


def quote(arg: str) -> str:
    """One ExecStart word in double quotes: backslash and quote escaped, $ and % kept literal."""
    s = arg.replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$")
    return '"' + _spec_escape(s) + '"'


def render(spec: Spec) -> str:
    # WorkingDirectory= and append: take the rest of the line as the path (quotes would become part of it), so
    # those paths are written as they are with % escaped; spaces and umlauts are fine there.
    env = "".join(f"Environment={quote(f'{k}={v}')}\n" for k, v in spec.env.items())
    return (
        "# Written by orch services; changes here are replaced. Manage it with: orch services\n"
        "[Unit]\n"
        f"Description={_spec_escape(spec.name)} (orch service)\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={' '.join(quote(a) for a in spec.argv)}\n"
        f"WorkingDirectory={_spec_escape(str(spec.cwd))}\n"
        f"{env}"
        f"StandardOutput=append:{_spec_escape(str(spec.log))}\n"
        f"StandardError=append:{_spec_escape(str(spec.log))}\n"
        "Restart=on-failure\n"
        "RestartSec=2\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _utc(text: str) -> str | None:
    """'Tue 2026-11-17 16:19:15 UTC' -> RFC 3339; empty or other forms -> None."""
    parts = text.split()
    if len(parts) < 3 or parts[-1] != "UTC":
        return None
    try:
        t = datetime.strptime(f"{parts[-3]} {parts[-2]}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class Systemd(Driver):
    name = "systemd"

    def __init__(self) -> None:
        self.tool = shutil.which("systemctl") or "systemctl"

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return run_tool([self.tool, "--user", *args])

    def _do(self, what: str, *args: str) -> None:
        cp = self._run(*args)
        if cp.returncode != 0:
            raise tool_failed(what, cp)

    def _write(self, spec: Spec) -> None:
        if spec.external:  # adopted: the person's own unit file is never rewritten
            return
        p = self.entry_path(spec)
        p.parent.mkdir(parents=True, exist_ok=True)
        spec.log.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(render(spec), encoding="utf-8")
        os.replace(tmp, p)
        self._do("reload the service list", "daemon-reload")

    def check(self) -> None:
        if not shutil.which("systemctl"):
            raise Unavailable("systemctl is missing")
        if self._run("show-environment").returncode != 0:
            raise Unavailable("the service manager of your account is not running")

    def keep_running(self) -> str | None:
        """Owner 17 Nov (ORCH-328 q2): without linger the person's service manager stops at logout and starts again
        only at their next login, so their services stop too. Switch it on for the person's own account (no admin
        rights needed) and say so in one line; None when it is already on or this computer has no loginctl."""
        tool = shutil.which("loginctl")
        if not tool:
            return None
        cp = run_tool([tool, "show-user", str(os.getuid()), "--property=Linger", "--value"])
        if cp.returncode == 0 and cp.stdout.strip() == "yes":
            return None
        if run_tool([tool, "enable-linger"]).returncode == 0:
            return "Your services now keep running after you log out and start again after a restart."
        return "This computer did not allow it: your services stop when you log out."

    def entry_path(self, spec: Spec) -> Path:
        if spec.external_path:
            return spec.external_path
        return Path.home() / ".config" / "systemd" / "user" / unit_name(spec)

    def install(self, spec: Spec) -> None:
        self._write(spec)
        self.set_auto(spec, write=False)

    def start(self, spec: Spec) -> None:
        if not self.entry_path(spec).exists():
            if spec.external:
                raise adopted_gone(spec)
            self._write(spec)
        self._do("start it", "start", unit_name(spec))

    def stop(self, spec: Spec) -> None:
        if self.entry_path(spec).exists():
            self._do("stop it", "stop", unit_name(spec))

    def restart(self, spec: Spec) -> None:
        if not self.entry_path(spec).exists():
            if spec.external:
                raise adopted_gone(spec)
            self._write(spec)
        self._do("restart it", "restart", unit_name(spec))

    def set_auto(self, spec: Spec, write: bool = True) -> None:
        if write:
            self._write(spec)
        verb = "enable" if spec.auto else "disable"
        self._do("change whether it starts by itself", verb, unit_name(spec))

    def status(self, spec: Spec) -> Status:
        props = ["ActiveState", "MainPID", "ActiveEnterTimestamp", "InactiveEnterTimestamp"]
        args = ["show", unit_name(spec), *(f"--property={p}" for p in props)]
        cp = self._run(*args, "--timestamp=utc")
        if cp.returncode != 0:  # systemd before 248 has no --timestamp: no `since` then
            cp = self._run(*args)
        if cp.returncode != 0:
            return Status(running=False)
        v = dict(line.split("=", 1) for line in cp.stdout.splitlines() if "=" in line)
        running = v.get("ActiveState") == "active"
        pid = int(v["MainPID"]) if v.get("MainPID", "").isdigit() and int(v["MainPID"]) > 0 else None
        since = _utc(v.get("ActiveEnterTimestamp" if running else "InactiveEnterTimestamp", ""))
        return Status(running=running, pid=pid if running else None, since=since)

    def uninstall(self, spec: Spec) -> None:
        if (
            spec.external
        ):  # never reached through the CLI (remove only forgets an adopted one); kept safe anyway
            return
        p = self.entry_path(spec)
        if p.exists():
            self._run("stop", unit_name(spec))
            self._run("disable", unit_name(spec))
            p.unlink()
        self._run("daemon-reload")
        self._run("reset-failed", unit_name(spec))

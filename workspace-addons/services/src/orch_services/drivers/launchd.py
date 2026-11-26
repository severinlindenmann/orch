"""macOS: a LaunchAgent in the person's ~/Library/LaunchAgents, run by launchd in their own login session.

Label ch.orch.svc.<workspace id>.<id>. The plist always says KeepAlive with SuccessfulExit false (launchd brings it
back after a crash while it is loaded; a job that ends with exit code 0 stays stopped, like systemd's Restart=on-failure
and the Windows keeper, ORCH-1844) and RunAtLoad = starts by itself. Starts by itself off also disables the label (`launchctl disable`), so
launchd does not load the plist at the next login; a start enables it for the moment and disables it again."""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from . import Driver, Spec, Status, Unavailable, adopted_gone, run_tool, tool_failed

NOT_LOADED = (3, 113)  # "Could not find service" (113) / "No such process" (3)


def label(spec: Spec) -> str:
    return spec.external or f"ch.orch.svc.{spec.workspace_id}.{spec.sid}"


def disabled_labels(text: str) -> set[str]:
    """Labels `launchctl print-disabled <domain>` lists as switched off. Newer macOS writes `"x" => disabled`,
    older `"x" => true`. A switched-off label is not loaded at login, whatever RunAtLoad says (ORCH-1003)."""
    out = set()
    for m in re.finditer(r'^\s*"([^"\n]+)"\s*=>\s*(\S+)', text, re.MULTILINE):
        if m.group(2) in ("disabled", "true"):
            out.add(m.group(1))
    return out


def render(spec: Spec) -> bytes:
    """The plist. XML escapes every path and word; nothing is passed through a shell."""
    data = {
        "Label": label(spec),
        "ProgramArguments": list(spec.argv),
        "WorkingDirectory": str(spec.cwd),
        "StandardOutPath": str(spec.log),
        "StandardErrorPath": str(spec.log),
        "RunAtLoad": bool(spec.auto),
        "KeepAlive": {"SuccessfulExit": False},  # True also starts a job that ended on its own (ORCH-1844)
        "ProcessType": "Background",
    }
    if spec.env:
        data["EnvironmentVariables"] = dict(spec.env)
    return plistlib.dumps(data, fmt=plistlib.FMT_XML, sort_keys=False)


class Launchd(Driver):
    name = "launchd"

    def __init__(self) -> None:
        self.tool = shutil.which("launchctl") or "/bin/launchctl"
        self.domain = f"gui/{os.getuid()}"

    # -- helpers
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return run_tool([self.tool, *args])

    def _target(self, spec: Spec) -> str:
        return f"{self.domain}/{label(spec)}"

    def _write(self, spec: Spec) -> None:
        if spec.external:  # adopted: the person's own plist is never rewritten
            return
        p = self.entry_path(spec)
        p.parent.mkdir(parents=True, exist_ok=True)
        spec.log.parent.mkdir(parents=True, exist_ok=True)
        spec.cwd.mkdir(parents=True, exist_ok=True)  # the home folder of a job on an external disk
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_bytes(render(spec))
        os.replace(tmp, p)

    def _print(self, spec: Spec) -> subprocess.CompletedProcess:
        return self._run("print", self._target(spec))

    def _loaded(self, spec: Spec) -> bool:
        return self._print(spec).returncode == 0

    def _enable(self, spec: Spec, on: bool) -> None:
        cp = self._run("enable" if on else "disable", self._target(spec))
        if cp.returncode != 0:
            raise tool_failed("change whether it starts by itself", cp)

    # -- interface
    def check(self) -> None:
        if not Path(self.tool).exists():
            raise Unavailable("launchctl is missing")
        cp = self._run("print", self.domain)
        if cp.returncode != 0:
            raise Unavailable("there is no login session for your account (log in on this Mac's screen once)")

    def entry_path(self, spec: Spec) -> Path:
        if spec.external_path:
            return spec.external_path
        return Path.home() / "Library" / "LaunchAgents" / f"{label(spec)}.plist"

    def install(self, spec: Spec) -> None:
        self._write(spec)
        self._enable(spec, spec.auto)

    def start(self, spec: Spec) -> None:
        if not self.entry_path(spec).exists():
            if spec.external:
                raise adopted_gone(spec)
            self._write(spec)
        if self._loaded(spec):
            if not self.status(spec).running:
                cp = self._run("kickstart", self._target(spec))
                if cp.returncode != 0:
                    raise tool_failed("start it", cp)
            return
        if (
            not spec.external
        ):  # not loaded: launchd reads the plist now, so the job gets today's log and folder
            self._write(spec)
        self._enable(spec, True)  # a disabled label cannot be loaded
        cp = self._run("bootstrap", self.domain, str(self.entry_path(spec)))
        if cp.returncode != 0 and not self._loaded(spec):
            raise tool_failed("start it", cp)
        if not self.status(spec).running:  # a taken-over job without RunAtLoad or KeepAlive only loads
            cp = self._run("kickstart", self._target(spec))
            if cp.returncode != 0:
                raise tool_failed("start it", cp)
        if not spec.auto:
            self._enable(spec, False)  # the running job stays; launchd only skips it at the next login

    def stop(self, spec: Spec) -> None:
        if not self._loaded(spec):
            return
        cp = self._run("bootout", self._target(spec))
        if cp.returncode not in (0, *NOT_LOADED) and self._loaded(spec):
            raise tool_failed("stop it", cp)

    def restart(self, spec: Spec) -> None:
        if not self._loaded(spec):
            self.start(spec)
            return
        cp = self._run("kickstart", "-k", self._target(spec))
        if cp.returncode != 0:
            raise tool_failed("restart it", cp)

    def set_auto(self, spec: Spec) -> None:
        self._write(spec)
        self._enable(spec, spec.auto)

    def status(self, spec: Spec) -> Status:
        cp = self._print(spec)
        if cp.returncode != 0:
            return Status(running=False)
        state = re.search(r"^[ \t]*state = (\S+(?: \S+)*)", cp.stdout, re.MULTILINE)  # "spawn scheduled"
        pid = re.search(r"^\s*pid = (\d+)", cp.stdout, re.MULTILINE)
        if not (state and state.group(1) == "running" and pid):
            # launchd says "spawn scheduled" or "xpcproxy" while a job is only being launched (slow under load)
            launching = bool(state) and state.group(1) in ("spawn scheduled", "xpcproxy", "running")
            return Status(running=False, starting=launching)
        n = int(pid.group(1))
        return Status(running=True, pid=n, since=_started(n))

    def switched_off(self, spec: Spec) -> bool:
        cp = self._run("print-disabled", self.domain)
        return cp.returncode == 0 and label(spec) in disabled_labels(cp.stdout)

    def last_exit(self, spec: Spec) -> int | None:
        """`last exit code = N` of `launchctl print` (78: launchd could not open the log or the folder)."""
        cp = self._print(spec)
        m = re.search(r"^\s*last exit code = (\d+)", cp.stdout, re.MULTILINE) if cp.returncode == 0 else None
        return int(m.group(1)) if m else None

    def runs(self, spec: Spec) -> int | None:
        """`runs = N` of `launchctl print` (KeepAlive starts it again after every crash)."""
        cp = self._print(spec)
        m = re.search(r"^\s*runs = (\d+)", cp.stdout, re.MULTILINE) if cp.returncode == 0 else None
        return int(m.group(1)) if m else None

    def uninstall(self, spec: Spec) -> None:
        if (
            spec.external
        ):  # never reached through the CLI (remove only forgets an adopted one); kept safe anyway
            return
        self.stop(spec)
        try:
            self.entry_path(spec).unlink()
        except FileNotFoundError:
            pass


def _started(pid: int) -> str | None:
    """Start time of a process in RFC 3339 UTC, from ps (C locale, local time)."""
    try:
        cp = subprocess.run(
            ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
        t = time.strptime(" ".join(cp.stdout.split()), "%a %b %d %H:%M:%S %Y")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return datetime.fromtimestamp(time.mktime(t), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

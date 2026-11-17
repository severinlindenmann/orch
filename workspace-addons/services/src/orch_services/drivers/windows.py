"""Windows: a scheduled task of the person's own account (no admin rights, no permission prompt).

Task \\orch\\orch-svc-<workspace id>-<id>: runs as the signed-in person only (InteractiveToken, LeastPrivilege), one
trigger "at sign-in of this person" that is on when the service starts by itself. The task starts the keeper
(orch_services.keeper with pythonw, so no window), which keeps the program running, restarts it after a crash and
appends its output to the workspace log. Tried on a Windows 11 VM as a standard user (ORCH-346): Task Scheduler's
own "restart on failure" does not start a crashed program again, and ending a task leaves its child processes
running, so the keeper does both jobs and stop ends the keeper (its job ends the program).

Files: .orch/addons/services/keeper/<id>.json (what to run) and <id>.run.json (written by the keeper)."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

from .. import keeper, winproc
from . import Driver, Spec, Status, Unavailable, run_tool, tool_failed

FOLDER = "\\orch\\"
START_WAIT = 10.0


def task_name(spec: Spec) -> str:
    return f"{FOLDER}orch-svc-{spec.workspace_id}-{spec.sid}"


def settings_path(spec: Spec) -> Path:
    return spec.log.parent.parent / "keeper" / f"{spec.sid}.json"


def python() -> Path:
    """pythonw.exe next to the interpreter orch runs on (same uv tool env, so it stays put across updates)."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.is_file() else exe


def render(spec: Spec, user: str, program: Path) -> str:
    """The task XML. Every word is XML-escaped; the keeper's words are quoted the Windows way."""
    args = subprocess.list2cmdline(["-P", "-m", "orch_services.keeper", str(settings_path(spec))])
    on = "true" if spec.auto else "false"
    u = escape(user)
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        f"  <RegistrationInfo><Description>{escape(spec.name)} (orch service). Manage it with: orch services"
        "</Description></RegistrationInfo>\n"
        f"  <Triggers><LogonTrigger><Enabled>{on}</Enabled><UserId>{u}</UserId></LogonTrigger></Triggers>\n"
        f'  <Principals><Principal id="Author"><UserId>{u}</UserId><LogonType>InteractiveToken</LogonType>'
        "<RunLevel>LeastPrivilege</RunLevel></Principal></Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>true</AllowHardTerminate>\n"
        "    <StartWhenAvailable>false</StartWhenAvailable>\n"
        "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
        "    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>\n"
        "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
        "    <Enabled>true</Enabled>\n"
        "    <Hidden>false</Hidden>\n"
        "    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n"
        "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
        "    <Priority>5</Priority>\n"
        "  </Settings>\n"
        '  <Actions Context="Author"><Exec>'
        f"<Command>{escape(str(program))}</Command>"
        f"<Arguments>{escape(args)}</Arguments>"
        f"<WorkingDirectory>{escape(str(spec.cwd))}</WorkingDirectory>"
        "</Exec></Actions>\n"
        "</Task>\n"
    )


def _since(run: dict) -> str | None:
    s = run.get("since")
    return s if isinstance(s, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", s) else None


class Windows(Driver):
    name = "windows"

    def __init__(self) -> None:
        self.tool = shutil.which("schtasks") or "schtasks"
        self._user: str | None = None

    # -- helpers
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return run_tool([self.tool, *args])

    def user(self) -> str:
        """This account's SID (language-independent), else DOMAIN\\name."""
        if self._user is None:
            sid = None
            who = shutil.which("whoami")
            if who:
                cp = run_tool([who, "/user", "/fo", "csv", "/nh"])
                rows = list(csv.reader(io.StringIO(cp.stdout))) if cp.returncode == 0 else []
                if rows and rows[0] and re.fullmatch(r"S-1-[0-9-]+", rows[0][-1].strip()):
                    sid = rows[0][-1].strip()
            dom, name = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
            self._user = sid or (f"{dom}\\{name}" if dom else name)
        return self._user

    def _write(self, spec: Spec) -> None:
        """Write the keeper's settings and (re)register the task. Re-registering a running task keeps it running."""
        p = settings_path(spec)
        p.parent.mkdir(parents=True, exist_ok=True)
        spec.log.parent.mkdir(parents=True, exist_ok=True)
        data = {"argv": list(spec.argv), "cwd": str(spec.cwd), "log": str(spec.log), "env": dict(spec.env)}
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        xml = p.with_name(f".{spec.sid}.task.xml")
        xml.write_bytes(render(spec, self.user(), python()).encode("utf-16"))
        try:
            cp = self._run("/Create", "/TN", task_name(spec), "/XML", str(xml), "/F")
        finally:
            xml.unlink(missing_ok=True)
        if cp.returncode != 0:
            raise tool_failed("save it in Task Scheduler", cp)

    def _run_info(self, spec: Spec) -> dict | None:
        return keeper.read_run(settings_path(spec))

    def _keeper_alive(self, run: dict | None) -> bool:
        return bool(run) and winproc.is_same(run.get("keeper"), run.get("keeper_start"))

    def _end_all(self, spec: Spec) -> None:
        run = self._run_info(spec)
        if run:
            winproc.end(run.get("keeper"), run.get("keeper_start"))  # first: it would start the program again
            winproc.end(run.get("pid"), run.get("pid_start"))
        keeper.run_file(settings_path(spec)).unlink(missing_ok=True)

    # -- interface
    def check(self) -> None:
        if not shutil.which("schtasks"):
            raise Unavailable("schtasks is missing")
        if sys.platform == "win32" and python().name.lower() != "pythonw.exe":
            raise Unavailable("pythonw.exe is missing next to orch's Python")

    def entry_path(self, spec: Spec) -> Path:
        return settings_path(spec)

    def install(self, spec: Spec) -> None:
        self._write(spec)

    def start(self, spec: Spec) -> None:
        self._write(spec)  # also heals a task whose Python moved
        if self.status(spec).running:
            return
        if not self._keeper_alive(self._run_info(spec)):
            keeper.run_file(settings_path(spec)).unlink(missing_ok=True)
        cp = self._run("/Run", "/TN", task_name(spec))
        if cp.returncode != 0:
            raise tool_failed("start it", cp)
        end = time.monotonic() + START_WAIT
        while time.monotonic() < end and not self.status(spec).running:
            time.sleep(0.2)

    def stop(self, spec: Spec) -> None:
        self._end_all(spec)
        self._run("/End", "/TN", task_name(spec))  # tidies the task's own state; nothing is left to end

    def restart(self, spec: Spec) -> None:
        self.stop(spec)
        self.start(spec)

    def set_auto(self, spec: Spec) -> None:
        self._write(spec)

    def status(self, spec: Spec) -> Status:
        run = self._run_info(spec)
        if not self._keeper_alive(run) or not winproc.is_same(run.get("pid"), run.get("pid_start")):
            return Status(running=False)
        return Status(running=True, pid=run["pid"], since=_since(run))

    def uninstall(self, spec: Spec) -> None:
        self.stop(spec)
        cp = self._run("/Delete", "/TN", task_name(spec), "/F")
        if cp.returncode != 0 and self._run("/Query", "/TN", task_name(spec)).returncode == 0:
            raise tool_failed("remove it from Task Scheduler", cp)
        settings_path(spec).unlink(missing_ok=True)

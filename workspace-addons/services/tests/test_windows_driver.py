"""The Windows driver through the real commands, against a fake `schtasks` (and `whoami`) on PATH, on any computer.

The fake keeps each task's XML in a folder and, on /Run, starts the task's action like Task Scheduler does: so the
real keeper runs and keeps a real program. The real Task Scheduler run is in test_real_driver.py (Windows only)."""

import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from conftest import WID, jrun

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
SID = "S-1-5-21-1111-2222-3333-1001"

FAKE = r"""#!{python}
import json, os, shlex, subprocess, sys
import xml.etree.ElementTree as ET
from pathlib import Path
d = Path(os.environ["FAKE_ST_DIR"])
tasks = d / "tasks"
tasks.mkdir(parents=True, exist_ok=True)
args = sys.argv[1:]
with open(d / "calls.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(args) + "\n")
def opt(name):
    return args[args.index(name) + 1] if name in args else None
name = opt("/TN")
file = tasks / ((name or "").strip("\\").replace("\\", "__") + ".xml")
verb = args[0] if args else ""
if verb == "/Create":
    if not name or not name.startswith("\\orch\\"):
        print("ERROR: wrong folder", file=sys.stderr); sys.exit(1)
    text = Path(opt("/XML")).read_bytes().decode("utf-16")
    ET.fromstring(text.split("\n", 1)[1])  # must be valid XML
    file.write_text(text, encoding="utf-8")
    print(f'SUCCESS: The scheduled task "{{name}}" has successfully been created.')
elif not file.exists():
    print("ERROR: The system cannot find the file specified.", file=sys.stderr); sys.exit(1)
elif verb == "/Run":
    ns = {{"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}}
    root = ET.fromstring(file.read_text(encoding="utf-8").split("\n", 1)[1])
    cmd = root.find(".//t:Exec/t:Command", ns).text
    words = shlex.split(root.find(".//t:Exec/t:Arguments", ns).text)
    cwd = root.find(".//t:Exec/t:WorkingDirectory", ns).text
    subprocess.Popen([cmd, *words], cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
elif verb == "/Delete":
    file.unlink()
elif verb in ("/End", "/Query"):
    pass
"""
FAKE_WHOAMI = r"""#!{python}
print('"windev\\user","{sid}"')
"""
SLEEPER = "print('hello from the service', flush=True); import time; time.sleep(600)"


def _tool(bin_dir: Path, name: str, body: str) -> None:
    script = bin_dir / f"{name}.py"
    script.write_text(body, encoding="utf-8")
    if sys.platform == "win32":
        (bin_dir / f"{name}.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        exe = bin_dir / name
        exe.write_text(body, encoding="utf-8")
        exe.chmod(0o755)


@pytest.fixture
def st(tmp_path, monkeypatch, ws):
    from orch_services import drivers
    from orch_services.drivers import windows
    from orch_services.drivers.windows import Windows

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _tool(bin_dir, "schtasks", FAKE.format(python=sys.executable))
    _tool(bin_dir, "whoami", FAKE_WHOAMI.format(python=sys.executable, sid=SID))
    state = tmp_path / "st"
    monkeypatch.setenv("FAKE_ST_DIR", str(state))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}")
    # the driver takes Windows tools from System32 only; here from the fake folder only (also on Windows)
    monkeypatch.setattr(windows, "system_tool", lambda name: shutil.which(name, path=str(bin_dir)))
    made: list[Windows] = []

    def get():
        d = Windows()
        made.append(d)
        return d

    monkeypatch.setattr(drivers, "get", get)

    class S:
        dir = state

        def calls(self):
            f = state / "calls.jsonl"
            if not f.exists():
                return []
            return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]

        def task(self, sid):
            f = state / "tasks" / f"orch__orch-svc-{WID}-{sid}.xml"
            if not f.exists():
                return None
            return ET.fromstring(f.read_text(encoding="utf-8").split("\n", 1)[1])

    yield S()
    # never leave a keeper or a program behind
    for f in (ws / ".orch/addons/services/keeper").glob("*.run.json"):
        from orch_services import winproc

        d = json.loads(f.read_text(encoding="utf-8"))
        winproc.end(d.get("keeper"), d.get("keeper_start"))
        winproc.end(d.get("pid"), d.get("pid_start"))


@pytest.fixture
def wcli(ws, st, capsys):
    from orch_services.cli import main

    def run(*argv):
        code = main([*argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    return run


def _wait(cond, seconds=15.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


def _alive(pid):
    from orch_services import winproc

    return winproc.started(pid) is not None


def _trigger_on(task) -> bool:
    return task.find(".//t:LogonTrigger/t:Enabled", NS).text == "true"


def test_windows_add_start_restart_auto_stop_remove(wcli, st, ws):
    code, out = jrun(
        wcli, "add", 'Sleeper ä &" Co', "--id", "sleeper", "--", sys.executable, "-u", "-c", SLEEPER
    )
    assert code == 0, out
    assert out["service"]["state"] == "stopped"
    task = st.task("sleeper")
    assert task is not None and not _trigger_on(task)
    # only for this person, without admin rights
    assert task.find(".//t:Principal/t:UserId", NS).text == SID
    assert task.find(".//t:LogonTrigger/t:UserId", NS).text == SID
    assert task.find(".//t:Principal/t:LogonType", NS).text == "InteractiveToken"
    assert task.find(".//t:Principal/t:RunLevel", NS).text == "LeastPrivilege"
    assert task.find(".//t:Settings/t:ExecutionTimeLimit", NS).text == "PT0S"
    assert 'Sleeper ä &" Co' in task.find(".//t:Description", NS).text
    assert task.find(".//t:Exec/t:WorkingDirectory", NS).text == str(ws.resolve())
    settings = ws / ".orch/addons/services/keeper/sleeper.json"
    assert f'"{settings}"' in task.find(".//t:Exec/t:Arguments", NS).text  # path with a space is quoted
    cfg = json.loads(settings.read_text(encoding="utf-8"))
    assert Path(cfg["argv"][0]) == Path(os.path.abspath(sys.executable)) and cfg["log"].endswith(
        "sleeper.log"
    )

    code, out = jrun(wcli, "start", "sleeper")
    assert code == 0, out
    assert out["service"]["state"] == "running", out
    pid = out["service"]["pid"]
    assert _alive(pid) and out["service"]["since"]
    log = ws / ".orch/addons/services/logs/sleeper.log"
    assert _wait(lambda: log.is_file() and "hello from the service" in log.read_text(encoding="utf-8"))
    code, out = jrun(wcli, "start", "sleeper")  # already running: nothing new
    assert out["service"]["pid"] == pid

    code, out = jrun(wcli, "restart", "sleeper")
    assert code == 0 and out["service"]["state"] == "running", out
    assert out["service"]["pid"] != pid
    assert _wait(lambda: not _alive(pid))
    pid = out["service"]["pid"]

    code, out = jrun(wcli, "auto", "sleeper", "on")
    assert code == 0 and out["service"]["auto"] is True and _trigger_on(st.task("sleeper"))
    code, out = jrun(wcli, "auto", "sleeper", "off")
    assert code == 0 and out["service"]["auto"] is False and not _trigger_on(st.task("sleeper"))
    assert out["service"]["state"] == "running" and out["service"]["pid"] == pid  # auto does not stop it

    run = json.loads((ws / ".orch/addons/services/keeper/sleeper.run.json").read_text(encoding="utf-8"))
    keeper_pid = run["keeper"]
    code, out = jrun(wcli, "stop", "sleeper")
    assert code == 0 and out["service"]["state"] == "stopped", out
    assert _wait(lambda: not _alive(pid)) and _wait(lambda: not _alive(keeper_pid))

    code, out = jrun(wcli, "remove", "sleeper")
    assert code == 0, out
    assert st.task("sleeper") is None and not settings.exists()
    assert log.is_file()
    verbs = [c[0] for c in st.calls()]
    assert verbs.count("/Run") == 2 and "/Delete" in verbs
    name = f"\\orch\\orch-svc-{WID}-sleeper"
    assert all(c[c.index("/TN") + 1] == name for c in st.calls() if "/TN" in c)


def test_windows_add_with_auto_turns_the_sign_in_trigger_on(wcli, st):
    code, out = jrun(wcli, "add", "Web", "--id", "web", "--auto", "--", sys.executable, "-c", "pass")
    assert code == 0 and out["service"]["auto"] is True, out
    assert _trigger_on(st.task("web"))


def test_windows_refuses_when_schtasks_is_missing(ws, fake, monkeypatch, capsys, tmp_path):
    from orch_services import drivers
    from orch_services.cli import main
    from orch_services.drivers import windows
    from orch_services.drivers.windows import Windows

    monkeypatch.setattr(windows, "system_tool", lambda name: None)
    monkeypatch.setattr(drivers, "get", lambda: Windows())
    code = main(["add", "Web", "--id", "web", "--json", "--", sys.executable, "-c", "pass"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and "cannot keep services running" in out["error"] and "schtasks" in out["error"]
    assert not (ws / ".orch/addons/services/services/web.json").exists()


def test_windows_is_picked_on_windows(monkeypatch):
    from orch_services import drivers
    from orch_services.drivers import windows  # noqa: F401 - load it on this platform first (no kernel32 here)

    monkeypatch.setattr(sys, "platform", "win32")
    assert drivers.get().name == "windows"


def test_found_on_windows_says_so_in_one_sentence(cli, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    code, out = jrun(cli, "found")
    assert code == 0 and out["found"] == [] and "Windows" in out["note"]
    code, text, _ = cli("found")
    assert code == 0 and text.strip() == out["note"]


# ---------------------------------------------------------------- the keeper on its own


def _settings(tmp_path: Path, argv: list[str]) -> Path:
    d = tmp_path / "keeper dir ü"
    d.mkdir()
    s = d / "svc.json"
    s.write_text(
        json.dumps(
            {"argv": argv, "cwd": str(tmp_path), "log": str(tmp_path / "logs" / "svc.log"), "env": {}}
        ),
        encoding="utf-8",
    )
    return s


def test_keeper_starts_a_crashed_program_again_and_stops_on_exit_0(tmp_path):
    from orch_services import keeper

    count = tmp_path / "count"
    prog = (
        "import pathlib, sys; p = pathlib.Path(sys.argv[1]); n = int(p.read_text()) + 1 if p.exists() else 1; "
        "p.write_text(str(n)); print('run', n, flush=True); sys.exit(3 if n < 3 else 0)"
    )
    s = _settings(tmp_path, [sys.executable, "-c", prog, str(count)])
    waits: list[float] = []
    assert keeper.keep(s, sleep=waits.append) == 0
    assert count.read_text() == "3"
    assert waits == [2.0, 4.0]  # backs off while it keeps crashing
    log = (tmp_path / "logs" / "svc.log").read_text(encoding="utf-8")
    assert "run 1" in log and "run 3" in log
    assert log.count("stopped with code 3") == 2
    run = keeper.read_run(s)
    assert run["pid"] is None and run["exit"] == 0


def test_keeper_notes_a_program_that_cannot_start(tmp_path):
    from orch_services import keeper

    s = _settings(tmp_path, [str(tmp_path / "missing program")])

    class Done(Exception):
        pass

    def sleep(_):
        raise Done

    with pytest.raises(Done):
        keeper.keep(s, sleep=sleep)
    assert "Could not start the program" in (tmp_path / "logs" / "svc.log").read_text(encoding="utf-8")


def test_a_second_keeper_leaves_the_first_alone(tmp_path):
    from orch_services import keeper, winproc

    s = _settings(tmp_path, [sys.executable, "-c", "raise SystemExit(5)"])
    ppid = os.getppid()
    keeper.run_file(s).write_text(json.dumps({"keeper": ppid, "keeper_start": winproc.started(ppid)}))
    assert keeper.keep(s, sleep=lambda _: pytest.fail("must not run")) == 0
    assert not (tmp_path / "logs" / "svc.log").exists()


def test_keeper_back_off():
    from orch_services.keeper import FIRST_DELAY, MAX_DELAY, next_delay

    assert next_delay(FIRST_DELAY, 1) == 4.0
    assert next_delay(40, 1) == MAX_DELAY
    assert next_delay(MAX_DELAY, 120) == FIRST_DELAY


def test_start_replaces_a_keeper_that_waits_after_a_crash(wcli, st, ws):
    from orch_services import winproc

    code, out = jrun(wcli, "add", "Sleeper", "--id", "sleeper", "--", sys.executable, "-u", "-c", SLEEPER)
    assert code == 0, out
    # a keeper in its wait after a crash: alive, no program
    waiting = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        run = ws / ".orch/addons/services/keeper/sleeper.run.json"
        run.write_text(
            json.dumps({"keeper": waiting.pid, "keeper_start": winproc.started(waiting.pid), "pid": None})
        )
        code, out = jrun(wcli, "start", "sleeper")
        assert code == 0 and out["service"]["state"] == "running", out
        assert waiting.wait(timeout=10) is not None  # the waiting keeper was ended
        assert json.loads(run.read_text(encoding="utf-8"))["keeper"] != waiting.pid
    finally:
        if waiting.poll() is None:
            waiting.kill()


def test_end_leaves_a_process_with_another_start_alone():
    from orch_services import winproc

    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert winproc.end(p.pid, (winproc.started(p.pid) or 0) + 12345) is False
        assert winproc.end(p.pid, None) is False and winproc.end(None, 1) is False
        assert p.poll() is None
        assert winproc.end(p.pid, winproc.started(p.pid)) is True
        assert p.wait(timeout=10) is not None
    finally:
        if p.poll() is None:
            p.kill()


def test_keeper_ends_once_the_service_is_removed(tmp_path):
    from orch_services import keeper

    s = _settings(tmp_path, [sys.executable, "-c", "raise SystemExit(4)"])
    waits: list[float] = []

    def sleep(d):
        waits.append(d)
        s.unlink()  # removed while the keeper waits after a crash

    assert keeper.keep(s, sleep=sleep) == 0
    assert waits == [2.0]

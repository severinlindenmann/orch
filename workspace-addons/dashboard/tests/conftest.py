import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
CONTRACTS = HERE.parents[2] / "contracts" / "review"


def _ticket(i, title, status, **kw):
    t = json.loads((CONTRACTS / "ticket.example.json").read_text())
    t.update(id=i, title=title, status=status, **kw)
    return t


@pytest.fixture(autouse=True, scope="session")
def _isolated_orch_home():
    """`orch` children of these tests (run_orch, the act ops) must never fall back to the real ~/.orch-tool
    (ORCH_HOME unset = real folder, and a trace line in its .fallback-trace.log). One private home for the
    session, under ~/.orch-test (a trusted place: under the user's home, outside every cwd and any .git/.orch
    parent), removed by its exact path at the end."""
    import os
    import shutil
    import tempfile

    base = Path.home() / ".orch-test"
    base.mkdir(exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="dash-home-", dir=base))
    old = os.environ.get("ORCH_HOME")
    os.environ["ORCH_HOME"] = str(home)
    yield home
    if old is None:
        os.environ.pop("ORCH_HOME", None)
    else:
        os.environ["ORCH_HOME"] = old
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "Pilatus"
    tdir = root / ".orch" / "tickets"
    tdir.mkdir(parents=True)
    ex = json.loads((CONTRACTS / "ticket.example.json").read_text())
    (tdir / f"{ex['id']}.json").write_text(json.dumps(ex))
    rec = _ticket(
        "t_weekly01",
        "Weekly report",
        "waiting",
        checklist=[],
        questions=[],
        waiting_on=None,
        ext={"scheduler": {"cron": "0 8 * * 1"}},
    )
    (tdir / "t_weekly01.json").write_text(json.dumps(rec))
    for i, (title, st) in enumerate(
        [("Open one", "open"), ("Done one", "done"), ("Dropped one", "dropped"), ("Active one", "active")]
    ):
        t = _ticket(f"t_other{i:03d}x", title, st, waiting_on=None, checklist=[], questions=[], ext={})
        (tdir / f"{t['id']}.json").write_text(json.dumps(t))
    (tdir / "t_broken0001.json").write_text("{not json")
    (root / ".orch" / "inbox").mkdir()
    msgs = json.loads((CONTRACTS / "message.examples.json").read_text())
    for m in msgs:
        m.pop("_note", None)
        (root / ".orch" / "inbox" / f"{m['id']}.json").write_text(json.dumps(m))
    (root / ".orch" / "inbox-seen.json").write_text(json.dumps({msgs[0]["id"]: "2026-11-04T10:00:00Z"}))
    d = root / ".agents" / "skills" / "orch-relay"
    d.mkdir(parents=True)
    (d / "workspaces.json").write_text((CONTRACTS / "workspaces.example.json").read_text())
    (root / ".orch" / "secrets").mkdir()
    (root / ".orch" / "secrets" / "relay.json").write_text('{"token": "orn_SECRET"}')
    return root


@pytest.fixture
def server(ws):
    import threading

    from orch_dashboard.server import make_server

    srv = make_server(ws, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


VIEW = CONTRACTS / "scheduler.view.example.json"


@pytest.fixture
def fake_orch(tmp_path):
    """A fake `orch` command. Behaviour per file in its folder: addons.json (list), view.json (stdout of
    `scheduler view --json`), mode.txt (ok | slow | fail | junk | big)."""
    d = tmp_path / "fakeorch"
    d.mkdir()
    (d / "addons.json").write_text(
        json.dumps(
            [
                {
                    "name": "scheduler",
                    "version": "0.2.0",
                    "description": "x",
                    "source": "built-in",
                    "active": True,
                    "dashboard": {"label": "Schedule", "icon": "clock", "order": 10},
                    "background": True,
                    "ticket_view": [
                        {"field": "cron", "label": "Repeats", "format": "cron-human"},
                        {"field": "agents", "label": "Agents", "format": "chips"},
                    ],
                },
                {
                    "name": "wiki",
                    "version": "0.1.0",
                    "description": "y",
                    "source": "built-in",
                    "active": False,
                    "dashboard": {"label": "Wiki", "icon": "book", "order": 20},
                    "background": False,
                    "ticket_view": [],
                },
                {
                    "name": "relay",
                    "version": "0.1.0",
                    "description": "z",
                    "source": "built-in",
                    "active": True,
                    "dashboard": None,
                    "background": False,
                    "ticket_view": [],
                },
            ]
        )
    )
    (d / "view.json").write_text(VIEW.read_text())
    (d / "mode.txt").write_text("ok")
    script = d / "orch"
    script.write_text(f"""#!{sys.executable}
import sys, time, pathlib
d = pathlib.Path(__file__).parent
a = sys.argv[1:]
mode = (d / "mode.txt").read_text().strip()
if a[:2] == ["addon", "list"]:
    print((d / "addons.json").read_text())
elif a[1:] == ["view", "--json"]:
    if mode == "slow": time.sleep(5)
    if mode == "fail": print('{{"error": "x"}}'); sys.exit(2)
    if mode == "junk": print("not json")
    elif mode == "big": print('{{"x": "' + "a" * 300000 + '"}}')
    else: print((d / "view.json").read_text())
else:
    sys.exit(2)
""")
    script.chmod(0o755)
    return script


# orch_ui lives in the workspace package; in this add-on's own test env it is found by path.
sys.path.insert(0, str(HERE.parents[2] / "workspace" / "src"))


@pytest.fixture
def act_orch(tmp_path):
    """A fake `orch` that records its argv (one JSON line per call in calls.jsonl) and answers per mode.txt:
    ok | conflict | refuse."""
    d = tmp_path / "actorch"
    d.mkdir()
    (d / "mode.txt").write_text("ok")
    script = d / "orch"
    script.write_text(f"""#!{sys.executable}
import json, pathlib, sys
d = pathlib.Path(__file__).parent
a = sys.argv[1:]
with open(d / "calls.jsonl", "a") as f:
    f.write(json.dumps(a) + "\\n")
if a[:2] in (["addon", "list"], ["run", "status"]) or a[:1] in (["needs"], ["status"], ["agents"], ["ticket"]) and a[1:2] == ["list"]:
    sys.exit(2)
mode = (d / "mode.txt").read_text().strip()
if mode == "conflict":
    print(json.dumps({{"error": "Title was changed by agent:claude at 10:00.", "revision": 7, "changed_by": "agent:claude",
                       "current": "x"}}))
    sys.stderr.write("Refused: Title was changed by agent:claude at 10:00.\\n")
    sys.exit(2)
if mode == "refuse":
    print(json.dumps({{"error": "Nope, not allowed."}}))
    sys.stderr.write("Refused: Nope, not allowed.\\n")
    sys.exit(2)
print(json.dumps({{"ok": True}}))
""")
    script.chmod(0o755)
    return script


@pytest.fixture
def act_server(ws, act_orch):
    import threading

    from orch_dashboard.server import make_server

    srv = make_server(ws, 0, orch_bin=str(act_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


# --- No server outlives its test (0909 leak fix) ------------------------------------------------
# Every `python -m orch_dashboard` process the tests start is recorded through its Popen handle and killed
# at teardown by its exact PID (it is our own child, never a pid read from a file). At the end of the
# session any such process still alive fails the run.
_STARTED: list = []


@pytest.fixture(autouse=True)
def _reap_started_servers(monkeypatch):
    import contextlib
    import os
    import signal
    import subprocess

    real = subprocess.Popen

    class Recording(real):
        def __init__(self, args, *a, **kw):
            super().__init__(args, *a, **kw)
            if isinstance(args, (list, tuple)) and "orch_dashboard" in [str(x) for x in args]:
                _STARTED.append(self)

    monkeypatch.setattr(subprocess, "Popen", Recording)
    before = len(_STARTED)
    yield
    for p in _STARTED[before:]:
        if p.poll() is None:
            try:
                os.kill(p.pid, signal.SIGKILL)
            except OSError:
                pass
        with contextlib.suppress(subprocess.TimeoutExpired):
            p.wait(timeout=10)


def pytest_sessionfinish(session, exitstatus):
    alive = [p.pid for p in _STARTED if p.poll() is None]
    if alive:
        print(f"\nLEAK: orch_dashboard servers started by the tests are still alive: {alive}")
        session.exitstatus = 1


@pytest.fixture(autouse=True)
def _copies_unlocked(request, monkeypatch):
    """Separate copies are locked Off for this release; the feature's tests run unlocked unless marked."""
    from orch import config

    if not request.node.get_closest_marker("copies_locked"):
        monkeypatch.setattr(config, "COPIES_LOCKED", False)
        monkeypatch.setattr(config, "DEFAULT_COPIES", "together")  # the feature's own default when unlocked

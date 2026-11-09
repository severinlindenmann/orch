import json
import sys
import threading
from pathlib import Path

import pytest

HERE = Path(__file__).parent
# orch_ui lives in the workspace package; in this add-on's own test env it is found by path.
sys.path.insert(0, str(HERE.parents[2] / "workspace" / "src"))

TID = "t_inv7c2ab"


def ticket(**kw):
    t = {
        "schema": "orch.ticket/1", "id": TID, "title": "Close March books", "status": "active", "revision": 3,
        "checklist": [
            {"id": "c1", "text": "Match transactions", "done": True, "evidence": [{"type": "note", "ref": "42 matched", "text": "42 matched"}]},
            {"id": "c2", "text": "Review totals", "done": False, "state": "doing", "evidence": []},
        ],
        "questions": [], "history": [{"at": "2026-11-06T08:00:00Z", "by": "human:anna", "via": "cli", "text": "Created"}],
        "refs": [],
    }  # fmt: skip
    t.update(kw)
    return t


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    d = root / ".orch" / "tickets"
    d.mkdir(parents=True)
    (d / f"{TID}.json").write_text(json.dumps(ticket()))
    return root


@pytest.fixture
def fake_orch(tmp_path):
    """A fake `orch`: records argv in calls.jsonl; `run status` answers from status.json."""
    d = tmp_path / "fakeorch"
    d.mkdir()
    (d / "status.json").write_text(json.dumps({"running": False}))
    script = d / "orch"
    script.write_text(f"""#!{sys.executable}
import json, pathlib, sys
d = pathlib.Path(__file__).parent
with open(d / "calls.jsonl", "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
a = sys.argv[1:]
if a[:2] == ["run", "status"]:
    print((d / "status.json").read_text())
elif a[:2] == ["ticket", "show"]:
    import os
    p = pathlib.Path(os.environ["ORCH_ROOT"]) / ".orch" / "tickets" / (a[2] + ".json")
    if not p.exists():
        print(json.dumps({{"error": "no such ticket"}})); sys.exit(2)
    print(p.read_text())
elif a[:2] == ["ticket", "list"]:
    import os
    d = pathlib.Path(os.environ["ORCH_ROOT"]) / ".orch" / "tickets"
    print(json.dumps([json.loads(x.read_text()) for x in sorted(d.glob("t_*.json"))]))
elif a[:2] == ["run", "session"]:
    print(json.dumps({{"agent": a[3], "session": None}}))
elif a[:2] == ["run", "send"]:
    print(json.dumps({{"id": "p1", "delivered": 0, "state": "none"}}))
elif a[0] == "ask":
    print(json.dumps({{"id": "q7", "text": a[2], "answer": None}}))
elif a[:2] == ["run", "start"]:
    print(json.dumps({{"ok": True, "run": "r_start001"}}))
else:
    print(json.dumps({{"ok": True}}))
""")
    script.chmod(0o755)
    return script


def calls(fake):
    p = fake.parent / "calls.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


@pytest.fixture
def server(ws, fake_orch):
    from orch_focus.server import make_server

    srv = make_server(ws, 0, orch_bin=str(fake_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


# --- No server outlives its test (0909 leak fix) ------------------------------------------------
# Every `python -m orch_focus` process the tests start is recorded through its Popen handle and killed
# at teardown by its exact PID (it is our own child, never a pid read from a file). At the end of the
# session any such process still alive fails the run.
_STARTED: list = []


@pytest.fixture(autouse=True)
def _reap_started_servers(monkeypatch):
    import os
    import signal
    import subprocess

    real = subprocess.Popen

    class Recording(real):
        def __init__(self, args, *a, **kw):
            super().__init__(args, *a, **kw)
            if isinstance(args, (list, tuple)) and "orch_focus" in [str(x) for x in args]:
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
        try:
            p.wait(timeout=10)
        except Exception:
            pass


def pytest_sessionfinish(session, exitstatus):
    alive = [p.pid for p in _STARTED if p.poll() is None]
    if alive:
        print(f"\nLEAK: orch_focus servers started by the tests are still alive: {alive}")
        session.exitstatus = 1

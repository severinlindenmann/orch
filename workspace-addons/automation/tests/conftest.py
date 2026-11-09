import json
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

FAKE_ORCH = """#!{py}
import json, sys, os
from pathlib import Path
root = Path.cwd()
args = [a for a in sys.argv[1:] if a != "--json"]
by = None
if "--by" in args:
    i = args.index("--by"); by = args[i + 1]; del args[i:i + 2]
with open(root / "calls.jsonl", "a") as f:
    f.write(json.dumps({{"args": args, "by": by}}) + "\\n")
tdir = root / ".orch" / "tickets"
def load(i): return json.loads((tdir / (i + ".json")).read_text())
def save(t): (tdir / (t["id"] + ".json")).write_text(json.dumps(t))
def note(t, text): t.setdefault("history", []).append({{"by": by, "text": text}})
if args[:2] == ["ticket", "list"]:
    print(json.dumps([json.loads(p.read_text()) for p in sorted(tdir.glob("t_*.json"))]))
elif args[:2] == ["addon", "list"]:
    print(json.dumps([{{"name": "automation", "active": not (root / "inactive").exists()}},
                      {{"name": "relay", "active": not (root / "relay-off").exists()}}]))
elif args[0] == "wait" and "--clear" in args:
    t = load(args[1]); t["waiting_on"] = None; note(t, "Wait cleared"); save(t); print("{{}}")
elif args[:2] == ["relay", "inbox"] and "--since" in args:
    p = root / "since.json"
    print(p.read_text() if p.exists() else json.dumps({{"next": int(args[args.index("--since") + 1]), "items": []}}))
elif args[:2] == ["relay", "inbox"]:
    p = root / "inbox.json"
    print(p.read_text() if p.exists() else "[]")
elif args[0] == "wait" and "--until" in args:
    t = load(args[1]); t["waiting_on"] = {{"kind": "time", "until": args[args.index("--until") + 1]}}
    t["status"] = "waiting"; note(t, "Waiting"); save(t); print("{{}}")
elif args[:2] == ["relay", "done"]:
    s = root / "seen.json"
    seen = json.loads(s.read_text()) if s.exists() else []
    s.write_text(json.dumps(seen + [args[2]]))
    t = root / "done-tickets.json"
    print(json.dumps({{"ticket": json.loads(t.read_text()).get(args[2])}}) if t.exists() else "{{}}")
elif args[:2] == ["ticket", "new"]:
    n = len(list(tdir.glob("*.json"))) + 1
    t = {{"id": "t_new%03d" % n, "title": args[2], "status": "open",
         "created_at": "2026-11-01T00:00:00Z", "history": []}}
    if "--parent" in args: t["parent"] = args[args.index("--parent") + 1]
    for i, a in enumerate(args):
        if a == "--ext": k, _, v = args[i + 1].partition("="); t.setdefault("ext", {{}})[k] = json.loads(v)
    save(t); print(json.dumps(t))
elif args[:2] == ["ticket", "status"]:
    t = load(args[2]); t["status"] = args[3]; note(t, "Status"); save(t); print(json.dumps(t))
elif args[:2] == ["ext", "set"]:
    t = load(args[2])
    if "--if-revision" in args and t.get("revision") != int(args[args.index("--if-revision") + 1]):
        sys.exit(2)
    t.setdefault("ext", {{}})[args[3]] = json.loads(args[4]); note(t, "Set ext"); save(t); print("{{}}")
elif args[:2] == ["ext", "unset"]:
    t = load(args[2])
    if "--if-revision" in args and t.get("revision") != int(args[args.index("--if-revision") + 1]):
        sys.exit(2)
    t.get("ext", {{}}).pop(args[3], None); note(t, "Unset ext"); save(t); print("{{}}")
elif args[:2] == ["run", "start"]:
    tid = args[2]
    if (root / "noagent").exists():
        print(json.dumps({{"error": "No agent found; set one later: orch config set workspace.agent <name>"}})); sys.exit(2)
    if (root / ("busy-" + tid)).exists():
        print(json.dumps({{"error": "An agent is already working on this ticket.", "pending": "--text" in args}})); sys.exit(2)
    log = ".orch/run/logs/" + tid + "-r1.log"
    (root / log).parent.mkdir(parents=True, exist_ok=True)
    (root / log).write_text("x")
    print(json.dumps({{"run": "r_1", "agent": "fake", "resumed": False, "log": log}}))
elif args[:2] == ["chat", "id"]:
    cf = root / "chat-ticket"
    print(json.dumps({{"ticket": cf.read_text().strip(), "paused": (root / "chat-paused").exists()}} if cf.exists() else {{"ticket": None}}))
elif args[:2] == ["run", "status"]:
    d = {{"ticket": args[2], "running": not (root / ("ended-" + args[2])).exists()}}
    pq = root / ("pending-" + args[2])
    if pq.exists(): d["human_pending_ids"] = json.loads(pq.read_text())
    print(json.dumps(d))
elif args[0] == "ask":
    t = load(args[1]); qs = t.setdefault("questions", [])
    q = {{"id": "q%d" % (len(qs) + 1), "text": args[2], "answer": None,
         "kind": args[args.index("--kind") + 1], "options": [args[i + 1] for i, a in enumerate(args) if a == "--option"]}}
    qs.append(q); t["status"] = "waiting"; save(t); print(json.dumps(q))
elif args[0] == "log":
    t = load(args[1]); t.setdefault("history", []).append({{"by": by, "text": args[2]}}); save(t); print("{{}}")
elif args[0] == "answer" and (root / "fail-answer").exists():
    sys.exit(2)
elif args[0] == "answer":
    print("{{}}")
else:
    sys.exit(2)
"""


def T(h=0, m=0, d=4):
    return datetime(2026, 11, d, h, m, tzinfo=UTC)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)
    (root / ".orch" / "addons" / "automation").mkdir(parents=True)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    orch = bin_ / "orch"
    orch.write_text(FAKE_ORCH.format(py=sys.executable))
    orch.chmod(orch.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("ORCH_BIN", str(orch))
    return root


def add_ticket(root: Path, tid: str, **kw):
    t = {
        "schema": "orch.ticket/1",
        "id": tid,
        "title": "T " + tid,
        "status": "open",
        "revision": 1,
        "created_at": "2026-11-01T00:00:00Z",
        "updated_at": "2026-11-01T00:00:00Z",
        "checklist": [],
        "refs": [],
        "questions": [],
        "history": [],
    }
    t.update(kw)
    (root / ".orch" / "tickets" / f"{tid}.json").write_text(json.dumps(t))
    return t


def calls(root: Path):
    p = root / "calls.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def runs_started(root: Path):
    """Ticket ids `orch run start` was called for, in order."""
    return [c["args"][2] for c in calls(root) if c["args"][:2] == ["run", "start"]]


# --- No server outlives its test (0909 leak fix) ------------------------------------------------
# Every `python -m orch_automation` process the tests start is recorded through its Popen handle and killed
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
            if isinstance(args, (list, tuple)) and "orch_automation" in [str(x) for x in args]:
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
        print(f"\nLEAK: orch_automation servers started by the tests are still alive: {alive}")
        session.exitstatus = 1

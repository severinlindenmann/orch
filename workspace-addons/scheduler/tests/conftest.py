import json
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

FAKE_ORCH = '''#!{py}
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
if args[:2] == ["relay", "inbox"]:
    p = root / "inbox.json"
    print(p.read_text() if p.exists() else "[]")
elif args[:2] == ["relay", "done"]:
    s = root / "seen.json"
    seen = json.loads(s.read_text()) if s.exists() else []
    s.write_text(json.dumps(seen + [args[2]]))
    t = root / "done-tickets.json"
    print(json.dumps({{"ticket": json.loads(t.read_text()).get(args[2])}}) if t.exists() else "{{}}")
elif args[:2] == ["ticket", "new"]:
    n = len(list(tdir.glob("*.json"))) + 1
    t = {{"id": "t_new%03d" % n, "title": args[2], "type": "task", "status": "open",
         "created_at": "2026-11-01T00:00:00Z", "history": []}}
    save(t); print(json.dumps(t))
elif args[:2] == ["ticket", "status"]:
    t = load(args[2]); t["status"] = args[3]; save(t); print(json.dumps(t))
elif args[0] == "wait" and "--clear" in args:
    if (root / "fail-wait").exists():
        sys.exit(2)
    t = load(args[1]); t["wake_at"] = t["waiting_on"] = None
    if t["status"] == "waiting": t["status"] = "active"
    save(t); print(json.dumps(t))
elif args[:2] == ["ext", "set"]:
    t = load(args[2]); t.setdefault("ext", {{}})[args[3]] = json.loads(args[4]); save(t); print("{{}}")
elif args[0] == "answer" and (root / "fail-answer").exists():
    sys.exit(2)
elif args[0] in ("log", "answer"):
    print("{{}}")
else:
    sys.exit(2)
'''

FAKE_AGENT = '''import sys, time
from pathlib import Path
Path("ran-" + sys.argv[1].split()[3].rstrip(".") + ".txt").write_text(sys.argv[1])
print("agent ran")
sys.exit(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
'''


def T(h=0, m=0, d=4):
    return datetime(2026, 11, d, h, m, tzinfo=UTC)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)
    (root / ".orch" / "scheduler").mkdir()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    orch = bin_ / "orch"
    orch.write_text(FAKE_ORCH.format(py=sys.executable))
    orch.chmod(orch.stat().st_mode | stat.S_IXUSR)
    agent = tmp_path / "agent.py"
    agent.write_text(FAKE_AGENT)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    (root / ".orch" / "scheduler" / "config.toml").write_text(f"agent = '{sys.executable} {agent} {{prompt}}'\n")
    return root


def add_ticket(root: Path, tid: str, **kw):
    t = {"schema": "orch.ticket/1", "id": tid, "title": "T " + tid, "type": "task", "status": "open",
         "created_at": "2026-11-01T00:00:00Z", "updated_at": "2026-11-01T00:00:00Z",
         "checklist": [], "links": [], "questions": [], "history": []}
    t.update(kw)
    (root / ".orch" / "tickets" / f"{tid}.json").write_text(json.dumps(t))
    return t


def calls(root: Path):
    p = root / "calls.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

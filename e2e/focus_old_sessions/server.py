"""Fixture workspace + fake-orch Focus server for the earlier-chats screenshots (e2e/focus_old_sessions/shots.cjs).

    python e2e/focus_old_sessions/server.py <dir> <port>

Serves the real Focus page files with mocked data in <dir> (under ~/.orch-test). Prints `ready` when it can be opened.
"""

import json
import sys
import time
import zlib
import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path

D, PORT = Path(sys.argv[1]).resolve(), int(sys.argv[2])
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workspace-addons" / "focus" / "src"))
sys.path.insert(0, str(ROOT / "workspace" / "src"))
ws, fake = D / "Pilatus", D / "fake"
(ws / ".orch" / "tickets").mkdir(parents=True, exist_ok=True)
fake.mkdir(exist_ok=True)
NOW = datetime.now(UTC)
iso = lambda m: (NOW - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731


def ticket(tid, key, title, status="active", tasks=(), questions=()):
    return {"schema": "orch.ticket/1", "id": tid, "key": key, "title": title, "status": status, "revision": 2,
            "started": True, "checklist": list(tasks), "questions": list(questions), "history": [], "refs": []}  # fmt: skip


def png(path):
    def chunk(t, b):
        c = struct.pack(">I", len(b)) + t + b
        return c + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    w, h = 120, 60
    raw = b"".join(b"\x00" + b"".join(bytes([30 + x, 110 + y, 190]) for x in range(w)) for y in range(h))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def evidence(tid, name, text=None):
    d = ws / ".orch" / "tickets" / tid / "evidence"
    d.mkdir(parents=True, exist_ok=True)
    if name.endswith(".png"):
        png(d / name)
    else:
        (d / name).write_text(text or "")
    return f".orch/tickets/{tid}/evidence/{name}"


STATUS = {}
TICKETS = [ticket("t_pil1aaaa", "PIL-1", "Plan the offsite agenda", tasks=[
    {"id": "c1", "text": "Collect wishes", "done": True, "evidence": []},
    {"id": "c2", "text": "Put the days in order", "done": False, "state": "doing", "evidence": []},
])]
STATUS["t_pil1aaaa"] = {"running": True, "pending": 1, "waiting_input": [
    {"id": "p_abc12345", "text": "Use the spring photo for story two.", "at": iso(2)}],
    "claim": {"run": "r_pilone01", "agent": "claude", "mode": "oneshot", "started_at": iso(18)}}
for t in TICKETS:
    (ws / ".orch" / "tickets" / f"{t['id']}.json").write_text(json.dumps(t))
(fake / "status.json").write_text(json.dumps(STATUS))
(fake / "orch").write_text(f'''#!{sys.executable}
import json, pathlib, sys
d = pathlib.Path(__file__).parent
a = sys.argv[1:]
ws = pathlib.Path.cwd() / ".orch" / "tickets"
if a[:2] == ["ticket", "list"]:
    print(json.dumps([json.loads(x.read_text()) for x in sorted(ws.glob("t_*.json"))]))
elif a[:2] == ["ticket", "show"]:
    print((ws / (a[2] + ".json")).read_text())
elif a[:2] == ["run", "status"]:
    print(json.dumps(json.loads((d / "status.json").read_text()).get(a[2], {{"running": False}})))
elif a[:2] == ["run", "history"]:
    rows = [
        {{"agent": "claude", "id": "s-now", "host": "h", "last_used": "{iso(5)}", "title": "Plan the offsite agenda", "turns": 8, "readable": True, "current": True}},
        {{"agent": "codex", "id": "s-codex", "host": "h", "last_used": "{iso(60*26)}", "title": "Check the budget sheet", "turns": 4, "readable": True, "current": False}},
        {{"agent": "claude", "id": "s-gone", "host": "h", "last_used": "{iso(60*24*9)}", "title": "", "turns": 0, "readable": False, "current": False}},
    ]
    if "--session" in a:
        print(json.dumps({{"turns": [{{"role": "user", "text": "Please check the budget sheet."}}, {{"role": "helper", "text": "The total is 4,200 and matches the invoices."}}], "more": False}}))
    else:
        print(json.dumps({{"sessions": rows}}))
elif a[:1] == ["agents"]:
    print(json.dumps([{{"name": "claude", "label": "Claude"}}]))
elif a[:3] == ["relay", "mobile", "status"]:
    print(json.dumps({{"on": True}}))
else:
    print(json.dumps({{"ok": True}}))
''')
(fake / "orch").chmod(0o755)

from orch_focus.server import make_server  # noqa: E402

srv = make_server(ws, PORT, orch_bin=str(fake / "orch"))
print("ready", flush=True)
srv.serve_forever()

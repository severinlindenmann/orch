"""Fixture workspace + fake-orch-backed Focus server for e2e/focus_insights_shots.cjs.

    python e2e/focus_insights/server.py <dir> <port>

Builds a throw-away workspace in <dir> (two running tickets, one asking; events with skills, tools, connections,
files and a helper; areas), a fake `orch` that answers from it, and serves Focus on 127.0.0.1:<port>.
Run it from the focus add-on's environment (`uv run --project workspace-addons/focus`). Never touches a real
workspace, home or key: <dir> is under ~/.orch-test. Prints `ready` when the page can be opened.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

D, PORT = Path(sys.argv[1]).resolve(), int(sys.argv[2])
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workspace-addons" / "focus" / "src"))
sys.path.insert(0, str(ROOT / "workspace" / "src"))
ws, fake = D / "Pilatus", D / "fake"  # the workspace name shows on the page
(ws / ".orch" / "tickets").mkdir(parents=True, exist_ok=True)
fake.mkdir(exist_ok=True)


def ticket(tid, key, title, tasks, questions=()):
    return {"schema": "orch.ticket/1", "id": tid, "key": key, "title": title, "status": "active", "revision": 2,
            "started": True, "checklist": tasks, "questions": list(questions), "history": [], "refs": []}  # fmt: skip


TICKETS = [
    ticket("t_pil1aaaa", "PIL-1", "Plan the offsite agenda", [
        {"id": "c1", "text": "Collect wishes", "done": True, "evidence": []},
        {"id": "c2", "text": "Put the days in order", "done": False, "state": "doing", "evidence": []},
        {"id": "c3", "text": "Send the agenda", "done": False, "evidence": []},
    ], [{"id": "q1", "text": "Should the boat trip be on day 1 or day 2?", "answer": None,
         "options": ["Day 2", "Day 1"], "recommended": "Day 2"}]),
    ticket("t_pil2bbbb", "PIL-2", "Write the newsletter", [
        {"id": "c1", "text": "Outline", "done": True, "evidence": [{"type": "note", "ref": "outline", "text": "Outline written"}]},
        {"id": "c2", "text": "Write the intro", "done": False, "state": "doing", "evidence": []},
    ]),
]  # fmt: skip
for t in TICKETS:
    (ws / ".orch" / "tickets" / f"{t['id']}.json").write_text(json.dumps(t))


def event(run, tid, i, text, at, used, files=(), kind="step", agent="main", parent=None):
    kind_, name, action, source = used
    return {"v": 1, "id": f"toolu_{run}{i}", "seq": i, "run": run, "agent": agent, "parent": parent, "at": at,
            "ticket": tid, "via": "log", "checked": True, "kind": kind, "text": text,
            "used": {"kind": kind_, "name": name, "action": action, "source": source, "version": None},
            "files": list(files), "outcome": None}  # fmt: skip


NOW = datetime.now(UTC)
ago = lambda m: (NOW - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
# (text, used, files, kind, agent, parent) per step; PIL-1 reads the budget, PIL-2 changes it (same-file line)
RUNS = {
    "t_pil1aaaa": ("r_pilone01", [
        ("Looked up the weather for Lucerne, 14-15 May", ("mcp", "Weather", "forecast", "harness"), (), "step", "main", None, 9),
        ("Read budget-2026.xlsx (sheet Offsite)", ("tool", "Read", None, "builtin"), ["budget-2026.xlsx"], "step", "main", None, 7),
        ("Planning the days", ("skill", "event-planning", None, "workspace"), (), "step", "main", None, 5),
        ("Changed offsite/agenda.docx", ("tool", "Edit", None, "builtin"), ["offsite/agenda.docx"], "step", "main", None, 3),
    ]),
    "t_pil2bbbb": ("r_piltwo01", [
        ("collect the news from the team chat", ("helper", "Researcher", None, "builtin"), (), "helper.start", "h_1", "main", 8),
        ("Searched Slack", ("mcp", "Slack", "search", "admin"), (), "step", "h_1", "main", 7),
        ("Read newsletter-outline.docx", ("tool", "Read", None, "builtin"), ["comms/newsletter-outline.docx"], "step", "main", None, 6),
        ("Writing the intro in newsletter-nov.docx", ("skill", "newsletter-writing", None, "workspace"), (), "step", "main", None, 4),
        ("Wrote comms/newsletter-nov.docx", ("tool", "Write", None, "builtin"), ["comms/newsletter-nov.docx"], "step", "main", None, 3),
        ("Changed budget-2026.xlsx (1 row: newsletter print)", ("tool", "Edit", None, "builtin"), ["budget-2026.xlsx"], "step", "main", None, 2),
    ]),
}  # fmt: skip
lines = {}
for tid, (run, steps) in RUNS.items():
    lines[tid] = [
        json.dumps({"type": "event", "cursor": f"rc1.{tid}{i}",
                    "event": event(run, tid, i + 1, text, ago(m), used, files, kind, agent, parent)})
        for i, (text, used, files, kind, agent, parent, m) in enumerate(steps)
    ]  # fmt: skip
# the second run shows what orch could not check: its last step was only reported by the agent (a hook line,
# "not checked" mark) and one line was changed outside orch (the quiet run warning)
_last = json.loads(lines["t_pil2bbbb"][-1])
_last["event"].update(via="hook", checked=False)
lines["t_pil2bbbb"][-1] = json.dumps(_last)
lines["t_pil2bbbb"].append(json.dumps({
    "type": "unavailable", "status": "ok", "reason": "content", "changed": 1, "removed": 0,
    "message": "Some records of this run were changed outside orch. To be safe, orch does not show them. Nothing was deleted.",
}))  # fmt: skip
(fake / "events.json").write_text(json.dumps(lines))
(fake / "runs.json").write_text(json.dumps({tid: run for tid, (run, _) in RUNS.items()}))
(fake / "orch").write_text(f'''#!{sys.executable}
import json, pathlib, sys, time
d = pathlib.Path(__file__).parent
a = sys.argv[1:]
ws = pathlib.Path.cwd() / ".orch" / "tickets"
runs = json.loads((d / "runs.json").read_text())
if a[:2] == ["ticket", "list"]:
    print(json.dumps([json.loads(x.read_text()) for x in sorted(ws.glob("t_*.json"))]))
elif a[:2] == ["ticket", "show"]:
    print((ws / (a[2] + ".json")).read_text())
elif a[:2] == ["run", "status"]:
    print(json.dumps({{"running": True, "claim": {{"run": runs[a[2]], "agent": "codex" if a[2] == "t_pil2bbbb" else "claude", "mode": "oneshot",
                                                  "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 18 * 60))}}}}))
elif a[:2] == ["record", "tail"]:
    tid = [t for t, r in runs.items() if r == a[a.index("--run") + 1]][0]
    for line in json.loads((d / "events.json").read_text())[tid]:
        print(line, flush=True)
    time.sleep(600)
elif a[:3] == ["relay", "mobile", "status"]:
    print(json.dumps({{"on": False}}))
elif a[:1] == ["agents"]:
    print(json.dumps([{{"name": "claude", "label": "Claude"}}, {{"name": "codex", "label": "Codex"}}]))
elif a[:1] == ["answer"]:
    p = ws / (a[1] + ".json")
    t = json.loads(p.read_text())
    for q in t["questions"]:
        if q["id"] == a[2]:
            q["answer"] = a[-1]
    p.write_text(json.dumps(t))
    print(json.dumps({{"id": a[2], "answer": a[-1]}}))
else:
    print(json.dumps({{"ok": True}}))
''')
(fake / "orch").chmod(0o755)

from orch_focus import areas  # noqa: E402
from orch_focus.server import make_server  # noqa: E402

areas.add(ws, "Offsite", "offsite/")
areas.add(ws, "Newsletter", "comms/")
areas.add(ws, "Budget", "budget-2026.xlsx")
areas.add(ws, "Venue", "venue/")
areas.add(ws, "Catering", "catering/")  # stays suggested: the dialog shows both kinds
for n in ("a1", "a2", "a3", "a4"):
    areas.accept(ws, n)
srv = make_server(ws, PORT, orch_bin=str(fake / "orch"))
print("ready", flush=True)
srv.serve_forever()

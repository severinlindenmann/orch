"""Build a demo workspace from the contract examples: python tests/make_fixture.py <folder> (used for screenshots)."""
import json
import sys
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "review"


def build(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    tdir = root / ".orch" / "tickets"
    tdir.mkdir(parents=True, exist_ok=True)
    ex = json.loads((CONTRACTS / "ticket.example.json").read_text())
    (tdir / f"{ex['id']}.json").write_text(json.dumps(ex))
    for i, (title, st) in enumerate([("Weekly report", "waiting"), ("Fix flaky export test", "active"),
                                     ("Plan Q1 backlog", "open"), ("Update onboarding notes", "done"),
                                     ("Old migration idea", "dropped")]):
        t = {**ex, "id": f"t_demo{i:03d}x", "title": title, "status": st, "wake_at": None, "waiting_on": None,
             "questions": [], "links": [], "ext": {}, "checklist": [], "type": "task"}
        if st == "waiting":
            t.update(type="recurring", ext={"scheduler": {"cron": "0 8 * * 1"}})
        (tdir / f"{t['id']}.json").write_text(json.dumps(t))
    (root / ".orch" / "inbox").mkdir(exist_ok=True)
    for m in json.loads((CONTRACTS / "message.examples.json").read_text()):
        m.pop("_note", None)
        (root / ".orch" / "inbox" / f"{m['id']}.json").write_text(json.dumps(m))
    (root / ".orch" / "scheduler").mkdir(exist_ok=True)
    (root / ".orch" / "scheduler" / "state.json").write_text(
        json.dumps({"t_demo000x": {"last_run": "2026-11-02T08:00:00Z", "next_run": "2026-11-09T08:00:00Z"}}))
    return root


if __name__ == "__main__":
    build(Path(sys.argv[1]))

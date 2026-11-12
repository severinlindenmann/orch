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
    for i, (title, st) in enumerate(
        [
            ("Weekly report", "waiting"),
            ("Fix flaky export test", "active"),
            ("Plan Q1 backlog", "open"),
            ("Update onboarding notes", "done"),
            ("Old migration idea", "dropped"),
        ]
    ):
        t = {
            **ex,
            "id": f"t_demo{i:03d}x",
            "title": title,
            "status": st,
            "wake_at": None,
            "waiting_on": None,
            "questions": [],
            "refs": [],
            "ext": {},
            "checklist": [],
            "type": "task",
        }
        if st == "waiting":
            # Screenshot case (owner pass 11 Nov): the Chat card shows "Weekly report · <due>", "Needs your OK"
            # and the question's own buttons; the key sits behind Details.
            question = {
                "id": "q_weekly1",
                "text": "Send the weekly report now?",
                "options": ["Send it", "Not yet"],
            }
            question.update(recommended=None, answer=None, answered_by=None, via=None)
            t.update(
                type="recurring",
                ext={"scheduler": {"cron": "0 8 * * 1"}},
                due="2026-11-11",
                questions=[question],
            )
        (tdir / f"{t['id']}.json").write_text(json.dumps(t))
    (root / ".orch" / "inbox").mkdir(exist_ok=True)
    for m in json.loads((CONTRACTS / "message.examples.json").read_text()):
        m.pop("_note", None)
        (root / ".orch" / "inbox" / f"{m['id']}.json").write_text(json.dumps(m))
    d = root / ".agents" / "skills" / "orch-relay"
    d.mkdir(parents=True, exist_ok=True)
    (d / "workspaces.json").write_text((CONTRACTS / "workspaces.example.json").read_text())
    (root / ".orch" / "scheduler").mkdir(exist_ok=True)
    (root / ".orch" / "scheduler" / "state.json").write_text(
        json.dumps({"t_demo000x": {"last_run": "2026-11-02T08:00:00Z", "next_run": "2026-11-09T08:00:00Z"}})
    )
    # Screenshot case: the phone conversation is shown once, in Chat (not Home Messages).
    conversation = json.loads((Path(__file__).parent / "fixtures" / "general-chat.json").read_text())
    general = {**ex, **conversation["general"], "general": True, "title": "General", "questions": []}
    (tdir / f"{general['id']}.json").write_text(json.dumps(general))
    chat = conversation["chat"]
    chatdir = root / ".orch" / "chat"
    chatdir.mkdir(exist_ok=True)
    (chatdir / f"{chat['day']}.json").write_text(
        json.dumps({"schema": "orch.chat-day/1", "day": chat["day"], "messages": chat["messages"]})
    )
    return root


if __name__ == "__main__":
    build(Path(sys.argv[1]))

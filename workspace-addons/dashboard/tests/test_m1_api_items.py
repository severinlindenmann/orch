import json
import subprocess
from pathlib import Path

import pytest

from orch_dashboard import actions, data


def test_paste_creates_ticket_with_full_note(ws):
    python = Path(__file__).resolve().parents[3] / "workspace/.venv/bin/python"
    if (
        not python.exists()
    ):  # the dashboard CI job has no workspace venv: the workspace job covers ticket paste
        pytest.skip("needs the workspace venv")

    def invoke(argv):
        result = subprocess.run(
            [str(python), "-m", "orch", *argv], cwd=ws, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr + result.stdout
        return result.returncode

    text = "\n  \n" + "A" * 100 + "\n" + "Details. " * 100
    argv = actions.build_argv("ticket.paste", {"text": text})
    assert invoke(argv) == 0
    created = next(t for t in data.load_tickets(ws)[0] if t.get("note") == text)
    assert created["title"] == "A" * 80
    parent = created["id"]
    argv = actions.build_argv("ticket.paste", {"text": "Child\nDetails", "parent": parent})
    assert invoke(argv) == 0
    assert any(
        t.get("parent") == parent and t.get("note") == "Child\nDetails" for t in data.load_tickets(ws)[0]
    )


@pytest.mark.parametrize("text", [None, "  \n", "x\x00y", "x" * 500_001])
def test_paste_rejects_invalid_text(text):
    with pytest.raises(actions.BadRequest):
        actions.build_argv("ticket.paste", {"text": text})


def test_parts_are_direct_children_with_done_counts(ws, monkeypatch):
    # the core says which tickets are Done (it verifies the signed verdict); without it a raw "done" reads as Review
    monkeypatch.setattr(
        data,
        "run_orch",
        lambda *a, **k: [data._load(f) for f in data._json_files(ws / ".orch" / "tickets")],
    )

    def parent(child, parent):
        path = ws / ".orch/tickets" / f"{child}.json"
        ticket = json.loads(path.read_text())
        ticket["parent"] = parent
        path.write_text(json.dumps(ticket))

    parent("t_other000x", "t_weekly01")
    parent("t_other001x", "t_weekly01")
    parent("t_other002x", "t_weekly01")
    parent("t_other003x", "t_other000x")
    rows = {t["id"]: t for t in data.load_state(ws)["tickets"]}
    assert set(rows["t_weekly01"]["children"]) == {"t_other000x", "t_other001x", "t_other002x"}
    assert (rows["t_weekly01"]["parts_done"], rows["t_weekly01"]["parts_total"]) == (1, 3)
    assert rows["t_other003x"]["parent"] == "t_other000x"
    assert rows["t_other003x"]["children"] == []
    assert rows["t_other003x"]["parts_total"] == rows["t_other003x"]["parts_done"] == 0


@pytest.mark.parametrize(
    "mode,running,since,expected",
    [
        ("live", True, "2026-11-08T12:00:00Z", 480),
        ("live", True, "2026-11-08T11:00:00Z", 0),
        ("live", False, "2026-11-08T12:00:00Z", None),
        ("oneshot", True, "2026-11-08T12:00:00Z", None),
    ],
)
def test_warmth_uses_live_activity_and_fake_clock(ws, monkeypatch, mode, running, since, expected):
    from datetime import datetime

    from orch import config

    monkeypatch.setattr(config, "live_idle_minutes", lambda root: 10)
    monkeypatch.setattr(
        data.time, "time", lambda: datetime.fromisoformat("2026-11-08T12:02:00+00:00").timestamp()
    )
    statuses = {
        "t_weekly01": {
            "running": running,
            "claim": {
                "mode": mode,
                "live": {"state": "idle", "since": since},
                "renewed_at": "2026-11-08T12:02:00Z",
            },
        }
    }
    monkeypatch.setattr(data, "load_runs", lambda *args: statuses)
    rows = {t["id"]: t for t in data.load_state(ws)["tickets"]}
    if expected is None:
        assert "warmth" not in rows["t_weekly01"]
    else:
        assert rows["t_weekly01"]["warmth"] == {"seconds_left": expected}
        assert type(rows["t_weekly01"]["warmth"]["seconds_left"]) is int
    assert "warmth" not in rows["t_other000x"]


def test_who_matches_plain_owner(ws, monkeypatch):
    from orch import tickets

    monkeypatch.setattr(actions.getpass, "getuser", lambda: "anna")
    ticket = tickets.create(ws, "Mine", actions.actor(), fields={"owner": "anna"})
    state = data.load_state(ws)
    assert state["who"] == actions.actor().removeprefix("human:") == "anna"
    assert next(t for t in state["tickets"] if t["id"] == ticket["id"])["owner"] == state["who"]


def test_who_uses_actor_fallback(ws, monkeypatch):
    def missing_user():
        raise KeyError("no user")

    monkeypatch.setattr(actions.getpass, "getuser", missing_user)
    assert data.load_state(ws)["who"] == "dashboard"

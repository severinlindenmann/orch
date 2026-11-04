import json
from pathlib import Path

import pytest

HERE = Path(__file__).parent
CONTRACTS = HERE.parents[2] / "contracts" / "review"


def _ticket(i, title, status, **kw):
    t = json.loads((CONTRACTS / "ticket.example.json").read_text())
    t.update(id=i, title=title, status=status, **kw)
    return t


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "Pilatus"
    tdir = root / ".orch" / "tickets"
    tdir.mkdir(parents=True)
    ex = json.loads((CONTRACTS / "ticket.example.json").read_text())
    (tdir / f"{ex['id']}.json").write_text(json.dumps(ex))
    rec = _ticket("t_weekly01", "Weekly report", "waiting", type="recurring", wake_at=None, checklist=[],
                  questions=[], waiting_on=None, ext={"scheduler": {"cron": "0 8 * * 1"}})
    (tdir / "t_weekly01.json").write_text(json.dumps(rec))
    for i, (title, st) in enumerate([("Open one", "open"), ("Done one", "done"), ("Dropped one", "dropped"),
                                     ("Active one", "active")]):
        t = _ticket(f"t_other{i:03d}x", title, st, wake_at=None, waiting_on=None, checklist=[], questions=[], ext={})
        (tdir / f"{t['id']}.json").write_text(json.dumps(t))
    (tdir / "t_broken0001.json").write_text("{not json")
    (root / ".orch" / "inbox").mkdir()
    msgs = json.loads((CONTRACTS / "message.examples.json").read_text())
    for m in msgs:
        m.pop("_note", None)
        (root / ".orch" / "inbox" / f"{m['id']}.json").write_text(json.dumps(m))
    (root / ".orch" / "inbox-seen.json").write_text(json.dumps({msgs[0]["id"]: "2026-11-04T10:00:00Z"}))
    (root / ".orch" / "scheduler").mkdir()
    (root / ".orch" / "scheduler" / "state.json").write_text(
        json.dumps({"t_weekly01": {"last_run": "2026-11-02T08:00:00Z", "last_exit": 1, "next_run": "2026-11-09T08:00:00Z"}}))
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



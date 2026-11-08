"""Contracts needed by the accepted Focus layouts."""
import json

import pytest

from orch_focus import actions

from .conftest import TID
from .test_server import req


def test_mark_done_is_revision_checked_and_fixed_scope():
    argv = actions.build_argv("ticket.done", {"ticket": TID, "if_revision": 7})
    assert argv[:3] == ["ticket", "patch", TID]
    assert "--if-revision=7" in argv
    assert json.loads(argv[-1]) == {"status": "done"}
    for args in ({"ticket": TID}, {"ticket": TID, "if_revision": True},
                 {"ticket": TID, "if_revision": 7, "status": "active"}):
        with pytest.raises(actions.BadRequest):
            actions.build_argv("ticket.done", args)


@pytest.mark.parametrize("started", [False, True])
def test_started_and_question_delivery_survive_view(server, ws, started):
    path = ws / ".orch" / "tickets" / f"{TID}.json"
    ticket = json.loads(path.read_text())
    ticket.update(status="open", ticket_view={"started": started}, questions=[
        {"id": "q1", "text": "Which greeting?", "answer": None, "sent_to_phone": True},
        {"id": "q2", "text": "Which colour?", "answer": None},
    ])
    path.write_text(json.dumps(ticket))
    view = json.loads(req(server, "GET", f"/api/t/{TID}")[1])
    assert view["ticket"]["started"] is started
    assert view["ticket"]["questions"][0]["sent_to_phone"] is True
    assert "sent_to_phone" not in view["ticket"]["questions"][1]
    assert view["capabilities"]["phone_mode"] is False  # unavailable relay stays hidden
    rows = json.loads(req(server, "GET", "/api/tickets")[1])["tickets"]
    assert rows[0]["started"] is started


def test_mark_done_uses_existing_action_fence(server, fake_orch):
    from .conftest import calls

    body = {"op": "ticket.done", "args": {"ticket": TID, "if_revision": 3}}
    assert req(server, "POST", "/api/act", body, {"Origin": "https://other.example"})[0] == 403
    assert req(server, "POST", "/api/act", body)[0] == 200
    patches = [a for a in calls(fake_orch) if a[:2] == ["ticket", "patch"]]
    assert len(patches) == 1
    assert "--if-revision=3" in patches[0]
    assert json.loads(patches[0][-1]) == {"status": "done"}

"""ORCH-1047: a click's quick answer (data.patch_ticket) reads the clicked ticket again; its question rows that are no
longer open leave the needs list too. Before, the needs list stayed the cached one, so Home showed an answered
question again until the background build ran, and a click on it was refused ("q1 is already answered.")."""

import json

from orch_dashboard import data

from .conftest import _ticket


def _q(qid, text, answer=None):
    return {"id": qid, "text": text, "options": ["Yes", "No"], "recommended": "Yes", "answer": answer}


def _row(tid, qid):
    return {"id": f"core:q:{tid}:{qid}", "source": "core", "kind": "question", "ticket": tid,
            "answer": {"question": qid, "options": ["Yes", "No"]}}  # fmt: skip


def test_an_answered_question_leaves_the_needs_list_of_the_click_answer(ws):
    tid = "t_order0001"
    before = _ticket(tid, "Weekly newsletter template", "waiting", checklist=[], ext={},
                     questions=[_q("q1", "Story?"), _q("q2", "Colour?"), _q("q3", "Language?")])  # fmt: skip
    after = {**before, "questions": [_q("q1", "Story?", "Yes"), _q("q2", "Colour?"), _q("q3", "Language?")]}
    (ws / ".orch" / "tickets" / f"{tid}.json").write_text(json.dumps(after))
    other = _row("t_other000x", "q1")  # another ticket's question stays, whatever its id
    notice = {"id": "sync:note", "source": "sync", "ticket": None, "text": "A note"}
    state = {
        "tickets": [before],
        "needs": [_row(tid, "q1"), _row(tid, "q2"), _row(tid, "q3"), other, notice],
        "runs": {},
    }
    out = data.patch_ticket(ws, None, state, tid)
    assert out is not None
    assert [n["id"] for n in out["needs"]] == [
        f"core:q:{tid}:q2",
        f"core:q:{tid}:q3",
        "core:q:t_other000x:q1",
        "sync:note",
    ]
    assert state["needs"][0]["id"] == f"core:q:{tid}:q1", "the cached state itself is not changed"


def test_parking_a_ticket_reads_needs_and_the_parked_list_again(ws, monkeypatch):
    """ORCH-2431: "Not now" changes the ticket's wait; its question leaves Home at once and the parked list
    names it (before, the cached needs list kept the row until the background build)."""
    tid = "t_order0002"
    before = _ticket(tid, "Try it on my notebook", "waiting", checklist=[], ext={},
                     questions=[_q("q1", "Did it work?")], waiting_on={"kind": "question", "ref": "q1"})  # fmt: skip
    after = {**before, "waiting_on": {"kind": "external", "ref": "Not now"}}
    parked = [{"ticket": tid, "key": "DM-2", "kind": "external", "reason": "Until you bring it back"}]
    asked = []

    def run_orch(orch_bin, args, root, timeout=5.0):
        asked.append(list(args))
        if args[:2] == ["ticket", "show"]:
            return after
        if args == ["needs", "--json"]:
            return []
        if args == ["needs", "--parked", "--json"]:
            return parked
        return None

    monkeypatch.setattr(data, "run_orch", run_orch)
    state = {"tickets": [before], "needs": [_row(tid, "q1")], "runs": {}, "parked": []}
    out = data.patch_ticket(ws, "orch", state, tid)
    assert out is not None and out["needs"] == [] and out["parked"] == parked
    assert ["needs", "--parked", "--json"] in asked
    # a click that moves nothing asks neither again
    asked.clear()
    same = data.patch_ticket(ws, "orch", {**state, "tickets": [after], "parked": parked}, tid)
    assert same["parked"] == parked and ["needs", "--parked", "--json"] not in asked
    # an older core without the list: empty, never an error
    monkeypatch.setattr(data, "run_orch", lambda *a, **k: None)
    assert data.load_parked(ws, "orch") == []


def test_the_waits_a_page_may_set():
    """ORCH-2431: besides a time, "Not now" by hand (until the person brings it back) and Bring back (the
    ticket waits on its own question again); nothing else (a wait on another ticket, a pull request, a helper
    that could not start)."""
    from orch_dashboard import actions

    ok = [
        {"kind": "time", "until": "2030-01-01T08:00:00Z"},
        {"kind": "time", "until": "2030-01-01T08:00:00Z", "ref": "Not now"},
        {"kind": "external", "ref": "Not now"},
        {"kind": "question", "ref": "q12"},
    ]
    bad = [
        {"kind": "external"},
        {"kind": "external", "ref": " "},
        {"kind": "external", "ref": "x" * 201},
        {"kind": "external", "ref": "x", "start": True},
        {"kind": "question", "ref": "--all"},
        {"kind": "question", "ref": "q1", "until": "2030-01-01T08:00:00Z"},
        {"kind": "ticket", "ref": "DM-1"},
        {"kind": "pr", "ref": "https://github.com/a/b/pull/1"},
        {"kind": "time"},
        {"kind": "time", "until": "x", "ref": 5},
        "tomorrow",
    ]
    assert all(actions._page_wait(w) for w in ok)
    assert not any(actions._page_wait(w) for w in bad)
    args = {"ticket": "t_abcdef", "data": {"status": "waiting", "waiting_on": ok[2]}, "if_revision": 3}
    argv = actions.build_argv("ticket.patch", args)
    assert argv[:3] == ["ticket", "patch", "t_abcdef"] and '"kind": "external"' in " ".join(argv)

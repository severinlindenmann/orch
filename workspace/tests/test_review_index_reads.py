"""ORCH-522: with the ticket index (ORCH-521) the Review stack and the newest answers read only the tickets
that can hold them; the answers are the same as from every ticket."""

import json
import sys
import types

import pytest

from orch import review, tickets
from orch.cli_review import _answered

ME = "human:pat"


def _new(run, title):
    code, out, err = run("ticket", "new", title, "--json", "--by", "agent:x")
    assert code == 0, out + err
    return json.loads(out)["id"]


def _draft(run, tid):
    code, out, err = run(
        "ask", tid, "Please look: block", "--draft", "block", "--then", "I build it.", "--ok", "Build it",
        "--json", "--by", "agent:x",
    )  # fmt: skip
    assert code == 0, out + err
    return json.loads(out)


def _answer(run, tid, qid):
    code, out, err = run("review", "answer", tid, qid, "--verdict", "ok", "--by", ME, "--json")
    assert code == 0, out + err


@pytest.fixture
def index(monkeypatch):
    """A stand-in orch.ticketindex built from the ticket files; `seen` lists the ticket ids read in full."""
    seen: list[str] = []

    def rows(root, include_hidden=False):
        out = []
        for t in tickets.list_all(root):
            done = [q for q in t.get("questions") or [] if q.get("answer") is not None and q.get("decision")]
            out.append(
                {
                    "id": t["id"],
                    "status": t["status"],
                    "updated_at": t.get("updated_at"),
                    "questions_open": sum(1 for q in t.get("questions") or [] if q.get("answer") is None),
                    "answers": len(done),
                    "answered_at": max((q.get("at") or "" for q in done), default=None),
                    "hidden": None,
                }
            )
        return out

    mod = types.ModuleType("orch.ticketindex")
    mod.rows = rows
    monkeypatch.setitem(sys.modules, "orch.ticketindex", mod)
    real = tickets.load

    def load(root, tid, *a, **k):
        seen.append(tid)
        return real(root, tid, *a, **k)

    monkeypatch.setattr(tickets, "load", load)
    return seen


def test_stack_reads_only_tickets_that_hold_a_card(proj, run, index):
    asked = _new(run, "Has a question")
    _new(run, "Nothing to answer")
    q = _draft(run, asked)
    index.clear()
    cards = review.stack(proj)
    assert [c["ticket"] for c in cards] == [asked] and cards[0]["key"] == q["id"]
    assert index == [asked], "only the ticket with an open question is read"


def test_newest_answers_with_a_limit_read_few_tickets(proj, run, index):
    ids = [_new(run, f"T{i}") for i in range(4)]
    for tid in ids[:3]:
        _answer(run, tid, _draft(run, tid)["id"])
    every = _answered(proj)
    assert len(every) == 3
    index.clear()
    newest = _answered(proj, limit=2)
    assert newest == every[:2]
    assert ids[3] not in index, "a ticket without an answer is never read"

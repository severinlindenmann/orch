"""`orch review answer` with the real person proof (ticket.answer / ticket.verdict)."""

import io
import json

import pytest

from orch import humanproof as hp
from orch import review, tickets


@pytest.fixture
def ws(proj, monkeypatch):
    from orch import addons

    base = addons.real_home() / ".orch-test"
    root = base / "ws"
    (root / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.chdir(root)
    return root


def _proof(ws, op, target, by="human:pat"):
    return hp.mint(hp.human_key(ws), hp.new_payload(op, target, by))


def _go(run, monkeypatch, proof, *argv):
    monkeypatch.setattr("sys.stdin", io.StringIO((proof + "\n") if proof else ""))
    return run("review", "answer", *argv, "--proof-stdin", "--json")


def _card(ws, run):
    code, out, _ = run("ticket", "new", "Q", "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    code, out, err = run(
        "review", "add", tid, "--draft", "Block", "--then", "I build it.", "--json", "--by", "agent:x"
    )
    assert code == 0, out + err
    q = json.loads(out)
    return tid, q["id"], tickets.question_digest(q)


def test_answer_with_a_valid_proof_counts_as_the_person(ws, run, monkeypatch):
    tid, qid, d = _card(ws, run)
    code, out, err = _go(
        run, monkeypatch, _proof(ws, "ticket.answer", f"{tid}:{qid}:{d}"), tid, qid, "--verdict", "ok",
        "--digest", d,
    )  # fmt: skip
    assert code == 0, out + err
    assert json.loads(out)["answered_by"] == "human:pat"


def test_answer_without_a_proof_is_refused(ws, run, monkeypatch):
    tid, qid, d = _card(ws, run)
    code, out, _ = run("review", "answer", tid, qid, "--verdict", "ok", "--by", "human:pat", "--json")
    assert code == 2 and tickets.load(ws, tid)["questions"][0]["answer"] is None
    code, out, _ = _go(run, monkeypatch, "", tid, qid, "--verdict", "ok", "--digest", d)
    assert code == 2 and tickets.load(ws, tid)["questions"][0]["answer"] is None


@pytest.mark.parametrize(
    "op,suffix",
    [("ticket.verdict", ":{d}"), ("ticket.answer", ":{x}"), ("ticket.answer", "")],
)
def test_proof_for_something_else_is_refused(ws, run, monkeypatch, op, suffix):
    tid, qid, d = _card(ws, run)
    target = f"{tid}:{qid}" + suffix.format(d=d, x="0" * 64)
    code, out, _ = _go(run, monkeypatch, _proof(ws, op, target), tid, qid, "--verdict", "ok", "--digest", d)
    assert code == 2 and tickets.load(ws, tid)["questions"][0]["answer"] is None


def test_proof_needs_the_digest_and_an_agent_cannot_use_it(ws, run, monkeypatch):
    tid, qid, d = _card(ws, run)
    proof = _proof(ws, "ticket.answer", f"{tid}:{qid}:{d}")
    code, out, _ = _go(run, monkeypatch, proof, tid, qid, "--verdict", "ok")  # no --digest
    assert code == 2 and json.loads(out)["code"] == "changed"
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, _ = _go(run, monkeypatch, proof, tid, qid, "--verdict", "ok", "--digest", d)
    assert code == 2 and json.loads(out)["code"] == "needs_person"
    assert tickets.load(ws, tid)["questions"][0]["answer"] is None


def test_check_card_needs_the_verdict_proof(ws, run, monkeypatch):
    code, out, _ = run("ticket", "new", "R", "--json", "--by", "agent:x")
    tid = json.loads(out)["id"]
    tickets.apply_op(ws, tid, lambda t: t.update(status="review"), by=tickets.SYSTEM)
    d = review.check_digest(tickets.load(ws, tid))
    code, out, _ = _go(
        run, monkeypatch, _proof(ws, "ticket.answer", f"{tid}:review:{d}"), tid, "review", "--verdict", "ok",
        "--digest", d,
    )  # fmt: skip
    assert code == 2 and tickets.load(ws, tid)["status"] == "review"
    code, out, err = _go(
        run, monkeypatch, _proof(ws, "ticket.verdict", tid), tid, "review", "--verdict", "ok", "--digest", d
    )
    assert code == 0, out + err
    assert tickets.load(ws, tid)["status"] == "done"

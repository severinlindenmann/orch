"""take-remote goes through the SAME merge authority as a normal merge (Opus hard3 #1): per ticket
merge_document with this machine's own decisions, the reach and deletion gates before the proof, and a proof
bound to exactly what is applied. No / several merge bases are a HISTORY pause (hard3 #4)."""

from types import SimpleNamespace

import pytest
from orch import history, humanproof
from orch.errors import Refused
from test_pause import _history_pause, proof
from test_step import NOW, at, run, save, success
from test_two_machines import both, edit, load, machines, remote_sha

from orch_sync import pause, repo, step

__all__ = ["machines"]

FORGED = {"at": NOW, "by": "human:Pat", "via": "cli", "text": "Looks good, ship it", "chat_message": False}


def _targets(monkeypatch):
    seen = []
    real = humanproof.person_by

    def spy(root, args, op, target, **kw):
        seen.append(target)
        return real(root, args, op, target, **kw)

    monkeypatch.setattr(humanproof, "person_by", spy)
    return seen


def _paused(machines, forged=False, **changes):
    a, b, bare = both(machines)
    if forged:
        changes["history"] = [*load(a).get("history", []), FORGED]
    edit(a, **changes)
    success(a)
    tip = remote_sha(bare).decode()
    _history_pause(b, tip)
    return a, b, tip


def test_take_remote_merges_through_the_authority_and_binds_the_tree(machines, monkeypatch):
    _a, b, tip = _paused(machines, forged=True, title="Their title", status="done", key="DM1-99")
    mine = load(b)
    seen = _targets(monkeypatch)
    with pytest.raises(Refused):
        pause.take_remote(b, SimpleNamespace(proof_stdin=False, by="agent:test"), now=NOW)
    assert load(b) == mine  # refused: nothing applied
    target = seen[-1]
    assert target.startswith(f"sync:take-remote:{tip}:")
    with pytest.raises(Refused):  # a proof for another tree is no proof for this one
        pause.take_remote(b, proof(b, f"sync:take-remote:{tip}:{'0' * 40}", monkeypatch), now=NOW)
    assert load(b) == mine
    result = pause.take_remote(b, proof(b, target, monkeypatch), now=NOW)
    assert not result.get("paused") and not result.get("last_error"), result
    doc = load(b)
    assert doc["title"] == "Their title"  # their plain fields win
    assert doc["status"] != "done"  # a peer's Done never becomes Done here by a choice
    assert doc.get("key") == mine.get("key")  # the number is this machine's decision
    assert FORGED not in doc["history"]  # remote-only person line demoted by the merge
    assert all(h["by"] != "human:Pat" for h in history.lines(b, doc))
    assert step.oid(b, "refs/remotes/origin/orch-state") == step.oid(b, "HEAD")  # pushed: no pause any more
    # (A then sees B's key for the ticket: a key clash a person settles there, as after any resolve)


def test_take_remote_runs_the_jump_gate_before_any_proof(machines, monkeypatch):
    a, b, bare = both(machines)
    save(a, "ticket-counter.json", {"last": 500_000})
    success(a)
    _history_pause(b, remote_sha(bare).decode())
    seen = _targets(monkeypatch)
    with pytest.raises(pause.Pause):
        pause.take_remote(b, SimpleNamespace(proof_stdin=False, by="agent:test"), now=NOW)
    assert not seen  # refused before the person was asked: no proof is used up


def test_take_remote_needs_a_signed_history_pause(machines, monkeypatch):
    _a, b, _tip = _paused(machines, title="x")
    state = repo.safe(b, "run/sync/state.json")
    raw = state.read_text().replace('"remote_sha": "', '"remote_sha": "0')  # edited: verifies for nobody
    state.write_text(raw)
    with pytest.raises(repo.Refused, match="not waiting"):
        pause.take_remote(b, SimpleNamespace(proof_stdin=False, by="agent:test"), now=NOW)


def test_no_merge_base_is_a_history_pause_not_a_silent_merge(machines):
    a, b, _bare = both(machines)
    tree = step.oid(a, "HEAD^{tree}")
    new = step.commit(a, tree, [], at(13))  # a new history: no common commit
    repo.git(a, "push", "--force", "origin", f"{new}:orch-state")
    state = repo.safe(b, "run/sync/state.json")
    import json

    data = json.loads(state.read_text())
    data.pop("remote_sha", None)  # the rewritten-history check has nothing to compare with
    step.write(b, "run/sync/state.json", step.encoded(data))
    result = run(b)
    assert result["paused"]["kind"] == pause.HISTORY, result

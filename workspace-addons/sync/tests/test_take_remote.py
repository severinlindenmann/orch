"""take-remote goes through the SAME merge authority as a normal merge (Opus hard3 #1): per ticket
merge_document with this machine's own decisions, and the reach and deletion gates. No / several merge bases are a HISTORY pause (hard3 #4)."""

import pytest
from test_pause import _history_pause, plain_args
from test_step import NOW, at, run, save, success
from test_two_machines import both, edit, load, machines, remote_sha

from orch_sync import pause, repo, step

__all__ = ["machines"]

FORGED = {"at": NOW, "by": "human:Pat", "via": "cli", "text": "Looks good, ship it", "chat_message": False}


def _paused(machines, forged=False, **changes):
    a, b, bare = both(machines)
    if forged:
        changes["history"] = [*load(a).get("history", []), FORGED]
    edit(a, **changes)
    success(a)
    tip = remote_sha(bare).decode()
    _history_pause(b, tip)
    return a, b, tip


def test_take_remote_merges_through_the_normal_merge(machines):
    _a, b, tip = _paused(machines, forged=True, title="Their title", status="done", key="DM1-99")
    mine = load(b)
    result = pause.take_remote(b, plain_args(), now=NOW)
    assert not result.get("paused") and not result.get("last_error"), result
    doc = load(b)
    assert doc["title"] == "Their title"  # their plain fields win
    assert doc["status"] != "done"  # a peer's Done never becomes Done here by a choice
    assert doc.get("key") == mine.get("key")  # the number is this machine's decision
    assert tip in repo.git(b, "rev-list", "HEAD").stdout.decode()  # their history is the new base
    assert step.oid(b, "refs/remotes/origin/orch-state") == step.oid(b, "HEAD")  # sent: no pause any more
    assert not repo.safe(b, "run/sync/pending.json").exists()
    # (A then sees B's key for the ticket: a key clash a person settles there, as after any resolve)


def test_take_remote_only_answers_a_history_pause(machines):
    _a, b, _bare = both(machines)
    with pytest.raises(repo.Refused, match="not waiting"):
        pause.take_remote(b, plain_args(), now=NOW)


def test_take_remote_runs_the_counter_jump_check_first(machines):
    a, b, bare = both(machines)
    save(a, "ticket-counter.json", {"last": 500_000})
    success(a)
    _history_pause(b, remote_sha(bare).decode())
    mine = load(b)
    with pytest.raises(pause.Pause):
        pause.take_remote(b, plain_args(), now=NOW)
    assert load(b) == mine and step.oid(b, "HEAD") != remote_sha(bare).decode()


def test_take_remote_looks_again_when_the_remote_moved(machines):
    a, b, _tip = _paused(machines, title="Their title")
    edit(a, title="Later")
    success(a)
    result = pause.take_remote(b, plain_args(), now=NOW)
    assert result["review_again"] and not result.get("paused"), result
    assert load(b)["title"] == "Later"


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

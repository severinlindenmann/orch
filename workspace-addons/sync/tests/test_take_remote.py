"""take-remote goes through the SAME merge authority as a normal merge (Opus hard3 #1): per ticket
merge_document with this machine's own decisions, and the reach and deletion gates. No / several merge bases are a HISTORY pause (hard3 #4)."""

from test_pause import _history_pause
from test_step import NOW, at, run, success
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

    # (A then sees B's key for the ticket: a key clash a person settles there, as after any resolve)


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

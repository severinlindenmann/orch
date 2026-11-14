"""Sync page facts (owner feedback 14 Nov, fb18): where, what, when, the last 5 syncs, in `act status`."""

import json

from test_step import ART, configure, run, save

from orch_sync import act, cli


def card(root):
    return act.status(root, cli.read(root, "settings") | {"mode": "local", "interval": 15, "remote": None})


def test_counts_and_folder(root):
    configure(root)
    save(root)
    save(root, ART, b"x" * 100)
    run(root)
    c = card(root)
    assert c["counts"]["tickets"] == 1 and c["counts"]["files"] == 1 and c["counts"]["bytes"] >= 100
    assert c["folder"] == root.name


def test_history_last_five_newest_first(root):
    configure(root)
    save(root)
    for _ in range(7):
        run(root)
    h = card(root)["history"]
    assert len(h) == 5
    assert all(set(e) == {"at", "ok", "text"} for e in h)
    assert h[0]["at"] >= h[-1]["at"]


def test_history_says_what_changed_and_plain_errors(root):
    configure(root)
    save(root)
    run(root)
    first = json.loads((root / ".orch/run/sync/history.json").read_text())["entries"][-1]
    assert first["ok"] is True and "1 ticket" in first["text"]
    run(root)
    assert (
        json.loads((root / ".orch/run/sync/history.json").read_text())["entries"][-1]["text"] == "nothing new"
    )


def test_history_unreadable_is_empty(root):
    configure(root)
    (root / ".orch/run/sync").mkdir(parents=True, exist_ok=True)
    (root / ".orch/run/sync/history.json").write_text("[not json")
    assert card(root)["history"] == []

"""Tool updates in Settings (ORCH-589): what the page reads and the person-only Update click, which starts
`orch tools update <name>` in the background."""

from __future__ import annotations

from orch import addons  # noqa: F401 - imported first, so the isolation fixture fakes its real home

from orch_dashboard import update

ROW = {"name": "acme", "label": "Acme CLI", "can_update": True}


def _status(monkeypatch, tools, job=None):
    from orch import toolupdates

    monkeypatch.setattr(
        toolupdates,
        "status",
        lambda root, refresh=False, only=None: {"tools": tools, "updates": 1, "job": job},
    )


def test_update_starts_orch_tools_update_in_the_background(ws, monkeypatch):
    _status(monkeypatch, [ROW])
    started = []
    code, _ = update.start_tool_update(
        ws, "/bin/orch", {}, "acme", start=lambda argv, **kw: started.append(argv)
    )
    assert code == 202
    assert started == [["/bin/orch", "tools", "update", "acme"]]


def test_update_is_refused_for_a_bad_name_a_tool_without_update_and_while_one_runs(ws, monkeypatch):
    def never(argv, **kw):
        raise AssertionError("started")

    _status(monkeypatch, [ROW, {"name": "gh", "label": "GitHub CLI", "can_update": False}])
    assert update.start_tool_update(ws, "/bin/orch", {}, "../x", start=never)[0] == 400
    assert update.start_tool_update(ws, "/bin/orch", {}, "gh", start=never)[0] == 409
    _status(monkeypatch, [ROW], job={"name": "codex", "label": "Codex", "status": "running"})
    code, text = update.start_tool_update(ws, "/bin/orch", {}, "acme", start=never)
    assert code == 409 and "Codex is being updated" in text


def test_a_broken_check_gives_an_empty_list_not_an_error(ws, monkeypatch):
    from orch import toolupdates

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(toolupdates, "status", boom)
    assert update.tool_updates(ws) == {"tools": [], "updates": 0, "job": None}

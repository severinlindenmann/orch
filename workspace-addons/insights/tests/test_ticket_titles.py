"""ORCH-522: the settings view's ticket list (ids and titles) comes from the core's ticket index when there is
one, not from `orch ticket list --all --json` (every ticket in full)."""

import sys
import types

from orch_insights import server


def test_titles_from_the_index(monkeypatch, tmp_path):
    mod = types.ModuleType("orch.ticketindex")
    mod.rows = lambda root, include_hidden=False: [{"id": "t_aaaaaa", "title": "One", "status": "done"}]
    monkeypatch.setitem(sys.modules, "orch.ticketindex", mod)
    monkeypatch.setattr(server, "read_json", lambda *a: (_ for _ in ()).throw(AssertionError("no command")))
    assert server.read_ticket_titles(tmp_path) == [{"id": "t_aaaaaa", "title": "One"}]


def test_without_an_index_the_command_answers(monkeypatch, tmp_path):
    mod = types.ModuleType("orch.ticketindex")

    def broken(root, include_hidden=False):
        raise OSError("no index")

    mod.rows = broken
    monkeypatch.setitem(sys.modules, "orch.ticketindex", mod)
    seen = []
    monkeypatch.setattr(server, "read_json", lambda root, orch_bin, argv: seen.append(argv) or [])
    assert server.read_ticket_titles(tmp_path) == []
    assert seen == [["ticket", "list", "--all", "--json"]]

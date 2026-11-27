"""ORCH-522: the settings view's ticket list (ids and titles) comes from the core's ticket index when there is
one, not from `orch ticket list --all --json` (every ticket in full)."""

import sys
import types

import orch

from orch_insights import server


def _index(monkeypatch, mod):
    """The stand-in index, also as the attribute of the orch package: once another test imported the real one
    (orch.reads does), `from orch import ticketindex` finds the attribute first."""
    monkeypatch.setitem(sys.modules, "orch.ticketindex", mod)
    monkeypatch.setattr(orch, "ticketindex", mod, raising=False)


def test_titles_from_the_index(monkeypatch, tmp_path):
    mod = types.ModuleType("orch.ticketindex")
    mod.rows = lambda root, include_hidden=False: [{"id": "t_aaaaaa", "title": "One", "status": "done"}]
    _index(monkeypatch, mod)
    monkeypatch.setattr(server, "read_json", lambda *a: (_ for _ in ()).throw(AssertionError("no command")))
    assert server.read_ticket_titles(tmp_path) == [{"id": "t_aaaaaa", "title": "One"}]


def test_without_an_index_the_command_answers(monkeypatch, tmp_path):
    mod = types.ModuleType("orch.ticketindex")

    def broken(root, include_hidden=False):
        raise OSError("no index")

    mod.rows = broken
    _index(monkeypatch, mod)
    seen = []
    monkeypatch.setattr(server, "read_json", lambda root, orch_bin, argv: seen.append(argv) or [])
    assert server.read_ticket_titles(tmp_path) == []
    assert seen == [["ticket", "list", "--all", "--json"]]

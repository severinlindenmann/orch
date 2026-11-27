"""ORCH-522: the settings view's ticket list (ids and titles) comes from the core's ticket index when there is
one, not from `orch ticket list --all --json` (every ticket in full)."""

from orch import ticketindex

from orch_insights import server


def test_titles_from_the_index(monkeypatch, tmp_path):
    # Patch the loaded module: collector imports may already have cached it on orch.
    monkeypatch.setattr(
        ticketindex,
        "rows",
        lambda root, include_hidden=False: [{"id": "t_aaaaaa", "title": "One", "status": "done"}],
    )
    monkeypatch.setattr(server, "read_json", lambda *a: (_ for _ in ()).throw(AssertionError("no command")))
    assert server.read_ticket_titles(tmp_path) == [{"id": "t_aaaaaa", "title": "One"}]


def test_without_an_index_the_command_answers(monkeypatch, tmp_path):
    def broken(root, include_hidden=False):
        raise OSError("no index")

    monkeypatch.setattr(ticketindex, "rows", broken)
    seen = []
    monkeypatch.setattr(server, "read_json", lambda root, orch_bin, argv: seen.append(argv) or [])
    assert server.read_ticket_titles(tmp_path) == []
    assert seen == [["ticket", "list", "--all", "--json"]]

"""Areas: agents suggest, a person accepts (areas.toml, /api/areas)."""

import json
import os

import pytest

from orch_focus import areas

from .conftest import TID
from .test_server import req


def test_add_is_always_a_suggestion_and_the_same_area_is_not_twice(ws):
    a = areas.add(ws, "Offsite", "offsite/")
    assert a == {"id": "a1", "name": "Offsite", "path": "offsite/", "state": "suggested", "tickets": []}
    assert areas.add(ws, "offsite", "other/")["id"] == "a1" and areas.add(ws, "X", "offsite/")["id"] == "a1"
    assert areas.add(ws, "Budget", "budget-2026.xlsx")["id"] == "a2"
    assert [x["state"] for x in areas.load(ws)] == ["suggested", "suggested"]


def test_accept_and_remove_and_set_ticket(ws):
    areas.add(ws, "Offsite", "offsite/")
    areas.add(ws, "Newsletter", "comms/")
    assert areas.accept(ws, "a1")["state"] == "accepted"
    areas.set_ticket(ws, TID, "Offsite")
    areas.set_ticket(ws, TID, "a2")  # moves: one area at most
    assert [a["tickets"] for a in areas.load(ws)] == [[], [TID]]
    areas.remove(ws, "a1")
    assert [a["id"] for a in areas.load(ws)] == ["a2"]
    with pytest.raises(areas.BadArea):
        areas.accept(ws, "a9")


@pytest.mark.parametrize(
    "path",
    ["/etc", "../x", "a/../../x", "~/x", "C:/x", ".orch/secrets", ".git/config", "", "a\x00b", "x" * 300],
)
def test_paths_outside_the_workspace_are_refused(ws, path):
    with pytest.raises(areas.BadArea):
        areas.add(ws, "Bad", path)


def test_names_are_plain():
    for bad in ("", "x" * 41, "a<b", "a\nb"[:0]):
        with pytest.raises(areas.BadArea):
            areas.clean_name(bad)
    assert areas.clean_name("  Two   words ") == "Two words"


def test_a_bad_or_linked_file_reads_as_no_areas_and_a_forged_state_is_not_accepted(ws, tmp_path):
    d = ws / ".orch" / "addons" / "focus"
    d.mkdir(parents=True)
    (d / "areas.toml").write_text("not [toml")
    assert areas.load(ws) == []
    (d / "areas.toml").write_text(
        '[[area]]\nid="a1"\nname="X"\npath="x/"\nstate="bogus"\n[[area]]\nid="../x"\nname="Y"\npath="y/"\n'
    )
    assert [(a["id"], a["state"]) for a in areas.load(ws)] == [("a1", "suggested")]
    (d / "areas.toml").unlink()
    outside = tmp_path / "elsewhere.toml"
    outside.write_text('[[area]]\nid="a1"\nname="X"\npath="x/"\nstate="accepted"\n')
    os.symlink(outside, d / "areas.toml")
    assert areas.load(ws) == []


def test_a_linked_addon_folder_is_never_written(ws, tmp_path):
    (ws / ".orch" / "addons").mkdir()
    (tmp_path / "evil").mkdir()
    os.symlink(tmp_path / "evil", ws / ".orch" / "addons" / "focus")
    with pytest.raises(areas.BadArea):
        areas.add(ws, "A", "a/")
    assert list((tmp_path / "evil").iterdir()) == []


def test_api_areas_lists_and_a_click_accepts_and_removes(server, ws):
    areas.add(ws, "Offsite", "offsite/")
    got = json.loads(req(server, "GET", "/api/areas")[1])["areas"]
    assert got == [
        {"id": "a1", "name": "Offsite", "path": "offsite/", "state": "suggested", "who": [], "quiet": True}
    ]
    st = req(server, "POST", "/api/act", {"op": "area.accept", "args": {"area": "a1"}})[0]
    assert st == 200 and areas.load(ws)[0]["state"] == "accepted"
    assert req(server, "POST", "/api/act", {"op": "area.accept", "args": {"area": "a7"}})[0] == 422
    assert req(server, "POST", "/api/act", {"op": "area.accept", "args": {"area": "a1", "x": 1}})[0] == 400
    assert req(server, "POST", "/api/act", {"op": "area.remove", "args": {"area": "a1"}})[0] == 200
    assert areas.load(ws) == []


def test_strip_shows_who_works_in_an_area(ws):
    areas.add(ws, "Offsite", "offsite/")
    areas.set_ticket(ws, TID, "a1")
    got = areas.strip(ws, [{"ticket": TID, "agent": "Claude"}, {"ticket": "t_other0001", "agent": "Codex"}])
    assert got[0]["who"] == ["Claude"] and got[0]["quiet"] is False


def test_cli_only_suggests(ws, capsys):
    from orch_focus import cli

    assert cli.main(["--dir", str(ws), "area", "add", "Offsite", "offsite/", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "suggested"
    assert cli.main(["--dir", str(ws), "area", "set", TID, "Offsite"]) == 0
    assert cli.main(["--dir", str(ws), "area", "add", "Bad", "../x"]) == 2
    assert cli.main(["--dir", str(ws), "area", "list", "--json"]) == 0
    assert [a["tickets"] for a in json.loads(capsys.readouterr().out.splitlines()[-1])] == [[TID]]


def _snapshot(server):
    return {
        p: req(server, "GET", p)[1]
        for p in ("/api/live", f"/api/t/{TID}", "/api/procs", "/api/tickets", "/api/mobile")
    }


def test_a_forged_areas_file_changes_nothing_but_the_strip(server, ws, fake_orch):
    """areas.toml is writable by agents. Whatever it says, only the strip changes: no card, ticket, permission,
    process or action differs, and nothing outside areas.toml is read or written because of it."""
    before = _snapshot(server)
    calls_before = (
        (fake_orch.parent / "calls.jsonl").read_text() if (fake_orch.parent / "calls.jsonl").exists() else ""
    )
    quiet = lambda p: p.is_file() and "runs" not in p.parts  # the work clock and event logs are Focus's own
    files_before = {p: p.stat().st_mtime_ns for p in ws.rglob("*") if quiet(p)}
    d = ws / ".orch" / "addons" / "focus"
    d.mkdir(parents=True, exist_ok=True)
    (d / "areas.toml").write_text(
        f'[[area]]\nid="a1"\nname="Everything"\npath="."\nstate="accepted"\ntickets=["{TID}"]\n'
    )
    assert areas.load(ws) == []  # "." is not an area path: refused row
    (d / "areas.toml").write_text(
        f'[[area]]\nid="a1"\nname="Forged"\npath="x/"\nstate="accepted"\ntickets=["{TID}"]\n'
    )
    assert _snapshot(server) == before
    shown = json.loads(req(server, "GET", "/api/areas")[1])["areas"]
    assert [(a["name"], a["state"]) for a in shown] == [("Forged", "accepted")]
    after = {p: p.stat().st_mtime_ns for p in ws.rglob("*") if quiet(p) and p != d / "areas.toml"}
    assert after == {p: t for p, t in files_before.items() if p in after}
    calls_after = (fake_orch.parent / "calls.jsonl").read_text()
    assert [c for c in calls_after.splitlines()[len(calls_before.splitlines()) :] if "area" in c] == []


def test_nothing_but_the_areas_surfaces_reads_areas():
    """The invariant in code: areas are not used for access, permits, routing or the guard."""
    from pathlib import Path

    src = Path(areas.__file__).parent
    users = {
        p.name
        for p in src.glob("*.py")
        if p.name != "areas.py"
        and ("areas." in p.read_text() or "import areas" in p.read_text() or ", areas" in p.read_text())
    }
    assert users <= {"cli.py", "server.py"}
    server_text = (src / "server.py").read_text()
    for name in ("actions", "permissions", "proofs"):
        assert "areas" not in (src / f"{name}.py").read_text()
    assert server_text.count("areas.strip") == 2 and "areas.load" not in server_text

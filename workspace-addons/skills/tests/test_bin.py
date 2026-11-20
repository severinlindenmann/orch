"""Skills add-on: Delete into a bin, Restore, and New skill (ORCH-841). No file is ever lost, also when a move is
cut off half way."""

import json
import os
import shutil
from pathlib import Path

import pytest

from orch_skills import bin as skill_bin
from orch_skills import cli, model, switches


def _files(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def _skill(data, name):
    return next(i for i in data["skills"] if i["name"] == name)


@pytest.fixture
def walk(ws):
    """release-walk with a second file, so a half done copy or removal can be seen."""
    folder = ws / ".agents/skills/release-walk"
    (folder / "references").mkdir()
    (folder / "references/steps.md").write_text("1. install\n2. click\n")
    return ws, folder, _files(folder)


def test_delete_a_workspace_skill_and_restore_it(walk):
    ws, folder, before = walk
    data = model.build(ws)
    assert _skill(data, "release-walk")["can_delete"]
    assert not _skill(data, "orch-hello")["can_delete"] and not _skill(data, "github")["can_delete"]
    res = model.delete(ws, "skill:workspace:release-walk", "human:Anna")
    row = res["bin"]
    assert not folder.exists()
    assert (
        row["id"].startswith("bin:workspace:") and row["can_restore"] and row["from"] == ".agents/skills/release-walk"
    )
    entry = ws / ".orch/addons/skills/bin" / row["id"].split(":", 2)[2]
    assert _files(entry / "item") == before and json.loads((entry / "record.json").read_text())["state"] == "in-bin"
    data = model.build(ws)
    assert "release-walk" not in {i["name"] for i in data["skills"]}
    assert [r["name"] for r in data["bin"]] == ["release-walk"]
    model.restore(ws, row["id"], "human:Anna")
    assert _files(folder) == before and not entry.exists()
    assert model.build(ws)["bin"] == []


def test_a_computer_skill_is_kept_outside_the_workspace(ws, tmp_path):
    home_skill = tmp_path / "home/.claude/skills/status-page"
    before = _files(home_skill)
    row = model.delete(ws, "skill:mine:status-page", "human:Anna")["bin"]
    assert not home_skill.exists()
    entry = skill_bin.mine_bin() / row["id"].split(":", 2)[2]
    assert ws not in entry.parents and _files(entry / "item") == before
    assert row["from"] == "~/.claude/skills/status-page"
    assert not (ws / ".orch/addons/skills/bin").exists() or not any((ws / ".orch/addons/skills/bin").iterdir())
    model.restore(ws, row["id"], "human:Anna")
    assert _files(home_skill) == before


def test_nothing_is_removed_from_the_bin_by_itself(walk):
    ws, _folder, _ = walk
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]
    for _ in range(3):
        model.build(ws)
    assert [r["id"] for r in model.build(ws)["bin"]] == [row["id"]]


def test_restore_never_replaces_a_new_skill_of_that_name(walk):
    ws, folder, _ = walk
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: release-walk\ndescription: the new one, written after the delete\n---\n"
    )
    rows = model.build(ws)["bin"]
    assert not rows[0]["can_restore"] and "there again" in rows[0]["why"]
    with pytest.raises(switches.Refused, match="never replaces"):
        model.restore(ws, row["id"], "human:Anna")
    assert "the new one" in (folder / "SKILL.md").read_text()
    assert model.build(ws)["bin"][0]["id"] == row["id"]  # still in the bin


def test_orch_admin_and_linked_skills_are_not_deleted(ws, tmp_path):
    for target in ("skill:orch:orch-hello", "skill:admin:github", "instructions:workspace:AGENTS.md"):
        with pytest.raises(switches.Refused, match="cannot be deleted"):
            model.delete(ws, target, "human:Anna")
    elsewhere = tmp_path / "elsewhere/linked"
    elsewhere.mkdir(parents=True)
    (elsewhere / "SKILL.md").write_text("---\nname: linked\ndescription: a skill that lives somewhere else\n---\n")
    os.symlink(elsewhere, ws / ".agents/skills/linked")
    assert not _skill(model.build(ws), "linked")["can_delete"]
    with pytest.raises(switches.Refused, match="link"):
        model.delete(ws, "skill:workspace:linked", "human:Anna")
    assert (elsewhere / "SKILL.md").is_file()


def test_a_forged_bin_record_cannot_restore_somewhere_else(walk, tmp_path):
    ws, _folder, _ = walk
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]
    entry = ws / ".orch/addons/skills/bin" / row["id"].split(":", 2)[2]
    rec = json.loads((entry / "record.json").read_text())
    for origin in ("../../outside", str(tmp_path / "x"), ".orch/harness/skills/x", ".agents/skills/a/b"):
        rec["from"] = origin
        (entry / "record.json").write_text(json.dumps(rec))
        with pytest.raises(switches.Refused):
            model.restore(ws, row["id"], "human:Anna")
    assert not (tmp_path / "x").exists() and not (ws.parent / "outside").exists()
    for bad in ("bin:workspace:../x", "bin:elsewhere:" + entry.name, "skill:workspace:release-walk"):
        with pytest.raises(switches.Refused):
            model.restore(ws, bad, "human:Anna")


# ---- cut off half way --------------------------------------------------------------------------------------


def test_a_delete_cut_off_while_copying_is_undone(walk):
    ws, folder, before = walk
    entry = ws / ".orch/addons/skills/bin/20261120T120000Z-release-walk-abcdef"
    (entry / "item").mkdir(parents=True)
    shutil.copy(folder / "SKILL.md", entry / "item/SKILL.md")  # half the files, then the power went
    (entry / "record.json").write_text(
        json.dumps(
            {
                "schema": skill_bin.SCHEMA,
                "where": "workspace",
                "name": "release-walk",
                "from": ".agents/skills/release-walk",
                "state": "copying",
            }
        )
    )
    data = model.build(ws)
    assert not entry.exists() and data["bin"] == [] and _files(folder) == before
    assert _skill(data, "release-walk")["on"]


def test_a_failed_copy_leaves_the_skill_where_it_was(walk, monkeypatch):
    ws, folder, before = walk

    def half(src, dst, *args, **kw):
        Path(dst).mkdir()
        shutil.copy(Path(src) / "SKILL.md", Path(dst) / "SKILL.md")
        raise OSError("disk full")

    monkeypatch.setattr(skill_bin.shutil, "copytree", half)
    with pytest.raises(OSError):
        model.delete(ws, "skill:workspace:release-walk", "human:Anna")
    assert _files(folder) == before and model.build(ws)["bin"] == []


def test_a_delete_cut_off_while_removing_is_finished(walk, monkeypatch):
    ws, folder, before = walk
    real = skill_bin._clear_held

    def cut(aside, held):
        (aside / "references/steps.md").unlink()
        raise KeyboardInterrupt  # the process stops here: the record still says "removing"

    monkeypatch.setattr(skill_bin, "_clear_held", cut)
    with pytest.raises(KeyboardInterrupt):
        model.delete(ws, "skill:workspace:release-walk", "human:Anna")
    monkeypatch.setattr(skill_bin, "_clear_held", real)
    assert list(folder.parent.glob(".orch-delete-*"))  # half removed, moved aside
    rows = model.build(ws)["bin"]
    assert not folder.exists() and rows[0]["state"] == "in-bin" and rows[0]["can_restore"]
    model.restore(ws, rows[0]["id"], "human:Anna")
    assert _files(folder) == before


def test_finishing_a_cut_off_delete_keeps_files_added_since(walk, monkeypatch):
    ws, folder, _ = walk

    def cut(src, entry, held):
        raise KeyboardInterrupt  # cut off before the folder was moved aside

    monkeypatch.setattr(skill_bin, "_finish_removal", cut)
    with pytest.raises(KeyboardInterrupt):
        model.delete(ws, "skill:workspace:release-walk", "human:Anna")
    monkeypatch.undo()
    (folder / "notes.md").write_text("written after the delete started")
    rows = model.build(ws)["bin"]
    assert (folder / "notes.md").read_text() == "written after the delete started"
    assert not (folder / "SKILL.md").exists() and "stayed" in rows[0]["note"]


def test_a_restore_cut_off_before_the_rename_is_undone(walk, monkeypatch):
    ws, folder, before = walk
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]
    entry = ws / ".orch/addons/skills/bin" / row["id"].split(":", 2)[2]
    rec = json.loads((entry / "record.json").read_text())
    rec["state"] = "restoring"
    (entry / "record.json").write_text(json.dumps(rec))
    tmp = folder.parent / f".orch-restore-{entry.name}"
    tmp.mkdir()
    shutil.copy(entry / "item/SKILL.md", tmp / "SKILL.md")  # half of the copy
    rows = model.build(ws)["bin"]
    assert not tmp.exists() and not folder.exists() and rows[0]["state"] == "in-bin"
    model.restore(ws, row["id"], "human:Anna")
    assert _files(folder) == before


def test_a_restore_cut_off_after_the_rename_is_finished(walk, monkeypatch):
    ws, folder, before = walk
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]
    real = skill_bin._write

    def stop(entry, doc):
        if doc.get("state") == "restored":
            raise KeyboardInterrupt
        real(entry, doc)

    monkeypatch.setattr(skill_bin, "_write", stop)
    with pytest.raises(KeyboardInterrupt):
        model.restore(ws, row["id"], "human:Anna")
    monkeypatch.undo()
    assert _files(folder) == before  # in place, the record still says "restoring"
    assert model.build(ws)["bin"] == []
    assert _files(folder) == before


def test_a_failed_restore_stays_in_the_bin(walk, monkeypatch):
    ws, folder, _ = walk
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]

    def fail(a, b):
        raise OSError("no")

    monkeypatch.setattr(skill_bin.os, "rename", fail)
    with pytest.raises(OSError):
        model.restore(ws, row["id"], "human:Anna")
    monkeypatch.undo()
    assert not folder.exists() and not list(folder.parent.glob(".orch-restore-*"))
    assert model.build(ws)["bin"][0]["can_restore"]


# ---- new skill ---------------------------------------------------------------------------------------------


def test_new_skill_makes_a_draft_with_the_standard_header(ws):
    res = model.new_skill(ws, "weekly-report", "Anna")
    text = (ws / ".agents/skills/weekly-report/SKILL.md").read_text()
    assert text.startswith("---\nname: weekly-report\ndescription: ")
    assert 'metadata:\n  version: "0.1.0"\n  owner: "Anna"\n  status: "draft"\n---\n# weekly-report\n' in text
    assert res["item"]["where"] == "workspace" and res["item"]["can_delete"]


def test_new_skill_header_reads_back(ws):
    skillmeta = pytest.importorskip("orch.skillmeta")
    model.new_skill(ws, "weekly-report", "Anna")
    head = skillmeta.try_header(ws / ".agents/skills/weekly-report")
    assert head["metadata"]["status"] == "draft" and head["metadata"]["owner"] == "Anna"


@pytest.mark.parametrize(
    "name", ["", "Weekly", "a--b", "-a", "a b", "../x", "orch-mine", "release-walk", "github", "status-page", "x" * 65]
)
def test_new_skill_refuses_bad_or_taken_names(ws, name):
    with pytest.raises(switches.Refused):
        model.new_skill(ws, name, "Anna")
    assert not (ws / ".agents/skills" / name / "SKILL.md").exists() or name in ("release-walk", "github")


# ---- the command and the page's clicks ---------------------------------------------------------------------


def test_cli_delete_bin_restore_new_and_history(walk, capsys):
    ws, folder, before = walk
    d = ["--dir", str(ws)]
    assert cli.main([*d, "act", "delete", "skill:workspace:release-walk", "--by", "human:Anna", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["changed"] and out["bin"]["id"].startswith("bin:workspace:")
    assert cli.main([*d, "bin"]) == 0
    assert "release-walk from .agents/skills/release-walk" in capsys.readouterr().out
    assert cli.main([*d, "act", "restore", out["bin"]["id"], "--by", "human:Anna", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["changed"] and _files(folder) == before
    assert cli.main([*d, "act", "new", "skill:workspace:weekly-report", "--by", "human:Anna", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["item"]["name"] == "weekly-report"
    assert cli.main([*d, "history"]) == 0
    text = capsys.readouterr().out
    assert "moved to the bin" in text and "restored" in text and "made as a draft" in text


@pytest.mark.parametrize(
    "verb,target",
    [
        ("restore", "skill:workspace:release-walk"),
        ("new", "skill:workspace:Bad_Name"),
        ("new", "skill:orch:x"),
        ("delete", "bin:workspace:20261120T120000Z-x-abcdef"),
        ("purge", "skill:workspace:release-walk"),
    ],
)
def test_cli_act_refuses_other_shapes(walk, capsys, verb, target):
    ws, folder, before = walk
    assert cli.main(["--dir", str(ws), "act", verb, target, "--by", "human:Anna", "--json"]) == 2
    assert "error" in json.loads(capsys.readouterr().out) and _files(folder) == before


def test_a_helper_cannot_delete_restore_or_make(walk, capsys, monkeypatch):
    ws, folder, before = walk
    monkeypatch.setenv("ORCH_AGENT", "claude")
    for verb, target in (("delete", "skill:workspace:release-walk"), ("new", "weekly-report")):
        assert cli.main(["--dir", str(ws), verb, target, "--json"]) == 2
        assert "Only a person" in json.loads(capsys.readouterr().out)["error"]
    assert _files(folder) == before and not (ws / ".agents/skills/weekly-report").exists()


# ---- points from the outside review --------------------------------------------------------------------------


def test_a_skill_file_named_like_orchs_own_names_is_restored_intact(walk):
    ws, folder, _ = walk
    (folder / ".orch-restore").write_text("the author's own file")
    before = _files(folder)
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]
    model.restore(ws, row["id"], "human:Anna")
    assert _files(folder) == before


def test_restore_does_not_remove_a_folder_in_its_way(walk):
    ws, folder, _ = walk
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]
    tmp = folder.parent / (".orch-restore-" + row["id"].split(":", 2)[2])
    tmp.mkdir()
    (tmp / "mine.txt").write_text("somebody else's")
    with pytest.raises(switches.Refused, match="in the way"):
        model.restore(ws, row["id"], "human:Anna")
    assert (tmp / "mine.txt").read_text() == "somebody else's" and not folder.exists()


def test_recovering_a_restore_leaves_a_foreign_temporary_folder(walk):
    ws, folder, _ = walk
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]
    entry = ws / ".orch/addons/skills/bin" / row["id"].split(":", 2)[2]
    rec = json.loads((entry / "record.json").read_text())
    rec["state"] = "restoring"
    (entry / "record.json").write_text(json.dumps(rec))
    tmp = folder.parent / f".orch-restore-{entry.name}"
    tmp.mkdir()
    (tmp / "other.txt").write_text("not from the bin")
    rows = model.build(ws)["bin"]
    assert (tmp / "other.txt").exists() and rows[0]["state"] == "in-bin" and "left it" in rows[0]["note"]


def test_restore_never_replaces_an_empty_folder_that_appears(walk, monkeypatch):
    ws, folder, _ = walk
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]
    real = shutil.copytree

    def then_someone_makes_it(src, dst, *args, **kw):
        real(src, dst, *args, **kw)
        if Path(dst).name.startswith(".orch-restore-"):  # the top call, not shutil's own for subfolders
            folder.mkdir()  # an empty folder of that name appears between the check and the rename

    monkeypatch.setattr(skill_bin.shutil, "copytree", then_someone_makes_it, raising=True)
    with pytest.raises(switches.Refused, match="never replaces"):
        model.restore(ws, row["id"], "human:Anna")
    monkeypatch.undo()
    assert folder.is_dir() and not any(folder.iterdir())  # theirs, untouched
    assert model.build(ws)["bin"][0]["state"] == "in-bin"


def test_a_file_changed_during_the_removal_stays(walk, monkeypatch):
    ws, folder, _ = walk
    real = skill_bin._clear_held

    def edit_then_clear(aside, held):
        (aside / "references/steps.md").write_text("changed by an editor just now")
        return real(aside, held)

    monkeypatch.setattr(skill_bin, "_clear_held", edit_then_clear)
    row = model.delete(ws, "skill:workspace:release-walk", "human:Anna")["bin"]
    assert (folder / "references/steps.md").read_text() == "changed by an editor just now"
    assert not (folder / "SKILL.md").exists() and "stayed" in row["note"]


def test_a_list_does_not_recover_while_a_change_runs(walk):
    ws, folder, before = walk
    entry = ws / ".orch/addons/skills/bin/20261120T120000Z-release-walk-abcdef"
    (entry / "item").mkdir(parents=True)
    (entry / "record.json").write_text(
        json.dumps(
            {
                "schema": skill_bin.SCHEMA,
                "where": "workspace",
                "name": "release-walk",
                "from": ".agents/skills/release-walk",
                "state": "copying",
            }
        )
    )
    with skill_bin.locked(ws):
        model.build(ws)
        assert entry.exists()  # the running change owns it
    model.build(ws)
    assert not entry.exists() and _files(folder) == before

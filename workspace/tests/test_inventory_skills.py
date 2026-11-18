"""ORCH-416: orch record counts carries what the workspace can use (inventory.md), so Insights can say how
many connected services, skills and keys there are instead of "Not measured yet"."""

import json
import os
import sys
from pathlib import Path

from test_fakeorch import check, validator

from orch import addons, cli, inventory

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "contracts"))
import validate  # noqa: E402  (the reference functions of the contracts)


def skill(base: Path, name: str, text: str = "x", extra: dict | None = None) -> Path:
    folder = base / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {text}\n---\n")
    for rel, body in (extra or {}).items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(body)
    return folder


def counts(capsys, *argv):
    code = cli.main(["record", "counts", *argv, "--json"])
    out = capsys.readouterr().out
    assert code == 0, out
    return json.loads(out.splitlines()[-1])


def test_skill_version_matches_the_reference(tmp_path):
    folder = skill(tmp_path, "a", extra={"topics/10.md": "t", "b.md": "b", ".DS_Store": "junk"})
    # raw bytes: on Windows write_text wrote CRLF, and the version hashes the bytes
    files = {
        p.relative_to(folder).as_posix(): p.read_bytes().decode("utf-8")
        for p in folder.rglob("*")
        if p.is_file() and not p.name.startswith(".")
    }
    assert inventory.skill_version(folder) == validate.inv_skill_version(files)
    (folder / ".orch-shared").write_text("marker")  # dot names never change the version
    assert inventory.skill_version(folder) == validate.inv_skill_version(files)


def test_workspace_and_tool_skills_with_shadowing(proj):
    home = addons.real_home()
    skill(proj / ".agents" / "skills", "mine")
    skill(proj / ".agents" / "skills", "both")
    skill(home / ".claude" / "skills", "both", text="other")
    skill(home / ".claude" / "skills", "users-own")
    (proj / ".agents" / "skills" / "not-a-skill").mkdir()  # no SKILL.md
    outside = skill(proj.parent / f"{proj.name}_outside", "leak")
    os.symlink(outside, proj / ".agents" / "skills" / "leak")  # a link out of the workspace is left out
    got = {(s["name"], s["source"]): s for s in inventory.skills(proj)}
    names = {n for n, _ in got}
    assert {"mine", "both", "users-own"} <= names and "not-a-skill" not in names and "leak" not in names
    assert got[("both", "workspace")]["shadowed"] is False and got[("both", "harness")]["shadowed"] is True
    assert got[("users-own", "harness")]["shadowed"] is False
    assert got[("mine", "workspace")]["version"].startswith("sha256:")


def test_counts_carry_the_inventory_and_list_unused_items(proj, capsys):
    skill(proj / ".agents" / "skills", "never-used")
    (proj / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "drive": {"command": "/usr/local/bin/gdrive-mcp", "args": ["--x"], "env": {"K": "v"}}
                }
            }
        )
    )
    ans = counts(capsys)
    check(validator("counts", "answer"), ans, "counts")
    inv = ans["inventory"]
    assert any(s["name"] == "never-used" for s in inv["skills"])
    (conn,) = [c for c in inv["connections"] if c["name"] == "drive"]
    assert conn["command"] == "gdrive-mcp" and conn["source"] == "harness"
    text = json.dumps(ans)
    assert "--x" not in text and '"v"' not in text  # names only: no argument and no env value
    by = {(i["kind"], i["name"]): i for i in ans["items"]}
    # nothing ran in the window, so an unused item is "can't tell yet", never a 0 that looks measured
    assert by[("skill", "never-used")]["seen"] == "unknown" and by[("skill", "never-used")]["uses"] == 0
    assert by[("mcp", "drive")]["seen"] == "unknown"
    # --kind narrows the unused items too; the inventory stays whole
    only = counts(capsys, "--kind", "mcp")
    assert {i["kind"] for i in only["items"]} == {"mcp"} and only["inventory"]["skills"]


def test_insights_measures_connected_services_from_the_counts(proj, capsys):
    """With the list in the counts, the Connected services tile is a number, not "Not measured yet"."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workspace-addons" / "insights" / "src"))
    from orch_insights.overview import build_overview

    (proj / ".mcp.json").write_text(json.dumps({"mcpServers": {"drive": {"command": "npx"}}}))
    view = build_overview(counts(capsys))
    assert "error" not in view, view
    assert view["tabs"]["connections"] == {"count": 1, "known": True}

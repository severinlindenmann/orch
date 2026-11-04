from importlib import metadata, resources


def test_entry_point_and_skill_text():
    eps = metadata.entry_points(group="orch.addons")
    assert any(e.name == "scheduler" for e in eps)
    root = resources.files("orch_scheduler") / "skills" / "orch-scheduler"
    assert (root / "SKILL.md").read_text().startswith("---\nname: orch-scheduler\n")
    block = (root / "agents-block.md").read_text()
    assert block.startswith("<!-- orch:begin orch-scheduler -->") and block.rstrip().endswith("<!-- orch:end orch-scheduler -->")

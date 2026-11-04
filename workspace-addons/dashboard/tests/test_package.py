from importlib import metadata, resources


def test_entry_point_and_skill_text():
    eps = metadata.entry_points(group="orch.addons")
    assert any(e.name == "dashboard" for e in eps)
    root = resources.files("orch_dashboard") / "skills" / "orch-dashboard"
    skill = (root / "SKILL.md").read_text()
    assert skill.startswith("---\nname: orch-dashboard\n")
    block = (root / "agents-block.md").read_text()
    assert block.startswith("<!-- orch:begin orch-dashboard -->") and block.rstrip().endswith("<!-- orch:end orch-dashboard -->")

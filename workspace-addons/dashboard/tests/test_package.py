from importlib import metadata, resources


def test_entry_point_and_skill_text():
    eps = metadata.entry_points(group="orch.addons")
    assert any(e.name == "dashboard" for e in eps)
    root = resources.files("orch_dashboard") / "skills" / "orch-dashboard"
    skill = (root / "SKILL.md").read_text()
    assert skill.startswith("---\nname: orch-dashboard\n")
    block = (root / "agents-block.md").read_text()
    assert block.startswith("<!-- orch:begin orch-dashboard -->") and block.rstrip().endswith("<!-- orch:end orch-dashboard -->")


def test_web_has_icon_sprite_and_no_inline_styles():
    """CSP is style-src 'self': inline style attributes would be silently blocked (the visual charts use SVG attributes)."""
    from orch_dashboard.server import web_file
    js, html = web_file("app.js").decode(), web_file("index.html").decode()
    assert 'style="' not in js and "i-check" in html and "i-question" in html

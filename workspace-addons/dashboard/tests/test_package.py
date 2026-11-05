from importlib import metadata, resources


def test_entry_point_and_skill_text():
    eps = metadata.entry_points(group="orch.addons")
    assert any(e.name == "dashboard" and e.value == "orch_dashboard" for e in eps)
    root = resources.files("orch_dashboard") / "skills" / "orch-dashboard"
    skill = (root / "SKILL.md").read_text()
    assert skill.startswith("---\nname: orch-dashboard\n")
    block = (root / "AGENTS-block.md").read_text()
    assert block.startswith("<!-- orch:addon:dashboard -->") and block.rstrip().endswith("<!-- /orch:addon:dashboard -->")


def test_manifest():
    import tomllib
    m = tomllib.loads((resources.files("orch_dashboard") / "orch-addon.toml").read_text())
    assert m["schema"] == "orch.addon/1" and m["orch_api"] == 1 and m["name"] == "dashboard" and m["run"] == "orch_dashboard"
    assert "dashboard" not in m and len(m["description"]) < 120  # the host has no tab of its own
    assert (resources.files("orch_dashboard") / m["skill"] / "SKILL.md").is_file()
    assert (resources.files("orch_dashboard") / m["agents_block"]).is_file()


def test_web_has_icon_sprite_and_no_inline_styles():
    """CSP is style-src 'self': inline style attributes would be silently blocked (the visual charts use SVG attributes)."""
    from orch_dashboard.server import web_file
    js, html = web_file("app.js").decode(), web_file("index.html").decode()
    assert 'style="' not in js and "i-check" in html and "i-question" in html


def test_web_plain_words_and_no_inline_style_flex():
    from orch_dashboard.server import web_file
    js = web_file("app.js").decode()
    assert "Code updated" in js and "questions" in js and "updates this week" in js and "nextCron" not in js
    assert "Code change" not in js and "No time set" not in js


def test_status_bar_is_proportional_svg_without_inline_style():
    from pathlib import Path
    web = Path(__file__).resolve().parents[1] / "src" / "orch_dashboard" / "web"
    js = (web / "app.js").read_text()
    assert 'class="segbar"' in js and "n / total * 100" in js
    assert 'style="' not in js.split("function statusBar")[1].split("function ")[0]

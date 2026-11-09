from importlib import metadata, resources


def test_entry_point_and_skill_text():
    eps = metadata.entry_points(group="orch.addons")
    assert any(e.name == "dashboard" and e.value == "orch_dashboard" for e in eps)
    root = resources.files("orch_dashboard") / "skills" / "orch-dashboard"
    skill = (root / "SKILL.md").read_text()
    assert skill.startswith("---\nname: orch-dashboard\n")
    block = (root / "AGENTS-block.md").read_text()
    assert block.startswith("<!-- orch:addon:dashboard -->") and block.rstrip().endswith(
        "<!-- /orch:addon:dashboard -->"
    )


def test_manifest():
    import tomllib

    m = tomllib.loads((resources.files("orch_dashboard") / "orch-addon.toml").read_text())
    assert (
        m["schema"] == "orch.addon/1"
        and m["orch_api"] == 1
        and m["name"] == "dashboard"
        and m["run"] == "orch_dashboard"
    )
    assert "dashboard" not in m and len(m["description"]) < 120  # the host has no tab of its own
    assert (resources.files("orch_dashboard") / m["skill"] / "SKILL.md").is_file()
    assert (resources.files("orch_dashboard") / m["agents_block"]).is_file()


def test_web_has_no_inline_styles():
    """CSP is style-src 'self': inline style attributes would be silently blocked."""
    from orch_dashboard.server import web_file

    from . import webjs

    assert 'style="' not in webjs.all_js() and " style=" not in web_file("index.html").decode()
    for p in webjs.PAGES:  # every page module and its stylesheet is packaged and listed in the page
        assert web_file(f"pages/{p}.js") and web_file(f"pages/{p}.css")
        assert f'src="pages/{p}.js"' in web_file("index.html").decode()

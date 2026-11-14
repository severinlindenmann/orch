"""The master design system (orch_ui/static): every file a page links exists, the gallery is complete, no copies."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "workspace" / "src" / "orch_ui" / "static"
ADDONS = ROOT / "workspace-addons"


def _links(html: str, prefix: str) -> list[str]:
    return re.findall(rf'(?:href|src)="{re.escape(prefix)}([A-Za-z0-9._/-]+)"', html)


def test_every_kit_file_a_page_links_exists_in_the_master():
    pages = {
        "dashboard": (ADDONS / "dashboard/src/orch_dashboard/web/index.html", "kit/"),
        "focus": (ADDONS / "focus/src/orch_focus/web/index.html", "__P__/kit/"),
        "insights": (ADDONS / "insights/src/orch_insights/web/index.html", "__P__/kit/"),
        "factory": (ADDONS / "factory/src/orch_factory/web/index.html", "__P__/kit/"),
    }
    for name, (path, prefix) in pages.items():
        links = _links(path.read_text(), prefix)
        assert links, name
        for link in links:
            assert (STATIC / link).is_file(), f"{name} links kit/{link} but the master has no such file"


def test_add_on_servers_serve_what_their_pages_link():
    for name, mod in (("focus", "orch_focus"), ("insights", "orch_insights"), ("factory", "orch_factory")):
        server = (ADDONS / name / "src" / mod / "server.py").read_text()
        listed = set(re.findall(r'"([a-z0-9-]+\.(?:css|js))"', server.split("KIT_FILES", 1)[1].split(")", 1)[0]))
        linked = set(_links((ADDONS / name / "src" / mod / "web" / "index.html").read_text(), "__P__/kit/"))
        assert linked <= listed, f"{name}: page links kit files its server does not serve: {linked - listed}"


def test_no_add_on_carries_a_kit_copy():
    assert not list(ADDONS.glob("*/src/*/web/kit")), "kit copies are gone; pages load orch_ui/static"


def test_gallery_links_exist_and_use_only_the_master():
    html = (STATIC / "gallery.html").read_text()
    for link in re.findall(r'(?:href|src)="([a-z0-9][a-z0-9._/-]*\.(?:css|js|svg|pdf|csv|md))"', html):
        assert (STATIC / link).is_file(), link
    assert "<style" not in html.lower()
    for sect in ("kit", "foundations", "controls", "results", "states", "overlays", "motion"):
        assert f'id="{sect}"' in html, sect
    # loading, empty and error each have an example
    for word in ("Loaded", "Loading", "Empty", "Error"):
        assert word in html
    js = (STATIC / "gallery.js").read_text()
    for builder in ("statusIcon", "state(", "stat(", "progress(", "table(", "sheet("):
        assert builder in js, builder


def test_design_doc_names_how_to_add_a_component():
    doc = (STATIC / "DESIGN.md").read_text()
    assert "How to add a component" in doc and "gallery" in doc and "SX-1" in doc


def test_one_chevron_no_text_glyph():
    for name in ("select.js", "components.css", "widgets.js"):
        assert "⌄" not in (STATIC / name).read_text() and "⌄" not in (STATIC / name).read_text(), name

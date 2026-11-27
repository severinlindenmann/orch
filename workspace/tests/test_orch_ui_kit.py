"""The master design system (orch_ui/static): linked files exist, the gallery is complete, no copies."""

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
        "insights": (ADDONS / "insights/src/orch_insights/web/index.html", "__P__/kit/"),
        "factory": (ADDONS / "factory/src/orch_factory/web/index.html", "__P__/kit/"),
        "usage": (ADDONS / "usage/src/orch_usage/web/index.html", "__P__/kit/"),
    }
    for name, (path, prefix) in pages.items():
        links = _links(path.read_text(encoding="utf-8"), prefix)
        assert links, name
        for link in links:
            assert (STATIC / link).is_file(), f"{name} links kit/{link} but the master has no such file"


def test_add_on_servers_serve_what_their_pages_link():
    for name, mod in (
        ("insights", "orch_insights"),
        ("factory", "orch_factory"),
        ("usage", "orch_usage"),
    ):
        server = (ADDONS / name / "src" / mod / "server.py").read_text(encoding="utf-8")
        table = server.split("KIT_FILES", 1)[1].split(")", 1)[0]
        listed = set(re.findall(r'"([a-z0-9-]+\.(?:css|js))"', table))
        linked = set(
            _links(
                (ADDONS / name / "src" / mod / "web" / "index.html").read_text(encoding="utf-8"), "__P__/kit/"
            )
        )
        assert linked <= listed, f"{name}: page links kit files its server does not serve: {linked - listed}"


def test_no_add_on_carries_a_kit_copy():
    assert not list(ADDONS.glob("*/src/*/web/kit")), "kit copies are gone; pages load orch_ui/static"


def test_gallery_links_exist_and_use_only_the_master():
    html = (STATIC / "gallery.html").read_text(encoding="utf-8")
    for link in re.findall(r'(?:href|src)="([a-z0-9][a-z0-9._/-]*\.(?:css|js|svg|pdf|csv|md))"', html):
        assert (STATIC / link).is_file(), link
    assert "<style" not in html.lower()
    # no inline handlers: the page's Content-Security-Policy blocks them (ORCH-67, the column picker)
    assert not re.search(r"\son[a-z]+=", html), "inline event handler in gallery.html"
    for sect in (
        "kit",
        "foundations",
        "controls",
        "results",
        "result-widgets",
        "states",
        "overlays",
        "motion",
    ):
        assert f'id="{sect}"' in html, sect
    # loading, empty and error each have an example
    for word in ("Loaded", "Loading", "Empty", "Error"):
        assert word in html
    js = (STATIC / "gallery.js").read_text(encoding="utf-8")
    for builder in ("statusIcon", "state(", "stat(", "progress(", "table(", "sheet("):
        assert builder in js, builder


def test_gallery_widget_targets_exist():
    html = (STATIC / "gallery.html").read_text(encoding="utf-8")
    js = (STATIC / "gallery.js").read_text(encoding="utf-8")
    targets = set(re.findall(r"q\(['\"]#(w-[a-z0-9-]+)['\"]\)", js))
    ids = set(re.findall(r'id="([^"]+)"', html))
    assert targets, "no gallery widget targets found"
    assert not targets - ids, f"gallery widget containers missing: {sorted(targets - ids)}"


def test_design_doc_names_how_to_add_a_component():
    doc = (STATIC / "DESIGN.md").read_text(encoding="utf-8")
    assert "How to add a component" in doc and "gallery" in doc and "SX-1" in doc


def test_one_chevron_no_text_glyph():
    for name in ("select.js", "components.css", "widgets.js"):
        assert "⌄" not in (STATIC / name).read_text(encoding="utf-8") and "⌄" not in (
            STATIC / name
        ).read_text(encoding="utf-8"), name


def test_an_unsized_icon_sizes_itself():
    css = (STATIC / "components.css").read_text(encoding="utf-8")
    assert ":where(svg.ic,svg.ico,.ico>svg){width:20px;height:20px}" in css


def test_shared_date_picker_offers_today_and_tomorrow():
    js = (STATIC / "date.js").read_text(encoding="utf-8")
    assert "data-today" in js and "data-tomorrow" in js and "data-clear" in js
    assert ".ui-quick" in (STATIC / "interaction.css").read_text(encoding="utf-8")


def test_phone_tabs_always_mark_where_you_are():
    # ORCH-1698: a page that is none of Home, Tickets and Review marks More (data-current);
    # the gallery shows that state
    js = (STATIC / "gallery.js").read_text(encoding="utf-8")
    sample = js.split("const wt=q('#w-tabbar')", 1)[1].split("\n", 1)[0]
    assert "current:cur==='More'" in sample and "T('More'" in sample, (
        "the gallery has no tab bar with More current"
    )
    mockups = ADDONS / "dashboard" / "mockup"
    for page in sorted(mockups.rglob("*.html")):
        for nav in re.findall(r'<nav class="tabbar[^"]*".*?</nav>', page.read_text(encoding="utf-8"), re.S):
            marked = re.findall(r'<(?:a|button)\b[^>]*\b(?:aria-current|data-current)="page"', nav)
            assert len(marked) == 1, (
                f"{page.relative_to(mockups)}: the phone tabs mark {len(marked)} tabs, not 1"
            )
    home = (mockups / "home" / "home.html").read_text(encoding="utf-8")
    assert re.search(r'class="btn outline sm phone-only"[^>]*>New ticket<', home), (
        "phone Home mockup has no New ticket"
    )

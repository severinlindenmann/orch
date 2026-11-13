import json
import tomllib
from importlib import resources
from pathlib import Path

import jsonschema

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def test_manifest_is_valid():
    m = tomllib.loads((resources.files("orch_focus") / "orch-addon.toml").read_text())
    jsonschema.validate(m, json.loads((CONTRACTS / "addon-manifest.schema.json").read_text()))
    assert m["name"] == "focus" and m["background"] is True


def test_feed_shows_names_not_actor_ids():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src" / "orch_focus" / "web" / "store.js").read_text()
    assert r"/\b(?:agent|human):([A-Za-z0-9_.@-]+)/g" in js


def test_feed_tool_lines_use_plain_names_too():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src" / "orch_focus" / "web" / "live.js").read_text()
    assert "text: plainNames(e.text)" in js and "return plainNames(text);" in js


def test_web_scripts_are_served_and_loaded_in_order():
    import re

    from orch_focus import server

    web = Path(__file__).resolve().parents[1] / "src" / "orch_focus" / "web"
    assert {p.name for p in web.glob("*.js")} <= set(server.WEB_FILES)
    html = (web / "index.html").read_text()
    scripts = re.findall(r'<script src="([^"]+)" defer></script>', html)
    names = [
        "helpers",
        "proof",
        "store",
        "jobs",
        "live-now",
        "areas",
        "used",
        "session",
        "settings",
        "live",
        "ticket",
        "compose",
        "focus",
    ]
    assert scripts[-len(names) :] == [f"__P__/web/{name}.js" for name in names]


def test_every_name_helpers_js_exports_is_defined():
    """A name in the export list that is not defined throws at load and takes the whole page down (#525 lost holdText)."""
    import re

    web = Path(__file__).resolve().parents[1] / "src" / "orch_focus" / "web"
    text = (web / "helpers.js").read_text()
    exported = re.search(r"root\.FocusHelpers = \{([^}]*)\}", text).group(1).replace(" ", "").split(",")
    missing = [n for n in exported if not re.search(rf"(?:function|const|let|var)\s+{n}\b", text)]
    assert not missing, missing

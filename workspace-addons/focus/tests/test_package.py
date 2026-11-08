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

    js = (Path(__file__).resolve().parents[1] / "src" / "orch_focus" / "web" / "focus.js").read_text()
    assert r"/\b(?:agent|human):([A-Za-z0-9_.@-]+)/g" in js

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

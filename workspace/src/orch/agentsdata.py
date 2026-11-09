"""Built-in adapter data, merged in a fixed lane order."""

import json
from pathlib import Path

FRAGMENTS = ("deny", "capabilities", "connections", "readonly")


def agents_dir() -> Path:
    return Path(__file__).with_name("agents")


def _merge(base: dict, fragment: dict) -> None:
    for key, value in fragment.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def load(directory: Path | None = None) -> dict:
    directory = agents_dir() if directory is None else directory
    doc = json.loads((directory / "base.json").read_bytes())
    names = set(doc["adapters"])
    for name in FRAGMENTS:
        fragment = json.loads((directory / f"{name}.json").read_bytes())
        if not isinstance(fragment, dict):
            raise RuntimeError(f"agents/{name}.json must be an object")
        adapters = fragment.get("adapters", {})
        if not isinstance(adapters, dict) or set(adapters) - names:
            raise RuntimeError(f"agents/{name}.json must only extend existing adapters")
        _merge(doc, fragment)
    return doc

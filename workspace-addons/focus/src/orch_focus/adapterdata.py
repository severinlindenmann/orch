"""What an agent's adapter says about itself, read as DATA from core's agents/ (core code is never imported).

A user-named agent in .orch/config.toml ([agents.<name>] adapter = "<base>") uses its base adapter's data.
"""

from __future__ import annotations

import json
import re
import tomllib
from importlib.util import find_spec
from pathlib import Path

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")


def _merge(base: dict, fragment: dict) -> None:
    for key, value in fragment.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def _registry() -> dict:
    spec = find_spec("orch")
    for base in (spec.submodule_search_locations or []) if spec else []:
        try:
            directory = Path(base) / "agents"
            doc = json.loads((directory / "base.json").read_bytes())
            names = set(doc["adapters"])
            for name in ("deny", "capabilities", "connections", "readonly"):
                fragment = json.loads((directory / f"{name}.json").read_bytes())
                if not isinstance(fragment, dict):
                    raise RuntimeError(f"agents/{name}.json must be an object")  # noqa: TRY004
                adapters = fragment.get("adapters", {})
                if not isinstance(adapters, dict) or set(adapters) - names:
                    raise RuntimeError(f"agents/{name}.json must only extend existing adapters")
                _merge(doc, fragment)
            return doc.get("adapters", {})
        except (OSError, ValueError):
            continue
    return {}


def base_name(root: Path, agent: str) -> str:
    if not isinstance(agent, str) or not NAME.fullmatch(agent):
        return ""
    try:
        cfg = tomllib.loads((root / ".orch" / "config.toml").read_text(encoding="utf-8"))
        entry = (cfg.get("agents") or {}).get(agent)
        if isinstance(entry, dict) and isinstance(entry.get("adapter"), str):
            return entry["adapter"]
    except (OSError, ValueError):
        pass
    return agent


def adapter(root: Path, agent: str) -> dict:
    a = _registry().get(base_name(root, agent))
    return a if isinstance(a, dict) else {}


def events_kind(root: Path, agent: str, mode: str) -> str | None:
    """The mapper the adapter names: live -> live.events, oneshot -> `<adapter>-stream-json/1` when it can stream."""
    a = adapter(root, agent)
    if mode == "live":
        return (a.get("live") or {}).get("events")
    if (a.get("oneshot") or {}).get("stream_args"):
        return f"{base_name(root, agent)}-stream-json/1"
    return None


def permission_retry(root: Path, agent: str) -> bool:
    return bool((adapter(root, agent).get("capabilities") or {}).get("permission_retry"))

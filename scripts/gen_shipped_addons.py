#!/usr/bin/env python3
"""Generate workspace/src/orch/shipped_addons.json: the parsed manifest of every shipped add-on
(addons.SHIPPED_ADDONS), read from workspace-addons/<name>/src/<pkg>/orch-addon.toml with the same parser orch
uses. It lets `orch addon list` show what orch ships on a normal install (no source folder, no network).
Run it after any change to a shipped add-on's manifest:  python3 scripts/gen_shipped_addons.py
`--check` only compares and exits 1 when the committed file is out of date."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workspace" / "src"))
OUT = ROOT / "workspace" / "src" / "orch" / "shipped_addons.json"


def build() -> dict:
    from orch import addons, fields

    out = {}
    for name in addons.SHIPPED_ADDONS:
        m = addons.folder_manifest(ROOT / "workspace-addons" / name)
        m = dict(m)
        m.pop("dir")
        # the ticket fields need the add-on's schema file, which a normal install does not have: keep the result
        m["ticket_fields_section"] = fields.section({**m, "dir": ROOT / "workspace-addons" / name})
        out[name] = m
    return out


def render() -> str:
    return json.dumps(build(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if OUT.read_text(encoding="utf-8") == text else 1)
    OUT.write_text(text, encoding="utf-8")
    print("ok", OUT.relative_to(ROOT))

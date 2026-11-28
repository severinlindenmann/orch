"""P-006 (owner, 28 Nov, option A): the relay and publish portals take the master's sizes, and keep one accent each.

The sizes are a switch (<html data-size="master">) both portal sheets carry in the same words; its values are the
master's tokens (brand/tokens.json), never numbers of their own. The portal pages turn it on in their own change.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHEETS = [ROOT / "relay" / "web" / "style.css", ROOT / "publish" / "web" / "admin.css"]
START = "/* P-006 (owner, 28 Nov, option A): master sizes."


def block(path: Path) -> str:
    css = path.read_text(encoding="utf-8")
    assert START in css, f"{path.name} has no P-006 block"
    return css[css.index(START) :]


def test_both_portals_carry_the_same_master_size_switch():
    relay, publish = (block(p) for p in SHEETS)
    assert relay == publish


def test_the_switch_reads_the_master_tokens_only():
    rules = block(SHEETS[0]).split("*/", 1)[1]
    assert not re.search(r"\d+px", rules.replace("line-height:36px", "").replace("min-width:721px", "")), rules
    for token in ("--fs-3", "--fs-title", "--topbar-height", "--control-height"):
        assert f"var({token})" in rules
    tokens = json.loads((ROOT / "brand" / "tokens.json").read_text(encoding="utf-8"))
    flat = json.dumps(tokens)
    for name, value in (("fs-body", 14), ("fs-title", 28), ("topbar-height", 56), ("control-height", 36)):
        assert f'"{name}": {value}' in flat, name


def test_the_switch_leaves_phone_touch_sizes_alone():
    rules = block(SHEETS[0]).split("*/", 1)[1]
    wide = rules[rules.index("@media(min-width:721px){") :]
    assert ".topbar{min-height" in wide and ".btn.primary" in wide
    assert ".btn.primary" not in rules[: rules.index("@media(min-width:721px){")]

"""UX checklist H1/H2 (WCAG 2.2 AA) on the colour tokens, no browser needed: every text colour is readable on every
surface it is used on (4.5:1), and borders of controls and the focus colour stand out from every surface (3:1).
The page-level checks (contrast on the real gallery, focus, target size, reduced motion, 390 px) are in
workspace/src/orch_ui/tests/ux_checks.cjs."""

import json
from pathlib import Path

import pytest

_RAW = json.loads((Path(__file__).resolve().parents[1] / "tokens.json").read_text())
TOKENS = {**_RAW["color"], **_RAW["code"]}

SURFACES = ["bg", "sidebar", "surface", "surface-2", "surface-3"]
TEXT = ["text", "text-muted", "text-faint", "brand", "info", "warning", "success", "danger", "chart-4"]
STATUS = ["info", "warning", "success", "danger", "brand"]
UI_PARTS = ["border-strong", "brand"]  # control borders (--input) and the focus ring


def hex_of(name: str) -> str:
    value = TOKENS[name]
    while value.startswith("var(--"):  # e.g. "input": "var(--border-strong)"
        value = TOKENS[value[6:-1]]
    assert value.startswith("#") and len(value) == 7, f"{name} is not a plain colour: {value}"
    return value


def luminance(hex_colour: str) -> float:
    def channel(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def ratio(a: str, b: str) -> float:
    hi, lo = sorted((luminance(hex_of(a)), luminance(hex_of(b))), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_ratio_matches_wcag_reference_values():
    TOKENS["_white"], TOKENS["_black"], TOKENS["_grey"] = "#ffffff", "#000000", "#767676"
    try:
        assert round(ratio("_white", "_black"), 1) == 21.0
        assert round(ratio("_grey", "_white"), 2) == 4.54  # the classic lightest AA grey on white
    finally:
        for k in ("_white", "_black", "_grey"):
            TOKENS.pop(k)


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("fg", TEXT)
def test_text_on_surfaces(fg, surface):
    assert ratio(fg, surface) >= 4.5, f"--{fg} on --{surface}: {ratio(fg, surface):.2f}:1, needs 4.5:1"


@pytest.mark.parametrize("name", STATUS)
def test_status_text_on_its_soft_background(name):
    for fg in (name, "text", "text-muted"):
        r = ratio(fg, f"{name}-soft")
        assert r >= 4.5, f"--{fg} on --{name}-soft: {r:.2f}:1, needs 4.5:1"


def test_text_on_filled_buttons():
    for bg in ("brand", "brand-strong"):
        r = ratio("on-brand", bg)
        assert r >= 4.5, f"--on-brand on --{bg}: {r:.2f}:1, needs 4.5:1"


SOFT = ["brand-soft", "info-soft", "warning-soft", "success-soft", "danger-soft"]
CODE = list(_RAW["code"])  # syntax colours in .code-block (surface-2) and folded code (sidebar)
# Named pairs the master uses together (alias tokens resolve through hex_of).
PAIRS = [
    ("brand-strong", "brand-soft"),  # selected chip
    ("disabled-text", "disabled-bg"),
    ("addon-text", "addon-soft"),
    ("on-addon", "addon"),
    ("brand-chip-text", "brand-soft"),
    ("text", "nav-selected"),
    ("text", "add-bg"),
    ("text", "del-bg"),
    ("ink", "paper"),
] + [(s, "surface") for s in ("working", "needs-you", "review", "done", "paused", "failed")]


@pytest.mark.parametrize("bg", SOFT)
@pytest.mark.parametrize("fg", ["text", "text-muted", "text-faint"])
def test_neutral_text_on_every_soft_background(fg, bg):
    assert ratio(fg, bg) >= 4.5, f"--{fg} on --{bg}: {ratio(fg, bg):.2f}:1, needs 4.5:1"


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("fg", CODE + ["brand-strong"])
def test_code_and_strong_text_on_surfaces(fg, surface):
    assert ratio(fg, surface) >= 4.5, f"--{fg} on --{surface}: {ratio(fg, surface):.2f}:1, needs 4.5:1"


@pytest.mark.parametrize("fg,bg", PAIRS)
def test_named_pairs(fg, bg):
    assert ratio(fg, bg) >= 4.5, f"--{fg} on --{bg}: {ratio(fg, bg):.2f}:1, needs 4.5:1"


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("part", UI_PARTS)
def test_control_borders_and_focus_stand_out(part, surface):
    assert ratio(part, surface) >= 3, f"--{part} on --{surface}: {ratio(part, surface):.2f}:1, needs 3:1"

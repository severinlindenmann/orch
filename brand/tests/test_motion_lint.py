"""UX checklist J1/H10 static lint on the master library: interaction.css holds the global reduced-motion rule, and no one-shot animation or transition in the master runs longer than the slowest token.
The runtime check (nothing still moves with reduced motion) is in workspace/src/orch_ui/tests/ux_checks.cjs."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "workspace/src/orch_ui/static"
MAX_MS = 240
DURATION = re.compile(r"(?<![\w.-])(\d*\.?\d+)(ms|s)\b")


def ms_of(value: str, unit: str) -> float:
    return float(value) * (1000 if unit == "s" else 1)


def test_global_reduced_motion_rule_exists():
    css = (STATIC / "interaction.css").read_text()
    rule = re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{\s*\*,\s*\*::before,\s*\*::after\s*\{([^}]*)\}", css)
    assert rule, "interaction.css needs the global prefers-reduced-motion rule"
    for part in ("animation-duration:0s!important", "transition-duration:0s!important"):
        assert part in rule.group(1).replace(" ", "")


def test_one_shot_durations_stay_within_slowest_token():
    too_slow = []
    for css in sorted(STATIC.glob("*.css")):
        if css.name == "tokens.css":
            continue
        for n, line in enumerate(css.read_text().splitlines(), 1):
            if not re.search(r"animation|transition", line) or "infinite" in line:
                continue
            for m in DURATION.finditer(line):
                if ms_of(*m.groups()) > MAX_MS:
                    too_slow.append(f"{css.name}:{n} {m.group(0)}")
    assert too_slow == [], f"use a --dur-* token (at most {MAX_MS} ms): {too_slow}"


def test_tokens_css_has_the_duration_tokens():
    tokens = (STATIC / "tokens.css").read_text()
    for name in ("--dur-fast", "--dur-base", "--dur-settle", "--dur-slow", "--dur-exit"):
        assert name in tokens

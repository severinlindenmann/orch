import json
from pathlib import Path

import pytest

from orch.text import clean_untrusted

VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/vectors/clean-untrusted-v1.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", VECTORS["cases"], ids=[c["name"] for c in VECTORS["cases"]])
def test_vectors(case):
    assert clean_untrusted(case["in"]) == case["out"]


def test_limit_and_plain_text_untouched():
    assert clean_untrusted("a" * 50, 10) == "a" * 10
    assert clean_untrusted("Grüße, 日本語 <b>x</b> & 100%") == "Grüße, 日本語 <b>x</b> & 100%"
    assert clean_untrusted("é") == "é"  # NFC


def test_at_word_cuts_at_a_whole_word_with_an_ellipsis():
    from orch.text import at_word

    assert at_word("short text", 80) == "short text"
    long = "Usage stage 1: test with owner's rules, screenshots, one-day side by side with the old page"
    out = at_word(long, 80)
    assert out.endswith("…") and len(out) <= 80
    assert out[:-1] in long and long[len(out) - 1] == " "  # a whole word was kept, none was split
    assert at_word("x" * 50, 10) == "x" * 9 + "…"  # one long word: cut inside it, still shown as cut

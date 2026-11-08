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

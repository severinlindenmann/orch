"""R6.2 style lint: the repo is clean against the allowlist, and planted violations are caught."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_style as cs  # noqa: E402


def test_repo_matches_allowlist():
    import json

    assert cs.violations(cs.scan(), json.loads(cs.ALLOWLIST.read_text())) == []


def test_count_hex_and_style():
    assert cs.count("a{color:#fff;background:#12ab34}") == {"hex": 2, "style": 0}
    assert cs.count("<style>x</style><STYLE>") == {"hex": 0, "style": 2}


def test_false_positives_not_counted():
    assert cs.count('href="#main" &#123; url(a#b) #abcde x#fff') == {"hex": 0, "style": 0}


def test_more_hex_fails_fewer_passes():
    allowed = {"a.html": {"hex": 2, "style": 0}}
    assert cs.violations({"a.html": {"hex": 3, "style": 0}}, allowed)
    assert not cs.violations({"a.html": {"hex": 2, "style": 0}}, allowed)
    assert not cs.violations({"a.html": {"hex": 1, "style": 0}}, allowed)


def test_new_file_and_new_css_fail():
    assert cs.violations({"new.js": {"hex": 1, "style": 0}}, {})
    assert cs.violations({"new.css": {"hex": 0, "style": 0}}, {})


def test_master_is_exempt():
    assert not any(f.startswith(cs.EXEMPT_PREFIX) for f in cs.scan())

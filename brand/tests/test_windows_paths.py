"""Every path checks out on Windows without core.longpaths (ORCH-872): planted samples and the real repo."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import check_windows_paths as cwp  # noqa: E402


@pytest.mark.parametrize("path, words", [
    ("assets/" + "x" * 130 + ".txt", "characters"),
    ("docs/con", "reserved"),
    ("docs/AUX.txt", "reserved"),
    ("lpt1/readme.md", "reserved"),
    ("docs/notes.", "dot or a space"),
    ("docs/trailing /a.md", "dot or a space"),
    ("docs/what?.md", "character"),
    ("docs/a:b.md", "character"),
    ("docs/tab\there.md", "character"),
])
def test_bad_path_is_caught(path, words):
    found = cwp.problems([path])
    assert len(found) == 1 and found[0].startswith(path + ":") and words in found[0]


def test_case_clash_is_caught_once():
    found = cwp.problems(["Docs/a.md", "docs/b.md", "docs/c.md", "docs/README.md", "docs/readme.md"])
    assert len(found) == 2
    assert any("'docs' and 'Docs'" in p for p in found)
    assert any("'docs/readme.md' and 'docs/README.md'" in p for p in found)


@pytest.mark.parametrize("path", [
    "assets/" + "x" * (cwp.MAX_LEN - len("assets/")),
    "docs/console.md",       # only the bare device name is reserved
    "docs/comfy.txt",
    "docs/.gitkeep",
    "docs/v1.2/notes.md",
])
def test_fine_path_passes(path):
    assert cwp.problems([path]) == []


def test_repository_checks_out_on_windows():
    assert cwp.main(["--repo", str(ROOT)]) == 0

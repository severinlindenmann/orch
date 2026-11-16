"""The human-proof module is gone: nothing imports a module named humanproof, and its file does not exist."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _sources():
    yield from (ROOT / "workspace" / "src").rglob("*.py")
    yield from ROOT.glob("workspace-addons/*/src/**/*.py")


def _imported_names(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield from a.name.split(".")
        elif isinstance(node, ast.ImportFrom):
            yield from (node.module or "").split(".")
            for a in node.names:
                yield a.name


def test_no_module_named_humanproof_is_imported():
    bad = []
    for p in _sources():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        if "humanproof" in set(_imported_names(tree)):
            bad.append(str(p.relative_to(ROOT)))
    assert not bad, bad


def test_the_module_file_does_not_exist():
    assert not (ROOT / "workspace" / "src" / "orch" / "humanproof.py").exists()

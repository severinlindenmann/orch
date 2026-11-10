"""Lint: guarded-file modules read only through orch.saferead (no raw open(, read_text(, read_bytes().

A line may opt out with `# lint-allow: <reason>` (the reason is mandatory). os.open / os.fdopen are not reads
of a path by name: they are how locks and private writes are created with exact flags and rights."""

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "orch"
MODULES = (
    "humanproof.py",
    "keystore.py",
    "pageproof.py",
    "winacl.py",
)  # absent ones are checked once they exist
FORBIDDEN_ATTRS = {"read_text", "read_bytes", "open"}
ALLOW = re.compile(r"#\s*lint-allow:\s*\S")


def violations(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        bad = (isinstance(f, ast.Name) and f.id == "open") or (
            isinstance(f, ast.Attribute)
            and f.attr in FORBIDDEN_ATTRS
            and not (f.attr == "open" and isinstance(f.value, ast.Name) and f.value.id == "os")
        )
        if bad and not ALLOW.search(lines[node.lineno - 1]):
            out.append(f"{path.name}:{node.lineno}: {lines[node.lineno - 1].strip()}")
    return out


def test_guarded_modules_read_only_through_saferead():
    found = []
    for name in MODULES:
        if (SRC / name).exists():
            found += violations(SRC / name)
    assert not found, "raw reads in guarded modules (use saferead.read_private):\n" + "\n".join(found)


def test_lint_catches_raw_reads(tmp_path):
    f = tmp_path / "x.py"
    f.write_text(
        "import os\nfrom pathlib import Path\n"
        "a = open('x')\nb = Path('x').read_text()\nc = Path('x').read_bytes()\nd = Path('x').open()\n"
        "e = os.open('x', 0)\n"
        "g = open('x')  # lint-allow: a test fixture\n"
    )
    assert [v.split(":")[1] for v in violations(f)] == ["3", "4", "5", "6"]

"""orch core never imports orch_ui (the kit is a sibling module): `orch.cli` must work without it."""

import re
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
IMPORT = re.compile(r"^\s*(from\s+orch_ui\b|import\s+orch_ui\b)", re.M)


def test_core_source_never_names_orch_ui():
    bad = [str(p) for p in (SRC / "orch").rglob("*.py") if IMPORT.search(p.read_text(encoding="utf-8"))]
    assert not bad, f"orch core imports orch_ui: {bad}"


def test_orch_cli_imports_without_orch_ui():
    code = (
        "import sys\n"
        "class Hide:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'orch_ui' or name.startswith('orch_ui.'):\n"
        "            raise ImportError('orch_ui is hidden')\n"
        "sys.meta_path.insert(0, Hide())\n"
        "sys.modules.pop('orch_ui', None)\n"
        "import orch.cli\n"
        "assert not any(m.startswith('orch_ui') for m in sys.modules)\n"
        "print('ok')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=SRC)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr

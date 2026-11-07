"""Every spawn of `python -m ...` must pass -P (no current-folder imports): a planted orch.py in a workspace
must never run as the user."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def test_no_sys_executable_dash_m_without_dash_P():
    bad = []
    for f in SRC.rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"sys\.executable,\s*[\"']-m[\"']", line):
                bad.append(f"{f.relative_to(SRC)}:{n}")
    assert not bad, f"python -m without -P (use procs.orch_python_argv or add -P): {bad}"

"""Every spawn of Python with -m must pass -P to prevent current-folder imports."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def missing_dash_P(source):
    tree = ast.parse(source)

    def executable(node):
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "sys"
            and node.attr == "executable"
        )

    aliases = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and executable(node.value)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        strings = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        if (
            "-m" in strings
            and "-P" not in strings
            and any(executable(e) or isinstance(e, ast.Name) and e.id in aliases for e in node.elts)
        ):
            bad.append(node.lineno)
    return bad


@pytest.mark.parametrize(
    "source,bad",
    [
        ('argv = [\n    sys.executable,\n    "-m",\n    "orch",\n]', [1]),
        ('argv = (python, "-m", "orch")\npython = sys.executable', [1]),
        ('python = sys.executable\nargv = [python, "-P", "-m", "orch"]', []),
        ('argv = (sys.executable, "-m", "orch", "-P")', []),
        ('argv = ["other", "-m"]', []),
    ],
)
def test_checker(source, bad):
    assert missing_dash_P(source) == bad


def test_no_sys_executable_dash_m_without_dash_P():
    bad = []
    for src in [ROOT / "workspace/src", *sorted((ROOT / "workspace-addons").glob("*/src"))]:
        for f in sorted(src.rglob("*.py")):
            bad.extend(
                f"{f.relative_to(ROOT)}:{line}" for line in missing_dash_P(f.read_text(encoding="utf-8"))
            )
    assert not bad, f"python -m without -P (use procs.orch_python_argv or add -P): {bad}"

"""Every spawn of Python with -m must pass -P to prevent current-folder imports; a spawn of orch itself
(-m orch...) also -I (no PYTHON* variables, no user site)."""

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

    aliases = {"executable"}  # from sys import executable
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Assign, ast.AnnAssign))
            and node.value is not None
            and executable(node.value)
        ):
            for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(t, ast.Name):
                    aliases.add(t.id)
    # lists passed to runfiles.runs_args only MATCH a running command line; they spawn nothing
    matchers = {
        id(a)
        for c in ast.walk(tree)
        if isinstance(c, ast.Call) and getattr(c.func, "attr", getattr(c.func, "id", "")) == "runs_args"
        for a in c.args
    }
    bad = []
    for node in ast.walk(tree):
        if id(node) in matchers:
            continue
        if not isinstance(node, (ast.List, ast.Tuple)):
            continue
        strs = [
            e.value if isinstance(e, ast.Constant) and isinstance(e.value, str) else None for e in node.elts
        ]
        if "-m" not in strs:
            continue
        m = strs.index("-m")
        nxt = strs[m + 1] if m + 1 < len(strs) else None
        if "-P" in strs[:m]:
            if isinstance(nxt, str) and (nxt == "orch" or nxt.startswith("orch.")) and "-I" not in strs[:m]:
                bad.append(node.lineno)  # orch's own spawn: -I as well
            continue
        first = strs[0]
        if (
            first is None
            or first == "-m"
            or any(executable(e) or isinstance(e, ast.Name) and e.id in aliases for e in node.elts)
        ):
            bad.append(node.lineno)
    return bad


@pytest.mark.parametrize(
    "source,bad",
    [
        ('argv = [\n    sys.executable,\n    "-m",\n    "orch",\n]', [1]),
        ('argv = (python, "-m", "orch")\npython = sys.executable', [1]),
        ('python = sys.executable\nargv = [python, "-I", "-P", "-m", "orch"]', []),
        ('python = sys.executable\nargv = [python, "-P", "-m", "orch"]', [2]),
        ('argv = [sys.executable, "-P", "-m", "orch.pageproof"]', [1]),
        ('argv = [sys.executable, "-P", "-m", "some_addon"]', []),
        ('argv = (sys.executable, "-m", "orch", "-P")', [1]),
        ('argv = [sys.executable] + ["-m", "orch"]', [1]),
        ('cmd += ["-m", "orch"]', [1]),
        ('argv = [*base, "-m", "orch"]', [1]),
        ('from sys import executable\nargv = [executable, "-m", "orch"]', [2]),
        ('exe: str = sys.executable\nargv = [exe, "-m", "orch"]', [2]),
        ('self.py = sys.executable\nargv = [self.py, "-m", "orch"]', [2]),
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
    assert not bad, f"python -m without -P, or -m orch without -I (use procs.orch_python_argv): {bad}"

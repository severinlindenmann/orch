"""Lint: every os.killpg in shipped code is guarded for Windows, which has no os.killpg (and no SIGKILL).

An unguarded call raises AttributeError there. ORCH-1796 (report r-1123-1055): the dashboard's view puller
did, and every add-on tab on Windows showed an error. Guarded = an `if` (or a conditional expression) in
an enclosing function (or at module level) tests the platform (`os.name`, `sys.platform`, a module flag
`_WINDOWS`) and either holds the call or comes before it (an early return); or the call or its `def` line says
`# posix-only: <reason>` (the reason is mandatory), e.g. a helper only ever called on POSIX. A mention in a
comment or a log line is no guard."""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOTS = [REPO / "workspace" / "src", *sorted((REPO / "workspace-addons").glob("*/src"))]
GUARD = re.compile(r"\bos\.name\b|\bsys\.platform\b|\b_WINDOWS\b")
ALLOW = re.compile(r"#\s*posix-only:\s*\S")


def _killpg_lines(tree: ast.AST) -> list[int]:
    return sorted(
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and n.attr == "killpg"
        and isinstance(n.value, ast.Name)
        and n.value.id == "os"
    )


def _platform_ifs(scope: ast.AST) -> list[ast.AST]:
    return [
        n for n in ast.walk(scope) if isinstance(n, (ast.If, ast.IfExp)) and GUARD.search(ast.unparse(n.test))
    ]


def violations(path: Path, base: Path = REPO) -> list[str]:
    src = path.read_text(encoding="utf-8")
    if "killpg" not in src:
        return []
    lines = src.splitlines()
    tree = ast.parse(src)
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    out = []
    for line in _killpg_lines(tree):
        if ALLOW.search(lines[line - 1]):
            continue
        inner = [f for f in funcs if f.lineno <= line <= (f.end_lineno or f.lineno)]
        if any(ALLOW.search(lines[f.lineno - 1]) for f in inner):
            continue
        # an outer function may hold the guard (a nested kill() in a method that checks the platform)
        if any(g.lineno <= line for scope in (inner or [tree]) for g in _platform_ifs(scope)):
            continue
        out.append(f"{path.relative_to(base)}:{line}: {lines[line - 1].strip()}")
    return out


def test_every_killpg_in_shipped_code_is_guarded_for_windows():
    files = [p for root in ROOTS for p in sorted(root.rglob("*.py"))]
    assert len(files) > 50  # the roots were found
    bad = [v for p in files for v in violations(p)]
    assert not bad, "os.killpg without a Windows guard (see this file's docstring):\n" + "\n".join(bad)


def test_the_lint_catches_an_unguarded_call(tmp_path):
    p = tmp_path / "probe.py"
    p.write_text(
        "import os, signal\n"
        "def kill(p):\n"
        "    os.killpg(p.pid, signal.SIGKILL)\n"
        "def safe(p):\n"
        "    if os.name != 'nt':\n"
        "        os.killpg(p.pid, signal.SIGKILL)\n"
        "def marked(p):  # posix-only: only called on POSIX\n"
        "    os.killpg(p.pid, signal.SIGKILL)\n"
        "def mention(p):  # _WINDOWS is only named here\n"
        "    os.killpg(p.pid, signal.SIGKILL)\n"
        "if os.name == 'posix':\n"
        "    os.killpg(1, 0)\n"
    )
    assert _killpg_lines(ast.parse(p.read_text())) == [3, 6, 8, 10, 12]
    assert violations(p, tmp_path) == [
        "probe.py:3: os.killpg(p.pid, signal.SIGKILL)",
        "probe.py:10: os.killpg(p.pid, signal.SIGKILL)",
    ]

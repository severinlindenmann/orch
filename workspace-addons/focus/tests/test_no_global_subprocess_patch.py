"""No test may patch subprocess.run for the whole process.

`monkeypatch.setattr(subprocess, "run", ...)` (or `module.subprocess`) replaces the GLOBAL function, so a thread or
server left running by another test lands in the mock and shows up in this test's recorded calls (flaky
`test_posix_never_calls_icacls`, develop CI run 42730159856). Patch the module-local `_run` instead, e.g.
`monkeypatch.setattr(runfiles, "_run", fake)`."""

import ast
from pathlib import Path

TESTS = Path(__file__).parent


def _is_subprocess(node: ast.AST) -> bool:
    return (isinstance(node, ast.Name) and node.id == "subprocess") or (
        isinstance(node, ast.Attribute) and node.attr == "subprocess"
    )


def _offences(tree: ast.AST) -> list[int]:
    found = []
    for n in ast.walk(tree):
        if not (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("setattr", "setitem")
        ):
            continue
        a = n.args
        if len(a) >= 2 and _is_subprocess(a[0]) and isinstance(a[1], ast.Constant) and a[1].value == "run":
            found.append(n.lineno)
        if a and isinstance(a[0], ast.Constant) and a[0].value in ("subprocess.run", "subprocess.Popen"):
            found.append(n.lineno)  # monkeypatch.setattr("subprocess.run", ...)
    return found


def test_no_test_patches_subprocess_run_globally():
    bad = []
    for p in sorted(TESTS.glob("*.py")):
        bad += [f"{p.name}:{ln}" for ln in _offences(ast.parse(p.read_text(), str(p)))]
    assert not bad, "patch the module-local _run, not the global subprocess.run: " + ", ".join(bad)


def test_the_scan_catches_the_patterns():
    for src in (
        'monkeypatch.setattr(subprocess, "run", f)',
        'monkeypatch.setattr(runfiles.subprocess, "run", f)',
        'monkeypatch.setattr("subprocess.run", f)',
    ):
        assert _offences(ast.parse(src)) == [1], src
    assert _offences(ast.parse('monkeypatch.setattr(runfiles, "_run", f)')) == []

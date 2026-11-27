"""Add-ons start programs with an argument list, never through a shell (R1.6): a ticket title, a file name or
a folder with spaces, quotes or umlauts reaches the program as one word on Windows, macOS and Linux, and a
value can never become a second command. This lint keeps it that way. The allowlist names the places that may
hand a command line to the shell, each with its reason; a new entry needs the same."""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADDONS = REPO / "workspace-addons"
STARTERS = {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}

# (file, innermost function) -> why it may use a shell
ALLOW = {
    ("workspace-addons/pull-requests/src/orch_pull_requests/precheck.py", "_shell"): (
        "runs the person's own precheck command line from their settings as written "
        "(it may use && or a pipe); orch puts no value into it"
    ),
}


def _sources():
    for p in sorted(ADDONS.glob("*/src/**/*.py")):
        yield p.relative_to(REPO).as_posix(), ast.parse(p.read_text(encoding="utf-8"), filename=str(p))


def _findings(rel: str, tree: ast.AST):
    def walk(node, fn):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else fn
            if isinstance(child, ast.Call):
                yield from check(child, fn)
            yield from walk(child, name)

    def check(call: ast.Call, fn):
        f = call.func
        attr = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ""
        where = f"{rel}:{call.lineno} ({fn})"
        if owner == "os" and attr in {"system", "popen"}:
            yield f"{where}: os.{attr} runs a shell; use subprocess with an argument list"
        shell_only = owner == "subprocess" and attr in {"getoutput", "getstatusoutput"}
        if attr == "create_subprocess_shell" or shell_only:
            yield f"{where}: {attr} runs a shell; use an argument list"
        for kw in call.keywords:
            if kw.arg == "shell" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                if (rel, fn) not in ALLOW:
                    yield f"{where}: shell=True; pass an argument list instead"
        if owner == "subprocess" and attr in STARTERS and call.args:
            first = call.args[0]
            if isinstance(first, ast.JoinedStr | ast.BinOp) or (
                isinstance(first, ast.Constant) and isinstance(first.value, str)
            ):
                if (rel, fn) not in ALLOW:
                    yield f"{where}: a command built as one string; pass an argument list instead"

    yield from walk(tree, "<module>")


def test_addons_start_programs_with_an_argument_list_never_a_shell():
    found = [f for rel, tree in _sources() for f in _findings(rel, tree)]
    assert not found, "\n".join(found)


def test_every_allowed_shell_still_exists():
    """A stale entry would let a new shell in under an old name."""
    seen = set()
    for rel, tree in _sources():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and (rel, node.name) in ALLOW:
                calls = [c for c in ast.walk(node) if isinstance(c, ast.Call)]
                if any(kw.arg == "shell" for c in calls for kw in c.keywords):
                    seen.add((rel, node.name))
    assert seen == set(ALLOW)


def test_the_lint_catches_a_shell_and_a_string_command():
    bad = ast.parse(
        "import os, subprocess\n"
        "def f(name):\n"
        "    os.system('open ' + name)\n"
        "    subprocess.run(f'git add {name}', shell=True)\n"
        "    subprocess.Popen('ls -l')\n"
    )
    got = list(_findings("workspace-addons/x/src/x.py", bad))
    assert len(got) == 4 and all("(f)" in g for g in got)
    good = ast.parse("import subprocess\ndef f(n):\n    subprocess.run(['git', 'add', n], shell=False)\n")
    assert not list(_findings("workspace-addons/x/src/x.py", good))

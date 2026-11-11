"""`orch start` in a real terminal opens the page with a launch token (it crashed: a local import
shadowed the module-level `humanproof`, UnboundLocalError), and no function re-imports a name its module
already imports."""

import argparse
import ast
from pathlib import Path

from orch import cli_status, humanproof, services, term, worktrees


def test_start_in_a_terminal_opens_the_launch_url(tmp_path, monkeypatch):
    (tmp_path / ".orch").mkdir()
    rows = [{"addon": "dashboard", "url": "http://127.0.0.1:8421"}]
    monkeypatch.setattr(services, "start", lambda root: rows)
    monkeypatch.setattr(worktrees, "schedule_sweep", lambda root: None)
    monkeypatch.setattr(term, "is_terminal", lambda stream: True)
    monkeypatch.setattr(humanproof, "write_launch_token", lambda root, server: "tok123")
    opened = []
    monkeypatch.setattr(humanproof, "open_browser", lambda url: opened.append(url))
    args = argparse.Namespace(cmd="start", print_launch_url=False, json=False, no_open=False)
    cli_status._services_cmd(args, tmp_path)
    assert opened == ["http://127.0.0.1:8421#launch=tok123"]


KNOWN = {
    "cli_clients.py:_member_parts:relay",
    "humanproof.py:account_home:winacl",
    "init.py:choose_agent:adapters",
    "init.py:_other:adapters",
    "runs.py:_pending_proof:addons",
    "runs.py:_ws_id:addons",
    "tickets.py:next_key:config",
}


def test_no_function_reimports_a_module_level_orch_name():
    """A function-local `from orch import X` makes X local to the WHOLE function: any use before that line
    (or on another branch) raises UnboundLocalError; ruff F823 misses it when the use is later in the source.
    KNOWN: existing sites, to be removed in a follow-up (see the issue linked in the PR); new ones fail."""
    src = Path(__file__).resolve().parents[1] / "src" / "orch"
    bad = []
    for f in sorted(src.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        top = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "orch":
                top |= {a.asname or a.name for a in node.names}
            elif isinstance(node, ast.Import):
                top |= {(a.asname or a.name).split(".")[0] for a in node.names}
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.ImportFrom) and node.module == "orch":
                    for a in node.names:
                        key = f"{f.relative_to(src)}:{fn.name}:{a.asname or a.name}"
                        if (a.asname or a.name) in top and key not in KNOWN:
                            bad.append(f"{f.relative_to(src)}:{node.lineno} {fn.name}: {a.asname or a.name}")
    assert not bad, "local import shadows a module-level import:\n" + "\n".join(bad)

"""`orch start` in a real terminal opens the page with a launch token (it crashed: a local import
shadowed the module-level `orch_home`, UnboundLocalError), and no function re-imports a name its module
already imports."""

import argparse
import ast
from pathlib import Path

from orch import cli_status, pagelaunch, services, term, worktrees


def test_start_in_a_terminal_opens_the_launch_url(tmp_path, monkeypatch):
    (tmp_path / ".orch").mkdir()
    rows = [{"addon": "dashboard", "url": "http://127.0.0.1:8421"}]
    monkeypatch.setattr(services, "start", lambda root: rows)
    monkeypatch.setattr(worktrees, "schedule_sweep", lambda root: None)
    monkeypatch.setattr(term, "is_terminal", lambda stream: True)
    monkeypatch.setattr(pagelaunch, "write_launch_token", lambda root, server: "tok123")
    opened = []
    monkeypatch.setattr(pagelaunch, "open_browser", lambda url: opened.append(url))
    args = argparse.Namespace(cmd="start", print_launch_url=False, json=False, no_open=False)
    cli_status._services_cmd(args, tmp_path)
    assert opened == ["http://127.0.0.1:8421#launch=tok123"]


KNOWN: set[str] = set()


def test_no_function_reimports_a_module_level_orch_name():
    """A function-local `from orch import X` makes X local to the WHOLE function: any use before that line
    (or on another branch) raises UnboundLocalError; ruff F823 misses it when the use is later in the source.
    KNOWN: grandfathered sites (none left; new ones fail)."""
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


def test_print_launch_url_names_this_computer_as_other_computers_reach_it(tmp_path, monkeypatch, capsys):
    """Remote listening on (ORCH-106): the printed sign-in link uses the [dashboard] listen name and port,
    read from the settings file (never a link the add-on hands back); other pages keep their local link."""
    (tmp_path / ".orch").mkdir()
    (tmp_path / ".orch" / "config.toml").write_text(
        '[dashboard]\nlisten = "0.0.0.0"\nlisten_port = 8791\nlisten_name = "Dev.Example"\n'
    )
    rows = [
        {"addon": "dashboard", "url": "http://127.0.0.1:8421"},
        {"addon": "focus", "url": "http://127.0.0.1:8422"},
    ]
    monkeypatch.setattr(services, "start", lambda root: rows)
    monkeypatch.setattr(worktrees, "schedule_sweep", lambda root: None)
    monkeypatch.setattr(pagelaunch, "is_test_workspace", lambda root: True)
    monkeypatch.setattr(pagelaunch, "write_launch_token", lambda root, server, life=0: "tok123")
    args = argparse.Namespace(cmd="start", print_launch_url=True, json=False, no_open=False)
    cli_status._services_cmd(args, tmp_path)
    out = capsys.readouterr().out
    assert "launch dashboard: http://dev.example:8791/#launch=tok123" in out
    assert "launch focus: http://127.0.0.1:8422/#launch=tok123" in out


def test_no_remote_link_for_a_bad_or_missing_setting(tmp_path):
    (tmp_path / ".orch").mkdir()
    cfg = tmp_path / ".orch" / "config.toml"
    assert pagelaunch.remote_base(tmp_path, "dashboard") is None
    for bad in (
        'listen = "0.0.0.0"\nlisten_port = 8791\nlisten_name = "evil.example/x"\n',
        'listen = "0.0.0.0"\nlisten_port = 80\nlisten_name = "ok.example"\n',
        'listen_port = 8791\nlisten_name = "ok.example"\n',  # off: no listen
        'listen = "0.0.0.0"\nlisten_port = 8791\n',  # no name
    ):
        cfg.write_text("[dashboard]\n" + bad)
        assert pagelaunch.remote_base(tmp_path, "dashboard") is None, bad

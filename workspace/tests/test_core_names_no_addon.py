"""AGENTS.md R1.1 / R1.2: the core names no add-on package, and relay/publish are invisible until turned on."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = [*sorted((ROOT / "workspace/src/orch").rglob("*.py")), ROOT / "workspace/src/orch_entry.py"]
ADDONS = sorted(d.name for d in (ROOT / "workspace-addons").iterdir() if (d / "src").is_dir())

# file (relative to workspace/src) -> {literal: reason / issue}. Everything else must be clean.
_MANIFEST = "manifest field of contracts/addon-manifest.md, not a package name"
_FOLLOW_UP = "follow-up: core still names this add-on's setting/marker (see the PR body of #794)"
_GONE = "removed by #799"
ALLOW = {
    "orch/addons.py": {"dashboard": _MANIFEST},
    "orch/cli.py": {"dashboard": _MANIFEST},
    "orch/cli_chat.py": {"sync": "core `orch chat sync` command; not the add-on"},
    "orch/config.py": {"focus": _FOLLOW_UP, "insights": _FOLLOW_UP},
    "orch/history.py": {"sync": _FOLLOW_UP},
    "orch/chat.py": {"automation": _FOLLOW_UP},
    "orch/tickets.py": {"dashboard": "PERSON_VIA: the one named compat constant (wire value of contracts/chat-groups.md)"},
    "orch/humanproof.py": {"focus": _GONE, "dashboard": _GONE, "insights": _GONE},
    "orch/pageproof.py": {"focus": _GONE, "dashboard": _GONE, "insights": _GONE},
    "orch/syncgate.py": {"sync": _GONE},
}


def test_addon_folder_listing_is_found():
    assert {"automation", "dashboard", "sync"} <= set(ADDONS)


def test_core_imports_no_addon_package():
    bad = []
    for f in CORE:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods.append(node.module)
            bad += [f"{f.name}: {m}" for m in mods if m.split(".")[0] in {f"orch_{n}" for n in ADDONS}]
    assert not bad, bad


def test_core_has_no_addon_name_literals():
    names = set(ADDONS) | {f"orch_{n}" for n in ADDONS}
    bad = []
    for f in CORE:
        rel = str(f.relative_to(ROOT / "workspace/src"))
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names:
                if node.value not in ALLOW.get(rel, {}):
                    bad.append(f"{rel}:{node.lineno} {node.value!r}")
    assert not bad, "core names an add-on (R1.2); move it into the add-on or allowlist it with a reason:\n" + "\n".join(bad)


def test_allowlist_has_no_stale_entries():
    seen = {}
    for f in CORE:
        rel = str(f.relative_to(ROOT / "workspace/src"))
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                seen.setdefault(rel, set()).add(node.value)
    stale = [(f, n) for f, d in ALLOW.items() for n in d if n not in seen.get(f, set()) and (ROOT / "workspace/src" / f).exists()]
    assert not stale, stale


def test_shipped_addons_come_from_the_catalog():
    from orch import addons

    assert set(addons.SHIPPED_ADDONS) == set(ADDONS)


def _help(capsys, flag):
    from orch import cli

    capsys.readouterr()
    with pytest.raises(SystemExit):
        cli.main([flag])
    return capsys.readouterr().out


def test_fresh_init_has_no_relay_or_publish_trace(proj, run, capsys):
    code, out, err = run("init")
    assert code == 0
    assert not re.search(r"relay|publish", out + err, re.I), out + err
    tree = (proj / ".orch/harness/AGENTS.orch.md").read_text(encoding="utf-8")
    tree += "".join(p.read_text(encoding="utf-8") for p in (proj / ".orch/harness/skills").rglob("*.md"))
    assert not re.search(r"relay|publish", tree, re.I)
    for flag in ("--help", "--help-all"):
        assert not re.search(r"relay|publish", _help(capsys, flag), re.I), flag
    assert run("addon", "add", "relay", "--yes")[0] == 0
    assert re.search(r"\brelay\b", _help(capsys, "--help-all"))

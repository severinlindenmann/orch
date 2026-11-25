"""AGENTS.md R1.1 / R1.2: core names no add-on package; relay/publish stay invisible until turned on."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = [*sorted((ROOT / "workspace/src/orch").rglob("*.py")), ROOT / "workspace/src/orch_entry.py"]
ADDONS = sorted(d.name for d in (ROOT / "workspace-addons").iterdir() if (d / "src").is_dir())

# file (relative to workspace/src) -> {literal: reason / issue}. Everything else must be clean.
_MANIFEST = "manifest field of contracts/addon-manifest.md, not a package name"
_FOLLOW_UP = "follow-up: core still names this add-on's setting/marker (see #837)"
_GONE = "removed by #799"
_TOKENS = "the record kind 'usage' / the providers' JSON key for token use, not the Usage add-on"
_KEY = "plain data key 'services' (background add-ons, diagnose, doctor, look), not the add-on"
_SKILLS = (
    "the core's own skills (folder, manifest key, relay or key-store kind), not the Skills add-on (ORCH-834)"
)
# Plain words the core uses everywhere as data keys, allowed in every core file. The package name
# (orch_files) and its import stay forbidden.
EVERYWHERE = {
    "files": "plain data key 'files' (lists of files in tickets, evidence, diffs), not the add-on",
    "skills": "the skills folders and data key (.agents/skills, harness skills, inventory 'skills'); "
    "the Skills add-on (ORCH-834) only took the plain word as its name",
}
ALLOW = {
    "orch/addons.py": {"skills": _SKILLS, "dashboard": _MANIFEST, "services": _KEY},
    "orch/cli.py": {"dashboard": _MANIFEST},
    "orch/selfcheck.py": {"dashboard": _MANIFEST},
    "orch/cli_leave.py": {
        "services": "ORCH-843: orch doctor names a macOS-protected workspace folder only while the services "
        "add-on is on (launchd jobs die there); follow-up like #837 (a manifest key instead of the name)",
    },
    "orch/cli_chat.py": {"sync": "core `orch chat sync` command; not the add-on"},
    "orch/whoami.py": {
        "dashboard": "r-1119-1255-ws-8: the names list stays where the dashboard kept it "
        "(.orch/run/dashboard/people.json) so no name is lost; a folder name, not the package"
    },
    "orch/config.py": {"focus": _FOLLOW_UP, "insights": _FOLLOW_UP},
    "orch/history.py": {"sync": _FOLLOW_UP},
    "orch/chat.py": {"automation": _FOLLOW_UP},
    "orch/people.py": {"dashboard": "LOCAL_VIA: via value of a dashboard line (tickets._env_via)"},
    "orch/tickets.py": {
        "dashboard": "PERSON_VIA: the one named compat constant (wire value of contracts/chat-groups.md)",
    },
    "orch/pagesession.py": {"dashboard": _GONE, "insights": _GONE},
    "orch/pagelaunch.py": {"dashboard": _GONE, "insights": _GONE},
    "orch/syncgate.py": {"sync": _GONE},
    "orch/adapters.py": {"usage": _TOKENS},
    "orch/cli_record.py": {"skills": _SKILLS, "usage": _TOKENS},
    "orch/collect_claude.py": {"usage": _TOKENS},
    "orch/collect_execjson.py": {"usage": _TOKENS},
    "orch/keystart.py": {"usage": _TOKENS},
    "orch/record.py": {"usage": _TOKENS},
    "orch/usage.py": {"usage": _TOKENS},
    "orch/cli_look.py": {"services": _KEY},
    "orch/diag_collect.py": {"services": _KEY},
    "orch/diag_report.py": {"services": _KEY},
    "orch/doctorpass.py": {
        "services": _KEY,
        "usage": "the account switcher's JSON key for an account's use, not the Usage add-on",
    },
    "orch/look.py": {"services": _KEY},
    "orch/limitstop.py": {
        "usage": "ORCH-943: every workspace reads the computer's switch log <tool home>/usage/switched.jsonl "
        "(a folder in the tool home, not the add-on package) so its helpers are carried on; "
        "follow-up like #837"
    },
    "orch/winfinish.py": {"services": _KEY},
    "orch/skills.py": {"skills": _SKILLS},
    "orch/skillrender.py": {"skills": _SKILLS},
    "orch/relay.py": {"skills": _SKILLS},
    "orch/net.py": {"skills": _SKILLS},
    "orch/keystore.py": {"skills": _SKILLS},
    "orch/inventory.py": {"skills": _SKILLS},
    "orch/harness.py": {"skills": _SKILLS},
    "orch/cli_secret.py": {"skills": _SKILLS},
}


# Words that are an add-on's name AND an ordinary data key all over the core, allowed in every core file.
EVERYWHERE["skills"] = (
    "plain data key 'skills' (skill folders, lists and manifest field everywhere in orch), not the "
    "Skills add-on (ORCH-834)"
)


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
        rel = f.relative_to(ROOT / "workspace/src").as_posix()
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names:
                if node.value not in ALLOW.get(rel, {}) and node.value not in EVERYWHERE:
                    bad.append(f"{rel}:{node.lineno} {node.value!r}")
    assert not bad, (
        "core names an add-on (R1.2); move it into the add-on or allowlist it with a reason:\n"
        + "\n".join(bad)
    )


def test_allowlist_has_no_stale_entries():
    seen = {}
    for f in CORE:
        rel = f.relative_to(ROOT / "workspace/src").as_posix()
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                seen.setdefault(rel, set()).add(node.value)
    stale = [
        (f, n)
        for f, d in ALLOW.items()
        for n in d
        if n not in seen.get(f, set()) and (ROOT / "workspace/src" / f).exists()
    ]
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


def test_core_skills_name_no_addon():
    # ordinary words that are also an add-on name; the Factory run state is a core ticket term
    plain = set(EVERYWHERE) | {"services", "usage", "personal", "automation", "factory"}
    words = {n for n in ADDONS if n not in plain}
    bad = []
    for f in sorted((ROOT / "workspace/skills").rglob("*.md")):
        text = f.read_text(encoding="utf-8")
        for n in words:
            if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text, re.I):
                bad.append(f"{f.relative_to(ROOT)}: {n}")
    assert not bad, "a core skill names an add-on (R1.1/R1.2, #877):\n" + "\n".join(bad)

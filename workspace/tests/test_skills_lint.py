"""Lint for every shipped skill and AGENTS block (SK-01, SK-09, SK-10, SK-11, SK-14).

A skill that says what is on is rendered for every possible combination of facts; each is checked."""

from __future__ import annotations

import itertools
import re
import tomllib
from pathlib import Path

import pytest

from orch import cli, skillrender

ROOT = Path(__file__).resolve().parents[2]
BUILTIN = ROOT / "workspace/src/orch/builtin"

# Commands a person types (or the installer runs); no skill needs to teach them to an agent.
HUMAN_ONLY = {
    "review run",  # ORCH-848: the signed-in person's Run it now click on a run card
    "review signin",  # ORCH-865: only the terminal window a sign-in card's Run it now opened runs it
    *(f"relay mobile {x}" for x in ("on", "off", "status", "hours", "ack", "keeper")),  # a person's switch
    "tools update",  # a person updates a tool (Settings > About & updates; agents are refused)
    "look shared-pages",  # a person's switch in the dashboard (agents are refused)
    "review answer",  # a person decides a card (agents are refused: needs_person)
    *(f"relay contacts {x}" for x in ("accept", "withdraw", "unsigned")),  # a person's Contacts page clicks
    "relay group add",  # a person adds a workspace to a chat (helpers are refused: they use ask-add)
    "ticket changes",  # a person sends a Review ticket back (agents are refused)
    "run history",  # a person reads or continues an earlier chat (Focus; agents are refused to continue)
    "run take-back",  # a person takes back a waiting message (agents are refused)
    "ref merge",  # a person's Merge on a pull request a helper left open (agents are refused)
    "check wont-do",  # a person decides a step will not be done (agents ask with orch ask)
    "ticket model",  # a person's choice of model (agents are refused; orch picks by itself)
    "chat",  # the dashboard and the Chat helper (its prompt names the commands)
    "copy clean",  # a person's call (the dashboard's "Clean up now"); `orch copy` is hidden from help
    "copy retry",  # a person's "Try again" (agents are refused)
    "copy remove-orphaned",  # a person decides about copies of a moved project
    "copy review",  # the dashboard's review of waiting work (read-only)
    "copy approve",  # a person's "Review and bring back" (needs the person's proof)
    "copy ask-update",  # a person's button; only that ticket's own live run may send it too
    "init",
    "share",
    "private",  # a person's approvals and Move to private (agents are refused)
    "update",
    "doctor",  # a person's check of the install
    "logins",  # a person's check of the tool logins (the dashboard and phone show the same)
    "workspace companion",  # only orch Companion (the Mac menu bar app) runs it; JSON for the app (ORCH-1722)
    "uninstall",  # a person takes orch out of a folder
    "workspace move-here",  # a person keeps a moved folder's saved keys (helpers are refused)
    "relay invite",  # the admin adds a workspace (needs the admin token, typed)
    "publish invite",  # the same for the publish server
    "people",  # a person sets up people and their rights (Settings > People; helpers are refused)
    "start",
    "stop",
    "restart",
    "status",
    "pause",  # a person's runaway brake
    "resume",
    "addon",
    "agents",
    "config",
    "ticket patch",  # raw ticket operations for tools; agents use the commands above
    "run release",
    "run session",
    "run argv",
    "run attach",
    "run stop",
    "run event",
    "run _wrap",
    "publish view",  # feeds the dashboard's Shared tab
    "dev-mark",  # test installs only: the e2e harness marks a demo workspace (never in an agent skill)
    "dev-proof",  # test installs only: the e2e harness's scripted test human (never in an agent skill)
}


RESERVED = {"secret", "record", "job", "conn", "run screen", "run type"}

PENDING: set[str] = set()


def skill_dirs() -> dict[str, Path]:
    out = {
        "orch": ROOT / "workspace/skills/orch",
        "orch-diagnose": ROOT / "workspace/skills/orch-diagnose",
        "orch-github": ROOT / "workspace/skills/orch-github",
    }
    for p in sorted(BUILTIN.glob("*/skills/orch-*")):
        out[p.name] = p
    for p in sorted((ROOT / "workspace-addons").glob("*/src/*/skills/orch-*")):
        out[p.name] = p
    return out


SKILLS = skill_dirs()
ADDON_SRC = {
    # the command is the add-on name: orch_pull_requests -> pull-requests
    p.parent.name.removeprefix("orch_").replace("_", "-"): p
    for p in (ROOT / "workspace-addons").glob("*/src/*/cli.py")
}


def variants(name: str):
    if name == "orch-relay":
        keys = ["connected", "workspaces", "files", "delegate", "start", "phones", "webhooks"]
    elif name == "orch-publish":
        keys = ["connected", "files", "apps", "permanent", "public"]
    else:
        keys = list((skillrender.description_spec(SKILLS[name]) or {}).get("service_facts", {}))
    for vals in itertools.product([False, True], repeat=len(keys)):
        f = dict(zip(keys, vals, strict=True))
        if name in ("orch-relay", "orch-publish") and not f["connected"] and any(f.values()):
            continue
        if name == "orch-relay" and not f["workspaces"] and (f["files"] or f["delegate"] or f["start"]):
            continue
        yield f


def rendered(name: str):
    """[(facts, SKILL.md text, AGENTS block text)] for every possible combination."""
    d = SKILLS[name]
    return [(f, *skillrender.render_skill(d, f)) for f in variants(name)]


def front(text: str) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "no frontmatter"
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"')
    return out


@pytest.mark.parametrize("name", sorted(SKILLS))
def test_frontmatter_and_description(name):
    if name in PENDING:
        pytest.skip("rewritten in the next PR")
    for f, body, _ in rendered(name):
        assert "{{" not in body, f"unrendered tag in {name} {f}"
        fm = front(body)
        assert fm["name"] == name
        d = fm["description"]
        assert 150 <= len(d) <= 500, f"{name} {f}: description is {len(d)} characters"
        assert "Use when" in d and "Not for" in d, f"{name} {f}: description needs 'Use when' and 'Not for'"


@pytest.mark.parametrize("name", sorted(SKILLS))
def test_agents_block_is_short(name):
    if name in PENDING:
        pytest.skip("rewritten in the next PR")
    for f, _, block in rendered(name):
        lines = [x for x in block.strip().splitlines() if x.strip() and not x.startswith("<!--")]
        assert block.strip(), f"{name} has no AGENTS block"
        assert lines[0].startswith("## ")
        assert len(lines) <= 12, f"{name} {f}: AGENTS block is {len(lines)} lines (12 at most)"


@pytest.mark.parametrize("name", sorted(SKILLS))
def test_skill_has_the_three_parts(name):
    if name in PENDING:
        pytest.skip("rewritten in the next PR")
    for _, body, _ in rendered(name)[-1:]:
        for part in ("## When to use", "## Recipes", "## Rules"):
            assert part in body, f"{name}: missing '{part}'"


def test_core_skill_names_no_addon():
    text = (SKILLS["orch"] / "SKILL.md").read_text(encoding="utf-8")
    block = (SKILLS["orch"] / "AGENTS-block.md").read_text(encoding="utf-8")
    for word in ("relay", "publish", "automation", "dashboard", "focus", "phone", "webhook"):
        assert not re.search(rf"\b{word}\b", text + block, re.I), f"core skill names '{word}'"


@pytest.mark.parametrize("name", sorted(SKILLS))
def test_off_features_are_not_in_the_description(name):
    if name in PENDING:
        pytest.skip("rewritten in the next PR")
    words = {"phones": "phone", "webhooks": "webhook", "public": "public"}
    for f, body, _ in rendered(name):
        d = front(body)["description"].lower()
        for fact, word in words.items():
            if fact in f and not f[fact]:
                assert word not in d, f"{name} {f}: description names '{word}' while it is off"


# ---------------------------------------------------------------- commands


def _commands(text: str):
    """Every `orch ...` command in code blocks (indented) and inline code."""
    for line in text.splitlines():
        if "(proposed" in line:
            continue
        spans = [line.strip()] if line.startswith("    ") else re.findall(r"`([^`]+)`", line)
        for s in spans:
            s = re.sub(r"\s+#.*$", "", s.strip())
            if s.startswith("orch ") and len(s) > 5:
                yield s


def _walk(parser, words):
    """Follow lowercase words down the subcommands; returns (parser, error)."""
    for i, w in enumerate(words):
        subs = [a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"]
        if not subs:
            return parser, None
        ch = subs[0].choices
        if w in ch:
            parser = ch[w]
        elif re.fullmatch(r"[a-z][a-z0-9-]*", w):
            return parser, f"unknown command word '{w}' after {' '.join(words[:i])}"
        else:
            return parser, None  # a placeholder such as <id>
    return parser, None


def _check_line(line: str, core) -> str | None:
    toks = [t for t in re.split(r"\s+", line)[1:]]
    words = []
    for t in toks:
        if re.fullmatch(r"[a-z][a-z0-9-]*", t):
            words.append(t)
        else:
            break
    flags = {re.sub(r"[\]\[,;)(]", "", t).split("=")[0] for t in toks if t.startswith(("--", "[--"))}
    flags = {f.lstrip("[") for f in flags if f.startswith(("--", "[--")) and "|" not in f}
    if not words:
        return None  # `orch <add-on> ...`: the add-on is a placeholder
    first = words[0]
    if first in ADDON_SRC:
        src = ADDON_SRC[first].read_text(encoding="utf-8")
        for w in words[1:2]:  # the add-on's own command; what follows may be a verb, not a command
            if f'"{w}"' not in src:
                return f"add-on command '{first} {w}' not found in its cli.py"
        for fl in flags:
            if f'"{fl}"' not in src and fl not in ("--", "--json", "--help"):
                return f"flag {fl} not found in the {first} add-on"
        return None
    parser, err = _walk(core, words)
    if err:
        return err
    known = {s for a in parser._actions for s in a.option_strings}
    for fl in flags:
        if fl not in known:
            return f"flag {fl} is not accepted by 'orch {' '.join(words)}'"
    return None


def test_every_command_in_a_skill_exists():
    core = cli.build_parser(show_all=True)
    bad = []
    for name in SKILLS:
        if name in PENDING:
            continue
        d = SKILLS[name]
        texts = [(f, b + "\n" + blk) for f, b, blk in rendered(name)]
        seen = set()
        for _, t in texts:
            for line in _commands(t):
                if line in seen:
                    continue
                seen.add(line)
                err = _check_line(line, core)
                if err:
                    bad.append(f"{d.name}: `{line}`: {err}")
    assert not bad, "\n".join(bad)


def _leaves(parser, prefix=()):
    subs = [a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"]
    if not subs:
        yield " ".join(prefix)
        return
    for n, p in subs[0].choices.items():
        yield from _leaves(p, (*prefix, n))


def test_every_user_command_is_in_some_skill():
    core = cli.build_parser(show_all=True)
    text = "\n".join(b + blk for n in SKILLS for _, b, blk in rendered(n))
    missing = [
        c
        for c in _leaves(core)
        if c.split()[0] not in HUMAN_ONLY | RESERVED
        and c not in HUMAN_ONLY | RESERVED
        and not re.search(rf"\borch {re.escape(c)}\b", text)
    ]
    assert not missing, f"commands no skill mentions (add them or put them in HUMAN_ONLY): {missing}"


# ---------------------------------------------------------------- rendering


def test_render_sections_and_unknown_fact():
    t = "a\n{{#x}}\nX\n{{/x}}\n{{^x}}\nnotX\n{{/x}}\nb {{#y}}Y{{/y}}\n"
    assert skillrender.render(t, {"x": True, "y": False}) == "a\nX\nb \n"
    assert skillrender.render(t, {"x": False, "y": True}) == "a\nnotX\nb Y\n"
    with pytest.raises(ValueError):
        skillrender.render("{{#nope}}x{{/nope}}", {"x": True})


def test_description_toml_parts_and_limits():
    for name in ("orch-relay", "orch-publish"):
        spec = tomllib.loads((SKILLS[name] / "description.toml").read_text(encoding="utf-8"))
        for part in spec["online"]["part"]:
            assert len(part["text"]) <= 100


def _addon_with_skill(proj, name):
    from conftest import turn_on

    from orch import addons

    turn_on(proj, name)
    assert name in addons.active(proj)


def test_refresh_writes_only_on_change(proj, capsys):
    _addon_with_skill(proj, "publish")
    skill = proj / ".orch/harness/skills/orch-publish/SKILL.md"
    assert "Connect" in skill.read_text(encoding="utf-8") and "{{" not in skill.read_text(encoding="utf-8")
    capsys.readouterr()
    assert skillrender.refresh_skills(proj) == []
    assert capsys.readouterr().out == ""
    secrets = proj / ".orch/secrets"
    secrets.mkdir(parents=True)
    (secrets / "publish.json").write_text(
        '{"url": "http://x", "workspace": "ws_aaaaaaaaaa", "token": "orp_x",'
        ' "rights": {"files": true, "apps": false, "permanent": true, "public": false}}'
    )
    assert skillrender.refresh_skills(proj) == ["publish"]
    assert "they apply from the next agent session" in capsys.readouterr().err
    text = skill.read_text(encoding="utf-8")
    assert "--permanent" in text and "--public" not in text and "orch publish app" not in text


def test_skill_file_link_is_replaced_not_followed(proj, tmp_path):
    _addon_with_skill(proj, "publish")
    victim = proj / "victim.txt"  # inside the project (a link out of it is refused earlier)
    victim.write_text("keep me", encoding="utf-8")
    skill = proj / ".orch/harness/skills/orch-publish/SKILL.md"
    skill.unlink()
    skill.symlink_to(victim)
    (proj / ".orch/secrets").mkdir(parents=True)
    (proj / ".orch/secrets/publish.json").write_text(
        '{"url": "http://x", "workspace": "ws_aaaaaaaaaa", "token": "orp_x",'
        ' "rights": {"files": true, "apps": true, "permanent": false, "public": false}}'
    )
    skillrender.refresh_skills(proj)
    assert victim.read_text(encoding="utf-8") == "keep me"
    assert not skill.is_symlink() and "orch publish file" in skill.read_text(encoding="utf-8")


def test_skills_folder_link_is_refused(proj, tmp_path):
    from orch.errors import Refused

    _addon_with_skill(proj, "publish")
    real = proj / ".orch/harness/skills/orch-publish"
    moved = proj / "elsewhere"
    real.rename(moved)
    real.symlink_to(moved, target_is_directory=True)
    (moved / "SKILL.md").write_text("old", encoding="utf-8")
    with pytest.raises(Refused, match="is a link"):
        skillrender.refresh_skills(proj)
    assert (moved / "SKILL.md").read_text(encoding="utf-8") == "old"


def test_automation_and_dashboard_follow_the_facts():
    auto = SKILLS["orch-automation"]
    off = skillrender.render_skill(auto, {"relay": False, "webhooks": False})[0]
    on = skillrender.render_skill(auto, {"relay": True, "webhooks": True})[0]
    assert "webhook" not in off and "relay" not in off.lower()
    assert "orch relay webhook new" in on
    dash = SKILLS["orch-dashboard"]
    assert "--publish" not in skillrender.render_skill(dash, {"publish": False})[0]
    assert "--publish" in skillrender.render_skill(dash, {"publish": True})[0]


@pytest.mark.parametrize(
    ("name", "service", "marker"),
    [("automation", "relay", "orch relay webhook new"), ("dashboard", "publish", "--publish")],
)
def test_external_skill_refresh_lifecycle(proj, monkeypatch, name, service, marker):
    from orch import addons, harness

    source = SKILLS[f"orch-{name}"]
    manifest = addons.parse_manifest(source.parents[1] / addons.MANIFEST)
    installed = {name: manifest}
    monkeypatch.setattr(addons, "discover", lambda: installed)
    addons.record_consent(proj, name)
    addons._activate(proj, name)
    skill = proj / f".agents/skills/orch-{name}/SKILL.md"
    rendered = proj / f".orch/harness/skills/orch-{name}/SKILL.md"  # .agents is a copy on Windows
    assert marker not in skill.read_text(encoding="utf-8")
    cfg = proj / f".orch/secrets/{service}.json"
    cfg.parent.mkdir(exist_ok=True)
    cfg.write_text('{"url":"http://x","workspace":"ws_aaaaaaaaaa","token":"test"}', encoding="utf-8")
    assert skillrender.refresh_skills(proj) == [name]
    assert marker in rendered.read_text(encoding="utf-8")
    if name == "automation":
        assert "when work arrives from outside" in harness.current_block(proj, name)
    assert skillrender.refresh_skills(proj) == []
    installed.clear()
    cfg.unlink()
    assert skillrender.refresh_skills(proj) == []  # listed here, but its package is absent
    assert marker in rendered.read_text(encoding="utf-8")
    addons.remove(proj, name)
    installed[name] = manifest
    assert skillrender.refresh_skills(proj) == []  # installed again, but no longer turned on
    assert not skill.exists() and not harness.current_block(proj, name)


def test_unknown_service_fact_is_rejected(proj):
    with pytest.raises(ValueError, match="service_facts"):
        skillrender.facts_for(proj, "orch-example", {"service_facts": {"x": "typo"}})


def test_write_atomic_replaces_a_planted_link(tmp_path):
    from orch import net

    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    (tmp_path / "x.json").symlink_to(victim)
    net.write_atomic(tmp_path / "x.json", b"{}")  # private=True outside .orch is refused (test_init)
    assert victim.read_text() == "keep me" and not (tmp_path / "x.json").is_symlink()
    assert not list(tmp_path.glob(".*.tmp"))


def test_orch_block_is_five_numbered_rules():
    block = (SKILLS["orch"] / "AGENTS-block.md").read_text(encoding="utf-8")
    numbered = [x for x in block.splitlines() if re.match(r"[1-5]\. ", x)]
    assert len(numbered) == 5
    assert "orch ticket new" in numbered[0] and "orch check add" in numbered[1]
    assert "orch check done" in numbered[2] and "orch ask" in numbered[3]
    assert "orch ticket summary" in numbered[4]
    assert "There are no signing or planning gates" in block


# R2: each key statement of AGENTS.md section 2 (left) must be said by the shipped block (right).
R2_STATEMENTS = [
    (
        "Priority order: **task-based → evidence-based → context-based**",
        "task-based first, then evidence-based, then context-based",
    ),
    ("happens on a ticket with a checklist", "Every change belongs to a ticket"),
    (
        "Questions and read-only looking around need no ticket",
        "Questions and read-only looking around need no ticket",
    ),
    ("only when it has at least one evidence entry", "A task is done only with evidence"),
    ("the ticket holds a short handover and links", "short handover with links"),
    ("enough for a fresh agent to continue", "lets a fresh agent go on"),
    ("no copies of whole files and no secrets", "no copies of whole files, no secrets"),
    ('It never asks "may I do this step"', 'never ask "may I do this step"'),
    ("Every question carries options and a recommended answer", "--option A --option B --recommend A"),
    ("The user can adjust the list in one file the skill reads", "`.orch/ask-when.md`"),
    (
        "**R2.5 One way to ask:** the ticket question (`orch ask`)",
        "Every question for the person goes through `orch ask`",
    ),
    (
        "keeps working on items that don't depend on the answer",
        "keep working on the steps that do not depend on the answer",
    ),
]


@pytest.mark.parametrize(("rule", "said"), R2_STATEMENTS, ids=[s for s, _ in R2_STATEMENTS])
def test_orch_block_says_what_agents_md_r2_says(rule, said):
    """R2: the shipped AGENTS block says the same as AGENTS.md section 2, in the same priority order."""
    rules = " ".join((ROOT / "AGENTS.md").read_text(encoding="utf-8").split())
    section = rules[rules.index("## 2. How agents work") : rules.index("## 3. ")]
    block = " ".join((SKILLS["orch"] / "AGENTS-block.md").read_text(encoding="utf-8").split())
    assert rule in section, f"AGENTS.md R2 changed ('{rule}'): update R2_STATEMENTS and the AGENTS block"
    assert said in block, f"the AGENTS block drifted from AGENTS.md R2: it must say '{said}'"


def test_orch_block_keeps_the_r2_priority_order():
    block = (SKILLS["orch"] / "AGENTS-block.md").read_text(encoding="utf-8")
    order = [block.index(x) for x in ("orch check add", "orch check done", "orch ticket summary")]
    assert order == sorted(order), "task (check add), then evidence (check done), then context (summary)"


def addon_manifests() -> list[Path]:
    return sorted(
        [*(ROOT / "workspace-addons").glob("*/src/*/orch-addon.toml"), *BUILTIN.glob("*/orch-addon.toml")]
    )


def test_every_addon_package_has_a_manifest():
    """R1.2: every add-on with code plugs in through orch-addon.toml (placeholders without src/ excepted)."""
    for src in sorted((ROOT / "workspace-addons").glob("*/src")):
        assert list(src.glob("*/orch-addon.toml")), f"{src.parent.name}: no orch-addon.toml"


@pytest.mark.parametrize("manifest", addon_manifests(), ids=lambda p: p.parent.name)
def test_every_addon_ships_its_own_agents_block(manifest):
    """R1.2: every add-on ships its own skill and AGENTS block; none reuses the core block."""
    m = tomllib.loads(manifest.read_text(encoding="utf-8"))
    skill = manifest.parent / m["skill"]
    block = manifest.parent / m.get("agents_block", f"{m['skill']}/AGENTS-block.md")
    assert (skill / "SKILL.md").is_file(), f"{m['name']}: no SKILL.md"
    assert block.is_file(), f"{m['name']}: no AGENTS block at {block}"
    lines = [
        x for x in block.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("<!--")
    ]
    assert lines and lines[0].startswith("## "), (
        f"{m['name']}: the AGENTS block starts with its own '## ' heading"
    )
    assert lines[0] != "## orch workspace", f"{m['name']}: ships a copy of the core block, not its own"


def test_asking_keeps_the_agent_working():
    """R2.6: after `orch ask` the agent keeps working on what does not need the answer; never stops there."""
    block = (SKILLS["orch"] / "AGENTS-block.md").read_text(encoding="utf-8")
    text = (SKILLS["orch"] / "SKILL.md").read_text(encoding="utf-8")
    for where, t in (("AGENTS block", block), ("SKILL.md", text)):
        flat = " ".join(t.split())
        assert not re.search(r"orch ask[^.]*(then|and) stop\b", flat), f"{where}: asking must not mean stop"
        assert "keep working" in flat.lower(), f"{where}: say to keep working while the ticket waits"


def test_ask_list_is_in_the_skill_and_editable_in_one_file():
    """R2.4: the five cases are in the skill, and the person can replace them in one file the skill names."""
    text = " ".join((SKILLS["orch"] / "SKILL.md").read_text(encoding="utf-8").split())
    block = (SKILLS["orch"] / "AGENTS-block.md").read_text(encoding="utf-8")
    assert "## When to ask" in text
    for case in (
        "cannot be undone",
        "costs money",
        "touches production",
        "deletes real data",
        "visible to people outside",
    ):
        assert case in text, case
    assert 'Never ask "may I do this step"' in text and "recommended answer" in text
    assert "`.orch/ask-when.md`" in text and "`.orch/ask-when.md`" in block

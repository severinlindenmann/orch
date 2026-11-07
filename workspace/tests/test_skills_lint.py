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
    *(f"relay mobile {x}" for x in ("on", "off", "status", "hours", "ack", "keeper")),  # a person's switch
    "look shared-pages",  # a person's switch in the dashboard (agents are refused)
    "init",
    "share",
    "update",
    "start",
    "stop",
    "status",
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
}


PENDING: set[str] = set()


def skill_dirs() -> dict[str, Path]:
    out = {"orch": ROOT / "workspace/skills/orch"}
    for p in sorted(BUILTIN.glob("*/skills/orch-*")):
        out[p.name] = p
    for p in sorted((ROOT / "workspace-addons").glob("*/src/*/skills/orch-*")):
        out[p.name] = p
    return out


SKILLS = skill_dirs()
ADDON_SRC = {
    p.parent.name.removeprefix("orch_"): p for p in (ROOT / "workspace-addons").glob("*/src/*/cli.py")
}


def variants(name: str):
    keys = skillrender.FACTS.get(name, [])
    for vals in itertools.product([False, True], repeat=len(keys)):
        f = dict(zip(keys, vals, strict=True))
        if skillrender.possible(name, f):
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
        assert len(lines) <= 4, f"{name} {f}: AGENTS block is {len(lines)} lines (heading + 3 at most)"


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
    text = "\n".join(b + blk for n in SKILLS for _, b, blk in rendered(n) if skillrender.possible(n, _))
    missing = [
        c
        for c in _leaves(core)
        if c.split()[0] not in HUMAN_ONLY
        and c not in HUMAN_ONLY
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
    assert "they apply from the next agent session" in capsys.readouterr().out
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


def test_write_atomic_replaces_a_planted_link(tmp_path):
    from orch import net

    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    (tmp_path / "x.json").symlink_to(victim)
    net.write_atomic(tmp_path / "x.json", b"{}", True)
    assert victim.read_text() == "keep me" and not (tmp_path / "x.json").is_symlink()
    assert not list(tmp_path.glob(".*.tmp"))

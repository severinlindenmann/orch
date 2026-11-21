"""ORCH-534: a skill's metadata requires / requires-logins / requires-addons are checked on this computer.
A skill that misses something stays visible to helpers with one line "not ready here: gh missing" and the
inventory (Insights) carries what is missing."""

import json

from test_fakeorch import validator

from orch import addons, harness, inventory, skillready


def skill(base, name, meta: dict | None = None):
    folder = base / name
    folder.mkdir(parents=True)
    lines = ["---", f"name: {name}", f"description: {name} things. Use when x."]
    if meta:
        lines.append("metadata:")
        lines += [f'  {k}: "{v}"' for k, v in meta.items()]
    lines.append("---")
    (folder / "SKILL.md").write_text("\n".join(lines) + "\nBody\n")
    return folder


def test_header_metadata_is_read(tmp_path):
    folder = skill(tmp_path, "github", {"requires": "gh, git", "owner": "Severin"})
    assert skillready.metadata(folder) == {"requires": "gh, git", "owner": "Severin"}
    assert skillready.metadata(skill(tmp_path, "plain")) == {}
    (tmp_path / "broken").mkdir()
    never_closed = "---\nname: broken\nmetadata:\n  requires: gh\n"
    (tmp_path / "broken" / "SKILL.md").write_text(never_closed)
    assert skillready.metadata(tmp_path / "broken") == {}


def test_a_quoted_value_with_a_comment_after_it(tmp_path):
    folder = tmp_path / "gh"
    folder.mkdir()
    head = "---\nname: gh\nmetadata:\n  requires: \"gh\" # GitHub CLI\n  owner: 'Severin'\n---\nBody\n"
    (folder / "SKILL.md").write_text(head)
    assert skillready._fallback_header(head)["metadata"] == {"requires": "gh", "owner": "Severin"}


def test_missing_programs_logins_and_addons(proj, monkeypatch):
    monkeypatch.setattr(skillready.shutil, "which", lambda p: "/usr/bin/git" if p == "git" else None)
    monkeypatch.setattr(skillready, "_login_names", lambda root: {"have-login"})
    monkeypatch.setattr(skillready, "_active_addons", lambda root: {"relay"})
    meta = {
        "requires": "gh, git",
        "requires-logins": "have-login, github-login",
        "requires-addons": "relay, publish",
    }
    assert skillready.missing(proj, meta) == ["gh", "login github-login", "add-on publish"]
    assert skillready.missing(proj, {"requires": "git", "requires-addons": "relay"}) == []
    assert skillready.missing(proj, {}) == []
    # anything that is not a plain name is never looked up, shown or written
    assert skillready.missing(proj, {"requires": "$(touch x), ../bin/gh, a b"}) == []


def test_codex_review_cases(tmp_path, proj, monkeypatch):
    """Inline comments are not part of a value; the list stays within the schema; an unusable login is
    missing."""
    folder = tmp_path / "c"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        '---\nname: c\nmetadata:\n  requires: gh # GitHub CLI\n  tags: "a # b"\n---\n'
    )
    assert skillready.metadata(folder) == {"requires": "gh", "tags": "a # b"}
    monkeypatch.setattr(skillready.shutil, "which", lambda p: None)
    many = skillready.missing(proj, {"requires": ",".join(f"tool{i}" for i in range(70))})
    assert len(many) == skillready.MAX_MISSING
    from orch import keystore

    monkeypatch.setattr(
        keystore,
        "list_keys",
        lambda root: [
            {"name": "ok-login", "state": "active"},
            {"name": "stale-login", "state": keystore.NEEDS_REENTRY},
        ],
    )
    meta = {"requires-logins": "ok-login, stale-login"}
    assert skillready.missing(proj, meta) == ["login stale-login"]


def test_note_words():
    assert skillready.note(["gh"]) == "not ready here: gh missing"
    assert skillready.note(["gh", "login github-login"]) == "not ready here: gh, login github-login missing"
    long = skillready.note([f"p{i}" for i in range(10)])
    assert long.endswith("and 2 more missing")


def test_helpers_read_the_note_and_it_goes_away_when_ready(proj, monkeypatch):
    monkeypatch.setattr(skillready.shutil, "which", lambda p: None if p == "gh-missing-tool" else "/bin/" + p)
    skill(proj / ".agents" / "skills", "github", {"requires": "gh-missing-tool, git"})
    skill(proj / ".agents" / "skills", "ready-one", {"requires": "git"})
    harness.set_block(proj, "base", "## base block")
    assert skillready.refresh(proj) is True
    text = (harness.harness_dir(proj) / "AGENTS.orch.md").read_text()
    assert "## Skills not ready here" in text
    assert "- github: not ready here: gh-missing-tool missing" in text
    assert "ready-one" not in text and "## base block" in text
    assert skillready.refresh(proj) is False  # unchanged: nothing written
    # the skill is still offered: its folder and SKILL.md are untouched
    assert (proj / ".agents" / "skills" / "github" / "SKILL.md").read_text().startswith("---\nname: github")
    monkeypatch.setattr(skillready.shutil, "which", lambda p: "/bin/" + p)
    assert skillready.refresh(proj) is True
    text = (harness.harness_dir(proj) / "AGENTS.orch.md").read_text()
    assert "not ready here" not in text and "## base block" in text
    assert harness.current_block(proj, skillready.BLOCK, addon=False) is None


def test_user_skills_of_the_agent_tool_count_too(proj, monkeypatch):
    monkeypatch.setattr(skillready.shutil, "which", lambda p: None)
    skill(addons.real_home() / ".claude" / "skills", "users-own", {"requires": "gh"})
    assert [i["name"] for i in skillready.not_ready(proj)] == ["users-own"]


def test_refresh_never_raises(proj, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bad")

    monkeypatch.setattr(skillready, "not_ready", boom)
    assert skillready.refresh(proj) is False


def test_inventory_carries_missing_for_insights(proj, monkeypatch):
    monkeypatch.setattr(skillready.shutil, "which", lambda p: None if p == "gh" else "/bin/" + p)
    monkeypatch.setattr(skillready, "_active_addons", lambda root: set())
    skill(proj / ".agents" / "skills", "github", {"requires": "gh, git", "requires-addons": "relay"})
    skill(proj / ".agents" / "skills", "fine", {"requires": "git"})
    got = {s["name"]: s for s in inventory.skills(proj) if s["source"] == "workspace"}
    assert got["github"]["missing"] == ["gh", "add-on relay"]
    assert "missing" not in got["fine"]
    doc = inventory.document(proj, "2026-11-18T10:00:00Z")
    validator("inventory", "inventory").validate(doc)
    json.dumps(doc)

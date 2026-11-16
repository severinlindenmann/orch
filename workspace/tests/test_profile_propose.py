"""ORCH-36: `orch config propose` works out a workspace profile from the folder and saves nothing."""

import json

from orch import config, look, profile_propose, tickets


def test_proposal_from_readme_and_tickets_saves_nothing(proj, run):
    (proj / "README.md").write_text(
        '<p align="center"><img src="logo.svg"></p>\n\n# Corner Bakery: our shop\n\n'
        "[![badge](x.svg)](y)\n\nThe website, newsletter and orders of our bakery.\n\n## Setup\n\nRun it.\n",
        encoding="utf-8",
    )
    for title in ("Newsletter for May", "Fix the newsletter footer", "Newsletter photos", "Orders page"):
        tickets.create(proj, title, "human:t")
    cfg = proj / ".orch" / "config.toml"
    before = cfg.read_bytes() if cfg.exists() else None
    code, out, _ = run("config", "propose", "--json")
    assert code == 0
    p = json.loads(out)
    assert p["name"] == "Corner Bakery"
    assert p["description"] == "The website, newsletter and orders of our bakery."
    assert "newsletter" in p["tags"] and 1 <= len(p["tags"]) <= config.MAX_WS_TAGS
    assert all(config.WS_TAG_RE.fullmatch(t) for t in p["tags"])
    assert p["icon"] in look.ICON_IDS
    after = cfg.read_bytes() if cfg.exists() else None
    assert before == after and config.workspace_name(proj) is None


def test_empty_folder_falls_back_to_the_folder_name(proj):
    p = profile_propose.propose(proj)
    assert p["name"] and p["description"] == "" and p["tags"] == []
    assert "the folder name" in p["from"]


def test_generic_headings_and_a_pointer_file_are_skipped(proj):
    (proj / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    (proj / "AGENTS.md").write_text(
        "# AGENTS.md\n\n## Rules\n\n- one\n\n# Garden Club: notes\n\nPlans and photos for the garden club.\n",
        encoding="utf-8",
    )
    p = profile_propose.propose(proj)
    assert p["name"] == "Garden Club"
    assert p["description"] == "Plans and photos for the garden club."


def test_a_linked_readme_is_never_read(proj, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# Secret Place\n\nDo not read this file at all.\n", encoding="utf-8")
    (proj / "README.md").symlink_to(outside)
    p = profile_propose.propose(proj)
    assert p["name"] != "Secret Place" and "Do not read" not in p["description"]


def test_an_icon_the_person_picked_is_never_proposed_again(proj):
    (proj / "README.md").write_text("# Code Lab\n\nSoftware development for our team.\n", encoding="utf-8")
    assert profile_propose.propose(proj)["icon"] == "code"
    look.set_look(proj, icon="wallet", by="human:t", push=False)
    assert profile_propose.propose(proj)["icon"] is None

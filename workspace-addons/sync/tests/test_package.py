import re
import tomllib
from importlib import resources

from orch_sync import cli

PRODUCTS = re.compile(r"tailscale|zerotier|wireguard|openvpn|nordvpn|hamachi", re.IGNORECASE)


def manifest():
    return tomllib.loads((resources.files("orch_sync") / "orch-addon.toml").read_text())


def test_manifest_names_agents_block_and_plain_description():
    m = manifest()
    assert m["agents_block"] == "skills/orch-sync/AGENTS-block.md" and m["background"] is True
    d = m["description"]  # the core shows it when the person turns sync on (orch addon add sync)
    assert len(d) <= 120 and "tickets" in d and "never secrets or private files" in d and "Off any time" in d
    assert not PRODUCTS.search(d)


def test_agents_block_says_person_only_actions_need_proof():
    root = resources.files("orch_sync") / "skills" / "orch-sync"
    block = (root / "AGENTS-block.md").read_text()
    assert block.startswith("## orch-sync\n") and "orch:addon" not in block and len(block.splitlines()) <= 6
    assert "skills/orch-sync/SKILL.md" in block
    for word in ("resolve", "approve", "take-remote", "keep-key", "proof", "Ask the person", "never run"):
        assert word in block
    skill = (root / "SKILL.md").read_text()
    for cmd in ("orch sync start", "orch sync stop", "orch sync status --json", "orch sync now --json",
                "orch sync set --interval"):
        assert cmd in skill
    assert not PRODUCTS.search(block + skill)


def test_consent_text_says_what_where_how_often_and_off():
    local = cli.consent({"mode": "local", "interval": 60})
    remote = cli.consent({"mode": "remote", "interval": 60, "remote": "https://me:pw@git.example/r.git"})
    for text in (local, remote):
        assert "tickets and their files in .orch" in text and "never copies secrets or private files" in text
        assert "turn it off any time" in text and not PRODUCTS.search(text)
    assert "on this computer only" in local and "every 5 minutes at most" in local
    assert "at https://git.example/r.git" in remote and "every 60 minutes" in remote and "me:pw" not in remote

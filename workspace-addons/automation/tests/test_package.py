import tomllib
from importlib import metadata, resources
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def test_entry_point_is_module_only_and_manifest_next_to_it():
    eps = {e.name: e.value for e in metadata.entry_points(group="orch.addons")}
    assert eps["automation"] == "orch_automation"
    pkg = resources.files("orch_automation")
    m = tomllib.loads((pkg / "orch-addon.toml").read_text())
    assert m["name"] == "automation" and m["run"] == "orch_automation" and m["background"] is True
    assert m["ticket_ext"] == "ext.schema.json" and m["dashboard"]["label"] == "Automation"


def test_manifest_is_the_review_example_and_valid():
    import json

    import jsonschema

    pkg = resources.files("orch_automation")
    assert (pkg / "orch-addon.toml").read_text() == (
        CONTRACTS / "review" / "automation.orch-addon.toml"
    ).read_text()
    schema = json.loads((CONTRACTS / "addon-manifest.schema.json").read_text())
    jsonschema.validate(tomllib.loads((pkg / "orch-addon.toml").read_text()), schema)


def test_ext_schema_byte_identical_to_contract():
    ours = (resources.files("orch_automation") / "ext.schema.json").read_bytes()
    assert ours == (CONTRACTS / "addons" / "automation" / "ext.schema.json").read_bytes()


def test_skill_and_agents_block():
    root = resources.files("orch_automation") / "skills" / "orch-automation"
    skill = (root / "SKILL.md").read_text()
    assert (
        skill.startswith("---\nname: orch-automation\n")
        and "wake_at" not in skill
        and "--recurring" not in skill
    )
    block = (root / "AGENTS-block.md").read_text()
    assert (
        block.startswith("## orch-automation") and "orch:addon" not in block and len(block.splitlines()) <= 6
    )
    assert "skills/orch-automation/SKILL.md" in block and "wake_at" not in block

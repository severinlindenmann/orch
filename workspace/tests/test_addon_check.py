"""`orch addon check`: every shipped add-on follows contracts/addon-manifest.md; a broken one gets plain
problems."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orch import addoncheck, addons

REPO = Path(__file__).resolve().parents[2]
SHIPPED = sorted(
    p.parent
    for p in (REPO / "workspace-addons").glob("*/pyproject.toml")
    if any(p.parent.glob(f"**/{addons.MANIFEST}"))  # placeholders of removed add-ons ship no manifest
)


def test_every_folder_with_a_manifest_is_shipped():
    assert {f.name for f in SHIPPED} == set(addons.SHIPPED_ADDONS)


@pytest.mark.parametrize("folder", SHIPPED, ids=lambda f: f.name)
def test_every_shipped_addon_follows_the_contract(folder):
    res = addoncheck.check(str(folder))
    assert res["ok"], "\n".join(res["problems"])
    assert res["name"] == folder.name


@pytest.mark.parametrize("name", addons.CORE_ADDONS)
def test_core_addons_follow_the_contract(name):
    res = addoncheck.check(name)
    assert res["ok"], "\n".join(res["problems"])


def _addon(base: Path, name: str = "hello") -> Path:
    module = "orch_" + name.replace("-", "_")
    folder = base / name
    pkg = folder / "src" / module
    sk = pkg / "skills" / f"orch-{name}"
    sk.mkdir(parents=True)
    (folder / "pyproject.toml").write_text(
        f'[project]\nname = "x"\n[project.entry-points."orch.addons"]\n{name} = "{module}"\n',
        encoding="utf-8",
    )
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / addons.MANIFEST).write_text(
        f'schema = "orch.addon/1"\norch_api = 1\nname = "{name}"\nversion = "0.1.0"\n'
        f'description = "Says hello."\nrun = "{module}"\nskill = "skills/orch-{name}"\n'
        'ticket_ext = "ext.schema.json"\n'
        '[[ticket_view]]\nfield = "greeting"\nlabel = "Greeting"\nformat = "text"\n',
        encoding="utf-8",
    )
    (sk / "SKILL.md").write_text(f"---\nname: orch-{name}\ndescription: d\n---\nbody\n", encoding="utf-8")
    (sk / "AGENTS-block.md").write_text(f"## orch-{name}\nRead the skill.\n", encoding="utf-8")
    (pkg / "ext.schema.json").write_text(
        json.dumps({"type": "object", "properties": {"greeting": {"type": "string"}}}), encoding="utf-8"
    )
    return folder


def test_a_good_folder_passes(tmp_path):
    res = addoncheck.check(str(_addon(tmp_path)))
    assert res == {"name": "hello", "folder": str(tmp_path / "hello"), "ok": True, "problems": []}


def test_each_broken_part_is_named(tmp_path):
    f = _addon(tmp_path)
    pkg = f / "src" / "orch_hello"
    toml = pkg / addons.MANIFEST
    toml.write_text(toml.read_text().replace('name = "hello"', 'name = "hallo"'), encoding="utf-8")
    sk = pkg / "skills" / "orch-hello"
    (sk / "SKILL.md").write_text("---\nname: hello\n---\nbody\n", encoding="utf-8")
    (sk / "AGENTS-block.md").write_text("<!-- only a comment -->\n", encoding="utf-8")
    (pkg / "ext.schema.json").write_text(json.dumps({"type": "array"}), encoding="utf-8")
    res = addoncheck.check(str(f))
    assert not res["ok"]
    text = "\n".join(res["problems"])
    assert 'The entry point is hello but orch-addon.toml says name = "hallo"' in text
    assert "it must be orch-hallo" in text
    assert "has no description" in text
    assert "AGENTS block (skills/orch-hello/AGENTS-block.md) is empty" in text
    assert 'must describe an object (type = "object")' in text
    assert "has no property greeting" not in text  # an array schema has no properties to compare


def test_entry_point_and_manifest_problems(tmp_path):
    f = _addon(tmp_path)
    (f / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert addoncheck.check(str(f))["problems"] == [
        "pyproject.toml has no entry point: "
        'add [project.entry-points."orch.addons"] with <name> = "<module>".'
    ]
    (f / "pyproject.toml").write_text(
        '[project]\nname = "x"\n[project.entry-points."orch.addons"]\nhello = "orch_hello:main"\n',
        encoding="utf-8",
    )
    assert "top-level module only" in addoncheck.check(str(f))["problems"][0]
    (f / "pyproject.toml").write_text(
        '[project]\nname = "x"\n[project.entry-points."orch.addons"]\nhello = "orch_hi"\n', encoding="utf-8"
    )
    assert "no orch-addon.toml next to the package orch_hi" in addoncheck.check(str(f))["problems"][0]
    (f / "pyproject.toml").write_text(
        '[project]\nname = "x"\n[project.entry-points."orch.addons"]\nhello = "orch_hello"\n',
        encoding="utf-8",
    )
    (f / "src/orch_hello/ext.schema.json").write_text(json.dumps({"type": "object", "properties": {}}))
    assert addoncheck.check(str(f))["problems"] == [
        "greeting is shown on tickets but ext.schema.json has no property greeting: add it to the schema."
    ]
    (f / "src/orch_hello/skills/orch-hello/SKILL.md").unlink()
    assert addoncheck.check(str(f))["problems"] == [
        "This add-on's orch-addon.toml is not valid: the skill folder has no SKILL.md."
    ]


def test_cli_exit_codes_and_json(proj, run, tmp_path):
    good = _addon(tmp_path / "a")
    code, out, _ = run("addon", "check", str(good), "--json")
    assert code == 0 and json.loads(out)["ok"] is True
    (good / "src/orch_hello/skills/orch-hello/AGENTS-block.md").write_text("", encoding="utf-8")
    code, out, _ = run("addon", "check", str(good))
    assert code == 1
    assert "hello: 1 problem with the add-on contract" in out and "is empty" in out
    assert "Next: fix what is listed, then run orch addon check" in out
    code, _, err = run("addon", "check", "no-such-addon")
    assert code == 2 and "No add-on named no-such-addon is installed here" in err

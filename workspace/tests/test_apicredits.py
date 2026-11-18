"""ORCH-625: orch finds every API credit that skills and add-ons declare (format ORCH-600), and `orch skill check`
flags a wrong declaration. No code per provider, and never a key value."""
# ruff: noqa: E501

import json
from pathlib import Path

import pytest

from orch import addons, apicredits, cli, skillmeta
from orch.errors import Refused

FAKE_KEY = "sk-ant-api03-" + "Zq7" * 12 + "AA"  # made up; shaped like a key so the secret patterns match it

HEADER = (
    "---\nname: {name}\ndescription: Look up places on a map service. Use when a ticket needs addresses.\n"
    'metadata:\n  status: "active"\n  api-credits: "{file}"\n---\n# body\n'
)

GOOD = """
[[credit]]
name     = "main"
label    = "Maps key"
provider = "Google Maps"
key      = "pass:Agents/Maps key"
unit     = "calls"
spend    = "report"

[[credit]]
name     = "backup"
label    = "Maps key 2"
provider = "Google Maps"
key      = "orch:maps-backup"
unit     = "$"
spend    = "log:spend.jsonl"
balance  = "python3 balance.py"
"""


def credit_skill(
    base: Path, name: str = "maps-helper", toml: str = GOOD, file: str = "api-credits.toml"
) -> Path:
    """A made-up skill that declares credits: what any new skill with API access would ship."""
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(HEADER.format(name=name, file=file), encoding="utf-8")
    if toml is not None:
        (folder / "api-credits.toml").write_text(toml, encoding="utf-8")
    return folder


def one(**over) -> str:
    c = {
        "name": "main",
        "label": "Maps key",
        "provider": "Google Maps",
        "key": "pass:Agents/Maps key",
        "unit": "calls",
        "spend": "report",
    }
    c.update(over)
    lines = [f"{k} = {json.dumps(v) if isinstance(v, str) else v}" for k, v in c.items() if v is not None]
    return "[[credit]]\n" + "\n".join(lines) + "\n"


@pytest.fixture
def ws(proj, monkeypatch, tmp_path):
    """A workspace whose person's own skill folders are temp folders (never the real home)."""
    user = tmp_path.parent / f"{tmp_path.name}_userskills"
    monkeypatch.setattr(apicredits, "user_skill_dirs", lambda: [user / ".claude" / "skills"])
    monkeypatch.setattr(apicredits, "_addon_manifests", lambda root: {})
    return proj


def run(capsys, *argv) -> tuple[int, str]:
    try:
        code = cli.main(["skill", *argv])
    except SystemExit as e:
        code = e.code
    return code or 0, capsys.readouterr().out


# --- found without a code change ---------------------------------------------------------------------------


def test_a_made_up_skill_with_credits_is_listed(ws, capsys):
    credit_skill(ws / ".agents" / "skills")
    code, out = run(capsys, "credits", "--json")
    res = json.loads(out)
    assert code == 0 and res["problems"] == []
    got = {c["credit"]: c for c in res["credits"]}
    assert list(got) == ["maps-helper/main", "maps-helper/backup"]
    main = got["maps-helper/main"]
    assert {
        k: main[k] for k in ("label", "provider", "key", "unit", "spend", "balance", "owner", "source")
    } == {
        "label": "Maps key",
        "provider": "Google Maps",
        "key": "pass:Agents/Maps key",
        "unit": "calls",
        "spend": "report",
        "balance": "",
        "owner": "maps-helper",
        "source": "workspace",
    }
    assert (
        got["maps-helper/backup"]["unit"] == "$" and got["maps-helper/backup"]["spend"] == "log:spend.jsonl"
    )
    code, out = run(capsys, "credits")
    assert code == 0 and "Maps key  (maps-helper/main)  Google Maps, in calls" in out
    assert run(capsys, "check", "maps-helper")[0] == 0


def test_the_persons_own_skills_and_addons_are_read(ws, monkeypatch, tmp_path):
    user = apicredits.user_skill_dirs()[0]
    credit_skill(
        user, "claude-api-credit", one(name="key-1", label="Claude API key 1", provider="Anthropic", unit="$")
    )
    addon = tmp_path / "addon"
    addon.mkdir()
    (addon / "credits.toml").write_text(
        one(name="ocr", label="OCR calls", provider="Example OCR"), encoding="utf-8"
    )
    monkeypatch.setattr(
        apicredits,
        "_addon_manifests",
        lambda root: {"scan": {"dir": addon, "api-credits": "credits.toml"}, "other": {"dir": addon}},
    )
    res = apicredits.declared(ws)
    assert [(c["credit"], c["source"]) for c in res["credits"]] == [
        ("claude-api-credit/key-1", "user"),
        ("scan/ocr", "addon:scan"),
    ]
    assert res["problems"] == []
    assert apicredits.declared(ws, user=False)["credits"][0]["credit"] == "scan/ocr"


def test_a_workspace_skill_hides_the_persons_skill_of_the_same_name(ws):
    credit_skill(ws / ".agents" / "skills", "maps-helper", one(label="Workspace one"))
    credit_skill(apicredits.user_skill_dirs()[0], "maps-helper", one(label="Home one"))
    assert [c["label"] for c in apicredits.declared(ws)["credits"]] == ["Workspace one"]


def test_skills_without_a_declaration_add_nothing(ws, capsys):
    folder = ws / ".agents" / "skills" / "plain"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: plain\ndescription: A plain skill without any API access at all.\n---\n", encoding="utf-8"
    )
    assert apicredits.declared(ws) == {"credits": [], "problems": []}
    code, out = run(capsys, "credits")
    assert code == 0 and "No skill or add-on here declares an API credit." in out


# --- a broken declaration is flagged -----------------------------------------------------------------------

BROKEN = [
    (one(unit="dollars"), "unit is one of"),
    (one(key="Agents/Maps key"), "key says where the key lives"),
    (one(key=FAKE_KEY), "looks like a key value"),
    (one(balance=f"echo {FAKE_KEY}"), "looks like a key value"),
    (one(balance="curl --api-key abcdefghijklmnopqrstuv"), "looks like a key value"),
    (one(label="Maps \x1b[31mkey"), "label is plain text"),
    (one(key="pass:Agents/Maps\x1b[2Jkey"), "key says where the key lives"),
    (one(key="orch:maps\n"), "key says where the key lives"),
    (one(provider=None), "has no provider"),
    (one(name="Main Key"), "name is lowercase"),
    (one(spend="log:../../elsewhere.jsonl"), "spend is"),
    (one(spend="sometimes"), "spend is"),
    (one(colour="blue"), "'colour' is not a credit field"),
    (one(unit=3), "must be text"),
    (one() + one(), "declared twice"),
    ("name = 'x'\n", "is not read"),
    ("", "has no [[credit]] table"),
    ("[[credit]\nname=", "is not valid TOML"),
]


@pytest.mark.parametrize(("toml", "says"), BROKEN)
def test_skill_check_flags_a_broken_declaration(ws, capsys, toml, says):
    credit_skill(ws / ".agents" / "skills", toml=toml)
    code, out = run(capsys, "check", "--json")
    res = json.loads(out)
    assert code == 2 and res["ok"] is False
    found = [f for f in res["findings"] if f["skill"] == "maps-helper"]
    assert found and all(f["level"] == "error" and f["field"].startswith("api-credits") for f in found)
    assert any(says in f["message"] for f in found), found
    assert FAKE_KEY not in out
    # the listing shows the problem and none of that file's credits
    code, out = run(capsys, "credits", "--json")
    res = json.loads(out)
    assert code == 0 and res["credits"] == [] and res["problems"][0]["owner"] == "maps-helper"
    assert FAKE_KEY not in out


@pytest.mark.parametrize(
    ("file", "says"),
    [
        (FAKE_KEY + ".toml", "looks like a key value"),
        ("missing.toml", "there is no such file"),
        ("../outside.toml", "inside the folder"),
        ("", "names no file"),
    ],
)
def test_skill_check_flags_a_declaration_that_names_no_good_file(ws, capsys, file, says):
    credit_skill(ws / ".agents" / "skills", toml=None, file=file)
    (ws / ".agents" / "outside.toml").write_text(GOOD, encoding="utf-8")
    code, out = run(capsys, "check", "maps-helper", "--json")
    assert code == 2 and any(says in f["message"] for f in json.loads(out)["findings"])
    assert FAKE_KEY not in out


def test_check_path_flags_a_skill_folder_outside_the_workspace(ws, capsys, tmp_path):
    folder = credit_skill(tmp_path / "src", toml=one(unit="euro"))
    code, out = run(capsys, "check", "--path", str(folder))
    assert code == 2 and "unit is one of" in out


def test_one_bad_credit_hides_the_whole_file(tmp_path):
    f = tmp_path / "api-credits.toml"
    f.write_text(one() + one(name="second", unit="euro"), encoding="utf-8")
    credits, problems = apicredits.read_file(f)
    assert credits == [] and len(problems) == 1 and "credit 'second'" in problems[0]["message"]


def test_a_key_shaped_name_or_field_is_never_repeated(tmp_path):
    f = tmp_path / "api-credits.toml"
    bare = FAKE_KEY.replace("-", "_")
    f.write_text(one(name=FAKE_KEY) + f'{bare} = "x"\n', encoding="utf-8")
    _, problems = apicredits.read_file(f)
    assert problems and FAKE_KEY not in json.dumps(problems) and bare not in json.dumps(problems)


def test_the_reader_never_opens_the_secret_store(ws, monkeypatch):
    """The key field is where the key lives: nothing resolves it."""
    import subprocess

    from orch import keystore

    def boom(*a, **k):
        raise AssertionError("the credit reader must not read a key or run a program")

    for fn in [n for n in dir(keystore) if not n.startswith("_") and callable(getattr(keystore, n))]:
        monkeypatch.setattr(keystore, fn, boom)
    for fn in ("run", "Popen", "check_output"):  # no pass-cli, no balance command
        monkeypatch.setattr(subprocess, fn, boom)
    credit_skill(ws / ".agents" / "skills", toml=one(key="orch:maps", balance="pass-cli item view x"))
    assert apicredits.declared(ws)["credits"][0]["key"] == "orch:maps"


# --- add-on manifest ---------------------------------------------------------------------------------------

MANIFEST = """schema = "orch.addon/1"
orch_api = 1
name = "scan"
version = "0.1.0"
description = "Reads scanned letters."
run = "orch_scan"
skill = "skills/orch-scan"
api-credits = "{file}"
"""


def test_an_addon_manifest_may_name_its_credits_file(tmp_path):
    sk = tmp_path / "skills" / "orch-scan"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: orch-scan\ndescription: d\n---\n", encoding="utf-8")
    (sk / "AGENTS-block.md").write_text("## orch-scan\n", encoding="utf-8")
    (tmp_path / "api-credits.toml").write_text("not even toml [", encoding="utf-8")
    m = tmp_path / addons.MANIFEST
    m.write_text(MANIFEST.format(file="api-credits.toml"), encoding="utf-8")
    assert (
        addons.parse_manifest(m)["api-credits"] == "api-credits.toml"
    )  # content: apicredits.py, not the add-on
    rows, problems = apicredits._declared_in(tmp_path, "api-credits.toml", "scan", "addon:scan")
    assert rows == [] and "not valid TOML" in problems[0]["message"]
    m.write_text(MANIFEST.format(file="missing.toml"), encoding="utf-8")
    assert addons.parse_manifest(m)["api-credits"] == "missing.toml"  # the add-on stays; the reader says it
    rows, problems = apicredits._declared_in(tmp_path, "missing.toml", "scan", "addon:scan")
    assert rows == [] and "no such file" in problems[0]["message"]
    m.write_text(MANIFEST.format(file="../x.toml"), encoding="utf-8")
    with pytest.raises(Refused):
        addons.parse_manifest(m)


def test_orchs_own_skills_still_pass_with_the_credit_check():
    from test_skillmeta import shipped_skills

    entries = [skillmeta._entry(d.name, d, "orch") for d in shipped_skills()]
    assert apicredits.check(entries) == []

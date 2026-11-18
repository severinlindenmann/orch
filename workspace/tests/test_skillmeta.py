"""ORCH-532: the flat skill header reader, `orch skill check` and `orch skill list | show` (skill format ORCH-531)."""
# ruff: noqa: E501

import json
from pathlib import Path

import pytest

from orch import cli, skillmeta

REPO = Path(__file__).resolve().parents[2]
SHIPPED = ("workspace/skills", "workspace/src/orch/builtin", "workspace-addons")


def skill(base: Path, name: str, header: str, body: str = "# body\n") -> Path:
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\n{header}---\n{body}", encoding="utf-8")
    return folder


GOOD = (
    "name: github\n"
    "description: GitHub operations for the data repos. Use when a pull request is involved.\n"
    "license: proprietary\n"
    "metadata:\n"
    '  platforms: "macos, windows"\n'
    '  requires: "sh"\n'
    "  owner: 'Severin''s team'\n"
    '  status: "draft"   # a comment\n'
    "  routing-table: references/routing.md\n"
)


def errors(folder: Path) -> list[str]:
    return [f["message"] for f in skillmeta.check_skill(folder) if f["level"] == "error"]


# --- reader ------------------------------------------------------------------------------------------------


def test_reads_the_flat_header(tmp_path):
    h = skillmeta.read_header(skill(tmp_path, "github", GOOD))
    assert h == {
        "name": "github",
        "description": "GitHub operations for the data repos. Use when a pull request is involved.",
        "license": "proprietary",
        "metadata": {
            "platforms": "macos, windows",
            "requires": "sh",
            "owner": "Severin's team",
            "status": "draft",
            "routing-table": "references/routing.md",
        },
    }
    assert skillmeta.split_list(h["metadata"]["platforms"]) == ["macos", "windows"]
    assert skillmeta.split_list(" gh, ,git ") == ["gh", "git"] and skillmeta.split_list(None) == []


def test_header_without_metadata_has_an_empty_map(tmp_path):
    h = skillmeta.read_header(skill(tmp_path, "a", 'name: a\ndescription: "say \\"hi\\" # not a comment"\n'))
    assert h == {"name": "a", "description": 'say "hi" # not a comment', "metadata": {}}


def test_crlf_header_reads_the_same(tmp_path):
    folder = tmp_path / "a"
    folder.mkdir()
    (folder / "SKILL.md").write_bytes(
        b"---\r\nname: a\r\ndescription: x\r\nmetadata:\r\n  status: active\r\n---\r\n"
    )
    assert skillmeta.read_header(folder) == {
        "name": "a",
        "description": "x",
        "metadata": {"status": "active"},
    }


@pytest.mark.parametrize(
    "header, says",
    [
        ("name: a\ndescription: x\nmetadata:\n  requires:\n    bins: gh\n", "text value"),
        ("name: a\ndescription: x\nmetadata:\n  a: b\n    c: d\n", "one level"),
        ("name: a\ndescription: >\n  folded\n", "block value"),
        ("name: a\ndescription: x\nmetadata:\n  requires: [gh, git]\n", "commas"),
        ("name: a\ndescription: &d x\n", "anchors"),
        ("name: a\nname: b\ndescription: x\n", "twice"),
        ("name: a\ndescription: x\n  stray: y\n", "indented"),
        ('name: a\ndescription: "open\n', "end"),
    ],
)
def test_refuses_what_it_does_not_read(tmp_path, header, says):
    folder = skill(tmp_path, "a", header)
    with pytest.raises(skillmeta.HeaderError, match=says):
        skillmeta.read_header(folder)
    assert skillmeta.try_header(folder) == {}
    assert [f["field"] for f in skillmeta.check_skill(folder)] == ["header"]


def test_no_header_at_all(tmp_path):
    folder = tmp_path / "a"
    folder.mkdir()
    (folder / "SKILL.md").write_text("# just text\n")
    with pytest.raises(skillmeta.HeaderError, match="---"):
        skillmeta.read_header(folder)
    assert errors(tmp_path / "missing") == ["There is no SKILL.md in this folder."]


# --- check -------------------------------------------------------------------------------------------------


def test_a_good_skill_passes(tmp_path):
    assert skillmeta.check_skill(skill(tmp_path, "github", GOOD)) == []


def test_name_must_match_the_folder_and_the_pattern(tmp_path):
    assert "not the folder name" in errors(skill(tmp_path, "other", GOOD))[0]
    bad = skill(
        tmp_path, "Bad_Name", "name: Bad_Name\ndescription: A skill that does a thing. Use when asked.\n"
    )
    assert "lowercase" in errors(bad)[0]
    assert errors(skill(tmp_path, "n", "description: A skill that does a thing. Use when asked.\n")) == [
        "The header has no name."
    ]


def test_description_present_short_and_not_a_placeholder(tmp_path):
    assert errors(skill(tmp_path, "a", "name: a\n")) == ["The header has no description."]
    assert "too short" in errors(skill(tmp_path, "b", "name: b\ndescription: d\n"))[0]
    assert "at most 1024" in errors(skill(tmp_path, "c", f"name: c\ndescription: {'x' * 1100}\n"))[0]
    long = skillmeta.check_skill(skill(tmp_path, "e", f"name: e\ndescription: {'x' * 700}\n"))
    assert [f["level"] for f in long] == ["warn"]


def test_templated_description_of_an_orch_source_is_not_measured(tmp_path):
    folder = skill(tmp_path, "orch-x", 'name: orch-x\ndescription: "{{description}}"\n')
    assert "too short" in errors(folder)[0]
    (folder / "description.toml").write_text('schema = "orch.skill-description/1"\n')
    assert errors(folder) == []


def test_extra_top_level_field_goes_under_metadata(tmp_path):
    msgs = errors(
        skill(tmp_path, "a", "name: a\ndescription: A skill that does a thing. Use when asked.\nowner: me\n")
    )
    assert msgs == ["'owner' is not a standard header field; move it under metadata."]


def test_metadata_values_must_be_text(tmp_path):
    h = 'name: a\ndescription: A skill that does a thing. Use when asked.\nmetadata:\n  version: 1.2\n  ok: "1.3"\n'
    h += "  review-by: 2027-03-01\n  beta: yes\n"
    fields = sorted(f["field"] for f in skillmeta.check_skill(skill(tmp_path, "a", h)))
    assert fields == ["metadata.beta", "metadata.review-by", "metadata.version"]


def test_status_and_platform_words(tmp_path):
    base = "name: a\ndescription: A skill that does a thing. Use when asked.\nmetadata:\n"
    assert "Unknown status" in errors(skill(tmp_path / "1", "a", base + "  status: old\n"))[0]
    assert "Unknown platform" in errors(skill(tmp_path / "2", "a", base + '  platforms: "macos, beos"\n'))[0]
    alias = skillmeta.check_skill(skill(tmp_path / "3", "a", base + "  platforms: mac\n"))
    assert [(f["level"], f["message"]) for f in alias] == [("warn", "Write 'macos' instead of 'mac'.")]
    retired = skillmeta.check_skill(skill(tmp_path / "4", "a", base + "  status: retired\n"))
    assert [f["field"] for f in retired] == ["metadata.replaced-by"]


def test_missing_program_is_a_note_not_a_problem(tmp_path, monkeypatch):
    monkeypatch.setitem(
        __import__("sys").modules, "orch.skillready", None
    )  # the fallback, whatever is merged
    h = 'name: a\ndescription: A skill that does a thing. Use when asked.\nmetadata:\n  requires: "sh, no-such-tool-532"\n'
    found = skillmeta.check_skill(skill(tmp_path, "a", h))
    assert [(f["level"], f["message"]) for f in found] == [
        ("warn", "Not ready here: no-such-tool-532 missing.")
    ]


def test_checks_over_all_skills_can_be_added(tmp_path, monkeypatch):
    entry = skillmeta._entry("github", skill(tmp_path, "github", GOOD), "workspace")
    monkeypatch.setattr(
        skillmeta, "CHECKS", [lambda es, root: [skillmeta._finding(es[0]["name"], "warn", "x", "seen")]]
    )
    assert skillmeta.check_all([entry]) == [
        {"skill": "github", "level": "warn", "field": "x", "message": "seen"}
    ]


# --- orch's own skills (this is what runs in CI) -----------------------------------------------------------


def shipped_skills() -> list[Path]:
    return sorted(p.parent for base in SHIPPED for p in (REPO / base).rglob("SKILL.md"))


def test_orchs_own_skills_pass_the_check():
    folders = shipped_skills()
    assert len(folders) >= 15
    problems = [f for d in folders for f in skillmeta.check_skill(d) if f["level"] == "error"]
    assert problems == []


def test_orchs_own_skills_carry_the_default_fields():
    for d in shipped_skills():
        meta = skillmeta.read_header(d)["metadata"]
        assert meta.get("owner") == "orch" and meta.get("status") == "active", d


# --- the commands ------------------------------------------------------------------------------------------


def workspace(proj: Path) -> Path:
    skill(
        proj / ".orch/harness/skills",
        "orch",
        "name: orch\ndescription: Track work as tickets. Use when you start.\n",
    )
    skill(proj / ".orch/harness/skills", "orch-hello", "name: orch-hello\ndescription: d\n")
    (proj / ".orch/addons.json").write_text(json.dumps({"active": {"hello": {"version": "0.1.0"}}}))
    skill(proj / ".agents/skills", "github", GOOD)
    shared = skill(
        proj / ".agents/skills", "shared-one", "name: shared-one\ndescription: x\nmetadata:\n  a:\n"
    )
    (shared / ".orch-shared").write_text("")
    return proj


def run(capsys, *argv) -> tuple[int, str]:
    try:
        code = cli.main(["skill", *argv])
    except SystemExit as e:
        code = e.code
    return code or 0, capsys.readouterr().out


def test_skill_list_json_shows_the_parsed_header(proj, capsys):
    workspace(proj)
    code, out = run(capsys, "list", "--json")
    got = {e["name"]: e for e in json.loads(out)}
    assert code == 0 and list(got) == ["orch", "orch-hello", "github", "shared-one"]
    assert [got[n]["source"] for n in got] == ["orch", "addon:hello", "workspace", "relay"]
    assert got["github"]["header"]["metadata"]["status"] == "draft" and got["github"]["error"] is None
    assert got["shared-one"]["header"] is None and "text value" in got["shared-one"]["error"]


def test_skill_check_exit_2_and_names_the_broken_ones(proj, capsys):
    workspace(proj)
    code, out = run(capsys, "check", "--json")
    res = json.loads(out)
    assert code == 2 and res["ok"] is False
    assert sorted({f["skill"] for f in res["findings"] if f["level"] == "error"}) == [
        "orch-hello",
        "shared-one",
    ]
    code, out = run(capsys, "check", "orch", "github")
    assert code == 0 and "All 2 skills pass." in out
    assert run(capsys, "check", "nope")[0] == 2


def test_skill_check_path_and_show(proj, capsys):
    folder = skill(proj / "src", "github", GOOD)
    code, out = run(capsys, "check", "--path", str(folder / "SKILL.md"))
    assert code == 0 and "All 1 skills pass." in out
    workspace(proj)
    code, out = run(capsys, "show", "orch-hello", "--json")
    res = json.loads(out)
    assert code == 0 and res["source"] == "addon:hello" and res["findings"][0]["field"] == "description"
    assert run(capsys, "show", "nope")[0] == 2

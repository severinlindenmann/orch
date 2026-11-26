"""`orch skill` (cli_skill.py): list, show, check, credits, review-due in a temp workspace."""

import json

from orch import cli

GOOD = "name: mine\ndescription: Does one thing. Use when asked.\nlicense: proprietary\n"


def _ws(proj, header=GOOD, name="mine"):
    (proj / ".orch").mkdir(exist_ok=True)
    d = proj / ".agents" / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\n{header}---\n# body\n", encoding="utf-8")
    return d


def _run(capsys, *argv):
    try:
        code = cli.main(["skill", *argv])
    except SystemExit as e:
        code = e.code
    cap = capsys.readouterr()
    return code or 0, cap.out, cap.err


def test_list_and_show_text_and_json(proj, capsys):
    _ws(proj)
    code, out, _ = _run(capsys, "list")
    assert code == 0 and "mine  (workspace)" in out
    code, out, _ = _run(capsys, "show", "mine")
    assert code == 0 and "Does one thing." in out and "All 1 skills pass." in out
    code, out, _ = _run(capsys, "show", "mine", "--json")
    assert json.loads(out)["name"] == "mine"


def test_unknown_skill_error_names_the_next_command(proj, capsys):
    _ws(proj)
    for argv in (("show", "nope"), ("check", "nope")):
        code, _, err = _run(capsys, *argv)
        assert code != 0 and "orch skill list" in err


def test_check_path_must_be_a_skill_folder(proj, capsys):
    code, _, err = _run(capsys, "check", "--path", str(proj / "missing"))
    assert code != 0 and "Give the folder that holds SKILL.md" in err


def test_broken_header_text_asks_for_a_fix_and_json_exits_2(proj, capsys):
    _ws(proj, header="name: mine\n")
    code, out, err = _run(capsys, "check")
    assert code != 0 and "Skill headers to fix: mine" in err and "problem" in out
    code, out, _ = _run(capsys, "check", "--json")
    assert code == 2 and json.loads(out)["ok"] is False


def test_credits_and_review_due_without_anything_declared(proj, capsys):
    _ws(proj)
    code, out, _ = _run(capsys, "credits")
    assert code == 0 and "No skill or add-on here declares an API credit." in out
    code, out, _ = _run(capsys, "credits", "--json")
    assert code == 0 and json.loads(out)["credits"] == []
    code, out, _ = _run(capsys, "review-due", "--dry-run", "--json")
    assert code == 0 and isinstance(json.loads(out), dict)

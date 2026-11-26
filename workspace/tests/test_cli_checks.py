"""cli_checks.py: `orch checks` in an isolated workspace (success, errors, --json)."""

import json

from test_checkfiles import databricks  # noqa: F401  (fixture)

from orch import checkfiles, cli_checks


def test_list_json_before_and_after_init(proj, run, databricks):  # noqa: F811
    assert run("init")[0] == 0
    code, out, _ = run("checks", "list", "--json")
    doc = json.loads(out)
    assert code == 0 and doc["checks"] == []
    assert run("checks", "init")[0] == 0
    code, out, _ = run("checks", "list")
    assert code == 0 and "No checks yet. Add one: orch checks templates" in out
    assert json.loads(run("checks", "list", "--json")[1])["present"] is True


def test_no_action_means_list(proj, run, databricks):  # noqa: F811
    run("init")
    assert run("checks")[1].splitlines()[0] == run("checks", "list")[1].splitlines()[0]


def test_templates_json_names_the_profile_flag(proj, run, databricks):  # noqa: F811
    run("init")
    code, out, _ = run("checks", "templates", "--json")
    by = {t["name"]: t for t in json.loads(out)["templates"]}
    assert code == 0 and by["databricks"]["profile"] is True


def test_add_json_approve_run_remove(proj, run, databricks):  # noqa: F811
    run("init")
    run("checks", "init")
    code, out, err = run("checks", "add", "databricks", "--profile", "dev", "--json")
    assert code == 0, err
    added = json.loads(out)["added"]
    code, out, _ = run("checks", "run", added, "--json")
    assert code == 0 and [x["name"] for x in json.loads(out)["items"]] == [added]
    rows = {x["name"]: x for x in json.loads(run("checks", "list", "--json")[1])["checks"]}
    assert rows[added]["status"] == "approved" and rows[added]["state"]
    code, out, _ = run("checks", "remove", added, "--json")
    assert code == 0 and json.loads(out) == {"removed": added}
    assert not (checkfiles.folder(proj) / f"{added}.json").exists()


def test_unknown_names_are_refused_with_the_next_step(proj, run, databricks):  # noqa: F811
    run("init")
    run("checks", "init")
    for action in ("remove", "run"):
        code, _, err = run("checks", action, "nope")
        assert code == 2 and "There is no check called nope. See them with: orch checks list" in err


def test_add_unknown_template_and_duplicate_are_refused(proj, run, databricks):  # noqa: F811
    run("init")
    run("checks", "init")
    assert run("checks", "add", "no-such-tool")[0] == 2
    assert run("checks", "add", "databricks", "--profile", "dev")[0] == 0
    code, _, err = run("checks", "add", "databricks", "--profile", "dev")
    assert code == 2 and "orch checks remove databricks-dev" in err


def test_approve_unknown_check_is_refused(proj, run, databricks):  # noqa: F811
    run("init")
    run("checks", "init")
    code, _, err = run("checks", "approve", "ghost")
    assert code == 2 and err.strip()


def test_run_with_nothing_set_up_says_so(proj, run, databricks):  # noqa: F811
    run("init")
    code, out, _ = run("checks", "run")
    assert code == 0 and out.strip()


def test_dispatch_ignores_other_commands():
    assert cli_checks.dispatch(type("A", (), {"cmd": "status"})(), None) is False


def test_when_formats_utc_and_never():
    assert cli_checks._when("2026-01-02T03:04:05Z") == "2026-01-02 03:04:05 UTC"
    assert cli_checks._when(None) == "never"

"""The group set of scripts/ci_light.py --group: the before-merge checks of a merge queue group run on this
computer (ORCH-1177, part of the queue's local check ORCH-1123)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADDONS_YML = (ROOT / ".github" / "workflows" / "addons.yml").read_text(encoding="utf-8")


def _load():
    spec = importlib.util.spec_from_file_location("ci_light_group", ROOT / "scripts" / "ci_light.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


light = _load()
ADDONS = {"dashboard": 8, "sync": 8, "pull-requests": 2, "factory": 2}
TEXT_CHECKS = ["banned words", "style rules", "CI time limits", "headless launch", "Windows paths"]


def names(steps):
    return [s["name"] for s in steps]


def by_name(steps):
    return {s["name"]: s for s in steps}


def test_a_group_that_changes_only_docs_runs_every_check_but_no_add_on_suite():
    steps = light.group_plan(["docs/x.md"], ADDONS, "origin/develop")
    assert names(steps) == [
        *TEXT_CHECKS,
        "brand wording and tokens",
        "contracts",
        "workspace: ruff",
        "add-on dashboard: ruff",
        "add-on factory: ruff",
        "add-on pull-requests: ruff",
        "add-on sync: ruff",
        "workspace: tests (not slow)",
    ]


def test_ruff_checks_and_format_checks_the_workspace_and_every_add_on():
    steps = by_name(light.group_plan([], ADDONS, "origin/develop"))
    want = [("workspace: ruff", "workspace")] + [(f"add-on {a}: ruff", f"workspace-addons/{a}") for a in ADDONS]
    for name, cwd in want:
        assert steps[name]["cwd"] == cwd
        assert "uv run ruff check ." in steps[name]["cmd"] and "uv run ruff format --check ." in steps[name]["cmd"]


def test_the_text_checks_run_their_scripts_and_banned_words_reads_the_group_base():
    steps = by_name(light.group_plan([], ADDONS, "abc123"))
    assert steps["banned words"]["cmd"] == "python3 scripts/check_banned_words.py --base abc123"
    for name, script in zip(
        TEXT_CHECKS[1:],
        ["check_style", "check_ci_timeouts", "check_headless_launch", "check_windows_paths"],
        strict=True,
    ):
        assert steps[name]["cmd"] == f"python3 scripts/{script}.py"
        assert (ROOT / "scripts" / f"{script}.py").is_file()


def test_the_labels_go_to_banned_words_like_rules_yml_passes_them():
    steps = by_name(light.group_plan([], ADDONS, "b", "owner-approved,x y"))
    assert (
        steps["banned words"]["cmd"] == "python3 scripts/check_banned_words.py --base b --labels 'owner-approved,x y'"
    )


def test_the_base_is_quoted_for_the_shell():
    steps = by_name(light.group_plan([], ADDONS, "x; rm -rf y"))
    assert steps["banned words"]["cmd"].endswith("--base 'x; rm -rf y'")


def test_brand_wording_and_contracts_run_what_ci_runs():
    steps = by_name(light.group_plan([], ADDONS, "b"))
    assert steps["brand wording and tokens"]["cmd"].endswith("pytest -q -p no:cacheprovider brand/tests")
    assert steps["contracts"]["cmd"].endswith("python contracts/validate.py")
    assert "--with jsonschema" in steps["contracts"]["cmd"]


def test_workspace_tests_are_the_not_slow_ones_on_at_most_8_workers():
    cmd = by_name(light.group_plan([], ADDONS, "b"))["workspace: tests (not slow)"]["cmd"]
    assert light.WORKERS == 8
    assert cmd == 'uv run pytest -q -n 8 -m "not slow"'


def test_only_the_add_ons_the_group_touched_run_their_suite_on_ci_s_worker_count():
    steps = light.group_plan(
        ["workspace-addons/sync/src/x.py", "workspace-addons/pull-requests/tests/test_y.py"], ADDONS, "b"
    )
    suites = {s["name"]: s["cmd"] for s in steps if s["name"].endswith(": tests")}
    assert suites == {
        "add-on pull-requests: tests": "uv run pytest -q -n 2",
        "add-on sync: tests": "uv run pytest -q -n 8",
    }
    assert names(steps)[-2:] == ["add-on pull-requests: tests", "add-on sync: tests"]  # suites come last


def test_an_add_on_ci_does_not_check_is_never_planned():
    steps = light.group_plan(["workspace-addons/personal/src/x.py"], ADDONS, "b")
    assert not any("personal" in n for n in names(steps))


def test_the_page_library_runs_the_dashboard_suite_with_its_node_tests():
    steps = by_name(light.group_plan(["workspace/src/orch_ui/static/x.css"], ADDONS, "b"))
    cmd = steps["add-on dashboard: tests"]["cmd"]
    assert "node --test tests/*.test.js ../../workspace/src/orch_ui/tests/*.test.mjs" in cmd
    assert cmd.endswith("uv run pytest -q -n 8")


def test_the_shared_add_on_test_guard_runs_every_add_on_suite():
    steps = light.group_plan(["workspace-addons/_orch_test_guard.py"], ADDONS, "b")
    assert sorted(n for n in names(steps) if n.endswith(": tests")) == [f"add-on {a}: tests" for a in sorted(ADDONS)]


def test_ci_addons_reads_every_add_on_job_and_caps_its_workers():
    text = (
        "jobs:\n  a:\n    defaults:\n      run:\n        working-directory: workspace-addons/a\n"
        "    steps:\n      - run: uv run pytest -q -n auto\n"
        "  b:\n    defaults:\n      run:\n        working-directory: workspace-addons/b\n"
        "    steps:\n      - run: uv run pytest -q -n 2\n"
        "  c:\n    defaults:\n      run:\n        working-directory: workspace-addons/c\n"
        "    steps:\n      - run: uv run pytest -q -n 16\n"
        "  scan:\n    steps:\n      - run: uv run pytest -q -n 4\n"
    )
    assert light.ci_addons(text) == {"a": 8, "b": 2, "c": 8}


def test_ci_addons_finds_the_real_add_on_jobs_and_each_is_a_folder():
    got = light.ci_addons(ADDONS_YML)
    assert {"dashboard", "sync", "pull-requests", "services"} <= set(got)
    assert all((ROOT / "workspace-addons" / a / "pyproject.toml").is_file() for a in got)
    assert all(1 <= n <= light.WORKERS for n in got.values())


def test_every_planned_step_folder_exists():
    for s in light.group_plan(["workspace-addons/_orch_test_guard.py"], light.ci_addons(ADDONS_YML), "b"):
        assert (ROOT / s["cwd"]).is_dir(), s


def _steps(*codes):
    return [{"name": f"s{i}", "cwd": ".", "cmd": f"exit {c}"} for i, c in enumerate(codes)]


def test_it_stops_at_the_first_red_with_one_fail_line(tmp_path):
    lines: list[str] = []
    failed = tmp_path / "failed.txt"
    env = {"PATH": "/usr/bin:/bin", "ORCH_CHECK_FAILED": str(failed)}
    assert light.run_group(_steps(0, 3, 0), env, out=lines.append) == 1
    assert [x for x in lines if x.startswith("== ")] == [lines[0], lines[1]]  # s2 never started
    assert lines[-1].startswith("local check: FAIL at s1 (step 2 of 3, exit 3,")
    assert sum(x.startswith("local check:") for x in lines) == 1
    assert failed.read_text(encoding="utf-8") == "s1\n"


def test_all_green_ends_with_one_pass_line():
    lines: list[str] = []
    assert light.run_group(_steps(0, 0), {"PATH": "/usr/bin:/bin"}, out=lines.append) == 0
    assert lines[-1].startswith("local check: PASS (2 steps,")
    assert sum(x.startswith("local check:") for x in lines) == 1


def test_group_plan_prints_json_and_runs_nothing(capsys, monkeypatch):
    monkeypatch.setattr(light, "changed", lambda base: ["workspace-addons/sync/x.py"])
    monkeypatch.setattr(light.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    assert light.main(["--base", "b", "--group", "--plan"]) == 0
    out = capsys.readouterr().out
    assert '"add-on sync: tests"' in out and '"workspace: tests (not slow)"' in out

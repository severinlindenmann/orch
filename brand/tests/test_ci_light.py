"""The light check set of a pull request and the proven develop push (ORCH-545, scripts/ci_light.py, ci_proven.py)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


light = _load("ci_light")
proven = _load("ci_proven")

TEXTS = {
    "test_store.py": "from orch import store\n",
    "test_tickets.py": "import orch.tickets\nfrom orch import store, tickets\n",
    "test_cli.py": "from orch.cli import main\n",
    "test_storey.py": "from orch import storeyard\n",
    "test_rest.py": "x" * 10_000,  # the rest of the suite: a few picked files stay under one part
}
ADDONS = {"dashboard", "sync", "pull-requests"}


def names(steps):
    return [s["name"] for s in steps]


def test_words_and_style_always_run():
    steps = light.plan(["docs/x.md"], TEXTS, ADDONS)
    assert names(steps) == ["brand: words, tokens, CI time limits", "style rules"]


def test_a_workspace_or_addon_change_checks_the_generated_files():
    for f in ("workspace/src/orch/store.py", "workspace-addons/sync/src/orch_sync/orch-addon.toml"):
        steps = light.plan([f], TEXTS, ADDONS)
        assert "generated files are current (shipped_addons.json)" in names(steps)
    assert "generated files are current (shipped_addons.json)" not in names(light.plan(["docs/x.md"], TEXTS, ADDONS))


def test_a_changed_module_runs_the_tests_that_import_it_and_no_others():
    steps = light.plan(["workspace/src/orch/store.py"], TEXTS, ADDONS)
    cmd = steps[-1]["cmd"]
    assert "tests/test_store.py" in cmd and "tests/test_tickets.py" in cmd
    assert "test_storey.py" not in cmd and "test_cli.py" not in cmd  # a longer name is another module
    assert "--part" not in cmd


def test_a_multiline_import_counts():
    texts = {"test_m.py": "from orch import (\n    other,\n    store,\n)\n", "test_rest.py": "x" * 10_000}
    assert light.pick_tests(["workspace/src/orch/store.py"], texts) == (["test_m.py"], False)


def test_a_module_in_a_sub_package_runs_the_sample():
    assert light.pick_tests(["workspace/src/orch/sub/helper.py"], TEXTS) == ([], True)


def test_a_changed_test_file_runs_itself():
    tests, broad = light.pick_tests(["workspace/tests/test_cli.py"], TEXTS)
    assert tests == ["test_cli.py"] and not broad


def test_shared_test_code_runs_the_sample():
    for f in ("workspace/tests/conftest.py", "workspace/pyproject.toml", "workspace/uv.lock"):
        steps = light.plan([f], TEXTS, ADDONS)
        assert f"--part 1/{light.BROAD_PARTS}" in steps[-1]["cmd"], f


def test_a_module_no_test_imports_runs_the_sample():
    tests, broad = light.pick_tests(["workspace/src/orch/nobodyreads.py"], TEXTS)
    assert broad and tests == []


def test_test_files_bigger_than_one_part_run_the_sample():
    texts = {"test_big.py": "from orch import big\n" + "x" * 1000, "test_rest.py": "y" * 1000}
    assert light.pick_tests(["workspace/src/orch/big.py"], texts) == ([], True)
    texts["test_rest.py"] = "y" * 10_000
    assert light.pick_tests(["workspace/src/orch/big.py"], texts) == (["test_big.py"], False)


def test_a_changed_addon_runs_its_own_suite_only():
    steps = light.plan(["workspace-addons/sync/src/orch_sync/x.py"], TEXTS, ADDONS)
    assert names(steps)[-1] == "add-on sync"
    assert steps[-1]["cwd"] == "workspace-addons/sync"
    assert not any("workspace:" in n for n in names(steps))


SKILL = "workspace-addons/sync/src/orch_sync/skills/orch-sync/SKILL.md"
ADDON_TEXTS = {
    "sync": {"test_package.py": "x = 'skills/orch-sync/SKILL.md'\n", "test_cli.py": "from orch_sync import cli\n"},
    "dashboard": {"test_views.py": "pass\n"},
}


def test_an_addon_skill_text_change_runs_only_its_tests_that_read_skills():
    steps = light.plan([SKILL], TEXTS, ADDONS, ADDON_TEXTS)
    step = steps[-1]
    assert step["cwd"] == "workspace-addons/sync"
    assert step["name"].startswith("add-on sync: 1 test file(s) that read the skills")
    assert "tests/test_package.py" in step["cmd"] and "test_cli.py" not in step["cmd"]


def test_an_addon_skill_change_with_no_test_reading_skills_runs_no_addon_step():
    f = "workspace-addons/dashboard/src/orch_dashboard/skills/orch-dashboard/SKILL.md"
    assert not any(n.startswith("add-on") for n in names(light.plan([f], TEXTS, ADDONS, ADDON_TEXTS)))


def test_an_addon_skill_and_code_change_runs_the_whole_suite():
    steps = light.plan([SKILL, "workspace-addons/sync/src/orch_sync/x.py"], TEXTS, ADDONS, ADDON_TEXTS)
    assert names(steps)[-1] == "add-on sync"


def test_a_page_library_change_with_a_dashboard_skill_change_runs_the_whole_dashboard_suite():
    f = "workspace-addons/dashboard/src/orch_dashboard/skills/orch-dashboard/SKILL.md"
    steps = light.plan([f, "workspace/src/orch_ui/static/x.js"], TEXTS, ADDONS, ADDON_TEXTS)
    assert "add-on dashboard" in names(steps)


def test_a_focus_or_insights_skill_change_starts_no_browser():
    for name in ("focus", "insights"):
        f = f"workspace-addons/{name}/src/orch_{name}/skills/orch-{name}/SKILL.md"
        assert not any("browser" in n or "Chromium" in n for n in names(light.plan([f], TEXTS, ADDONS, ADDON_TEXTS)))
    page = "workspace-addons/focus/src/orch_focus/web/app.js"
    assert "Focus and Insights pages load in a browser" in names(light.plan([page], TEXTS, ADDONS, ADDON_TEXTS))


def test_without_addon_texts_a_skill_change_runs_the_whole_suite():
    assert names(light.plan([SKILL], TEXTS, ADDONS))[-1] == "add-on sync"


def test_addon_test_texts_reads_every_known_addon():
    texts = light.addon_test_texts({"sync"})
    assert texts["sync"] and all(k.startswith("test_") or "/test_" in k for k in texts["sync"])


def test_rule_tests_over_the_whole_tree_run_on_workspace_and_addon_changes():
    for f in ("workspace/src/orch/store.py", "workspace-addons/sync/src/orch_sync/x.py", "workspace/README.md"):
        steps = light.plan([f], TEXTS, ADDONS)
        rules = next(s for s in steps if s["name"] == "rule tests over the whole tree")
        assert rules["cwd"] == "workspace"
        for t in light.RULE_TESTS:
            assert f"tests/{t}" in rules["cmd"], (f, t)
    assert "rule tests over the whole tree" not in names(light.plan(["docs/x.md"], TEXTS, ADDONS))


def test_a_rule_test_is_not_run_twice():
    texts = {**TEXTS, "test_cli_seams.py": "from orch import store\n"}
    steps = light.plan(["workspace/src/orch/store.py"], texts, ADDONS)
    assert "test_cli_seams.py" not in steps[-1]["cmd"]
    assert "tests/test_store.py" in steps[-1]["cmd"]


def test_every_rule_test_exists():
    have = {p.name for p in (ROOT / "workspace" / "tests").glob("test_*.py")}
    assert set(light.RULE_TESTS) <= have


def test_every_rule_node_exists():
    for node in light.RULE_NODES:
        f, name = node.split("::")
        assert f"def {name}(" in (ROOT / "workspace" / "tests" / f).read_text(encoding="utf-8"), node


def test_a_new_rule_test_runs_by_its_name_alone():
    """Owner 19 Nov: test_spawn_argv and others were never on the hand list, so their red reached queue groups."""
    texts = {**TEXTS, "test_spawn_argv.py": "", "test_no_new_thing.py": "", "test_words_lint.py": "",
             "test_relay_secret_scan.py": "", "test_secret_scan_doors.py": "", "test_storage.py": ""}  # fmt: skip
    got = light.rule_tests(texts)
    for t in (
        "test_spawn_argv.py",
        "test_no_new_thing.py",
        "test_words_lint.py",
        "test_secret_scan_doors.py",
    ):
        assert t in got
    assert "test_relay_secret_scan.py" not in got and "test_storage.py" not in got
    assert list(light.RULE_TESTS) == got[: len(light.RULE_TESTS)]
    assert light.RULE_NODES[0] in got
    rules = next(s for s in light.plan(["workspace-addons/sync/x.py"], texts, ADDONS) if s["name"].startswith("rule"))
    assert "tests/test_spawn_argv.py" in rules["cmd"] and f"tests/{light.RULE_NODES[0]}" in rules["cmd"]


def test_the_real_tree_runs_spawn_argv_and_history_lint():
    got = light.rule_tests(light.test_texts())
    assert {
        "test_spawn_argv.py",
        "test_history_lint.py",
        "test_core_names_no_addon.py",
        "test_skills_lint.py",
    } <= set(got)


def test_a_changed_click_through_runs_itself_in_a_browser():
    f = "workspace-addons/dashboard/clickthrough/features/f-links.cjs"
    steps = light.plan([f], TEXTS, ADDONS)
    assert "headless Chromium for the page tests" in names(steps)
    click = next(s for s in steps if s["name"].startswith("dashboard: the 1 click-through"))
    assert click["cmd"].endswith("run.cjs --only f-links")
    assert names(steps).index("headless Chromium for the page tests") < names(steps).index(click["name"])
    gone = "workspace-addons/dashboard/clickthrough/features/zz-deleted.cjs"
    assert not any(n.startswith("dashboard: the") for n in names(light.plan([gone], TEXTS, ADDONS)))


def test_a_focus_or_insights_change_loads_their_pages():
    for f in (
        "workspace-addons/focus/src/x.py",
        "workspace-addons/insights/web/a.js",
        "e2e/focus_insights_smoke.cjs",
    ):
        assert "Focus and Insights pages load in a browser" in names(light.plan([f], TEXTS, ADDONS)), f
    steps = light.plan(["workspace/src/orch/store.py"], TEXTS, ADDONS)
    assert "headless Chromium for the page tests" not in names(steps)


def test_the_browser_version_is_the_page_jobs_one():
    addons = (ROOT / ".github" / "workflows" / "addons.yml").read_text(encoding="utf-8")
    assert f"playwright@{light.PLAYWRIGHT}" in addons


def test_rules_mode_runs_only_the_whole_tree_checks_whatever_changed():
    steps = light.rules_plan(TEXTS)
    assert names(steps) == [
        "brand: words, tokens, CI time limits",
        "style rules",
        "generated files are current (shipped_addons.json)",
        "workspace: ruff",
        "rule tests over the whole tree",
    ]
    assert steps[-1]["cmd"].startswith("ORCH_TEST_GUARD=warn uv run pytest")
    light_rules = next(s for s in light.plan(["workspace/x.md"], TEXTS, ADDONS) if s["name"].startswith("rule"))
    assert "ORCH_TEST_GUARD" not in light_rules["cmd"]  # CI keeps the hard guard


def test_the_page_library_runs_the_dashboard_suite():
    steps = light.plan(["workspace/src/orch_ui/static/widgets.js"], TEXTS, ADDONS)
    assert "add-on dashboard" in names(steps)
    dash = next(s for s in steps if s["name"] == "add-on dashboard")
    assert "orch_ui/tests" in dash["cmd"]


def test_test_file_names_are_quoted_for_the_shell():
    texts = {"test_a b.py": "from orch import store\n", "test_rest.py": "x" * 10_000}
    steps = light.plan(["workspace/src/orch/store.py"], texts, ADDONS)
    assert "'tests/test_a b.py'" in steps[-1]["cmd"]


def test_every_addon_light_runs_exists_as_a_folder():
    assert {"dashboard", "sync", "pull-requests"} <= light.addons_known()


# -- proven develop push ---------------------------------------------------------------------------------------
GREEN = {
    "name": "ci",
    "event": "pull_request",
    "head_branch": "orch-queue/develop-1-abc",
    "status": "completed",
    "conclusion": "success",
}


def test_same_files_as_a_green_queue_group_is_proven():
    ok, _ = proven.decide(["p1", "p2"], "T", "T", [GREEN])
    assert ok


def test_not_proven_without_a_merge_commit_same_files_or_a_green_group_run():
    assert not proven.decide(["p1"], "T", "", [GREEN])[0]
    assert not proven.decide(["p1", "p2"], "T", "U", [GREEN])[0]
    assert not proven.decide(["p1", "p2"], "T", "T", [dict(GREEN, conclusion="failure")])[0]
    assert not proven.decide(["p1", "p2"], "T", "T", [dict(GREEN, head_branch="feat/x")])[0]  # its own light run
    assert not proven.decide(["p1", "p2"], "T", "T", [dict(GREEN, name="rules")])[0]
    assert not proven.decide(["p1", "p2"], "T", "T", [dict(GREEN, event="workflow_dispatch")])[0]
    assert not proven.decide(["p1", "p2"], "T", "T", [])[0]


# -- ci.yml wiring ---------------------------------------------------------------------------------------------
def _job_if(job: str) -> str:
    m = re.search(rf"^  {re.escape(job)}:\n(?:    .*\n|\s*\n)*?    if: (.*)$", CI, re.MULTILINE)
    assert m, job
    return m.group(1)


def test_the_full_suite_leaves_light_pull_requests_and_runs_on_every_queue_group():
    for job in ("addons", "clock", "brand"):
        cond = _job_if(job)
        assert "outputs.light != 'true'" in cond, job
        assert "outputs.queue == 'true'" in cond, job
    for job in ("cli-smoke", "e2e-smoke", "contracts"):
        assert "outputs.queue == 'true'" in _job_if(job), job
    ws = _job_if("workspace")
    assert "outputs.light != 'true'" in ws and "outputs.queue == 'true'" in ws


def test_a_proven_develop_push_runs_no_suite():
    for job in ("clock", "brand", "contracts", "publish", "relay"):  # mobile: see the phone build test below
        assert "outputs.proven != 'true'" in _job_if(job), job
    # for now (ORCH-1106) a proven push still calls these two for the click-throughs and the Windows parts only,
    # which queue groups skip; their other suites stay off (brand/tests/test_ci_queue_skip.py)
    assert _job_if("addons").startswith("needs.changes.outputs.proven == 'true' ||")
    # workspace: not when the Windows parts run on our own Windows VM (ORCH-1127, test_winvm_windows.py)
    assert _job_if("workspace").startswith(
        "(needs.changes.outputs.proven != 'true' || vars.WINDOWS_RUNNER != 'winvm') && (needs.changes.outputs.proven == 'true' ||"
    )


def test_the_phone_build_is_not_in_queue_groups_and_runs_on_develop_even_when_proven():
    """ORCH-1118, owner yes on 20 Nov: 21 min in 47 percent of groups. A green group no longer proves the phone
    app, so a develop push that changes it runs the full suite; nightly and release pull requests keep it."""
    cond = _job_if("mobile")
    assert "needs.changes.outputs.queue != 'true'" in cond and "proven" not in cond
    assert "github.event_name == 'schedule'" in cond and "needs.changes.outputs.mobile == 'true'" in cond


def test_queue_groups_take_no_dashboard_pictures():
    assert "needs.changes.outputs.queue != 'true'" in _job_if("dash-shots")


def test_the_light_job_runs_only_on_light_pull_requests_and_the_final_check_waits_for_it():
    assert _job_if("light") == "needs.changes.outputs.light == 'true'"
    assert re.search(r"needs: \[changes, light,", CI)
    assert "scripts/ci_light.py" in CI and "scripts/ci_proven.py" in CI


def test_steps_use_uv_s_own_python_not_the_shared_tool_folder_one():
    """#1566: the setup-python interpreter lives in a group-writable folder; orch secret exec refuses it."""
    env = light.step_env({"PATH": "/opt/hostedtoolcache/Python/3.12/x64/bin:/usr/bin"})
    assert env["UV_PYTHON_PREFERENCE"] == "only-managed" and env["PATH"].startswith("/opt/hostedtoolcache")

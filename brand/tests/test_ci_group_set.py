"""The group set of scripts/ci_light.py --group: the before-merge checks of a merge queue group run on this
computer (ORCH-1177, part of the queue's local check ORCH-1123)."""

from __future__ import annotations

import importlib.util
import re
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


def test_a_group_that_touches_the_workspace_or_an_add_on_checks_the_generated_files():
    for f in ("workspace/src/orch/x.py", "workspace-addons/sync/x.py"):
        steps = names(light.group_plan([f], ADDONS, "b"))
        assert steps.index(light.GENERATED["name"]) == steps.index("contracts") + 1
    assert light.GENERATED["name"] not in names(light.group_plan(["docs/x.md"], ADDONS, "b"))


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
    in_order = [s["name"] for s in steps if not s.get("background")]  # the smokes run next to the others
    assert in_order[-2:] == ["add-on pull-requests: tests", "add-on sync: tests"]  # suites come last


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


def test_a_marker_that_cannot_be_written_still_ends_with_the_fail_line(tmp_path):
    lines: list[str] = []
    env = {"PATH": "/usr/bin:/bin", "ORCH_CHECK_FAILED": str(tmp_path / "missing" / "failed.txt")}
    assert light.run_group(_steps(4), env, out=lines.append) == 1
    assert lines[-1].startswith("local check: FAIL at s0 (step 1 of 1, exit 4,")


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
    assert '"add-on sync: tests"' in out and '"workspace: rule tests over the whole tree"' in out



def test_the_merge_queue_hands_the_group_labels_over_in_its_environment(capsys, monkeypatch):
    """ORCH-1363: the local check sets ORCH_CHECK_LABELS; --labels still wins when given."""
    monkeypatch.setattr(light, "changed", lambda base: [])
    monkeypatch.setenv("ORCH_CHECK_LABELS", "owner-approved")
    assert light.main(["--base", "b", "--group", "--plan"]) == 0
    assert "--labels owner-approved" in capsys.readouterr().out
    assert light.main(["--base", "b", "--group", "--plan", "--labels", "x"]) == 0
    assert "--labels x" in capsys.readouterr().out
    monkeypatch.delenv("ORCH_CHECK_LABELS")
    assert light.main(["--base", "b", "--group", "--plan"]) == 0
    assert "--labels" not in capsys.readouterr().out

# -- the picked workspace tests (texts given, ORCH-1123): before the merge only what the group can break -----------
TEXTS = {
    "test_adapters.py": "import orch.adapters\n",
    "test_cli_seams.py": "",
    "test_addons.py": "from orch import addons\n",
    "test_worktrees.py": "from orch import worktrees\n" + "x" * 50,
    "test_ticket.py": "import orch.ticket\n" + "x" * 5000,
    "test_other.py": "x" * 5000,
}


def _ws(files):
    steps = light.group_plan(files, ADDONS, "b", texts=TEXTS)
    return [s for s in steps if s["name"].startswith("workspace:") and "ruff" not in s["name"]]


def test_with_texts_the_full_suite_is_replaced_by_rule_tests_and_picked_files():
    steps = _ws(["workspace/src/orch/worktrees.py"])
    assert [s["name"] for s in steps] == [
        "workspace: rule tests over the whole tree",
        "workspace: 1 test file(s) that read the changed code",
    ]
    assert steps[1]["cmd"] == 'uv run pytest -q -n 8 -m "not slow" tests/test_worktrees.py'
    assert "workspace: tests (not slow)" not in names(light.group_plan(["workspace/x"], ADDONS, "b", texts=TEXTS))


def test_the_rule_tests_always_run_and_name_the_core_text_rule_of_test_addons():
    steps = _ws(["docs/x.md"])
    assert [s["name"] for s in steps] == ["workspace: rule tests over the whole tree"]
    assert steps[0]["cmd"].startswith("uv run pytest -q -n 8 tests/test_adapters.py tests/test_cli_seams.py")
    assert "tests/test_addons.py::test_core_text_names_no_addon" in steps[0]["cmd"]


def test_a_broad_change_or_a_contracts_change_runs_the_quarter_sample():
    for f in ("workspace/tests/conftest.py", "contracts/x.json", "workspace/src/orch/nobody_imports.py"):
        steps = _ws([f])
        assert steps[-1]["cmd"] == 'uv run pytest -q -n 8 -m "not slow" --part 1/4', f


def test_a_changed_rule_test_file_does_not_run_twice():
    steps = _ws(["workspace/tests/test_cli_seams.py"])
    assert [s["name"] for s in steps] == ["workspace: rule tests over the whole tree"]


def test_every_rule_node_names_a_real_test():
    for node in light.RULE_NODES:
        file, func = node.split("::")
        text = (ROOT / "workspace" / "tests" / file).read_text(encoding="utf-8")
        assert f"def {func}(" in text, node


def test_all_tests_flag_keeps_the_full_not_slow_suite(capsys, monkeypatch):
    monkeypatch.setattr(light, "changed", lambda base: ["workspace/src/orch/worktrees.py"])
    assert light.main(["--group", "--plan", "--all-tests"]) == 0
    assert "workspace: tests (not slow)" in capsys.readouterr().out
    assert light.main(["--group", "--plan"]) == 0
    out = capsys.readouterr().out
    assert "workspace: tests (not slow)" not in out and "rule tests over the whole tree" in out


# -- the two smokes (ORCH-1124, manager 22 Nov) ----------------------------------------------------------------------
def _plan(files):
    return light.group_plan(files, ADDONS, "b", texts=TEXTS)


def test_the_e2e_smoke_runs_next_to_the_others_when_ci_would_run_it():
    for f in ("workspace/src/orch/store.py", "workspace-addons/sync/x.py", "e2e/run.sh", "install.sh"):
        smoke = [s for s in _plan([f]) if s["name"] == "e2e smoke"]
        assert smoke == [light.E2E_SMOKE_STEP] and smoke[0]["background"], f
    for f in ("docs/x.md", "install.ps1", "mobile/x.swift"):
        assert "e2e smoke" not in [s["name"] for s in _plan([f])], f
    # never the internet: W0 installs GitHub's develop (a green group went red on 22 Nov when GitHub dropped it)
    assert light.E2E_SMOKE_STEP["cmd"] == "e2e/run.sh smoke-offline --mode local"
    main = (ROOT / "e2e" / "main.py").read_text(encoding="utf-8")
    assert 'SMOKE_OFFLINE = [s for s in SMOKE if s != "W0"]' in main and '"smoke-offline"' in main


def test_the_page_smoke_runs_only_when_the_group_touches_focus_or_insights():
    name = light.PAGE_SMOKE_STEP["name"]
    for f in (
        "workspace-addons/focus/src/x.js",
        "workspace-addons/insights/x.py",
        "e2e/focus_insights_shots.cjs",
        "e2e/focus_d/steps.cjs",  # group 2409 of 21 Nov: red on GitHub in the Focus click-through
        "e2e/dash_sync_card.cjs",
        "e2e/headless.cjs",
        # group 2718 of 23 Nov: the Chat contacts cache in the dashboard broke the Focus Chat step on GitHub
        "workspace-addons/dashboard/src/orch_dashboard/data.py",
        "workspace-addons/dashboard/src/orch_dashboard/web/pages/liveterm.js",
    ):
        assert name in [s["name"] for s in _plan([f])], f
    for f in (
        "workspace-addons/sync/x.py",
        "e2e/run.sh",
        "e2e/dash_ci_shots.py",
        "workspace-addons/dashboard/tests/test_x.py",
        "workspace-addons/dashboard/clickthrough/features/a.cjs",
    ):
        assert name not in [s["name"] for s in _plan([f])], f
    cmd = light.PAGE_SMOKE_STEP["cmd"]
    assert "npm install -g" not in cmd and f"playwright@{light.PLAYWRIGHT}" in cmd  # never global on a shared Mac
    for part in light.PAGE_SMOKE_PARTS:  # every part CI runs, here at once
        assert part in cmd
    assert 'node e2e/focus_insights_smoke.cjs --part "$p"' in cmd and cmd.endswith("exit $rc; }")
    # a failed install must end the step red: the parts sit in braces after the last &&
    assert cmd.index(" && { for p in ") < cmd.index("jobs -p")
    smoke = (light.ROOT / "e2e/focus_insights_smoke.cjs").read_text(encoding="utf-8")
    focus = int(re.search(r"const FOCUS_PARTS = (\d+);", smoke).group(1))
    assert set(light.PAGE_SMOKE_PARTS) == {"pages", *(f"focus-{i}" for i in range(1, focus + 1))}


def _bg(name, cmd):
    return {"name": name, "cwd": ".", "cmd": cmd, "background": True}


def test_a_background_step_runs_next_to_the_others_and_both_pass():
    lines: list[str] = []
    steps = [*_steps(0), _bg("smoke", "sleep 1; echo smoke-said-hi"), *_steps(0)]
    t = __import__("time").monotonic()
    assert light.run_group(steps, {"PATH": "/usr/bin:/bin"}, out=lines.append) == 0
    assert __import__("time").monotonic() - t < 5
    assert lines[0].startswith("== [2/3] smoke starts next to the others")
    assert "smoke-said-hi" in "\n".join(lines) and lines[-1].startswith("local check: PASS (3 steps,")


def test_a_red_background_step_fails_the_check_by_its_name(tmp_path):
    lines: list[str] = []
    failed = tmp_path / "failed.txt"
    env = {"PATH": "/usr/bin:/bin", "ORCH_CHECK_FAILED": str(failed)}
    assert light.run_group([*_steps(0), _bg("smoke", "echo broke; exit 5")], env, out=lines.append) == 1
    assert lines[-1].startswith("local check: FAIL at smoke (step 2 of 2, exit 5,")
    assert "broke" in "\n".join(lines) and failed.read_text(encoding="utf-8") == "smoke\n"


def _gone(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _wait_pid(f, secs=5.0):
    import time

    end = time.monotonic() + secs
    while time.monotonic() < end:
        if f.exists() and f.read_text().strip():
            return int(f.read_text().strip())
        time.sleep(0.05)
    raise AssertionError(f"no pid in {f}")


def test_a_red_step_stops_a_background_step_and_its_children(tmp_path):
    lines: list[str] = []
    pid = tmp_path / "pid"
    # the child that matters is the sleep (a server, a browser), not the shell that started it
    smoke = _bg("smoke", f"sleep 30 & echo $! > {pid}; wait")
    first = {"name": "wait", "cwd": ".", "cmd": f"while [ ! -s {pid} ]; do sleep 0.05; done"}
    t = __import__("time").monotonic()
    assert light.run_group([smoke, first, *_steps(2)], {"PATH": "/usr/bin:/bin"}, out=lines.append) == 1
    assert __import__("time").monotonic() - t < 20
    assert _gone(_wait_pid(pid))
    assert lines[-1].startswith("local check: FAIL at s0 (step 3 of 3, exit 2,")


def test_a_smoke_that_turns_red_stops_a_long_step_at_once(tmp_path):
    lines: list[str] = []
    t = __import__("time").monotonic()
    steps = [_bg("smoke", "sleep 0.5; echo said-why; exit 7"), {"name": "long", "cwd": ".", "cmd": "sleep 30"}]
    assert light.run_group(steps, {"PATH": "/usr/bin:/bin"}, out=lines.append) == 1
    assert __import__("time").monotonic() - t < 15
    assert lines[-1].startswith("local check: FAIL at smoke (step 1 of 2, exit 7,")
    assert "said-why" in "\n".join(lines)


def test_a_green_smoke_is_not_red_when_a_long_step_passes_its_limit(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(light, "BACKGROUND_SECS", 1)
    steps = [_bg("smoke", "echo smoke-ok"), {"name": "long", "cwd": ".", "cmd": "sleep 2.5"}]
    assert light.run_group(steps, {"PATH": "/usr/bin:/bin"}, out=lines.append) == 0
    assert lines[-1].startswith("local check: PASS (2 steps,")
    assert "smoke-ok" in "\n".join(lines)


def test_a_smoke_past_its_limit_sends_the_group_to_github(monkeypatch, tmp_path):
    lines: list[str] = []
    failed = tmp_path / "failed.txt"
    monkeypatch.setattr(light, "BACKGROUND_SECS", 1)
    env = {"PATH": "/usr/bin:/bin", "ORCH_CHECK_FAILED": str(failed)}
    assert light.run_group([_bg("smoke", "sleep 30"), *_steps(0)], env, out=lines.append) == 2
    assert lines[-1].startswith("local check: TIMEOUT at smoke (step 1 of 2, still running after 1 s,")
    assert not failed.exists()  # no failed check names: nothing to split the group by


# -- what only GitHub can check (ORCH-1124: group 2445 of 22 Nov, red on GitHub in the services click-through) -------
def test_a_group_that_changes_what_only_github_checks_is_sent_there(capsys, monkeypatch):
    for f in (
        "relay/src/main.rs",
        "publish/Cargo.toml",
        "mobile/App/x.swift",
        "contracts/blocks.schema.json",
        "contracts/vectors/look-v1.json",
        "contracts/examples/message/valid-question-review.json",
        "transcription/src/main.rs",
        "install.ps1",
        "workspace-addons/services/src/orch_services/cli.py",
        "e2e/walkthrough/package.json",
        "e2e/scenarios_services.py",
        "workspace/src/orch_ui/static/tokens.css",
        "workspace/src/orch/templates/page.html",
    ):
        assert light.github_only(["docs/x.md", f]) == [f], f
    for f in (
        "workspace/src/orch/store.py",
        "workspace-addons/sync/x.py",
        "install.sh",
        "e2e/run.sh",
        "docs/x.md",
        "contracts/addon-manifest.schema.json",  # no server or phone code reads it: checked here
        "contracts/addons/browse/README.md",
        "contracts/ticket.schema.json",
        "contracts/examples/ticket/invalid-priority-normal.json",
    ):
        assert light.github_only([f]) == [], f
    monkeypatch.setattr(light, "changed", lambda base: ["workspace/src/orch/store.py", "relay/src/main.rs"])
    monkeypatch.setattr(light, "run_group", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    assert light.main(["--group"]) == 2  # the local check's code for broken: GitHub checks the group
    assert capsys.readouterr().out.strip().endswith("local check: GitHub only: the group changes relay/src/main.rs")
    assert light.main(["--group", "--plan"]) == 0  # the plan still shows what would run here


def test_the_short_add_on_suites_share_one_runner_and_light_still_finds_each():
    """ORCH-1118 (#2492): eight jobs of under a minute took eight runners and groups waited for free ones.
    Plain text over the block style of addons.yml (no yaml module in the brand tests)."""
    import re

    jobs = dict(re.findall(r"(?m)^  ([A-Za-z0-9_-]+):\n((?:(?!  \S).*\n|\n)*)", ADDONS_YML + "\n"))
    small = ("automation", "focus", "insights", "lessons", "files", "pull-requests", "usage", "skills")
    for name in (*small, "tool-name-scan"):
        assert name not in jobs, name
    body = jobs["small-addons"]
    for a in small:
        for part in ("install", "ruff", "tests"):
            step = re.search(rf'- name: "{a}: {part}"\n(.*\n){{3}}', body)
            assert step, (a, part)
            assert "if: ${{ !cancelled() }}" in step.group(0), (a, part)  # one red suite never hides the next
            assert f"working-directory: workspace-addons/{a}" in step.group(0), (a, part)
    assert set(small) <= set(light.ci_addons(ADDONS_YML))


# Contract paths a server or the phone app names: "contracts/<path>" anywhere, or a path relative to contracts/
# that the phone tests open through their own helper (ReviewTests object("vectors/...")).
CONTRACT_MENTION = re.compile(r"contracts/([A-Za-z0-9_.\-/]+)")
RELATIVE_MENTION = re.compile(r'"((?:vectors|examples|review|look)/[A-Za-z0-9_.\-/]+)"')
READERS = ("relay", "publish", "transcription", "mobile")
TEXT = {".rs", ".swift", ".js", ".cjs", ".mjs", ".ts", ".py", ".toml", ".sh", ".json", ".yml", ".yaml"}


def _mentions() -> set[str]:
    out: set[str] = set()
    for top in READERS:
        for f in (ROOT / top).rglob("*"):
            if f.suffix not in TEXT or not f.is_file() or "target" in f.parts or "node_modules" in f.parts:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            for m in (*CONTRACT_MENTION.findall(text), *RELATIVE_MENTION.findall(text)):
                out.add(m.rstrip("./"))
    return out


def test_every_contract_a_server_or_the_phone_app_reads_goes_to_github():
    # the local check runs no Rust and no phone tests: a contract they read must send the group to GitHub
    missed = []
    for m in sorted(_mentions()):
        path = ROOT / "contracts" / m
        if path.is_file():
            files = [path]
        elif path.is_dir():
            files = [p for p in path.rglob("*") if p.is_file()]
        else:
            continue  # a word in a comment or a name built at run time (its folder is named too)
        if m == "validate.py":
            continue  # the local check runs it itself (the contracts step)
        for p in files:
            rel = p.relative_to(ROOT).as_posix()
            if not light.github_only([rel]):
                missed.append(f"{rel} (named as contracts/{m})")
    assert not missed, "add to SERVER_CONTRACTS in scripts/ci_light.py:\n" + "\n".join(missed)

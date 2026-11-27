"""A pull request that changes file, process or path code also runs Windows (scripts/touches_os_code.py)."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import touches_os_code as t  # noqa: E402


def diff(path: str, *lines: str) -> str:
    body = "\n".join(lines)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n{body}\n"


def hits(text: str) -> list[str]:
    return t.reasons(t.parse(text))


def test_a_file_time_call_in_a_test_runs_windows():
    # the call behind the 78 unseen Windows failures (Nov 2026)
    assert hits(diff("workspace/tests/test_doctor.py", "+    os.utime(p, (1, 1), follow_symlinks=False)"))


def test_process_and_path_calls_run_windows():
    for line in (
        "+    subprocess.run(['git', 'status'])",
        "+    p = Popen(cmd)",
        "+    shutil.move(a, b)",
        "+    os.replace(tmp, dst)",
        "-    if os.name == 'nt':",
        "+    target.symlink_to(src)",
        "+    real = p.resolve()",
        "+    os.path.join(a, b)",
    ):
        assert hits(diff("workspace/src/orch/x.py", line)), line


def test_addon_source_counts_and_its_tests_do_not():
    assert hits(diff("workspace-addons/services/src/orch_services/cli.py", "+    subprocess.run(cmd)"))
    assert not hits(diff("workspace-addons/services/tests/test_cli.py", "+    subprocess.run(cmd)"))


def test_plain_changes_stay_on_ubuntu():
    assert not hits(diff("workspace/src/orch/words.py", "+    text = text.replace('a', 'b')", "+    return 1"))
    assert not hits(diff("workspace/src/orch/x.py", "+import subprocess", "+from os import path"))
    assert not hits(diff("workspace/src/orch/x.py", "+    n = 1  # subprocess.run is not called here"))
    assert not hits(diff("docs/windows.md", "+Use os.replace on Windows."))
    assert not hits(diff("mobile/App.swift", "+    subprocess"))


def test_files_about_files_and_processes_run_windows_on_any_change():
    for path in ("install.ps1", "workspace/src/orch/winacl.py", "workspace/src/orch/procs.py", "e2e/windows/a.ps1"):
        assert hits(diff(path, "+# a comment")), path


def test_a_rename_without_line_changes_still_counts_for_the_whole_files():
    assert hits("diff --git a/workspace/src/orch/home.py b/workspace/src/orch/home.py\nsimilarity index 100%\n")


def test_the_command_prints_true_or_false(capsys, monkeypatch):
    monkeypatch.setattr(t, "changed", lambda base: t.parse(diff("workspace/src/orch/x.py", "+    os.kill(pid, 9)")))
    assert t.main(["--base", "origin/develop", "--why"]) == 0
    out = capsys.readouterr()
    assert out.out == "true\n"
    assert "os.kill" in out.err
    monkeypatch.setattr(t, "changed", lambda base: [])
    t.main(["--base", "origin/develop"])
    assert capsys.readouterr().out == "false\n"


def test_a_pull_request_runs_no_windows_parts_while_windows_is_known_red(monkeypatch, capsys):
    # ORCH-453: 841 Windows minutes on pull requests in one night, all known red; they run on queue groups instead
    monkeypatch.setattr(t, "changed", lambda base: [("workspace/src/orch/procs.py", "")])
    monkeypatch.setattr(t, "windows_known_red", lambda: True)
    assert t.main(["--base", "x", "--pr"]) == 0
    assert capsys.readouterr().out.strip() == "false"
    assert t.main(["--base", "x"]) == 0  # without --pr (a manual question) the diff still decides
    assert capsys.readouterr().out.strip() == "true"


def test_a_pull_request_runs_windows_again_once_it_is_green(monkeypatch, capsys):
    monkeypatch.setattr(t, "changed", lambda base: [("workspace/src/orch/procs.py", "")])
    monkeypatch.setattr(t, "windows_known_red", lambda: False)
    assert t.main(["--base", "x", "--pr"]) == 0
    assert capsys.readouterr().out.strip() == "true"


def test_windows_known_red_reads_the_workflow():
    import ci_known_red

    assert t.windows_known_red() == ("windows-latest" in ci_known_red.known_red())


# --- where the Windows parts run (ORCH-1118 q7): ci.yml's own conditions, played through for each place ---

CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
NAME = re.compile(r"\b(?:github|needs|vars|inputs|steps)(?:\.[A-Za-z_]+)+")


def gh_eval(expr: str, ctx: dict[str, str]) -> bool:
    """A GitHub expression of ci.yml (==, !=, &&, ||, !, startsWith, cancelled) over plain strings; unset = ''."""
    expr = expr.strip()
    if expr.startswith("${{"):
        expr = expr[3:-2]
    py = NAME.sub(lambda m: repr(ctx.get(m.group(0), "")), expr)
    py = py.replace("&&", " and ").replace("||", " or ").replace("cancelled()", "False")
    py = re.sub(r"!(?!=)", " not ", py).replace("startsWith", "str.startswith")
    return bool(eval(py, {"__builtins__": {}, "str": str}))  # our own workflow text


def ci_line(pattern: str) -> str:
    return re.search(pattern, CI, re.MULTILINE).group(1)


OS_STEP_IF = ci_line(r"^      - id: os\n        if: (.+)$")
WS_IF = ci_line(r"^  workspace:\n(?:    #.*\n)*    needs: .*\n(?:    #.*\n)*    if: (.+)$")
WS_WINDOWS = ci_line(r"^      windows: (.+)$")
OS_FILE = diff("workspace/src/orch/procs.py", "+    os.kill(pid, 9)")
PLAIN_FILE = diff("workspace/src/orch/words.py", "+    return 1")


def place(head: str, base: str, light: bool, queue: bool, files: str) -> dict[str, str]:
    ctx = {
        "github.event_name": "pull_request",
        "github.head_ref": head,
        "github.base_ref": base,
        "steps.place.outputs.light": str(light).lower(),
        "needs.changes.outputs.light": str(light).lower(),
        "needs.changes.outputs.queue": str(queue).lower(),
        "needs.changes.outputs.workspace": "true",
        "needs.changes.result": "success",
    }
    if gh_eval(OS_STEP_IF, ctx):  # the os step runs and answers from the diff
        ctx["needs.changes.outputs.oscode"] = "true" if hits(files) else "false"
    return ctx


def runs_windows(ctx: dict[str, str]) -> bool:
    return gh_eval(WS_IF, ctx) and gh_eval(WS_WINDOWS, ctx)


def test_a_light_pull_request_with_os_code_runs_no_windows_parts():
    # owner 24 Nov: 20 Windows parts, about 150 runner-minutes on every push of such a pull request
    ctx = place("copilot/x", "develop", light=True, queue=False, files=OS_FILE)
    assert "needs.changes.outputs.oscode" not in ctx  # not even asked
    assert not runs_windows(ctx)


def test_a_queue_group_runs_the_windows_parts_only_for_os_code():
    assert runs_windows(place("orch-queue/develop-1", "develop", light=False, queue=True, files=OS_FILE))
    group = place("orch-queue/develop-1", "develop", light=False, queue=True, files=PLAIN_FILE)
    assert gh_eval(WS_IF, group) and not gh_eval(WS_WINDOWS, group)  # Linux parts only


def test_a_release_pull_request_with_os_code_still_runs_windows():
    assert runs_windows(place("develop", "main", light=False, queue=False, files=OS_FILE))


def test_the_cli_smoke_stays_on_every_pull_request_that_touches_the_cli():
    # R3.4: the Windows + macOS CLI smoke is not moved to the queue
    smoke_if = ci_line(r"^  cli-smoke:\n(?:    #.*\n)*    needs: .*\n(?:    #.*\n)*    if: (.+)$")
    ctx = place("copilot/x", "develop", light=True, queue=False, files=OS_FILE) | {"needs.changes.outputs.smoke": "true"}
    assert gh_eval(smoke_if, ctx)


def test_the_os_code_list_has_one_home():
    # ci.yml asks the script; no second file list for "os code" in a workflow
    assert CI.count("touches_os_code.py --base") == 1
    assert "procs" not in CI and "winacl" not in CI

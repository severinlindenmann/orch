"""A pull request that changes file, process or path code also runs Windows (scripts/touches_os_code.py)."""

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

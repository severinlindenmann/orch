"""orch work-check: the one-line reminder when files changed and no ticket covers them."""

import io
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from orch import filesig, procs, runs, safegit, tickets, workcheck
from orch import init as init_mod


def _git(proj, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", *args], cwd=proj, env=env, capture_output=True, text=True, check=True)


@pytest.fixture
def ws(proj):
    """An initialised workspace (git) with one committed file and one ticket event in the past."""
    _git(proj, "init", "-q")
    _git(proj, "config", "user.email", "t@example.com")
    _git(proj, "config", "user.name", "t")
    (proj / "a.txt").write_text("a")
    init_mod.init(proj)
    _git(proj, "add", "a.txt")
    _git(proj, "commit", "-qm", "i")
    old = time.time() - 600
    os.utime(proj / "a.txt", (old, old))
    return proj


def _edit(proj, name="b.txt", ahead=30):
    p = proj / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")
    t = time.time() + ahead  # clearly after any ticket event made by the test
    os.utime(p, (t, t))
    return p


def _hook(monkeypatch, proj, event="UserPromptSubmit", payload=None, capsys=None):
    body = json.dumps({"hook_event_name": event, "cwd": str(proj)}) if payload is None else payload
    monkeypatch.setattr(sys, "stdin", io.StringIO(body))
    rc = workcheck.hook_main(["work-check", "--hook", "claude"])
    return rc, capsys.readouterr().out


def test_unchanged_is_silent(ws):
    assert workcheck.check(ws)["remind"] is False


def test_changed_files_and_no_ticket_gives_the_line(ws):
    _edit(ws)
    res = workcheck.check(ws)
    assert res["remind"] and res["files"] == 1 and res["line"].startswith("orch: files changed")


def test_active_claim_keeps_it_quiet(ws):
    t = tickets.create(ws, "Rename", "human:t")
    _edit(ws)
    assert workcheck.check(ws)["remind"] is True  # a ticket alone is not enough: nobody is working on it
    runs.claim(ws, t["id"], "agent:claude", "claude", "live", pid=os.getpid())
    assert workcheck.check(ws)["remind"] is False


def test_closed_ticket_with_claim_does_not_count(ws):
    t = tickets.create(ws, "Old", "human:t")
    runs.claim(ws, t["id"], "agent:claude", "claude", "live", pid=os.getpid())
    tickets.set_status(ws, t["id"], "dropped", "human:t")
    _edit(ws)
    assert workcheck.check(ws)["remind"] is True


def test_file_older_than_the_last_ticket_event_is_not_a_change(ws):
    old = _edit(ws, ahead=-300)
    tickets.create(ws, "Later", "human:t")
    assert old.exists() and workcheck.check(ws)["remind"] is False


def test_untracked_ignored_and_orch_files_are_left_out(ws):
    (ws / ".gitignore").write_text("*.log\n")
    os.utime(ws / ".gitignore", (1, 1))
    _edit(ws, "x.log")
    _edit(ws, "node_modules/p/i.js")
    _edit(ws, ".orch/run/whatever")
    assert workcheck.check(ws)["remind"] is False


def test_once_per_change_set_then_again_for_a_new_one(ws, monkeypatch, capsys):
    _edit(ws)
    rc, out = _hook(monkeypatch, ws, capsys=capsys)
    assert rc == 0 and json.loads(out)["hookSpecificOutput"]["additionalContext"].startswith("orch:")
    assert _hook(monkeypatch, ws, capsys=capsys) == (0, "")  # the same change set: quiet (double fire)
    _edit(ws, "c.txt")
    assert _hook(monkeypatch, ws, capsys=capsys)[1] != ""  # a different change set


def test_hook_json_shape_per_event(ws, monkeypatch, capsys):
    _edit(ws)
    _, out = _hook(monkeypatch, ws, event="SessionStart", capsys=capsys)
    doc = json.loads(out)
    assert set(doc) == {"hookSpecificOutput"}
    assert doc["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert doc["hookSpecificOutput"]["additionalContext"] == workcheck.LINE


def test_other_events_and_garbage_stay_silent_or_default(ws, monkeypatch, capsys):
    _edit(ws)
    assert _hook(monkeypatch, ws, event="Stop", capsys=capsys) == (0, "")
    rc, out = _hook(monkeypatch, ws, payload="not json", capsys=capsys)  # unreadable: the usual event
    assert rc == 0 and json.loads(out)["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


def test_own_run_ticket_open_is_silent(ws, monkeypatch, capsys):
    t = tickets.create(ws, "Mine", "human:t")
    _edit(ws)
    monkeypatch.setenv("ORCH_RUN", "r_1")
    monkeypatch.setenv("ORCH_TICKET", t["id"])
    assert _hook(monkeypatch, ws, capsys=capsys) == (0, "")
    monkeypatch.setenv("ORCH_TICKET", "t_nothere1")  # ORCH_RUN without an open ticket: normal rules
    assert _hook(monkeypatch, ws, capsys=capsys)[1] != ""


def test_hook_exits_zero_on_any_error(ws, monkeypatch, capsys):
    _edit(ws)

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(workcheck, "check", boom)
    assert _hook(monkeypatch, ws, capsys=capsys) == (0, "")
    monkeypatch.setattr(workcheck, "_read_event", boom)
    assert _hook(monkeypatch, ws, capsys=capsys) == (0, "")


def test_hook_as_a_process_never_fails(ws):
    """The real command line, also with a stdin that is not JSON and a folder that is no workspace."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "ORCH_RUN", "ORCH_TICKET"))}
    argv = procs.orch_python_argv(
        "work-check", "--hook", "claude"
    )  # the shipped command differs (-I): see init tests
    for cwd, stdin in ((ws, '{"hook_event_name":"UserPromptSubmit"}'), (ws, "{{{"), (ws.parent, "")):
        r = subprocess.run(argv, cwd=cwd, input=stdin, capture_output=True, text=True, env=env, timeout=30)
        assert r.returncode == 0, r.stderr
    _edit(ws)
    r = subprocess.run(
        argv, cwd=ws, input='{"hook_event_name":"UserPromptSubmit"}', capture_output=True, text=True, env=env
    )
    assert r.returncode == 0 and "additionalContext" in r.stdout


def test_cli_text_json_and_silence(ws, run):
    code, out, _ = run("work-check")
    assert code == 0 and out.strip() == ""
    _edit(ws)
    code, out, _ = run("work-check")
    assert code == 0 and out.strip() == workcheck.LINE
    code, out, _ = run("work-check", "--json")
    assert json.loads(out)["remind"] is True and json.loads(out)["files"] == 1


def test_no_git_uses_mtimes_and_skips_the_usual_folders(proj):
    (proj / "a.txt").write_text("a")
    init_mod.init(proj)
    os.utime(proj / "a.txt", (1, 1))
    assert workcheck.check(proj)["remind"] is False
    _edit(proj, "node_modules/x/y.js")
    _edit(proj, ".venv/z.py")
    assert workcheck.check(proj)["remind"] is False
    _edit(proj, "src/new.py")
    assert workcheck.check(proj)["files"] == 1


def test_caps_make_it_silent(ws, monkeypatch):
    _edit(ws)
    assert workcheck.check(ws)["remind"] is True
    monkeypatch.setattr(workcheck, "MAX_FILES", 0)
    assert workcheck.check(ws)["remind"] is False  # git folder: too many files
    (ws / ".git").rename(ws / ".git-away")  # now a plain folder
    assert workcheck.check(ws)["remind"] is False  # walked folder: too many files
    monkeypatch.setattr(workcheck, "MAX_FILES", 20000)
    monkeypatch.setattr(workcheck, "TIMEOUT", -1.0)
    assert workcheck.check(ws)["remind"] is False  # too slow


def test_hostile_git_filter_never_runs(ws):
    """A repo whose config/attributes name a clean filter, a textconv and an fsmonitor hook: work-check only
    lists names, so none of them runs."""
    marker = ws / "ran.txt"
    _git(ws, "config", "filter.evil.clean", f"touch {marker}; cat")
    _git(ws, "config", "diff.evil.textconv", f"touch {marker}; cat")
    _git(ws, "config", "core.fsmonitor", f"touch {marker}; echo")
    (ws / ".git" / "hooks").mkdir(exist_ok=True)
    hook = ws / ".git" / "hooks" / "post-index-change"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    (ws / ".gitattributes").write_text("*.txt filter=evil diff=evil\n")
    os.utime(ws / ".gitattributes", (1, 1))
    _edit(ws, "a.txt")  # stat-dirty tracked file: `git status` would run the filter on it
    _edit(ws, "new.txt")
    assert workcheck.check(ws)["files"] == 2
    assert not marker.exists()


def test_git_runs_through_safegit_with_the_hardened_flags(ws, monkeypatch):
    seen = []
    real = subprocess.run

    def spy(argv, *a, **k):
        seen.append((list(argv), dict(k.get("env") or {})))
        return real(argv, *a, **k)

    monkeypatch.setattr(safegit.subprocess, "run", spy)
    monkeypatch.setenv("GIT_DIR", "/nonexistent")
    _edit(ws)
    assert workcheck.check(ws)["remind"] is True
    assert seen
    for argv, env in seen:
        assert os.path.isabs(argv[0])  # resolved by safegit, never a bare "git"
        assert argv[1] == "--no-optional-locks"
        for want in ("core.fsmonitor=false", "core.untrackedCache=false", "protocol.allow=never"):
            assert want in argv
        assert any(a.startswith("core.hooksPath=") and a != "core.hooksPath=/dev/null" for a in argv)
        assert not any(k.startswith("GIT_DIR") for k in env)
        assert not {"diff", "status", "log", "show", "add", "commit"} & set(argv)


def _fake_git(folder, marker="planted.txt"):
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / ("git.exe" if os.name == "nt" else "git")
    f.write_text(f"#!/bin/sh\ntouch {marker}\n")
    f.chmod(0o755)
    return f


def test_git_is_never_taken_from_the_project_or_a_relative_path_entry(ws, monkeypatch):
    real = shutil.which("git")
    _fake_git(ws / "tools")
    _fake_git(ws / "bin")
    monkeypatch.setattr(safegit, "_exes", {})
    # the project's folders first on PATH, a relative entry, the current folder: all skipped
    path = os.pathsep.join([str(ws / "tools"), "bin", "", ".", str(ws), os.path.dirname(real)])
    monkeypatch.setenv("PATH", path)
    monkeypatch.chdir(ws)
    assert safegit.git_exe(ws) == real
    _edit(ws)
    assert workcheck.check(ws)["remind"] is True
    assert not (ws / "planted.txt").exists()


def test_git_only_inside_the_project_means_no_git_and_a_walk(ws, monkeypatch):
    _fake_git(ws / "tools")
    monkeypatch.setattr(safegit, "_exes", {})
    monkeypatch.setenv("PATH", str(ws / "tools"))
    assert safegit.git_exe(ws) is None
    _edit(ws)
    assert workcheck.check(ws)["files"] == 2 and not (ws / "planted.txt").exists()  # b.txt + tools/git


def test_hostile_repo_runs_nothing_in_the_hook_and_files_sig(ws, tmp_path, monkeypatch, capsys):
    """A fake git and true in the workspace PATH, a repo hook, an fsmonitor and a filter driver: nothing runs,
    and the hook output is the same as in a clean repo."""
    marker = tmp_path / "RAN"
    for d in ("tools", "bin"):
        _fake_git(ws / d, marker=str(marker))
        t = ws / d / "true"
        t.write_text(f"#!/bin/sh\ntouch {marker}\n")
        t.chmod(0o755)
    hooks = ws / ".git" / "hooks"
    for h in ("reference-transaction", "post-index-change", "pre-commit"):
        (hooks / h).write_text(f"#!/bin/sh\ntouch {marker}\n")
        (hooks / h).chmod(0o755)
    _git(ws, "config", "core.fsmonitor", f"touch {marker}; echo")
    _git(ws, "config", "core.hooksPath", str(hooks))
    _git(ws, "config", "filter.x.clean", f"touch {marker}; cat")
    _git(ws, "config", "filter.x.smudge", f"touch {marker}; cat")
    (ws / ".gitattributes").write_text("*.txt filter=x\n")
    clean = shutil.which("git")
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join([str(ws / "tools"), str(ws / "bin"), os.path.dirname(clean), "/usr/bin", "/bin"]),
    )
    monkeypatch.setattr(safegit, "_exes", {})
    _edit(ws)

    def no_walk(*a, **k):
        raise AssertionError("git was expected to work: the folder must not be walked")

    monkeypatch.setattr(workcheck, "_walk_names", no_walk)
    rc, out = _hook(monkeypatch, ws, capsys=capsys)
    assert rc == 0 and out.strip()  # the reminder line is still printed
    assert workcheck.check(ws)["files"] >= 2
    assert filesig.files_sig(ws)
    assert not marker.exists() and not (ws / "planted.txt").exists()


def test_find_root_stays_in_its_own_project(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    (shared / ".orch").mkdir(parents=True)
    proj = shared / "proj"
    (proj / ".git").mkdir(parents=True)
    (proj / "sub").mkdir()
    assert workcheck.find_root(proj / "sub") == proj / "sub"  # stopped at the git top folder, no .orch there
    (proj / ".orch").mkdir()
    assert workcheck.find_root(proj / "sub") == proj


def test_hook_unknown_tool_or_missing_arg_is_silent(ws, monkeypatch, capsys):
    _edit(ws)
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": str(ws)}))
    )
    assert workcheck.hook_main(["work-check", "--hook", "nosuchtool"]) == 0
    assert workcheck.hook_main(["work-check", "--hook"]) == 0
    assert capsys.readouterr().out == ""


def test_find_root_needs_a_boundary_to_walk_up(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "elsewhere"))
    monkeypatch.setattr(workcheck.Path, "home", classmethod(lambda cls: tmp_path / "elsewhere"))
    (tmp_path / ".orch").mkdir()
    deep = tmp_path / "x" / "y"
    deep.mkdir(parents=True)
    assert workcheck.find_root(deep) == deep  # no .git or home on the way up: only the start counts
    (tmp_path / ".git").mkdir()
    assert workcheck.find_root(deep) == tmp_path  # a git top folder is the boundary and holds our .orch


def test_hook_reads_its_stdin_field_names_from_the_data(ws, monkeypatch, capsys):
    from orch import adapters

    _edit(ws)
    data = adapters.load("claude")["reminder"]["input"]
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({data["event"]: "SessionStart", data["cwd"]: str(ws)}))
    )
    assert workcheck.hook_main(["work-check", "--hook", "claude"]) == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["hookEventName"] == "SessionStart"

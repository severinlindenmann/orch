"""ORCH_ROOT: the workspace of whoever started the process, strictly validated; passed to every spawn."""

import json
import os
import shlex
import sys
import time

import pytest

from orch import cli, config, runs, runs_live


def _store(p):
    """A workspace folder with an orch store in it."""
    p.mkdir(parents=True, exist_ok=True)
    (p / ".orch").mkdir(exist_ok=True)
    return p


def _files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_orch_root_beats_a_nested_store(proj, run, monkeypatch):
    outer = _store(proj / "main")
    copy = _store(proj / "main" / "copy")  # a tracked .orch inside a copy: the stale second store
    sub = copy / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)
    monkeypatch.setenv("ORCH_ROOT", str(outer))
    assert cli._find_root() == outer.resolve()
    code, out, _ = run("ticket", "new", "From the copy", "--json", "--by", "human:t")
    assert code == 0
    tid = json.loads(out)["id"]
    assert (outer / ".orch" / "tickets" / f"{tid}.json").is_file()
    assert not (copy / ".orch" / "tickets").exists()
    assert not (sub / ".orch").exists()


def test_without_orch_root_the_nearest_store_wins(proj, monkeypatch):
    outer = _store(proj / "main")
    copy = _store(proj / "main" / "copy")
    monkeypatch.chdir(copy / ".orch")
    monkeypatch.delenv("ORCH_ROOT", raising=False)
    assert cli._find_root() == copy
    assert outer.exists()


def test_orch_root_is_resolved_through_links(proj, monkeypatch):
    real = _store(proj / "real")
    link = proj / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("no symlinks here")
    monkeypatch.setenv("ORCH_ROOT", str(link))
    assert cli._find_root() == real.resolve()


@pytest.mark.parametrize("kind", ["relative", "missing", "no-orch", "file"])
def test_invalid_orch_root_is_refused_and_nothing_is_written(proj, run, monkeypatch, kind):
    store = _store(proj / "store")  # a valid store is right here: still no fallback to it
    monkeypatch.chdir(store)
    (proj / "plain").mkdir()
    (proj / "afile").write_text("x", encoding="utf-8")
    raw = {
        "relative": "store",
        "missing": str(proj / "nope"),
        "no-orch": str(proj / "plain"),
        "file": str(proj / "afile"),
    }[kind]
    monkeypatch.setenv("ORCH_ROOT", raw)
    before = _files(proj)
    code, out, err = run("ticket", "new", "Nope", "--by", "human:t")
    assert code == 2 and "ORCH_ROOT" in err and "Nothing was changed" in err
    assert _files(proj) == before


def test_init_refuses_in_a_copy_when_orch_root_names_another_folder(proj, run, monkeypatch):
    outer = _store(proj / "main")
    copy = proj / "copy"
    copy.mkdir()
    monkeypatch.chdir(copy)
    monkeypatch.setenv("ORCH_ROOT", str(outer))
    before = _files(proj)
    code, _, err = run("init", "--yes")
    assert code == 2 and "ORCH_ROOT is set to" in err
    assert _files(proj) == before


def test_init_works_when_orch_root_is_this_folder(proj, run, monkeypatch):
    here = _store(proj / "here")
    monkeypatch.chdir(here)
    monkeypatch.setenv("ORCH_ROOT", str(here))
    code, _, err = run("init", "--yes")
    assert code == 0, err


def test_init_refuses_inside_the_orch_worktrees_folder(proj, run, monkeypatch):
    from orch import addons

    copy = addons.home() / "worktrees" / "ws1" / "T-1"
    copy.mkdir(parents=True)
    monkeypatch.chdir(copy)
    monkeypatch.delenv("ORCH_ROOT", raising=False)
    code, _, err = run("init", "--yes")
    assert code == 2 and "copy that orch made" in err
    assert not (copy / ".orch").exists()


def test_agent_environment_names_the_workspace(proj, monkeypatch):
    monkeypatch.setenv("ORCH_ROOT", "/stale/other")
    monkeypatch.setenv("ORCH_VIA", "page")
    env = runs._agent_environ(proj)
    assert env["ORCH_ROOT"] == str(proj) and "ORCH_VIA" not in env


def test_tmux_start_passes_orch_root_to_the_session_and_the_agent(proj, run, monkeypatch):
    calls, env_files = [], []

    class R:
        returncode = 0
        stderr = ""
        stdout = "123"

    def fake_tmux(root, *a, **k):
        calls.append(a)
        if a[0] == "new-session":  # the env file is private and removed by the wrapper: read it now
            f = a[a.index("--env-file") + 1]
            env_files.append(json.loads(open(f, encoding="utf-8").read()))
        return R()

    monkeypatch.setattr(runs_live, "tmux", fake_tmux)
    monkeypatch.setattr(runs_live, "session_exists", lambda *a: False)
    py = shlex.quote(sys.executable)
    config.add_agent(proj, "fake", f"{py} -c pass {{prompt}}", f"{py} -c pass")
    config.set_key(proj, "workspace", "agent", "fake")
    tid = json.loads(run("ticket", "new", "T", "--json", "--by", "human:t")[1])["id"]
    monkeypatch.setenv("ORCH_ROOT", "/stale/other")  # whatever the starter had is replaced, not passed on
    runs_live.start_live(proj, tid, "agent:x", "fake", fresh=False, take_over=False, busy_text="")
    new = [c for c in calls if c[0] == "new-session"][0]
    assert new[new.index("-e") + 1] == f"ORCH_ROOT={proj}"
    assert env_files[0]["ORCH_ROOT"] == str(proj)


@pytest.mark.skipif(os.name == "nt", reason="detached wrapper uses shell stubs")
def test_runs_start_overwrites_a_stale_orch_root_in_the_agent_environment(
    proj, run, monkeypatch, subprocess_home
):
    other = _store(proj.parent / f"{proj.name}-other")  # a VALID store: the stale value must not survive
    out = proj.parent / f"{proj.name}-root.txt"
    monkeypatch.setenv("ORCH_CMD", f"{shlex.quote(sys.executable)} -m orch")
    stub = proj.parent / f"{proj.name}-stub.py"
    stub.write_text(
        "import os,sys\nopen(sys.argv[1],'w').write(os.environ.get('ORCH_ROOT',''))\n", encoding="utf-8"
    )
    py, q = shlex.quote(sys.executable), shlex.quote
    config.add_agent(proj, "fake", f"{py} {q(str(stub))} {q(str(out))} {{prompt}}")
    config.set_key(proj, "workspace", "agent", "fake")
    tid = json.loads(run("ticket", "new", "T", "--json", "--by", "human:t")[1])["id"]
    monkeypatch.setenv("ORCH_ROOT", str(other))
    other_before = _files(other)
    runs.start(proj, tid, "agent:focus", mode="oneshot")  # the library, as the dashboard calls it
    end = time.monotonic() + 25
    while time.monotonic() < end and (runs.read(proj, tid) is not None or not out.exists()):
        time.sleep(0.05)
    assert out.read_text(encoding="utf-8") == str(proj.resolve())
    assert _files(other) == other_before  # the other (stale) store was never touched


def test_a_symlinked_workspace_gives_one_root_string(proj, monkeypatch):
    real = _store(proj / "real")
    link = proj / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("no symlinks here")
    monkeypatch.chdir(link)  # walk-up from the link
    monkeypatch.delenv("ORCH_ROOT", raising=False)
    parent = cli._find_root()
    monkeypatch.setenv("ORCH_ROOT", str(runs._agent_environ(parent)["ORCH_ROOT"]))
    assert cli._find_root() == parent == real.resolve()  # the child agrees with the parent


def test_empty_orch_root_counts_as_unset(proj, monkeypatch):
    store = _store(proj / "s")
    monkeypatch.chdir(store)
    monkeypatch.setenv("ORCH_ROOT", "")
    assert cli._find_root() == store.resolve()


def test_orch_root_with_dotdot_is_normalised(proj, monkeypatch):
    store = _store(proj / "s")
    (proj / "x").mkdir()
    monkeypatch.setenv("ORCH_ROOT", str(proj / "x" / ".." / "s"))
    assert cli._find_root() == store.resolve()


def test_help_with_an_invalid_orch_root_is_refused_with_the_fix(proj, run, monkeypatch):
    monkeypatch.setenv("ORCH_ROOT", str(proj / "nope"))
    code, _, err = run("--help")
    assert code == 2 and "Unset ORCH_ROOT" in err


def test_init_in_a_subfolder_of_orch_root_is_refused_with_a_plain_message(proj, run, monkeypatch):
    outer = _store(proj / "main")
    sub = outer / "sub"
    sub.mkdir()
    monkeypatch.chdir(sub)
    monkeypatch.setenv("ORCH_ROOT", str(outer))
    code, _, err = run("init", "--yes")
    assert code == 2 and "ORCH_ROOT is set to" in err and "unset ORCH_ROOT" in err
    assert not (sub / ".orch").exists()


def test_init_guard_with_orch_home_unset_uses_the_default_home(proj, run, monkeypatch):
    from orch import addons

    monkeypatch.delenv("ORCH_HOME", raising=False)
    monkeypatch.delenv("ORCH_ROOT", raising=False)
    copy = addons.real_home() / ".orch-tool" / "worktrees" / "ws1" / "T-1"
    copy.mkdir(parents=True)
    monkeypatch.chdir(copy)
    code, _, err = run("init", "--yes")
    assert code == 2 and "copy that orch made" in err
    assert not (copy / ".orch").exists()


def test_init_guard_sees_a_symlinked_cwd_that_resolves_into_worktrees(proj, run, monkeypatch):
    from orch import addons

    copy = addons.home_candidates()[0] / "worktrees" / "ws1" / "T-1"
    copy.mkdir(parents=True)
    link = proj / "link"
    try:
        link.symlink_to(copy, target_is_directory=True)
    except OSError:
        pytest.skip("no symlinks here")
    monkeypatch.chdir(link)
    monkeypatch.delenv("ORCH_ROOT", raising=False)
    code, _, err = run("init", "--yes")
    assert code == 2 and "copy that orch made" in err


def test_a_note_names_a_stale_orch_root_but_not_inside_a_copy(proj, run, monkeypatch):
    from orch import addons

    outer = _store(proj / "main")
    elsewhere = _store(proj / "else")
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("ORCH_ROOT", str(outer))
    monkeypatch.setattr(cli, "_noted", False)
    _, _, err = run("ticket", "new", "A", "--by", "human:t")
    assert "Note: ORCH_ROOT sends this to" in err
    copy = addons.home_candidates()[0] / "worktrees" / "ws1" / "T-1"
    copy.mkdir(parents=True)
    monkeypatch.chdir(copy)
    monkeypatch.setattr(cli, "_noted", False)
    _, _, err = run("ticket", "new", "B", "--by", "human:t")
    assert "Note:" not in err


def test_init_in_the_orch_root_folder_reached_through_a_symlink_is_not_refused(proj, run, monkeypatch):
    real = _store(proj / "real")
    link = proj / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("no symlinks here")
    monkeypatch.chdir(link)
    monkeypatch.setenv("ORCH_ROOT", str(real))
    code, _, err = run("init", "--yes")
    assert code == 0, err

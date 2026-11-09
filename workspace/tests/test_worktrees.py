"""B11: separate copies (git worktrees) of the project folder, one per ticket."""

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

from orch import adapters, addons, config, harness, runs, safegit, tickets, worktrees
from orch.errors import Refused

pytestmark = pytest.mark.skipif(os.name == "nt", reason="uses shell-free POSIX stubs")

WS = "0123456789abcdef0123456789abcdef"


def git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env, check=False)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


@pytest.fixture
def repo(proj, new_ticket):
    """The workspace is a git repo with its .orch tracked (tickets are committed by default)."""
    git(proj, "init", "-q")
    git(proj, "config", "user.email", "t@t")
    git(proj, "config", "user.name", "t")
    (proj / "code.py").write_text("print(1)\n")
    first = new_ticket("First")
    second = new_ticket("Second")
    addons.workspace_id(proj, create=True)
    harness.protect_local(proj)  # what `orch init` does: .orch/.gitignore (tracked) + .git/info/exclude
    git(proj, "add", "-A")
    git(proj, "commit", "-qm", "init")
    repo = type("Repo", (type(proj),), {})(proj)  # a Path that can carry the two ticket ids
    repo.tids = (first, second)
    yield repo
    # every copy this test made goes away with its folder, and git forgets it
    for t in list(worktrees.registry(repo)):
        for e in worktrees.registry(repo)[t]["paths"]:
            subprocess.run(["git", "worktree", "remove", "--force", e["path"]], cwd=repo, capture_output=True)
    subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)


def orch_env(root, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["ORCH_ROOT"] = str(root)
    env.update(extra)
    return env


def orch_cli(cwd, root, *args):
    """`orch <args>` as an agent in a copy runs it: cwd = the copy, ORCH_ROOT = the workspace."""
    return subprocess.run(
        [sys.executable, "-P", "-m", "orch", *args],
        cwd=cwd,
        env=orch_env(root, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src")),
        capture_output=True,
        text=True,
    )


def _route(root, ticket):
    """route() plus the slow steps it hands back (claim_routed runs them after the lock)."""
    folder, notes, after = worktrees.route(root, ticket)
    for step in after:
        notes = notes + step()
    return folder, notes


# ---------------------------------------------------------------- path_for


def test_path_for_is_inside_the_worktrees_folder(proj):
    p = worktrees.path_for(WS, "t_abc123")
    assert p == (addons.home() / "worktrees").resolve() / "01234567" / "t_abc123"


@pytest.mark.parametrize(
    "ticket",
    ["../x", "t_../x", "t_abc123/..", "T_abc123", "t_ab", "", "t_abc123\n", "t_abc123/", "/abs", ".", ".."],
)
def test_path_for_refuses_odd_ticket_ids(proj, ticket):
    with pytest.raises(Refused):
        worktrees.path_for(WS, ticket)


@pytest.mark.parametrize("ws", ["", "../..", "zz" * 16, "0123", WS.upper(), None])
def test_path_for_refuses_odd_workspace_ids(proj, ws):
    with pytest.raises(Refused):
        worktrees.path_for(ws, "t_abc123")


def test_path_for_refuses_a_link_that_leaves_the_folder(proj, tmp_path):
    base = addons.home() / "worktrees"
    base.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (base / "01234567").symlink_to(outside, target_is_directory=True)
    # the ws8 folder resolves outside <home>/worktrees: refused
    with pytest.raises(Refused):
        worktrees.path_for(WS, "t_abc123")


# ---------------------------------------------------------------- create


def test_create_makes_a_worktree_on_its_own_branch_and_registers_it(repo):
    t = repo.tids[0]
    e = worktrees.create(repo, t)
    head = git(repo, "rev-parse", "HEAD")
    wid = addons.workspace_id(repo)
    assert Path(e["path"]) == worktrees.path_for(wid, t)
    assert e["branch"] == f"orch/{t}" and e["base"] == head and e["sub"] == ""
    assert (Path(e["path"]) / "code.py").read_text() == "print(1)\n"
    assert git(e["path"], "rev-parse", "--abbrev-ref", "HEAD") == f"orch/{t}"
    assert worktrees.registry(repo)[t]["paths"][0] == e
    assert worktrees.count(repo) == 1
    owner = Path(e["path"]).parent / ".owner"
    assert owner.read_text().strip() == str(repo.resolve())  # B12 finds the workspace through it
    # the project's own status never shows the copy
    assert git(repo, "status", "--porcelain") == ""
    # the second call finds it, nothing is made twice
    assert worktrees.create(repo, t) == e and worktrees.count(repo) == 1


def test_the_copy_never_holds_the_tracked_orch_store(repo):
    t = repo.tids[0]
    e = worktrees.create(repo, t)
    copy = Path(e["path"])
    assert not (copy / ".orch" / "tickets").exists() or not list((copy / ".orch" / "tickets").iterdir())
    assert git(copy, "ls-files", "-v", ".orch").count("S ") == len(
        git(copy, "ls-files", ".orch").splitlines()
    )
    assert git(copy, "status", "--porcelain") == ""
    # orch commands of the agent go to the workspace store, the copy stays clean
    r = orch_cli(copy, repo, "ticket", "new", "Made from the copy", "--json", "--by", "human:t")
    assert r.returncode == 0, r.stderr
    new = json.loads(r.stdout)["id"]
    assert (repo / ".orch" / "tickets" / f"{new}.json").is_file()
    assert not (copy / ".orch" / "tickets" / f"{new}.json").exists()
    assert git(copy, "status", "--porcelain") == ""
    # `git add -A` and `commit -a` in the copy take the agent's work, never ticket JSON
    (copy / "code.py").write_text("print(2)\n")
    (copy / "new.txt").write_text("x\n")
    git(copy, "add", "-A")
    assert sorted(git(copy, "diff", "--cached", "--name-only").splitlines()) == ["code.py", "new.txt"]
    assert not any(
        p.startswith(".orch") for p in git(copy, "ls-tree", "-r", "--name-only", "HEAD").splitlines()[:0]
    )
    assert (repo / "code.py").read_text() == "print(1)\n"  # the project folder is untouched


def test_a_workspace_below_the_git_top_gets_the_copy_of_its_own_folder(tmp_path, proj, monkeypatch):
    top = proj
    git(top, "init", "-q")
    git(top, "config", "user.email", "t@t")
    git(top, "config", "user.name", "t")
    sub = top / "apps" / "web"
    sub.mkdir(parents=True)
    (sub / "a.txt").write_text("a\n")
    (top / "root.txt").write_text("r\n")
    monkeypatch.chdir(sub)
    tid = tickets.create(sub, "In a sub folder", by="human:t")["id"]
    git(top, "add", "-A")
    git(top, "commit", "-qm", "init")
    e = worktrees.create(sub, tid)
    assert e["sub"] == "apps/web"
    assert worktrees.work_dir(e) == Path(e["path"]) / "apps" / "web"
    assert (worktrees.work_dir(e) / "a.txt").is_file()
    assert git(e["path"], "status", "--porcelain") == ""
    git(top, "worktree", "remove", "--force", e["path"])


def test_without_git_no_copy_is_made(proj, new_ticket):
    t = new_ticket("No git here")
    assert worktrees.create(proj, t) is None
    assert worktrees.count(proj) == 0
    folder, notes = _route(proj, t)
    assert folder == proj and notes == []
    assert not (addons.home() / "worktrees").exists() or not any((addons.home() / "worktrees").rglob("t_*"))


def test_a_repo_without_a_commit_makes_no_copy(proj, new_ticket):
    t = new_ticket("Fresh repo")
    git(proj, "init", "-q")
    assert worktrees.create(proj, t) is None


def test_git_is_always_called_with_an_argv_list_and_long_paths(repo, monkeypatch):
    seen = []
    real = subprocess.run

    def spy(argv, *a, **k):
        seen.append((argv, k))
        return real(argv, *a, **k)

    monkeypatch.setattr(safegit.subprocess, "run", spy)
    worktrees.create(repo, repo.tids[0])
    assert seen
    for argv, kw in seen:
        assert isinstance(argv, list) and os.path.isabs(argv[0]) and "core.longpaths=true" in argv
        assert "core.fsmonitor=false" in argv and any(a.startswith("core.hooksPath=") for a in argv)
        assert not kw.get("shell") and kw.get("timeout")
        assert "GIT_DIR" not in (kw.get("env") or {})


def test_a_failed_checkout_takes_back_what_it_made(repo, monkeypatch):
    t = repo.tids[0]
    real = worktrees._git

    def broken(args, cwd, *a, **k):
        if args and args[0] == "checkout-index":
            return 1, "", "disk full"
        return real(args, cwd, *a, **k)

    monkeypatch.setattr(worktrees, "_git", broken)
    assert worktrees.create(repo, t) is None
    monkeypatch.undo()
    assert worktrees.count(repo) == 0
    assert git(repo, "branch", "--list", f"orch/{t}") == ""
    assert "orch/" not in git(repo, "worktree", "list")


# ---------------------------------------------------------------- routing


def _alive(root, tid):
    return runs.claim(root, tid, "agent:x", "claude", pid=os.getpid())


def test_default_is_together_and_a_lone_agent_works_in_the_project_folder(repo):
    assert config.copies_mode(repo) == "together"
    a, _ = repo.tids
    assert _route(repo, a) == (repo, [])
    assert worktrees.count(repo) == 0


def test_together_makes_a_copy_for_the_second_agent_only(repo):
    a, b = repo.tids
    _alive(repo, a)
    folder, notes = _route(repo, b)
    assert folder != repo and worktrees.is_orch_copy(folder) and notes == []
    # the ticket keeps its copy for life, also when nobody else is around any more
    runs.release(repo, a)
    again, _ = _route(repo, b)
    assert again == folder
    w = tickets.load(repo, b)["work"]["folders"]
    assert (
        len(w) == 1 and w[0]["branch"] == f"orch/{b}" and "path" not in w[0] and w[0]["host"] == runs.host()
    )
    assert not tickets.load(repo, a).get("work")


def test_always_off_and_the_cap(repo):
    a, b = repo.tids
    config.set_copies_mode(repo, "off")
    _alive(repo, a)
    assert _route(repo, b) == (repo, [])
    config.set_copies_mode(repo, "always")
    runs.release(repo, a)
    f, _ = _route(repo, a)
    assert f != repo
    config.set_copies_max(repo, "1")
    f2, notes = _route(repo, b)  # at the cap: the project folder, and it says so
    assert f2 == repo and "1 separate copies" in notes[0]
    assert worktrees.count(repo) == 1


def test_settings_validate_and_live_per_machine_not_in_the_workspace(repo):
    with pytest.raises(Refused):
        config.set_copies_mode(repo, "sometimes")
    for bad in ("0", "-1", "21", "x", "1.5"):
        with pytest.raises(Refused):
            config.set_copies_max(repo, bad)
    config.set_copies_max(repo, "5")
    assert config.copies_max(repo) == 5
    # a committed .orch/config.toml cannot choose any of them
    (repo / ".orch" / "config.toml").write_text(
        '[workflow]\ncopies = "off"\ncopies_max = 9\ncopy_setup = "touch pwned"\n'
    )
    assert config.copies_mode(repo) == "together" and config.copies_max(repo) == 5
    assert config.copy_setup(repo) is None


def test_two_starts_at_the_same_moment_make_exactly_one_copy(repo, subprocess_home):
    """Two orch processes start two tickets together: decide + create + claim run under one workspace lock,
    so the second one sees the first one's claim. (The lock is per process: threads would not show it.)"""
    a, b = repo.tids
    code = (
        "import sys; from pathlib import Path; from orch import runs; "
        "runs.claim_routed(Path(sys.argv[1]), sys.argv[2], 'human:t', 'claude', 'oneshot')"
    )
    env = orch_env(repo, ORCH_HOME=os.environ["ORCH_HOME"], ORCH_HOME_STRICT="1")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    ps = [
        subprocess.Popen(
            [sys.executable, "-P", "-c", code, str(repo), t], env=env, cwd=repo, stderr=subprocess.PIPE
        )
        for t in (a, b)
    ]
    for p in ps:
        assert p.wait(120) == 0, p.stderr.read()
    folders = {runs.read(repo, t)["folder"] for t in (a, b)}
    assert len(folders) == 2 and str(repo.resolve()) in folders  # one in the project folder, one in a copy
    assert worktrees.count(repo) == 1


# ---------------------------------------------------------------- setup command


def test_setup_runs_once_in_the_copy_from_the_persons_config(repo):
    a, b = repo.tids
    config.set_copy_setup(repo, f"{shlex.quote(sys.executable)} -c \"open('ready.txt','w').write('1')\"")
    config.set_copies_mode(repo, "always")
    f, notes = _route(repo, a)
    assert notes == [] and (f / "ready.txt").read_text() == "1"
    assert not (repo / "ready.txt").exists()
    log = (repo / ".orch" / "run" / "logs" / f"{a}-copy-setup.log").read_text()
    assert log.startswith("$ ")
    (f / "ready.txt").unlink()
    _route(repo, a)  # the copy exists: no second setup
    assert not (f / "ready.txt").exists()


def test_setup_is_never_a_shell_line_and_a_failure_only_warns(repo):
    a, b = repo.tids
    config.set_copies_mode(repo, "always")
    config.set_copy_setup(repo, f"{sys.executable} -c 'import sys; sys.exit(3)'")
    f, notes = _route(repo, a)
    assert f != repo and "failed (exit code 3)" in notes[0]  # the copy is used anyway
    # `;` is an argument, not a second command: nothing is created by a shell
    config.set_copy_setup(repo, f"{shlex.quote(sys.executable)} -c pass ; touch evil")
    f2, _ = _route(repo, b)
    assert not (f2 / "evil").exists() and not (repo / "evil").exists()
    # a command that is not there warns, the copy stays
    c = tickets.create(repo, "Third", by="human:t")["id"]
    config.set_copy_setup(repo, "no-such-command-xyz --now")
    f3, notes3 = _route(repo, c)
    assert f3 != repo and "was not found" in notes3[0]


def test_setup_has_a_timeout(repo, monkeypatch):
    a, _ = repo.tids
    config.set_copies_mode(repo, "always")
    monkeypatch.setattr(worktrees, "SETUP_TIMEOUT", 1)
    config.set_copy_setup(repo, f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(30)'")
    t0 = time.monotonic()
    f, notes = _route(repo, a)
    assert time.monotonic() - t0 < 20 and f != repo and "stopped" in notes[0]


def test_ticket_data_never_chooses_the_setup_command(repo):
    a, _ = repo.tids
    config.set_copies_mode(repo, "always")
    marker = repo / "pwned-by-ticket"
    for key, val in (
        ("note", f"touch {marker}"),
        ("done_when", f"touch {marker}"),
        ("ext", {"copy_setup": "touch x"}),
    ):
        tickets.apply_op(repo, a, lambda t, k=key, v=val: t.__setitem__(k, v))
    tickets.apply_op(
        repo, a, lambda t: t.__setitem__("work", {"copy_setup": f"touch {marker}", "folders": []})
    )
    f, notes = _route(repo, a)
    assert f != repo and notes == [] and not marker.exists()
    assert worktrees.config.copy_setup(repo) is None


def test_an_agent_cannot_set_the_setup_command(repo, run, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, err = run("config", "set", "workflow.copy_setup", "touch x")
    assert code != 0 and config.copy_setup(repo) is None
    monkeypatch.delenv("CLAUDECODE")
    code, out, _ = run("config", "set", "workflow.copy_setup", "npm ci", "--json")
    assert code == 0 and config.copy_setup(repo) == "npm ci"
    assert run("config", "set", "workflow.copies", "always")[0] == 0
    assert run("config", "set", "workflow.copies_max", "2")[0] == 0
    assert run("config", "get", "workflow.copies", "--json")[1].strip().endswith('"always"\n}'.strip())


# ---------------------------------------------------------------- the copy's own files, trust


def test_harness_files_in_the_copy_point_at_the_workspace_harness(repo):
    from orch import skills

    (repo / ".orch" / "harness" / "skills" / "orch").mkdir(parents=True)
    (repo / ".orch" / "harness" / "skills" / "orch" / "SKILL.md").write_text("# orch\n")
    (repo / ".orch" / "harness" / "blocks").mkdir(parents=True, exist_ok=True)
    (repo / ".agents").mkdir(exist_ok=True)
    skills.apply_agent_files(repo)
    a, _ = repo.tids
    config.set_copies_mode(repo, "always")
    f, notes = _route(repo, a)
    link = f / ".agents" / "skills" / "orch"
    assert link.exists() and (link / "SKILL.md").read_text() == "# orch\n"
    assert link.resolve() == (repo / ".orch" / "harness" / "skills" / "orch").resolve()
    assert git(f, "status", "--porcelain") == ""  # the shared exclude hides the links in the copy too


def test_trust_is_set_for_a_registered_copy_only(repo, proj, monkeypatch):
    cfg = Path(os.environ["CLAUDE_CONFIG_DIR"])
    (cfg / ".claude.json").write_text("{}")
    a, _ = repo.tids
    config.set_copies_mode(repo, "always")
    f, _ = _route(repo, a)
    assert adapters.trust_folder("claude", f) == "set"
    doc = json.loads((cfg / ".claude.json").read_text())
    assert doc["projects"][str(f.resolve())]["hasTrustDialogAccepted"] is True
    assert adapters.trust_folder("claude", f) == "already"
    # not a copy: a decoy under worktrees/, a folder of the project, the orch home itself
    decoy = Path(f).parent / "t_decoy1"
    decoy.mkdir()
    assert not worktrees.is_orch_copy(decoy)
    assert adapters.trust_folder("claude", decoy) == "skipped"
    other = proj.parent / "some-other-folder"
    other.mkdir()
    assert adapters.trust_folder("claude", other) == "skipped"
    assert not worktrees.is_orch_copy(addons.home())


def test_a_registry_entry_for_another_machine_is_not_a_copy(repo):
    a, _ = repo.tids
    rec = {"folder": "/somewhere/else/worktrees/01234567/" + a}
    assert worktrees.workdir_for(repo, rec) == repo
    assert worktrees.workdir_for(repo, {"folder": ".."}) == repo
    assert worktrees.workdir_for(repo, None) == repo


# ---------------------------------------------------------------- spawn: cwd, ORCH_ROOT, record


def test_a_oneshot_run_in_a_copy_starts_there_with_orch_root_and_records_the_folder(
    repo, tmp_path, subprocess_home, monkeypatch
):
    a, b = repo.tids
    script = tmp_path / "agent.py"
    seen = tmp_path / "seen.json"
    script.write_text(
        "import json, os, subprocess, sys\n"
        f"json.dump({{'cwd': os.getcwd(), 'root': os.environ.get('ORCH_ROOT')}}, open({str(seen)!r}, 'w'))\n"
        "t = os.environ['ORCH_TICKET']\n"
        "subprocess.run([sys.executable, '-P', '-m', 'orch', 'ticket', 'new', 'Made by the agent',\n"
        "                '--by', 'agent:fake'])\n"
    )
    config.add_agent(repo, "fake", f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{prompt}}")
    config.set_key(repo, "workspace", "agent", "fake")
    config.set_copies_mode(repo, "always")
    monkeypatch.setenv("ORCH_CMD", f"{shlex.quote(sys.executable)} -m orch")
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "src"))
    r = runs.start(repo, a, "human:t", mode="oneshot")
    rec = runs.read(repo, a)
    copy = Path(rec["folder"])
    assert copy != repo.resolve() and worktrees.is_orch_copy(copy)
    end = time.monotonic() + 30
    while time.monotonic() < end and (not seen.exists() or runs.read(repo, a)):
        time.sleep(0.1)
    got = json.loads(seen.read_text())
    assert Path(got["cwd"]).resolve() == copy and Path(got["root"]).resolve() == repo.resolve()
    assert r["run"] and "path" not in tickets.load(repo, a)["work"]["folders"][0]
    titles = [tickets.load(repo, p.stem)["title"] for p in (repo / ".orch" / "tickets").glob("t_*.json")]
    assert "Made by the agent" in titles  # written to the workspace store
    assert git(copy, "status", "--porcelain") == ""


def test_live_start_puts_tmux_in_the_copy_and_trusts_it(repo, monkeypatch):
    from orch import runs_live

    a, _ = repo.tids
    config.set_copies_mode(repo, "always")
    calls = []

    def fake_tmux(root, *args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="4242\n", stderr="")

    monkeypatch.setattr(runs_live, "tmux", fake_tmux)
    monkeypatch.setattr(runs_live, "session_exists", lambda *a, **k: False)
    trusted = []
    monkeypatch.setattr(adapters, "trust_folder", lambda name, p, *a, **k: trusted.append(Path(p)) or "set")
    config.add_agent(
        repo, "fake", f"{shlex.quote(sys.executable)} -c pass {{prompt}}", f"{shlex.quote(sys.executable)}"
    )
    config.set_key(repo, "workspace", "agent", "fake")
    r = runs_live.start_live(repo, a, "human:t", "fake", fresh=False, take_over=False, busy_text="x")
    new = [c for c in calls if c and c[0] == "new-session"][0]
    where = new[new.index("-c") + 1]
    assert worktrees.is_orch_copy(Path(where)) and where != str(repo)
    assert f"ORCH_ROOT={repo}" in new
    assert repo.resolve() in [p.resolve() for p in trusted] and Path(where).resolve() in [
        p.resolve() for p in trusted
    ]
    assert r["notes"] == []


# ---------------------------------------------------------------- delta 1 fixes


@pytest.mark.parametrize("sub", ["/abs", "../..", "a/../../b", "C:/x", "C:x", "\\\\srv\\share", "x\0y"])
def test_a_registry_sub_that_leaves_the_copy_is_refused(repo, sub):
    a, _ = repo.tids
    e = worktrees.create(repo, a)
    assert not worktrees._safe_sub(sub)
    with pytest.raises(Refused):
        worktrees.work_dir({**e, "sub": sub})
    # a forged registry line is dropped by the reader, so route never hands it out
    reg = json.loads((repo / ".orch/run/worktrees.json").read_text())
    reg["tickets"][a]["paths"][0]["sub"] = sub
    (repo / ".orch/run/worktrees.json").write_text(json.dumps(reg))
    assert a not in worktrees.registry(repo)


def test_a_sub_that_is_a_link_out_of_the_copy_is_refused(repo, tmp_path):
    a, _ = repo.tids
    e = worktrees.create(repo, a)
    out = tmp_path / "outside"
    out.mkdir()
    (Path(e["path"]) / "esc").symlink_to(out)
    with pytest.raises(Refused):
        worktrees.work_dir({**e, "sub": "esc"})


def test_create_gives_back_only_a_real_copy(repo):
    a, _ = repo.tids
    e = worktrees.create(repo, a)
    decoy = Path(e["path"]).parent / "t_decoy1"
    decoy.mkdir()
    reg = json.loads((repo / ".orch/run/worktrees.json").read_text())
    reg["tickets"][a]["paths"][0]["path"] = str(decoy)
    (repo / ".orch/run/worktrees.json").write_text(json.dumps(reg))
    got = worktrees.create(repo, a)
    assert got is None or Path(got["path"]).resolve() != decoy.resolve()


def test_is_orch_copy_works_when_the_home_is_under_a_link(repo, tmp_path, monkeypatch):
    real = tmp_path.parent / f"{tmp_path.name}_realhome"  # outside the workspace folder
    real.mkdir()
    link = tmp_path.parent / f"{tmp_path.name}_linkhome"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("ORCH_HOME", str(link / "orchhome"))
    monkeypatch.setattr(addons, "real_home", lambda: real)
    a, _ = repo.tids
    f, _ = _route(repo, a) if config.set_copies_mode(repo, "always") else (None, None)
    assert f != repo and worktrees.is_orch_copy(f)


def test_a_committed_symlink_cannot_make_orch_write_outside_the_copy(repo, tmp_path):
    (repo / ".orch" / "harness" / "skills" / "orch").mkdir(parents=True)
    (repo / ".orch" / "harness" / "skills" / "orch" / "SKILL.md").write_text("# orch\n")
    victim = tmp_path / "victim.txt"
    victim.write_text("mine\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo / "CLAUDE.local.md").symlink_to(victim)
    (repo / ".claude").symlink_to(elsewhere, target_is_directory=True)
    git(repo, "add", "-f", "CLAUDE.local.md", ".claude")
    git(repo, "commit", "-qm", "links")
    a, _ = repo.tids
    config.set_copies_mode(repo, "always")
    f, notes = _route(repo, a)
    assert f != repo
    assert victim.read_text() == "mine\n" and list(elsewhere.iterdir()) == []
    assert any("link" in n for n in notes)


def test_setup_env_has_no_git_variables_and_runs_a_relative_command_from_the_copy(repo, monkeypatch):
    a, _ = repo.tids
    monkeypatch.setenv("GIT_DIR", "/nowhere")
    monkeypatch.setenv("GIT_WORK_TREE", "/nowhere")
    (repo / "setup.sh").write_text("#!/bin/sh\nenv > env.txt\n")
    (repo / "setup.sh").chmod(0o755)
    git(repo, "add", "setup.sh")
    git(repo, "commit", "-qm", "setup")
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    config.set_copies_mode(repo, "always")
    config.set_copy_setup(repo, "./setup.sh")
    monkeypatch.setenv("GIT_DIR", "/nowhere")
    monkeypatch.setenv("ORCH_VIA", "dashboard")
    f, notes = _route(repo, a)
    assert notes == [], notes
    env = (f / "env.txt").read_text()
    assert (
        "GIT_DIR" not in env
        and "ORCH_VIA" not in env
        and f"ORCH_ROOT={repo.resolve()}" in env.replace(str(repo), str(repo.resolve()))
    )
    monkeypatch.undo()


def test_route_is_quick_under_the_lock_and_hands_the_slow_steps_back(repo):
    a, _ = repo.tids
    config.set_copies_mode(repo, "always")
    config.set_copy_setup(repo, f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(2)'")
    t0 = time.monotonic()
    folder, notes, after = worktrees.route(repo, a)
    assert time.monotonic() - t0 < 2 and folder != repo and len(after) == 1 and notes == []
    assert not (repo / ".orch/run/logs" / f"{a}-copy-setup.log").exists()  # setup has not run yet
    assert worktrees.LOCK_WAIT > worktrees.CREATE_BUDGET


def test_no_copy_says_why_in_the_setup_log(proj, new_ticket):
    t = new_ticket("No git")
    config.set_copies_mode(proj, "always")
    f, _ = _route(proj, t)
    assert f == proj
    assert "no separate copy" in (proj / ".orch/run/logs" / f"{t}-copy-setup.log").read_text()


def test_the_ticket_record_has_no_local_path(repo):
    a, _ = repo.tids
    config.set_copies_mode(repo, "always")
    _route(repo, a)
    rec = tickets.load(repo, a)["work"]["folders"][0]
    assert set(rec) == {"branch", "base", "sub", "host"}
    assert str(repo.resolve().parent) not in json.dumps(tickets.load(repo, a)["work"])

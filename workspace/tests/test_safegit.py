"""safegit: the one way orch runs git where a repo's own config, hooks and attributes are not trusted."""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from orch import addons, safegit, worktrees

SRC = Path(__file__).resolve().parents[1] / "src" / "orch"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX shell stubs")


def plain_git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env, check=False)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def sh(path, body):
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture(autouse=True)
def fresh_exe(monkeypatch):
    monkeypatch.setattr(safegit, "_exe", None)


@pytest.fixture
def hostile(tmp_path):
    """A repository whose config, attributes and hooks would run a program for every git step."""
    marker = tmp_path / "PWNED"
    r = tmp_path / "hostile"
    r.mkdir()
    plain_git(r, "init", "-q")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    (r / ".gitattributes").write_text("*.txt filter=evil\n*.md filter=evil2\n")
    (r / "a.txt").write_text("hello\n")
    (r / "b.md").write_text("bye\n")
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "init")
    for name in ("post-checkout", "reference-transaction", "post-commit", "post-merge", "pre-commit"):
        sh(r / ".git" / "hooks" / name, f"touch {marker}.{name}")
    cat = f"touch {marker}.filter; cat"
    plain_git(r, "config", "filter.evil.smudge", cat)
    plain_git(r, "config", "filter.evil.clean", cat)
    plain_git(r, "config", "filter.evil.process", f"touch {marker}.process")
    plain_git(r, "config", "filter.evil2.smudge", cat)
    # a driver that arrives through an include, as agent-written config can
    inc = tmp_path / "inc.cfg"
    inc.write_text(f'[filter "evil2"]\n\tprocess = touch {marker}.included\n')
    plain_git(r, "config", "include.path", str(inc))
    plain_git(r, "config", "core.fsmonitor", f"touch {marker}.fsmonitor; echo")
    return r, marker


def marks(marker):
    return sorted(p.name for p in marker.parent.glob(marker.name + "*"))


def test_hostile_repo_runs_nothing_through_safegit(hostile, tmp_path):
    r, marker = hostile
    wt = tmp_path / "wt"
    assert safegit.run(["worktree", "add", "--no-checkout", "-b", "x", str(wt), "HEAD"], r)[0] == 0
    assert safegit.run(["read-tree", "HEAD"], wt)[0] == 0
    assert safegit.run(["checkout-index", "-a", "-f", "-u"], wt, filters=True)[0] == 0
    assert (wt / "a.txt").read_text() == "hello\n"  # content untouched by the neutralized driver
    assert safegit.run(["status", "--porcelain"], wt, read_only=True)[1] == ""
    assert safegit.run(["worktree", "remove", "--force", str(wt)], r)[0] == 0
    assert safegit.run(["branch", "-D", "x"], r)[0] == 0
    assert marks(marker) == []


def test_plain_git_would_have_run_them(hostile, tmp_path):
    """The control: without safegit the same steps do create the marker (the test above proves something)."""
    r, marker = hostile
    wt = tmp_path / "wt"
    plain_git(r, "worktree", "add", "--no-checkout", "-b", "x", str(wt), "HEAD")
    plain_git(wt, "read-tree", "HEAD")
    subprocess.run(["git", "checkout-index", "-a", "-f", "-u"], cwd=wt, capture_output=True)
    assert marks(marker)


def test_creating_preparing_and_dropping_a_copy_never_runs_repo_code(hostile, proj, monkeypatch):
    r, marker = hostile
    # the hostile repo as a workspace
    (r / ".orch" / "tickets").mkdir(parents=True)
    (r / ".orch" / "tickets" / "t_abc123.json").write_text("{}")
    plain_git(r, "add", "-A")
    subprocess.run(["git", "commit", "-qm", "orch", "--no-verify"], cwd=r, capture_output=True)
    for p in marker.parent.glob(marker.name + "*"):
        p.unlink()
    monkeypatch.chdir(r)
    addons.workspace_id(r, create=True)
    e = worktrees.create(r, "t_abc123")
    assert e is not None and (Path(e["path"]) / "a.txt").read_text() == "hello\n"
    worktrees._drop_partial(r, Path(e["path"]), e["branch"], True)
    assert marks(marker) == []


def test_every_call_carries_the_hardening(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(
        safegit, "_raw", lambda argv, cwd, timeout, data=None: seen.append((argv, cwd)) or (0, "", "")
    )
    monkeypatch.setenv("GIT_DIR", "/elsewhere")
    monkeypatch.setattr(safegit, "git_exe", lambda cwd: "/usr/bin/git")
    safegit.run(["status"], tmp_path, read_only=True)
    argv = seen[-1][0]
    assert "--no-optional-locks" in argv and "core.fsmonitor=false" in argv and "protocol.allow=never" in argv
    assert any(a.startswith("core.hooksPath=") and a.endswith("/empty-hooks") for a in argv)
    assert "core.longpaths=true" in argv and "core.untrackedCache=false" in argv
    assert "GIT_DIR" not in safegit.env() and safegit.env()["GIT_TERMINAL_PROMPT"] == "0"


def test_empty_hooks_folder_is_kept_empty():
    d = safegit.empty_hooks()
    (d / "post-checkout").write_text("#!/bin/sh\ntouch x\n")
    (d / "sub").mkdir()
    (d / "sub" / "f").write_text("x")
    assert list(safegit.empty_hooks().iterdir()) == []


# ---------------------------------------------------------------- which git


def test_a_git_in_the_repo_or_in_a_path_entry_inside_it_is_never_used(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    (proj / "bin").mkdir(parents=True)
    marker = tmp_path / "FAKE-GIT-RAN"
    sh(proj / "git", f"touch {marker}")
    sh(proj / "bin" / "git", f"touch {marker}")
    real = Path(safegit.subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip())
    monkeypatch.setenv(
        "PATH", os.pathsep.join(["", ".", "relative/bin", str(proj / "bin"), str(real.parent)])
    )
    monkeypatch.chdir(proj)
    assert safegit.git_exe(proj) == str(real)
    rc, out, _ = safegit.run(["--version"], proj)
    assert rc == 0 and out.startswith("git version") and not marker.exists()
    # only a fake one on the PATH: refused, nothing runs
    monkeypatch.setattr(safegit, "_exe", None)
    monkeypatch.setenv("PATH", str(proj / "bin"))
    assert safegit.run(["--version"], proj)[0] == 127 and not marker.exists()
    # a cached git that lies inside the folder we work in is refused too
    monkeypatch.setattr(safegit, "_exe", str(proj / "bin" / "git"))
    assert safegit.git_exe(proj) is None


# ---------------------------------------------------------------- lint


# Modules that still start git themselves. This list must shrink to zero: filesig.py (B8) and B9's work-check
# join it until they migrate onto safegit.
ALLOW = {"addons.py", "harness.py", "safegit.py"}


def test_no_module_starts_git_except_safegit_and_the_to_migrate_list():
    rx = re.compile(r"""["']git["']""")
    bad = []
    for f in sorted(SRC.rglob("*.py")):
        if f.name in ALLOW:
            continue
        text = f.read_text(encoding="utf-8")
        if rx.search(text) and re.search(r"subprocess|Popen|os\.exec|os\.spawn|os\.system", text):
            bad.append(str(f.relative_to(SRC)))
    assert bad == [], f"run git through orch.safegit, not directly: {bad}"

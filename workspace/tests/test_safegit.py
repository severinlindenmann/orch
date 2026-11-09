"""safegit: the one way orch runs git where a repo's own config, hooks and attributes are not trusted."""

import ast
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
    monkeypatch.setattr(safegit, "_exes", {})


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
        safegit,
        "_raw",
        lambda argv, cwd, timeout, data=None, root=None: seen.append((argv, cwd)) or (0, "", ""),
    )
    monkeypatch.setenv("GIT_DIR", "/elsewhere")
    monkeypatch.setattr(safegit, "git_exe", lambda cwd, root=None: "/usr/bin/git")
    safegit.run(["status"], tmp_path, read_only=True)
    argv = seen[-1][0]
    assert "--no-optional-locks" in argv and "core.fsmonitor=false" in argv and "protocol.allow=never" in argv
    assert any(a.startswith("core.hooksPath=") and "/no-hooks/" in a for a in argv)
    assert "core.longpaths=true" in argv and "core.untrackedCache=false" in argv
    assert "GIT_DIR" not in safegit.env() and safegit.env()["GIT_TERMINAL_PROMPT"] == "0"


def test_hooks_path_is_a_fresh_path_that_does_not_exist():
    a, b = safegit._no_hooks(), safegit._no_hooks()
    assert a != b and not Path(a).exists() and not Path(b).exists()
    assert Path(a).parent == addons.home() / "no-hooks"


def test_sentinel_empty_driver_values_really_prevent_execution(tmp_path):
    """git might spawn "" for an empty smudge/process: it does not (no marker, no error, same bytes)."""
    r = tmp_path / "r"
    r.mkdir()
    plain_git(r, "init", "-q")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    (r / ".gitattributes").write_text("*.txt filter=a\n*.md filter=b\n*.c merge=m\n")
    for n, c in (("a.txt", "x\n"), ("b.md", "y\n")):
        (r / n).write_text(c)
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "i")
    m = tmp_path / "MARK"
    plain_git(r, "config", "filter.a.smudge", f"touch {m}.smudge; cat")
    plain_git(r, "config", "filter.b.process", f"touch {m}.process")
    plain_git(r, "config", "merge.m.driver", f"touch {m}.merge")
    wt = tmp_path / "wt"
    assert (
        safegit.run(["worktree", "add", "--no-checkout", "-b", "q", str(wt), "HEAD"], r, filters=False)[0]
        == 0
    )
    assert safegit.run(["read-tree", "HEAD"], wt, filters=False)[0] == 0
    rc, out, err = safegit.run(["checkout-index", "-a", "-f", "-u"], wt)
    assert (
        rc == 0 and err == "" and (wt / "a.txt").read_text() == "x\n" and (wt / "b.md").read_text() == "y\n"
    )
    assert not list(tmp_path.glob("MARK*"))
    args = safegit.driver_args(r)
    assert "filter.a.smudge=" in args and "filter.b.process=" in args and "merge.m.driver=" in args


def test_it_fails_closed_when_the_drivers_cannot_be_listed(hostile, tmp_path, monkeypatch):
    r, marker = hostile
    monkeypatch.setattr(safegit, "driver_args", lambda *a, **k: None)
    wt = tmp_path / "wt"
    assert (
        safegit.run(["worktree", "add", "--no-checkout", "-b", "x", str(wt), "HEAD"], r, filters=False)[0]
        == 0
    )
    assert safegit.run(["read-tree", "HEAD"], wt, filters=False)[0] == 0
    rc, _, err = safegit.run(["checkout-index", "-a", "-f", "-u"], wt)
    assert rc == safegit.REFUSED and "filters" in err and marks(marker) == []
    assert safegit.run(["rev-parse", "HEAD"], wt, filters=False)[0] == 0  # no file content: still fine


def test_diff_like_calls_get_no_ext_diff_and_the_future_defaults(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(
        safegit, "_raw", lambda argv, cwd, timeout, data=None, root=None: seen.append(argv) or (0, "", "")
    )
    safegit.run(["diff", "HEAD"], tmp_path, filters=False)
    argv = seen[-1]
    assert argv[argv.index("diff") :] == ["diff", "--no-ext-diff", "--no-textconv", "HEAD"]
    for want in (
        "diff.external=",
        "commit.gpgSign=false",
        "tag.gpgSign=false",
        "core.sshCommand=",
        "credential.helper=",
    ):
        assert want in argv


def test_the_cache_is_per_set_of_avoided_folders(tmp_path, monkeypatch):
    real = Path(safegit.subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip())
    monkeypatch.setenv("PATH", str(real.parent))
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert safegit.git_exe(a, a) == str(real) and safegit.git_exe(b, b) == str(real)
    assert len(safegit._exes) >= 2
    # a root that contains the PATH entry: that git is not used
    assert safegit.git_exe(real.parent, real.parent) is None


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
    monkeypatch.setattr(safegit, "_exes", {})
    monkeypatch.setenv("PATH", str(proj / "bin"))
    assert safegit.run(["--version"], proj, filters=False)[0] == 127 and not marker.exists()
    assert safegit.run(["status"], proj)[0] in (125, 127) and not marker.exists()


# ---------------------------------------------------------------- lint (AST)

# Modules that still start git themselves. MUST SHRINK TO ZERO. filesig.py (B8) and B9's work-check join it
# until they migrate onto safegit.
ALLOW = set(safegit.LEGACY) | {"safegit.py"}
_SPAWN = re.compile(
    r"^(subprocess\.\w+|os\.(exec\w+|spawn\w+|posix_spawn\w*|system|popen)|asyncio\.create_subprocess_\w+)$"
)


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _mentions_git(node, git_names):
    for n in ast.walk(node):
        if (
            isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and re.fullmatch(r"(?:.*[\\/])?git(\.exe)?", n.value)
        ):
            return True
        if isinstance(n, ast.Name) and n.id in git_names:
            return True
        if isinstance(n, ast.Call) and _dotted(n.func) == "shutil.which" and n.args:
            if _mentions_git(n.args[0], git_names):
                return True
    return False


def git_spawns(source: str) -> list[int]:
    """Line numbers of process starts whose argv mentions git (a literal, a name bound to one, shutil.which),
    and of any use of harness._git_env."""
    tree = ast.parse(source)
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and _mentions_git(n.value, set()):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _SPAWN.match(_dotted(n.func)):
            if any(_mentions_git(a, names) for a in [*n.args, *[k.value for k in n.keywords]]):
                bad.append(n.lineno)
        if isinstance(n, ast.Attribute) and n.attr == "_git_env":
            bad.append(n.lineno)
    return sorted(set(bad))


@pytest.mark.parametrize(
    "src,hit",
    [
        ('import subprocess\nsubprocess.run(["git", "status"])', True),
        ('import subprocess\nG = "git"\nsubprocess.Popen([G, "x"])', True),
        ('import subprocess, shutil\nsubprocess.run([shutil.which("git"), "x"])', True),
        ('import os\nos.execv("/usr/bin/git", ["git"])', True),
        ('import asyncio\nasyncio.create_subprocess_exec("git")', True),
        ("from orch import harness\nharness._git_env()", True),
        ('import subprocess\nsubprocess.run(["ls"])', False),
        ('x = ["git", "status"]', False),
    ],
)
def test_the_lint_itself_catches_git_spawns(src, hit):
    assert bool(git_spawns(src)) is hit


def test_no_module_starts_git_except_safegit_and_the_to_migrate_list():
    bad = {}
    for f in sorted(SRC.rglob("*.py")):
        if f.name in ALLOW:
            continue
        lines = git_spawns(f.read_text(encoding="utf-8"))
        if lines:
            bad[str(f.relative_to(SRC))] = lines
    assert bad == {}, f"run git through orch.safegit, not directly: {bad}"


def test_nothing_that_prepares_a_copy_runs_git_with_a_copy_as_cwd():
    """worktrees.py, skills.apply_copy_files and the harness functions it calls write files; the only git they
    may start is through safegit (the lint above), and harness.py's git helpers are not used for copies."""
    text = (SRC / "skills.py").read_text(encoding="utf-8")
    a = text.index("def apply_copy_files")
    body = text[a : text.index("\ndef ", a + 10)]
    assert "_git" not in body and "protect_local" not in body and "exclude_set" not in body

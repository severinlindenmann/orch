"""safegit: the one way orch runs git where a repo's own config, hooks and attributes are not trusted."""

import ast
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

from orch import addons, humanproof, safegit, worktrees
from orch.errors import Refused

SRC = Path(__file__).resolve().parents[1] / "src" / "orch"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX shell stubs")


def plain_git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    # (the test's own helper: a hostile core.fsmonitor in a fixture must not break its setup commands)
    p = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def _exe(where):
    exe = safegit.git_exe(where, where)
    assert exe is not None
    return Path(exe)


def sh(path, body):
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture(autouse=True)
def fresh_exe(monkeypatch):
    monkeypatch.setattr(safegit, "_exes", {})


@pytest.fixture
def filters_gate_off(monkeypatch):
    """For tests of other hardening (argv shape, root checks) that use filters=False only to skip the driver
    listing with any subcommand: the filters=False allowlist itself is tested at the end of this file."""
    monkeypatch.setattr(safegit, "filters_off_refusal", lambda args: None)


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
    assert safegit.run(["add", "-A"], r)[0] == 0  # plain git would run the hostile filter driver here
    assert safegit.run(["commit", "-qm", "orch"], r)[0] == 0
    for p in marker.parent.glob(marker.name + "*"):
        p.unlink()
    monkeypatch.chdir(r)
    # the hostile repo lives under pytest's tmp dir, not ~/.orch-test: give it the usable guarded home
    # that the other worktree tests use (the real pairing rules are tested in test_humanproof.py)
    monkeypatch.setattr(humanproof, "guarded_home", lambda root: Path(os.environ["ORCH_HOME"]))
    addons.workspace_id(r, create=True)
    e = worktrees.create(r, "t_abc123")
    assert e is not None and (Path(e["path"]) / "a.txt").read_text() == "hello\n"
    worktrees._drop_partial(r, Path(e["path"]), e["branch"], True, e["base"])
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
    safegit.run(["rev-parse", "HEAD"], tmp_path, read_only=True, filters=False)
    argv = seen[-1][0]
    assert "--no-optional-locks" in argv and "core.fsmonitor=false" in argv and "protocol.allow=never" in argv
    assert any(a == "core.hooksPath=/dev/null" for a in argv)
    assert "core.longpaths=true" in argv and "core.untrackedCache=false" in argv
    e = safegit.env(tmp_path, None, "/bin/true")
    assert "GIT_DIR" not in e and e["GIT_TERMINAL_PROMPT"] == "0"


def test_hooks_path_is_a_device_and_planted_symlinks_and_folders_are_never_used(
    hostile, tmp_path, monkeypatch
):
    import ntpath

    assert safegit._no_hooks() == ("/dev/null" if os.name != "nt" else "//./NUL")
    with monkeypatch.context() as m:
        m.setattr(safegit.os, "name", "nt")  # simulated Windows: the absolute device path
        win = safegit._no_hooks()
    assert win == "//./NUL" and ntpath.isabs(win)
    r, marker = hostile
    # hooks planted where earlier versions looked: <tempdir>/orch-no-hooks as a folder AND as a symlink to a
    # folder of hooks
    hooks = tmp_path / "evil-hooks"
    hooks.mkdir()
    for n in ("post-checkout", "reference-transaction"):
        sh(hooks / n, f"touch {marker}.{n}")
    shared = Path(tempfile.gettempdir()) / "orch-no-hooks"
    planted = []
    if not shared.exists() and not shared.is_symlink():
        shared.symlink_to(hooks, target_is_directory=True)
        planted.append(shared)
    try:
        wt = tmp_path / "wt"
        assert (
            safegit.run(["worktree", "add", "--no-checkout", "-b", "x", str(wt), "HEAD"], r, filters=False)[0]
            == 0
        )
        assert safegit.run(["read-tree", "HEAD"], wt)[0] == 0
        assert safegit.run(["checkout-index", "-a", "-f", "-u"], wt)[0] == 0
        assert safegit.run(["worktree", "remove", "--force", str(wt)], r)[0] == 0
        assert safegit.run(["branch", "-D", "x"], r, filters=False)[0] == 0
        assert marks(marker) == []  # neither the planted links/folders nor the repo's own .git/hooks ran
    finally:
        for link in planted:
            link.unlink()


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
    assert safegit.run(["read-tree", "HEAD"], wt)[0] == 0
    rc, out, err = safegit.run(["checkout-index", "-a", "-f", "-u"], wt)
    assert (
        rc == 0 and err == "" and (wt / "a.txt").read_text() == "x\n" and (wt / "b.md").read_text() == "y\n"
    )
    assert not list(tmp_path.glob("MARK*"))
    args = safegit.driver_args(r)
    pairs = dict(args)
    assert pairs["filter.a.smudge"] == "" and pairs["filter.b.process"] == ""
    assert pairs["merge.m.driver"].strip("'").endswith("/false")


@pytest.mark.usefixtures("filters_gate_off")
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


@pytest.mark.usefixtures("filters_gate_off")
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
        "merge.autoStash=false",
        "rerere.enabled=false",
        "tag.gpgSign=false",
        "core.sshCommand=",
        "credential.helper=",
    ):
        assert want in argv


def test_the_cache_is_per_set_of_avoided_folders(tmp_path, monkeypatch):
    real = _exe(tmp_path)
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
    real = _exe(tmp_path)
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join(["", ".", "relative/bin", str(proj / "bin"), str(real.parent), "/usr/bin", "/bin"]),
    )
    monkeypatch.chdir(proj)
    assert safegit.git_exe(proj) == str(real)
    rc, out, _ = safegit.run(["--version"], proj, filters=False)
    assert rc == 0 and out.startswith("git version") and not marker.exists()
    # only a fake one on the PATH: refused, nothing runs
    monkeypatch.setattr(safegit, "_exes", {})
    monkeypatch.setenv("PATH", str(proj / "bin"))
    assert safegit.run(["--version"], proj, filters=False)[0] in (125, 127) and not marker.exists()
    assert safegit.run(["status"], proj)[0] in (125, 127) and not marker.exists()


# ---------------------------------------------------------------- lint (AST)

# Modules that still start git themselves. MUST SHRINK TO ZERO (empty since B11b: filesig, work-check and
# harness run git through safegit.run / run_bytes).
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


_GIT_NAME = re.compile(r"git(\.exe)?", re.IGNORECASE)
_JOINERS = {"os.path.join", "pathlib.Path", "Path", "PurePath", "pathlib.PurePath", "shutil.which"}
_INTERNALS = {"git_exe", "_exes", "hardened"}  # safegit internals nobody else may touch


def _fold(node, env) -> set[str] | None:
    """The strings an expression can be, when they are constants: literals, "a" + "b", f-strings, `x if c
    else y` (both branches), and names bound (transitively) to such values. None = not constant."""
    if isinstance(node, ast.Constant):
        return {node.value} if isinstance(node.value, str) else None
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.NamedExpr):
        return _fold(node.value, env)
    if isinstance(node, ast.IfExp):
        a, b = _fold(node.body, env), _fold(node.orelse, env)
        return (a | b) if a is not None and b is not None else (a or b)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _fold(node.left, env), _fold(node.right, env)
        return {x + y for x in a for y in b} if a is not None and b is not None else None
    if isinstance(node, ast.JoinedStr):
        out = {""}
        for v in node.values:
            part = _fold(v.value if isinstance(v, ast.FormattedValue) else v, env)
            if part is None:
                return None
            out = {x + y for x in out for y in part}
        return out
    return None


def _assigned(n, env):
    """(name, value-node) pairs bound by one statement: `x = v`, `x: T = v`, `(x := v)`, `a, b = v1, v2`."""
    if isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name):
                yield t.id, n.value
            elif isinstance(t, (ast.Tuple, ast.List)) and isinstance(n.value, (ast.Tuple, ast.List)):
                for tt, vv in zip(t.elts, n.value.elts, strict=False):
                    if isinstance(tt, ast.Name):
                        yield tt.id, vv
    elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None:
        yield n.target.id, n.value
    elif isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name):
        yield n.target.id, n.value


def _bindings(tree) -> dict[str, set[str]]:
    """name -> constant strings of every constant binding in the module (any scope), until stable."""
    env: dict[str, set[str]] = {}
    for _ in range(8):
        changed = False
        for n in ast.walk(tree):
            for name, node in _assigned(n, env):
                val = _fold(node, env)
                if val is not None and not val <= env.get(name, set()):
                    env[name] = env.get(name, set()) | val
                    changed = True
        if not changed:
            break
    return env


_GIT_PART = re.compile(r"[/\\]git(\.exe)?$", re.IGNORECASE)  # a path ending in git (a bare "git" is no path)


def _git_fstring(node) -> bool:
    """An f-string that ends in a placeholder + the constant "git"/"git.exe" (f"{d}{os.sep}git")."""
    return (
        isinstance(node, ast.JoinedStr)
        and len(node.values) > 1
        and isinstance(node.values[-1], ast.Constant)
        and bool(_GIT_NAME.fullmatch(str(node.values[-1].value)))
    )


def _is_git(node, env) -> bool:
    vals = _fold(node, env)
    return bool(vals) and any(_GIT_NAME.fullmatch(v) for v in vals)


def git_path_builders(source: str) -> list[int]:
    """Line numbers where a module OTHER than safegit finds or builds the path of the git program, under any
    function name (B9's work-check did it with its own PATH loop, then ran the resolved file; the spawn check
    cannot tie that to git). Flagged: a constant that can be "git"/"git.exe" (a literal, "gi" + "t", an
    f-string, `"git.exe" if nt else "git"`, or a name bound to one, transitively) used in os.path.join,
    Path(...), .joinpath, `/` or shutil.which; any use of safegit internals (git_exe, _exes, hardened) as a
    call, attribute, import, alias or getattr string; and find_exe("git") also through an import alias.
    Also: any string constant (or f-string part) that ends in `/git`, `\\git` or `/git.exe` (f"{d}/git",
    "%s/git" % d), `x + "git"` and `sep.join([..., "git"])`.
    A guardrail, not a boundary. Known false positives: names are tracked per module, not per scope (a global
    `x = "git"` taints every `x` in the file), and any attribute or call NAMED hardened / *git_exe* is flagged
    whatever object it belongs to. Known gaps: a path built from data that is not a constant in the file."""
    tree = ast.parse(source)
    env = _bindings(tree)
    find_aliases = {"find_exe"}
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[-1] == "safegit":
            for a in n.names:
                if a.name in _INTERNALS:
                    bad.append(n.lineno)
                if a.name == "find_exe":
                    find_aliases.add(a.asname or a.name)
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and _GIT_PART.search(n.value):
            bad.append(n.lineno)
        elif _git_fstring(n):
            bad.append(n.lineno)
        elif isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.Add)) and _is_git(n.right, env):
            bad.append(n.lineno)
        elif isinstance(n, ast.Attribute) and n.attr in _INTERNALS:
            bad.append(n.lineno)
        elif isinstance(n, ast.Call):
            name = _dotted(n.func) or (n.func.attr if isinstance(n.func, ast.Attribute) else "")
            last = name.rsplit(".", 1)[-1]
            args = [*n.args, *[k.value for k in n.keywords]]
            if (name in _JOINERS or last == "joinpath") and any(_is_git(a, env) for a in args):
                bad.append(n.lineno)
            elif last == "join" and any(
                isinstance(a, (ast.List, ast.Tuple)) and any(_is_git(e, env) for e in a.elts) for a in args
            ):
                bad.append(n.lineno)
            elif "git_exe" in last or last in _INTERNALS:
                bad.append(n.lineno)
            elif last in find_aliases and n.args and _is_git(n.args[0], env):
                bad.append(n.lineno)
            elif name == "getattr" and len(n.args) >= 2 and (_fold(n.args[1], env) or set()) & _INTERNALS:
                bad.append(n.lineno)
    return sorted(set(bad))


def git_spawns(source: str) -> list[int]:
    """Line numbers of process starts whose argv mentions git (a literal, a name bound to one, shutil.which),
    and of any use of harness._git_env, and of building git's path (git_path_builders)."""
    tree = ast.parse(source)
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and _mentions_git(n.value, set()):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
    bad = list(git_path_builders(source))
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _SPAWN.match(_dotted(n.func)):
            if any(_mentions_git(a, names) for a in [*n.args, *[k.value for k in n.keywords]]):
                bad.append(n.lineno)
        if isinstance(n, ast.Attribute) and n.attr == "_git_env":
            bad.append(n.lineno)
    return sorted(set(bad))


# B9's work-check as it was before B11b: its own PATH loop for git, then a subprocess of the resolved file.
_OLD_WORKCHECK = """
import os, subprocess
def _git_exe(root):
    name = "git.exe" if os.name == "nt" else "git"
    for d in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(d, name)
        if os.path.isfile(cand):
            return cand
def _git(root, args):
    exe = _git_exe(root)
    return subprocess.run([exe, *args], cwd=root)
"""


_RENAMED = """
import os, subprocess
def _find_tool(root):
    name = "git.exe" if os.name == "nt" else "git"
    for d in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(d, name)
        if os.path.isfile(cand):
            return cand
def _run(root, args):
    tool = _find_tool(root)
    return subprocess.run([tool, *args], cwd=root)
"""


@pytest.mark.parametrize(
    "src",
    [
        _RENAMED,  # the old work-check with the function renamed: only the IfExp name reaches the join
        'import os\nn = "git.exe" if os.name == "nt" else "git"\np = os.path.join(d, n)',
        'import os\na = "git"\nb = a\nc = b\nos.path.join(d, c)',  # transitive
        'import os\np = os.path.join(d, "gi" + "t")',  # folded concatenation
        "import os\np = os.path.join(d, f\"gi{'t'}\")",  # f-string with a constant placeholder
        'import os\np = os.path.join(d, f"git")',
        'import shutil\nn = "git"\nx = shutil.which(n)',
        'from pathlib import Path\nn = "git"\np = Path(d) / n',
        "from orch.safegit import git_exe as g\ng(cwd)",
        "from orch.safegit import _exes",
        "from orch.safegit import hardened",
        'from orch import safegit\nf = getattr(safegit, "git_exe")',
        'from orch import safegit\nn = "hard" + "ened"\nf = getattr(safegit, n)',
        "from orch import safegit\nsafegit._exes.clear()",
        "from orch import safegit\nsafegit.hardened(cwd)",
        'from orch.safegit import find_exe as fe\nfe("git", set())',
        'import os\np = f"{d}/git"',
        'import os\np = f"{d}{os.sep}git"',
        'import os\np = f"{d}{os.sep}git.exe"',
        'import os\np = "%s/git" % d',
        'import os\np = d + os.sep + "git"',
        'p = "/".join([d, "git.exe"])',
        'import os\nn: str = "git"\nos.path.join(d, n)',  # annotated assignment
        'import os\nos.path.join(d, (n := "git"))',  # walrus
        'import os\na, b = "git", "x"\nos.path.join(d, a)',  # tuple unpacking
        'import os\np = "C:\\\\tools\\\\git.exe"',
    ],
)
def test_the_lint_flags_every_way_of_finding_git(src):
    assert git_path_builders(src)


def test_the_old_workcheck_pattern_is_flagged():
    assert git_spawns(_OLD_WORKCHECK)  # the function name, and the run of the resolved exe
    # each ingredient alone is enough
    assert git_path_builders('import os\nname = "git"\np = os.path.join("/usr/bin", "git")')
    assert git_path_builders('from pathlib import Path\np = Path("/usr/bin") / "git.exe"')
    assert git_path_builders('from pathlib import Path\np = Path("/usr/bin").joinpath("git")')
    assert git_path_builders("from orch import safegit\nx = safegit.git_exe(cwd)")
    assert git_path_builders('from orch import safegit\nsafegit.find_exe("git", set())')
    assert not git_path_builders('x = os.path.join(a, ".git")')  # the .git folder is no program
    assert not git_path_builders("from orch import safegit\nsafegit.find_exe(argv[0], safegit.avoid_for(w))")
    assert not git_path_builders("from orch import safegit\nsafegit.have_git(cwd)")
    assert not git_path_builders('import os\nn = "gitignore"\nos.path.join(d, n)')


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


# ---------------------------------------------------------------- round 4


@pytest.mark.usefixtures("filters_gate_off")
def test_subcommand_is_found_past_global_options(tmp_path, monkeypatch):
    monkeypatch.setattr(safegit, "ALLOWED", safegit.ALLOWED | safegit._DIFFLIKE)  # flag handling only
    assert safegit.subcommand_index(["-C", "x", "--literal-pathspecs", "--no-pager", "diff"]) == 4
    assert safegit.subcommand_index(["status"]) == 0
    seen = []
    monkeypatch.setattr(
        safegit, "_raw", lambda argv, cwd, timeout, data=None, root=None: seen.append(argv) or (0, "", "")
    )
    for cmd in ("diff", "log", "show", "format-patch", "blame"):
        safegit.run(["-C", ".", "--literal-pathspecs", cmd, "x"], tmp_path, filters=False)
        i = seen[-1].index(cmd)
        assert seen[-1][i + 1 : i + 3] == ["--no-ext-diff", "--no-textconv"], cmd
    safegit.run(["grep", "x"], tmp_path, filters=False)
    assert "--no-textconv" in seen[-1]


def test_sha256_repo_gets_its_own_empty_tree(tmp_path):
    r = tmp_path / "s"
    p = subprocess.run(["git", "init", "-q", "--object-format=sha256", str(r)], capture_output=True)
    if p.returncode != 0:
        pytest.skip("this git cannot make sha256 repositories")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("x\n")
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "i")
    assert safegit.empty_tree(r) == safegit.EMPTY_TREE["sha256"]
    assert plain_git(r, "hash-object", "-t", "tree", "/dev/null") == safegit.EMPTY_TREE["sha256"]
    wt = tmp_path / "wt"
    assert (
        safegit.run(["worktree", "add", "--no-checkout", "-b", "q", str(wt), "HEAD"], r, filters=False)[0]
        == 0
    )
    assert safegit.run(["read-tree", "HEAD"], wt)[0] == 0
    assert safegit.run(["checkout-index", "-a", "-f", "-u"], wt)[0] == 0
    assert (wt / "a.txt").read_text() == "x\n"


@pytest.mark.parametrize("old_git", [False, True])
def test_a_merge_driver_never_runs_and_the_merge_conflicts(tmp_path, monkeypatch, old_git):
    if old_git:  # git < 2.40: no --attr-source, the attributes ARE read, so driver=false forces the conflict
        monkeypatch.setattr(safegit, "version", lambda *a, **k: (2, 39))
    r = tmp_path / "m"
    r.mkdir()
    plain_git(r, "init", "-q", "-b", "main")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    (r / ".gitattributes").write_text("*.dat merge=evil\n")
    (r / "f.dat").write_text("base\n")
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "base")
    plain_git(r, "checkout", "-qb", "side")
    (r / "f.dat").write_text("theirs\n")
    plain_git(r, "commit", "-qam", "side")
    plain_git(r, "checkout", "-q", "main")
    (r / "f.dat").write_text("ours\n")
    plain_git(r, "commit", "-qam", "main")
    mark = tmp_path / "MERGE-RAN"
    plain_git(r, "config", "merge.evil.driver", f"touch {mark}; cp %A %A.x; exit 0")
    rc, _, _ = safegit.run(["merge", "--no-edit", "side"], r)
    assert not mark.exists()
    assert rc != 0  # a conflict, not a silent success that dropped "theirs"


def test_a_copy_holds_the_committed_bytes_whatever_the_eol_attributes(tmp_path):
    r = tmp_path / "e"
    r.mkdir()
    plain_git(r, "init", "-q")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    plain_git(r, "config", "core.autocrlf", "false")
    (r / ".gitattributes").write_text("* text=auto eol=crlf\n*.sh text eol=lf\n")
    (r / "a.txt").write_bytes(b"one\r\ntwo\r\n")
    (r / "b.sh").write_bytes(b"echo\n")
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "i")

    def blob(n):
        return subprocess.run(["git", "cat-file", "blob", f"HEAD:{n}"], cwd=r, capture_output=True).stdout

    wt = tmp_path / "wt"
    assert (
        safegit.run(["worktree", "add", "--no-checkout", "-b", "q", str(wt), "HEAD"], r, filters=False)[0]
        == 0
    )
    assert safegit.run(["read-tree", "HEAD"], wt)[0] == 0
    assert safegit.run(["checkout-index", "-a", "-f", "-u"], wt)[0] == 0
    if safegit.version(r) >= (2, 40):  # no attribute applies: the committed bytes, exactly
        assert (wt / "a.txt").read_bytes() == blob("a.txt") and (wt / "b.sh").read_bytes() == blob("b.sh")
    else:  # older git applies eol attributes (filters are still off): content is the converted form
        assert (wt / "a.txt").read_bytes().replace(b"\r\n", b"\n") == blob("a.txt").replace(b"\r\n", b"\n")


def test_blame_and_format_patch_accept_the_no_textconv_flags_for_real(tmp_path, monkeypatch):
    monkeypatch.setattr(safegit, "ALLOWED", safegit.ALLOWED | safegit._DIFFLIKE)  # proves git takes the flags
    r = tmp_path / "b"
    r.mkdir()
    plain_git(r, "init", "-q")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("one\n")
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "i")
    (r / "a.txt").write_text("one\ntwo\n")
    plain_git(r, "commit", "-qam", "j")
    rc, out, err = safegit.run(["blame", "a.txt"], r)
    assert rc == 0 and "two" in out, err
    rc, out, err = safegit.run(["format-patch", "-1", "--stdout"], r)
    assert rc == 0 and "+two" in out, err
    rc, out, err = safegit.run(["log", "--oneline", "-p"], r)
    assert rc == 0 and "+two" in out, err


def test_find_exe_never_returns_a_committed_program(tmp_path, monkeypatch):
    work = tmp_path / "copy"
    (work / "bin").mkdir(parents=True)
    good = tmp_path / "tools"
    good.mkdir()
    for d, n in ((work / "bin", "npm"), (work / "bin", "npm.cmd"), (work, "npm"), (good, "npm")):
        sh(d / n, "true")
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", "rel", str(work / "bin"), str(good)]))
    avoid = safegit.avoid_for(work, tmp_path / "root")
    assert safegit.find_exe("npm", avoid) == str(good / "npm")
    monkeypatch.setenv("PATH", str(work / "bin"))
    assert safegit.find_exe("npm", avoid) is None
    assert safegit.find_exe("npm.cmd", avoid) is None or os.name != "nt"
    monkeypatch.setenv("PATH", str(good))
    assert safegit.find_exe("npm", safegit.avoid_for(good, good)) is None  # inside an avoided folder


def test_global_options_with_a_value_are_skipped():
    assert safegit.subcommand_index(["-C", "v", "whatchanged"]) == 2
    # every other option stops the scan AT the option: it is refused, it never swallows the next word
    for opt in ("--config-env", "--super-prefix", "-c", "--attr-source", "--shallow-file", "--exec-path"):
        assert safegit.subcommand_index([opt, "v", "whatchanged"]) == 0
        assert safegit.refusal([opt, "v", "whatchanged"])


@pytest.mark.parametrize(
    "args",
    [
        ["difftool"],
        ["-C", ".", "mergetool", "x"],
        ["add", "-p"],
        ["add", "--patch", "f"],
        ["checkout", "-p"],
        ["reset", "-p"],
        ["restore", "--patch"],
        ["stash", "push", "-p"],
        ["add", "-i"],
        ["add", "-pf"],
    ],
)
def test_external_tools_and_interactive_modes_are_refused(args, tmp_path):
    rc, _, err = safegit.run(args, tmp_path, filters=False)
    assert rc == safegit.REFUSED and err


@pytest.mark.parametrize(
    "args",
    [
        ["add", "-A"],
        ["add", "--", "-p"],
        ["merge", "--no-edit", "x"],
        ["stash", "list"],
        ["commit", "-m", "msg"],
        ["worktree", "add", "p"],
        ["rev-list", "--count", "a..b"],
        ["merge-tree", "--write-tree", "--name-only", "-z", "a", "b"],
        ["check-attr", "filter", "diff", "text", "--", "f.txt"],
    ],
)
def test_ordinary_calls_are_not_refused(args):
    assert safegit.refusal(args) is None


@pytest.mark.usefixtures("filters_gate_off")
def test_stash_show_gets_the_no_textconv_flags(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(
        safegit, "_raw", lambda argv, cwd, timeout, data=None, root=None: seen.append(argv) or (0, "", "")
    )
    safegit.run(["stash", "show", "--stat"], tmp_path, filters=False)
    i = seen[-1].index("show")
    assert seen[-1][i + 1 : i + 3] == ["--no-ext-diff", "--no-textconv"]
    assert safegit.refusal(["cherry", "-v"])  # not an allowed command at all


@pytest.mark.usefixtures("filters_gate_off")
def test_every_call_runs_with_no_editor_no_prompt_and_no_stdin(tmp_path, monkeypatch):
    got = {}

    def fake_run(argv, **kw):
        got.update(kw)
        got["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(safegit.subprocess, "run", fake_run)
    monkeypatch.setenv("GIT_EDITOR", "vim")
    safegit.run(["status"], tmp_path, filters=False)
    assert got["stdin"] == subprocess.DEVNULL
    e = got["env"]
    assert (
        os.path.isabs(e["GIT_EDITOR"].strip("'"))
        and e["GIT_EDITOR"] == e["GIT_SEQUENCE_EDITOR"] == e["GIT_ASKPASS"]
    )
    assert e["GIT_TERMINAL_PROMPT"] == "0"
    assert any(a.startswith("core.editor=/") for a in got["argv"])
    assert any(a.startswith("sequence.editor=/") for a in got["argv"])


def test_config_is_read_only_and_worktree_subcommands_are_limited():
    assert safegit.refusal(["config", "--get", "a.b"]) is None
    assert safegit.refusal(["config", "--includes", "--get-regexp", "x"]) is None
    assert safegit.refusal(["worktree", "remove", "--force", "p"]) is None


@pytest.mark.usefixtures("filters_gate_off")
def test_literal_pathspecs_and_the_hardening_apply_to_every_allowed_subcommand(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(
        safegit, "_raw", lambda argv, cwd, timeout, data=None, root=None: seen.append(argv) or (0, "", "")
    )
    for cmd in sorted(safegit.ALLOWED):
        args = {
            "worktree": ["worktree", "list"],
            "stash": ["stash", "list"],
            "config": ["config", "--get", "a"],
        }
        safegit.run(args.get(cmd, [cmd]), tmp_path, filters=False)
        argv = seen[-1]
        assert argv.index(cmd) > argv.index("core.fsmonitor=false"), cmd
        for want in ("commit.gpgSign=false", "log.showSignature=false"):
            assert want in argv, (cmd, want)
        assert any(a.startswith("core.editor=/") for a in argv), cmd
        assert any(a == "core.hooksPath=/dev/null" for a in argv), cmd
        # a repo-writable config can never make git run a signature program (every git call of orch)
        true = next(a.split("=", 1)[1] for a in argv if a.startswith("core.editor="))
        for want in (
            "merge.verifySignatures=false",
            "core.useReplaceRefs=false",
            "diff.ignoreSubmodules=none",
            f"gpg.program={true}",
            f"gpg.openpgp.program={true}",
            f"gpg.x509.program={true}",
            f"gpg.ssh.program={true}",
            "gpg.ssh.defaultKeyCommand=",
            "core.gitProxy=",
            "core.askPass=",
        ):
            assert want in argv, (cmd, want)
    safegit.run(["--literal-pathspecs", "ls-files"], tmp_path, filters=False)
    assert safegit.refusal(["--literal-pathspecs", "ls-files"]) is None


@pytest.mark.parametrize(
    "args",
    [
        ["merge-tree", "--write-tree", "--merge-base=x", "a", "b"],
        ["merge-tree", "--trivial-merge", "a", "b", "c"],
        ["rev-list", "--output=/tmp/x", "HEAD"],
        ["rev-list", "--exec=x", "HEAD"],
        ["rev-list", "--count", "--objects", "--filter=blob:none", "HEAD"],
        ["check-attr", "--source", "x", "filter", "--", "f"],
        ["check-attr", "--all", "--", "f"],
        ["check-attr", "-z", "--stdin", "filter"],
    ],
)
def test_rev_list_and_check_attr_run_only_exact_read_flags(args):
    assert safegit.refusal(args) is not None


def test_flags_that_are_not_bad_words_still_pass():
    for ok in (
        ["branch", "--show-current"],
        ["log", "--no-textconv"],
        ["diff", "--name-only"],
        ["status", "--porcelain"],
        ["ls-files", "-z"],
        ["worktree", "add", "--force", "p"],
        ["log", "--", "--textconv"],
    ):
        assert safegit.refusal(ok) is None, ok


REFUSED_CALLS = [
    # caller-supplied global options before the command
    ["-c", "x=y", "status"],
    ["--config-env=a=b", "status"],
    ["--git-dir=x", "status"],
    ["--exec-path=x", "status"],
    ["--work-tree", "x", "status"],
    ["--attr-source", "x", "status"],
    ["--namespace=x", "status"],
    # words that run external programs, also abbreviated
    ["diff", "--ext-diff"],
    ["diff", "--ext"],
    ["log", "--textconv"],
    ["log", "--textc"],
    ["log", "--show-signature"],
    ["log", "--show-sig"],
    ["cat-file", "--textconv", "HEAD:a"],
    ["cat-file", "--textc", "HEAD:a"],
    ["cat-file", "--filters", "HEAD:a"],
    ["cat-file", "--filt", "HEAD:a"],
    # commands and sub-commands orch does not run
    ["config", "k", "v"],
    ["config", "--unset", "k"],
    ["config", "alias.x", "!sh"],
    ["worktree", "move", "a", "b"],
    ["worktree", "lock", "p"],
    ["stash", "pop"],
    ["stash", "push"],
    ["gc"],
    ["fetch"],
    ["push"],
    ["rebase", "-i"],
    ["clean", "-i"],
    ["checkout", "x"],
    # interactive modes, also abbreviated
    ["add", "--patc"],
    ["add", "--inter"],
    ["add", "--ed"],
    ["add", "-e"],
    ["commit", "--inte"],
    ["commit", "-p"],
]


@pytest.mark.parametrize("args", REFUSED_CALLS, ids=lambda a: " ".join(a))
def test_these_calls_are_refused_with_rc_125(args, tmp_path):
    rc, _, err = safegit.run(args, tmp_path, filters=False)
    assert rc == safegit.REFUSED == 125 and err


def test_fake_true_and_false_in_the_workspace_are_never_run(tmp_path, monkeypatch):
    """git runs the editor, askpass and a failing merge driver by name: those must be absolute, trusted
    paths, and the PATH git sees must not contain a folder inside the workspace."""
    proj = tmp_path / "proj"
    (proj / "bin").mkdir(parents=True)
    ran = tmp_path / "FAKE-RAN"
    r = tmp_path / "r"
    r.mkdir()
    plain_git(r, "init", "-q", "-b", "main")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    (r / ".gitattributes").write_text("*.dat merge=evil\n")
    (r / "f.dat").write_text("base\n")
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "b")
    plain_git(r, "checkout", "-qb", "side")
    (r / "f.dat").write_text("theirs\n")
    plain_git(r, "commit", "-qam", "s")
    plain_git(r, "checkout", "-q", "main")
    (r / "f.dat").write_text("ours\n")
    plain_git(r, "commit", "-qam", "m")
    plain_git(r, "config", "merge.evil.driver", "cp %A %A.x")
    for n in ("true", "false", "git"):
        sh(proj / "bin" / n, f"touch {ran}")
    real = _exe(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join([str(proj / "bin"), str(real.parent), "/usr/bin", "/bin"]))
    monkeypatch.setattr(safegit, "_exes", {})
    assert str(proj / "bin") not in safegit.safe_path(proj, proj).split(os.pathsep)
    assert safegit.trivial("true", proj, proj).strip("'") in ("/usr/bin/true", "/bin/true")
    assert safegit.trivial("false", proj, proj).strip("'") in ("/usr/bin/false", "/bin/false")
    e = safegit.env(proj, proj, safegit.trivial("true", proj, proj))
    assert str(proj) not in e["PATH"] and e["GIT_EDITOR"].strip("'").startswith("/")
    monkeypatch.setattr(
        safegit, "version", lambda *a, **k: (2, 39)
    )  # attributes are read: driver=false matters
    rc, _, _ = safegit.run(["merge", "--no-edit", "side"], r, root=proj)
    assert rc != 0 and not ran.exists()


def test_driver_names_with_equals_and_spaces_are_neutralized(tmp_path, monkeypatch):
    r = tmp_path / "n"
    r.mkdir()
    plain_git(r, "init", "-q")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    mark = tmp_path / "ODD"
    (r / ".gitattributes").write_text('*.txt filter="a=b c"\n')
    (r / "a.txt").write_text("x\n")
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "i")
    plain_git(r, "config", "filter.a=b c.smudge", f"touch {mark}; cat")
    pairs = safegit.driver_args(r)
    assert ("filter.a=b c.smudge", "") in pairs
    wt = tmp_path / "wt"
    assert (
        safegit.run(["worktree", "add", "--no-checkout", "-b", "q", str(wt), "HEAD"], r, filters=False)[0]
        == 0
    )
    assert safegit.run(["read-tree", "HEAD"], wt)[0] == 0
    monkeypatch.setattr(
        safegit, "version", lambda *a, **k: (2, 39)
    )  # attributes read: the odd name is consulted
    assert safegit.run(["checkout-index", "-a", "-f", "-u"], wt)[0] == 0
    assert (wt / "a.txt").read_text() == "x\n" and not mark.exists()


def test_git_older_than_2_31_is_refused_when_drivers_would_have_to_be_switched_off(
    hostile, tmp_path, monkeypatch
):
    r, marker = hostile
    monkeypatch.setattr(safegit, "version", lambda *a, **k: (2, 30))
    wt = tmp_path / "wt"
    assert (
        safegit.run(["worktree", "add", "--no-checkout", "-b", "x", str(wt), "HEAD"], r, filters=False)[0]
        == 0
    )
    rc, _, err = safegit.run(["checkout-index", "-a", "-f", "-u"], wt)
    assert rc == safegit.REFUSED and "2.31" in err and marks(marker) == []
    assert safegit.run(["rev-parse", "HEAD"], wt, filters=False)[0] == 0  # nothing to neutralize: still runs


def test_the_driver_overrides_really_reach_the_git_process(hostile, tmp_path, monkeypatch):
    r, _ = hostile
    seen = {}
    real = safegit.subprocess.run

    def spy(argv, **kw):
        if "checkout-index" in argv:
            seen.update(kw["env"])
        return real(argv, **kw)

    monkeypatch.setattr(safegit.subprocess, "run", spy)
    wt = tmp_path / "wt"
    assert (
        safegit.run(["worktree", "add", "--no-checkout", "-b", "x", str(wt), "HEAD"], r, filters=False)[0]
        == 0
    )
    assert safegit.run(["read-tree", "HEAD"], wt)[0] == 0
    safegit.run(["checkout-index", "-a", "-f", "-u"], wt)
    n = int(seen["GIT_CONFIG_COUNT"])
    pairs = {seen[f"GIT_CONFIG_KEY_{i}"]: seen[f"GIT_CONFIG_VALUE_{i}"] for i in range(n)}
    assert pairs["filter.evil.smudge"] == "" and pairs["filter.evil.process"] == ""
    assert pairs["filter.evil.required"] == "false" and pairs["filter.evil2.smudge"] == ""


def test_no_bare_true_anywhere(tmp_path, monkeypatch):
    monkeypatch.setattr(safegit, "trivial", lambda *a, **k: None)
    for filters in (True, False):
        rc, _, err = safegit.run(["status"], tmp_path, filters=filters)
        assert rc == safegit.REFUSED and err
    import inspect

    assert inspect.signature(safegit.base_args).parameters["true"].default is inspect.Parameter.empty
    assert inspect.signature(safegit.env).parameters["true"].default is inspect.Parameter.empty


def test_a_project_python_is_not_a_trusted_trivial_command_on_windows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # (our own cwd is always avoided; the test runs from the venv's folder)
    import sys

    assert safegit._python_trivial("true", tmp_path, tmp_path).startswith(f'"{sys.executable}"')
    inside = Path(sys.executable).parent
    assert safegit._python_trivial("true", inside, inside) is None


def test_the_legacy_callers_never_run_a_workspace_git_hook_or_fsmonitor(proj, monkeypatch):
    """files_sig and harness (_in_git_repo, _tracked, _ignored, _git_exclude, check_private_path) use the
    hardened git: a fake `git` in a PATH entry inside the workspace, a repo hook and an fsmonitor command
    never run."""
    from orch import filesig, harness

    r = proj
    plain_git(r, "init", "-q")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("x\n")
    (r / ".orch").mkdir()
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "i")
    marker = proj.parent / (proj.name + "_LEGACY")
    for name in ("post-checkout", "reference-transaction", "pre-commit", "post-index-change"):
        sh(r / ".git" / "hooks" / name, f"touch {marker}.{name}")
    plain_git(r, "config", "core.fsmonitor", f"touch {marker}.fsmonitor; echo")
    (r / "bin").mkdir()
    sh(r / "bin" / "git", f"touch {marker}.fakegit")
    sh(r / "bin" / "true", f"touch {marker}.faketrue")
    real = _exe(proj.parent)
    monkeypatch.setenv("PATH", os.pathsep.join([str(r / "bin"), str(real.parent), "/usr/bin", "/bin"]))
    monkeypatch.setattr(safegit, "_exes", {})
    (r / "new.txt").write_text("n\n")
    assert filesig.files_sig(r)
    assert harness._in_git_repo(r) is True
    assert harness._tracked(r, "a.txt") is True
    harness._ignored(r, "new.txt")
    assert harness._git_exclude(r) is not None
    with pytest.raises(Refused):  # not ignored here: refused after asking the hardened git
        harness.check_private_path(r, r / ".orch" / "local" / "x.json")
    assert list(marker.parent.glob(marker.name + "*")) == []


def _planted_only(proj, monkeypatch):
    """The only git on the PATH is one inside the workspace: have_git() finds none it trusts."""
    (proj / "bin").mkdir(exist_ok=True)
    sh(proj / "bin" / "git", "exit 0")
    monkeypatch.setenv("PATH", str(proj / "bin"))
    monkeypatch.setattr(safegit, "_exes", {})


def test_with_no_trusted_git_each_caller_closes_in_its_own_safe_direction(proj, monkeypatch, capsys):
    from orch import filesig, harness

    plain_git(proj, "init", "-q")
    (proj / "a.txt").write_text("x\n")
    (proj / ".orch").mkdir()
    _planted_only(proj, monkeypatch)
    assert not safegit.have_git(proj)
    assert filesig.files_sig(proj) is None  # no signature
    with pytest.raises(Refused):
        harness._in_git_repo(proj)  # a planted git must not read as "not a repo"
    with pytest.raises(Refused):
        harness.check_private_path(proj, proj / ".orch" / "local" / "x.json")
    with pytest.raises(Refused):
        harness._ignored(proj, "a.txt")
    assert harness._tracked(proj, "a.txt") is True  # the team's file: left alone
    assert harness._git_exclude(proj) is None
    assert "git excludes skipped" in capsys.readouterr().err


def test_with_no_git_at_all_a_plain_folder_is_fine(proj, monkeypatch):
    from orch import harness

    monkeypatch.setenv("PATH", "/nonexistent-dir")
    monkeypatch.setattr(safegit, "_exes", {})
    assert harness._in_git_repo(proj) is False


def test_ignored_answers_from_the_hardened_git(proj):
    from orch import harness

    plain_git(proj, "init", "-q")
    (proj / ".gitignore").write_text("secret.txt\n")
    assert harness._ignored(proj, "secret.txt") is True
    assert harness._ignored(proj, "other.txt") is False


def test_source_sha_uses_the_hardened_git(tmp_path, monkeypatch):
    plain_git(tmp_path, "init", "-q")
    plain_git(tmp_path, "config", "user.email", "t@t")
    plain_git(tmp_path, "config", "user.name", "t")
    (tmp_path / "f").write_text("x")
    plain_git(tmp_path, "add", "-A")
    plain_git(tmp_path, "commit", "-qm", "i")
    head = plain_git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.setattr(addons, "repo", lambda: str(tmp_path))
    monkeypatch.setattr(addons, "_is_local", lambda r: True)
    seen = []
    real = addons.subprocess.run
    monkeypatch.setattr(addons.subprocess, "run", lambda a, **k: seen.append((a, k)) or real(a, **k))
    assert addons._source_sha() == head
    argv, kw = seen[-1]
    assert os.path.isabs(argv[0]) and any(a.startswith("core.hooksPath=") for a in argv) and "env" in kw


def test_env_sets_the_c_locale(monkeypatch):
    monkeypatch.setenv("LANG", "de_CH.UTF-8")
    monkeypatch.setenv("LC_ALL", "de_CH.UTF-8")
    e = safegit.env(Path("/tmp"), None, "/bin/true")
    assert e["LC_ALL"] == e["LANG"] == "C"


# ---------------------------------------------------------------- run_bytes


def test_run_bytes_returns_raw_bounded_stdout_with_the_same_allowlist(proj):
    sh_git = lambda *a: subprocess.run(["git", *a], cwd=proj, check=True, capture_output=True)  # noqa: E731
    sh_git("init", "-q")
    (proj / "aé.txt").write_text("x")
    rc, out, _ = safegit.run_bytes(["ls-files", "-z", "--others", "--exclude-standard"], proj)
    assert rc == 0 and isinstance(out, bytes) and out == "aé.txt".encode() + b"\0"
    rc, out, err = safegit.run_bytes(["ls-files", "-z", "--others"], proj, max_bytes=3)
    assert rc == safegit.TOO_LONG and out == b""
    for bad in (
        ["clean", "-fdx"],
        ["checkout", "x"],
        ["-c", "core.pager=x", "ls-files"],
        ["config", "a", "b"],
    ):
        assert safegit.run_bytes(bad, proj)[0] == safegit.REFUSED


def _fake_exe(tmp_path, body):
    d = tmp_path.parent / (tmp_path.name + "_fakebin")  # outside the folder git runs in
    d.mkdir(exist_ok=True)
    sh(d / "git", body)
    return d


def _gone(pidf, wait=3.0):
    """The recorded (grand)child is dead: kill(pid, 0) fails. Polls a moment (the kernel reaps it async)."""
    import time

    pid = int(pidf.read_text())
    end = time.monotonic() + wait
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.05)
    return False


posix_only = pytest.mark.skipif(os.name == "nt", reason="process groups: POSIX")


@posix_only
def test_run_bytes_kills_git_and_its_child_as_soon_as_the_cap_is_passed(proj, tmp_path, monkeypatch):
    """A git that would print far more than the cap (and then hang) is stopped while it prints, and so is
    the child it started."""
    import time

    gpid = tmp_path.parent / (tmp_path.name + "_gpid")
    d = _fake_exe(tmp_path, f"sleep 30 & echo $! > {gpid}; yes x | head -c 50000000; wait")
    monkeypatch.setenv("PATH", os.pathsep.join([str(d), "/usr/bin", "/bin"]))
    monkeypatch.setattr(safegit, "_exes", {})
    t = time.monotonic()
    rc, out, _ = safegit.run_bytes(["ls-files", "-z"], proj, 20, max_bytes=100_000)
    assert rc == safegit.TOO_LONG and out == b"" and time.monotonic() - t < 10
    assert _gone(gpid)  # the grandchild too


@posix_only
def test_run_bytes_kills_git_and_its_child_on_timeout(proj, tmp_path, monkeypatch):
    import time

    gpid = tmp_path.parent / (tmp_path.name + "_gpid")
    d = _fake_exe(tmp_path, f"sleep 30 & echo $! > {gpid}; wait")
    monkeypatch.setenv("PATH", os.pathsep.join([str(d), "/usr/bin", "/bin"]))
    monkeypatch.setattr(safegit, "_exes", {})
    t = time.monotonic()
    rc, out, _ = safegit.run_bytes(["ls-files", "-z"], proj, 1)
    assert rc == 124 and time.monotonic() - t < 10
    assert _gone(gpid)


@posix_only
def test_a_child_left_behind_by_a_finished_git_is_killed_and_the_call_fails_closed(
    proj, tmp_path, monkeypatch
):
    """git exits at once but a background child still holds the pipes: the call ends at the timeout with 124
    and no data (never a partial result as success), and the child is killed."""
    import time

    gpid = tmp_path.parent / (tmp_path.name + "_gpid")
    d = _fake_exe(tmp_path, f"sleep 30 & echo $! > {gpid}; printf hi")
    monkeypatch.setenv("PATH", os.pathsep.join([str(d), "/usr/bin", "/bin"]))
    monkeypatch.setattr(safegit, "_exes", {})
    t = time.monotonic()
    rc, out, _ = safegit.run_bytes(["ls-files", "-z"], proj, 2)
    assert rc == 124 and out == b"" and time.monotonic() - t < 10
    assert _gone(gpid)


def test_run_bytes_needs_no_waitid(proj, monkeypatch):
    """os.waitid is missing on macOS Python < 3.13: nothing may depend on it."""
    monkeypatch.delattr(os, "waitid", raising=False)
    plain_git(proj, "init", "-q")
    rc, out, _ = safegit.run_bytes(["rev-parse", "--is-inside-work-tree"], proj, 10)
    assert (rc, out.strip()) == (0, b"true")


def test_taskkill_is_found_by_full_path_in_the_system_folder(tmp_path, monkeypatch):
    import types

    sysdir = tmp_path / "System32"
    sysdir.mkdir()
    (sysdir / "taskkill.exe").write_text("x")

    def get_dir(buf, size):
        buf.value = str(sysdir)
        return len(buf.value)

    fake = types.SimpleNamespace(kernel32=types.SimpleNamespace(GetSystemDirectoryW=get_dir))
    monkeypatch.setattr("ctypes.windll", fake, raising=False)
    monkeypatch.delenv("SystemRoot", raising=False)
    assert safegit.taskkill_exe() == str(sysdir / "taskkill.exe")
    (sysdir / "taskkill.exe").unlink()
    assert safegit.taskkill_exe() is None  # not found: never a bare name
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    (tmp_path / "System32" / "taskkill.exe").write_text("x")
    assert safegit.taskkill_exe() == str(tmp_path / "System32" / "taskkill.exe")  # the %SystemRoot% route


def test_without_a_findable_taskkill_a_windows_kill_fails_closed(monkeypatch):
    import types

    monkeypatch.setattr(safegit.os, "name", "nt")
    monkeypatch.setattr(safegit, "taskkill_exe", lambda: None)
    killed = []
    p = types.SimpleNamespace(returncode=None, pid=1234, kill=lambda: killed.append(1))
    assert safegit._kill(p, safegit.threading.Lock()) is False and killed


@posix_only
def test_output_is_never_returned_while_a_reader_is_still_running(proj, monkeypatch):
    """If a reader outlives its join, the call fails (124) and no partial data is returned as success."""
    real = safegit.threading.Thread

    class Stuck(real):
        def join(self, timeout=None):  # pretend the reader never finishes
            pass

        def is_alive(self):
            return True

    monkeypatch.setattr(safegit.threading, "Thread", Stuck)
    plain_git(proj, "init", "-q")
    rc, out, err = safegit.run_bytes(["rev-parse", "--is-inside-work-tree"], proj, 10)
    assert rc == 124 and out == b""  # (a reader past the timeout or past its join: never data)


@pytest.mark.parametrize("bad", [["--std"], ["--stdi"], ["-qz"], ["-z"], ["--stdin"], ["-q", "-e"], ["-p"]])
def test_check_ignore_takes_only_listed_options(proj, bad):
    assert safegit.run_bytes(["check-ignore", *bad, "--", "x"], proj)[0] == safegit.REFUSED


def test_check_ignore_is_allowed_with_paths_only(proj):
    plain_git(proj, "init", "-q")
    (proj / ".gitignore").write_text("s.txt\n")
    assert safegit.run_bytes(["check-ignore", "-q", "--", "s.txt"], proj)[0] == 0
    assert safegit.run_bytes(["check-ignore", "-q", "--", "o.txt"], proj)[0] == 1
    assert safegit.run_bytes(["check-ignore", "--stdin"], proj)[0] == safegit.REFUSED


@pytest.mark.parametrize("rc", [123, 2, 128, -11])
def test_tracked_cannot_tell_means_tracked(proj, monkeypatch, rc):
    from orch import harness

    plain_git(proj, "init", "-q")
    (proj / "a.txt").write_text("x\n")
    real = safegit.subprocess.Popen

    class Done:  # a finished git process (safegit streams through Popen)
        returncode = rc

        def __init__(self):
            import io

            self.stdout, self.stderr = io.BufferedReader(io.BytesIO(b"")), io.BufferedReader(io.BytesIO(b""))

        def wait(self, timeout=None):
            return rc

    def fake(argv, **kw):
        return Done() if "ls-files" in argv else real(argv, **kw)

    monkeypatch.setattr(safegit.subprocess, "Popen", fake)
    assert harness._tracked(proj, "a.txt") is True  # unexpected exit code: the team's file
    monkeypatch.setattr(safegit.subprocess, "Popen", real)
    assert harness._tracked(proj, "a.txt") is False  # git's own answer: not tracked
    plain_git(proj, "add", "a.txt")
    assert harness._tracked(proj, "a.txt") is True


def test_a_git_in_our_own_cwd_is_never_used_even_without_cwd_or_root(tmp_path, monkeypatch):
    ran = tmp_path / "CWD-GIT-RAN"
    here = tmp_path / "agentrepo"
    here.mkdir()
    sh(here / "git", f"touch {ran}")
    real = _exe(tmp_path)
    for path in (os.pathsep.join([str(here), str(real.parent)]), str(here)):
        monkeypatch.setenv("PATH", path)
        monkeypatch.setattr(safegit, "_exes", {})
        monkeypatch.chdir(here)
        exe = safegit.git_exe(tmp_path / "elsewhere")  # the caller names another cwd and no root
        assert exe in (None, str(real))
        safegit.run(["--version"], tmp_path, filters=False)
        assert not ran.exists()
    assert str(here.resolve()) in safegit._avoid(tmp_path, None)


def test_a_broad_cwd_does_not_switch_git_off(tmp_path, monkeypatch):
    real = _exe(tmp_path)
    monkeypatch.setattr(safegit, "_exes", {})
    monkeypatch.setenv("PATH", str(real.parent))
    for broad in (Path("/"), tmp_path / "fakehome"):
        if broad != Path("/"):
            (broad / ".local" / "bin").mkdir(parents=True)
            monkeypatch.setattr(Path, "home", classmethod(lambda cls, h=broad: h))
            sh(broad / ".local" / "bin" / "git", "exec " + str(real) + ' "$@"')
            monkeypatch.setenv("PATH", os.pathsep.join([str(broad / ".local" / "bin"), str(real.parent)]))
        monkeypatch.setattr(safegit, "_exes", {})
        monkeypatch.chdir(broad)
        assert safegit.git_exe(tmp_path, tmp_path) is not None, broad  # PROCESS cwd `/` or home: git is found
    # but a PATH entry that IS the cwd is still avoided there
    monkeypatch.setattr(safegit, "_exes", {})
    monkeypatch.setenv("PATH", os.pathsep.join([str(tmp_path / "fakehome"), str(real.parent)]))
    sh(tmp_path / "fakehome" / "git", "exit 1")
    monkeypatch.chdir(tmp_path / "fakehome")
    assert safegit.git_exe(tmp_path, tmp_path) == str(real)


def test_in_a_project_cwd_the_whole_subtree_is_still_avoided(tmp_path, monkeypatch):
    real = _exe(tmp_path)
    proj = tmp_path / "project"
    (proj / "node_modules" / ".bin").mkdir(parents=True)
    sh(proj / "node_modules" / ".bin" / "git", "exit 1")
    monkeypatch.setenv("PATH", os.pathsep.join([str(proj / "node_modules" / ".bin"), str(real.parent)]))
    monkeypatch.setattr(safegit, "_exes", {})
    monkeypatch.chdir(proj)
    assert safegit.git_exe(proj) == str(real)
    assert safegit._avoid(proj, None) >= {str(proj)}


def test_the_git_cache_does_not_survive_a_chdir_into_an_avoided_folder(tmp_path, monkeypatch):
    real = _exe(tmp_path)
    bindir = tmp_path / "work" / "bin"
    bindir.mkdir(parents=True)
    # a git that is only visible because of where we stand
    sh(bindir / "git", "exit 1")
    monkeypatch.setenv("PATH", os.pathsep.join([str(bindir), str(real.parent)]))
    monkeypatch.setattr(safegit, "_exes", {})
    monkeypatch.chdir(tmp_path)
    first = safegit.git_exe(tmp_path)  # bindir is not inside the cwd (tmp_path): it is chosen... or tmp_path
    monkeypatch.chdir(tmp_path / "work")
    second = safegit.git_exe(tmp_path / "work")
    assert second == str(real) and first is not None


@pytest.mark.usefixtures("filters_gate_off")
def test_the_windows_hint_is_in_the_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(safegit, "trivial", lambda *a, **k: None)
    rc, _, err = safegit.run(["status"], tmp_path, filters=False)
    assert rc == safegit.REFUSED and "virtual environment located elsewhere" in err


def test_a_failure_in_resolve_or_home_never_relaxes_the_avoidance(tmp_path, monkeypatch):
    class Boom(type(tmp_path)):
        def resolve(self, *a, **k):
            raise OSError("boom")

    assert safegit._broad(Boom(tmp_path)) is False  # an exception: full avoidance stays
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("no home"))))
    assert safegit._is_home(tmp_path.resolve()) is False
    safegit._broad(tmp_path)  # a failing home lookup does not crash it
    assert not safegit._entry(tmp_path / "proj").startswith("=")


def test_the_relaxation_is_only_for_the_process_cwd(tmp_path, monkeypatch):
    real = _exe(tmp_path)
    home = tmp_path / "fakehome"
    (home / ".local" / "bin").mkdir(parents=True)
    sh(home / ".local" / "bin" / "git", "exit 1")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("PATH", os.pathsep.join([str(home / ".local" / "bin"), str(real.parent)]))
    monkeypatch.setattr(safegit, "_exes", {})
    monkeypatch.chdir(tmp_path)
    # the CALLER's cwd == home: its whole subtree is avoided (the planted ~/.local/bin/git is not used)
    assert safegit.git_exe(home, None) == str(real)
    assert str(home) in safegit._avoid(home, None)  # a full-subtree entry, no "=" prefix
    # the PROCESS cwd == home (relaxed): a git in ~/.local/bin is allowed (Homebrew-in-home)
    monkeypatch.setattr(safegit, "_exes", {})
    monkeypatch.chdir(home)
    proj = tmp_path.parent / (tmp_path.name + "_proj")  # not above the fake home
    proj.mkdir()
    assert safegit.git_exe(proj, proj) == str(home / ".local" / "bin" / "git")
    # process cwd `/` with a normal root: git is found
    monkeypatch.setattr(safegit, "_exes", {})
    monkeypatch.setenv("PATH", str(real.parent))
    monkeypatch.chdir("/")
    assert safegit.git_exe(proj, proj) == str(real)


@pytest.mark.usefixtures("filters_gate_off")
def test_a_root_that_is_home_or_a_drive_root_refuses_git(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for root in (tmp_path, Path("/")):
        rc, _, err = safegit.run(["status"], tmp_path, filters=False, root=root)
        assert rc == safegit.REFUSED and "whole home folder or a drive root" in err
        assert safegit.run_bytes(["rev-parse", "--show-toplevel"], tmp_path, root=root)[0] == safegit.REFUSED
        assert safegit.run_bytes(["rev-parse", "--show-toplevel"], root)[0] == safegit.REFUSED  # root = cwd
    assert safegit.unusable_root(tmp_path / "project") is None
    assert safegit.unusable_root(None) is None


def test_harness_shows_the_plain_message_for_a_home_or_drive_root_workspace(tmp_path, monkeypatch):
    from orch import harness

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for fn in (
        lambda: harness._in_git_repo(tmp_path),
        lambda: harness._ignored(tmp_path, "a"),
        lambda: harness.check_private_path(tmp_path, tmp_path / ".orch" / "x"),
    ):
        with pytest.raises(Refused, match="whole home folder or a drive root"):
            fn()


def test_a_differently_spelled_home_is_still_refused(tmp_path, monkeypatch):
    home = tmp_path / "Home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    other = tmp_path / "home"
    if not other.exists():
        pytest.skip("this file system is case-sensitive: `home` is a different folder from `Home`")
    assert safegit.unusable_root(other)  # os.path.samefile: the same folder
    link = tmp_path / "homelink"
    link.symlink_to(home, target_is_directory=True)
    assert safegit.unusable_root(link)  # a link to home too


@pytest.mark.usefixtures("filters_gate_off")
def test_git_exe_with_root_home_and_a_planted_git_in_home_is_refused(tmp_path, monkeypatch):
    real = _exe(tmp_path)
    home = tmp_path / "fakehome"
    (home / ".local" / "bin").mkdir(parents=True)
    sh(home / ".local" / "bin" / "git", "exit 1")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("PATH", os.pathsep.join([str(home / ".local" / "bin"), str(real.parent)]))
    monkeypatch.setattr(safegit, "_exes", {})
    other = tmp_path.parent / (tmp_path.name + "_x")
    other.mkdir()
    monkeypatch.chdir(other)
    # root == home: the home subtree is avoided in full, so the planted git is not chosen ...
    assert safegit.git_exe(other, home) == str(real)
    # ... and any run with that root is refused outright
    rc, _, err = safegit.run(["status"], other, filters=False, root=home)
    assert rc == safegit.REFUSED and "home folder" in err


def test_runs_kill_tree_uses_the_full_path_taskkill_or_does_nothing(monkeypatch, capsys):
    from orch import runs

    monkeypatch.setattr(runs.os, "name", "nt")
    calls = []
    monkeypatch.setattr(runs.subprocess, "run", lambda argv, **k: calls.append(argv))
    monkeypatch.setattr(safegit, "taskkill_exe", lambda: r"C:\Windows\System32\taskkill.exe")
    runs.kill_tree(4321)
    assert calls == [[r"C:\Windows\System32\taskkill.exe", "/PID", "4321", "/T", "/F"]]
    calls.clear()
    monkeypatch.setattr(safegit, "taskkill_exe", lambda: None)
    runs.kill_tree(4321)
    assert calls == [] and "taskkill.exe was not found" in capsys.readouterr().err  # no bare name is run


def test_safegit_works_with_an_untrusted_orch_home(proj, monkeypatch, tmp_path):
    """The hooks path must not need the orch home: with an ORCH_HOME that is not trusted, run_bytes() and
    run() still work (the test that found this: refreshing with an unpaired home)."""
    from orch import harness

    monkeypatch.setenv(
        "ORCH_HOME", str(tmp_path)
    )  # not under the (faked) real home: untrusted in strict mode
    assert safegit.run_bytes(["rev-parse", "--is-inside-work-tree"], proj)[0] in (0, 128)
    assert safegit.run(["--version"], proj, filters=False)[0] == 0
    assert harness._in_git_repo(proj) is False


# ---- filters=False is only for subcommands that never hash, clean, smudge or check out content

FILTERS_OFF_CALLS = [
    ["rev-parse", "--show-toplevel"],
    ["rev-parse", "--verify", "-q", "HEAD"],
    ["symbolic-ref", "-q", "HEAD"],
    ["branch", "--list"],
    ["branch", "-D", "nothere"],
    ["check-ignore", "-q", "--", "a.txt"],
    ["worktree", "list"],
    ["worktree", "prune"],
    ["ls-files", "-z", "--stage", "--", "."],
    ["ls-files", "-z", "--others", "--exclude-standard", "--", "."],
    ["--literal-pathspecs", "ls-files", "-z", "--", ".orch"],
    ["-C", ".", "ls-files", "--error-unmatch", "--", "a.txt"],
    ["check-attr", "-z", "filter", "eol", "--", "a.txt"],
    ["check-attr", "-z", "--source=" + "a" * 40, "filter", "--", "a.txt"],
    ["check-attr", "-z", "--cached", "filter", "--", "a.txt"],
    ["worktree", "add", "--no-checkout", "-b", "zz", "../zz", "HEAD"],
    ["branch", "-d", "--", "nothere"],
]
FILTERS_OFF_REFUSED = [
    ["worktree", "add", "--lock", "--reason", "--no-checkout", "-b", "probe", "../p", "HEAD"],  # a value
    ["worktree", "add", "-b", "x", "--no-checkout", "../x", "HEAD"],  # --no-checkout not first
    ["worktree", "add", "--no-checkout", "--checkout", "../x", "HEAD"],
    ["worktree", "add", "--no-checkout", "-b", "x", "--force", "../x", "HEAD"],
    ["worktree", "add", "--no-checkout", "-b", "../x"],  # -b eats the folder: no positional left
    ["rm", "--cached", "-f", "-q", "--", "a.txt"],
    ["add", "-A"],
    ["status", "--porcelain"],
    ["diff", "--stat"],
    ["update-index", "--refresh"],
    ["checkout-index", "-a", "-f", "-u"],
    ["read-tree", "HEAD"],
    ["ls-files", "-m"],
    ["ls-files", "--modified"],
    ["ls-files", "-z", "--eol"],
    ["ls-files", "-d"],
    ["reset", "--hard"],
    ["commit", "-a", "-qm", "x"],
    ["worktree", "add", "-b", "x", "../x", "HEAD"],  # without --no-checkout it writes content
    ["worktree", "remove", "--force", "../x"],
    ["-c", "core.pager=x", "status"],  # refused anyway
    ["-C", ".", "rm", "--cached", "a.txt"],
    ["--no-optional-locks", "add", "-A"],
    [
        "--shallow-file",
        "rev-parse",
        "rm",
        "--cached",
        "a.txt",
    ],  # git reads --shallow-file's value as the next word
    ["--paginate", "rev-parse", "HEAD"],
    ["-p", "rev-parse", "HEAD"],
    ["--bare", "rev-parse", "HEAD"],
    ["--exec-path", "rev-parse", "HEAD"],
    ["--unknown-global", "x", "rev-parse"],
    ["worktree", "add", "--no-checkout", "--checkout", "-b", "zz", "../zz", "HEAD"],  # the last one wins
    ["worktree", "add", "--no-checkout", "--check", "-b", "zz", "../zz", "HEAD"],  # an abbreviation of it
    ["branch", "-m", "a", "b"],
    ["branch", "--set-upstream-to=x"],
    ["branch", "-f", "a", "HEAD"],
    ["check-attr", "--all", "a.txt"],
]


@pytest.fixture
def canary_repo(tmp_path):
    """Tracked, stat-dirty files with a planted clean filter: any content hashing runs the canary."""
    canary = tmp_path / "CANARY"
    r = tmp_path / "repo"
    r.mkdir()
    plain_git(r, "init", "-q")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    prog = tmp_path / "clean.sh"
    sh(prog, f"touch {canary}\ncat")
    (r / "a.txt").write_text("hello\n")
    (r / ".orch").mkdir()
    (r / ".orch" / "t.json").write_text("{}")
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "init")
    plain_git(r, "config", "filter.x.clean", str(prog))  # planted only after the setup
    (r / ".git" / "info" / "attributes").write_text("* filter=x\n")
    os.utime(r / "a.txt", (1, 1))  # stat-dirty
    os.utime(r / ".orch" / "t.json", (1, 1))
    return r, canary


@pytest.mark.parametrize("args", FILTERS_OFF_CALLS, ids=lambda a: " ".join(a))
def test_filters_off_allowlist_runs_and_never_runs_the_clean_filter(canary_repo, args):
    r, canary = canary_repo
    assert not canary.exists(), "fixture"
    assert safegit.filters_off_refusal(args) is None
    rc, _, err = safegit.run(args, r, read_only=args[0] not in ("branch",), filters=False)
    assert rc != safegit.REFUSED, err
    rc = safegit.run_bytes(args, r)[0]  # run_bytes defaults to filters off
    assert rc != safegit.REFUSED
    assert not canary.exists()


def test_the_gate_is_what_stops_the_canary(canary_repo, monkeypatch):
    """Positive control: with the gate switched off, `status` (stat-dirty files) does run the clean filter."""
    r, canary = canary_repo
    monkeypatch.setattr(safegit, "filters_off_refusal", lambda args: None)
    monkeypatch.setattr(safegit, "refusal", lambda args: None)
    safegit.run(["status", "--porcelain"], r, read_only=False, filters=False)
    assert canary.exists()


@pytest.mark.parametrize("args", FILTERS_OFF_REFUSED, ids=lambda a: " ".join(a))
def test_filters_off_for_anything_else_is_refused_before_git_starts(canary_repo, monkeypatch, args):
    r, canary = canary_repo
    started = []
    monkeypatch.setattr(safegit, "_raw", lambda *a, **k: started.append(a) or (0, "", ""))
    monkeypatch.setattr(safegit, "_raw_bytes", lambda *a, **k: started.append(a) or (0, b"", ""))
    assert safegit.run(args, r, filters=False)[0] == safegit.REFUSED
    assert safegit.run_bytes(args, r)[0] == safegit.REFUSED  # the run_bytes default is filters off too
    assert safegit.run_bytes(args, r, filters=False)[0] == safegit.REFUSED
    assert started == [] and not canary.exists()


def test_filters_off_allowlist_is_only_what_callers_need():
    assert set(safegit.FILTERS_OFF_OK) == {
        "rev-parse",
        "symbolic-ref",
        "branch",
        "check-ignore",
        "check-attr",
        "worktree",
        "ls-files",
    }


def test_replace_refs_and_grafts_never_change_what_orch_sees(tmp_path):
    """The shared repository's refs/replace/* (an agent can write them) must not alter commit content or
    ancestry for any orch git call: the reviewed-tip and ancestor checks depend on it."""
    r = tmp_path / "r"
    r.mkdir()
    plain_git(r, "init", "-q")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("one\n")
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "one")
    plain_git(r, "checkout", "-qb", "side")
    (r / "a.txt").write_text("two\n")
    plain_git(r, "commit", "-qam", "two")
    side = plain_git(r, "rev-parse", "HEAD")
    plain_git(r, "checkout", "-q", "-")
    (r / "a.txt").write_text("evil\n")
    plain_git(r, "commit", "-qam", "evil")
    evil = plain_git(r, "rev-parse", "HEAD")
    plain_git(r, "replace", side, evil)  # same id, other content
    plain_git(r, "replace", "--graft", plain_git(r, "rev-parse", "HEAD"), side)  # side becomes an ancestor
    rc, out, _ = safegit.run(["cat-file", "-p", f"{side}:a.txt"], r, read_only=True)
    assert rc == 0 and out.strip() == "two"
    rc, _, _ = safegit.run(["merge-base", "--is-ancestor", side, "HEAD"], r, read_only=True)
    assert rc != 0


def test_ignore_submodules_in_the_repo_config_does_not_hide_a_gitlink(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    plain_git(r, "init", "-q")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("x\n")
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "base")
    plain_git(r, "update-index", "--add", "--cacheinfo", "160000", "a" * 40, "sub")
    plain_git(r, "commit", "-qm", "gitlink")
    plain_git(r, "config", "diff.ignoreSubmodules", "all")
    rc, out, _ = safegit.run(["diff", "--raw", "-z", "--no-renames", "HEAD~1", "HEAD"], r, read_only=True)
    assert rc == 0 and ":000000 160000" in out


def test_history_files_an_agent_can_write_are_not_trusted(tmp_path, monkeypatch):
    """B13: the commit-graph is switched off for every call; a shallow, alternates or grafts file in the
    repository (or the project a work copy belongs to) makes orch refuse to run git there."""
    seen = []
    monkeypatch.setattr(
        safegit, "_raw", lambda argv, cwd, timeout, data=None, root=None: seen.append(argv) or (0, "", "")
    )
    monkeypatch.setattr(safegit, "git_exe", lambda cwd, root=None: "/usr/bin/git")
    r = tmp_path / "r"
    r.mkdir()
    plain_git(r, "init", "-q")
    safegit.run(["rev-parse", "HEAD"], r, read_only=True, filters=False)
    assert "core.commitGraph=false" in seen[-1] and "gc.writeCommitGraph=false" in seen[-1]
    for rel in ("shallow", "objects/info/alternates", "objects/info/grafts", "info/grafts"):
        f = r / ".git" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("0" * 40 + "\n")
        n = len(seen)
        rc, _, err = safegit.run(["rev-parse", "HEAD"], r, read_only=True, filters=False)
        assert rc == safegit.REFUSED and err == safegit.HISTORY_REFUSAL and len(seen) == n, rel
        f.unlink()
    assert safegit.run(["rev-parse", "HEAD"], r, read_only=True, filters=False)[0] == 0


def test_a_work_copy_of_a_shallow_project_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(safegit, "_raw", lambda *a, **k: (0, "", ""))
    monkeypatch.setattr(safegit, "git_exe", lambda cwd, root=None: "/usr/bin/git")
    r = tmp_path / "r"
    r.mkdir()
    plain_git(r, "init", "-q")
    plain_git(r, "config", "user.email", "t@t")
    plain_git(r, "config", "user.name", "t")
    (r / "a").write_text("x\n")
    plain_git(r, "add", "-A")
    plain_git(r, "commit", "-qm", "i")
    wt = tmp_path / "wt"
    plain_git(r, "worktree", "add", "-q", "-b", "q", str(wt))
    assert safegit.run(["rev-parse", "HEAD"], wt, read_only=True, filters=False)[0] == 0
    (r / ".git" / "shallow").write_text("0" * 40 + "\n")
    assert safegit.run(["rev-parse", "HEAD"], wt, read_only=True, filters=False)[0] == safegit.REFUSED


def test_fsck_runs_only_in_its_checking_form_and_a_symlinked_git_folder_is_refused(tmp_path):
    ok = ["fsck", "--strict", "--no-dangling", "--no-reflogs", "a" * 40, "b" * 40]
    assert safegit.refusal(ok) is None
    for bad in (["fsck", "--lost-found"], ["fsck", "--name-objects"], ["fsck", "HEAD"], ["fsck", "--", "x"]):
        assert safegit.refusal(bad), bad
    r = tmp_path / "r"
    r.mkdir()
    plain_git(r, "init", "-q")
    moved = tmp_path / "elsewhere"
    (r / ".git").rename(moved)
    (r / ".git").symlink_to(moved)
    assert safegit.hostile_history(r) == safegit.HISTORY_REFUSAL


def test_every_fsck_format_id_can_really_be_ignored(tmp_path):
    """git refuses to demote some ids ("Cannot demote ... to ignore"): only accepted ids are listed."""
    r = tmp_path / "r"
    r.mkdir()
    plain_git(r, "init", "-q")
    for i in safegit.FSCK_FORMAT_OK:
        p = subprocess.run(["git", "-c", f"fsck.{i}=ignore", "fsck"], cwd=r, capture_output=True, text=True)
        assert "Cannot demote" not in p.stderr, i


def test_colour_is_off_for_every_call(tmp_path, monkeypatch):
    """A repo's own config (color.diff=always) must not put escape codes into what orch parses."""
    seen = []
    monkeypatch.setattr(
        safegit, "_raw", lambda argv, cwd, timeout, data=None, root=None: seen.append(argv) or (0, "", "")
    )
    monkeypatch.setattr(safegit, "git_exe", lambda cwd, root=None: "/usr/bin/git")
    safegit.run(["rev-parse", "HEAD"], tmp_path, read_only=True, filters=False)
    assert "color.ui=never" in seen[-1] and "color.diff=never" in seen[-1]


UNKNOWN_GLOBALS = [
    ["--shallow-file", "x", "rev-parse", "HEAD"],
    ["--shallow-file", "rev-parse", "rm", "--cached", "a.txt"],
    ["--bare", "rev-parse", "HEAD"],
    ["-p", "rev-parse", "HEAD"],
    ["--paginate", "rev-parse", "HEAD"],
    ["--exec-path=/x", "rev-parse", "HEAD"],
    ["--super-prefix=x", "rev-parse", "HEAD"],
    ["--frobnicate", "rev-parse", "HEAD"],
    ["-C", "x", "--frobnicate", "rev-parse", "HEAD"],  # after a known one too
]


@pytest.mark.parametrize("filters", [True, False], ids=["filters-on", "filters-off"])
@pytest.mark.parametrize("args", UNKNOWN_GLOBALS, ids=lambda a: " ".join(a))
def test_unknown_leading_options_are_refused_before_git_starts(canary_repo, monkeypatch, args, filters):
    """Only the closed list of leading options (with its exact arity) is accepted; no denylist."""
    r, _ = canary_repo
    started = []
    monkeypatch.setattr(safegit, "_raw", lambda *a, **k: started.append(a) or (0, "", ""))
    monkeypatch.setattr(safegit, "_raw_bytes", lambda *a, **k: started.append(a) or (0, b"", ""))
    assert safegit.run(args, r, filters=filters)[0] == safegit.REFUSED
    assert safegit.run_bytes(args, r, filters=filters)[0] == safegit.REFUSED
    assert started == []


def test_the_closed_list_of_leading_options_has_exact_arity():
    assert safegit.subcommand_index(["-C", "x", "rev-parse"]) == 2  # exactly one value
    assert safegit.subcommand_index(["--no-optional-locks", "--literal-pathspecs", "rev-parse"]) == 2
    assert safegit.subcommand_index(["-C", "rev-parse"]) == 2  # -C swallows one word, as git does

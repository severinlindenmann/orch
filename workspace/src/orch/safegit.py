"""The ONE place orch runs git inside a workspace or a separate copy of it.

A repository's own configuration is not trusted. `.git/config` (also through include.path / includeIf),
`.gitattributes` and `.git/hooks` can name programs, and in a copy they are branch content an agent could have
written. When a person clicks Start, orch must not become the one who runs them, outside the agent tool's
sandbox and permission mode. So every call here:

* drops every GIT_* variable of the caller (a hook's GIT_DIR must not aim us at another repository; only what
  this module sets is passed), and sets GIT_TERMINAL_PROMPT=0;
* uses `-c core.hooksPath=<orch home>/empty-hooks`, a folder orch owns and keeps empty (repo hooks never
  run: reference-transaction on branch changes, post-checkout, ...), `core.fsmonitor=false`,
  `core.untrackedCache=false`, `protocol.allow=never` (no network), `core.longpaths=true` (Windows);
* adds `--no-optional-locks` to read-only calls;
* is an argv list with a timeout, never a shell.

`filter_args(cwd)` neutralizes clean/smudge/process filter drivers (git has no wildcard): for every driver
the repository's config defines it passes `-c filter.<d>.smudge= ... required=false`. Every `run` does
it unless
`filters=False` is passed for a call that never reads file content.

tests/test_safegit.py has a lint: no other module under workspace/src/orch starts `git` itself, except the
files listed in LEGACY, which still do and are to be migrated.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from orch import addons

# Modules that still start git themselves (to migrate; each one runs in the person's own workspace only).
# filesig.py (B8) and work-check (B9) join this list until they migrate after they merge.
LEGACY = ("addons.py", "harness.py")

IDENTITY = ["-c", "user.name=orch", "-c", "user.email=orch@localhost"]  # for commits orch makes (bring-back)
_DRIVER = re.compile(r"^filter\.(.+)\.(smudge|clean|process)$")
TIMEOUT = 60


_exe: str | None = None


def _inside(path: str, folder: str) -> bool:
    a, b = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(folder))
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:  # another drive
        return False


def _avoid(cwd: Path) -> list[str]:
    out = [str(cwd)]
    try:
        out.append(str(addons.home() / "worktrees"))
    except Exception:  # noqa: BLE001 - no usable orch home: only the folder itself is avoided
        pass
    return out


def git_exe(cwd: Path) -> str | None:
    """The one git program orch runs: found ONCE on the PATH, as an absolute path, cached. Not shutil.which
    (on Windows it also looks in the current folder, so a committed git.exe would run). Only absolute PATH
    entries count, only `git.exe` on Windows (never .cmd/.bat: they go through cmd.exe), and never an entry
    inside the folder we work in or the orch copies folder. A cached path inside `cwd` is refused as well."""
    global _exe
    if _exe is None:
        name = "git.exe" if os.name == "nt" else "git"
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if not d or d == "." or not os.path.isabs(d):
                continue
            p = os.path.join(d, name)
            if os.path.isfile(p) and os.access(p, os.X_OK) and not any(_inside(p, a) for a in _avoid(cwd)):
                _exe = p
                break
    if _exe is None or any(_inside(_exe, a) for a in _avoid(cwd)):
        return None
    return _exe


def empty_hooks() -> Path:
    """<orch home>/empty-hooks: made if missing, emptied if anything was put in it (orch's own folder)."""
    d = addons.home() / "empty-hooks"
    d.mkdir(parents=True, exist_ok=True)
    for p in d.iterdir():
        try:
            if p.is_dir() and not p.is_symlink():
                for q in p.rglob("*"):
                    if q.is_file() or q.is_symlink():
                        q.unlink()
                for q in sorted(p.rglob("*"), reverse=True):
                    q.rmdir()
                p.rmdir()
            else:
                p.unlink()
        except OSError:
            pass
    return d


def env() -> dict[str, str]:
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e["LC_ALL"] = "C"
    e["GIT_TERMINAL_PROMPT"] = "0"
    return e


def base_args(read_only: bool = False) -> list[str]:
    hooks = empty_hooks().as_posix()
    out = [
        "-c", f"core.hooksPath={hooks}",
        "-c", "core.fsmonitor=false",
        "-c", "core.untrackedCache=false",
        "-c", "protocol.allow=never",
        "-c", "core.longpaths=true",
    ]  # fmt: skip
    return ["--no-optional-locks", *out] if read_only else out


def _raw(argv: list[str], cwd: Path, timeout: float, data: bytes | None = None):
    exe = git_exe(cwd)
    if exe is None:
        return 127, "", "git is not installed (or only found inside the project, which orch does not run)"
    argv = [exe, *argv[1:]]
    try:
        p = subprocess.run(
            argv, cwd=cwd, capture_output=True, input=data, env=env(), timeout=timeout, check=False
        )
    except FileNotFoundError:
        return 127, "", "git is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"git {argv[-1] if argv else ''} took longer than {int(timeout)} s"
    except OSError as e:
        return 127, "", str(e)
    return (
        p.returncode,
        p.stdout.decode("utf-8", "surrogateescape"),
        p.stderr.decode("utf-8", "replace").strip(),
    )


def filter_args(cwd: Path, timeout: float = TIMEOUT) -> list[str]:
    """`-c filter.<d>.smudge= ...` for every filter driver this repository's configuration defines."""
    rc, out, _ = _raw(
        [
            "git",
            *base_args(True),
            "config",
            "--includes",
            "--null",
            "--get-regexp",
            r"^filter\..*\.(smudge|clean|process)$",
        ],
        cwd,
        timeout,
    )
    names: set[str] = set()
    if rc == 0:
        for rec in out.split("\0"):
            m = _DRIVER.match(rec.split("\n", 1)[0].strip())
            if m:
                names.add(m.group(1))
    args: list[str] = []
    for d in sorted(names):
        args += ["-c", f"filter.{d}.smudge=", "-c", f"filter.{d}.clean=", "-c", f"filter.{d}.process=",
                 "-c", f"filter.{d}.required=false"]  # fmt: skip
    return args


def run(
    args: list[str],
    cwd: Path,
    timeout: float = TIMEOUT,
    *,
    data: bytes | None = None,
    read_only: bool = False,
    filters: bool = True,
    strip: bool = True,
) -> tuple[int, str, str]:
    """(exit code, stdout, stderr) of git `args` in `cwd`, hardened as the module says. rc 127: git missing,
    124: timeout. `filters` (default on): neutralize the repository's filter drivers (status, diff, add,
    checkout and merge all run them). Off only for calls that touch no file content (rev-parse, config)."""
    argv = ["git", *base_args(read_only), *(filter_args(cwd, timeout) if filters else []), *args]
    rc, out, err = _raw(argv, cwd, timeout, data)
    return rc, out.strip() if strip else out, err

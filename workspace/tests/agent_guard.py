"""No test may start a real agent tool (claude, codex, copilot) of the computer it runs on (ORCH-1843).

The real `copilot` started with a test's throw-away HOME unpacks its ~350 MB package into
<HOME>/Library/Caches/copilot again for every test: that filled 23 GB of a dev Mac in an hour. Used by
workspace/tests/conftest.py and every add-on test tree (workspace-addons/_orch_test_guard.py):

* `hidden_path` / `apply`: the test's PATH without the real agent programs (a folder that holds one is
  replaced by a copy made of links to its other programs, so `node`, `git` ... stay), and NVM_DIR in the fake
  home, so orch's `find_binary` finds no real agent, in the test process and in the `orch` children it starts.
* an audit hook: a test process that still starts a real agent program (any absolute path, its own PATH)
  raises AgentStarted, and the test fails even when the code swallows the error (`started`).
* `footprints`: the folders a real copilot leaves in a home; a test that made one fails and the folder is
  removed at once (it can be hundreds of MB).
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

_BASE_JSON = Path(__file__).resolve().parents[1] / "src" / "orch" / "agents" / "base.json"
_EXTS = [e.lower() for e in os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").split(";") if e]
FOOTPRINTS = (("Library", "Caches", "copilot"), (".cache", "copilot"))


class AgentStarted(RuntimeError):
    pass


def agent_binaries() -> tuple[str, ...]:
    """The programs of orch's built-in agents (agents/base.json `detect.binary`): one list, no copy."""
    doc = json.loads(_BASE_JSON.read_text("utf-8"))
    names = {(a.get("detect") or {}).get("binary") for a in doc["adapters"].values() if isinstance(a, dict)}
    return tuple(sorted(n for n in names if n))


NAMES = agent_binaries()


def _is_agent(name: str) -> bool:
    low = name.lower()
    if os.name == "nt":
        stem, ext = os.path.splitext(low)
        return stem in NAMES and (not ext or ext in _EXTS)
    return low in NAMES


def _real_home() -> Path:
    try:
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError):
        return Path.home()


def _agents_in(folder: Path) -> list[Path]:
    with contextlib.suppress(OSError):
        return [p for p in folder.iterdir() if _is_agent(p.name) and p.is_file()]
    return []


def real_agent_paths(path: str | None = None) -> set[str]:
    """Every real agent program this computer has, resolved: the PATH and the folders orch's find_binary
    looks in (the real home's, nvm's, Homebrew's)."""
    home = _real_home()
    path = path if path is not None else os.environ.get("PATH", "")
    folders = [Path(p) for p in path.split(os.pathsep) if p]
    folders += [home / ".local" / "bin", home / ".npm-global" / "bin", home / ".bun" / "bin"]
    for nvm in {Path(os.environ.get("NVM_DIR") or home / ".nvm"), home / ".nvm"}:
        with contextlib.suppress(OSError):
            folders += [d / "bin" for d in (nvm / "versions" / "node").iterdir()]
    folders += [Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    return {os.path.realpath(p) for f in folders for p in _agents_in(f)}


def hidden_path(path: str, shadow_root: Path) -> str:
    """`path` with every folder that holds a real agent program replaced by a shadow folder: links to all its
    other entries (macOS/Linux); on Windows the folder is left out."""
    out = []
    for i, entry in enumerate(path.split(os.pathsep)):
        folder = Path(entry) if entry else None
        if folder is None or not _agents_in(folder):
            out.append(entry)
            continue
        if os.name == "nt":
            continue
        shadow = shadow_root / f"{i}-{folder.name}"
        shadow.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            for p in folder.iterdir():
                if not _is_agent(p.name) and not (shadow / p.name).exists():
                    with contextlib.suppress(OSError):
                        (shadow / p.name).symlink_to(p)
        out.append(str(shadow))
    return os.pathsep.join(out)


_REAL_PATH = os.environ.get("PATH", "")
BLOCKED: set[str] = real_agent_paths(_REAL_PATH)
started: list[str] = []
_shadow: dict[str, str] = {}


def _shadow_path() -> str:
    """The hidden PATH of the test start PATH, made once per process (its folder also holds an empty nvm)."""
    if "path" not in _shadow:
        root = Path(tempfile.mkdtemp(prefix="orch-test-path-"))
        atexit.register(shutil.rmtree, root, True)
        _shadow["nvm"] = str(root / "no-nvm")
        _shadow["path"] = hidden_path(_REAL_PATH, root)
    return _shadow["path"]


def _program(argv, executable, env) -> str | None:
    if isinstance(argv, (str, bytes)):
        argv = [argv]
    argv = [os.fsdecode(a) for a in (argv or [])]
    prog = os.fsdecode(executable) if executable else (argv[0] if argv else None)
    if prog and os.path.basename(prog) in ("sh", "bash", "zsh") and "-c" in argv[:-1]:
        with contextlib.suppress(ValueError, IndexError):
            prog = shlex.split(argv[argv.index("-c") + 1])[0]
    if not prog:
        return None
    if not os.path.dirname(prog):
        found = shutil.which(prog, path=(env if env is not None else os.environ).get("PATH"))
        prog = found or prog
    return os.path.realpath(prog) if os.path.dirname(prog) else None


def _hook(event: str, args: tuple) -> None:
    if event == "subprocess.Popen":
        exe, argv, _cwd, env = args
    elif event == "os.posix_spawn" or event == "os.exec":
        exe, argv, env = args
    elif event == "os.system":
        exe, argv, env = None, ["/bin/sh", "-c", os.fsdecode(args[0])], None
    else:
        return
    prog = None
    with contextlib.suppress(Exception):
        prog = _program(argv, exe, env)
    if prog is not None and prog in BLOCKED:
        started.append(prog)
        raise AgentStarted(
            f"a test started the real agent program {prog}: stub it (a fake executable on PATH or a "
            "monkeypatched command) - a real copilot unpacks ~350 MB into the test's home on every start"
        )


if not getattr(sys, "_orch_agent_guard", False):
    sys._orch_agent_guard = True
    sys.addaudithook(_hook)


def hide_process_wide() -> None:
    """At conftest import, before collection (a test module may look up a tool at import time): the hidden
    PATH and an empty nvm folder for this process and every child it starts."""
    os.environ["PATH"] = _shadow_path()
    os.environ["NVM_DIR"] = _shadow["nvm"]


def wrap_find_binary(adapters) -> None:
    """orch's find_binary also looks in the real home's and Homebrew's folders: it never returns a real
    agent program in a test (a test's own stub is found as before)."""
    if getattr(adapters.find_binary, "_orch_agent_guard", False):
        return
    orig = adapters.find_binary

    def find_binary(binary):
        found = orig(binary)
        return None if found and os.path.realpath(found) in BLOCKED else found

    find_binary._orch_agent_guard = True
    adapters.find_binary = find_binary


def footprints(home: Path) -> list[Path]:
    return [home.joinpath(*parts) for parts in FOOTPRINTS if home.joinpath(*parts).exists()]


def apply(monkeypatch, fake_home: Path) -> None:
    """Per test: PATH without the real agent programs, nvm's folder in the fake home."""
    monkeypatch.setenv("PATH", _shadow_path())
    monkeypatch.setenv("NVM_DIR", str(fake_home / ".nvm"))
    started.clear()


def check(fake_home: Path) -> str | None:
    """After a test: what it did wrong (the folder a real copilot left is removed now), or None."""
    bad = [f"started {p}" for p in started]
    started.clear()
    for f in footprints(fake_home):
        shutil.rmtree(f, ignore_errors=True)
        bad.append(f"left {f} (a real copilot ran with this test's HOME)")
    return "; ".join(bad) or None


def sweep(root: Path, depth: int = 3) -> list[Path]:
    """Session end: any copilot package folder left under the test temp folder (children of children, a test
    that set its own HOME), removed. Looks only `depth` folders deep, so it stays fast."""
    found = []
    for parts in FOOTPRINTS:
        for d in range(1, depth + 1):
            found += [p for p in root.glob("/".join(["*"] * d + list(parts))) if p.is_dir()]
    for p in found:
        shutil.rmtree(p, ignore_errors=True)
    return found

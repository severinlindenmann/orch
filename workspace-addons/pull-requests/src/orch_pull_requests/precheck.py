"""The precheck: a quick command run on a queue group's merged tree on this computer, before the group is pushed
(setting `[pull_requests] precheck`, ORCH-545).

On 19 Nov most red queue groups were red in rule tests that take seconds (tool names, history lint, skills lint),
but each one cost a 16 minute group run and a split. With a precheck the queue runs those seconds on the merged
tree first; when it is red, each member is checked on its own on top of the same base, and a member that is red
alone leaves the queue at once with the failing lines.

The command is the person's setting, never read from the repository, and runs in a plain throw-away folder of
the group commit's files (`git archive`, then a fresh repository of its own with them as one commit: no link back
to the queue's git copy, so the code can never plant a hook or config there) with a throw-away home: HOME, USERPROFILE and ORCH_HOME point into that folder and
ORCH_HOME_STRICT=1, so the orch of this computer is never touched by accident. Only PATH, the language and uv's own
cache and Python folders are kept from this computer's environment (shared for speed, as every local test run
here shares them). It is no sandbox against hostile code: it runs only pull requests the queue takes, i.e. of its
own login and never from a fork. Trouble (no copy, no command, too slow) is never red: the group run decides then.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .store import Refused

TIMEOUT_SECS = 600
TAIL_LINES, TAIL_CHARS = 8, 600
KEEP = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "COMSPEC", "PATHEXT", "WINDIR", "TEMP", "TMP", "TMPDIR")


@dataclass
class Result:
    ok: bool | None  # None: it could not run (not red)
    tail: str = ""


def env(home: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    base = dict(os.environ) if base is None else base
    real = Path.home()
    out = {k: base[k] for k in KEEP if k in base}
    out.update(
        HOME=str(home),
        USERPROFILE=str(home),
        ORCH_HOME=str(home / "orch"),
        ORCH_HOME_STRICT="1",
        # uv's downloads stay shared, so a run takes seconds and not a fresh Python each time
        UV_CACHE_DIR=base.get("UV_CACHE_DIR") or str(real / ".cache" / "uv"),
        UV_PYTHON_INSTALL_DIR=base.get("UV_PYTHON_INSTALL_DIR")
        or str(real / ".local" / "share" / "uv" / "python"),
    )
    return out


def _tail(text: str) -> str:
    lines = [x.rstrip() for x in text.splitlines() if x.strip()]
    return "\n".join(lines[-TAIL_LINES:])[-TAIL_CHARS:]


def own_repo(git_exe: str, src: Path, home: Path, timeout: int = TIMEOUT_SECS) -> None:
    """A fresh git repository of its own in src with the files as one commit: checks that ask git (ls-files, diff)
    work, and nothing in it points back to the queue's copy."""
    e = env(home)
    e.update(
        GIT_AUTHOR_NAME="orch precheck", GIT_AUTHOR_EMAIL="precheck@orch.invalid", GIT_TERMINAL_PROMPT="0"
    )
    e.update(GIT_COMMITTER_NAME="orch precheck", GIT_COMMITTER_EMAIL="precheck@orch.invalid", LC_ALL="C")
    for args in (
        ["init", "-q"],
        ["add", "-A"],
        ["commit", "-q", "--no-verify", "--no-gpg-sign", "-m", "precheck"],
    ):
        try:
            got = subprocess.run(
                [git_exe, "-c", "core.hooksPath=", *args], cwd=src, env=e, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, check=False,
            )  # fmt: skip
        except (subprocess.TimeoutExpired, OSError):
            raise Refused(f"git {args[0]} did not finish") from None
        if got.returncode != 0:
            raise Refused(f"git {args[0]} failed: {(got.stderr or got.stdout).strip()[:200]}")


def run(git, sha: str, command: str, timeout: int = TIMEOUT_SECS) -> Result:
    """Run command in a copy of commit sha. ok True = exit 0, False = any other exit, None = it could not run."""
    # next to the queue's git copy, not in the system temp folder: some checks treat a home or Python there as
    # special (test_adapters: an orch home in temp makes Codex writable), so they would be red only here
    where = Path(git.dir).parent.parent / "precheck"
    where.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="run-", dir=where))
    src, home = tmp / "src", tmp / "home"
    home.mkdir()
    try:
        try:
            git.export(sha, src, timeout=timeout)
            own_repo(git.git, src, home, timeout)
        except Refused as e:
            return Result(None, f"no copy of the group commit: {e}")
        try:
            got = subprocess.run(
                command, shell=True, cwd=src, env=env(home), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, check=False,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            return Result(None, f"the precheck did not finish in {timeout // 60} minutes")
        except OSError as e:
            return Result(None, f"the precheck did not start: {e}")
        return Result(got.returncode == 0, _tail((got.stdout or "") + "\n" + (got.stderr or "")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

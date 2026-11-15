"""Shared by every add-on test tree (imported from each tests/conftest.py): no test may touch the real user's
~/.orch-tool.

* `isolated_orch_home` (autouse): HOME/USERPROFILE and ORCH_HOME point into a private temp folder and
  ORCH_HOME_STRICT=1 for EVERY test (an unset ORCH_HOME is then an error, never a fallback to the real folder).
  A test that wants its own ORCH_HOME sets it afterwards.
* `check_real_home` (called from pytest_sessionfinish): the real ~/.orch-tool must look the same after the session (listing, size, content
  hash); anything that changed fails the session and is named. Read only, controller process only.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest


def _real_home() -> Path:
    try:
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError):
        return Path.home()


_REAL_TOOL_HOME = _real_home() / ".orch-tool"


def snapshot(base: Path = _REAL_TOOL_HOME) -> dict:
    """{path: (size, sha256) | "dir" | None} of everything under `base` (read only)."""
    out: dict = {}
    if not base.exists():
        return out
    for p in (base, *base.rglob("*")):
        try:
            if p.is_dir() and not p.is_symlink():
                out[str(p)] = "dir"
            else:
                out[str(p)] = (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
        except OSError:
            out[str(p)] = None
    return out


_AT_START = snapshot()


def diff(before: dict, after: dict) -> list[str]:
    return [
        f"{k}: {'removed' if k not in after else 'created' if k not in before else 'changed'}"
        for k in sorted(set(before) | set(after))
        if before.get(k) != after.get(k)
    ]


@pytest.fixture(autouse=True)
def isolated_orch_home(tmp_path_factory, monkeypatch):
    fake = tmp_path_factory.mktemp("realhome")
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setenv("USERPROFILE", str(fake))
    monkeypatch.setenv("ORCH_HOME", str(fake / "toolhome"))  # under the faked home = a trusted folder
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    if "orch.addons" in sys.modules:
        monkeypatch.setattr(sys.modules["orch.addons"], "real_home", lambda: fake)


def check_real_home(session) -> None:
    """Call from pytest_sessionfinish (a conftest that has its own defines it and calls this)."""
    if hasattr(session.config, "workerinput"):  # xdist worker: the controller checks
        return
    changed = diff(_AT_START, snapshot())
    if changed:
        print(
            "\nREAL ~/.orch-tool CHANGED during the test session:\n  " + "\n  ".join(changed), file=sys.stderr
        )
        session.exitstatus = 1

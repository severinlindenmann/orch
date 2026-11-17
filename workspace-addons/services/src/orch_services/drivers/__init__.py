"""One small interface over the computer's own service tool, one module per platform (picked by sys.platform).

Every driver works for the person's own account only: never sudo, never a system-wide folder, never `User=`.
The home folder for its files is `Path.home()` (tests point HOME at a temp folder)."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..store import Refused

NO_TOOL = "This computer cannot keep services running for you: {}."


class Unavailable(Refused):
    """The platform tool is missing or cannot be reached; the sentence says why."""

    def __init__(self, reason: str):
        super().__init__(NO_TOOL.format(reason))


@dataclass
class Spec:
    """What a driver needs to know about one service, with every path made absolute."""

    sid: str
    name: str
    workspace_id: str
    argv: list[str]  # argv[0] is the program's full path
    cwd: Path
    log: Path
    auto: bool
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Status:
    running: bool
    pid: int | None = None
    since: str | None = None  # RFC 3339 UTC, when the platform says it


class Driver:
    """The interface. `install` writes the platform entry and leaves the service stopped."""

    name = "none"

    def check(self) -> None:
        raise NotImplementedError

    def entry_path(self, spec: Spec) -> Path:
        raise NotImplementedError

    def install(self, spec: Spec) -> None:
        raise NotImplementedError

    def start(self, spec: Spec) -> None:
        raise NotImplementedError

    def stop(self, spec: Spec) -> None:
        raise NotImplementedError

    def restart(self, spec: Spec) -> None:
        raise NotImplementedError

    def set_auto(self, spec: Spec) -> None:
        """Make the entry match `spec.auto` (starts by itself after a restart or not)."""
        raise NotImplementedError

    def status(self, spec: Spec) -> Status:
        raise NotImplementedError

    def uninstall(self, spec: Spec) -> None:
        """Stop it and remove the platform entry (the log file stays)."""
        raise NotImplementedError


def run_tool(argv: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv, check=False, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL
        )
    except FileNotFoundError:
        raise Unavailable(f"{Path(argv[0]).name} is missing") from None
    except subprocess.TimeoutExpired:
        raise Refused(
            f"{Path(argv[0]).name} did not answer within {timeout} seconds. Try again in a moment."
        ) from None


def tool_failed(what: str, cp: subprocess.CompletedProcess) -> Refused:
    detail = (cp.stderr or cp.stdout or "").strip().splitlines()
    tail = f" ({detail[-1][:160]})" if detail else ""
    return Refused(f"Could not {what}{tail}. Run orch services list and try again.")


def get() -> Driver:
    """The driver for this computer, or Unavailable."""
    if sys.platform == "darwin":
        from .launchd import Launchd

        return Launchd()
    if sys.platform.startswith("linux"):
        from .systemd import Systemd

        return Systemd()
    raise Unavailable("only macOS and Linux are supported so far")

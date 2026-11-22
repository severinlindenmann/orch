"""Keep helper shells from disrupting a workspace's running helpers or remote sign-in."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from orch import addons, home, pagelaunch, runs, runs_live, tickets
from orch.errors import Refused


def isolated(root: Path) -> bool:
    if pagelaunch.is_test_workspace(root):
        return True
    # A temporary HOME alone must never exempt a real workspace elsewhere.
    base = Path.home().resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    return (
        base != temp
        and base.is_relative_to(temp)
        and root.resolve().is_relative_to(base)
        and os.environ.get("ORCH_HOME_STRICT", "") not in ("", "0")
        and bool(os.environ.get("ORCH_HOME"))
        and Path(os.environ["ORCH_HOME"]).resolve().is_relative_to(base)
        and not home._same(str(base), str(home.account_home()))
    )


def require_change(root: Path, by: str | None = None) -> None:
    if not tickets.agent_tool() and not (by or "").startswith("agent:"):
        return
    if isolated(root):
        return
    if any(pagelaunch.remote_base(root, a) for a in addons.active(root)) or any(
        runs.state(rec) == "alive" for rec in runs_live.records(root)
    ):
        raise Refused(
            "A helper shell cannot change services here while helpers or remote sign-in are active; "
            "use orch ask to ask the person to do it from their own terminal or a card."
        )


def command(root: Path, cmd: str, sub: str | None = None, by: str | None = None) -> None:
    if (
        cmd in ("start", "stop", "restart", "update")
        or (cmd == "addon" and sub in ("add", "remove"))
        or (sub == "stop" and cmd in addons.active(root))  # an add-on's own stop (orch dashboard stop)
    ):
        require_change(root, by)

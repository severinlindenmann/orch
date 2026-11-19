"""Sessions without a ticket (ORCH-364, draft D): empty helper, chat helper, plain terminal, Manager.

One start path for all four (`orch session new <kind>`, the dashboard's New menu): each lives on a hidden
ticket, so runs, slots, the idle close and `orch run attach` treat it like any helper session.
- chat: the workspace's Chat helper (chat.py, the hidden General ticket), started live when it is not on.
- manager: the always-on Manager (manager.py), started when it is not on.
- empty: a helper with no ticket and no task yet (tickets.ensure_session "empty"). A normal helper for
  slots and the idle close; it works in the workspace folder and waits for the person's first message.
- terminal: a plain terminal (tickets.ensure_session "terminal"): the person's login shell in the workspace
  folder, on orch's own tmux server under the hidden ticket's id (the dashboard's terminal bridge shows it).
  No helper and no slot; it shows open until it is closed (`orch session close terminal`), which ends the
  shell. Without tmux (Windows, or not installed) it stays a placeholder.
One of each per workspace: a second New of the same kind goes to the one that is there."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from orch import manager, runs, runs_live, tickets
from orch.errors import Refused

KINDS = ("empty", "chat", "terminal", "manager")
TITLES = {"empty": "Empty helper", "chat": "Chat helper", "terminal": "Plain terminal", "manager": "Manager"}


def empty_prompt(ticket: dict, news: str = "") -> str:
    """What a fresh empty helper starts with: no ticket, no task, wait for the person."""
    tid = ticket["id"]
    out = [
        f"You are a helper without a ticket and without a task yet. This hidden ticket ({tid}) is only your "
        "conversation: never add tasks to it, never finish it or move its status.",
        "Read .agents/skills/orch/SKILL.md first. The person talks to you here, in Focus or in a terminal "
        "joined to this session. Answer short and in plain words, in the person's language.",
        "Wait for the person's first message and do what they ask. When it becomes a piece of work, find or "
        "make its ticket first (orch ticket list, orch ticket new) and track the steps there.",
        "Ask before anything the orch skill's ask list names (cannot be undone, costs money, production, "
        "deletes real data, visible outside).",
    ]
    if news:
        out.append("New since you last looked:\n" + news)
    return "\n\n".join(out)[:12000]


def _id(root: Path, kind: str) -> str | None:
    if kind == "chat":
        return tickets.general_id(root)
    if kind == "manager":
        return tickets.manager_id(root)
    return tickets.session_id(root, kind)


def _closed(root: Path, tid: str) -> bool:
    try:
        return bool(tickets.load(root, tid).get("closed_at"))
    except Exception:  # noqa: BLE001 - a broken ticket shows as closed
        return True


def _login_shell() -> str:
    """The person's own shell ($SHELL, else the account's), an absolute path that runs; else /bin/sh."""
    cands = [os.environ.get("SHELL") or ""]
    try:
        import pwd

        cands.append(pwd.getpwuid(os.getuid()).pw_shell)
    except (ImportError, KeyError, OSError):
        pass
    for c in cands:
        if c and os.path.isabs(c) and os.access(c, os.X_OK):
            return c
    return "/bin/sh"


def shell_on(root: Path, tid: str) -> bool:
    """The plain terminal's shell runs (its tmux session is there)."""
    return os.name != "nt" and runs_live.session_exists(root, tid)


def start_shell(root: Path, tid: str) -> bool:
    """Start the plain terminal's shell (a login shell in the workspace folder, 200 x 50 like a helper's
    session) unless it runs. False: this machine has no tmux, or tmux could not start it."""
    if os.name == "nt" or not shutil.which("tmux"):
        return False
    if runs_live.session_exists(root, tid):
        return True
    r = runs_live.tmux(
        root, "new-session", "-d", "-x", "200", "-y", "50", "-s", tid, "-c", str(root),
        "-e", f"ORCH_ROOT={root}", "--", _login_shell(), "-l",
    )  # fmt: skip
    return r.returncode == 0


def stop_shell(root: Path, tid: str) -> bool:
    """End the plain terminal's shell; True when one was running."""
    if not shell_on(root, tid):
        return False
    return runs_live.tmux(root, "kill-session", "-t", runs_live.target(tid)).returncode == 0


def one(root: Path, kind: str) -> dict | None:
    """{id, kind, title, running, open} of a session without a ticket, None when it was never made.
    open: a helper whose session is on, or the plain terminal until it is closed. The plain terminal also
    says whether its shell runs (shell) and, when it does, its tmux session (tmux: {socket, session}, as a
    live run's claim names it)."""
    tid = _id(root, kind)
    if tid is None:
        return None
    on = runs.running(root, tid) if kind != "terminal" else False
    is_open = on if kind != "terminal" else not _closed(root, tid)
    out = {"id": tid, "kind": kind, "title": TITLES[kind], "running": on, "open": is_open}
    if kind == "terminal":
        sh = is_open and shell_on(root, tid)
        out["shell"] = sh
        if sh:
            out["tmux"] = {"socket": runs_live.socket_name(root), "session": tid}
    return out


def listing(root: Path) -> list[dict]:
    """Every session without a ticket that was made, in the New menu's order."""
    return [s for k in KINDS if (s := one(root, k)) is not None]


def new(root: Path, kind: str, by: str) -> dict:
    """Start (or go to) the session without a ticket of this kind: {id, kind, title, running, open, started,
    notes}. Already on: nothing new starts (started False)."""
    if kind not in KINDS:
        raise Refused(f"No such session without a ticket: {kind}. Choose one of: {', '.join(KINDS)}.")
    notes: list[str] = []
    started = False
    if kind == "manager":
        d = manager.start(root, by)
        started, notes = bool(d.get("started")), list(d.get("notes") or [])
    elif kind == "terminal":
        made = tickets.session_id(root, "terminal") is None
        tid = tickets.ensure_session(root, "terminal", by)
        started = made or _closed(root, tid)
        if not made and started:
            tickets.apply_op(root, tid, lambda t: t.pop("closed_at", None), by=by)
        if not shell_on(root, tid):  # also after a restart of this computer: the shell comes back
            started = start_shell(root, tid) or started
    else:
        tid = (
            tickets.ensure_general(root, by) if kind == "chat" else tickets.ensure_session(root, "empty", by)
        )
        if not runs.running(root, tid):
            r = runs.start(root, tid, by, mode="live")
            started, notes = True, list(r.get("notes") or [])
    return {**(one(root, kind) or {}), "started": started, "notes": notes}


def close(root: Path, kind: str, by: str) -> dict:
    """End the session without a ticket of this kind: a helper's session stops (its conversation is kept,
    the next New resumes it); the plain terminal closes and its shell ends. Not there or not on: nothing
    happens."""
    if kind not in KINDS:
        raise Refused(f"No such session without a ticket: {kind}. Choose one of: {', '.join(KINDS)}.")
    tid = _id(root, kind)
    closed = False
    if tid and kind == "terminal":
        if not _closed(root, tid):
            tickets.apply_op(root, tid, lambda t: t.__setitem__("closed_at", tickets.now()), by=by)
            closed = True
        closed = stop_shell(root, tid) or closed
    elif tid and runs.running(root, tid):
        closed = bool(runs_live.stop(root, tid, hold=True))
    return {**(one(root, kind) or {"kind": kind, "title": TITLES[kind]}), "closed": closed}

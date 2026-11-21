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

from orch import adapters, manager, runs, runs_live, sessionmode, tickets
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
        f"You start on a small model. When the person's work turns hard here (design, security, several "
        f'parts), move up first: orch ticket model {tid} up --why "<what makes it hard>".',
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
    if kind == "empty":
        out["model"] = start_model(root, tid)
    if kind in sessionmode.KINDS:
        out["permissions"] = _mode_row(root, kind, tid if on else None)
    return out


def _running_mode(root: Path, tid: str) -> str | None:
    rec = runs.read(root, tid) or {}
    v = rec.get("permissions")
    return v if v in sessionmode.RANK else None


def _mode_row(root: Path, kind: str, running_tid: str | None) -> dict:
    """ORCH-818: the Start choice's modes for this kind, and the mode the running session has (the pane
    header shows it in words). Never fails a listing: a tool orch cannot load shows no choices."""
    try:
        name = adapters.chosen(root)
        row = sessionmode.offer(root, kind, name)
    except Exception:  # noqa: BLE001 - no tool here: nothing to choose
        return {"current": None, "label": None, "choices": [], "full_warned": False, "running": None}
    run = _running_mode(root, running_tid) if running_tid else None
    row["running"] = run
    row["running_label"] = sessionmode.label(name, run, root) if run else None
    return row


def start_model(root: Path, tid: str) -> str | None:
    """The model the Empty helper starts on (or runs on), read only: the New menu shows it and preselects it
    (ORCH-710). None when its ticket cannot be read."""
    try:
        return tickets.next_model(tickets.load(root, tid))
    except Exception:  # noqa: BLE001 - a broken ticket shows no model
        return None


def listing(root: Path) -> list[dict]:
    """Every session without a ticket that was made, in the New menu's order."""
    return [s for k in KINDS if (s := one(root, k)) is not None]


def new(
    root: Path, kind: str, by: str, model: str | None = None, mode: str | None = None, person: bool = False
) -> dict:
    """Start (or go to) the session without a ticket of this kind: {id, kind, title, running, open, started,
    notes}. Already on: nothing new starts (started False). model: the person's pick for the Empty helper
    (haiku, sonnet, opus, fable), set before it starts (ORCH-710); one already running keeps its model.
    mode (ORCH-818): the permission mode to start in (sessionmode.MODES), remembered for this kind; refused
    above what the workspace allows, and above the kind's current mode unless person (the signed-in grant).
    A session that is on in another mode ends and continues the same conversation in the new one."""
    if kind not in KINDS:
        raise Refused(f"No such session without a ticket: {kind}. Choose one of: {', '.join(KINDS)}.")
    if model and kind != "empty":
        raise Refused("Only the Empty helper takes a model here. Pick the others' model in their own place.")
    if mode is not None and kind not in sessionmode.KINDS:
        raise Refused(f"The {TITLES[kind]} runs no helper, so it has no permission mode.")
    notes: list[str] = []
    started = False
    if mode is not None:
        chosen = sessionmode.resolve(root, kind, mode, person)
        sessionmode.remember(root, kind, chosen)
        tid = _id(root, kind)
        if tid and runs.running(root, tid):
            name = adapters.chosen(root)
            want = sessionmode.tool_mode(name, chosen, root)
            if _running_mode(root, tid) != want:  # restart in the new mode, same conversation
                runs_live.stop(root, tid)
                notes.append(f"The {TITLES[kind]} goes on in {sessionmode.label(name, want, root)}.")
    if kind == "manager":
        d = manager.start(root, by)
        started, notes = bool(d.get("started")), notes + list(d.get("notes") or [])
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
        on = runs.running(root, tid)
        # the pick is for the start; a running one keeps its model (its pane's model line switches it)
        if model and not on and model != start_model(root, tid):
            tickets.set_model(root, tid, model, by)
        if not on:
            r = runs.start(root, tid, by, mode="live")
            started, notes = True, notes + list(r.get("notes") or [])
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

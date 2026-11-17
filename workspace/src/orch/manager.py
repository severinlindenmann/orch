"""The Manager (ORCH-147): one always-on helper session per workspace, next to Chat.

A hidden ticket (`manager: true`, no display key, its file kept out of git like the Chat ticket's) holds the
session. Unlike Chat it has the full rights of a normal helper. Nothing ends its session by itself: the idle
close (runs_live.cleanup) and the helper watcher (tend) leave it alone, it never waits for a free slot and
never counts against one, and it never starts fresh on its own. The person talks to it in Focus (message box
or typing on its screen) or joins it from a terminal (`orch run attach <id>`), stops it, or starts it
fresh."""

from __future__ import annotations

from pathlib import Path

from orch import runs, runs_live, tickets


def prompt(root: Path, ticket: dict, news: str = "") -> str:
    """What a fresh Manager session starts with."""
    tid = ticket["id"]
    out = [
        f"You are the Manager of this workspace: an always-on helper session. This hidden ticket ({tid}) is "
        "your conversation, not a piece of work: never add tasks to it, never finish it or move its status.",
        "Read .agents/skills/orch/SKILL.md first. The person talks to you here: in Focus, or in a terminal "
        "joined to this session. Answer short and in plain words, in the person's language.",
        "You look after the workspace's tickets and helpers with the full rights of a normal helper: "
        "orch ticket list, orch run list, orch run status, starting, nudging or stopping helpers, making, "
        "tidying and sorting tickets, and answering what the person asks about them. Real work on a ticket "
        "belongs to that ticket's own helper: start one for it instead of doing the work in this session.",
        "Ask before anything the orch skill's ask list names (cannot be undone, costs money, production, "
        "deletes real data, visible outside).",
        "Nothing ends this session by itself. When you finish an answer, wait for the next message.",
    ]
    if news:
        out.append("New since you last looked:\n" + news)
    return "\n\n".join(out)[:12000]


def status(root: Path) -> dict:
    """{ticket, running, attach}: ticket None before the Manager was first started."""
    tid = tickets.manager_id(root)
    if tid is None:
        return {"ticket": None, "running": False, "attach": None}
    return {"ticket": tid, "running": runs.running(root, tid), "attach": f"orch run attach {tid}"}


def start(root: Path, by: str, fresh: bool = False) -> dict:
    """Make the Manager when there is none, then start its live session (resume its conversation, or fresh).
    Already running: nothing happens, unless fresh, which ends it and starts an empty conversation."""
    tid = tickets.ensure_manager(root, by)
    was = runs.running(root, tid)
    if was and not fresh:
        return {**status(root), "started": False, "fresh": False, "notes": []}
    if was:
        runs_live.stop(root, tid)
    r = runs.start(root, tid, by, fresh=fresh, mode="live")
    return {**status(root), "started": True, "fresh": fresh, "run": r.get("run"), "notes": r.get("notes", [])}


def stop(root: Path) -> dict:
    """End the Manager's session (its conversation stays; the next start resumes it)."""
    tid = tickets.manager_id(root)
    stopped = bool(tid and runs.running(root, tid) and runs_live.stop(root, tid, hold=True))
    return {**status(root), "stopped": stopped}

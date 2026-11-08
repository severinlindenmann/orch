"""Mobile mode and the Relay tab's "Send a message" are what the dashboard shows of the relay add-on. Everything that names the add-on lives
in this file (the other dashboard sources name no add-on; a test keeps it that way)."""

from __future__ import annotations

import re
from pathlib import Path

HOURS = (4, 8, 12, 24)


def _actions():
    from . import actions  # imported late: actions builds its op table from this file

    return actions


def _bad(msg):
    return _actions().BadRequest(msg)


def _hours(v) -> int:
    if isinstance(v, bool) or v not in HOURS:
        raise _bad("Pick 4, 8, 12 or 24 hours.")
    return v


def _mobile_set(a):
    """Mobile mode on or off: `orch relay mobile on [--hours=N]` / `off` (the relay add-on does the work)."""
    _only = _actions()._only
    _only(a, ("on", "hours"))
    if not isinstance(a.get("on"), bool):
        raise _bad("Say on or off.")
    if not a["on"]:
        if "hours" in a:
            raise _bad("Hours only go with turning it on.")
        return ["relay", "mobile", "off"], [], []
    return ["relay", "mobile", "on"], ([f"--hours={_hours(a['hours'])}"] if "hours" in a else []), []


def _mobile_hours(a):
    """Save how long Mobile mode stays on by default: `orch relay mobile hours N`."""
    _only = _actions()._only
    _only(a, ("hours",))
    return ["relay", "mobile", "hours", str(_hours(a.get("hours")))], [], []


def _mobile_ack(a):
    """Dismiss the 'Mobile mode ended' notice: `orch relay mobile ack`."""
    _only = _actions()._only
    _only(a, ())
    return ["relay", "mobile", "ack"], [], []


PEER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


def _relay_send(a):
    """Send a text to a workspace or phone from the Relay tab: `orch relay send <peer> -- <text>`."""
    acts = _actions()
    acts._only(a, ("workspace", "text"))
    peer = a.get("workspace")
    if not (isinstance(peer, str) and PEER.fullmatch(peer)):
        raise _bad("Choose who to send to.")
    return ["relay", "send", peer], [], [acts._text(a.get("text"), "message")]


def _group_ticket(a):
    acts = _actions()
    return acts._tid(a.get("ticket"))


GROUP_ID = re.compile(r"grp_t_[a-z0-9]{6,16}")


def _group_say(a):
    """Write into a group chat. As the host (`ticket`): `orch relay group say <ticket> --dashboard -- <text>`.
    In a group this workspace was invited to (`group` + `host`): a member message to the host,
    `orch relay group reply <host> <group> -- <text>`."""
    acts = _actions()
    if "ticket" in a:
        acts._only(a, ("ticket", "text"))
        return ["relay", "group", "say", _group_ticket(a)], ["--dashboard"], [acts._text(a.get("text"), "message")]
    acts._only(a, ("group", "host", "text"))
    host, group = a.get("host"), a.get("group")
    if not (isinstance(host, str) and PEER.fullmatch(host)):
        raise _bad("Choose the group's host.")
    if not (isinstance(group, str) and GROUP_ID.fullmatch(group)):
        raise _bad("Choose a group.")
    return ["relay", "group", "reply", host, group], ["--dashboard"], [acts._text(a.get("text"), "message")]


def _group_member(verb):
    def op(a):
        acts = _actions()
        acts._only(a, ("ticket", "workspace"))
        peer = a.get("workspace")
        if not (isinstance(peer, str) and PEER.fullmatch(peer)):
            raise _bad("Choose a workspace.")
        return ["relay", "group", verb, _group_ticket(a), peer], [], []

    op.__doc__ = (
        f"{verb.title()} a workspace in a ticket's group: `orch relay group {verb} <ticket> <workspace>`."
    )
    return op


MOBILE_OPS = {
    "group.say": _group_say,
    "group.add": _group_member("add"),
    "group.remove": _group_member("remove"),
    "mobile.set": _mobile_set,
    "mobile.hours": _mobile_hours,
    "mobile.ack": _mobile_ack,
    "message.send": _relay_send,
}


def load_mobile(root: Path, orch_bin: str | None) -> dict | None:
    """Mobile mode from `orch relay mobile status --json` (the relay add-on). None when the add-on is not on here:
    the page then shows no switch. Only the fields the page uses, strings cut short."""
    from .data import run_orch  # late: data imports this file

    d = run_orch(orch_bin, ["relay", "mobile", "status", "--json"], root)
    if not isinstance(d, dict) or not isinstance(d.get("on"), bool):
        return None
    s = lambda v, n=80: v[:n] if isinstance(v, str) else None
    ended = d.get("ended")
    ended = (
        {
            "reason": s(ended.get("reason"), 10),
            "text": s(ended.get("text"), 200),
            "at": s(ended.get("at"), 30),
        }
        if isinstance(ended, dict) and ended.get("text")
        else None
    )
    choices = [h for h in (d.get("hours_choices") or []) if h in (4, 8, 12, 24)] or [4, 8, 12, 24]
    dh = d.get("default_hours")
    return {
        "on": d["on"],
        "default_hours": dh if dh in choices else 12,
        "hours_choices": choices,
        "awake": d.get("awake") if d.get("awake") in ("ok", "could_not_keep_awake") else None,
        "since": s(d.get("since"), 30),
        "ends_at": s(d.get("ends_at"), 30),
        "machine": s(d.get("machine"), 60),
        "ended": ended,
    }


def _short(v, n=200):
    return v[:n] if isinstance(v, str) else None


_WORD = re.compile(r"[a-z0-9-]{1,24}")


def _look(v):
    """Icon and colour ids only (a host-controlled look must never carry style or markup)."""
    if isinstance(v, dict) and isinstance(v.get("icon"), str) and isinstance(v.get("color"), str):
        if _WORD.fullmatch(v["icon"]) and _WORD.fullmatch(v["color"]):
            return {"icon": v["icon"], "color": v["color"]}
    return None


def _num(v, hi=2**31 - 1):
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= hi else None


def _strs(d, keys, n=200):
    return {k: _short(d.get(k), n) for k in keys if isinstance(d.get(k), str)} if isinstance(d, dict) else None


def _card(c):
    """The host's ticket card, field by field: short strings, small numbers, a short checklist."""
    if not isinstance(c, dict):
        return None
    q = c.get("question") if isinstance(c.get("question"), dict) else None
    return {
        **_strs(c, ("ticket", "key", "status"), 40),
        "title": _short(c.get("title"), 120),
        "summary": _short(c.get("summary"), 280),
        "question": _strs(q, ("question_id", "text"), 500) if q else None,
        "checklist": [
            {"text": _short(i.get("text"), 200), "done": bool(i.get("done"))}
            for i in (c.get("checklist") or [])[:20]
            if isinstance(i, dict)
        ],
        "done": _num(c.get("done"), 9999),
        "total": _num(c.get("total"), 9999),
        "rev": _num(c.get("rev")) or 0,
    }


def load_groups(root: Path, orch_bin: str | None) -> dict | None:
    """Group chats across workspaces from `orch relay group list --json`: the groups this workspace hosts (members,
    seen, task cards) and those it was invited to (members as the host listed them, the ticket card, the last
    messages). Read only; None when the add-on is not on here or there is no group."""
    from .data import run_orch  # late: data imports this file

    d = run_orch(orch_bin, ["relay", "group", "list", "--json"], root)
    if not isinstance(d, dict) or not (d.get("hosted") or d.get("joined")):
        return None

    def members(rows):
        return [
            {
                "ws": _short(x.get("ws"), 20),
                "name": _short(x.get("name"), 60),
                "look": _look(x.get("look")),
                "host": bool(x.get("host")),
                "joined_at": _short(x.get("joined_at"), 30),
                "left_at": _short(x.get("left_at"), 30),
                "seen": x.get("seen") if isinstance(x.get("seen"), int) else None,
            }
            for x in rows
            if isinstance(x, dict)
        ]

    hosted = [
        {
            "id": _short(g.get("id"), 30),
            "ticket": _short(g.get("ticket"), 20),
            "title": _short(g.get("title"), 120),
            "closed": bool(g.get("closed")),
            "seq": g.get("seq") if isinstance(g.get("seq"), int) else 0,
            "members": members(g.get("members") or []),
            "connectable": [
                {"ws": _short(c.get("ws"), 20), "name": _short(c.get("name"), 60)}
                for c in g.get("connectable") or []
                if isinstance(c, dict)
            ],
            "tasks": [
                {
                    k: _short(v, 120)
                    for k, v in t.items()
                    if k in ("delegate", "ws", "ticket", "key", "title", "status")
                }
                for t in g.get("tasks") or []
                if isinstance(t, dict)
            ],
        }
        for g in d.get("hosted") or []
        if isinstance(g, dict)
    ]
    joined = [
        {
            "host": _short(g.get("host"), 20),
            "id": _short(g.get("id"), 30),
            "title": _short(g.get("title"), 120),
            "closed": bool(g.get("closed")),
            "left": bool(g.get("left")),
            "seq_max": g.get("seq_max") if isinstance(g.get("seq_max"), int) else 0,
            "members": members(g.get("members") or []),
            "card": _card(g.get("card")),
            "log": [
                {
                    "id": _short(x.get("id"), 20),
                    "seq": _num(x.get("seq")),
                    "type": _short(x.get("type"), 12),
                    "at": _short(x.get("at"), 32),
                    "shown": _short(x.get("shown"), 80),
                    "text": _short(x.get("text"), 600),
                    "authority": False,
                    "late": bool(x.get("late")),
                    "task": _strs(x.get("task"), ("delegate", "ws", "ticket", "key", "title", "status"), 120),
                    "event": _strs(x.get("event"), ("kind", "ws", "name", "reason", "mode"), 60),
                    "file": _strs(x.get("file"), ("blob_id", "name", "sha256", "title"), 200),
                }
                for x in (g.get("log") or [])[-50:]
                if isinstance(x, dict)
            ],
        }
        for g in d.get("joined") or []
        if isinstance(g, dict)
    ]
    return {"hosted": hosted, "joined": joined}

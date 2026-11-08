# ruff: noqa: E501
"""Chat: the one conversation of a workspace with the person's phones and dashboard (former General).

contracts/chat-groups.md section 1. The hidden General ticket (`general: true`) is the record and the
helper's session; this module holds what is only about the conversation: the Chat day (local wall time, day
starts 04:00), one file per day under .orch/chat/ (History), the daily fresh start of the helper's session,
cards (refs) and the numbers of the activity strip. Nothing here goes on the wire except body.by / via / day
(relay.send_text); cards are local data (the contract: "not a wire field in v1")."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import re
import tomllib
from pathlib import Path

from orch import net, phone_view, relay, runs, runs_live, tickets
from orch.errors import Refused

CUT_HOUR = 4  # local wall clock: before 04:00 still belongs to the day before
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
KEY_RE = re.compile(r"\b[A-Z0-9]{2,4}-[1-9][0-9]{0,8}\b")
MAX_DAY_MESSAGES = 2000
MAX_TEXT = 20000  # Chat keeps 20000 characters (contract section 5)
REF_KINDS = ("ticket", "reference", "file")
# a file card names a file inside the workspace; never under .orch/ or .git/, never a key, token or login file
_NOT_FILES = re.compile(
    r"(^|/)(\.orch|\.git|\.ssh|\.gnupg|\.aws|secrets)(/|$)"
    r"|(^|/)(\.env[^/]*|\.npmrc|\.netrc|\.pypirc|\.git-credentials|id_(rsa|dsa|ecdsa|ed25519)[^/]*)$"
    r"|\.(pem|key|p8|p12|pfx|jks|kdbx|sqlite3?|db)(\.[^/]*)?$|token|credential|secret|password",
    re.I,
)


def tz_of(root: Path):
    """The workspace's zone: `[workspace] tz` in .orch/config.toml, else the machine's local zone."""
    with contextlib.suppress(Exception):
        import zoneinfo

        cfg = tomllib.loads((root / ".orch" / "config.toml").read_text(encoding="utf-8"))
        name = (cfg.get("workspace") or {}).get("tz")
        if isinstance(name, str) and name:
            try:
                return zoneinfo.ZoneInfo(name)
            except (zoneinfo.ZoneInfoNotFoundError, ValueError):
                import sys

                print(
                    f"orch: the time zone '{name}' in .orch/config.toml is not known; using this computer's.",
                    file=sys.stderr,
                )
    return None  # astimezone(None) = the machine's local zone


def _parse(at) -> dt.datetime:
    if isinstance(at, dt.datetime):
        return at if at.tzinfo else at.replace(tzinfo=dt.UTC)
    if isinstance(at, str):
        with contextlib.suppress(ValueError):
            return dt.datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(dt.UTC)
    return dt.datetime.now(dt.UTC)


def day_key(root: Path, at=None) -> str:
    """The Chat day (body.day): the workspace's local date of `at`, or the date before while the local wall
    clock shows before 04:00. Wall clock on purpose (a DST day stays right): never "minus 4 hours"."""
    local = _parse(at).astimezone(tz_of(root))
    d = local.date()
    if local.hour < CUT_HOUR:
        d -= dt.timedelta(days=1)
    return d.isoformat()


def helper_name(root: Path) -> str:
    """ "<Workspace> helper" (display rule: never sent as text)."""
    with contextlib.suppress(Exception):
        name = relay.name_of(root, relay._cfg(root)["workspace"])
        if name and not name.startswith("ws_"):
            return f"{name} helper"
    return f"{root.name} helper"


# ---------------------------------------------------------------- the record: one file per day


def chat_dir(root: Path) -> Path:
    return root / ".orch" / "chat"


def _day_path(root: Path, day: str) -> Path:
    if not DAY_RE.fullmatch(day or ""):
        raise Refused("A day looks like 2026-11-08.")
    return chat_dir(root) / f"{day}.json"


def _read_day(root: Path, day: str) -> dict:
    d = net.read_json(_day_path(root, day), None)
    if not isinstance(d, dict) or not isinstance(d.get("messages"), list):
        return {"schema": "orch.chat-day/1", "day": day, "messages": []}
    return d


def clean_refs(root: Path, refs) -> list[dict]:
    """Cards of a message: tickets (by key or id, found here), references (safe http(s) links) and files
    (a path inside the workspace, never a secret). Anything else is dropped."""
    out: list[dict] = []
    for r in refs if isinstance(refs, list) else []:
        if not isinstance(r, dict) or r.get("kind") not in REF_KINDS or len(out) >= 10:
            continue
        kind = r["kind"]
        if kind == "ticket":
            t = _find_ticket(root, str(r.get("key") or r.get("id") or ""))
            if t:
                out.append(
                    {
                        "kind": "ticket",
                        "id": t["id"],
                        "key": t.get("key"),
                        "title": phone_view._clip(t.get("title", ""), 120),
                    }
                )
        elif kind == "reference":
            url = phone_view.safe_url(str(r.get("url") or ""))
            if url:
                out.append(
                    {
                        "kind": "reference",
                        "url": url,
                        "title": phone_view._clip(str(r.get("title") or url), 120),
                    }
                )
        else:
            p = safe_file(root, str(r.get("path") or ""))
            if p:
                out.append(
                    {
                        "kind": "file",
                        "path": p,
                        "title": phone_view._clip(str(r.get("title") or Path(p).name), 120),
                    }
                )
    return out


def _find_ticket(root: Path, ref: str) -> dict | None:
    ref = ref.strip()
    if not ref:
        return None
    for t in tickets.list_all(root):
        if t.get("id") == ref or (t.get("key") and t["key"] == ref):
            return t
    return None


def safe_file(root: Path, rel_path: str) -> str | None:
    """A file card names a file inside the workspace (real path, links resolved); secrets are never one."""
    if not rel_path or "\x00" in rel_path:
        return None
    try:
        base = root.resolve()
        real = (base / rel_path).resolve()
        rel = real.relative_to(base).as_posix()
    except (ValueError, OSError):
        return None
    if not real.is_file() or _NOT_FILES.search(rel):
        return None
    return rel


def refs_in_text(root: Path, text: str) -> list[dict]:
    """Ticket cards for the keys a text names (FIN-14) that exist here: what the helper opened or made."""
    seen: list[dict] = []
    for k in dict.fromkeys(KEY_RE.findall(text or "")):
        seen += clean_refs(root, [{"kind": "ticket", "key": k}])
    return seen


def record(
    root: Path,
    mid: str,
    by: str,
    via: str,
    text: str,
    at: str | None = None,
    reply_to: str | None = None,
    phone: str | None = None,
    refs: list[dict] | None = None,
) -> dict:
    """Add one Chat text to its day's file (once per message id). by: "you" or the workspace id."""
    at = at or tickets.now()
    day = day_key(root, at)
    entry: dict = {"id": mid, "at": at, "by": by, "via": via, "text": str(text)[:MAX_TEXT], "day": day}
    if reply_to:
        entry["reply_to"] = reply_to
    if phone:
        entry["phone"] = phone
    cards = clean_refs(root, refs or []) + [c for c in refs_in_text(root, text) if c["kind"] == "ticket"]
    uniq = list({json.dumps(c, sort_keys=True): c for c in cards}.values())
    if uniq:
        entry["refs"] = uniq[:10]
    with tickets._locked(root, "chat"):
        d = _read_day(root, day)
        if any(m.get("id") == mid for m in d["messages"]):
            return next(m for m in d["messages"] if m.get("id") == mid)
        d["messages"] = [*d["messages"], entry][-MAX_DAY_MESSAGES:]
        net.write_json(_day_path(root, day), d, True)
    return entry


def days(root: Path) -> list[dict]:
    """History: every day that has texts, newest first: [{day, count, last}] (nothing is ever deleted)."""
    out = []
    if chat_dir(root).is_dir():
        for p in chat_dir(root).glob("*.json"):
            if not DAY_RE.fullmatch(p.stem):
                continue
            d = _read_day(root, p.stem)
            if d["messages"]:
                last = d["messages"][-1]
                out.append(
                    {
                        "day": p.stem,
                        "count": len(d["messages"]),
                        "last": phone_view._clip(last.get("text", ""), 120),
                    }
                )
    return sorted(out, key=lambda x: x["day"], reverse=True)


def read_day(root: Path, day: str) -> dict:
    """One day, read only: {day, today, messages}."""
    d = _read_day(root, day)
    msgs = []
    for m in d["messages"]:
        if isinstance(
            m.get("refs"), list
        ):  # a file card is checked again now (a link may have changed since)
            m = {
                **m,
                "refs": [
                    r for r in m["refs"] if r.get("kind") != "file" or safe_file(root, r.get("path", ""))
                ],
            }
        msgs.append(m)
    return {"day": day, "today": day == day_key(root), "messages": msgs}


# ---------------------------------------------------------------- the helper's daily fresh start


def session_day(ticket: dict) -> str | None:
    c = (ticket.get("ext") or {}).get("chat")
    return c.get("session_day") if isinstance(c, dict) else None


def cut_session(root: Path, tid: str, now=None) -> bool:
    """04:00: the helper's session of an earlier Chat day ends. Its stored session ids go, so the next
    message starts an empty one (runs.plan resumes only a stored session). Returns True when it was cut.
    The first start of a new day records the day. Called by runs.plan before every start."""
    today = day_key(root, now)

    def op(t):
        if session_day(t) == today:
            return tickets.NO_WRITE
        had = bool(t.get("sessions"))
        t["sessions"] = []
        t.setdefault("ext", {})["chat"] = {"session_day": today}
        return had

    return tickets.apply_op(root, tid, op)[1] is True


# ---------------------------------------------------------------- what the person writes in the dashboard


def say(root: Path, text: str, by: str | None = None) -> dict:
    """The person writes in Chat from the dashboard: kept in the day file and the General history as theirs
    (by "you", via dashboard), queued as human input so the automation host starts the helper, and sent to
    the paired phones (only when a relay is connected: otherwise it stays local)."""
    text = (text or "").strip()
    if not text or len(text) > MAX_TEXT:
        raise Refused("A Chat text has 1 to 20000 characters.")
    who = tickets.current_actor(by)
    if not who.startswith("human:") or tickets.agent_tool():
        raise Refused("Only a person writes as themselves in Chat.")
    gid = tickets.ensure_general(root, who)
    mid = relay.new_id()
    entry = record(root, mid, "you", "dashboard", text)
    tickets.apply_op(root, gid, lambda t: tickets.add_history(t, who, text, "dashboard"))
    runs.pending_add(root, gid, who, "message", text, "dashboard", "p_" + mid[2:])
    sent = None
    with contextlib.suppress(Refused, OSError):
        sent = relay.send_text(
            root, "phones", text, None, None, None, general=True, sender="you", via="dashboard", mid=mid
        )
    return {"id": mid, "ticket": gid, "day": entry["day"], "sent": bool(sent)}


# ---------------------------------------------------------------- dashboard data


def activity(root: Path, now=None) -> dict:
    """The strip (fb2): {phone_today, from_workspaces: {name: n}, running}. Counts are for the Chat day."""
    today = day_key(root, now)
    phone = 0
    for m in _read_day(root, today)["messages"]:
        if m.get("via") == "phone" and m.get("by") == "you":
            phone += 1
    gid = tickets.general_id(root)
    from_ws: dict[str, int] = {}
    inbox = root / ".orch" / "inbox"
    for f in inbox.glob("m_*.json") if inbox.is_dir() else []:
        m = net.read_json(f, None)
        if (
            not isinstance(m, dict)
            or not str(m.get("from", "")).startswith("ws_")
            or m.get("type") not in relay_view_kinds()
        ):
            continue
        if day_key(root, m.get("created_at")) == today:
            n = relay.name_of(root, m["from"])
            from_ws[n] = from_ws.get(n, 0) + 1
    running = sum(1 for r in runs_live.records(root) if runs.state(r) == "alive" and r.get("ticket") != gid)
    return {"day": today, "phone_today": phone, "from_workspaces": from_ws, "running": running}


def relay_view_kinds():
    from orch import relay_view

    return relay_view.KINDS


def chat_id(root: Path) -> dict:
    """Cheap, for the automation pass: the Chat ticket (None before the first text) and whether it is paused."""
    gid = tickets.general_id(root)
    paused = False
    if gid:
        with contextlib.suppress(Refused, OSError, ValueError):
            paused = ((tickets.load(root, gid).get("ext") or {}).get("automation") or {}).get(
                "paused"
            ) is True
    return {"ticket": gid, "paused": paused}


def status(root: Path, now=None) -> dict:
    """What the dashboard shows: helper name, today, the day's texts, the strip, the History list."""
    gid = tickets.general_id(root)
    today = day_key(root, now)
    waiting = [i["id"] for i in runs.human_waiting(root, gid)] if gid else []
    return {
        "helper": helper_name(root),
        "ticket": gid,
        "day": today,
        "messages": _read_day(root, today)["messages"][-200:],
        "activity": activity(root, now),
        "days": days(root),
        "running": bool(gid and runs.running(root, gid)),
        "human_pending_ids": waiting,
    }


def helper_prompt(root: Path, ticket: dict, items: list[dict], news: str) -> str:
    """What a fresh helper session starts with (the Chat of one workspace, one persistent helper)."""
    tid = ticket["id"]
    out = [
        f"You are {helper_name(root)}: the one helper of this workspace. A person writes to you in Chat from "
        f"their phone or the dashboard; this hidden ticket ({tid}) is your conversation.",
        "Read .agents/skills/orch/SKILL.md first. Answer short and in plain words, in the person's language.",
        f'Answer with: orch relay send <phone id of the message> "<answer>" --ticket {tid} '
        "--reply-to <message id>. "
        "Add --ref ticket:<KEY> for a ticket you made or opened, --ref reference:<url> or --ref file:<path> "
        "for something you point to: they show as cards.",
        "You may make tickets (orch ticket new), write notes and answer questions. You never sign, approve, "
        "publish, close, drop or delete anything, and you never answer a permission question: those are for "
        "the person.",
        "Your conversation is cleared every day at 04:00; keep nothing you need in your head: make a ticket.",
    ]
    if news:
        out.append("New since you last looked:\n" + news)
    return "\n\n".join(out)[:12000]


# ---------------------------------------------------------------- the helper's role (enforced here, not in the prompt)

# The Chat helper may run exactly these (cmd, sub) pairs and nothing else (an allowlist: a new command is
# refused until it is listed here). The run hooks the wrapper itself calls are included; start/stop/send/attach
# of runs are not.
HELPER_ALLOWED = frozenset(
    {
        ("ticket", "new"),
        ("ticket", "show"),
        ("ticket", "list"),
        ("ticket", "tree"),
        ("log", None),
        ("check", "add"),
        ("ref", "add"),
        ("ref", "list"),
        ("relay", "send"),
        ("relay", "topic"),
        ("chat", "status"),
        ("chat", "days"),
        ("chat", "day"),
        ("chat", "id"),
        ("needs", None),
        ("status", None),
        ("run", "claim"),
        ("run", "release"),
        ("run", "status"),
        ("run", "session"),
        ("run", "argv"),
        ("run", "event"),
        ("run", "done"),
    }
)
HELPER_FLAGS_DENIED = (
    "take_over",
    "fresh",
    "force",
    "file",
)  # --take-over, --fresh, --force, relay send --file
HELPER_TARGET_FIELDS = ("id", "ticket", "parent")
_PHONE_TARGET = re.compile(r"phones|ph_[a-z0-9]{10}")


def is_helper(root: Path) -> bool:
    """An agent whose run is the Chat ticket's (ORCH_TICKET in its environment = the General id). The
    environment is the same-user boundary: an agent that strips it is as free as it is for `orch run start`."""
    import os

    gid = tickets.general_id(root)
    return bool(gid and tickets.agent_tool() and os.environ.get("ORCH_TICKET") == gid)


def guard(root: Path, args) -> None:
    """The helper makes tickets, notes and answers to the person. It never signs, approves, publishes, closes,
    drops, deletes, answers a question, starts or stops another run, or changes the Chat ticket (general flag,
    ext.chat, sessions, status): everything outside HELPER_ALLOWED is refused (Refused, exit 2)."""
    if not is_helper(root):
        return
    cmd, sub = getattr(args, "cmd", None), getattr(args, "sub", None)
    if (cmd, sub) not in HELPER_ALLOWED or getattr(args, "wsub", None) is not None:
        raise Refused(
            "The Chat helper cannot do that. It can make tickets, notes and answers; the rest is the person's."
        )
    if any(getattr(args, f, None) for f in HELPER_FLAGS_DENIED):
        raise Refused("The Chat helper cannot use that option.")
    gid = tickets.general_id(root)
    for f in HELPER_TARGET_FIELDS:  # every field that names a ticket, keys resolved to ids
        v = getattr(args, f, None)
        if isinstance(v, str) and v:
            try:
                v = tickets.resolve(root, v)
            except Refused:
                continue
            if v == gid and (cmd, sub) not in {
                ("ticket", "show"),
                ("ticket", "list"),
                ("ticket", "tree"),
                ("run", "claim"),
                ("run", "release"),
                ("run", "status"),
                ("run", "session"),
                ("run", "argv"),
                ("run", "event"),
                ("run", "done"),
                ("relay", "send"),
            }:
                raise Refused("The Chat conversation itself is not changed by the helper.")
    if cmd == "relay" and sub == "send":
        if not _PHONE_TARGET.fullmatch(str(getattr(args, "workspace", ""))) or getattr(args, "update", None):
            raise Refused("The Chat helper answers the person's phone with a plain text only.")

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
REF_KINDS = ("ticket", "reference", "file", "proposal")
# a file card names a file inside the workspace; never under .orch/ or .git/, never a key, token or login file
_NOT_FILES = re.compile(
    r"(^|/)(\.orch|\.git|\.ssh|\.gnupg|\.aws|\.kube|\.docker|secrets)(/|$)"
    r"|(^|/)(\.env[^/]*|\.npmrc|\.netrc|\.pypirc|\.git-credentials|\.pgpass|\.htpasswd|\.bash_history|\.zsh_history|auth\.json|terraform\.tfstate[^/]*|id_(rsa|dsa|ecdsa|ed25519)[^/]*)$"
    r"|\.(pem|key|p8|p12|pfx|jks|kdbx|sqlite3?|db)([.-][^/]*)?$|token|credential|secret|password",
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
    d["messages"] = [
        m for m in d["messages"] if isinstance(m, dict)
    ]  # a hand-edited file never crashes a read
    return d


def clean_refs(root: Path, refs) -> list[dict]:
    """Cards of a message: tickets (by key or id, found here), references (safe http(s) links) and files
    (a path inside the workspace, never a secret). Anything else is dropped."""
    out: list[dict] = []
    helper = is_helper(root)  # who adds the card decides the file rule it keeps for life (added_by)
    by = "helper" if helper else "person"
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
                        "added_by": by,
                    }
                )
        elif kind == "proposal":
            title = str(r.get("title") or "").strip()
            if title:
                out.append({"kind": "proposal", "title": phone_view._clip(title, 120), "added_by": by})
        elif kind == "reference":
            url = phone_view.safe_url(str(r.get("url") or ""))
            if url:
                out.append(
                    {
                        "kind": "reference",
                        "url": url,
                        "title": phone_view._clip(str(r.get("title") or url), 120),
                        "added_by": by,
                    }
                )
        else:
            p = (helper_safe_file if helper else safe_file)(root, str(r.get("path") or ""))
            if p:
                out.append(
                    {
                        "kind": "file",
                        "path": p,
                        "title": phone_view._clip(str(r.get("title") or Path(p).name), 120),
                        "added_by": by,
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
    """A file card names a file inside the workspace (real path, links resolved); secrets are never one.
    The rule for everyone (a person at the CLI, the dashboard): unchanged semantics."""
    if not rel_path or "\x00" in rel_path:
        return None
    try:
        base = root.resolve()
        real = (base / rel_path).resolve()
        rel = real.relative_to(base).as_posix()
        if (
            not real.is_file() or real.stat().st_nlink > 1 or _NOT_FILES.search(rel)
        ):  # a hard link may be a secret
            return None
    except (ValueError, OSError):
        return None
    return rel


def helper_safe_file(root: Path, rel_path: str) -> str | None:
    """Stricter, for what the Chat helper (an agent) may name: backslashes mean `/`, no absolute, drive, `~` or
    `..` path, no folder that is a link, nothing under .orch or .git (safefile.file_ref_ok), then safe_file."""
    import posixpath
    from pathlib import PureWindowsPath

    from orch import safefile

    if not rel_path or "\x00" in rel_path:
        return None
    rel_path = rel_path.replace("\\", "/")
    if Path(rel_path).is_absolute() or PureWindowsPath(rel_path).drive or rel_path.startswith("~"):
        return None
    norm = posixpath.normpath(rel_path)
    if (
        norm in (".", "..")
        or norm.startswith("../")
        or ".." in norm.split("/")
        or not safefile.file_ref_ok(root, norm)
    ):
        return None
    return safe_file(root, norm)


def file_rule(added_by):
    """The file rule a card keeps: a card a person added keeps the person rule; anything else (the helper's, or
    a card without the mark) gets the strict helper rule."""
    return safe_file if added_by == "person" else helper_safe_file


def read_file(
    root: Path, rel_path: str, max_bytes: int = 5_000_000, added_by: str | None = None
) -> bytes | None:
    """The bytes of a file card, for whoever serves it. added_by is the card's mark ("person" keeps the person
    rule, anything else the strict helper rule). None = not allowed."""
    from orch import safefile

    p = file_rule(added_by)(root, rel_path)
    if not p:
        return None
    if added_by == "person":
        return _read_resolved(root, p, max_bytes)
    try:
        # open_file_ref (safefile._read_parts) opens every folder without following links, then fstat()s the file:
        # regular file and st_nlink == 1, same dev/ino as lstat; anything else is None
        return safefile.open_file_ref(root, p, max_bytes)
    except Exception:  # noqa: BLE001 - TooLarge, OSError, anything: a card that cannot be read is no card
        return None


def _read_resolved(root: Path, rel: str, max_bytes: int) -> bytes | None:
    """A person's card: safe_file already resolved the real path inside the workspace (outside .orch, .git and the
    secret names), so open that path without following a last link and check what was opened."""
    import os
    import stat

    real = root.resolve() / rel
    try:
        before = real.lstat()
        fd = os.open(real, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        same = (st.st_dev, st.st_ino) == (before.st_dev, before.st_ino)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or not same or st.st_size > max_bytes:
            return None
        with os.fdopen(fd, "rb", closefd=False) as f:
            return f.read(max_bytes + 1)[:max_bytes]
    except OSError:
        return None
    finally:
        os.close(fd)


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
    convo_start: bool = False,
) -> dict:
    """Add one Chat text to its day's file (once per message id). by: "you" or the workspace id."""
    at = at or tickets.now()
    day = day_key(root, at)
    entry: dict = {"id": mid, "at": at, "by": by, "via": via, "text": str(text)[:MAX_TEXT], "day": day}
    if convo_start:
        entry["convo_start"] = True
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
        if by == "you" and not convo_start:
            latest = next(iter(days(root)), None)
            previous = _read_day(root, latest["day"])["messages"][-1] if latest else None
            if previous and previous.get("moved_to"):
                entry["convo_start"] = True
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
    for m in d["messages"]:  # _read_day keeps only dict entries
        if isinstance(
            m.get("refs"), list
        ):  # a file card is checked again now (a link may have changed since)
            ok = [
                r
                for r in m["refs"]
                if isinstance(r, dict)
                and (r.get("kind") != "file" or file_rule(r.get("added_by"))(root, str(r.get("path", ""))))
            ]
            m = {**m, "refs": ok}
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


def say(root: Path, text: str, by: str | None = None, new: bool = False) -> dict:
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
    entry = record(root, mid, "you", "dashboard", text, convo_start=new)
    tickets.apply_op(root, gid, lambda t: tickets.add_history(t, who, text, "dashboard", chat=True))
    runs.pending_add(root, gid, who, "message", text, "dashboard", "p_" + mid[2:])
    sent = None
    with contextlib.suppress(Refused, OSError):
        sent = relay.send_text(
            root, "phones", text, None, None, None, general=True, sender="you", via="dashboard", mid=mid
        )
    return {"id": mid, "ticket": gid, "day": entry["day"], "sent": bool(sent)}


def make_ticket(root: Path, mid: str, title: str | None = None, by: str | None = None) -> dict:
    """Move a proposed conversation into a normal ticket, once, on the person's click."""
    who = tickets.current_actor(by)
    if tickets.agent_tool() or not who.startswith("human:"):
        raise Refused("Only a person makes a ticket from Chat.")
    with tickets._locked(root, "chat"):
        documents = [_read_day(root, row["day"]) for row in reversed(days(root))]
        entries = [m for d in documents for m in d["messages"]]
        end = next((i for i in range(len(entries) - 1, -1, -1) if entries[i].get("id") == mid), None)
        if end is None:
            raise Refused("That Chat message was not found.")
        message = entries[end]
        proposals = [r for r in message.get("refs", []) if r.get("kind") == "proposal"]
        if not proposals:
            raise Refused("That Chat message has no ticket proposal.")
        made = message.get("moved_to") or next((r["made"] for r in proposals if r.get("made")), None)
        if made:
            t = tickets.load(root, made["id"])
            return {"ticket": t["id"], "key": t["key"], "title": t["title"]}
        start = next((i for i in range(end, -1, -1) if entries[i].get("convo_start")), 0)
        conversation = entries[start : end + 1]
        helper = helper_name(root)
        note = "\n\n".join(
            ("You" if m.get("by") == "you" else helper) + ": " + m.get("text", "") for m in conversation
        )
        # Ticket notes have a 2000-character schema limit; history below keeps every complete text.
        t = tickets.create(
            root, title if title is not None else proposals[0]["title"], who, fields={"note": note[:2000]}
        )

        def copy_history(ticket):
            for m in conversation:
                tickets.add_history(
                    ticket,
                    who if m.get("by") == "you" else "agent:" + helper,
                    m.get("text", ""),
                    m.get("via"),
                )
                ticket["history"][-1]["at"] = m.get("at", ticket["history"][-1]["at"])

        tickets.apply_op(root, t["id"], copy_history)
        moved = {"id": t["id"], "key": t["key"], "title": t["title"]}
        for m in conversation:
            m["moved_to"] = moved
            for ref in m.get("refs", []):
                if ref.get("kind") == "proposal":
                    ref["made"] = {"id": t["id"], "key": t["key"]}
        moved_entries = {id(m) for m in conversation}
        for d in documents:
            if any(id(m) in moved_entries for m in d["messages"]):
                net.write_json(_day_path(root, d["day"]), d, True)
        return {"ticket": t["id"], "key": t["key"], "title": t["title"]}


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


STAY_IN_ORCH = (
    "You can only use orch tools and the files in this workspace. Never offer, suggest or use other services, "
    "accounts or connectors (email, calendar, drives, chat apps or similar), even if your environment lists some. "
    "If asked for one, say you cannot and offer an orch ticket instead."
)


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
        "When the person has told you enough to make a ticket, ask 'Ready. Shall I make this a ticket?' "
        "and add --ref proposal:<short ticket title>. Never make the ticket yourself in this talk: "
        "the person clicks Make ticket. You may write notes and answer questions. You never sign, approve, "
        "publish, close, drop or delete anything, and you never answer a permission question: those are for "
        "the person.",
        STAY_IN_ORCH,
        "Your conversation is cleared every day at 04:00; keep important context in the conversation.",
    ]
    if news:
        out.append("New since you last looked:\n" + news)
    return "\n\n".join(out)[:12000]


# ---------------------------------------------------------------- the helper's role (enforced here, not in the prompt)

# The Chat helper may run exactly these (cmd, sub) pairs, each with exactly these arguments (argparse dests), and
# nothing else: a new command or option is refused until it is listed here. HELPER_TARGETS names the dests that
# hold a ticket (keys are resolved; a target that does not resolve is refused). `--by`, `--phone`, `--take-over`,
# `--fresh`, `--file`, `--update` are in no list. kind: "write" targets must not be the Chat ticket, "read" may be,
# "run" (the wrapper's hooks) must be the Chat ticket and, when given, the helper's own run (ORCH_RUN).
HELPER_COMMANDS = {
    ("ticket", "new"): ("write", {"title", "parent", "due", "note"}, ("parent",)),
    ("ticket", "show"): ("read", {"id"}, ("id",)),
    ("ticket", "list"): ("read", {"status", "all"}, ()),
    ("ticket", "tree"): ("read", {"id"}, ("id",)),
    ("log", None): ("write", {"id", "text"}, ("id",)),
    ("check", "add"): ("write", {"id", "text"}, ("id",)),
    ("ref", "add"): ("write", {"id", "target", "kind", "title"}, ("id",)),
    ("ref", "list"): ("read", {"id"}, ("id",)),
    ("relay", "send"): (
        "relay",
        {"workspace", "text", "reply_to", "ticket", "summary", "speak", "ref"},
        ("ticket",),
    ),
    ("relay", "topic"): ("plain", {"message", "title"}, ()),  # makes a ticket from a phone text; no target
    ("chat", "status"): ("read", set(), ()),
    ("chat", "days"): ("read", set(), ()),
    ("chat", "day"): ("read", {"day"}, ()),
    ("chat", "id"): ("read", set(), ()),
    ("needs", None): ("read", set(), ()),
    ("status", None): ("read", set(), ()),
    ("run", "claim"): ("run", {"ticket", "agent", "pid"}, ("ticket",)),
    ("run", "release"): ("run", {"ticket", "run"}, ("ticket",)),
    ("run", "done"): ("run", {"ticket", "run"}, ("ticket",)),
    ("run", "input"): ("run", {"ticket"}, ("ticket",)),
    ("run", "status"): ("run", {"ticket"}, ("ticket",)),
    ("run", "session"): ("run", {"ticket", "agent"}, ("ticket",)),
    ("run", "argv"): ("run", {"ticket", "agent", "session"}, ("ticket",)),
    ("run", "event"): ("run", {"ticket", "kind", "run", "session_id"}, ("ticket",)),
}
_NO_DEST = {"cmd", "sub", "json", "wsub", "func"}
_PHONE_TARGET = re.compile(r"phones|ph_[a-z0-9]{10}")


def is_helper(root: Path) -> bool:
    """An agent whose run is the Chat ticket's (ORCH_TICKET in its environment = the General id). The
    environment is the same-user boundary: an agent that strips it is as free as it is for `orch run start`."""
    import os

    want = os.environ.get("ORCH_TICKET")
    if not want or not tickets.agent_tool():
        return False  # a person (or any agent outside a run) never reads the ticket folder here: init works anywhere
    return want == tickets.general_id(root)


def _check_ref_add(root: Path, args, no: Refused) -> None:
    """A reference the helper adds is normalised exactly as `orch ref add` does (refs.detect), then must be a web
    link, a ticket, or a project file safe_file accepts (inside the workspace, not local/absolute): nothing else."""
    from orch import refs

    try:
        owner = tickets.resolve(
            root, getattr(args, "id", None) or ""
        )  # detect's 2nd argument: the owning ticket
        d = refs.detect(
            root,
            owner if isinstance(owner, str) else "",
            str(getattr(args, "target", "") or ""),
            getattr(args, "kind", None),
            getattr(args, "title", None),
        )
    except Refused:
        raise no from None
    if d.get("url") and d["kind"] not in ("ticket", "artifact", "file"):
        if re.match(r"https?://", str(d["url"]), re.I):
            return  # a web reference, http(s) only
        raise no
    if d["kind"] == "ticket":
        if d.get("ticket") == tickets.general_id(root):
            raise no  # the Chat ticket is hidden: no reference to it
        return
    if d["kind"] == "file" and not d.get("local") and helper_safe_file(root, d["path"]):
        return
    raise no  # an allowlist: web, ticket, safe file; artifacts and anything else are refused


def _given(args, cmd, sub) -> set[str]:
    """The options and arguments that differ from the parser's own default (a store_false flag set to False counts)."""
    from orch import cli

    p = cli.build_parser(show_all=True)
    try:
        for name in (cmd, sub):
            if name is None:
                continue
            action = p._subparsers._group_actions[0]  # noqa: SLF001
            p = action.choices[name]
    except (AttributeError, KeyError, IndexError):
        return set(vars(args)) - _NO_DEST  # cannot find the parser: everything counts as given
    return {k for k, v in vars(args).items() if k not in _NO_DEST and v != p.get_default(k)}


def guard(root: Path, args) -> None:
    """The helper makes tickets, notes and answers to the person. It never signs, approves, publishes, closes,
    drops, deletes, answers a question, starts or stops another run, or changes the Chat ticket (general flag,
    ext.chat, sessions, status): everything outside HELPER_COMMANDS is refused (Refused, exit 2)."""
    import os

    if not is_helper(root):
        return
    no = Refused(
        "The Chat helper cannot do that. It can make tickets, notes and answers; the rest is the person's."
    )
    cmd, sub = getattr(args, "cmd", None), getattr(args, "sub", None)
    entry = HELPER_COMMANDS.get((cmd, sub))
    if entry is None:
        raise no
    kind, allowed, targets = entry
    used = _given(args, cmd, sub)
    if used - allowed or getattr(args, "wsub", None) is not None:
        raise no
    gid = tickets.general_id(root)
    for f in targets:
        v = getattr(args, f, None)
        if not v:
            if kind == "write" and f in ("id", "ticket"):
                raise no  # a write names its ticket: an implicit one is ORCH_TICKET, the Chat ticket
            continue  # run hooks: the default is ORCH_TICKET = the Chat ticket; parent/ticket: none given
        try:
            rid = tickets.resolve(root, v)
        except Refused:
            raise no from None
        if not isinstance(rid, str) or not tickets._ID_RE.fullmatch(rid):
            raise no  # not a ticket we can name: refused, never skipped
        if kind in ("run", "relay") and rid != gid or kind == "write" and rid == gid:
            raise no
    if kind == "run" and getattr(args, "run", None) not in (None, os.environ.get("ORCH_RUN")):
        raise no  # only the helper's own run
    if (cmd, sub) == ("run", "claim") and getattr(args, "agent", None) not in (
        None,
        os.environ.get("ORCH_AGENT"),
    ):
        raise no
    if (cmd, sub) == ("run", "event") and getattr(args, "kind", None) not in (
        "session",
        "idle",
        "working",
        "attention",
    ):
        raise no
    if (cmd, sub) == ("ref", "add"):
        _check_ref_add(root, args, no)
    if kind == "relay":
        to = str(getattr(args, "workspace", ""))
        try:
            to = relay.resolve(root, to)
        except Refused:
            raise no from None
        paired = {p.get("id") for p in relay._read_dir(root).get("phones", []) if isinstance(p, dict)}
        if not _PHONE_TARGET.fullmatch(to) or (to != "phones" and to not in paired):
            raise Refused("The Chat helper answers the person's paired phones with a plain text only.")
        for r in getattr(args, "ref", None) or []:  # cards: checked now, again when stored and when read
            k, _, v = str(r).partition(":")
            if k not in REF_KINDS or (k == "file" and not helper_safe_file(root, v)):
                raise Refused("That card is not allowed.")

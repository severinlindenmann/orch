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
        m for m in d["messages"] if isinstance(m, dict) and not phone_view.internal_wakeup(m)
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
    files: list[dict] | None = None,
    summary: str | None = None,
) -> dict:
    """Add one Chat text to its day's file (once per message id). by: "you" or the workspace id.
    files: [{name, size}] attached to the Chat ticket with this message (chat_files checked them)."""
    at = at or tickets.now()
    day = day_key(root, at)
    entry: dict = {"id": mid, "at": at, "by": by, "via": via, "text": str(text)[:MAX_TEXT], "day": day}
    if convo_start:
        entry["convo_start"] = True
    if short := tickets.clean_summary(summary):
        entry["summary"] = short  # the helper's own short line of a long answer (O-19)
    if files:
        entry["files"] = [
            {"name": str(f["name"]), "size": int(f.get("size") or 0)} for f in files[:MAX_SAY_FILES]
        ]
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
            previous_messages = _read_day(root, latest["day"])["messages"] if latest else []
            previous = previous_messages[-1] if previous_messages else None
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

    return tickets.apply_op(root, tid, op, by=tickets.SYSTEM)[1] is True


# ---------------------------------------------------------------- what the person writes in the dashboard


MAX_SAY_FILES = 10  # the dashboard's message box takes up to 10 files (as the ticket page's)


def chat_files(root: Path, gid: str, names) -> list[dict]:
    """The files a person added to a Chat message: names of files already attached to the Chat ticket (the
    dashboard sends them with `ticket.attach` first). Each must be a plain file in its artifacts folder; a name
    with a folder in it, a link or a missing file is refused. Returns [{name, size}] for the day file."""
    names = list(names or [])
    if len(names) > MAX_SAY_FILES:
        raise Refused(f"A Chat message takes up to {MAX_SAY_FILES} files.")
    folder = tickets.artifacts_path(root, gid)
    out: list[dict] = []
    for name in names:
        name = str(name or "")
        p = folder / name
        if (
            not name
            or name in (".", "..")
            or "/" in name
            or "\\" in name
            or "\x00" in name
            # R1.6: on Windows `folder / "C:x"` leaves the folder (a drive-qualified name), and "x:y" names a
            # second stream of x. No attached file has such a name: refused on every system, as the other bad names
            or ":" in name
            or p.is_symlink()
            or not p.is_file()
        ):
            raise Refused(f"The file {name[:80]!r} is not in the Chat. Add it again.")
        if name not in [f["name"] for f in out]:
            out.append({"name": name, "size": p.stat().st_size})
    return out


def files_line(gid: str, files: list[dict]) -> str:
    """orch's line after the person's words in the helper's input: which files came with the message."""
    if not files:
        return ""
    names = ", ".join(f["name"] for f in files)
    what = "a file" if len(files) == 1 else f"{len(files)} files"
    return f"I added {what} to this chat: {names} (in .orch/tickets/{gid}/artifacts). Read {'it' if len(files) == 1 else 'them'} first."


def say(
    root: Path, text: str, by: str | None = None, new: bool = False, files: list[str] | None = None
) -> dict:
    """The person writes in Chat from the dashboard: kept in the day file and the General history as theirs
    (by "you", via dashboard), queued as human input so the automation host starts the helper, and sent to
    the paired phones (only when a relay is connected: otherwise it stays local). `files`: names of files
    already attached to the Chat ticket; the message shows them as file cards and the helper is told."""
    text = (text or "").strip()
    if (not text and not files) or len(text) > MAX_TEXT:
        raise Refused("A Chat text has 1 to 20000 characters.")
    who = tickets.current_actor(by)
    if not who.startswith("human:") or tickets.agent_tool():
        raise Refused("Only a person writes as themselves in Chat.")
    tickets.no_secret(root, {"text": text}, "Chat text")
    # R5.2: the file names go into the Chat history and the helper's input like the words: the same scan
    tickets.no_secret(
        root, {"name": [str(f or "") for f in list(files or [])[: MAX_SAY_FILES + 1]]}, "Chat file"
    )
    gid = tickets.ensure_general(root, who)
    kept = chat_files(root, gid, files)
    told = "\n\n".join(x for x in (text, files_line(gid, kept)) if x)
    # the phones get the words and the file names, never a folder on this computer
    shown = "\n\n".join(x for x in (text, ", ".join(f["name"] for f in kept)) if x)
    mid = relay.new_id()
    entry = record(root, mid, "you", tickets.PERSON_VIA, text, convo_start=new, files=kept)
    tickets.apply_op(
        root, gid, lambda t: tickets.add_history(t, who, told, tickets.PERSON_VIA, chat=True, mid=mid), by=who
    )
    runs.pending_add(root, gid, who, "message", told, tickets.PERSON_VIA, "p_" + mid[2:])
    sent = None
    with contextlib.suppress(Refused, OSError):
        sent = relay.send_text(
            root,
            "phones",
            shown,
            None,
            None,
            None,
            general=True,
            sender="you",
            via=tickets.PERSON_VIA,
            mid=mid,
        )
    return {"id": mid, "ticket": gid, "day": entry["day"], "sent": bool(sent)}


def _set_summary(root: Path, mid: str, summary: str) -> None:
    """Put the helper's short line on a Chat text the relay path already recorded (same day file, same lock)."""
    with tickets._locked(root, "chat"):
        for row in days(root)[:2]:
            d = _read_day(root, row["day"])
            hit = next((m for m in d["messages"] if m.get("id") == mid), None)
            if hit is not None:
                hit["summary"] = summary
                net.write_json(_day_path(root, row["day"]), d, True)
                return


def reply(
    root: Path,
    text: str,
    ticket: str,
    reply_to: str | None = None,
    refs: list[dict] | None = None,
    summary: str | None = None,
) -> dict:
    """The helper answers in Chat (`orch chat reply`). It is kept in the Chat history first; when a relay is
    connected the paired phones get it too. No relay (or the add-on off) is not an error: the dashboard shows it."""
    from orch import addons

    text = (text or "").strip()
    if not text or len(text) > MAX_TEXT:
        raise Refused("A Chat text has 1 to 20000 characters.")
    short = tickets.clean_summary(summary)
    tickets.no_secret(root, {"text": text, **({"summary": short} if short else {})}, "Chat text")
    gid = tickets.general_id(root)
    if not gid or tickets.resolve(root, ticket) != gid:
        raise Refused("A Chat answer belongs to the Chat ticket.")
    if "relay" in addons.active(root):
        try:
            msg = relay.send_text(root, "phones", text, gid, None, reply_to, general=True, refs=refs)
            if short:
                with contextlib.suppress(Exception):  # the answer is saved and sent; the short line is extra
                    _set_summary(root, msg["id"], short)
            return {"id": msg["id"], "sent": bool(msg.get("sent", True))}
        except Refused as e:
            if "not connected" not in str(e):
                raise
    who = tickets.current_actor()
    mid = relay.new_id()
    tickets.apply_op(
        root, gid, lambda t: tickets.add_history(t, who, text, chat=True, mid=mid, summary=short), by=who
    )
    record(root, mid, "helper", "helper", text, reply_to=reply_to, refs=refs, summary=short)
    return {"id": mid, "sent": False}


# ---------------------------------------------------------------- ticket chats (team chat step 1, ORCH-1168)

TICKET_CHAT_MAX = 8000  # what the ticket's pending input takes (runs._pending_add_locked)


def _chat_ticket(root: Path, ref: str) -> dict:
    """A ticket whose chat a person or its helper writes in: not the workspace Chat, Manager or a session."""
    t = tickets.load(root, tickets.resolve(root, ref))
    if tickets.is_hidden(t):
        raise Refused("That is not a ticket chat.")
    return t


def _ticket_text(text: str) -> str:
    text = (text or "").strip()
    if not text or len(text) > TICKET_CHAT_MAX:
        raise Refused(f"A ticket chat message has 1 to {TICKET_CHAT_MAX} characters.")
    return text


def ticket_hint(key: str) -> str:
    """orch's own line before a person's ticket chat message in the helper's input: where to answer."""
    return f'This message was written in the ticket\'s chat. Answer there: orch chat reply --ticket {key} "<your answer>"'


def say_ticket(root: Path, ref: str, text: str, by: str | None = None, by_name: str | None = None) -> dict:
    """A person writes in a ticket's chat (the dashboard Chats page): one chat line on the ticket (theirs, via
    dashboard, with the name they typed if any) and the same words handed to the ticket's helper, as Send to
    helper does; orch's hint line before it says where to answer. Nothing works on the ticket: it waits there
    and the next helper reads it first (the dashboard starts one, like Add to this ticket)."""
    text = _ticket_text(text)
    tickets.no_secret(root, {"text": text}, "chat message")
    who = tickets.current_actor(by)
    if not who.startswith("human:") or tickets.agent_tool():
        raise Refused(
            "Only a person writes as themselves in a ticket chat. A helper answers with orch chat reply."
        )
    t = _chat_ticket(root, ref)
    mid = tickets.chat_line_id()
    tickets.apply_op(
        root,
        t["id"],
        lambda tk: tickets.add_history(
            tk, who, text, tickets.PERSON_VIA, chat=True, mid=mid, by_name=by_name
        ),
        by=who,
    )
    runs.pending_add(root, t["id"], "orch", "event", ticket_hint(t.get("key") or t["id"]), "chat")
    sent = runs_live.send(root, t["id"], who, text)
    return {"id": mid, "ticket": t["id"], "key": t.get("key") or t["id"], "send": sent}


def reply_ticket(root: Path, ref: str, text: str, summary: str | None = None) -> dict:
    """The helper answers in a ticket's chat (`orch chat reply --ticket <id>` on a ticket that is not the
    workspace Chat): one chat line on the ticket by the helper."""
    text = _ticket_text(text)
    short = tickets.clean_summary(summary)
    tickets.no_secret(root, {"text": text, **({"summary": short} if short else {})}, "chat message")
    t = _chat_ticket(root, ref)
    who = tickets.current_actor()
    mid = tickets.chat_line_id()
    tickets.apply_op(
        root,
        t["id"],
        lambda tk: tickets.add_history(tk, who, text, chat=True, mid=mid, summary=short),
        by=who,
    )
    return {"id": mid, "ticket": t["id"], "key": t.get("key") or t["id"], "sent": False}


def proposal_state(root: Path, mid: str) -> str:
    """Where the proposal in Chat message `mid` stands: "open" (nobody made it), "making" (started, not finished:
    a retry finishes the same ticket), "made", or "gone" (no such proposal in the last days)."""
    today = dt.date.fromisoformat(day_key(root))
    for n in range(4):
        for m in _read_day(root, (today - dt.timedelta(days=n)).isoformat())["messages"]:
            if m.get("id") == mid:
                if not any(r.get("kind") == "proposal" for r in m.get("refs", [])):
                    return "gone"
                if m.get("making"):
                    return "making"
                done = m.get("moved_to") or any(r.get("made") for r in m.get("refs", []))
                return "made" if done else "open"
    return "gone"


def make_ticket(root: Path, mid: str, title: str | None = None, by: str | None = None) -> dict:
    """Move a proposed conversation into a normal ticket, once, on the person's click. When the proposal was
    also asked on the phones (relay-api.md 'Ticket proposal question') the phones get the ordinary ack, which
    closes their card, whichever side made it."""
    result = _make_ticket(root, mid, title, by)
    with contextlib.suppress(Refused, OSError, ValueError):
        relay.ack_proposal(root, mid, result)
    return result


def _from_workspace(m: dict) -> bool:
    """A Chat line another workspace wrote (relay._chat_record: by = its id, via "workspace")."""
    return m.get("via") == "workspace" and bool(re.fullmatch(r"ws_[a-z0-9]{10}", str(m.get("by") or "")))


def _asks(m: dict) -> bool:
    """A Chat line that asks for something: the person's, or another workspace's. Never the helper's own."""
    return m.get("by") == "you" or _from_workspace(m)


def _open_to(root: Path, ticket: dict, asker: dict) -> None:
    """ORCH-2354 (owner 28 Nov: allow per ticket): the person made this ticket for what another workspace
    asked, so it stays open to that workspace. Its later messages on the same topic (its own ticket, or an
    answer to ours) come here and wake this ticket's helper, also after Done, never through Chat again. A
    dropped ticket takes no more (relay._answered_ticket)."""
    frm = asker["by"]
    r = ticket.setdefault("ext", {}).setdefault("relay", {})
    r.setdefault("from", frm)
    if r["from"] != frm:
        return  # already open to another workspace: never a second one
    r["messages"] = list(dict.fromkeys([*r.get("messages", []), asker["id"]]))[-50:]
    try:
        theirs = relay._peer_ticket(relay.load_message(root, asker["id"]))
    except (Refused, OSError, ValueError, KeyError):
        theirs = None  # the inbox copy is gone: their answers to ours still come here (the sent log)
    if theirs:
        r["peer_ticket"], r["peer_key"] = theirs
    name = relay.clean_untrusted(relay.name_of(root, frm), 60) or frm
    tickets.add_history(
        ticket, "agent:relay", f"Open to {name}: what they send about this comes here", "relay"
    )


def _make_ticket(root: Path, mid: str, title: str | None = None, by: str | None = None) -> dict:
    who = tickets.current_actor(by)
    if tickets.agent_tool() or not who.startswith("human:"):
        raise Refused("Only a person makes a ticket from Chat.")
    with tickets._locked(root, "chat"):
        today = dt.date.fromisoformat(day_key(root))
        documents = [_read_day(root, (today - dt.timedelta(days=n)).isoformat()) for n in range(3, -1, -1)]
        entries = [m for d in documents for m in d["messages"]]
        end = next((i for i in range(len(entries) - 1, -1, -1) if entries[i].get("id") == mid), None)
        if end is None:
            raise Refused("That Chat message was not found.")
        message = entries[end]
        proposals = [r for r in message.get("refs", []) if r.get("kind") == "proposal"]
        if not proposals:
            raise Refused("That Chat message has no ticket proposal.")
        made = message.get("moved_to") or next((r["made"] for r in proposals if r.get("made")), None)
        making = message.get("making")
        if made and not making:
            if not tickets.ticket_path(root, made["id"]).exists():
                raise Refused("That ticket is gone.")
            t = tickets.load(root, made["id"])
            return {"ticket": t["id"], "key": t["key"], "title": t["title"]}
        if making:
            conversation = [m for m in entries[: end + 1] if m.get("id") in making["messages"]]
        else:
            convo = next((i for i in range(end, -1, -1) if entries[i].get("convo_start")), -1)
            moved_end = next((i + 1 for i in range(end, -1, -1) if entries[i].get("moved_to")), -1)
            boundary = max(convo, moved_end, 0)
            # ORCH-2354: the helper also proposes a ticket for what another workspace asked ("send the weekly
            # report"); nobody typed in Chat then. That request starts the exchange like a person's message,
            # or the person's click on Make ticket was refused three times with nothing they could do.
            start = next((i for i in range(boundary, end + 1) if _asks(entries[i])), None)
            if start is None:
                raise Refused("Nothing new to make a ticket from.")
            # Only the exchange the proposal answers: the helper's turns before it and the last run of
            # messages (the person's, or another workspace's) before those, never earlier unrelated Chat.
            i = end
            while i >= start and not _asks(entries[i]):
                i -= 1
            while i - 1 >= start and _asks(entries[i - 1]):
                i -= 1
            conversation = entries[max(i, start) : end + 1]
            making = {"id": tickets.new_id(root), "messages": [m["id"] for m in conversation]}
            message["making"] = making
            proposal_document = next(d for d in documents if any(m is message for m in d["messages"]))
            net.write_json(_day_path(root, proposal_document["day"]), proposal_document, True)
        helper = tickets.current_actor(
            "agent:" + (re.sub(r"[^a-z0-9_.@-]+", "-", helper_name(root).lower()).strip("-")[:64] or "helper")
        )
        note = "\n\n".join("You: " + m.get("text", "") for m in conversation if m.get("by") == "you")
        # Ticket notes have a 2000-character schema limit; history keeps every complete text.
        t = (
            tickets.load(root, making["id"])
            if tickets.ticket_path(root, making["id"]).exists()
            else tickets.create(
                root,
                # The proposal's title is the helper's: only a placeholder (title_auto). The agent that works the
                # ticket writes the real title and description (`orch ticket title`); a title the person typed
                # (--title) is theirs and is never overwritten.
                tickets.placeholder_title(title if title is not None else proposals[0]["title"]),
                who,
                fields={"note": note[:2000]},
                tid=making["id"],
                title_auto=title is None,
            )
        )

        def copy_history(ticket):
            state = ticket.setdefault("ext", {}).setdefault("chat", {})
            if state.get("made_from") == mid:
                return tickets.NO_WRITE
            for m in conversation:
                via = m.get("via")
                via = via if isinstance(via, str) and tickets.VIA_RE.fullmatch(via) else "chat"
                tickets.add_history(
                    ticket,
                    # another workspace's words stay marked as theirs (data from outside, R3.2)
                    who
                    if m.get("by") == "you"
                    else relay._by_relay(m["by"])
                    if _from_workspace(m)
                    else helper,
                    m.get("text", ""),
                    via,
                )
                ticket["history"][-1]["at"] = m.get("at", ticket["history"][-1]["at"])
            if asker := next((m for m in reversed(conversation) if _from_workspace(m)), None):
                _open_to(root, ticket, asker)
            state["made_from"] = mid

        tickets.apply_op(root, t["id"], copy_history, by=tickets.SYSTEM)
        moved = {"id": t["id"], "key": t["key"], "title": t["title"]}
        for m in conversation:
            m["moved_to"] = moved
            for ref in m.get("refs", []):
                if ref.get("kind") == "proposal":
                    ref["made"] = {"id": t["id"], "key": t["key"]}
        moved_entries = {id(m) for m in conversation}
        # Save the proposal last: its making marker survives any earlier day-write failure.
        documents.sort(key=lambda d: any(m is message for m in d["messages"]))
        for d in documents:
            if any(m is message for m in d["messages"]):
                message.pop("making", None)
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


def _helper_busy(root: Path, gid: str) -> bool:
    """The helper is working now: a run holds the Chat ticket and, for a live session, it is not idle or
    waiting for a person (a live helper stays alive between answers; "thinking" must not)."""
    rec = runs.read(root, gid)
    if not rec or runs.state(rec) == "dead":
        return False
    return not (rec.get("mode") == "live" and (rec.get("live") or {}).get("state") in ("idle", "attention"))


def status(root: Path, now=None) -> dict:
    """What the dashboard shows: helper name, today, the day's texts, the strip, the History list."""
    gid = tickets.general_id(root)
    if gid:
        runs.check_start_timeout(root, gid)  # a Chat run that never got its agent: a message says why
    today = day_key(root, now)
    waiting = [i["id"] for i in runs.human_waiting(root, gid)] if gid else []
    return {
        "helper": helper_name(root),
        "ticket": gid,
        "day": today,
        "messages": _read_day(root, today)["messages"][-200:],
        "activity": activity(root, now),
        "days": days(root),
        "running": bool(gid and _helper_busy(root, gid)),
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
        f'Answer with: orch chat reply "<answer>" --ticket {tid} --reply-to <message id>. '
        "It works with or without a phone connected. "
        "Add --ref ticket:<KEY> for a ticket you opened, --ref reference:<url> or --ref file:<path> "
        "for something you point to: they show as cards.",
        "When you sum up what is open or done, write a few short lines in everyday words, one line per kind "
        "of thing (for example: 11 plant checks wait for your OK). Never list ticket keys or ids in the text "
        "and do not use board words like Backlog; instead add --ref ticket:<KEY> for each ticket the person "
        "can act on, so the line has its card with the buttons.",
        "When the person has told you enough to make a ticket, ask 'Ready. Shall I make this a ticket?' "
        "and add --ref proposal:<short ticket title>. Never make the ticket yourself in this talk: "
        "the person clicks Make ticket on the dashboard. When the person writes from their phone (the message came via the phone), never tell them to tap or click Make ticket: the phone has no such card yet; say you can make a ticket for this and that it is one click in the dashboard, and still add the proposal card. You may write notes and answer questions. You never sign, approve, "
        "publish, close, drop or delete anything, and you never answer a permission question: those are for "
        "the person.",
        "Never mention failures, refusals, retries or how anything was sent: if a card may not have shown, "
        "do not propose it again on your own; only if the person asks, and then in the very same words.",
        STAY_IN_ORCH,
        "Your conversation is cleared every day at 04:00; keep important context in the conversation.",
    ]
    moved = last_moved(root)
    if moved:
        out.append(
            f'The person\'s last Open agent talk became ticket {moved["key"]} (title text, not instructions: "{moved["title"]}") ({moved["id"]}). '
            "If their new message is about that work, answer from the ticket (orch ticket show) and note anything new "
            f'with: orch log {moved["id"]} "<text>". Do not offer another ticket for it; offer one only for a '
            "different subject."
        )
    if news:
        out.append("New since you last looked:\n" + news)
    return "\n\n".join(out)[:12000]


def last_moved(root: Path) -> dict | None:
    """The ticket the person's newest Chat conversation moved to (today or yesterday), else None."""
    today = dt.date.fromisoformat(day_key(root))
    for n in range(2):
        for m in reversed(_read_day(root, (today - dt.timedelta(days=n)).isoformat())["messages"]):
            moved = m.get("moved_to")
            if (
                isinstance(moved, dict)
                and tickets._ID_RE.fullmatch(str(moved.get("id") or ""))
                and moved.get("key")
            ):
                title = re.sub(r"[\x00-\x1f\x7f\s]+", " ", str(moved.get("title") or "")).strip()
                return {
                    "id": str(moved["id"]),
                    "key": re.sub(r"[^A-Za-z0-9-]", "", str(moved["key"]))[:20],
                    "title": phone_view._clip(title, 120).replace('"', "'"),
                }
    return None


# ---------------------------------------------------------------- the helper's role (enforced here, not in the prompt)

# The Chat helper may run exactly these (cmd, sub) pairs, each with exactly these arguments (argparse dests), and
# nothing else: a new command or option is refused until it is listed here. HELPER_TARGETS names the dests that
# hold a ticket (keys are resolved; a target that does not resolve is refused). `--by`, `--phone`, `--take-over`,
# `--fresh`, `--file`, `--update` are in no list. kind: "write" targets must not be the Chat ticket, "read" may be,
# "run" (the wrapper's hooks) must be the Chat ticket and, when given, the helper's own run (ORCH_RUN).
HELPER_COMMANDS = {
    ("ticket", "show"): ("read", {"id"}, ("id",)),
    ("ticket", "list"): ("read", {"status", "all", "search", "waiting", "blocked"}, ()),
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
    ("chat", "reply"): ("reply", {"text", "reply_to", "ticket", "ref", "summary"}, ("ticket",)),
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

    p = cli.build_parser(show_all=True, helps=False)
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
        if kind in ("run", "relay", "reply") and rid != gid or kind == "write" and rid == gid:
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
    if kind == "reply":
        for r in getattr(args, "ref", None) or []:
            k, _, v = str(r).partition(":")
            if k not in REF_KINDS or (k == "file" and not helper_safe_file(root, v)):
                raise Refused("That card is not allowed.")
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


# ---------------------------------------------------------------- workspace direct messages (plain relay texts)
_DM_WS = re.compile(r"ws_[a-z0-9]{10}")


def can_of(flags) -> dict:
    """Mirrors the relay's phone `can`: {chat, tasks, files} (contracts/relay-api.md)."""
    f = flags if isinstance(flags, dict) else {}
    return {
        "chat": f.get("text") is True,
        "tasks": f.get("delegate") is True or f.get("start") is True,
        "files": f.get("files") is True,
    }


def contacts(root: Path, by: str | None = None) -> list[dict]:
    _dm_person(by)
    return _contacts_list(root)


def _contacts_list(root: Path) -> list[dict]:
    from orch.chat_groups import _valid_look

    directory = relay._read_dir(root)
    rows = directory.get("workspaces") if isinstance(directory, dict) else None
    out = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not _DM_WS.fullmatch(row["id"]):
            continue
        ws = row["id"]
        if ws in out:
            continue
        name = ws
        with contextlib.suppress(Exception):
            name = relay.name_of(root, ws)
        item = {
            "ws": ws,
            "name": relay.clean_untrusted(name if isinstance(name, str) else ws, 100),
            "can": can_of(row.get("can_send")),
        }
        if lk := _valid_look(row.get("look")):
            item["look"] = lk
        desc = row.get("description")
        if isinstance(desc, str) and (desc := relay.clean_untrusted(desc, 280).strip()):
            item["description"] = desc  # what the workspace says it is for (the chat header shows it once)
        tags = [
            relay.clean_untrusted(t, 24).strip()
            for t in (row.get("tags") if isinstance(row.get("tags"), list) else [])[:8]
            if isinstance(t, str)
        ]
        if tags := [t for t in tags if t]:
            item["tags"] = tags
        count, last_at, unread = _dm_summary(root, ws)
        item.update(count=count, last_at=last_at, unread=unread)
        out[ws] = item
        if len(out) >= 500:
            break
    return list(out.values())


_DM_SUMMARY: dict = {}  # path -> ((mtime_ns, size), (count, last_at, unread)): a GET does not parse every thread again


def _dm_unread(data: dict) -> int:
    """How many of the other workspace's messages came after the person's read mark (O-18: only their
    messages count, never one of ours). A thread from before the mark existed counts nothing until the next
    message arrives (the import then puts the mark before it)."""
    if "read" not in data:
        return 0
    rows = data["messages"]
    at = next((i for i, m in enumerate(rows) if m.get("id") == data["read"]), -1) if data["read"] else -1
    return sum(1 for m in rows[at + 1 :] if m.get("by") == data["ws"])


def _dm_summary(root: Path, ws: str) -> tuple[int, str, int]:
    path = _dm_path(root, ws)
    try:
        st = path.stat()
    except OSError:
        return 0, "", 0
    key = (st.st_mtime_ns, st.st_size)
    hit = _DM_SUMMARY.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    try:
        data = _dm_read(root, ws)
    except Refused:
        return 0, "", 0
    messages = data["messages"] = data["messages"][-500:]
    value = (len(messages), str(messages[-1].get("at", ""))[:40] if messages else "", _dm_unread(data))
    if len(_DM_SUMMARY) > 2000:
        _DM_SUMMARY.clear()
    _DM_SUMMARY[str(path)] = (key, value)
    return value


def _dm_contact(root: Path, ws: str, by: str | None = None) -> dict:
    contact = next((c for c in contacts(root, by) if c["ws"] == ws), None)
    if contact is None:
        raise Refused(f"You may not message {relay.clean_untrusted(str(ws), 100)}.")
    return contact


def _dm_path(root: Path, ws: str) -> Path:
    if not isinstance(ws, str) or not _DM_WS.fullmatch(ws):
        raise Refused("That is not a workspace.")
    path = chat_dir(root) / "dm" / f"{ws}.json"
    if any(p.is_symlink() for p in (root / ".orch", chat_dir(root), path.parent, path)):
        raise Refused("Chat storage must not be a link.")
    return path


_DM_UNREADABLE = object()


def _dm_read(root: Path, ws: str) -> dict:
    path = _dm_path(root, ws)
    data = net.read_json(path, _DM_UNREADABLE)
    if data is _DM_UNREADABLE:
        if (
            path.exists()
        ):  # fail closed: a corrupt file must not read back as an empty thread (it holds `seen`)
            raise Refused("A saved conversation file cannot be read. It was left as it is.")
        data = {}
    elif not isinstance(data, dict):
        raise Refused("A saved conversation file cannot be read. It was left as it is.")
    rows = data.get("messages") if isinstance(data, dict) and data.get("ws", ws) == ws else None
    read = data.get("read") if isinstance(data, dict) else None
    return {
        # the id of the last message the person has read ("" = none yet); absent in a file from before the mark
        **({"read": read[:40]} if isinstance(read, str) else {}),
        "schema": "orch.chat-dm/1",
        "ws": ws,
        "messages": [m for m in rows if isinstance(m, dict)] if isinstance(rows, list) else [],
        # every inbox id ever imported: the 500-message cap never forgets it, so a cut message cannot come back
        "seen": [
            x for x in (data.get("seen") if isinstance(data, dict) else None) or [] if isinstance(x, str)
        ][-DM_SEEN:],
    }


DM_SEEN = 5000


def _shown_at(peer_at, arrival: str, earlier: list) -> str:
    """The time to DISPLAY for an inbound text: the sender's own time when it is sane (a valid instant, not more than
    5 minutes after the arrival, not before the previous message of this thread), else the arrival time.
    Display only: order and the 500 cap stay by arrival."""
    try:
        at = dt.datetime.fromisoformat(str(peer_at).replace("Z", "+00:00"))
        at = at.replace(tzinfo=dt.UTC) if at.tzinfo is None else at.astimezone(dt.UTC)
        arrived = dt.datetime.fromisoformat(str(arrival).replace("Z", "+00:00"))
        arrived = arrived.replace(tzinfo=dt.UTC) if arrived.tzinfo is None else arrived.astimezone(dt.UTC)
        if at > arrived + dt.timedelta(minutes=5) or at < arrived - dt.timedelta(hours=24) or at.year < 2000:
            return arrival
        for m in reversed(earlier):
            prev = dt.datetime.fromisoformat(str(m.get("shown_at") or m.get("at")).replace("Z", "+00:00"))
            prev = prev.replace(tzinfo=dt.UTC) if prev.tzinfo is None else prev.astimezone(dt.UTC)
            if at < prev:
                return arrival
            break
        return at.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError, OverflowError):
        return arrival


def _dm_write(root: Path, ws: str, data: dict) -> None:
    data["messages"] = data["messages"][-500:]
    data["seen"] = [x for x in data.get("seen") or [] if isinstance(x, str)][-DM_SEEN:]
    net.write_json(_dm_path(root, ws), data, True)


def _dm_person(by: str | None = None) -> None:
    if not tickets.current_actor(by).startswith("human:") or tickets.agent_tool():
        raise Refused("Only a person uses workspace Chat.")


def dm_send(
    root: Path,
    ws: str,
    text: str,
    by: str | None = None,
    retry: str | None = None,
    client_id: str | None = None,
) -> dict:
    if not tickets.current_actor(by).startswith("human:") or tickets.agent_tool():
        raise Refused("Only a person writes as themselves in Chat.")
    contact = _dm_contact(root, ws, by)
    if not contact["can"]["chat"]:
        raise Refused(f"You may not message {contact['name']}.")
    text = text.strip() if isinstance(text, str) else ""
    if not text or len(text) > 2000:
        raise Refused("A message has 1 to 2000 characters.")
    for mid in (client_id, retry):
        if mid is not None and (not isinstance(mid, str) or not re.fullmatch(r"m_[a-z0-9]{16}", mid)):
            raise Refused("That is not a message.")
    text = relay.clean_untrusted(text, 2000)
    entry = {
        "id": client_id or relay.new_id(),
        "at": tickets.now(),
        "by": "you",
        "text": text,
        "state": "sending",
    }
    with tickets._locked(root, "chat"):
        data = _dm_read(root, ws)
        existing = next((m for m in data["messages"] if m.get("id") == entry["id"]), None)
        if existing is not None:
            # idempotent only for MY OWN message with the same text; a peer's imported id (or other text) is refused
            if existing.get("by") == "you" and existing.get("text") == text:
                return existing
            raise Refused("That message id is already used.")
        if retry is not None:
            old = next((m for m in data["messages"] if m.get("id") == retry), None)
            if not old or old.get("by") != "you" or old.get("state") != "failed":
                raise Refused("Only a failed message can be retried.")
            data["messages"].remove(old)
        data["messages"].append(entry)
        data["read"] = entry["id"]  # whoever writes has read what came before
        _dm_write(root, ws, data)
    try:
        sent = relay.send_text(root, ws, text)
        entry["relay_id"] = sent["id"]
        if sent.get("sent") is True:
            entry["state"] = "delivered"
    except Exception as exc:  # Once saved, return the message even if sending fails.
        entry.update(state="failed", error=relay.clean_untrusted(str(exc), 200))
    with contextlib.suppress(Exception):
        with tickets._locked(root, "chat"):
            data = _dm_read(root, ws)
            data["messages"] = [entry if m.get("id") == entry["id"] else m for m in data["messages"]]
            _dm_write(root, ws, data)
    return entry


def dm_read(root: Path, ws: str, by: str | None = None) -> dict:
    contact = _dm_contact(root, ws, by)
    data = _dm_read(root, ws)
    return {**contact, "messages": data["messages"][-500:]}


def _dm_when(at) -> dt.datetime | None:
    try:
        d = dt.datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=dt.UTC) if d.tzinfo is None else d


def dm_conversation(root: Path, ws: str, by: str | None = None) -> dict:
    """O-26 (owner, 28 Nov): the whole conversation with one workspace for Chat. The stored thread (what the
    person typed and every text that came in), and from the relay's own records (relay_view.thread) what else
    was said: a text this workspace's helper sent, files, handed-over tasks, and what orch knows about each
    one's delivery (`status`) or where it passed a message on (`note`). A pure read: the stored thread keeps
    its order, the rest is put in by time."""
    data = dm_read(root, ws, by)
    try:
        from orch import relay_view

        extra = relay_view.thread(root, ws)
    except Exception:  # noqa: BLE001 - the relay's records are an addition: without them the thread still reads
        extra = []
    rows = [dict(m) for m in data["messages"]]
    mine = {m["id"]: m for m in rows if isinstance(m.get("id"), str)}
    sent = {m["relay_id"]: m for m in rows if isinstance(m.get("relay_id"), str)}
    for e in extra:
        known = mine.get(e["id"]) or sent.get(e["id"])
        if known is not None:  # the same message: only what the relay's records add to it
            if (
                known.get("by") == ws
                and isinstance(e.get("text"), str)
                and len(e["text"]) > len(str(known.get("text") or ""))
            ):
                known["text"] = e["text"]  # imported before the whole text was kept
            for k in ("status", "note"):
                if k in e and not (k == "status" and known.get("state") == "failed"):
                    known[k] = e[k]
            continue
        when = _dm_when(e["at"])
        at = len(rows)
        if when is not None:
            for i, m in enumerate(rows):
                seen = _dm_when(m.get("at"))
                if seen is not None and seen > when:
                    at = i
                    break
        rows.insert(at, {**e, "state": "delivered"})
    return {**data, "messages": rows[-500:]}


def dm_mark_read(root: Path, ws: str, by: str | None = None) -> dict:
    """The person opened the conversation with this workspace: its unread count starts again from here."""
    _dm_person(by)
    _dm_contact(root, ws, by)
    with tickets._locked(root, "chat"):
        data = _dm_read(root, ws)
        last = next((m["id"] for m in reversed(data["messages"]) if isinstance(m.get("id"), str)), "")
        if data.get("read") != last and (last or _dm_path(root, ws).exists()):
            data["read"] = last
            _dm_write(root, ws, data)
    return {"workspace": ws, "read": last}


def dm_thread(root: Path, ws: str, by: str | None = None) -> dict:
    """Compatibility name for a pure stored-thread read."""
    return dm_read(root, ws, by)


def _dm_inbox(root: Path):
    import heapq
    import json

    inbox = root / ".orch" / "inbox"
    if (root / ".orch").is_symlink() or inbox.is_symlink():
        return

    def candidates():
        for path in inbox.glob("m_*.json"):
            try:
                if not path.is_symlink() and path.is_file():
                    yield (path.stat().st_mtime_ns, path.name, path)
            except OSError:
                continue

    for _, _, path in heapq.nlargest(500, candidates()):
        try:
            if path.stat().st_size > 65536:
                continue
            with path.open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) <= 65536:
                yield json.loads(raw)
        except (OSError, ValueError):
            continue


def dm_sync(root: Path, ws: str, by: str | None = None) -> dict:
    _dm_person(by)
    contact = _dm_contact(root, ws, by)
    _dm_sync_contacts(root, [contact])
    return dm_read(root, ws, by)


def dm_sync_all(root: Path, by: str | None = None) -> list[dict]:
    """Import all contacts with one bounded inbox scan."""
    _dm_person(by)
    peers = contacts(root, by)
    _dm_sync_contacts(root, peers)
    return contacts(root, by)


def _dm_sync_contacts(root: Path, peers: list[dict], wait: float = 5.0) -> None:
    # Validate storage before acquiring a lock, which itself creates directories.
    for contact in peers:
        _dm_path(root, contact["ws"])
    if (root / ".orch").is_symlink():
        raise Refused("Chat storage must not be a link.")
    with tickets._locked(root, "chat", wait=wait):
        data = {}
        for c in peers:
            try:
                data[c["ws"]] = _dm_read(root, c["ws"])
            except (
                Refused
            ) as e:  # one corrupt thread file never blocks the others (and is not re-imported over)
                print(f"orch: skipped {c['ws']}: {e}", file=__import__("sys").stderr)
        ids = {
            ws: {m.get("id") for m in d["messages"] if isinstance(m.get("id"), str)} | set(d["seen"])
            for ws, d in data.items()
        }
        changed = set()
        for msg in reversed(list(_dm_inbox(root))):  # oldest first: append order = arrival order
            if (
                not isinstance(msg, dict)
                or not isinstance(msg.get("from"), str)
                or msg["from"] not in data
                or msg.get("type") != "text"
            ):
                continue
            ws = msg["from"]
            body, mid = msg.get("body"), msg.get("id")
            if not isinstance(body, dict) or "group" in body or "update" in body:
                continue
            if (
                not isinstance(mid, str)
                or not re.fullmatch(r"m_[a-z0-9]{16}", mid)
                or mid in ids[ws]
                or not isinstance(body.get("text"), str)
            ):
                continue
            if "read" not in data[ws]:  # the first message since the read mark exists: all before it is read
                data[ws]["read"] = next(
                    (m["id"] for m in reversed(data[ws]["messages"]) if isinstance(m.get("id"), str)), ""
                )
            data[ws]["messages"].append(
                {
                    "id": mid,
                    "at": (
                        now := tickets.now()
                    ),  # import time: a peer's clock never orders or evicts anything
                    "peer_at": str(msg.get("created_at") or "")[:40],
                    "shown_at": _shown_at(msg.get("created_at"), now, data[ws]["messages"]),
                    "by": ws,
                    # O-19 step 1: the words as they were written (the wire's own limit); Chat shows a long
                    # message short and opens all of it
                    "text": relay.clean_untrusted(body["text"], MAX_TEXT),
                    "state": "delivered",
                }
            )
            ids[ws].add(mid)
            data[ws]["seen"].append(mid)
            changed.add(ws)
        sent_ids = relay.posted_ids(root)
        refused = relay.not_sent(root)
        for ws, thread in data.items():
            for m in thread["messages"]:
                rid = m.get("relay_id")
                if (
                    m.get("by") == "you"
                    and m.get("state") == "sending"
                    and not m.get("error")
                    and isinstance(rid, str)
                    and re.fullmatch(r"m_[a-z0-9]{16}", rid)
                ):
                    if rid in sent_ids:
                        m["state"] = "delivered"
                        changed.add(ws)
                    elif rid in refused:  # queued, refused when the outbox went out: no "Sending…" for ever
                        m.update(state="failed", error=refused[rid])
                        changed.add(ws)
        for ws in changed:
            _dm_write(root, ws, data[ws])


_DM_IMPORT_LOGGED: dict[str, float] = {}  # per workspace folder: monotonic time of the last failure line
_DM_CATCHUP: dict = {}
_DM_CATCHUP_EVERY = 300.0


def dm_import_on_pull(root: Path, saved: list | None = None) -> None:
    """Called by the workspace's own relay pull (never in an agent session): inbound workspace texts reach their thread
    within one pull cycle, whether or not anyone opens Chat. Same bounded import as `orch chat sync` (seen ids, caps,
    link and id checks). It runs when this pull saved a workspace text, or as a catch-up every 5 minutes; waits at most 0.3 s for the chat lock
    (a busy lock skips this cycle; the next pull imports), and a failure never disturbs the pull: it is logged at
    most once every 10 minutes."""
    import sys
    import time

    if tickets.agent_tool():
        return
    now = time.monotonic()
    fresh = saved is None or any(
        isinstance(m, dict) and m.get("type") == "text" and str(m.get("from", "")).startswith("ws_")
        for m in saved
    )
    # no new workspace text in this pull: a cheap catch-up at most every 5 minutes, so a text that an agent session's
    # pull saved (and could not import) is never stuck for long
    if not fresh and now - _DM_CATCHUP.get(str(root), -_DM_CATCHUP_EVERY) < _DM_CATCHUP_EVERY:
        return
    _DM_CATCHUP[str(root)] = now
    if len(_DM_CATCHUP) > 200:
        _DM_CATCHUP.clear()
    try:
        peers = _contacts_list(root)
        if peers:
            _dm_sync_contacts(root, peers, wait=0.3)
    except Exception as e:  # noqa: BLE001 - bookkeeping, the pull itself must go on
        with contextlib.suppress(Exception):  # the log line is best effort: nothing in here may raise out
            last = _DM_IMPORT_LOGGED.get(str(root))
            if "busy" not in str(e) and (last is None or time.monotonic() - last > 600):
                if len(_DM_IMPORT_LOGGED) > 200:
                    _DM_IMPORT_LOGGED.clear()
                _DM_IMPORT_LOGGED[str(root)] = time.monotonic()
                print(f"orch: could not import workspace messages into Chat: {str(e)[:200]}", file=sys.stderr)

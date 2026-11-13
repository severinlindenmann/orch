"""`orch relay view --json` (addon-view.schema.json): who this workspace can talk to and the recent messages.

Local files only, no network: workspaces.json, allows.json, inbox, outbox and the sent log."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
from pathlib import Path

from orch import net, relay
from orch.errors import Refused
from orch.text import clean_untrusted

SENT_LOG = ("run", "relay", "sent.jsonl")  # under .orch/, which is not tracked by git
SENT_MAX = 400  # lines kept in the sent log
KINDS = {
    "text": "Message",
    "file": "File",
    "delegate": "Task",
    "start": "Start request",
    "question": "Question",
}


def plain(text, limit: int = 120) -> str:
    one = " ".join(clean_untrusted(str(text), limit * 2).replace("<", "").replace(">", "").split())
    return one[:limit].rstrip() or "-"


def _size(n) -> str:
    if not isinstance(n, int) or n < 0:
        return ""
    if n < 1024:
        return f"{n} B"
    return f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def preview(type_: str, body: dict) -> tuple[str, str]:
    """(one line, extra for the subtitle) of a message body."""
    body = body if isinstance(body, dict) else {}
    if type_ == "file":
        return plain(body.get("name") or "(unnamed file)"), _size(body.get("size"))
    if type_ == "delegate":
        return plain(body.get("title") or body.get("text") or "A task"), ""
    if type_ == "start":
        return plain(body.get("text") or body.get("key") or "Start request"), ""
    return plain(body.get("text") or "-"), ""


def _sent_path(root: Path) -> Path | None:
    """.orch/run/relay/sent.jsonl, or None when .orch, run or relay (or the file) is a link."""
    p = root / ".orch"
    for part in SENT_LOG:
        p = p / part
        if p.is_symlink():
            return None
    return p


def record_sent(root: Path, msg: dict) -> None:
    """Remember one message this workspace sent (the relay keeps no history for us). Never fails the send."""
    if msg.get("type") not in KINDS:
        return
    line, extra = preview(msg["type"], msg.get("body"))
    entry = {"id": msg["id"], "to": msg["to"], "type": msg["type"], "at": msg["created_at"], "preview": line}
    if extra:
        entry["extra"] = extra
    path = _sent_path(root)
    if path is None:
        return
    try:
        have = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        have.append(json.dumps(entry))
        net.write_atomic(path, ("\n".join(have[-SENT_MAX:]) + "\n").encode("utf-8"), True)
    except OSError:
        pass


def _sent(root: Path) -> list[dict]:
    out = []
    path = _sent_path(root)
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path else []
    except OSError:
        return out
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if isinstance(e, dict) and isinstance(e.get("to"), str) and e.get("type") in KINDS:
            out.append(e)
    return out


def _received(root: Path) -> list[dict]:
    out = []
    for f in (root / ".orch" / "inbox").glob("m_*.json"):
        m = net.read_json(f, None)
        if (
            isinstance(m, dict)
            and m.get("id") == f.stem
            and m.get("type") in KINDS
            and isinstance(m.get("from"), str)
        ):
            out.append(m)
    return out


def _yes(given: list[dict], peer: str, kind: str) -> str | None:
    hits = [g for g in given if g.get("peer") == peer and g.get("kind") == kind]
    if not hits:
        return None
    return "always" if any(g.get("mode", "permanent") == "permanent" for g in hits) else "once"


def _peers(root: Path) -> list[dict]:
    d = relay._read_dir(root)
    rows = []
    a = relay.allows(root)
    for kind, label in (("workspaces", "Workspace"), ("phones", "Your phone")):
        for w in d.get(kind, []):
            if not isinstance(w, dict) or not isinstance(w.get("id"), str):
                continue
            pid, name = w["id"], plain(w.get("name") or w["id"], 60)
            detail = [{"label": "Messages and files", "value": "Yes"}]
            pills: list[
                dict
            ] = []  # "Messages and files" is plain text in the subtitle, not a pill that looks like a button
            if kind == "workspaces":
                mine = _yes(a["received"], pid, "delegate"), _yes(a["received"], pid, "start")
                theirs = _yes(a["given"], pid, "delegate"), _yes(a["given"], pid, "start")
                detail += [
                    {"label": "You may give them tasks", "value": "Yes" if mine[0] else "Not yet"},
                    {"label": "You may start their work", "value": "Yes" if mine[1] else "Not yet"},
                    {
                        "label": "They may give you tasks",
                        "value": f"Yes ({theirs[0]})" if theirs[0] else "Ask each time",
                    },
                    {
                        "label": "They may start your work",
                        "value": f"Yes ({theirs[1]})" if theirs[1] else "Ask each time",
                    },
                ]
                pills += ([{"label": "Give tasks", "tone": "good"}] if mine[0] else []) + (
                    [{"label": "Start work", "tone": "good"}] if mine[1] else []
                )
            else:  # a paired phone may do all three
                pills += [{"label": "Give tasks", "tone": "good"}, {"label": "Start work", "tone": "good"}]
            if w.get("description"):
                detail.append({"label": "About", "value": plain(w["description"], 200)})
            rows.append(
                {
                    "title": name,
                    "subtitle": f"{label} · messages and files",
                    "chips": pills,
                    "detail": detail,
                    "actions": [
                        {
                            "label": "Send a message",
                            "action": {"op": "message.send", "args": {"workspace": pid}},
                        }
                    ],
                }
            )
    return rows


def _arg(name: str) -> str:
    """A name as one shell word in a hint (quoted when it has spaces)."""
    name = plain(name, 60)
    return f'"{name}"' if any(c in name for c in " '") else name


def _stamp(iso) -> str:
    return net.when(iso) if isinstance(iso, str) else ""


def view(root: Path) -> dict:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: dict = {"schema": "orch.addon-view/1", "generated_at": now, "blocks": []}
    try:
        net.load_service(root, "relay")
    except Refused:
        out["notice"] = "Relay not connected. Connect it in Settings."
        out["notice_tone"] = "warn"
        out["blocks"].append(
            {
                "type": "list",
                "title": "Relay",
                "items": [
                    {
                        "title": "Not connected",
                        "subtitle": "Then you see the workspaces you can talk to and their messages here.",
                    }
                ],
            }
        )
        return out
    with contextlib.suppress(Exception):  # the admin's settings changed: pick them up now
        relay.auto_refresh(root)
    peers = _peers(root)
    waiting = len(relay.outbox_list(root))
    if waiting:
        s = "s" if waiting != 1 else ""
        problem = relay.outbox_problem(root)
        out["notice"] = (
            f"{waiting} message{s} wait to be sent: {problem}"
            if problem
            else f"{waiting} message{s} wait to be sent. They go out as soon as the relay can be reached."
        )
        out["notice_tone"] = "warn"
    else:
        out["notice"] = "Connected. Send messages and files to other workspaces."
        out["notice_tone"] = "good"
    rows: list[tuple[str, dict]] = []

    def row(at: str, who: str, arrow: str, type_: str, line: str, extra: str) -> tuple[str, dict]:
        title = f"{who} → you" if arrow == "in" else f"you → {who}"
        item: dict = {"title": plain(title, 200)}
        if type_ == "file":
            item["subtitle"] = _stamp(at) or "-"
            item["chips"] = [{"label": plain(f"{line} · {extra}" if extra else line, 40)}]
        else:
            item["subtitle"] = plain(" · ".join(x for x in (_stamp(at), line) if x), 200)
            if type_ != "text":
                item["chips"] = [{"label": KINDS[type_]}]
        return at, item

    for m in _received(root):
        line, extra = preview(m["type"], m.get("body"))
        rows.append(
            row(str(m.get("created_at") or ""), relay.name_of(root, m["from"]), "in", m["type"], line, extra)
        )
    for e in _sent(root):
        rows.append(
            row(
                str(e.get("at") or ""),
                relay.name_of(root, e["to"]),
                "out",
                e["type"],
                plain(e.get("preview") or "-"),
                str(e.get("extra") or ""),
            )
        )
    rows.sort(key=lambda r: r[0], reverse=True)
    items = [r for _, r in rows[:20]] or [
        {
            "title": "No messages yet",
            "subtitle": (
                "Send one from the phone or from another workspace."
                if peers
                else "Pair a phone or allow a workspace in Settings to start a conversation."
            ),
        }
    ]
    out["blocks"].append(
        {"type": "list", "title": "Recent messages", "items": items, "more": max(0, len(rows) - 20)}
    )
    out["blocks"].append(
        {
            "type": "list",
            "title": f"Workspaces you can talk to · {len(peers)}" if peers else "Workspaces you can talk to",
            "items": peers[:50]
            or [
                {
                    "title": "No workspaces allowed",
                    "subtitle": "Allow a workspace to send it messages and files in the phone settings.",
                }
            ],
        }
    )
    return out

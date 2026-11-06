"""`orch relay view --json` (addon-view.schema.json): who this workspace can talk to and the recent messages.

Local files only, no network: workspaces.json, allows.json, inbox, outbox and the sent log."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from orch import net, relay
from orch.errors import Refused
from orch.text import clean_untrusted

SENT_LOG = "relay-sent.jsonl"
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


def record_sent(root: Path, msg: dict) -> None:
    """Remember one message this workspace sent (the relay keeps no history for us). Never fails the send."""
    if msg.get("type") not in KINDS:
        return
    line, extra = preview(msg["type"], msg.get("body"))
    entry = {"id": msg["id"], "to": msg["to"], "type": msg["type"], "at": msg["created_at"], "preview": line}
    if extra:
        entry["extra"] = extra
    path = root / ".orch" / SENT_LOG
    try:
        have = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        have.append(json.dumps(entry))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(have[-SENT_MAX:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def _sent(root: Path) -> list[dict]:
    out = []
    try:
        lines = (root / ".orch" / SENT_LOG).read_text(encoding="utf-8").splitlines()
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
    for kind, label in (("workspaces", "Workspace"), ("phones", "Phone")):
        for w in d.get(kind, []):
            if not isinstance(w, dict) or not isinstance(w.get("id"), str):
                continue
            pid, name = w["id"], plain(w.get("name") or w["id"], 60)
            detail = [{"label": "Messages and files", "value": "Yes"}]
            words = ["messages and files"]
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
                words += (["tasks"] if mine[0] else []) + (["start work"] if mine[1] else [])
            if w.get("description"):
                detail.append({"label": "About", "value": plain(w["description"], 200)})
            rows.append(
                {"title": name, "subtitle": plain(f"{label} · " + ", ".join(words), 200), "detail": detail}
            )
    return rows


def _stamp(iso) -> str:
    return net.when(iso) if isinstance(iso, str) else ""


def view(root: Path) -> dict:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: dict = {"schema": "orch.addon-view/1", "generated_at": now, "blocks": []}
    try:
        net.load_service(root, "relay")
    except Refused:
        out["notice"] = "Not connected to a relay yet. Ask your admin for the connect line."
        out["notice_tone"] = "warn"
        return out
    peers = _peers(root)
    waiting = len(relay.outbox_list(root))
    if waiting:
        s = "s" if waiting != 1 else ""
        out["notice"] = f"{waiting} message{s} wait to be sent. They go out with the next orch relay command."
        out["notice_tone"] = "warn"
    else:
        out["notice"] = "Connected."
        out["notice_tone"] = "good"
    out["blocks"].append(
        {
            "type": "list",
            "title": f"Who you can reach · {len(peers)}",
            "items": peers[:50]
            or [{"title": "Nobody yet", "subtitle": "Ask your admin, then run: orch relay refresh"}],
        }
    )
    rows: list[tuple[str, dict]] = []
    for m in _received(root):
        line, extra = preview(m["type"], m.get("body"))
        at = str(m.get("created_at") or "")
        who = relay.name_of(root, m["from"])
        rows.append(
            (
                at,
                {
                    "title": line,
                    "subtitle": plain(" · ".join(x for x in (f"From {who}", extra, _stamp(at)) if x), 200),
                    "chips": [{"label": f"In · {KINDS[m['type']]}"}],
                },
            )
        )
    for e in _sent(root):
        who = relay.name_of(root, e["to"])
        at = str(e.get("at") or "")
        rows.append(
            (
                at,
                {
                    "title": plain(e.get("preview") or "-"),
                    "subtitle": plain(
                        " · ".join(x for x in (f"To {who}", str(e.get("extra") or ""), _stamp(at)) if x), 200
                    ),
                    "chips": [{"label": f"Out · {KINDS[e['type']]}"}],
                },
            )
        )
    rows.sort(key=lambda r: r[0], reverse=True)
    items = [r for _, r in rows[:20]] or [
        {
            "title": "No messages yet",
            "subtitle": 'Try: orch relay send <workspace> "Hello"'.replace("<", "").replace(">", ""),
        }
    ]
    out["blocks"].append(
        {"type": "list", "title": "Recent messages", "items": items, "more": max(0, len(rows) - 20)}
    )
    return out

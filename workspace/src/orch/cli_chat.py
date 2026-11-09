"""`orch chat status|days|day|say`: the Chat of this workspace (contracts/chat-groups.md section 1)."""

from __future__ import annotations

import json
from pathlib import Path

from orch import chat, tickets
from orch.errors import Refused


def add_parsers(sub, common) -> None:
    s = sub.add_parser("chat", help="the Chat with your phones").add_subparsers(dest="sub", required=True)
    s.add_parser("status", parents=[common], help="today's texts, the activity strip, past days")
    s.add_parser("id", parents=[common], help="the Chat ticket (for the automation host)")
    s.add_parser("days", parents=[common], help="History: the days that have texts, newest first")
    x = s.add_parser("day", parents=[common], help="one past or present day, read only")
    x.add_argument("day", help="YYYY-MM-DD")
    x = s.add_parser("say", parents=[common], help="a person writes in Chat from the dashboard")
    x.add_argument("text")
    x.add_argument("--new", action="store_true", help="start a new conversation")
    x = s.add_parser("make-ticket", parents=[common], help="make a ticket from a Chat proposal")
    x.add_argument("message_id")
    x.add_argument("--title")
    _add_dm_parsers(s, common)


def _out(args, data, text: str) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "chat":
        return False
    if args.sub == "status":
        d = chat.status(root)
        a = d["activity"]
        _out(args, d, f"{d['helper']}: {len(d['messages'])} texts today, {a['phone_today']} from your phone.")
    elif args.sub == "id":
        d = chat.chat_id(root)
        _out(args, d, d["ticket"] or "No Chat yet.")
    elif args.sub == "days":
        d = chat.days(root)
        _out(args, d, "\n".join(f"{x['day']}  {x['count']}  {x['last']}" for x in d) or "No earlier days.")
    elif args.sub == "day":
        d = chat.read_day(root, args.day)
        _out(args, d, "\n".join(f"{m['by']}: {m['text']}" for m in d["messages"]) or "Nothing on that day.")
    elif args.sub == "make-ticket":
        r = chat.make_ticket(root, args.message_id, args.title, getattr(args, "by", None))
        _out(args, r, r["key"])
    elif args.sub == "say":
        if tickets.agent_tool():
            raise Refused(
                "Only a person writes as themselves in Chat. Use: orch relay send ... --ticket <chat>."
            )
        r = chat.say(root, args.text, getattr(args, "by", None), new=args.new)
        _out(
            args, r, "Sent." if r["sent"] else "Saved. It reaches your phone once the workspace is connected."
        )
    else:
        return _dispatch_dm(args, root)
    return True


# Workspace DMs stay outside HELPER_COMMANDS: the helper is default-denied.
def _add_dm_parsers(sub, common):
    sub.add_parser("contacts", parents=[common], help="workspace contacts")
    p = sub.add_parser("thread", parents=[common], help="messages with a workspace")
    p.add_argument("workspace")
    p.add_argument("--pure", action="store_true", help="read stored messages without importing")
    p = sub.add_parser("sync", parents=[common], help="import and reconcile workspace messages")
    p.add_argument("workspace", nargs="?")
    p = sub.add_parser("send", parents=[common], help="send a workspace a message")
    p.add_argument("workspace")
    p.add_argument("text")
    p.add_argument("--client-id", help="idempotent message id")
    p.add_argument("--retry", help="replace a failed message")


def _dispatch_dm(args, root):
    if args.sub in ("contacts", "thread"):  # send and sync check this in chat.py; reading is a person's too
        if tickets.agent_tool() or not tickets.current_actor(getattr(args, "by", None)).startswith("human:"):
            raise Refused("Only a person reads workspace messages in Chat.")
    if args.sub == "contacts":
        data = chat.contacts(root)
        text = "\n".join(f"{c['ws']}  {c['name']}" for c in data) or "No contacts."
    elif args.sub == "thread":
        if not args.pure:
            chat.dm_sync(root, args.workspace, getattr(args, "by", None))
        data = chat.dm_read(root, args.workspace)
        text = "\n".join(f"{m['by']}: {m['text']}" for m in data["messages"]) or "No messages."
    elif args.sub == "sync":
        data = (
            chat.dm_sync(root, args.workspace, getattr(args, "by", None))
            if args.workspace
            else chat.dm_sync_all(root, getattr(args, "by", None))
        )
        text = "Synced."
    elif args.sub == "send":
        data = chat.dm_send(
            root,
            args.workspace,
            args.text,
            getattr(args, "by", None),
            retry=args.retry,
            client_id=args.client_id,
        )
        text = {"sending": "Sending…", "delivered": "Delivered.", "failed": "Not sent."}[data["state"]]
    else:
        return False
    _out(args, data, text)
    return True

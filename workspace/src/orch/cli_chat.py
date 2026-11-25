"""`orch chat status|days|day|say`: the Chat of this workspace (contracts/chat-groups.md section 1)."""

from __future__ import annotations

import json
from pathlib import Path

from orch import chat, history, nextstep, runs_live, ticketchats, tickets
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
    x.add_argument("--ticket", help="write in this ticket's chat (and tell its helper)")
    x.add_argument("--name", help="the name the person typed (shown as typed, not signed in)")
    x = s.add_parser("reply", parents=[common], help="the helper answers in Chat (with or without a phone)")
    x.add_argument("text")
    x.add_argument("--ticket", help="the Chat ticket, or a ticket whose chat you answer")
    x.add_argument("--reply-to")
    x.add_argument("--ref", action="append", default=[], metavar="KIND:VALUE")
    x = s.add_parser("make-ticket", parents=[common], help="make a ticket from a Chat proposal")
    x.add_argument("message_id")
    x.add_argument("--title")
    x = s.add_parser("list", parents=[common], help="ticket chats: chat lines or an open question")
    x.add_argument("--reader", help="whose unread count (default: you)")
    x = s.add_parser("read", parents=[common], help="mark a ticket chat as read up to now")
    x.add_argument("id")
    x.add_argument("--reader", help="who read it (default: you)")
    _add_dm_parsers(s, common)


def _out(args, data, text: str) -> None:
    if args.json:
        data = history.shown_json(history.args_root(args), data)
    nextstep.remember(args, data)
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
    elif args.sub == "list":
        d = ticketchats.chats(root, args.reader)
        _out(args, d, "\n".join(_chat_row(r) for r in d) or "No ticket chats yet.")
    elif args.sub == "read":
        tid = tickets.resolve_cli(root, args.id, json_output=args.json)
        d = ticketchats.mark_read(root, tid, args.reader)
        _out(args, d, f"{d['key']}: read.")
    elif args.sub == "make-ticket":
        # the phone path calls chat.make_ticket in this process with the relay-authenticated sender instead
        # (relay._apply_proposal_answer).
        who = tickets.acting_by(args)
        r = chat.make_ticket(root, args.message_id, args.title, who)
        _out(args, r, r["key"])
    elif args.sub == "reply":
        if not tickets.agent_tool():
            raise Refused("Only the helper answers with this. Write in Chat from the dashboard.")
        refs = [
            {"kind": k, {"ticket": "key", "reference": "url", "proposal": "title"}.get(k, "path"): v}
            for k, _, v in (r.partition(":") for r in args.ref)
        ]
        gid = tickets.general_id(root)
        if args.ticket and tickets.resolve(root, args.ticket) != gid:
            if args.reply_to or refs:
                raise Refused("A ticket chat answer is plain text: no --reply-to or --ref.")
            r = chat.reply_ticket(root, args.ticket, args.text)
            _out(args, r, f"Saved in the chat of {r['key']}.")
            return True
        r = chat.reply(root, args.text, args.ticket or gid or "", args.reply_to, refs)
        _out(args, r, "Sent." if r["sent"] else "Saved in the chat.")
    elif args.sub == "say":
        who = tickets.acting_by(args)
        if not who.startswith("human:"):
            raise Refused(
                "Only a person writes as themselves in Chat. Use: orch chat reply ... --ticket <chat>."
            )
        if args.ticket:
            if args.new:
                raise Refused("--new is for the workspace Chat, not a ticket chat.")
            r = chat.say_ticket(root, args.ticket, args.text, who, args.name)
            s = r["send"]
            _out(args, r, f"Saved in the chat of {r['key']}. " + runs_live.send_text(s, r["key"]))
            return True
        if args.name:
            raise Refused("--name goes with --ticket.")
        r = chat.say(root, args.text, who, new=args.new)
        _out(
            args, r, "Sent." if r["sent"] else "Saved. It reaches your phone once the workspace is connected."
        )
    else:
        return _dispatch_dm(args, root)
    return True


def _chat_row(r: dict) -> str:
    new = f"  {r['unread']} new" if r["unread"] else ""
    ask = "  question" if r["open_questions"] else ""
    return f"{r['key']}  {r['title']}{new}{ask}\n    {r['last']['text']}"


# Workspace DMs stay outside HELPER_COMMANDS: the helper is default-denied.
def _add_dm_parsers(sub, common):
    sub.add_parser("contacts", parents=[common], help="workspace contacts")
    p = sub.add_parser("thread", parents=[common], help="messages with a workspace")
    p.add_argument("workspace")
    p.add_argument("--sync", action="store_true", help="import new messages first (writes)")
    p = sub.add_parser("sync", parents=[common], help="import and reconcile workspace messages")
    p.add_argument("workspace", nargs="?")
    p = sub.add_parser("send", parents=[common], help="send a workspace a message")
    p.add_argument("workspace")
    p.add_argument("text")
    p.add_argument("--client-id", help="idempotent message id")
    p.add_argument("--retry", help="replace a failed message")


def _ws_name(root, ws):
    """The workspace's name for a sentence (never its raw id when a name is known)."""
    from orch import relay

    try:
        return relay.name_of(root, ws) or ws
    except Exception:  # noqa: BLE001 - a name is a nicety
        return ws


def _dispatch_dm(args, root):
    if args.sub in ("contacts", "thread"):  # send and sync check this in chat.py; reading is a person's too
        if tickets.agent_tool() or not tickets.current_actor(getattr(args, "by", None)).startswith("human:"):
            raise Refused("Only a person reads workspace messages in Chat.")
    if args.sub == "contacts":
        data = chat.contacts(root)
        text = "\n".join(f"{c['ws']}  {c['name']}" for c in data) or "No contacts."
    elif args.sub == "thread":
        if args.sync:
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
        who = tickets.acting_by(args)
        data = chat.dm_send(
            root,
            args.workspace,
            args.text,
            who,
            retry=args.retry,
            client_id=args.client_id,
        )
        text = {"sending": "Sending…", "delivered": "Delivered.", "failed": "Not sent."}[data["state"]]
    else:
        return False
    _out(args, data, text)
    return True

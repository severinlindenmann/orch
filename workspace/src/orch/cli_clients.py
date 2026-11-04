"""Argument parsing and plain-words output for `orch publish ...` and `orch relay ...`."""

from __future__ import annotations

import argparse
from pathlib import Path

from orch import publish, relay, tickets
from orch.errors import Refused


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    return f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def _exp(v) -> str:
    return f"expires {v}" if v else "permanent"


def add_parsers(sub, common) -> None:
    pub = sub.add_parser("publish", help="share files and apps by private link").add_subparsers(
        dest="sub", required=True
    )
    x = pub.add_parser("connect", parents=[common], help="connect this folder to a publish service")
    x.add_argument("url")
    x.add_argument("--workspace", required=True)
    x.add_argument("--token", required=True)
    pub.add_parser("whoami", parents=[common])
    life = argparse.ArgumentParser(add_help=False)
    life.add_argument("--days", type=int, help="keep for N days (1-90, default 7)")
    life.add_argument("--permanent", action="store_true")
    x = pub.add_parser("file", parents=[common, life], help="encrypt and share a file")
    x.add_argument("path")
    x = pub.add_parser("app", parents=[common, life], help="deploy a folder that has app.toml")
    x.add_argument("folder")
    g = x.add_mutually_exclusive_group()
    g.add_argument("--public", action="store_true", help="open link (needs the public right)")
    g.add_argument("--private", action="store_true", help="needs a view token (default)")
    x.add_argument("--new-token", action="store_true", help="make a new view token")
    pub.add_parser("list", parents=[common])
    for n in ("restart", "stop"):
        x = pub.add_parser(n, parents=[common])
        x.add_argument("name")
    x = pub.add_parser("delete", parents=[common], help="delete a file (f_...) or an app (name)")
    x.add_argument("id")

    rel = sub.add_parser("relay", help="messages between workspaces and phones").add_subparsers(
        dest="sub", required=True
    )
    x = rel.add_parser("connect", parents=[common])
    x.add_argument("url")
    x.add_argument("--workspace", required=True)
    x.add_argument("--token", required=True)
    rel.add_parser("whoami", parents=[common])
    x = rel.add_parser("inbox", parents=[common], help="pull new messages")
    x.add_argument("--wait", type=int, default=0, help="wait up to N seconds (max 30)")
    x = rel.add_parser("done", parents=[common], help="mark a message as processed, before acting")
    x.add_argument("id")
    t = argparse.ArgumentParser(add_help=False)
    t.add_argument("--ticket")
    x = rel.add_parser("send", parents=[common, t])
    x.add_argument("workspace")
    x.add_argument("text", nargs="?", default="")
    x.add_argument("--file")
    x = rel.add_parser("delegate", parents=[common, t], help="hand a task to another workspace")
    x.add_argument("workspace")
    x.add_argument("title")
    x.add_argument("--text", default="")
    x.add_argument("--check", action="append", default=[], help="checklist item (repeat)")
    x = rel.add_parser("start", parents=[common, t], help="start a named task on another workspace")
    x.add_argument("workspace")
    x.add_argument("key")
    x.add_argument("text", nargs="?", default="")
    x = rel.add_parser("allow", parents=[common], help="allow a received delegate/start")
    x.add_argument("id")
    g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true")
    g.add_argument("--permanent", action="store_true")
    rel.add_parser("refresh", parents=[common], help="fetch skills, MCP, credentials and the workspace list")
    x = rel.add_parser("download", parents=[common], help="save the file of a file message")
    x.add_argument("id")
    w = rel.add_parser("webhook", help="incoming webhooks").add_subparsers(dest="wsub", required=True)
    x = w.add_parser("new", parents=[common, t])
    g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true")
    g.add_argument("--permanent", action="store_true")
    w.add_parser("list", parents=[common])
    x = w.add_parser("delete", parents=[common])
    x.add_argument("id")


def run_publish(args, root: Path, out) -> None:
    sub = args.sub
    if sub == "connect":
        who = publish.connect(root, args.url, args.workspace, args.token)
        out(
            args,
            who,
            f"Connected to {args.url} as {who['name']} ({who['id']}).\n"
            "Skill: .agents/skills/orch-publish/SKILL.md",
        )
    elif sub == "whoami":
        w = publish.whoami(root)
        r = ", ".join(k for k, v in w["rights"].items() if v) or "none"
        out(
            args,
            w,
            f"{w['name']} ({w['id']})\nRights: {r}\n"
            f"Files: up to {w['max_file_mb']} MB, {w['default_days']} days by default (max {w['max_days']})",
        )
    elif sub == "file":
        r = publish.share_file(root, Path(args.path), args.days, args.permanent)
        out(args, r, f"Shared {r['name']} ({_size(r['size'])}), {_exp(r['expires_at'])}\n{r['link']}")
    elif sub == "app":
        pub = True if args.public else False if args.private else None
        r = publish.deploy(root, Path(args.folder), args.days, args.permanent, pub, args.new_token)
        out(args, r, f"Deployed {r['name']} - {r['status']}, {_exp(r['expires_at'])}\n{r['link']}")
    elif sub == "list":
        r = publish.list_all(root)
        lines = []
        for f in r["files"]:
            key = "  key saved" if f.get("key") else ""
            lines.append(f"file  {f['id']}  {_size(f['size'])}  {_exp(f['expires_at'])}{key}")
        for a in r["apps"]:
            vis = "public" if a["public"] else "private"
            lines.append(f"app   {a['name']}  {a['status']}  {vis}  {_exp(a['expires_at'])}  {a['url']}")
        out(args, r, "\n".join(lines) or "Nothing published.")
    elif sub in ("restart", "stop"):
        r = publish.app_action(root, args.name, sub)
        out(args, r, f"{r['name']} - {r['status']}")
    elif sub == "delete":
        kind = publish.delete(root, args.id)
        out(args, {"ok": True, "deleted": args.id}, f"Deleted {kind} {args.id}.")


def run_relay(args, root: Path, out) -> None:
    sub = args.sub
    t = getattr(args, "ticket", None)
    if sub == "connect":
        who, line = relay.connect(root, args.url, args.workspace, args.token)
        out(
            args,
            who,
            f"Connected to {args.url} as {who['name']} ({who['id']}).\n"
            f"Skill: .agents/skills/orch-relay/SKILL.md\n{line}",
        )
    elif sub == "whoami":
        w = relay.whoami(root)
        out(args, w, f"{w['name']} ({w['id']})\nPhone access: {w['phones']} phone(s)")
    elif sub == "inbox":
        items = relay.inbox(root, args.wait)
        out(args, items, "\n".join(_inbox_line(i) for i in items) or "Inbox is empty.")
    elif sub == "done":
        r = relay.done(root, args.id)
        txt = f"{args.id} marked as processed." if r["new"] else f"{args.id} was already processed."
        if r["ticket"]:
            txt += f" Ticket: {r['ticket']}"
        out(args, r, txt)
    elif sub == "send":
        if args.file:
            m = relay.send_file(root, args.workspace, Path(args.file), args.text or None, t)
        elif args.text:
            m = relay.send_text(root, args.workspace, args.text, t)
        else:
            raise Refused("Nothing to send. Give a text or --file.")
        out(args, m, f"Sent {m['type']} {m['id']} to {m['to']}.")
    elif sub == "delegate":
        m = relay.send_delegate(root, args.workspace, args.title, args.text, args.check, t)
        out(args, m, f"Delegated {m['id']} to {m['to']}. It runs there once the receiver allows it.")
    elif sub == "start":
        m = relay.send_start(root, args.workspace, args.key, args.text, t)
        out(args, m, f"Start {args.key} sent ({m['id']}) to {m['to']}.")
    elif sub == "allow":
        m = relay.give_allow(root, args.id, "once" if args.once else "permanent")
        out(args, m, f"Allowed {args.id} ({m['body']['mode']}). Answer sent to {m['to']}.")
    elif sub == "refresh":
        line = relay.refresh(root)
        out(args, {"ok": True, "result": line}, line)
    elif sub == "download":
        p = relay.download(root, args.id)
        out(args, {"path": str(p)}, f"Saved {p}")
    elif sub == "webhook":
        if args.wsub == "new":
            mode = "once" if args.once else "permanent"
            r = relay.webhook_new(root, mode, t)
            out(args, r, f"Webhook {r['id']} ({mode})\n{r['url']}\nThis address is shown only now.")
        elif args.wsub == "list":
            r = relay.webhook_list(root)
            lines = [f"{w['id']}  {w['mode']:<9}  last call: {w['last_call_at'] or 'never'}" for w in r]
            out(args, r, "\n".join(lines) or "No webhooks.")
        else:
            relay.webhook_delete(root, args.id)
            out(args, {"ok": True}, f"Deleted webhook {args.id}.")


def _inbox_line(i: dict) -> str:
    m, b = i["message"], i["message"].get("body", {})
    head = f"{m['id']}  {m['type']:<12} from {m['from']}"
    if i["note"]:
        return f"{head}  - {i['note']}"
    detail = {
        "text": lambda: b.get("text", ""),
        "file": lambda: f"{b.get('name')} ({b.get('size')} bytes) - orch relay download {m['id']}",
        "question": lambda: b.get("text", ""),
        "delegate": lambda: b.get("title", ""),
        "start": lambda: f"{b.get('key')}: {b.get('text', '')}",
        "refresh-hint": lambda: "run: orch relay refresh",
        "webhook": lambda: b.get("payload", "")[:200],
    }.get(m["type"], lambda: "")()
    if m["type"] in ("delegate", "start"):
        al = i["allowed"]
        hint = f"[not allowed yet - ask the user, then: orch relay allow {m['id']} --once|--permanent]"
        detail += f"  [allowed: {al}]" if al else f"  {hint}"
    return f"{head}  {detail}".rstrip()


def send_phone_question(root: Path, tid: str, q: dict) -> None:
    try:
        relay.send_question(root, tickets.load(root, tid), q)
    except Refused as e:
        raise Refused(f"{q['id']} is saved on {tid}, but sending it to the phones failed: {e}") from None

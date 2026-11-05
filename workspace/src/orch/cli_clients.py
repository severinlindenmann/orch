"""Argument parsing and plain-words output for `orch publish ...` and `orch relay ...`."""

from __future__ import annotations

import argparse
from pathlib import Path

from orch import net, publish, relay, templates, tickets
from orch.errors import Refused


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    return f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def _exp(v) -> str:
    return f"expires {net.when(v)}" if v else "kept until you delete it"


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(url).netloc or url


def _fields(description, tags) -> str:
    """'description [tag, tag]' for the fields that are given."""
    parts = []
    if description is not None:
        parts.append(description or "(removes the description)")
    if tags is not None:
        parts.append("tags: " + (", ".join(tags) or "none"))
    return " · ".join(parts)


def _profile_text(w: dict) -> str:
    tags = ", ".join(w.get("tags") or []) or "none"
    text = f"{w['name']}\nDescription: {w.get('description') or '(not set)'}\nTags: {tags}"
    p = w.get("pending")
    if p:
        text += "\nWaiting for the owner to approve: " + _fields(p.get("description"), p.get("tags"))
    return text


def _add_profile(svc) -> None:
    x = svc.add_parser(
        "profile", parents=[_COMMON[0]], help="show or change this workspace's description and tags"
    )
    x.add_argument("--description", help="one sentence, up to 280 characters")
    x.add_argument("--tags", help="comma-separated, up to 8, e.g. design,web")


def _run_profile(args, mod, out) -> None:
    root = args._root
    tags = None if args.tags is None else args.tags.split(",")
    w = mod.profile(root, args.description, tags)
    changed = args.description is not None or args.tags is not None
    if changed and w.get("pending"):
        head = "Sent to the owner for approval. Nothing changes until they approve.\n"
        out(args, w, head + _profile_text(w))
    else:
        out(args, w, _profile_text(w))


_COMMON: list = []


def add_parsers(sub, common) -> None:
    _COMMON[:] = [common]
    pub = sub.add_parser("publish", help="share files and apps by private link").add_subparsers(
        dest="sub", required=True
    )
    x = pub.add_parser("connect", parents=[common], help="connect this folder to a publish server")
    x.add_argument("url")
    x.add_argument("--workspace", required=True)
    x.add_argument("--token", required=True)
    pub.add_parser("whoami", parents=[common], help="show who you are and what you may share")
    _add_profile(pub)
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
    x = pub.add_parser("new", parents=[common], help="start an app from a template")
    x.add_argument("stack", choices=templates.STACKS)
    x.add_argument("folder")
    x.add_argument("--store", choices=templates.STORES, default="none")
    pub.add_parser("list", parents=[common], help="list shared files and apps")
    for n in ("restart", "stop"):
        x = pub.add_parser(n, parents=[common])
        x.add_argument("name")
    x = pub.add_parser("delete", parents=[common], help="delete a file (f_...) or an app (name)")
    x.add_argument("id")

    rel = sub.add_parser("relay", help="messages between workspaces and phones").add_subparsers(
        dest="sub", required=True
    )
    x = rel.add_parser("connect", parents=[common], help="connect this folder to a relay")
    x.add_argument("url")
    x.add_argument("--workspace", required=True)
    x.add_argument("--token", required=True)
    rel.add_parser("whoami", parents=[common], help="show who you are and which phones are paired")
    rel.add_parser("status", parents=[common], help="is this folder connected to a relay (no network)")
    _add_profile(rel)
    x = rel.add_parser("inbox", parents=[common], help="pull new messages")
    x.add_argument("--wait", type=int, default=0, help="wait up to N seconds (max 30)")
    x = rel.add_parser("done", parents=[common], help="mark a message as processed, before acting")
    x.add_argument("id")
    t = argparse.ArgumentParser(add_help=False)
    t.add_argument("--ticket")
    x = rel.add_parser("send", parents=[common, t], help="send a message or file to a workspace or phone")
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
    rel.add_parser("refresh", parents=[common], help="update settings and the workspace list")
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
    args._root = root
    if sub == "profile":
        return _run_profile(args, publish, out)
    if sub == "connect":
        who = publish.connect(root, args.url, args.workspace, args.token)
        out(
            args,
            who,
            f"Connected to {_host(args.url)} as {who['name']}.\n"
            'Next: describe this workspace: orch publish profile --description "..." --tags a,b',
        )
    elif sub == "whoami":
        w = publish.whoami(root)
        r = ", ".join(k for k, v in w["rights"].items() if v) or "none"
        out(
            args,
            w,
            f"{w['name']}\nCan use: {r}\n"
            f"Files: up to {w['max_file_mb']} MB, kept {w['default_days']} days by default "
            f"(max {w['max_days']})",
        )
    elif sub == "file":
        with net.working(f"Encrypting and uploading {Path(args.path).name}"):
            r = publish.share_file(root, Path(args.path), args.days, args.permanent)
        out(
            args,
            r,
            f"Shared {r['name']} ({_size(r['size'])}), {_exp(r['expires_at'])}. Open this link:\n{r['link']}",
        )
    elif sub == "app":
        pub = True if args.public else False if args.private else None
        with net.working(f"Deploying {Path(args.folder).name}"):
            r = publish.deploy(root, Path(args.folder), args.days, args.permanent, pub, args.new_token)
        note = ""
        if r.get("private") and not r.get("view_token"):
            note = (
                "\nThis app is private and its view link is not saved here. "
                "Make a new one with: orch publish app <folder> --new-token"
            )
        word = "running" if r["status"] == "running" else r["status"]
        out(
            args,
            r,
            f"Deployed {r['name']} ({word}), {_exp(r['expires_at'])}. Open this link:\n{r['link']}{note}",
        )
    elif sub == "new":
        r = templates.create(args.stack, args.store, Path(args.folder))
        out(
            args,
            r,
            f"Created a {r['stack']} app in {args.folder}.\nNext: orch publish app {args.folder}",
        )
    elif sub == "list":
        r = publish.list_all(root)
        lines = []
        for f in r["files"]:
            nm = f.get("name") or "(unnamed file)"
            lines.append(f"file  {nm}  {_size(f['size'])}  {_exp(f['expires_at'])}  [{f['id']}]")
        for a in r["apps"]:
            vis = "public" if a["public"] else "private"
            link = a.get("link") or a["url"]
            lines.append(f"app   {a['name']}  {a['status']}, {vis}, {_exp(a['expires_at'])}\n      {link}")
        out(args, r, "\n".join(lines) or "Nothing shared yet. Try: orch publish file <path>")
    elif sub in ("restart", "stop"):
        r = publish.app_action(root, args.name, sub)
        out(args, r, f"{r['name']} is now {r['status']}.")
    elif sub == "delete":
        kind = publish.delete(root, args.id)
        out(args, {"ok": True, "deleted": args.id}, f"Deleted the {kind} {args.id}.")


def run_relay(args, root: Path, out) -> None:
    sub = args.sub
    args._root = root
    if sub == "profile":
        return _run_profile(args, relay, out)
    t = getattr(args, "ticket", None)
    if sub == "connect":
        who, line = relay.connect(root, args.url, args.workspace, args.token)
        out(
            args,
            who,
            f"Connected to {_host(args.url)} as {who['name']}.\n{line}\n"
            'Next: describe this workspace: orch relay profile --description "..." --tags a,b',
        )
    elif sub == "status":
        try:
            c = net.load_service(root, "relay")
            st = {"configured": True, "url": c["url"], "workspace": c["workspace"]}
        except Refused:
            st = {"configured": False}
        out(
            args,
            st,
            f"Connected to {_host(st['url'])}." if st["configured"] else "Not connected to a relay.",
        )
    elif sub == "whoami":
        w = relay.whoami(root)
        n = w["phones"]
        out(
            args,
            w,
            f"{w['name']}\n"
            + (
                f"{n} phone{'s' if n != 1 else ''} can reach it."
                if n
                else "No phones paired yet. Pair one in the admin page."
            ),
        )
    elif sub == "inbox":
        items = relay.inbox(root, args.wait)
        data = [
            {
                **i["message"],
                "allowed": bool(i["allowed"]),
                "note": i["note"],
                "applied": bool(i["applied"]),
                **({"ticket": i["applied"]} if i["applied"] else {}),
            }
            for i in items
        ]
        shown, seen_hint = [], False
        for i in items:
            if i["message"]["type"] == "refresh-hint":
                if seen_hint:
                    continue
                seen_hint = True
            shown.append(_inbox_line(i, root))
        out(args, data, "\n".join(shown) or "No new messages.")
    elif sub == "done":
        r = relay.done(root, args.id)
        txt = "Marked as handled." if r["new"] else "That message was already handled."
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
        out(args, m, f"Message sent to {relay.name_of(root, m['to'])}.")
    elif sub == "delegate":
        m = relay.send_delegate(root, args.workspace, args.title, args.text, args.check, t)
        out(args, m, f"Task handed to {relay.name_of(root, m['to'])}. It starts once they allow it.")
    elif sub == "start":
        m = relay.send_start(root, args.workspace, args.key, args.text, t)
        out(args, m, f"Start request sent to {relay.name_of(root, m['to'])}.")
    elif sub == "allow":
        msg = relay.load_message(root, args.id)
        b = msg.get("body", {})
        task = b.get("title") or b.get("key") or args.id
        mode = "once" if args.once else "permanent"
        tickets.require_human(
            f"Allow {msg.get('from')} to {msg.get('type')} {task}?", f"allowing {msg.get('from')} ({mode})"
        )
        m = relay.give_allow(root, args.id, mode)
        out(args, m, f"Allowed ({m['body']['mode']}). {relay.name_of(root, m['to'])} has been told.")
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


def _inbox_line(i: dict, root: Path) -> str:
    m, b = i["message"], i["message"].get("body", {})
    kind = {
        "text": "Message",
        "file": "File",
        "question": "Question",
        "delegate": "Task",
        "start": "Start request",
        "refresh-hint": "Update",
        "webhook": "Webhook",
        "answer": "Answer",
    }.get(m["type"], m["type"])
    at = f" ({net.when(m['created_at'])})" if m.get("created_at") else ""
    head = f"{kind} from {relay.name_of(root, m['from'])}{at}"
    tail = f"  [{m['id']}]"
    if i["note"]:
        return f"{head}: {i['note']}{tail}"
    reply = f' - reply: orch relay send {m["from"]} "<text>"' if m["from"].startswith("ph_") else ""
    detail = {
        "text": lambda: b.get("text", "") + reply,
        "file": lambda: (
            f"{b.get('name')} ({_size(b.get('size') or 0)}) - save it with: orch relay download {m['id']}"
        ),
        "question": lambda: b.get("text", ""),
        "delegate": lambda: b.get("title", ""),
        "start": lambda: f"{b.get('key')}: {b.get('text', '')}",
        "refresh-hint": lambda: "new settings are waiting - run: orch relay refresh",
        "webhook": lambda: b.get("payload", "")[:200],
    }.get(m["type"], lambda: "")()
    if m["type"] in ("delegate", "start"):
        al = i["allowed"]
        hint = f"[not allowed yet - ask the human to run: orch relay allow {m['id']} --once|--permanent]"
        detail += f"  [allowed: {al}]" if al else f"  {hint}"
    return f"{head}: {detail}{tail}".replace(": " + tail, tail)


def send_phone_question(root: Path, tid: str, q: dict) -> None:
    try:
        relay.send_question(root, tickets.load(root, tid), q)
    except Refused as e:
        raise Refused(
            f"The question is saved on the ticket, but it could not be sent to the phones. {e}"
        ) from None

"""Argument parsing and plain-words output for `orch publish ...` and `orch relay ...`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlsplit

from orch import humanproof, net, publish, relay, templates, term, tickets
from orch.errors import Refused
from orch.text import clean_untrusted


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
    x = pub.add_parser("file", parents=[common, life], help="encrypt and share a file or a page folder")
    x.add_argument("path")
    x.add_argument("--note", help="a short message for the person who opens the link (up to 280 characters)")
    x.add_argument(
        "--replace", metavar="ID", help="swap the content of this file (f_...), the link stays the same"
    )
    x = pub.add_parser("extend", parents=[common], help="keep a shared file longer (same link)")
    x.add_argument("id")
    x.add_argument("--days", type=int, required=True, help="from today, 1-90 (never shorter than now)")
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
    pub.add_parser("view", parents=[common], help="the Shared tab of the dashboard (read-only, no keys)")
    for n in ("restart", "stop"):
        x = pub.add_parser(n, parents=[common], help=f"{n} a deployed app")
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
    rel.add_parser("view", parents=[common], help="the Relay tab of the dashboard (read-only, no network)")
    _add_mobile(rel, common)
    _add_profile(rel)
    x = rel.add_parser("inbox", parents=[common], help="pull new messages")
    x.add_argument("--wait", type=int, default=0, help="wait up to N seconds (max 30)")
    x.add_argument("--since", type=int, help="add-ons: list every arrival after this number (marks nothing)")
    x = rel.add_parser("outbox", parents=[common], help="messages saved but not sent yet")
    x.add_argument("--resend", action="store_true", help="try to send them now")
    x = rel.add_parser(
        "done", parents=[common], help="mark a message as handled (and get the ticket of an allowed task)"
    )
    x.add_argument("id")
    t = argparse.ArgumentParser(add_help=False)
    t.add_argument("--ticket")
    x = rel.add_parser("send", parents=[common, t], help="send a message or file to a workspace or phone")
    x.add_argument("workspace")
    x.add_argument("text", nargs="?", default="")
    x.add_argument("--file")
    x.add_argument("--update", choices=relay.UPDATE_KINDS, help="mark the text as a work update of --ticket")
    x.add_argument("--reply-to", help="id of the message this answers")
    x.add_argument("--speak", action="store_true", help="a phone can read this out loud (long answers)")
    x.add_argument("--summary", help="what to read out instead of the whole text (with --speak)")
    x.add_argument(
        "--ref",
        action="append",
        default=[],
        metavar="KIND:VALUE",
        help="a card in Chat: ticket:<KEY>, proposal:<title>, reference:<url> or file:<path> (repeat)",
    )
    x = rel.add_parser(
        "topic", parents=[common], help="turn a phone message (from General) into a ticket of its own"
    )
    x.add_argument("--from", dest="message", required=True, help="id of the phone message")
    x.add_argument("title")
    x = rel.add_parser("delegate", parents=[common, t], help="hand a task to another workspace")
    x.add_argument("workspace")
    x.add_argument("title")
    x.add_argument("--text", default="")
    x.add_argument("--check", action="append", default=[], help="checklist item (repeat)")
    x.add_argument(
        "--group",
        action="store_true",
        help="open the ticket's group chat with that workspace (needs --ticket)",
    )
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
    _add_group(rel, common)
    w = rel.add_parser("webhook", help="addresses that turn outside calls into messages").add_subparsers(
        dest="wsub", required=True
    )
    x = w.add_parser("new", parents=[common, t], help="make a webhook address (shown once)")
    g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true")
    g.add_argument("--permanent", action="store_true")
    w.add_parser("list", parents=[common], help="list webhooks")
    x = w.add_parser("delete", parents=[common], help="delete a webhook")
    x.add_argument("id")


def _add_group(rel, common) -> None:
    g = rel.add_parser("group", help="group chats across workspaces (hosted by the ticket's workspace)")
    gs = g.add_subparsers(dest="gsub", required=True)
    gs.add_parser("list", parents=[common], help="groups this workspace hosts or was invited to")
    x = gs.add_parser("say", parents=[common], help="host: write into the ticket's group")
    x.add_argument("ticket")
    x.add_argument("text")
    x.add_argument("--to-person", action="store_true", help="the text is addressed to the person (pushed)")
    x.add_argument("--dashboard", action="store_true", help="written by the person at this dashboard")
    x = gs.add_parser("add", parents=[common], help="host: add a connected workspace to the ticket's group")
    x.add_argument("ticket")
    x.add_argument("workspace")
    x = gs.add_parser("remove", parents=[common], help="host: remove a member")
    x.add_argument("ticket")
    x.add_argument("workspace")
    x = gs.add_parser(
        "ask", parents=[common], help="host: send an information question of the ticket to a member"
    )
    x.add_argument("ticket")
    x.add_argument("workspace")
    x.add_argument("question", help="question id on the ticket (q1)")
    x = gs.add_parser("share", parents=[common], help="host: share a file with the group")
    x.add_argument("ticket")
    x.add_argument("file")
    x.add_argument("--title")
    x.add_argument("--click", action="store_true", help="a person chose to share it (needed for pictures)")
    x.add_argument(
        "--unchecked-ok", action="store_true", help="with --click: share although it could not be checked"
    )
    x = gs.add_parser("reply", parents=[common], help="member: write into a group")
    x.add_argument("host")
    x.add_argument("group")
    x.add_argument("text")
    x.add_argument("--dashboard", action="store_true", help="written by the person at this dashboard")
    x = gs.add_parser("answer", parents=[common], help="member: answer a group question")
    x.add_argument("message")
    x.add_argument("text")
    x = gs.add_parser(
        "send-file", parents=[common], help="member: share a file with the group (a person's click)"
    )
    x.add_argument("host")
    x.add_argument("group")
    x.add_argument("file")
    x.add_argument("--title")
    x.add_argument("--click", action="store_true")
    x.add_argument(
        "--unchecked-ok", action="store_true", help="with --click: share although it could not be checked"
    )
    x = gs.add_parser("leave", parents=[common], help="member: leave a group")
    x.add_argument("host")
    x.add_argument("group")


def _confirm(args):
    """The person's yes to 'share anyway' for a file orch could not check. An agent session needs a yes
    typed at a terminal (tickets.require_human); a person at a terminal is asked; a person's dashboard (no
    terminal) has already asked in its own dialog and says so with --unchecked-ok."""

    def ask(question: str) -> bool:
        if tickets.agent_tool() is not None:
            try:
                tickets.require_human(question, "sharing a file that could not be checked")
            except Refused:
                return False
            return True
        if term.is_terminal(sys.stdin):
            sys.stderr.write(f"{question} [y/N] ")
            sys.stderr.flush()
            return sys.stdin.readline().strip().lower() in ("y", "yes")
        return bool(args.unchecked_ok)

    return ask


def _as_person(args, root: Path, op: str, target: str, **kw) -> str | None:
    """A person's own act in a group (H1). Returns the VERIFIED human identity (from a proof; a terminal
    command is handed off to the page and refused here), or None for a caller that claims to be an agent (an
    agent session, or --by agent:...). EVERY caller branches on the return value: a person's flags
    (--dashboard, --click) are honoured only for a verified identity, an agent claim gets the downgraded
    action. Never "did not raise"."""
    if tickets.agent_tool() or (getattr(args, "by", None) or "").startswith("agent:"):
        return None
    who = humanproof.person_by(root, args, op, target, **kw)
    if not who.startswith("human:"):
        return None
    return who


def _file_sha(root: Path, path: str) -> str:
    """The content hash of a file a person is about to share (the proof's target binds the content)."""
    import hashlib

    from orch import chat_groups as cg

    return hashlib.sha256(cg.read_shared(Path(path), root, confined=False)).hexdigest()


def _group_title(root: Path, group: str) -> str:
    """The group's name for a card (never its raw id); an unknown group is "a group chat"."""
    from orch import chat_groups as cg

    try:
        v = cg.view(root)
        for g in [*v["hosted"], *v["joined"]]:
            if g.get("id") == group and g.get("title"):
                return str(g["title"])
    except (Refused, OSError, KeyError):
        pass
    return "a group chat"


def _share_card(args) -> dict:
    """What the share card must show and what the page will run (F4): the full resolved path of the file (the
    card shows it in an "Exact file:" block) and a command with that absolute path, so the page's folder can
    never turn a relative name into another file."""
    full = str(Path(args.file).resolve())
    argv = humanproof._clean_argv(humanproof.CURRENT_ARGV) or []
    argv = [full if a == args.file else a for a in argv]
    return {"exact": full, "argv": argv}


def run_group(args, root: Path, out) -> None:
    from orch import chat_groups as cg

    by, sub = tickets.current_actor(), args.gsub
    tid = tickets.resolve(root, getattr(args, "ticket", None)) if hasattr(args, "ticket") else None
    ws = relay.resolve(root, args.workspace) if hasattr(args, "workspace") else None
    if sub == "list":
        v = cg.view(root)
        rows = [f"{g['title']} ({g['id']}) - hosted, {len(g['members'])} members" for g in v["hosted"]]
        rows += [f"{g['title']} ({g['host']}/{g['id']}) - invited" for g in v["joined"]]
        out(args, v, "\n".join(rows) or "No groups.")
    elif sub == "say":
        as_person = None
        if args.dashboard:  # writing into the group AS the person: only with the person's verified proof
            as_person = _as_person(
                args, root, "group.write_as_person", tid,
                parts={"title": humanproof.ticket_name(root, tid)}, value=args.text,
            )  # fmt: skip
        r = cg.say(root, tid, args.text, "dashboard" if as_person else "helper", args.to_person, by)
        out(args, r, "Written into the group.")
    elif sub == "add":
        r = cg.add_member(root, tid, ws, by)
        out(args, r, "Added to the group." if r["added"] else "Already in the group.")
    elif sub == "remove":
        person = _as_person(
            args, root, "group.remove_member", f"{tid}:{args.workspace}",
            parts={
                "title": humanproof.ticket_name(root, tid),
                "workspace": humanproof.part(relay.name_of(root, ws)),
            },
        )  # fmt: skip
        if person is None:  # an agent claim never removes a member (no typed yes, no flag counts)
            raise Refused(humanproof.AGENT_REFUSED)
        r = cg.remove_member(root, tid, ws, by)
        out(args, r, "Removed from the group.")
    elif sub == "ask":
        m = cg.ask(root, tid, ws, args.question, by)
        out(args, m, _sent_line(root, m, "Question sent to {}."))
    elif sub == "share":
        click, sha = False, None  # the downgraded action: confined to the workspace, no click
        if args.click:  # a person shares a file with the group: the proof binds the file's CONTENT
            sha = _file_sha(root, args.file)
            if _as_person(
                args, root, "group.share_file", f"{tid}:{sha}",
                parts={
                    "title": humanproof.ticket_name(root, tid),
                    "file": humanproof.part(Path(args.file).name),
                },
                **_share_card(args),
            ):  # fmt: skip
                click = True
        # the bytes that are uploaded are checked against the bytes the proof covers (expect_sha)
        r = cg.share_file(
            root,
            tid,
            Path(args.file),
            args.title,
            None,
            click,
            by,
            _confirm(args),
            expect_sha=sha if click else None,
        )
        out(args, r, "Shared with the group.")
    elif sub == "reply":
        as_person = None
        if (
            args.dashboard
        ):  # only a verified person speaks as themselves; an agent claim is downgraded to helper
            as_person = _as_person(
                args, root, "group.write_as_person", args.group,
                parts={"title": humanproof.part(_group_title(root, args.group))}, value=args.text,
            )  # fmt: skip
        m = cg.say_member(
            root,
            relay.resolve(root, args.host),
            args.group,
            args.text,
            "dashboard" if as_person else "helper",
        )
        out(args, m, "Written into the group.")
    elif sub == "answer":
        m = cg.answer(root, args.message, args.text)
        out(args, m, "Answer sent.")
    elif sub == "send-file":
        click, sha = False, None  # an agent claim: no click, so share_member refuses in words
        if args.click:  # the proof binds the file's content, checked against the uploaded bytes
            sha = _file_sha(root, args.file)
            if _as_person(
                args, root, "group.share_file", f"{args.group}:{sha}",
                parts={
                    "title": humanproof.part(_group_title(root, args.group)),
                    "file": humanproof.part(Path(args.file).name),
                },
                **_share_card(args),
            ):  # fmt: skip
                click = True
        m = cg.share_member(
            root,
            relay.resolve(root, args.host),
            args.group,
            Path(args.file),
            args.title,
            click,
            _confirm(args),
            expect_sha=sha if click else None,
        )
        out(args, m, "Shared with the group.")
    elif sub == "leave":
        r = cg.leave(root, relay.resolve(root, args.host), args.group)
        out(args, r, "You left the group.")


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
            r = publish.share_file(root, Path(args.path), args.days, args.permanent, args.note, args.replace)
        out(
            args,
            r,
            f"{'Replaced' if args.replace else 'Shared'} {r['name']} ({_size(r['size'])}), "
            f"{_exp(r['expires_at'])}. Open this link:\n{r['link']}"
            + (f"\nFiles: {', '.join(r['files'])}" if r.get("files") else "")
            + (f"\nLeft out (look like secrets): {', '.join(r['skipped'])}" if r.get("skipped") else ""),
        )
    elif sub == "extend":
        r = publish.extend(root, args.id, args.days)
        out(args, r, f"{r.get('name') or args.id} now {_exp(r['expires_at'])}. Same link.")
    elif sub == "view":
        v = publish.view(root)
        rows = [
            f"{i['title']}  {i['subtitle']}" for b in v["blocks"] if b["type"] == "list" for i in b["items"]
        ]
        out(args, v, "\n".join(rows) or "Nothing shared yet.")
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


def _add_mobile(rel, common) -> None:
    mob = rel.add_parser(
        "mobile",
        parents=[common],
        help="Mobile mode: questions also go to the phone, this computer stays awake",
    ).add_subparsers(dest="mobile", required=True)
    x = mob.add_parser("on", parents=[common], help="turn Mobile mode on")
    x.add_argument(
        "--hours", type=int, help="switch off by itself after 4, 8, 12 or 24 hours (default: the saved one)"
    )
    mob.add_parser("off", parents=[common], help="turn Mobile mode off")
    mob.add_parser("status", parents=[common], help="is Mobile mode on, until when")
    x = mob.add_parser("hours", parents=[common], help="save how long Mobile mode stays on by default")
    x.add_argument("hours", type=int)
    mob.add_parser("ack", parents=[common], help="dismiss the 'Mobile mode ended' notice")
    mob.add_parser("keeper", parents=[common], help=argparse.SUPPRESS)


def _mobile_line(st: dict) -> str:
    if not st["on"]:
        return (st.get("ended") or {}).get("text") or "Mobile mode is off."
    awake = "" if st["awake"] != "could_not_keep_awake" else " Could not keep this computer awake."
    return f"Mobile mode is on since {st['since']}, ends {st['ends_at']}.{awake}"


def run_mobile(args, root: Path, out) -> None:
    from orch import mobile_mode as mm

    sub = args.mobile
    if sub == "keeper":
        mm.run_keeper(root)
        return
    if sub == "on":
        st = mm.turn_on(root, args.hours)
    elif sub == "off":
        st = mm.turn_off(root)
    elif sub == "hours":
        mm.set_default_hours(root, args.hours)
        st = mm.status(root)
    elif sub == "ack":
        mm.acknowledge_ended(root)
        st = mm.status(root)
    else:
        st = mm.status(root)
    out(args, st, _mobile_line(st))


def run_relay(args, root: Path, out) -> None:
    sub = args.sub
    args._root = root
    if sub == "profile":
        return _run_profile(args, relay, out)
    if sub == "mobile":
        return run_mobile(args, root, out)
    t = getattr(args, "ticket", None)
    if sub not in ("connect", "status", "outbox", "view"):
        _resend_waiting(root)
    if sub == "group":
        return run_group(args, root, out)
    if sub == "connect":
        # connecting (or changing the relay address) is a person's action (H1): proof for this relay host
        address = humanproof.server_address(args.url)  # refuses a URL with a name or password in it
        if not humanproof.person_by(
            root,
            args,
            "relay.connect",
            address,
            parts={"host": address, "scheme": urlsplit(args.url.strip()).scheme},
            exact=address,
        ).startswith("human:"):
            raise Refused(humanproof.AGENT_REFUSED)
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
    elif sub == "view":
        from orch import relay_view

        v = relay_view.view(root)
        rows = [f"{i['title']}  {i['subtitle']}" for b in v["blocks"] for i in b["items"]]
        out(args, v, "\n".join([v.get("notice", ""), *rows]).strip())
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
    elif sub == "outbox":
        res = relay.resend_outbox(root) if args.resend else None
        left = relay.outbox_list(root)
        lines = [f"{m['id']}  to {relay.name_of(root, m['to'])}  {m['type']}" for m in left]
        for d in (res or {}).get("dropped", []):
            lines.append(f"Not sent, the relay refused {d['id']}: {d['reason']}")
        if res and res["sent"]:
            lines.insert(0, f"Sent {len(res['sent'])} waiting message{'s' if len(res['sent']) != 1 else ''}.")
        if left and (res or {}).get("problem"):
            lines.append(f"Not sent: {res['problem']} These go out once this is fixed.")
        elif left:
            lines.append("These go out with the next orch relay command.")
        out(args, {"waiting": left, **(res or {})}, "\n".join(lines) or "Nothing is waiting to be sent.")
    elif sub == "inbox" and args.since is not None:
        r = relay.since(root, args.since, args.wait)
        if r.get("warning"):
            print(
                f"Could not check the relay just now, showing what is saved here. {r['warning']}",
                file=sys.stderr,
            )
        lines = [
            f"{i['seq']}  {i['type']} from {relay.name_of(root, i['from'])}  [{i['id']}]" for i in r["items"]
        ]
        out(args, r, "\n".join(lines) or "Nothing new since then.")
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
        if args.file and (args.update or args.reply_to or args.speak):
            raise Refused("--update, --reply-to and --speak go with a text, not a file.")
        if args.summary and not args.speak:
            raise Refused("--summary goes with --speak.")
        if args.file:
            m = relay.send_file(root, args.workspace, Path(args.file), args.text or None, t)
        elif args.text:
            speak = relay.speak_hint(root, t, args.text, args.summary) if args.speak else None
            refs = [
                {"kind": k, {"ticket": "key", "reference": "url", "proposal": "title"}.get(k, "path"): v}
                for k, _, v in (r.partition(":") for r in args.ref)
            ]
            m = relay.send_text(
                root, args.workspace, args.text, t, args.update, args.reply_to, speak=speak, refs=refs
            )
        else:
            raise Refused("Nothing to send. Give a text or --file.")
        out(args, m, _sent_line(root, m, "Message sent to {}."))
    elif sub == "topic":
        r = relay.topic(root, args.message, args.title, tickets.current_actor())
        out(args, r, f"Started {r['key'] or r['ticket']} ({r['ticket']}). The phone shows it as a topic now.")
    elif sub == "delegate":
        m = relay.send_delegate(root, args.workspace, args.title, args.text, args.check, t, args.group)
        out(args, m, _sent_line(root, m, "Task handed to {}. It starts once they allow it."))
    elif sub == "start":
        m = relay.send_start(root, args.workspace, args.key, args.text, t)
        out(args, m, _sent_line(root, m, "Start request sent to {}."))
    elif sub == "allow":
        msg = relay.load_message(root, args.id)
        b = msg.get("body", {})
        task = b.get("title") or b.get("key") or args.id
        mode = "once" if args.once else "permanent"
        if not humanproof.person_by(
            root,
            args,
            "relay.allow",
            f"{args.id}:{mode}",
            parts={
                "peer": humanproof.part(relay.name_of(root, msg.get("from"))),
                "task": humanproof.part(task),
                "mode": mode,
            },
        ).startswith("human:"):
            raise Refused(humanproof.AGENT_REFUSED)
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


NOT_SENT = "Not sent yet - the relay can't be reached. It goes out with the next orch relay command."


def _sent_line(root: Path, m: dict, ok: str) -> str:
    if m.get("sent") is False and m.get("problem"):
        return f"Not sent: {m['problem']} The message is kept and goes out once this is fixed."
    return NOT_SENT if m.get("sent") is False else ok.format(relay.name_of(root, m["to"]))


def _resend_waiting(root: Path) -> None:
    """Every orch relay command first sends what waits in .orch/outbox/ (never fails the command)."""
    try:
        net.load_service(root, "relay")
        res = relay.resend_outbox(root)
    except (Refused, OSError):
        return
    for d in res["dropped"]:
        print(
            f"A saved message could not be sent and was removed: {d['reason']} [{d['id']}]", file=sys.stderr
        )
    if res.get("problem"):
        print(f"Saved messages are waiting: {res['problem']}", file=sys.stderr)


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
    if relay.msg_group(m) and not i.get("auto"):  # outside text: cleaned and framed, never instructions (G10)
        from orch import chat_groups

        return f"{head}: {chat_groups.prompt_text(m)}{tail}"
    if i["note"]:
        return f"{head}: {i['note']}{tail}"
    reply = f' - reply: orch relay send {m["from"]} "<text>"' if m["from"].startswith("ph_") else ""

    def c(v, n=2000):
        return clean_untrusted(str(v or ""), n)

    def file_line():
        said = f": {c(b.get('text'), 500)}" if b.get("text") else ""
        name = f"{c(b.get('name'), 200)} ({_size(b.get('size') or 0)})"
        return f"{name}{said} - save it with: orch relay download {m['id']}"

    detail = {
        "text": lambda: c(b.get("text")) + reply,
        "file": file_line,
        "question": lambda: c(b.get("text")),
        "delegate": lambda: c(b.get("title"), 200),
        "start": lambda: f"{c(b.get('key'), 48)}: {c(b.get('text'))}",
        "refresh-hint": lambda: "new settings are waiting - run: orch relay refresh",
        "webhook": lambda: c(b.get("payload"), 200),
    }.get(m["type"], lambda: "")()
    if m["type"] in ("delegate", "start"):
        al = i["allowed"]
        hint = f"[not allowed yet - ask the human to run: orch relay allow {m['id']} --once|--permanent]"
        detail += f"  [allowed: {al}]" if al else f"  {hint}"
    return f"{head}: {detail}{tail}".replace(": " + tail, tail)


def send_phone_question(
    root: Path, tid: str, q: dict, previews: list[str] | None = None, scope: str | None = None
) -> None:
    try:
        m = relay.send_question(root, tickets.load(root, tid), q, previews, scope)
        if m.get("sent") is False:
            raise Refused(m.get("problem") or NOT_SENT)
    except Refused as e:
        raise Refused(
            f"The question is saved on the ticket, but it could not be sent to the phones. {e}"
        ) from None

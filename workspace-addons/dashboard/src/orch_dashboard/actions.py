"""What the dashboard may do: one fixed table of ops, each building exactly one `orch` argv.

No shell is involved. Ids are checked by regex, text is limited to 2000 characters, and free text always goes
after `--` (or as `--flag=value`) so it can never be read as an option. The dashboard never names an add-on.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from . import runfiles
from .data import forget_static, publish_connected, run_orch
from .look import LOOK_OPS
from .look import forget as look_forget
from .mobile import MOBILE_OPS, MOBILE_REQUIRED_ADDONS

_run = subprocess.run  # tests patch this name, never the global subprocess.run (other threads use that)
try:
    from orch.pageproof import SELF, argv0, run_with_proof
except ImportError:  # standalone use without orch: nothing runs
    SELF = "orch:self"

    def argv0(orch_bin):
        return [str(orch_bin)]

    run_with_proof = None

MAX_TEXT = 2000
LONG_TEXT = 1500  # a longer new-ticket text is kept as a file (note.md), the Note stays short
MAX_LONG = 500_000  # characters of one long text (core refuses a file over 2 MB)
# Mirror of orch.tickets (ATTACH_TEXT/ATTACH_IMAGES/ATTACH_MAX): refuse early, before a ticket is made. orch decides.
ATTACH_EXT = frozenset(
    {
        "txt",
        "md",
        "csv",
        "tsv",
        "json",
        "log",
        "yml",
        "yaml",
        "toml",
        "ini",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
    }
)
ATTACH_MAX = 2 * 1024 * 1024
LONG_NOTE = (
    "The full text is attached as note.md. Read it, then give this ticket a short title and description."
)
TID = re.compile(r"t_[a-z0-9]{6,16}")
QID = re.compile(r"q[0-9]{1,4}")
SHA = re.compile(r"[0-9a-f]{40,64}")
DAY = re.compile(r"(\d{4}-\d\d-\d\d)?")
ADDON = re.compile(r"[a-z][a-z0-9-]{1,31}")
VERB = re.compile(r"[a-z][a-z-]{0,20}")
# A name that is also a core command is never an add-on target, whatever the add-on list says.
RESERVED = frozenset(
    {
        "ticket",
        "check",
        "log",
        "ask",
        "answer",
        "ref",
        "ext",
        "wait",
        "needs",
        "run",
        "start",
        "stop",
        "status",
        "init",
        "update",
        "addon",
        "agents",
        "config",
        "clients",
        "help",
        "setup",
        "dashboard",
    }
)
AGENT = re.compile(r"[a-z][a-z0-9-]{1,31}")
MAX_COMMAND = 500
MAX_TASK = 500
PERMISSIONS = ("ask", "auto", "full")
PATCH_KEYS = ("title", "status", "owner", "due", "note", "done_when", "summary")
STATUSES = ("open", "ready", "active", "waiting", "review", "done")


class BadRequest(Exception):
    """The request does not match the op table (HTTP 400)."""


class Unavailable(Exception):
    """No orch command to run (HTTP 503)."""


class NeedsPerson(Exception):
    """A human-only click without a proof session (HTTP 403): the page is watch-only here."""


# page op -> (core op, target of the proof) for the clicks that are a person's (H1, contracts/human-proof.md).
# `ticket.patch` is a verdict only when it sets Done ("Looks good"); the core checks the rest.
PROOF_OPS = {
    "copies.remove_orphaned": (
        "copy.remove_orphaned",
        lambda a: f"{a.get('ws8')}:discard" if a.get("discard") else a.get("ws8"),
    ),
    "copies.retry": ("copy.retry", lambda a: a.get("ticket")),
    "copies.approve": (
        "copy.retry",
        lambda a: f"approve:{a.get('ticket')}:{a.get('tip')}:{a.get('control_paths')}:{a.get('paths_hash')}",
    ),
    "answer": ("ticket.answer", lambda a: f"{a.get('ticket')}:{a.get('question')}:{_question_digest(a)}"),
    "ticket.changes": ("ticket.verdict", lambda a: a.get("ticket")),
    "chat.say": ("chat.send", lambda a: "general"),
    "run.send": ("run.human_input", lambda a: a.get("ticket")),  # also used by an embedded add-on page
    "chat.make_ticket": ("chat.make_ticket", lambda a: a.get("id")),
    "check.wont_do": ("check.wont_do", lambda a: f"{a.get('ticket')}:{a.get('check')}"),
    "check.reopen": ("check.wont_do_undo", lambda a: f"{a.get('ticket')}:{a.get('check')}:reopen"),
    "check.edit": ("check.wont_do_undo", lambda a: f"{a.get('ticket')}:{a.get('check')}:edit"),
    "check.remove": ("check.wont_do_undo", lambda a: f"{a.get('ticket')}:{a.get('check')}:remove"),
    "chat.send_ws": ("chat.send", lambda a: a.get("workspace")),
    "private.move": ("private.move", lambda a: "move"),
    "private.allow": ("private.allow", lambda a: f"{a.get('name')}:{a.get('key')}"),
    "config.permissions": ("config.permissions", lambda a: a.get("mode")),
    "config.agent.add": ("config.agent_add", lambda a: _agent_add_target(a)),
    "look.set": ("look.icon", lambda a: "look"),
}


def _agent_add_target(a):
    """The proof target of config.agent_add: core's one definition (name + digest of every saved value; the
    dashboard never offers a live command)."""
    from orch import humanproof

    return humanproof.agent_add_target(a.get("name"), a.get("command"), None, a.get("prompt_via"))


def proof_for(op, args, root=None):
    """(core op, target) when this click needs a proof, else None."""
    if op == "ticket.patch" and isinstance(args.get("data"), dict) and "status" in args["data"]:
        return "ticket.verdict", args.get("ticket")
    if (
        op == "check.set" and args.get("done") is False
    ):  # un-ticking may undo a Won't do (a person's decision)
        return "check.wont_do_undo", f"{args.get('ticket')}:{args.get('check')}:reopen"
    if op == "group.say":  # writing into a group as the person (host: by ticket; invited: by group)
        if args.get("ticket"):
            return "group.write_as_person", str(args["ticket"])
        from orch import humanproof as _hp

        return "group.write_as_person", _hp.group_target(root, str(args.get("host")), str(args.get("group")))
    if op == "group.remove":
        return "group.remove_member", f"{args.get('ticket')}:{args.get('workspace')}"
    if (
        op == "group.share" and root is not None
    ):  # the proof binds the file's CONTENT (the core hashes the same)
        return "group.share_file", f"{args.get('ticket')}:{_share_sha(root, args)}"
    if op == "workflow.set":  # allowing agents to finish tickets (off needs no proof)
        return ("config.agents_may_finish", "on") if args.get("on") is True else None
    if op == "copies.set" and "setup" in args:  # a command orch runs in every new copy; clearing is free
        v = args.get("setup")
        if isinstance(v, str) and v.strip() not in ("", "none"):
            return "config.copy_setup", hashlib.sha256(v.strip().encode()).hexdigest()
        return None
    if op == "share.set":  # sharing the orch entry with the team (off needs no proof)
        return ("config.share", "on") if args.get("on") is True else None
    if op == "look.shared":
        return "look.shared_pages", "on" if args.get("on") is True else "off"
    hit = PROOF_OPS.get(op)
    return (hit[0], hit[1](args)) if hit else None


# Ops any scripted request may do without a page session: they are what an agent can do through the CLI as
# itself (a ticket, a task, a note, a reference), nothing that speaks or decides for the person. EVERY other op acts
# as the person (`--by human:...`): the server refuses it without a page session (watch-only), and an op with a
# core gate (PROOF_OPS) also needs the person's proof.
FREE_OPS = frozenset(
    {
        "ticket.new",
        "ticket.paste",
        "ticket.attach",
        "ticket.edit",
        "ticket.field",
        "ticket.patch",
        "log",
        "check.add",
        "ref.add",
        "ref.rm",
        "look.description",
        "config.agent.test",
    }
)


def _share_sha(root, args) -> str:
    """The content hash the core computes for the same artifact (a person's click shares a ticket artifact). Read
    here with the file inside the ticket's artifacts folder only; anything else gives a target no proof matches."""
    import hashlib
    from pathlib import Path

    art = (Path(root) / ".orch" / "tickets" / str(args.get("ticket")) / "artifacts").resolve()
    try:
        path = (art / str(args.get("file"))).resolve()
        if art not in path.parents or not path.is_file() or path.stat().st_size > 25 * 1024 * 1024:
            return "unreadable"
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unreadable"


def needs_session(op) -> bool:
    return isinstance(op, str) and op not in FREE_OPS


def _tid(v) -> str:
    if not isinstance(v, str) or not TID.fullmatch(v):
        raise BadRequest("That is not a ticket id.")
    return v


def _qid(v) -> str:
    if not isinstance(v, str) or not QID.fullmatch(v):
        raise BadRequest("That is not a question id.")
    return v


def _text(v, name="text", empty=False, limit=MAX_TEXT) -> str:
    if not isinstance(v, str) or (not empty and not v.strip()):
        raise BadRequest(f"Please write the {name}.")
    if len(v) > limit:
        raise BadRequest(f"The {name} is too long (at most {limit} characters).")
    if "\x00" in v:
        raise BadRequest(f"The {name} has a character that is not allowed.")
    try:
        v.encode("utf-8")  # a lone surrogate (valid in JSON) cannot be passed on
    except UnicodeEncodeError:
        raise BadRequest(f"The {name} has a character that is not allowed.") from None
    return v


def _rev(v, required=False):
    if v is None and not required:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise BadRequest("The revision must be a whole number.")
    return v


def _flag(v) -> bool:
    if v is not None and not isinstance(v, bool):
        raise BadRequest("A yes/no value must be true or false.")
    return bool(v)


def _only(args: dict, allowed: tuple[str, ...]) -> None:
    extra = sorted(set(args) - set(allowed))
    if extra:
        raise BadRequest(f"Not allowed here: {', '.join(extra)}.")


def _question_digest(a):
    """The digest of the question as the page showed it (sent back with the answer): no digest, no answer."""
    d = a.get("digest")
    if not (isinstance(d, str) and re.fullmatch(r"[0-9a-f]{64}", d)):
        raise BadRequest("This question changed or can't be checked. Ask again.")
    return d


def _answer(a):
    _only(a, ("ticket", "question", "answer", "digest"))
    return (
        ["answer", _tid(a.get("ticket")), _qid(a.get("question"))],
        ["--via", "dashboard", "--question-digest", _question_digest(a)],
        [_text(a.get("answer"), "answer")],
    )


def _ticket_new(a):
    _only(
        a,
        (
            "title",
            "parent",
            "owner",
            "due",
            "note",
            "done_when",
            "long_text",
            "files",
            "title_auto",
            "plan_first",
        ),
    )
    flags = [f"--parent={_tid(a['parent'])}"] if a.get("parent") else []
    if _flag(a.get("title_auto")):  # the title is a placeholder: the agent writes the real one
        flags.append("--title-auto")
    if _flag(a.get("plan_first")):
        flags.append("--plan-first")
    long_text = a.get("long_text")
    if long_text is not None:
        _text(long_text, "text", limit=MAX_LONG)
    for k in ("owner", "due", "note", "done_when"):
        v = a.get(k)
        if k == "note" and long_text is not None and not v:
            v = LONG_NOTE
        if v:
            v = _text(v, k)
            if k == "due" and not DAY.fullmatch(v):
                raise BadRequest("The due day must look like 2026-11-30.")
            flags.append(f"--{k.replace('_', '-')}={v}")
    return ["ticket", "new"], flags, [_text(a.get("title"), "title")]


def attachments(op, args) -> list[tuple[str, bytes]]:
    """The files a new ticket brings along: (name hint, bytes), checked before anything is created. The name is
    only a hint, orch picks the real one; type, content and size are checked again by orch itself."""
    if op not in ("ticket.new", "ticket.paste", "ticket.attach") or not isinstance(args, dict):
        return []
    out: list[tuple[str, bytes]] = []
    long_text = args.get("long_text")
    if op == "ticket.paste":
        long_text = args.get("text") if len(args.get("text") or "") > LONG_TEXT else None
    if long_text is not None:
        out.append(("note.md", _text(long_text, "text", limit=MAX_LONG).encode("utf-8")))
        if len(out[0][1]) > ATTACH_MAX:
            raise BadRequest("The text is too long (at most 2 MB).")
    files = args.get("files")
    if files is None:
        return out
    # No count limit: each file stays under ATTACH_MAX and the request under the server's body limit.
    if op not in ("ticket.new", "ticket.attach") or not isinstance(files, list):
        raise BadRequest("Those files could not be read.")
    for f in files:
        if not isinstance(f, dict) or set(f) - {"name", "text", "data"} or not isinstance(f.get("name"), str):
            raise BadRequest("That file could not be read.")
        if len(f["name"]) > 240 or "\x00" in f["name"]:
            raise BadRequest("That file name is not allowed.")
        if isinstance(f.get("text"), str) and f.get("data") is None:
            try:
                raw = f["text"].encode("utf-8")
            except UnicodeEncodeError:
                raise BadRequest("That file could not be read.") from None
        elif isinstance(f.get("data"), str) and f.get("text") is None:
            try:
                raw = base64.b64decode(f["data"], validate=True)
            except ValueError:
                raise BadRequest("That file could not be read.") from None
        else:
            raise BadRequest("That file could not be read.")
        ext = f["name"].rsplit(".", 1)[-1].lower() if "." in f["name"] else ""
        if ext not in ATTACH_EXT:
            raise BadRequest(f"{f['name'][:60]}: only text files and pictures can be added.")
        if len(raw) > ATTACH_MAX:
            raise BadRequest(f"{f['name'][:60]} is over 2 MB.")
        out.append((f["name"], raw))
    return out


def _ticket_attach(a):
    """Files added to a ticket that already exists (a ticket page composer): one line in the history, the files go through
    `orch ticket attach` after it (see attachments / run_op)."""
    _only(a, ("ticket", "files"))
    if not isinstance(a.get("files"), list) or not a["files"]:
        raise BadRequest("Choose a file to add.")
    return ["log", _tid(a.get("ticket"))], [], ["Added files to the ticket"]


def _ticket_paste(a):
    _only(a, ("text", "parent"))
    text = _text(a.get("text"), limit=MAX_LONG)
    first = next(line.strip() for line in text.splitlines() if line.strip())
    auto = len(text) > LONG_TEXT or len([x for x in text.splitlines() if x.strip()]) > 1 or len(first) > 80
    args = {"title": first[:80], "parent": a.get("parent"), "title_auto": auto}
    if len(text) > LONG_TEXT:  # kept as note.md (see attachments); the Note stays short
        return _ticket_new({**args, "long_text": text})
    return _ticket_new({**args, "note": text})


def _ticket_patch(a):
    _only(a, ("ticket", "data", "if_revision", "review_tip"))
    data = a.get("data")
    if not isinstance(data, dict) or not data or set(data) - set(PATCH_KEYS):
        raise BadRequest("Nothing to change, or a field that cannot be changed here.")
    for k, v in data.items():
        if k == "status" and v not in STATUSES:
            raise BadRequest("That is not a status.")
        if k == "due" and not (isinstance(v, str) and DAY.fullmatch(v)):
            raise BadRequest("The due day must look like 2026-11-30.")
        if k not in ("status", "due"):
            _text(v, k, empty=k in ("owner", "note", "done_when"))
    rev = _rev(a.get("if_revision"), required=True)
    flags = [f"--if-revision={rev}"]
    # "Accept" sends the review tip the page showed; the core binds the Done to it. Anything that is not a
    # commit id is ignored (the Done is then judged as without one, never refused).
    tip = a.get("review_tip")
    if data.get("status") == "done" and isinstance(tip, str) and (tip == "none" or SHA.fullmatch(tip)):
        flags.append(f"--shown-tip={tip}")
    return (
        ["ticket", "patch", _tid(a.get("ticket"))],
        flags,
        [json.dumps(data, ensure_ascii=False)],
    )


def _ticket_changes(a):
    """Ask for changes on a ticket in Review: ONE call sets it Ready and queues the note as the person's input."""
    _only(a, ("ticket", "text"))
    return ["ticket", "changes"], [], [_tid(a.get("ticket")), _text(a.get("text"), "note")]


def _ticket_edit(a):
    _only(a, ("ticket", "title", "owner", "due", "note", "done_when", "if_revision"))
    flags = []
    for k in ("title", "owner", "due", "note", "done_when"):
        if k in a:
            v = _text(a[k], k, empty=k != "title")
            if k == "due" and not DAY.fullmatch(v):
                raise BadRequest("The due day must look like 2026-11-30.")
            flags.append(f"--{k.replace('_', '-')}={v}")
    if not flags:
        raise BadRequest("Nothing to change.")
    rev = _rev(a.get("if_revision"))
    if rev is not None:
        flags.append(f"--if-revision={rev}")
    return ["ticket", "edit", _tid(a.get("ticket"))], flags, []


def _check_add(a):
    """Add a task: `orch check add <ticket> --by ... -- <text>` (text up to 500 characters)."""
    _only(a, ("ticket", "text"))
    text = _text(a.get("text"), "task")
    if len(text) > MAX_TASK:
        raise BadRequest(f"The task is too long (at most {MAX_TASK} characters).")
    return ["check", "add", _tid(a.get("ticket"))], [], [text.strip()]


CID = re.compile(r"c[0-9]{1,4}")
TICKED_NOTE = "Ticked off in the dashboard"


def _check_set(a):
    """Tick a task on or off by hand: `orch check done <ticket> <task> --note ...` or `orch check reopen`.
    Proof for a person's tick is the fixed note above; only a task id of this ticket is accepted."""
    _only(a, ("ticket", "check", "done"))
    cid = a.get("check")
    if not (isinstance(cid, str) and CID.fullmatch(cid)):
        raise BadRequest("Choose a task.")
    if type(a.get("done")) is not bool:
        raise BadRequest("Say done or not done.")
    if a["done"]:
        return ["check", "done", _tid(a.get("ticket")), cid], [f"--note={TICKED_NOTE}"], []
    return ["check", "reopen", _tid(a.get("ticket")), cid], [], []


def _check_wont_do(a):
    _only(a, ("ticket", "check", "reason"))
    cid = a.get("check")
    if not (isinstance(cid, str) and CID.fullmatch(cid)):
        raise BadRequest("Choose a task.")
    reason = _text(a.get("reason", ""), "reason", empty=True, limit=200).strip()
    if "\n" in reason or "\r" in reason:
        raise BadRequest("The reason must be one line.")
    return ["check", "wont-do", _tid(a.get("ticket")), cid], [f"--reason={reason}"] if reason else [], []


def _check_edit(a):
    """Rename a step (used by an embedded add-on page): `orch check edit <ticket> <task> [flags] -- <text>`."""
    _only(a, ("ticket", "check", "text", "if_revision", "was"))
    cid = a.get("check")
    if not (isinstance(cid, str) and CID.fullmatch(cid)):
        raise BadRequest("Choose a task.")
    flags = []
    if (rev := _rev(a.get("if_revision"))) is not None:
        flags.append(f"--if-revision={rev}")
    if a.get("was") is not None:
        flags.append(f"--was={_text(a['was'], 'old text')}")
    return ["check", "edit", _tid(a.get("ticket")), cid], flags, [_text(a.get("text"))]


def _check_remove(a):
    _only(a, ("ticket", "check"))
    cid = a.get("check")
    if not (isinstance(cid, str) and CID.fullmatch(cid)):
        raise BadRequest("Choose a task.")
    return ["check", "remove", _tid(a.get("ticket")), cid], [], []


def _check_reopen(a):
    """Open a step again (also a Won't do step): `orch check reopen <ticket> <task>`."""
    _only(a, ("ticket", "check"))
    cid = a.get("check")
    if not (isinstance(cid, str) and CID.fullmatch(cid)):
        raise BadRequest("Choose a task.")
    return ["check", "reopen", _tid(a.get("ticket")), cid], [], []


def _ref_add(a):
    _only(a, ("ticket", "target"))
    return ["ref", "add", _tid(a.get("ticket"))], [], [_text(a.get("target"), "reference")]


def _ref_rm(a):
    _only(a, ("ticket", "n"))
    n = a.get("n")
    if type(n) is not int or n < 1:
        raise BadRequest("Choose a reference.")
    return ["ref", "rm", _tid(a.get("ticket")), str(n)], [], []


def _workflow_set(a):
    _only(a, ("on",))
    if type(a.get("on")) is not bool:
        raise BadRequest("Say on or off.")
    return ["config", "set", "workflow.agents_may_finish", "on" if a["on"] else "off"], [], []


COPY_MODES = ("off", "together", "always")


def _copies_set(a):
    """Separate copies (settings): exactly one of mode | max | setup, each one `orch config set workflow.<key>`.
    The setup command is a command orch runs in a new copy: it travels after `--` as one value, and core
    refuses it from an agent (a person's click only)."""
    _only(a, ("mode", "max", "setup"))
    given = [k for k in ("mode", "max", "setup") if k in a]
    if len(given) != 1:
        raise BadRequest("Change one setting at a time.")
    key = given[0]
    v = a[key]
    if key == "mode":
        if v not in COPY_MODES:
            raise BadRequest("Pick Off, When agents work together, or Every time.")
        return ["config", "set", "workflow.copies", v], [], []
    if key == "max":
        if type(v) is not int or not 1 <= v <= 20:
            raise BadRequest("Pick a number of copies from 1 to 20.")
        return ["config", "set", "workflow.copies_max", str(v)], [], []
    if not isinstance(v, str) or len(v) > 500 or any(c in v for c in "\r\n\x00"):
        raise BadRequest("Write the command on one line, at most 500 characters.")
    return ["config", "set", "workflow.copy_setup"], [], [v.strip() or "none"]


def _copies_clean(a):
    """The Clean up now button (settings): `orch copy clean`, the same sweep every start runs."""
    _only(a, ())
    return ["copy", "clean", "--json"], [], []


def _copies_remove_orphaned(a):
    """Remove the copies of a project that is gone or moved (a person's click; changes are saved first when git
    can reach the project, else the copies stay). `ws8` is the 8-character folder name `copies_disk` lists."""
    _only(a, ("ws8",))
    v = a.get("ws8")
    if not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{8}", v):
        raise BadRequest("That is not a copies folder.")
    return ["copy", "remove-orphaned", v, "--json"], [], []


def _copies_ask_update(a):
    _only(a, ("ticket",))
    v = a.get("ticket")
    if not isinstance(v, str) or not TID.fullmatch(v):
        raise BadRequest("That is not a ticket.")
    return ["copy", "ask-update", v, "--json"], [], []


def _copies_approve(a):
    _only(a, ("ticket", "tip", "control_paths", "paths_hash"))
    tid, tip, count = a.get("ticket"), a.get("tip"), a.get("control_paths")
    if (
        not isinstance(tid, str)
        or not TID.fullmatch(tid)
        or not isinstance(tip, str)
        or not re.fullmatch(r"[0-9a-f]{40,64}", tip)
        or type(count) is not int
        or count < 0
        or not isinstance(a.get("paths_hash"), str)
        or not re.fullmatch(r"[0-9a-f]{8}", a["paths_hash"])
    ):
        raise BadRequest("Review the copy again before bringing it back.")
    # What the person saw travels with the click; the core compares it with the copy as it is now.
    shown = ["--approve-tip", tip, "--control-paths", str(count), "--paths-hash", a["paths_hash"]]
    return ["copy", "retry", tid, *shown, "--json"], [], []


def _copies_retry(a):
    """Try again (settings), for a copy kept because git was interrupted: `orch copy retry <ticket>` (core
    removes the stale lock file of that copy and cleans it; a person's click only)."""
    _only(a, ("ticket",))
    v = a.get("ticket")
    if not isinstance(v, str) or not TID.fullmatch(v):
        raise BadRequest("That is not a ticket.")
    return ["copy", "retry", v, "--json"], [], []


def _ticket_field(a):
    """One add-on field: `orch ticket set <id> <addon>.<field> -- <value>` (core types and checks it; empty clears).
    The add-on must be on here (checked in run_op)."""
    _only(a, ("ticket", "addon", "field", "value", "if_revision"))
    addon, field = a.get("addon"), a.get("field")
    if not (isinstance(addon, str) and ADDON.fullmatch(addon) and addon not in RESERVED):
        raise BadRequest("That is not an add-on.")
    if not (isinstance(field, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", field)):
        raise BadRequest("That is not a field.")
    rev = _rev(a.get("if_revision"))
    flags = [f"--if-revision={rev}"] if rev is not None else []
    return (
        ["ticket", "set", _tid(a.get("ticket")), f"{addon}.{field}"],
        flags,
        [_text(a.get("value"), "value", empty=True)],
    )


def _log(a):
    _only(a, ("ticket", "text"))
    return ["log", _tid(a.get("ticket"))], [], [_text(a.get("text"))]


def _chat_say(a):
    """The person writes in Chat (history by "you", via dashboard; the background host starts the helper)."""
    _only(a, ("text", "new"))
    return ["chat", "say"], ["--new"] if _flag(a.get("new")) else [], [_text(a.get("text"))]


def _chat_make_ticket(a):
    _only(a, ("id",))
    mid = a.get("id")
    if not isinstance(mid, str) or not re.fullmatch(r"m_[a-z0-9]{10,64}", mid):
        raise BadRequest("That is not a message id.")
    return ["chat", "make-ticket", mid], [], []


def _run_start(a):
    _only(a, ("ticket", "fresh", "take_over"))
    flags = (["--fresh"] if _flag(a.get("fresh")) else []) + (
        ["--take-over"] if _flag(a.get("take_over")) else []
    )
    return ["run", "start", _tid(a.get("ticket"))], flags, []


def _run_send(a):
    _only(a, ("ticket", "text"))
    return ["run", "send"], [], [_tid(a.get("ticket")), _text(a.get("text"), "message")]


def _run_stop(a):
    _only(a, ("ticket",))
    return ["run", "stop", _tid(a.get("ticket"))], [], []


def _addon_start(a):
    _only(a, ())
    return ["start"], ["--no-open"], []


# Never in an add-on target: C0/C1 controls, line separators, bidi overrides, isolates and marks, zero-width
# characters. They can disguise a path or an address in an error or a sign step's review.
HIDDEN_CHARS = re.compile("[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]")


def _act_target(v) -> str:
    """What an add-on verb acts on: a ticket id, or one plain value the add-on checks itself (a sync address, a file
    of a ticket, `<ticket>:<add-on>`): one line, no control, bidi or zero-width character, never starting with "-".
    It always goes after `--`, so it can never be read as an option."""
    if isinstance(v, str) and TID.fullmatch(v):
        return v
    if (
        not isinstance(v, str)
        or not v.strip()
        or len(v) > 500
        or v.startswith("-")
        or v != v.strip()
        or HIDDEN_CHARS.search(v)
    ):
        raise BadRequest("That is not something this action can work on.")
    return _text(v, "target", limit=500)


def _addon_act(a):
    """ONE generic op for an add-on's own verbs: `orch <addon> act <verb> -- <target>`. The add-on name is checked
    against `orch addon list` in run_op (it must be on here); the dashboard code never names one. `sign` = the
    person signed this click on the page. Two phases (see addon_proof_target): `review: true` only asks the add-on
    for {target, review} (nothing runs) and the page shows that review; the signed click echoes the target it
    showed (`seen`), and run_op mints a proof only when the add-on still names exactly that target."""
    _only(a, ("addon", "verb", "target", "value", "sign", "review", "seen"))
    addon, verb = a.get("addon"), a.get("verb")
    if not (isinstance(addon, str) and ADDON.fullmatch(addon) and addon not in RESERVED):
        raise BadRequest("That is not an add-on.")
    if not (isinstance(verb, str) and VERB.fullmatch(verb)):
        raise BadRequest("That action is not available.")
    if "sign" in a and a["sign"] is not True:
        raise BadRequest("A signed click says sign: true.")
    if "review" in a and (a["review"] is not True or "sign" in a):
        raise BadRequest("A review asks review: true and signs nothing.")
    if "sign" in a and "seen" not in a:
        raise BadRequest("Sign what you saw: open it again.")
    if "seen" in a and ("sign" not in a or not (a["seen"] is None or isinstance(a["seen"], str))):
        raise BadRequest("Sign what you saw: open it again.")
    flags = []
    if "value" in a:
        if verb == "set":  # a setting's value: a whole number (sync: every 5, 15 or 60 minutes)
            if not (isinstance(a["value"], str) and re.fullmatch(r"[0-9]{1,4}", a["value"])):
                raise BadRequest("Set takes a whole number.")
            value = a["value"]
        else:
            value = _text(a["value"], "time")
            if verb != "repeat" or len(value) > 200:
                raise BadRequest("Only repeat takes a time, at most 200 characters.")
        flags.append(f"--value={value}")
    return [addon, "act", verb], flags, [_act_target(a.get("target"))]


PROOF_TARGET = re.compile(r"[a-z][a-z0-9-]{1,31}:[A-Za-z0-9_.:@/+=-]{1,400}")


REVIEW_KEYS = ("title", "body", "here", "there", "value")


def _review(v) -> dict | None:
    """The add-on's review of a signed click (what the person signs), as plain text lines only."""
    if not isinstance(v, dict):
        return None
    out = {k: v[k][:4000] for k in REVIEW_KEYS if isinstance(v.get(k), str) and v[k]}
    return out if out.get("title") else None


def addon_proof_target(
    root: Path, orch_bin: str, argv: list[str], addon: str
) -> tuple[str | None, dict | None]:
    """Which proof a signed add-on click needs and what the person is shown: `orch <addon> act <verb> --proof-target
    ... -- <target>` answers {"target": "<addon>:..." | null, "review": {title, body, here, there, value}}, both from
    the same bytes, and changes nothing. Only a target under the add-on's own name is minted, and only for the core
    op `addon.act` (a proof that only that add-on's own CLI checks); anything else is refused before a proof
    exists."""
    i = argv.index("--") if "--" in argv else len(argv)
    try:
        r = _run(
            [*argv0(orch_bin), *argv[:i], "--proof-target", *argv[i:]],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            env=human_env(root, orch_bin),
        )
        out = json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        raise BadRequest("That took too long. Please try again.") from None
    except (OSError, ValueError):
        out = None
    if not isinstance(out, dict) or r.returncode != 0 or "target" not in out:
        err = out.get("error") if isinstance(out, dict) else None
        raise BadRequest(str(err or "This can't be signed right now. Nothing was changed.")[:300])
    target, review = out["target"], _review(out.get("review"))
    if target is None:
        return None, review
    if not (isinstance(target, str) and PROOF_TARGET.fullmatch(target) and target.startswith(addon + ":")):
        raise BadRequest("This can't be signed right now. Nothing was changed.")
    return target, review


def _agent_name(v) -> str:
    if not (isinstance(v, str) and AGENT.fullmatch(v)):
        raise BadRequest("That is not an agent name (lowercase letters, digits and -).")
    return v


def _config_agent(a):
    """Choose the default agent: `orch config set workspace.agent <name>`; orch refuses a name nobody knows."""
    _only(a, ("name",))
    return ["config", "set", "workspace.agent", _agent_name(a.get("name"))], [], []


def _config_permissions(a):
    """How much an agent may do without asking: `orch config set workspace.permissions <ask|auto|full>`."""
    _only(a, ("mode", "confirm"))
    mode = a.get("mode")
    if mode not in PERMISSIONS:
        raise BadRequest("Pick Ask, Auto or Full.")
    if mode == "full" and a.get("confirm") is not True:
        raise BadRequest(
            "Full needs a Yes first: the agent will never ask."
        )  # the page sends confirm only after its Yes/No dialog
    if a.get("confirm") not in (None, True, False):
        raise BadRequest("A yes/no value must be true or false.")
    return ["config", "set", "workspace.permissions", mode], [], []


def _share_set(a):
    """Share with team: `orch share on|off` (AGENTS.md entry + merge=union; off removes both)."""
    _only(a, ("on",))
    if not isinstance(a.get("on"), bool):
        raise BadRequest("Say on or off.")
    return ["share", "on" if a["on"] else "off"], [], []


def _private_move(a):
    _only(a, ())
    return ["private", "move"], [], []


def _private_allow(a):
    """Allow ONE settings command, bound to what the person saw: the name and the key (hash) of the entry."""
    _only(a, ("name", "key"))
    if not (isinstance(a.get("name"), str) and re.fullmatch(r"[a-z][a-z0-9-]{0,31}", a["name"])):
        raise BadRequest("Pick the agent.")
    if not (isinstance(a.get("key"), str) and re.fullmatch(r"[0-9a-f]{64}", a["key"])):
        raise BadRequest("Look at the command again.")
    return ["private", "allow", a["name"], "--key", a["key"]], [], []


def _config_agent_test(a):
    """Try an agent: `orch agents test <name> --json` answers {name, ok, reason}. Changes nothing, so no --by."""
    _only(a, ("name",))
    return ["agents", "test", _agent_name(a.get("name"))], [], []


def _config_agent_add(a):
    """Add 'your own agent': `orch config agent add <name> --command=<one line>`. The command is ONE argv value
    (`--command=...`), so it can never be read as another option or run through a shell by the dashboard."""
    _only(a, ("name", "command", "prompt_via"))
    cmd = a.get("command")
    if not (
        isinstance(cmd, str)
        and 1 <= len(cmd) <= MAX_COMMAND
        and cmd.strip()
        and "\n" not in cmd
        and "\r" not in cmd
        and "\x00" not in cmd
    ):
        raise BadRequest(f"The command must be one line of at most {MAX_COMMAND} characters.")
    flags = [f"--command={cmd}"]
    via = a.get("prompt_via")
    if via is not None:
        if via not in ("arg", "stdin"):
            raise BadRequest("The task goes in as an argument or on stdin.")
        flags.append(f"--prompt-via={via}")
    return ["config", "agent", "add", _agent_name(a.get("name"))], flags, []


def _addon_set(a):
    """Turn an add-on on or off here: `orch addon add <name> --yes` / `orch addon remove <name>`. The name must be
    in `orch addon list` (checked in run_op); the dashboard cannot be turned off from itself."""
    _only(a, ("name", "on"))
    name = a.get("name")
    if not (isinstance(name, str) and ADDON.fullmatch(name) and name not in RESERVED):
        raise BadRequest("That is not an add-on.")
    if not isinstance(a.get("on"), bool):
        raise BadRequest("Say on or off.")
    return (["addon", "add", name], ["--yes"], []) if a["on"] else (["addon", "remove", name], [], [])


def _link(a, extend=False):
    _only(a, ("id", "days") if extend else ("id",))
    fid = a.get("id")
    if not isinstance(fid, str) or not re.fullmatch(r"f_[a-z0-9]+", fid):
        raise BadRequest("That is not a shared file id.")
    if extend and (type(a.get("days")) is not int or not 1 <= a["days"] <= 90):
        raise BadRequest("Choose a whole number of days from 1 to 90.")
    return (
        ["publish", "extend" if extend else "delete", fid],
        (["--days", str(a["days"])] if extend else []),
        [],
    )


# op -> function(args) -> (words incl. ids, flags, free text after "--")
OPS = {
    "link.extend": lambda a: _link(a, True),
    "link.stop": _link,
    "answer": _answer,
    "ticket.new": _ticket_new,
    "ticket.paste": _ticket_paste,
    "ticket.attach": _ticket_attach,
    "ticket.patch": _ticket_patch,
    "ticket.changes": _ticket_changes,
    "ticket.edit": _ticket_edit,
    "log": _log,
    "chat.say": _chat_say,
    "chat.make_ticket": _chat_make_ticket,
    "check.add": _check_add,
    "check.set": _check_set,
    "check.wont_do": _check_wont_do,
    "check.reopen": _check_reopen,
    "check.edit": _check_edit,
    "check.remove": _check_remove,
    "run.start": _run_start,
    "run.stop": _run_stop,
    "run.send": _run_send,
    "addon.start": _addon_start,
    "addon.act": _addon_act,
    "config.agent": _config_agent,
    "config.agent.add": _config_agent_add,
    "config.agent.test": _config_agent_test,
    "config.permissions": _config_permissions,
    "addon.set": _addon_set,
    "share.set": _share_set,
    "private.move": _private_move,
    "private.allow": _private_allow,
    **MOBILE_OPS,
    **LOOK_OPS,
    "ref.add": _ref_add,
    "ref.rm": _ref_rm,
    "workflow.set": _workflow_set,
    "copies.set": _copies_set,
    "copies.clean": _copies_clean,
    "copies.remove_orphaned": _copies_remove_orphaned,
    "copies.retry": _copies_retry,
    "copies.approve": _copies_approve,
    "copies.ask-update": _copies_ask_update,
    "ticket.field": _ticket_field,
}


def actor() -> str:
    try:
        who = re.sub(r"[^A-Za-z0-9_.@ -]", "_", getpass.getuser())[:64]
    except (OSError, KeyError, ImportError):
        who = ""
    return f"human:{who or 'dashboard'}"


def build_argv(op, args) -> list[str]:
    """The argv after the orch command, for one op. Raises BadRequest for anything outside the table."""
    fn = OPS.get(op) if isinstance(op, str) else None
    if fn is None:
        raise BadRequest("That action is not available.")
    if not isinstance(args, dict):
        raise BadRequest("The arguments must be an object.")
    words, flags, tail = fn(args)
    if op == "config.agent.test":
        return [*words, "--json"]
    return [*words, *flags, "--by", actor(), "--json", *(["--", *tail] if tail else [])]


def _addon_is_on(root: Path, orch_bin: str, name: str) -> bool:
    rows = run_orch(orch_bin, ["addon", "list", "--json"], root)
    return any(
        isinstance(r, dict) and r.get("name") == name and r.get("active") is True
        for r in (rows if isinstance(rows, list) else [])
    )


def _addon_known(root: Path, orch_bin: str, name: str) -> bool:
    rows = run_orch(orch_bin, ["addon", "list", "--json"], root)
    return any(
        isinstance(r, dict) and r.get("name") == name for r in (rows if isinstance(rows, list) else [])
    )


def _agent_exists(root: Path, orch_bin: str, name: str) -> bool:
    """Fails closed: when the list cannot be read, the name counts as taken (core refuses an existing name too)."""
    rows = run_orch(orch_bin, ["agents", "--json"], root)
    if not isinstance(rows, list):
        return True
    return any(
        isinstance(r, dict) and r.get("name") == name for r in (rows if isinstance(rows, list) else [])
    )


def _audit(root: Path, op: str, args: dict) -> None:
    """One line per settings change in .orch/run/dashboard/actions.log (local, gitignored): who, what, the exact command."""
    keep = {
        k: v for k, v in args.items() if k in ("name", "command", "prompt_via", "on", "mode", "id", "days")
    }
    line = json.dumps(
        {
            "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "by": actor(),
            "via": "dashboard",
            "op": op,
            **keep,
        },
        ensure_ascii=False,
    )
    try:
        # .orch/run/dashboard (0700), no symlink at any level, the file opened with O_NOFOLLOW (0600)
        with runfiles.open_append(runfiles.run_dir(root, "dashboard") / "actions.log") as f:
            f.write(line + "\n")
    except (OSError, RuntimeError):
        pass  # the change is done; a missing log must not turn it into an error


def _without_agent(environ) -> dict:
    """environ without the agent tools' variables, from orch's one list (orch.adapters.human_environ). When
    that list can not be read, the action is refused: it never runs with an agent's variables (fail closed)."""
    try:
        from orch.adapters import human_environ

        return human_environ(environ)
    except Exception as e:  # noqa: BLE001 - an old orch or a bad adapter file
        import sys
        import traceback

        print("orch could not check who is acting here:", file=sys.stderr)  # the full text: server side only
        traceback.print_exc(file=sys.stderr)
        fn = getattr(e, "filename", None)
        where = Path(fn).name if isinstance(fn, str) and fn else ""  # never a full path or file content
        why = e.__class__.__name__ + (f" in {where}" if where else "")
        raise Unavailable(
            f"orch could not check who is acting here ({why}). Fix that and try again."
        ) from None


def _attach_all(root: Path, orch_bin: str, tid: str, files: list[tuple[str, bytes]]) -> dict:
    """Keep each file with the new ticket through `orch ticket attach` (orch picks the name and checks type,
    content and size). A file that is refused does not undo the ticket: it is listed as failed."""
    saved, failed = [], []
    for hint, raw in files:
        try:
            r = _run(
                [*argv0(orch_bin), "ticket", "attach", tid, f"--name={hint}", "--by", actor(), "--json"],
                check=False,
                cwd=root,
                capture_output=True,
                input=raw,
                timeout=60,
                env=human_env(root, orch_bin),
            )
            out = json.loads(r.stdout.decode("utf-8", "replace")) if r.returncode == 0 else None
        except (subprocess.TimeoutExpired, OSError, ValueError):
            out = None
        if isinstance(out, dict) and isinstance(out.get("name"), str):
            saved.append(out["name"])
        else:
            failed.append(re.sub(r"[^A-Za-z0-9._ -]", "_", hint.rsplit("/", 1)[-1])[:60])
    return {"saved": saved, "failed": failed}


def human_env(root: Path, orch_bin: str) -> dict:
    """Browser actions are the person's actions, even if an agent launched the server."""
    try:
        import orch.adapters  # noqa: F401
    except ImportError:
        raise Unavailable("The orch tool is not available here.") from None
    env = _without_agent(os.environ)
    from orch.pageproof import child_env

    return child_env({**env, "ORCH_ROOT": str(root), "ORCH_VIA": "dashboard"}, orch_bin)


SHARE_MAX = (
    3 * 1024 * 1024
)  # raw bytes of a file picked in the browser (the request body is capped at 5 MB as base64)


def _sweep_shares(parent: Path, older_than: float = 600.0) -> None:
    """Remove copies a crashed share left behind (folders s-* older than 10 minutes, inside the share folder)."""
    now = time.time()
    for d in parent.glob("s-*"):
        try:
            if d.is_dir() and not d.is_symlink() and now - d.stat().st_mtime > older_than:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            continue


def share_file(root: Path, orch_bin: str | None, args, mint=None) -> tuple[int, str, dict | None]:
    """Share a file picked in the browser: `orch publish file` on a private copy under .orch/run/share, removed
    right after. The link (which holds the key) never goes back to the page: the list shows the new row."""
    if not isinstance(args, dict) or set(args) - {"name", "data", "days"}:
        raise BadRequest("That file could not be read.")
    name = args.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 240 or "\x00" in name:
        raise BadRequest("That file name is not allowed.")
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", name.replace("\\", "/").rsplit("/", 1)[-1]).lstrip(".")[:120]
    if not base:
        raise BadRequest("That file name is not allowed.")
    days = args.get("days", 7)
    if type(days) is not int or not 1 <= days <= 90:
        raise BadRequest("Choose a whole number of days from 1 to 90.")
    try:
        raw = base64.b64decode(args.get("data") or "", validate=True)
    except (ValueError, TypeError):
        raise BadRequest("That file could not be read.") from None
    if not raw:
        raise BadRequest("That file is empty.")
    if len(raw) > SHARE_MAX:
        raise BadRequest("That file is over 3 MB. Share bigger files with `orch publish file` in a terminal.")
    if not orch_bin:
        raise Unavailable("The orch command is not available here.")
    if orch_bin == SELF and mint is None:
        raise NeedsPerson("Open the dashboard from this computer to do this.")
    if not publish_connected(root, orch_bin):
        raise BadRequest("Sharing is not set up here.")
    try:  # no link at any level, 0700; anything else fails closed in plain words
        parent = runfiles.run_dir(root, "share")
        _sweep_shares(parent)
        folder = Path(tempfile.mkdtemp(prefix="s-", dir=parent))
    except (RuntimeError, OSError):
        raise BadRequest("This folder can't be used to share a file right now.") from None
    try:
        os.chmod(folder, 0o700)
        path = folder / base
        path.write_bytes(raw)
        os.chmod(path, 0o600)
        r = _run(
            [*argv0(orch_bin), "publish", "file", str(path), "--days", str(days), "--json"],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
            stdin=subprocess.DEVNULL,
            env=human_env(root, orch_bin),
        )
    except subprocess.TimeoutExpired:
        return 504, "That took too long. Please try again.", None
    except OSError:
        raise Unavailable("The orch command could not be started.") from None
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    try:
        out = json.loads(r.stdout)
    except ValueError:
        out = None
    if r.returncode == 0 and isinstance(out, dict):
        _audit(root, "link.share", {"id": out.get("id"), "days": days})
        return 200, "", {"id": out.get("id"), "name": out.get("name")}
    msg = out.get("error") if isinstance(out, dict) else None
    if not msg:
        msg = (r.stderr.strip().splitlines() or ["That did not work."])[0].removeprefix("Refused: ")
    return 422, str(msg)[:500], None


def run_op(root: Path, orch_bin: str | None, op, args, mint=None) -> tuple[int, str, dict | None]:
    """Run one op. Returns (http status, plain text, parsed json or None). `mint(core op, target)` gives an hp1
    proof for a request that carries a page session; None = watch-only (the click is refused)."""
    if op == "link.share":
        return share_file(root, orch_bin, args, mint)
    argv = build_argv(op, args)
    if orch_bin == SELF and needs_session(op) and mint is None:  # before anything is read, hashed or run (F8)
        raise NeedsPerson("Open the dashboard from this computer to do this.")
    need = (
        proof_for(op, args, root) if orch_bin == SELF else None
    )  # a test fake (explicit ORCH_BIN) needs none
    files = attachments(op, args)
    forget_static()  # a change may alter what the cached read-only answers say
    if not orch_bin:
        raise Unavailable("The orch command is not available here.")
    if op in ("link.extend", "link.stop") and not publish_connected(root, orch_bin):
        raise BadRequest("Sharing is not set up here.")
    if op in MOBILE_REQUIRED_ADDONS and not _addon_is_on(root, orch_bin, MOBILE_REQUIRED_ADDONS[op]):
        raise BadRequest("That add-on is not on in this workspace.")
    if op in ("addon.act", "ticket.field") and not _addon_is_on(root, orch_bin, args["addon"]):
        raise BadRequest("That add-on is not on in this workspace.")
    if op == "addon.set" and not _addon_known(root, orch_bin, args["name"]):
        raise BadRequest("That add-on is not installed.")
    if op == "config.agent.test" and not _agent_exists(root, orch_bin, args["name"]):
        raise BadRequest("That agent is not set up.")
    if op == "config.agent.add" and _agent_exists(root, orch_bin, args["name"]):
        raise BadRequest(
            "An agent with that name is already set up. Pick another name (changing one is done in the terminal)."
        )
    if op == "addon.act" and args.get("review") is True:
        # phase 1: what the person will sign; nothing runs (with any orch, a test fake too)
        target, review = addon_proof_target(root, orch_bin, argv, args["addon"])
        if review is None:
            raise BadRequest("This can't be signed right now. Nothing was changed.")
        return 200, "", {"target": target, "review": review}
    if op == "addon.act" and args.get("sign") is True and orch_bin == SELF:
        target, _ = addon_proof_target(
            root, orch_bin, argv, args["addon"]
        )  # a click with a session only (above)
        if target != args.get("seen"):  # phase 2: only what the page showed is minted
            raise BadRequest("This changed after you opened it. Nothing was changed; open it again.")
        need = ("addon.act", target) if target else None
    if need and mint is None:  # a request without the page secret: a plain refusal, never a crash
        raise NeedsPerson("Open the dashboard from this computer to do this.")
    try:
        if need:
            r = run_with_proof(
                argv, mint(*need), orch_bin=orch_bin, cwd=root, env=human_env(root, orch_bin), timeout=60
            )
        else:
            r = _run(
                [*argv0(orch_bin), *argv],
                check=False,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=75 if op == "config.agent.test" else 60,
                stdin=subprocess.DEVNULL,
                env=human_env(root, orch_bin),
            )
    except subprocess.TimeoutExpired:
        return 504, "That took too long. Please try again.", None
    except OSError:
        raise Unavailable("The orch command could not be started.") from None
    out = None
    try:
        out = json.loads(r.stdout)
    except ValueError:
        pass
    if op == "config.agent.test" and isinstance(out, dict) and isinstance(out.get("ok"), bool):
        return (
            200,
            "",
            out,
        )  # `orch agents test` exits 1 when the agent does not work; the JSON is the answer either way
    if r.returncode == 0:
        if op.startswith("look."):
            look_forget(root)
        if op in (
            "link.extend",
            "link.stop",
            "config.agent.add",
            "addon.set",
            "config.agent",
            "config.permissions",
            "workflow.set",
            "copies.set",
            "copies.clean",
            "copies.remove_orphaned",
            "copies.retry",
            "share.set",
            "private.move",
            "private.allow",
        ):
            _audit(root, op, args)
        if op in ("copies.clean", "copies.remove_orphaned", "copies.retry"):
            from . import data as _data

            _data.copies_disk_forget(root)
        if files and op == "ticket.attach":
            out = {**(out if isinstance(out, dict) else {}), "id": args["ticket"]}
        if files and isinstance(out, dict) and isinstance(out.get("id"), str) and TID.fullmatch(out["id"]):
            out["attached"] = _attach_all(root, orch_bin, out["id"], files)
        return 200, "", out if isinstance(out, dict) else None
    msg = out.get("error") if isinstance(out, dict) else None
    if not msg:
        msg = (r.stderr.strip().splitlines() or ["That did not work."])[0].removeprefix("Refused: ")
    conflict = isinstance(out, dict) and "revision" in out and "changed_by" in out
    return (409 if conflict else 422), str(msg)[:500], out if conflict else None


# Workspace direct messages: a separate operation from phone/group chat.
def _chat_send_ws(a):
    _only(a, ("workspace", "text", "retry", "client_id"))
    ws = a.get("workspace")
    if not isinstance(ws, str) or not re.fullmatch(r"ws_[a-z0-9]{10}", ws):
        raise BadRequest("That is not a workspace.")
    text = _text(a.get("text"))
    if len(text) > 2000:
        raise BadRequest("A message has 1 to 2000 characters.")
    retry = a.get("retry")
    if retry is not None and (not isinstance(retry, str) or not re.fullmatch(r"m_[a-z0-9]{16}", retry)):
        raise BadRequest("That is not a message.")
    client_id = a.get("client_id")
    if client_id is not None and (
        not isinstance(client_id, str) or not re.fullmatch(r"m_[a-z0-9]{16}", client_id)
    ):
        raise BadRequest("That is not a message.")
    flags = (["--retry", retry] if retry else []) + (["--client-id", client_id] if client_id else [])
    return ["chat", "send", ws], flags, [text]


def _chat_sync_ws(a):
    _only(a, ("workspace",))
    if "workspace" not in a:
        return ["chat", "sync"], [], []
    ws = a.get("workspace")
    if not isinstance(ws, str) or not re.fullmatch(r"ws_[a-z0-9]{10}", ws):
        raise BadRequest("That is not a workspace.")
    return ["chat", "sync", ws], [], []


OPS["chat.send_ws"] = _chat_send_ws

OPS["chat.sync_ws"] = _chat_sync_ws

"""What Focus may do: one fixed table of ops, each building exactly one `orch` argv (own copy of the dashboard pattern).

No shell. Ids are checked by regex, text is limited to 2000 characters, free text always goes after `--`.
Focus starts, messages and stops agents only through `orch run start|send|stop`; it never builds a tool command.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import re
import subprocess
from pathlib import Path

_run = subprocess.run  # tests patch this name, never the global subprocess.run (other threads use that)

MAX_TEXT = 2000
MAX_TASK = 500
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
TID = re.compile(r"t_[a-z0-9]{6,16}")
QID = re.compile(r"q[0-9]{1,4}")
CID = re.compile(r"c[0-9]{1,4}")
PID = re.compile(r"p_[a-z0-9]{6,32}")


class BadRequest(Exception):
    """The request does not match the op table (HTTP 400)."""


class Unavailable(Exception):
    """No orch command to run (HTTP 503)."""


class NeedsPerson(Exception):
    """A human-only click without a page session (HTTP 403): the page is watch-only here."""


try:
    from orch.pagesession import SELF, argv0, child_env
except ImportError:  # no orch: nothing runs
    SELF = "orch:self"

    def argv0(orch_bin):
        return [str(orch_bin)]

    def child_env(env, orch_bin):
        return {**env, "ORCH_BIN": orch_bin}


# What any scripted request may do without a page session: add or move a task (an agent does the same through
# the CLI as itself), and, KNOWN GAP (follow-up), start/stop a run and the phone switch: an embedded Focus page
# (under the dashboard, no session of its own) keeps its started-run bookkeeping in Focus, so these three stay
# open until that has a session path. Every other op acts as the person and needs the page session (watch-only
# without one).
FREE_OPS = frozenset({"check.add", "check.move", "run.start", "run.stop", "mobile.set"})


def needs_session(op) -> bool:
    return isinstance(op, str) and op not in FREE_OPS


def _id(rx: re.Pattern, v, what: str) -> str:
    if not isinstance(v, str) or not rx.fullmatch(v):
        raise BadRequest(f"That is not a {what} id.")
    return v


def _text(v, name="text") -> str:
    if not isinstance(v, str) or not v.strip():
        raise BadRequest(f"Please write the {name}.")
    if len(v) > MAX_TEXT:
        raise BadRequest(f"The {name} is too long (at most {MAX_TEXT} characters).")
    if "\x00" in v:
        raise BadRequest(f"The {name} has a character that is not allowed.")
    v = _CONTROL.sub("", v)  # other control characters (escape codes, DEL) are dropped; \n and \t stay
    if not v.strip():
        raise BadRequest(f"Please write the {name}.")
    return v


def _rev(v):
    if v is None:
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


def _t(a):
    return _id(TID, a.get("ticket"), "ticket")


def _question_digest(a):
    """The digest of the question as the page showed it (sent back with the answer): no digest, no answer."""
    d = a.get("digest")
    if not (isinstance(d, str) and re.fullmatch(r"[0-9a-f]{64}", d)):
        raise BadRequest("This question changed or can't be checked. Ask again.")
    return d


def _answer(a):
    _only(a, ("ticket", "question", "answer", "digest"))
    return (
        ["answer", _t(a), _id(QID, a.get("question"), "question")],
        ["--via", "focus", "--question-digest", _question_digest(a)],
        [_text(a.get("answer"), "answer")],
    )


def _run_start(a):
    _only(a, ("ticket", "fresh"))
    return ["run", "start", _t(a)], (["--fresh"] if _flag(a.get("fresh")) else []), []


def _run_stop(a):
    _only(a, ("ticket",))
    return ["run", "stop", _t(a)], [], []


def _run_send(a):
    _only(a, ("ticket", "text"))
    # The ticket goes AFTER the options, with the text: `run send` has an optional text, and some Python versions
    # (3.11, early 3.12) let `send <ticket>` swallow it, then fail on `-- <text>` with "unrecognized arguments".
    return ["run", "send"], [], [_t(a), _text(a.get("text"), "message")]


def _run_take_back(a):
    """Take back one waiting message: `orch run take-back <ticket> <id>`; the answer carries its text."""
    _only(a, ("ticket", "id"))
    return ["run", "take-back", _t(a), _id(PID, a.get("id"), "message")], [], []


def _check_add(a):
    """Add a task: `orch check add <ticket> -- <text>` (text up to 500 characters)."""
    _only(a, ("ticket", "text"))
    text = _text(a.get("text"), "task").strip()
    if len(text) > MAX_TASK:
        raise BadRequest(f"The task is too long (at most {MAX_TASK} characters).")
    return ["check", "add", _t(a)], [], [text]


def _check(a, extra=()):
    _only(a, ("ticket", "check", *extra))
    return _t(a), _id(CID, a.get("check"), "task")


def _check_edit(a):
    t, c = _check(a, ("text", "if_revision", "was"))
    flags = []
    if (rev := _rev(a.get("if_revision"))) is not None:
        flags.append(f"--if-revision={rev}")
    if a.get("was") is not None:
        flags.append(f"--was={_text(a['was'], 'old text')}")
    return ["check", "edit", t, c], flags, [_text(a.get("text"))]  # the new text goes after `--`


def _check_wont_do(a):
    t, c = _check(a, ("reason",))
    flags = []
    if "reason" in a:
        reason = a["reason"]
        if (
            not isinstance(reason, str)
            or len(reason) > 200
            or any(ch in reason for ch in "\r\n")
            or _CONTROL.search(reason)
        ):
            raise BadRequest("The reason must be one line, at most 200 characters.")
        flags.append(f"--reason={reason}")
    return ["check", "wont-do", t, c], flags, []


def _check_move(a):
    t, c = _check(a, ("after",))
    return ["check", "move", t, c], [f"--after={_id(CID, a.get('after'), 'task')}"], []


def _check_plain(name):
    def fn(a):
        t, c = _check(a)
        return ["check", name, t, c], [], []

    return fn


def _ticket_done(a):
    _only(a, ("ticket", "if_revision"))
    rev = _rev(a.get("if_revision"))
    if rev is None:
        raise BadRequest("The ticket revision is required.")
    return ["ticket", "patch", _t(a)], [f"--if-revision={rev}"], [json.dumps({"status": "done"})]


def _mobile_set(a):
    _only(a, ("on",))
    if not isinstance(a.get("on"), bool):
        raise BadRequest("Say on or off.")
    return ["relay", "mobile", "on" if a["on"] else "off"], [], []


# Files added to a ticket: the same limits as the composer (web/compose.js) and orch itself (orch decides).
ATTACH_EXT = frozenset(
    [
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
    ]
)
ATTACH_MAX = 25 * 1024 * 1024
ATTACH_FILES = 5


def attachments(op, args) -> list[tuple[str, bytes]]:
    """The files of a `ticket.attach` request as (name hint, bytes), all checked before anything is run.
    One plain sentence on every failure; orch checks type, content and size again."""
    if op != "ticket.attach" or not isinstance(args, dict):
        return []
    files = args.get("files")
    if not isinstance(files, list) or not files:
        raise BadRequest("Choose a file to add.")
    if len(files) > ATTACH_FILES:
        raise BadRequest(f"You can add up to {ATTACH_FILES} files at a time.")
    out: list[tuple[str, bytes]] = []
    for f in files:
        if not isinstance(f, dict) or set(f) - {"name", "data"} or not isinstance(f.get("name"), str):
            raise BadRequest("That file could not be read. Choose it again.")
        name = f["name"]
        if not name.strip() or len(name) > 240 or _CONTROL.search(name):
            raise BadRequest("That file name is not allowed. Rename the file and choose it again.")
        try:
            raw = base64.b64decode(f.get("data") or "", validate=True)
        except (ValueError, TypeError):
            raise BadRequest(f"{name[:60]} could not be read. Choose it again.") from None
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in ATTACH_EXT:
            raise BadRequest(f"{name[:60]}: only text files and pictures can be added.")
        if len(raw) > ATTACH_MAX:
            raise BadRequest(f"{name[:60]} is over 25 MB. Choose a smaller file.")
        out.append((name, raw))
    return out


def _ticket_attach(a):
    """One quiet line in the history; the files go through `orch ticket attach` after it (see run_op)."""
    _only(a, ("ticket", "files"))
    return ["log", _t(a)], [], ["Added files to the ticket"]


OPS = {
    "ticket.attach": _ticket_attach,
    "mobile.set": _mobile_set,
    "ticket.done": _ticket_done,
    "answer": _answer,
    "run.start": _run_start,
    "run.stop": _run_stop,
    "run.send": _run_send,
    "run.take_back": _run_take_back,
    "check.add": _check_add,
    "check.edit": _check_edit,
    "check.wont_do": _check_wont_do,
    "check.move": _check_move,
    "check.remove": _check_plain("remove"),
    "check.reopen": _check_plain("reopen"),
}
BY = {
    "run.start": "focus",
    "mobile.set": "focus",
}  # who a start is recorded as (the page is the starter); other ops: the person


def actor() -> str:
    try:
        who = re.sub(r"[^A-Za-z0-9_.@ -]", "_", getpass.getuser())[:64]
    except (OSError, KeyError, ImportError):
        who = ""
    return f"human:{who or 'focus'}"


def build_argv(op, args) -> list[str]:
    """The argv after the orch command, for one op. Raises BadRequest for anything outside the table."""
    fn = OPS.get(op) if isinstance(op, str) else None
    if fn is None:
        raise BadRequest("That action is not available.")
    if not isinstance(args, dict):
        raise BadRequest("The arguments must be an object.")
    words, flags, tail = fn(args)
    return [*words, *flags, "--by", BY.get(op) or actor(), "--json", *(["--", *tail] if tail else [])]


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


def human_env(root: Path, orch_bin: str) -> dict:
    """Page actions are the person's actions, even if an agent launched the server: the agent tools' own
    variables (and ORCH_AGENT/RUN/TICKET) are left out, or orch would count the click as the agent's."""
    return child_env({**_without_agent(os.environ), "ORCH_ROOT": str(root), "ORCH_VIA": "focus"}, orch_bin)


def orch(root: Path, orch_bin: str | None, argv: list[str], timeout: int = 60) -> tuple[int, str, str]:
    if not orch_bin:
        raise Unavailable("The orch command is not available here.")
    try:
        r = _run(
            [*argv0(orch_bin), *argv], check=False, cwd=root, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL, env=human_env(root, orch_bin),
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return 124, "", "That took too long. Please try again."
    except OSError:
        raise Unavailable("The orch command could not be started.") from None
    return r.returncode, r.stdout, r.stderr


def _attach_all(root: Path, orch_bin: str | None, tid: str, files: list[tuple[str, bytes]]) -> dict:
    """Keep each file with the ticket through `orch ticket attach` (orch picks the name and checks type, content and
    size). A refused file is listed as failed by its (cleaned) name."""
    saved, failed = [], []
    for hint, raw in files:
        try:
            r = _run(
                [*argv0(orch_bin), "ticket", "attach", tid, f"--name={hint}", "--by", actor(), "--json"],
                check=False, cwd=root, capture_output=True, input=raw, timeout=60, env=human_env(root, orch_bin),
            )  # fmt: skip
            out = json.loads(r.stdout.decode("utf-8", "replace")) if r.returncode == 0 else None
        except (subprocess.TimeoutExpired, OSError, ValueError):
            out = None
        if isinstance(out, dict) and isinstance(out.get("name"), str):
            saved.append(out["name"])
        else:
            failed.append(re.sub(r"[^A-Za-z0-9._ -]", "_", hint.rsplit("/", 1)[-1])[:60])
    return {"saved": saved, "failed": failed}


def run_op(root: Path, orch_bin: str | None, op, args, session: bool = False) -> tuple[int, str, dict | None]:
    """Run one op. Returns (http status, plain text, parsed json or None)."""
    argv = build_argv(op, args)
    if orch_bin == SELF and needs_session(op) and not session:
        raise NeedsPerson("Open Focus from this computer (orch focus open) to do this.")
    files = attachments(op, args)  # checked before anything is written
    code, stdout, stderr = orch(root, orch_bin, argv)
    if code == 124:
        return 504, stderr, None
    out = None
    try:
        out = json.loads(stdout)
    except ValueError:
        pass
    if code == 0 and files:
        failed = _attach_all(root, orch_bin, args["ticket"], files)["failed"]
        if failed:
            names = ", ".join(failed[:3])
            return (
                422,
                f"{names} could not be added. Choose a text file or a picture up to 25 MB and try again.",
                None,
            )
    if code == 0:
        return 200, "", out if isinstance(out, dict) else None
    msg = out.get("error") if isinstance(out, dict) else None
    if not msg:
        msg = (stderr.strip().splitlines() or ["That did not work."])[0].removeprefix("Refused: ")
    conflict = isinstance(out, dict) and "revision" in out and "changed_by" in out
    return (409 if conflict else 422), str(msg)[:500], out if conflict else None

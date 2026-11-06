"""What Focus may do: one fixed table of ops, each building exactly one `orch` argv (own copy of the dashboard pattern).

No shell. Ids are checked by regex, text is limited to 2000 characters, free text always goes after `--`.
Focus starts, messages and stops agents only through `orch run start|send|stop`; it never builds a tool command.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
from pathlib import Path

MAX_TEXT = 2000
MAX_TASK = 500
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
TID = re.compile(r"t_[a-z0-9]{6,16}")
QID = re.compile(r"q[0-9]{1,4}")
CID = re.compile(r"c[0-9]{1,4}")


class BadRequest(Exception):
    """The request does not match the op table (HTTP 400)."""


class Unavailable(Exception):
    """No orch command to run (HTTP 503)."""


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


def _answer(a):
    _only(a, ("ticket", "question", "answer"))
    return (
        ["answer", _t(a), _id(QID, a.get("question"), "question")],
        ["--via", "focus"],
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
    return ["run", "send", _t(a)], [], [_text(a.get("text"), "message")]


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


def _check_move(a):
    t, c = _check(a, ("after",))
    return ["check", "move", t, c], [f"--after={_id(CID, a.get('after'), 'task')}"], []


def _check_plain(name):
    def fn(a):
        t, c = _check(a)
        return ["check", name, t, c], [], []

    return fn


OPS = {
    "answer": _answer,
    "run.start": _run_start,
    "run.stop": _run_stop,
    "run.send": _run_send,
    "check.add": _check_add,
    "check.edit": _check_edit,
    "check.move": _check_move,
    "check.remove": _check_plain("remove"),
    "check.reopen": _check_plain("reopen"),
}
BY = {"run.start": "focus"}  # who a start is recorded as (the page is the starter); other ops: the person


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


def orch(root: Path, orch_bin: str | None, argv: list[str], timeout: int = 60) -> tuple[int, str, str]:
    if not orch_bin:
        raise Unavailable("The orch command is not available here.")
    try:
        r = subprocess.run(
            [orch_bin, *argv], check=False, cwd=root, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL, env={**os.environ, "ORCH_ROOT": str(root), "ORCH_BIN": orch_bin},
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return 124, "", "That took too long. Please try again."
    except OSError:
        raise Unavailable("The orch command could not be started.") from None
    return r.returncode, r.stdout, r.stderr


def run_op(root: Path, orch_bin: str | None, op, args) -> tuple[int, str, dict | None]:
    """Run one op. Returns (http status, plain text, parsed json or None)."""
    argv = build_argv(op, args)
    code, stdout, stderr = orch(root, orch_bin, argv)
    if code == 124:
        return 504, stderr, None
    out = None
    try:
        out = json.loads(stdout)
    except ValueError:
        pass
    if code == 0:
        return 200, "", out if isinstance(out, dict) else None
    msg = out.get("error") if isinstance(out, dict) else None
    if not msg:
        msg = (stderr.strip().splitlines() or ["That did not work."])[0].removeprefix("Refused: ")
    conflict = isinstance(out, dict) and "revision" in out and "changed_by" in out
    return (409 if conflict else 422), str(msg)[:500], out if conflict else None

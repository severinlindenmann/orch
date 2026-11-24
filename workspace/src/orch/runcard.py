"""The "run this" card (ORCH-848). Owner, 19 Nov: "for future stuff that I have to do can we have a button
run it now".

A helper asks the person to run one command (`orch ask <id> "<question>" --run "<command>"`). The card shows
the exact command with Copy and Run it now; one click runs it for the signed-in person in the workspace
folder, shows what it printed and answers the card "I ran it" with that as proof. A failure leaves the card
open with the error.

Safety (plan challenged on 19 Nov, see the ticket's run-card-plan.md):
- Only a person runs it: the dashboard's signed-in page session hands the one `orch review run` call a
  one-time person grant (ownerpick.person_granted, as for Renew and drafts), or a paired phone through the
  relay. Never a helper, a script, `orch review answer`, the Reviewer, its second look, routine answers, the
  Auto Reviewer or Away mode: `review.decide` and `tickets.answer` refuse a yes on a run card for everyone
  else, so "I ran it" is only ever written here.
- The command shown is the command run: the whole spec (argv, resolved program, folder, class, policy
  version) is in the card, the card is in the question digest, and the click carries the digest it showed.
  The spec is parsed again at run time from the command text and must come out the same.
- orch commands are not a blank cheque: only the operations in CONFIG_OPS / _orch_op run, and orch writes
  what they change and how to undo them. Any other `orch ...` is refused when the card is made.
- Other commands (with one more confirm): one program, no shell, no interpreter with inline code, no sudo or
  env prefix, resolved to an absolute path in the system folders (never inside the workspace or a temp
  folder), a small fixed environment. The click must say `confirmed`.
- Sign-in commands (ORCH-865) never run here: Run it now opens the Focus plain terminal with the sign-in
  program started in a window of its own, directly (no shell, no typed line: `orch review signin` starts
  the resolved program on that terminal and waits for it). The card is answered only when that program
  ended with exit code 0 AND its login check, run after it, is green; an already-green check before the
  click answers nothing. Offered only when the sign-in has a login check and tmux runs here; otherwise the
  card shows Copy. Typing into the terminal stays the person's own switch (the card shows it when it is off).
- The phone runs only orch's own operations.
- Output: at most OUT_MAX bytes read, lines that look like a secret hidden, kept on this computer.
- Every attempt is logged (ticket history and .orch/logs/card-runs.jsonl).

This stops helpers, scripts and the Reviewer from running a command or answering in the person's place
through orch. It does not stop a program that attacks this computer as the same user (no OS boundary here).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from orch import agentsdata, history, procs
from orch.errors import Refused

POLICY = 1  # bump when the rules below change: a card made under older rules is refused at run time
COMMAND_MAX = 300
TIMEOUT = 120  # seconds
OUT_MAX = 64 * 1024  # bytes of output read; the rest is dropped
TAIL_LINES = 20  # lines of output shown on the card and given to the helper
SAFE_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")
# a sign-in program may also live where its own installer puts it (the helper tools' installers)
LOGIN_DIRS = (*SAFE_DIRS, "~/.local/bin", "~/.npm-global/bin")
SIGNIN_START = 5 * 60  # seconds the terminal has to start the sign-in after the click
SIGNIN_TIMEOUT = 15 * 60  # seconds a sign-in may take before it is stopped
SIGNIN_VIA = "terminal"
OK_LABEL = "I ran it"
# the card's other answer: orch's own words, one of these (never a helper's, which could look like "I ran it")
NO_LABELS = ("Not now", "Leave it off for now", "Leave it as it is", "Skip it", "Do it later")
PHONE_RUN = (
    True  # Run it now from a paired phone, orch's own operations only (the phone shows the card: ORCH-860)
)
UNCHECKED = "orch did not check this command. Read it before you run it in your terminal."

PERSON_REFUSAL = (
    "Only the signed-in person runs this: click Run it now on the card in the dashboard. "
    "No helper, script, Reviewer or Away mode runs it or answers I ran it."
)
OK_REFUSAL = "This card is answered by running it: click Run it now on the card. Only that answers I ran it."
CHANGED = "The card changed after you saw it. Look at it again, then run it."

_CONTROL = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")
_SHELL = set(";|&<>`$\\")
# The only non-orch commands a card runs (with the person's confirm): exact shapes, plain names, no flags.
# Every other command still gets a card, with Copy only: the person runs it in their own terminal.
# letters, digits and dashes, an @version at most: no tap (owner/name), no local file (x.rb, x.json)
_PKG = re.compile(r"^[a-z0-9][a-z0-9+_-]{0,60}(@[0-9][0-9.]{0,15})?$")
OTHER_OPS: dict[tuple[str, ...], int] = {
    ("brew", "install"): 1,
    ("brew", "uninstall"): 1,
    ("brew", "upgrade"): 1,
}
NAMES_MAX = 5  # plain names after the shape; the number is the fewest it needs


def _other_op(argv: list[str]) -> bool:
    """True when the command is one of OTHER_OPS followed by plain names only (no flags, no paths)."""
    for shape, least in OTHER_OPS.items():
        names = argv[len(shape) :]
        if tuple(argv[: len(shape)]) == shape and least <= len(names) <= NAMES_MAX:
            return all(_PKG.fullmatch(n) for n in names)
    return False


# Sign-in commands a card may type into the Focus terminal. Helper tools' own ones come from the built-in
# adapter data (agents/login.json "card"), never from a workspace override.
LOGINS = (
    ("gh", "auth", "login"), ("gh", "auth", "refresh"), ("az", "login"), ("gcloud", "auth", "login"),
    ("databricks", "auth", "login"), ("orch", "logins", "renew"), ("npm", "login"), ("docker", "login"),
    *(
        (a["detect"]["binary"], *argv)
        for a in agentsdata.load()["adapters"].values()
        if (a.get("detect") or {}).get("binary")
        for argv in (a.get("login") or {}).get("card", ())
    ),
)  # fmt: skip

_ONOFF = ("on", "off")
# orch's own words for each setting a card may change: (what "on" does, what "off" does). Only these run.
CONFIG_OPS: dict[str, dict] = {
    "workflow.reviewer": {"values": _ONOFF, "on": "The Reviewer accepts small finished work for you",
                          "off": "The Reviewer leaves all finished work for you"},
    "workflow.reviewer_answers": {"values": _ONOFF,
                                  "on": "The Reviewer answers small routine questions for you",
                                  "off": "Routine questions wait for you"},
    "workflow.reviewer_look": {"values": _ONOFF,
                               "on": "The Reviewer gives bigger finished work a second look",
                               "off": "Bigger finished work waits for you without a second look"},
    "workflow.auto_reviewer": {"values": _ONOFF, "on": "New tickets start without Human review needed",
                               "off": "New tickets start with Human review needed"},
    "workflow.release_merge": {"values": _ONOFF,
                               "on": "Releases with every check green merge without your click",
                               "off": "Releases wait for your Merge click"},
    "github.release_walks": {"pattern": re.compile(r"^[a-z][a-z0-9-]{0,30}(=[a-z][a-z0-9-]{0,40})?"
                                                   r"(,[a-z][a-z0-9-]{0,30}(=[a-z][a-z0-9-]{0,40})?){0,7}$"),
                             "set": "Every release runs these walks before its Merge card: {value}"},
}  # fmt: skip


def _refuse(msg: str):
    raise Refused(msg)


def _orch_op(argv: list[str]) -> dict:
    """The typed operation an `orch ...` command is, or Refused. Exact shapes only: no extra flags."""
    allowed = "orch config set <setting> <value> (for " + ", ".join(CONFIG_OPS) + "), orch logins status"
    rest = argv[1:]
    if len(rest) == 4 and rest[:2] == ["config", "set"] and rest[2] in CONFIG_OPS:
        key, value = rest[2], rest[3]
        rule = CONFIG_OPS[key]
        if "values" in rule and value not in rule["values"]:
            _refuse(f"{key} takes {' or '.join(rule['values'])}.")
        if "pattern" in rule and not rule["pattern"].fullmatch(value):
            _refuse(f"{key} does not take that value.")
        op = {"verb": "config.set", "key": key, "value": value}
        if "pattern" in rule:  # the value it had when asked: the undo is built from it, never typed
            op["before"] = None
        return op
    if rest == ["logins", "status"]:
        return {"verb": "logins.status"}
    _refuse(f"This orch command cannot run from a card. A card runs only: {allowed}.")
    return {}  # unreachable


def op_words(root: Path | None, op: dict) -> tuple[str, str | None]:
    """(what it changes, how to undo it) in orch's own words for a typed operation."""
    if op["verb"] == "config.set":
        rule = CONFIG_OPS[op["key"]]
        if "values" in rule:
            other = "off" if op["value"] == "on" else "on"
            return rule[op["value"]], f"orch config set {op['key']} {other}"
        before = op.get("before")
        ok = isinstance(before, str) and rule["pattern"].fullmatch(before)
        return rule["set"].format(value=op["value"]), f"orch config set {op['key']} {before}" if ok else None
    return "Shows which logins work; nothing changes", None


def _current(root: Path, key: str) -> str | None:
    """The setting's value now, as `orch config get` says it (None when it cannot be read)."""
    with contextlib.suppress(Exception):
        r = subprocess.run(
            [*_orch_argv(), "config", "get", key, "--json"],
            cwd=root, env=_env(root), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
        )  # fmt: skip
        if r.returncode == 0:
            v = json.loads(r.stdout)
            v = v.get(key) if isinstance(v, dict) else v
            if isinstance(v, bool):
                return "on" if v else "off"
            if isinstance(v, str | int):
                return str(v)
    return None


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolve(root: Path, prog: str, dirs: tuple[str, ...] = SAFE_DIRS) -> str:
    """The absolute program a non-orch command runs, from the system folders only; Refused otherwise."""
    if "/" in prog:
        cand = Path(prog)
        if not cand.is_absolute():
            _refuse("Give the program by name or by its full path, not a path inside a folder.")
        found = str(cand) if cand.is_file() and os.access(cand, os.X_OK) else None
    else:
        found = shutil.which(prog, path=os.pathsep.join(os.path.expanduser(d) for d in dirs))
    if not found:
        _refuse(f"{prog} is not installed in the system folders of this computer.")
    real = Path(os.path.realpath(found))
    bad = [root.resolve(), Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()]
    bad.append(Path("/private/tmp"))
    home = Path.home()
    bad += [home / ".orch-tool", home / ".orch-test", home / "orch-wt"]
    if any(_inside(real, b) for b in bad):
        _refuse(f"{prog} lives in a work or temp folder; a card runs only installed programs.")
    return str(real)


def _login(argv: list[str]) -> bool:
    """A sign-in orch knows, word for word. Extra arguments (a host, a registry, a tenant) make it a command
    orch did not check: it gets the copy-only card with that warning, never orch's own "Sign in again"."""
    return tuple(argv) in LOGINS


def parse(root: Path, command, changes=None, undo=None, *, login: bool = False) -> dict:
    """The card's spec for one command, or Refused with one plain line why."""
    if not isinstance(command, str) or not command.strip():
        _refuse("Give the one command to run.")
    command = command.strip()
    if len(command) > COMMAND_MAX:
        _refuse(f"A command on a card is at most {COMMAND_MAX} characters.")
    if _CONTROL.search(command):
        _refuse("The command has a hidden or control character.")
    if any(c in _SHELL for c in command):
        _refuse("One command only, no shell operators (; | & < > $ ` or backslash).")
    _no_secret(root, command)
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        _refuse("The command's quotes do not close.")
    if not argv:
        _refuse("Give the one command to run.")
    prog = argv[0]
    if "=" in prog:
        _refuse("No settings before the command (like NAME=value cmd).")
    base = prog.rsplit("/", 1)[-1]
    spec: dict = {"v": POLICY, "command": command, "argv": argv, "cwd": str(root.resolve())}
    if login and not _login(argv):
        _refuse("--login is for a sign-in command such as gh auth login.")
    if _login(argv):  # orch's own words, never the helper's
        _line(changes, "changes"), _line(undo, "undo")
        spec.update({"class": "login", "exe": None, "changes": "Sign in again"})
        return spec
    if base == "orch":
        if prog != "orch":
            _refuse("Run orch by its name: orch ...")
        op = _orch_op(argv)
        if "before" in op:
            op["before"] = _current(root, op["key"])
        words, undo_words = op_words(root, op)
        spec.update({"class": "orch", "exe": None, "op": op, "changes": words})
        if undo_words:
            spec["undo"] = undo_words
        return spec
    if not _other_op(argv):  # shown with Copy only: the person runs it in their own terminal
        # no helper words on it: orch did not check this command, and the card says so (UNCHECKED)
        _line(changes, "changes"), _line(undo, "undo")  # still checked as one plain line each
        spec.update({"class": "copy", "exe": None})
        return spec
    _line(changes, "changes"), _line(undo, "undo")  # orch writes the words for an allowed shape
    words, undo_words = other_words(argv)
    spec.update({"class": "other", "exe": _resolve(root, prog), "changes": words})
    if undo_words:
        spec["undo"] = undo_words
    return spec


def other_words(argv: list[str]) -> tuple[str, str | None]:
    """orch's own words for an allowed non-orch shape: what it changes and how to undo it."""
    if tuple(argv[:2]) == ("brew", "install"):
        names = argv[2:]
        return f"Installs {', '.join(names)} with Homebrew", "brew uninstall " + " ".join(names)
    if tuple(argv[:2]) == ("brew", "uninstall"):
        names = argv[2:]
        return f"Removes {', '.join(names)} (installed with Homebrew)", "brew install " + " ".join(names)
    if tuple(argv[:2]) == ("brew", "upgrade"):
        return f"Updates {', '.join(argv[2:])} to the newest version with Homebrew", None
    return "Runs " + " ".join(argv), None  # a shape a test adds (runcard.OTHER_OPS)


def _no_secret(root: Path, text: str) -> None:
    from orch import secretscan

    try:
        found = secretscan.find(text, root)
    except Exception:  # noqa: BLE001  fail closed
        found = [{"kind": "unchecked"}]
    if found:
        _refuse("The command looks like it holds a password or key. A card never carries one.")


def _line(v, what: str) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str) or _CONTROL.search(v):
        _refuse(f"--{what} is one plain line.")
    v = v.strip()
    if len(v) > 200:
        _refuse(f"--{what} is at most 200 characters.")
    return v or None


def check_spec(root: Path | None, spec) -> dict:
    """A stored spec, parsed again from its command text: it must come out exactly the same (policy, argv,
    program, folder, class, operation). Refused otherwise (an older card or a hand-edited ticket)."""
    if not isinstance(spec, dict) or spec.get("v") != POLICY or root is None:
        _refuse("This card was made under older rules. Ask the helper to make it again.")
    again = parse(root, spec.get("command"), spec.get("changes"), spec.get("undo"),
                  login=spec.get("class") == "login")  # fmt: skip
    op, op2 = spec.get("op"), again.get("op")
    if isinstance(op, dict) and isinstance(op2, dict) and "before" in op2:
        op2 = {**op2, "before": op.get("before")}  # the value it had when asked; checked through the words
        again = {**again, "op": op2}
        again["changes"], undo = op_words(root, op2)
        again.pop("undo", None)
        if undo:
            again["undo"] = undo
    keys = ("v", "command", "argv", "cwd", "class", "exe", "op", "changes", "undo")  # what runs and is shown
    if any(again.get(k) != spec.get(k) for k in keys) or set(spec) - {*keys}:
        _refuse("This card does not match its command any more. Ask the helper to make it again.")
    return spec


# ------------------------------------------------------------------ running


def _orch_argv() -> list[str]:
    """This orch, by absolute path (never the PATH a helper may have changed)."""
    return procs.orch_python_argv()  # -I -P: no orch.py of the workspace folder, no PYTHON* settings


def _env(root: Path) -> dict:
    """A small fixed environment: no helper marks, no loader or config overrides from the dashboard's env."""
    home = str(Path.home())
    env = {
        "PATH": os.pathsep.join(SAFE_DIRS),
        "HOME": home,
        "USER": os.environ.get("USER") or Path(home).name,
        "LOGNAME": os.environ.get("LOGNAME") or os.environ.get("USER") or Path(home).name,
        "LANG": os.environ.get("LANG") or "en_US.UTF-8",
        "ORCH_ROOT": str(root),
        "NO_COLOR": "1",
        "HOMEBREW_FORBID_PACKAGES_FROM_PATHS": "1",  # brew never loads a formula from a file path
        "TERM": "dumb",
    }
    for k in ("ORCH_HOME", "ORCH_HOME_STRICT", "TMPDIR"):  # where this orch keeps its own files
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _exec(argv: list[str], root: Path, timeout: float) -> tuple[int | None, str, float]:
    """Run without a shell, stdin closed, in its own process group (POSIX) or group (Windows). A reader thread
    keeps at most OUT_MAX bytes. Returns (exit code or None on a timeout, output, seconds)."""
    import threading

    t0 = time.monotonic()
    extra = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    p = subprocess.Popen(
        argv, cwd=root, env=_env(root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, **extra,
    )  # fmt: skip
    buf = bytearray()

    def read():
        with contextlib.suppress(OSError, ValueError):
            for chunk in iter(lambda: p.stdout.read(8192), b""):
                if len(buf) < OUT_MAX:
                    buf.extend(chunk[: OUT_MAX - len(buf)])

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    code = None
    try:
        code = p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        code = None
    finally:
        if code is None:
            _kill(p)
        reader.join(timeout=5)
        with contextlib.suppress(OSError):
            p.stdout.close()
    return code, bytes(buf).decode("utf-8", "replace"), time.monotonic() - t0


def _kill(p) -> None:
    """Stop the command and what it started (its process group on POSIX)."""
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        if os.name == "nt":
            p.kill()
        else:
            os.killpg(p.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        p.wait(timeout=5)


def masked(root: Path, text: str) -> str:
    """Lines that look like a secret are hidden (secretscan); fail closed: on an error all of it is hidden."""
    from orch import secretscan

    text = text.replace("\r\n", "\n").replace("\r", "\n")  # one line numbering for the scan and the mask
    lines = text.split("\n")
    try:
        bad = {f["line"] for f in secretscan.find(text, root)}
    except Exception:  # noqa: BLE001
        return "(what it printed is hidden: orch could not check it for secrets)"
    return "\n".join("(hidden: looks like a secret)" if i + 1 in bad else ln for i, ln in enumerate(lines))


def _tail(text: str, n: int = TAIL_LINES) -> str:
    return "\n".join(text.rstrip("\n").splitlines()[-n:])


def _log(root: Path, row: dict) -> None:
    with contextlib.suppress(OSError):
        d = root / ".orch" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        with (d / "card-runs.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


class _Lock:
    def __init__(self, root: Path, tid: str, qid: str):
        self.path = root / ".orch" / "tickets" / tid / f".run-{qid}.lock"

    def __enter__(self):
        with contextlib.suppress(OSError):
            if time.time() - self.path.stat().st_mtime > TIMEOUT + 60:  # left by a crash
                self.path.unlink()
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise Refused("It is running already. Wait for it to finish.") from None
        os.close(fd)
        return self

    def __exit__(self, *a):
        with contextlib.suppress(OSError):
            self.path.unlink()


def card_of(q) -> dict | None:
    card = q.get("card") if isinstance(q, dict) else None
    return card if isinstance(card, dict) and card.get("kind") == "run" else None


def phone_ok(q) -> bool:
    """The phone shows Run it now only for orch's own operations."""
    card = card_of(q)
    spec = card.get("run") if card else None
    return PHONE_RUN and isinstance(spec, dict) and spec.get("class") == "orch"


def run(
    root: Path,
    tid: str,
    qid: str,
    digest: str | None,
    *,
    by: str,
    person: bool,
    via: str = "cli",
    confirmed: bool = False,
    timeout: float = TIMEOUT,
) -> dict:
    """Run a run card's command for the person and answer it. Returns {ok, exit, output, answered, ...}.
    A failure (exit not 0, a timeout, a setting that did not change) saves the attempt on the ticket and
    returns ok False; the card stays open. One run per card at a time: the lock covers the checks, the run
    and the answer (review.decide refuses another answer while it is held)."""
    from orch import tickets

    attempt = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "by": by, "via": via, "ticket": tid,
               "question": qid}  # fmt: skip
    tickets.load(root, tid)  # a plain ticket id before the lock file is named after it
    with _Lock(root, tid, qid):
        try:
            spec = _checked(root, tid, qid, digest, by=by, person=person, via=via, confirmed=confirmed)
        except Refused as e:
            _log(root, {**attempt, "refused": str(e)})
            raise
        attempt.update(digest=digest, argv=spec["argv"], cls=spec["class"])
        if spec["class"] == "login":
            return _start_signin(root, tid, qid, digest, spec, attempt)
        argv = [*_orch_argv(), *spec["argv"][1:], "--by", by] if spec["class"] == "orch" else [
            spec["exe"], *spec["argv"][1:]]  # fmt: skip
        code, out, secs = _exec(argv, Path(spec["cwd"]), timeout)
        out = masked(root, out)
        ok, reason = code == 0, None
        if code is None:
            reason = "timeout"
        elif code != 0:
            reason = "exit"
        elif spec["class"] == "orch" and spec["op"]["verb"] == "config.set":
            if _current(root, spec["op"]["key"]) != spec["op"]["value"]:
                ok, reason = False, "unchanged"
        why = error_words(reason, code, spec)
        tail = _tail(out)
        attempt.update(exit=code, secs=round(secs, 1), ok=ok, output=tail, reason=reason)
        _log(root, attempt)
        with contextlib.suppress(Refused, OSError):
            tickets.note_history(root, tid, by, f"Ran the card's command ({'ok' if ok else 'failed'}): "
                                 f"{spec['command']}", via)  # fmt: skip
        if not ok:
            _save_attempt(root, tid, qid, attempt, why)
            return {"ok": False, "exit": code, "output": tail, "error": why, "answered": False}
        d = {
            "action": "approve", "picked": None, "allows": OK_LABEL, "changes": [], "words": {"text": ""},
            "pins": [], "replaces": None, "replaced_by": None, "summary": OK_LABEL,
            "ran": {"at": attempt["at"], "exit": code, "secs": attempt["secs"], "output": tail,
                    "digest": digest},
        }  # fmt: skip
        tickets.answer(root, tid, qid, OK_LABEL, by, via, expected_question_digest=digest, decision=d,
                       person=True, ran=True)  # fmt: skip
        _save_attempt(root, tid, qid, attempt, None)
    return {"ok": True, "exit": code, "output": tail, "answered": True}


def _checked(
    root: Path, tid: str, qid: str, digest, *, by: str, person: bool, via: str, confirmed: bool
) -> dict:
    """Every check before a run, read fresh under the lock. Returns the card's spec, or Refused."""
    from orch import tickets

    q = next((x for x in tickets.load(root, tid).get("questions") or [] if x.get("id") == qid), None)
    if q is None:
        _refuse(f"Ticket {tid} has no question {qid}.")
    tickets.refuse_if_taken_back(q)
    card = card_of(q)
    if card is None:
        _refuse("That card has no command to run.")
    if q.get("answer") is not None:
        _refuse(f"{qid} is answered already.")
    if not person or not by.startswith("human:"):
        _refuse(PERSON_REFUSAL)
    if digest is None or tickets.question_digest(q) != digest:
        _refuse(CHANGED)
    spec = check_spec(root, card.get("run"))
    if via == "phone" and not (PHONE_RUN and spec["class"] == "orch"):
        _refuse("The phone runs only orch's own commands. Run this one at your computer.")
    if spec["class"] == "login" and (why := signin_blocked(root, spec)):
        _refuse(why)
    if spec["class"] == "copy":
        _refuse("This command runs in your own terminal: copy it and run it there.")
    if spec["class"] == "other" and not confirmed:
        _refuse("This is not an orch command: confirm it first (it runs exactly as shown).")
    return spec


def running(root: Path, tid: str, qid: str) -> bool:
    """A Run it now of this card is under way (review.decide refuses another answer meanwhile)."""
    p = _Lock(root, tid, qid).path
    with contextlib.suppress(OSError):
        return time.time() - p.stat().st_mtime <= TIMEOUT + 60
    return False


def error_words(reason: str | None, code, spec: dict | None = None) -> str | None:
    """The card's error line, always built by orch from the reason code (never stored text)."""
    if reason == "timeout":
        return "It took longer than 2 minutes and was stopped. It may have run partly."
    if (
        reason == "exit" and isinstance(code, int) and code < 0
    ):  # stopped by a signal (Ctrl+C in the terminal)
        return "It was stopped before it finished. Nothing was marked as done."
    if reason == "exit":
        n = code if isinstance(code, int) else "?"
        return f"It ended with exit code {n}. Nothing was marked as done."
    if reason == "refused":
        return "The sign-in did not start in the terminal. Click Run it now again."
    if reason == "check":
        return "The sign-in ended, but its login check is not green. Nothing was marked as done."
    if reason == "signin-timeout":
        return "The sign-in took longer than 15 minutes and was stopped. Nothing was marked as done."
    if reason == "unchanged":
        key = ((spec or {}).get("op") or {}).get("key") or "the setting"
        return f"It ran, but {key} did not change. Nothing was marked as done."
    return None


def _save_attempt(root: Path, tid: str, qid: str, attempt: dict, why: str | None) -> None:
    """The last try per card, on the ticket beside the question (not in it: the card's digest stays what was
    shown) and outside the add-on data a helper may write with `orch ext set`. The error line is rebuilt from
    the reason code when it is shown."""
    from orch import tickets

    row = {k: attempt.get(k) for k in ("at", "by", "exit", "secs", "ok", "output", "reason")}

    def op(t):
        runs = t.get("run_attempts") if isinstance(t.get("run_attempts"), dict) else {}
        runs[qid] = row
        t["run_attempts"] = runs

    with contextlib.suppress(Refused, OSError, ValueError):
        tickets.apply_op(root, tid, op, by=attempt["by"])


# ------------------------------------------------------------------ sign-in in the Focus terminal (ORCH-865)


def login_check(root: Path, argv: list[str]) -> dict | None:
    """The login check of a sign-in command: the check that names it as its sign-in, else the check whose own
    command runs the same program (gh auth login -> the GitHub check, a helper tool's login -> its own check).
    None: orch cannot tell whether this sign-in worked, so the card keeps Copy only."""
    from orch import health

    if not argv or argv[0] == "orch":  # orch's own renew has its own Renew button
        return None
    try:
        found = [r for r in health.recipes(root) if r.get("kind", "login") == "login" and not r.get("script")]
    except Exception:  # noqa: BLE001  no checks readable: no terminal sign-in
        return None
    command = " ".join(argv)
    for r in found:
        if r.get("sign_in") == command:
            return r
    prog = Path(argv[0]).name
    return next((r for r in found if (r.get("command") or [None])[0] == prog), None)


def _tmux_here() -> bool:
    return os.name != "nt" and shutil.which("tmux") is not None


def signin_blocked(root: Path | None, spec: dict) -> str | None:
    """Why Run it now cannot open the terminal for this sign-in (one plain line), None when it can."""
    copy = "copy it and run it in your terminal."
    if root is None or spec.get("class") != "login":
        return "This is not a sign-in."
    if not _tmux_here():
        return "This computer has no Focus terminal for a sign-in: " + copy
    if login_check(root, spec["argv"]) is None:
        return "orch has no login check for this sign-in, so it cannot tell when it worked: " + copy
    return None  # typing in the terminal stays the person's own switch: the card offers it (ORCH-865)


def terminal_ok(root: Path | None, q) -> bool:
    """The card's Run it now opens the Focus terminal (a sign-in orch can check, on a computer that can)."""
    card = card_of(q)
    spec = card.get("run") if card else None
    if not isinstance(spec, dict) or spec.get("class") != "login":
        return False
    with contextlib.suppress(Exception):
        return signin_blocked(root, spec) is None
    return False


def _hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _age(at) -> float:
    try:
        return time.time() - datetime.fromisoformat(str(at)).timestamp()
    except (TypeError, ValueError):
        return float("inf")


def login_now(t: dict, qid: str) -> dict | None:
    """The card's sign-in under way: {at, state, terminal} while the terminal starts it or it runs."""
    rows = t.get("run_attempts") if isinstance(t.get("run_attempts"), dict) else {}
    row = rows.get(qid) if isinstance(rows.get(qid), dict) else None
    if not row or row.get("state") not in ("starting", "running"):
        return None
    limit = SIGNIN_START if row["state"] == "starting" else SIGNIN_TIMEOUT + 60
    if _age(row.get("at" if row["state"] == "starting" else "started")) > limit:
        return None
    return {"at": row.get("at"), "state": row["state"], "terminal": row.get("terminal")}


def _claims(root: Path) -> Path:
    from orch import home as orch_home

    d = orch_home.key_dir(Path(root)) / "runcard" / "signin"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def _put_claim(root: Path, nonce: str, doc: dict) -> None:
    """Keep the click's claim (0600, named by the code's hash) in the guarded orch home; old ones go."""
    d = _claims(root)
    for f in d.iterdir():
        with contextlib.suppress(OSError):
            if time.time() - f.stat().st_mtime > SIGNIN_START:
                f.unlink()
    fd = os.open(d / f"{_hash(nonce)}.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f)


def _take_claim(root: Path, nonce: str) -> dict | None:
    """The click's claim for this code, used up (fresh or not); None when there is none or it is late."""
    if not isinstance(nonce, str) or not 20 <= len(nonce) <= 100:
        return None
    try:
        f = _claims(root) / f"{_hash(nonce)}.json"
        fresh = time.time() - f.stat().st_mtime <= SIGNIN_START
        doc = json.loads(f.read_text(encoding="utf-8"))
        f.unlink()
    except (OSError, ValueError, Refused):
        return None
    return doc if fresh and isinstance(doc, dict) else None


def _set_row(root: Path, tid: str, qid: str, row: dict | None, by: str, *, expect=None) -> None:
    """Write (or with None remove) the card's last-try row; expect(old row) may refuse in the same write."""
    from orch import tickets

    def op(t):
        runs = t.get("run_attempts") if isinstance(t.get("run_attempts"), dict) else {}
        if expect is not None:
            expect(runs.get(qid) if isinstance(runs.get(qid), dict) else None)
        if row is None:
            runs.pop(qid, None)
        else:
            runs[qid] = row
        t["run_attempts"] = runs

    tickets.apply_op(root, tid, op, by=by)


def _start_signin(root: Path, tid: str, qid: str, digest: str, spec: dict, attempt: dict) -> dict:
    """Open the plain terminal and start `orch review signin` in a new window of it (no shell). The window
    gets a one-time code in its environment; the ticket keeps only its hash, so only that window answers
    the card."""
    from orch import runs_live, sessions, tickets

    by = attempt["by"]
    if login_now(tickets.load(root, tid), qid):  # under the card's lock: one sign-in per card at a time
        _refuse("The sign-in runs in the terminal already. Finish it there.")
    check = login_check(root, spec["argv"])
    exe = _login_exe(root, spec["argv"][0])
    term = sessions.new(root, "terminal", by)
    if not term.get("shell"):
        _refuse("The plain terminal could not start. Copy the command and run it in your own terminal.")
    nonce = secrets.token_urlsafe(24)
    # the proof of the click lives in the guarded orch home (never the ticket file a helper may write);
    # the ticket only says what the card shows
    claim = {"ticket": tid, "question": qid, "by": by, "digest": digest, "exe": exe, "check": check["name"]}
    _put_claim(root, nonce, {**claim, "terminal": term["id"], "at": attempt["at"]})
    row = {"at": attempt["at"], "by": by, "ok": None, "state": "starting",
           "terminal": term["id"]}  # fmt: skip
    _set_row(root, tid, qid, row, by)
    env = ["-e", f"ORCH_SIGNIN={nonce}", "-e", f"ORCH_ROOT={root}"]
    for k in ("ORCH_HOME", "ORCH_HOME_STRICT"):  # the same orch home as this orch
        if os.environ.get(k):
            env += ["-e", f"{k}={os.environ[k]}"]
    r = runs_live.tmux(
        root, "new-window", "-t", f"={term['id']}:", "-n", sessions.SIGNIN_WINDOW, "-c", spec["cwd"], *env,
        "--",
        *_orch_argv(), "review", "signin", tid, qid,
    )  # fmt: skip
    if r.returncode != 0:
        _take_claim(root, nonce)
        with contextlib.suppress(Refused, OSError, ValueError):
            _set_row(root, tid, qid, None, by)
        _log(root, {**attempt, "refused": "the terminal did not start the sign-in"})
        _refuse("The terminal could not start the sign-in. Copy the command and run it in your own terminal.")
    _log(root, {**attempt, "terminal": term["id"], "check": check["name"], "started": True})
    with contextlib.suppress(Refused, OSError):
        tickets.note_history(root, tid, by, f"Started the card's sign-in in the terminal: {spec['command']}",
                             attempt.get("via"))  # fmt: skip
    return {
        "ok": True,
        "exit": None,
        "output": "",
        "answered": False,
        "in_terminal": True,
        "terminal": term["id"],
    }


def _login_exe(root: Path, prog: str) -> str:
    """The sign-in program by absolute path. Outside the system folders (a tool's own installer folder) it
    must belong to this user or root and neither it nor its folder may be writable by others."""
    exe = _resolve(root, prog, LOGIN_DIRS)
    if any(_inside(Path(exe), Path(d)) for d in SAFE_DIRS) or os.name == "nt":
        return exe
    for path in (Path(exe), Path(exe).parent):
        st = path.stat()
        if st.st_uid not in (0, os.getuid()) or st.st_mode & 0o022:
            _refuse(f"{prog} can be changed by others on this computer; run it in your own terminal.")
    return exe


def _login_env(root: Path) -> dict:
    """The sign-in's environment: the small fixed one, a real terminal, the sign-in program's own folders."""
    env = _env(root)
    env.pop("NO_COLOR", None)
    env["PATH"] = os.pathsep.join(os.path.expanduser(d) for d in LOGIN_DIRS)
    env["TERM"] = os.environ.get("TERM") if os.environ.get("TERM", "dumb") != "dumb" else "xterm-256color"
    return env


def _stop_terminal_group(p) -> None:
    """A sign-in that took too long: stop it and what it started on this terminal (the window's process
    group; this runner lets the signal pass so it can still say how it went)."""
    if os.name != "nt":
        prev = signal.signal(signal.SIGTERM, lambda *_: None)
        try:
            with contextlib.suppress(OSError):
                os.killpg(os.getpgrp(), signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(timeout=5)
        finally:
            signal.signal(signal.SIGTERM, prev)
    with contextlib.suppress(OSError):
        p.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        p.wait(timeout=5)


def _green(root: Path, name: str, exe: str | None = None) -> bool:
    """Run the login check now (and keep its result for the Logins page): True when it works. exe: the program
    that just signed in; its folder comes first on PATH, so the check asks that same program."""
    from orch import health

    if exe:
        os.environ["PATH"] = os.pathsep.join([str(Path(exe).parent), os.environ.get("PATH", "")])
    doc = health.check(root, only=name)
    row = next((x for x in doc.get("items") or [] if isinstance(x, dict) and x.get("name") == name), None)
    return bool(row) and row.get("state") in ("works", "soon")


def signin(root: Path, tid: str, qid: str, nonce: str | None, *, say=print, wait=None,
           timeout: float = SIGNIN_TIMEOUT) -> int:  # fmt: skip
    """`orch review signin` in the terminal window Run it now opened: start the sign-in program on this
    terminal, wait for it, run its login check and answer the card "I ran it" for the person who clicked,
    only when the program ended with 0 and the check is green. Returns the exit code for the window
    (0 = answered)."""
    from orch import runs_live, tickets

    started = datetime.now(UTC).isoformat(timespec="seconds")
    if not nonce:
        _refuse(PERSON_REFUSAL)
    tickets.load(root, tid)  # a plain ticket id
    # the code works once, only for the click that made it (this card), and only soon after it
    taken = _take_claim(root, nonce)
    if not taken or taken.get("ticket") != tid or taken.get("question") != qid:
        _refuse(PERSON_REFUSAL)
    by = str(taken.get("by") or "")
    if not history.is_person_line(by):  # the claim orch wrote at the click: who clicked
        _refuse(PERSON_REFUSAL)
    row = {"at": taken.get("at"), "by": by, "ok": None, "state": "running", "terminal": taken.get("terminal"),
           "started": started}  # fmt: skip
    _set_row(root, tid, qid, row, by)
    attempt = {"at": started, "by": by, "via": SIGNIN_VIA, "ticket": tid, "question": qid}

    def end(reason: str | None, code, secs: float, words: str) -> int:
        ok = reason is None
        done = {k: taken.get(k) for k in ("at", "by", "terminal", "check")}
        done.update(ok=ok, exit=code, secs=round(secs, 1), output=words, reason=reason, state=None)
        with contextlib.suppress(Refused, OSError, ValueError):
            _set_row(root, tid, qid, done, by)
        _log(root, {**attempt, "exit": code, "secs": round(secs, 1), "ok": ok, "reason": reason})
        return 0 if ok else 1

    try:
        q = next((x for x in tickets.load(root, tid).get("questions") or [] if x.get("id") == qid), None)
        if q is None or q.get("answer") is not None or card_of(q) is None:
            _refuse(f"{qid} is answered already or has no sign-in.")
        if tickets.question_digest(q) != taken.get("digest"):
            _refuse(CHANGED)
        spec = check_spec(root, card_of(q).get("run"))
        if spec["class"] != "login":
            _refuse("That card is not a sign-in.")
        exe = _login_exe(root, spec["argv"][0])
        if exe != taken.get("exe"):
            _refuse("The sign-in program changed since you clicked. Click Run it now again.")
    except Refused as e:
        say(f"orch: {e}")
        end("refused", None, 0.0, str(e))
        raise
    say(f"orch: starting the sign-in: {spec['command']}")
    say(f"orch: in {spec['cwd']}. The card answers itself once you are signed in.\n")
    t0 = time.monotonic()
    prev = (
        signal.signal(signal.SIGINT, lambda *_: None) if os.name != "nt" else None
    )  # Ctrl+C is the program's
    try:
        p = subprocess.Popen([exe, *spec["argv"][1:]], cwd=spec["cwd"], env=_login_env(root))  # this terminal
        try:
            code = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
            _stop_terminal_group(p)
    except OSError as e:
        say(f"\norch: the sign-in program did not start: {e.strerror or e}")
        return end("exit", None, time.monotonic() - t0, "The sign-in program did not start.")
    finally:
        if prev is not None:
            signal.signal(signal.SIGINT, prev)
    secs = time.monotonic() - t0
    if code is None:
        say("\norch: " + error_words("signin-timeout", None))
        rc = end("signin-timeout", None, secs, "")
    elif code != 0:
        say("\norch: " + error_words("exit", code))
        rc = end("exit", code, secs, "")
    elif not _green(root, taken["check"], exe):
        say("\norch: " + error_words("check", 0))
        rc = end("check", 0, secs, "")
    else:
        words = f"Signed in; the {taken['check']} login check is green."
        d = {
            "action": "approve", "picked": None, "allows": OK_LABEL, "changes": [], "words": {"text": ""},
            "pins": [], "replaces": None, "replaced_by": None, "summary": OK_LABEL,
            "ran": {"at": started, "exit": 0, "secs": round(secs, 1), "output": words,
                    "digest": taken.get("digest"), "check": taken["check"]},
        }  # fmt: skip
        try:
            tickets.answer(root, tid, qid, OK_LABEL, by, SIGNIN_VIA,
                           expected_question_digest=taken.get("digest"),
                           decision=d, person=True, ran=True)  # fmt: skip
        except Refused as e:
            say(f"\norch: signed in, but the card could not be answered: {e}")
            return end("refused", 0, secs, str(e))
        rc = end(None, 0, secs, words)
        with contextlib.suppress(Refused, OSError):
            tickets.note_history(root, tid, by, f"Signed in from the card in the terminal: {spec['command']}",
                                 SIGNIN_VIA)  # fmt: skip
        with contextlib.suppress(Refused, KeyError, StopIteration, OSError):
            q = next(x for x in tickets.load(root, tid)["questions"] if x["id"] == qid)
            runs_live.pass_answer(root, tid, {"id": qid, "answer": q.get("answer"),
                                              "decision": q.get("decision")}, by)  # fmt: skip
        say("\norch: " + words + " The card is answered.")
    if wait is not None:
        wait()
    return rc

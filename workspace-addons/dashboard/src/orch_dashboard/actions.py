"""What the dashboard may do: one fixed table of ops, each building exactly one `orch` argv.

No shell is involved. Ids are checked by regex, text is limited to 2000 characters, and free text always goes
after `--` (or as `--flag=value`) so it can never be read as an option. The dashboard never names an add-on.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from . import runfiles
from .data import run_orch

MAX_TEXT = 2000
TID = re.compile(r"t_[a-z0-9]{6,16}")
QID = re.compile(r"q[0-9]{1,4}")
DAY = re.compile(r"(\d{4}-\d\d-\d\d)?")
ADDON = re.compile(r"[a-z][a-z0-9-]{1,31}")
VERB = re.compile(r"[a-z][a-z-]{0,20}")
# A name that is also a core command is never an add-on target, whatever the add-on list says.
RESERVED = frozenset({"ticket", "check", "log", "ask", "answer", "link", "ext", "wait", "needs", "run", "start", "stop",
                      "status", "init", "update", "addon", "agents", "config", "clients", "help", "setup", "dashboard"})
AGENT = re.compile(r"[a-z][a-z0-9-]{1,31}")
MAX_COMMAND = 500
PATCH_KEYS = ("title", "status", "owner", "due", "note", "summary")
STATUSES = ("open", "active", "waiting", "done", "dropped")


class BadRequest(Exception):
    """The request does not match the op table (HTTP 400)."""


class Unavailable(Exception):
    """No orch command to run (HTTP 503)."""


def _tid(v) -> str:
    if not isinstance(v, str) or not TID.fullmatch(v):
        raise BadRequest("That is not a ticket id.")
    return v


def _qid(v) -> str:
    if not isinstance(v, str) or not QID.fullmatch(v):
        raise BadRequest("That is not a question id.")
    return v


def _text(v, name="text", empty=False) -> str:
    if not isinstance(v, str) or (not empty and not v.strip()):
        raise BadRequest(f"Please write the {name}.")
    if len(v) > MAX_TEXT:
        raise BadRequest(f"The {name} is too long (at most {MAX_TEXT} characters).")
    if "\x00" in v:
        raise BadRequest(f"The {name} has a character that is not allowed.")
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


def _answer(a):
    _only(a, ("ticket", "question", "answer"))
    return ["answer", _tid(a.get("ticket")), _qid(a.get("question"))], ["--via", "dashboard"], \
        [_text(a.get("answer"), "answer")]


def _ticket_new(a):
    _only(a, ("title", "parent"))
    flags = [f"--parent={_tid(a['parent'])}"] if a.get("parent") else []
    return ["ticket", "new"], flags, [_text(a.get("title"), "title")]


def _ticket_patch(a):
    _only(a, ("ticket", "data", "if_revision"))
    data = a.get("data")
    if not isinstance(data, dict) or not data or set(data) - set(PATCH_KEYS):
        raise BadRequest("Nothing to change, or a field that cannot be changed here.")
    for k, v in data.items():
        if k == "status" and v not in STATUSES:
            raise BadRequest("That is not a status.")
        if k == "due" and not (isinstance(v, str) and DAY.fullmatch(v)):
            raise BadRequest("The due day must look like 2026-11-30.")
        if k not in ("status", "due"):
            _text(v, k, empty=k in ("owner", "note"))
    rev = _rev(a.get("if_revision"), required=True)
    return (["ticket", "patch", _tid(a.get("ticket"))], [f"--if-revision={rev}"],
            [json.dumps(data, ensure_ascii=False)])


def _ticket_edit(a):
    _only(a, ("ticket", "owner", "due", "note", "if_revision"))
    flags = []
    for k in ("owner", "due", "note"):
        if k in a:
            v = _text(a[k], k, empty=True)
            if k == "due" and not DAY.fullmatch(v):
                raise BadRequest("The due day must look like 2026-11-30.")
            flags.append(f"--{k}={v}")
    if not flags:
        raise BadRequest("Nothing to change.")
    rev = _rev(a.get("if_revision"))
    if rev is not None:
        flags.append(f"--if-revision={rev}")
    return ["ticket", "edit", _tid(a.get("ticket"))], flags, []


def _log(a):
    _only(a, ("ticket", "text"))
    return ["log", _tid(a.get("ticket"))], [], [_text(a.get("text"))]


def _run_start(a):
    _only(a, ("ticket", "fresh", "take_over"))
    flags = (["--fresh"] if _flag(a.get("fresh")) else []) + (["--take-over"] if _flag(a.get("take_over")) else [])
    return ["run", "start", _tid(a.get("ticket"))], flags, []


def _run_stop(a):
    _only(a, ("ticket",))
    return ["run", "stop", _tid(a.get("ticket"))], [], []


def _addon_start(a):
    _only(a, ())
    return ["start"], ["--no-open"], []


def _addon_act(a):
    """ONE generic op for an add-on's own verbs: `orch <addon> act <verb> -- <target>`. The add-on name is checked
    against `orch addon list` in run_op (it must be on here); the dashboard code never names one."""
    _only(a, ("addon", "verb", "target"))
    addon, verb = a.get("addon"), a.get("verb")
    if not (isinstance(addon, str) and ADDON.fullmatch(addon) and addon not in RESERVED):
        raise BadRequest("That is not an add-on.")
    if not (isinstance(verb, str) and VERB.fullmatch(verb)):
        raise BadRequest("That action is not available.")
    return [addon, "act", verb], [], [_tid(a.get("target"))]


def _agent_name(v) -> str:
    if not (isinstance(v, str) and AGENT.fullmatch(v)):
        raise BadRequest("That is not an agent name (lowercase letters, digits and -).")
    return v


def _config_agent(a):
    """Choose the default agent: `orch config set workspace.agent <name>`; orch refuses a name nobody knows."""
    _only(a, ("name",))
    return ["config", "set", "workspace.agent", _agent_name(a.get("name"))], [], []


def _config_agent_add(a):
    """Add 'your own agent': `orch config agent add <name> --command=<one line>`. The command is ONE argv value
    (`--command=...`), so it can never be read as another option or run through a shell by the dashboard."""
    _only(a, ("name", "command", "prompt_via"))
    cmd = a.get("command")
    if not (isinstance(cmd, str) and 1 <= len(cmd) <= MAX_COMMAND and cmd.strip() and "\n" not in cmd and "\r" not in cmd
            and "\x00" not in cmd):
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


# op -> function(args) -> (words incl. ids, flags, free text after "--")
OPS = {"answer": _answer, "ticket.new": _ticket_new, "ticket.patch": _ticket_patch, "ticket.edit": _ticket_edit,
       "log": _log, "run.start": _run_start, "run.stop": _run_stop, "addon.start": _addon_start,
       "addon.act": _addon_act, "config.agent": _config_agent, "config.agent.add": _config_agent_add,
       "addon.set": _addon_set}


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
    return [*words, *flags, "--by", actor(), "--json", *(["--", *tail] if tail else [])]


def _addon_is_on(root: Path, orch_bin: str, name: str) -> bool:
    rows = run_orch(orch_bin, ["addon", "list", "--json"], root)
    return any(isinstance(r, dict) and r.get("name") == name and r.get("active") is True
               for r in (rows if isinstance(rows, list) else []))


def _addon_known(root: Path, orch_bin: str, name: str) -> bool:
    rows = run_orch(orch_bin, ["addon", "list", "--json"], root)
    return any(isinstance(r, dict) and r.get("name") == name for r in (rows if isinstance(rows, list) else []))


def _agent_exists(root: Path, orch_bin: str, name: str) -> bool:
    """Fails closed: when the list cannot be read, the name counts as taken (core refuses an existing name too)."""
    rows = run_orch(orch_bin, ["agents", "--json"], root)
    if not isinstance(rows, list):
        return True
    return any(isinstance(r, dict) and r.get("name") == name for r in (rows if isinstance(rows, list) else []))


def _audit(root: Path, op: str, args: dict) -> None:
    """One line per settings change in .orch/run/dashboard/actions.log (local, gitignored): who, what, the exact command."""
    keep = {k: v for k, v in args.items() if k in ("name", "command", "prompt_via", "on")}
    line = json.dumps({"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "by": actor(), "via": "dashboard", "op": op, **keep},
                      ensure_ascii=False)
    try:
        # .orch/run/dashboard (0700), no symlink at any level, the file opened with O_NOFOLLOW (0600)
        with runfiles.open_append(runfiles.run_dir(root, "dashboard") / "actions.log") as f:
            f.write(line + "\n")
    except (OSError, RuntimeError):
        pass  # the change is done; a missing log must not turn it into an error


def run_op(root: Path, orch_bin: str | None, op, args) -> tuple[int, str, dict | None]:
    """Run one op. Returns (http status, plain text, parsed json or None)."""
    argv = build_argv(op, args)
    if not orch_bin:
        raise Unavailable("The orch command is not available here.")
    if op == "addon.act" and not _addon_is_on(root, orch_bin, args["addon"]):
        raise BadRequest("That add-on is not on in this workspace.")
    if op == "addon.set" and not _addon_known(root, orch_bin, args["name"]):
        raise BadRequest("That add-on is not installed.")
    if op == "config.agent.add" and _agent_exists(root, orch_bin, args["name"]):
        raise BadRequest("An agent with that name is already set up. Pick another name (changing one is done in the terminal).")
    try:
        r = subprocess.run([orch_bin, *argv], check=False, cwd=root, capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL, env={**os.environ, "ORCH_ROOT": str(root), "ORCH_BIN": orch_bin})
    except subprocess.TimeoutExpired:
        return 504, "That took too long. Please try again.", None
    except OSError:
        raise Unavailable("The orch command could not be started.") from None
    out = None
    try:
        out = json.loads(r.stdout)
    except ValueError:
        pass
    if r.returncode == 0:
        if op in ("config.agent.add", "addon.set", "config.agent"):
            _audit(root, op, args)
        return 200, "", out if isinstance(out, dict) else None
    msg = out.get("error") if isinstance(out, dict) else None
    if not msg:
        msg = (r.stderr.strip().splitlines() or ["That did not work."])[0].removeprefix("Refused: ")
    conflict = isinstance(out, dict) and "revision" in out and "changed_by" in out
    return (409 if conflict else 422), str(msg)[:500], out if conflict else None

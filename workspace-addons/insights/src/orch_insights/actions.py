"""What the Insights settings page may do: one fixed table of ops, each building exactly one `orch` argv.

No shell, no --by/--from/--as/--dev: who acts comes from the proof (H1, contracts/human-proof.md).
The core decides under its own lock whether a change widens: every click first runs WITHOUT a proof;
only when the core answers `needs_person` and the request has the person is a proof minted (value-bound,
op and target fixed here) and the same argv run once more with the proof as the first line of stdin.
Settings changes are serialized here and carry `--if-current <observed>`, so a change in between is
refused by the core (`changed`), never overwritten.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from .overview import validated
from .settings import KEYS, TID, current_value

_run = subprocess.run  # tests may patch this name, never the global subprocess.run

PERSON = "Open Insights from the dashboard on this computer to do this."
AGENT_VARS = ("ORCH_AGENT", "ORCH_RUN", "ORCH_TICKET", "ORCH_DEV", "ORCH_BY", "ORCH_VIA")
FAILED = "That did not work."
NOT_READ = "The record could not be read. Nothing was deleted."
CHANGED = "This changed in the meantime. Reloaded."
SET_TIMEOUT = "That took too long. Reload to see the current setting."
DELETE_TIMEOUT = "That took too long. Reload to see what is still kept."
# The only core answers shown to the person, each as a fixed plain text (never core text or stderr).
MESSAGES = {
    "needs_person": PERSON,
    "invalid": "That value is not allowed.",
    "not_found": "That ticket was not found.",
    "unavailable": NOT_READ,
    "not_available": NOT_READ,
    "tampered": NOT_READ,
    "not_allowed": "This was refused.",
}
SHARING_LOCKS = {
    "off_by_admin": "Switched off by your admin.",
    "not_connected": "Not connected to an admin.",
}
SHARING_UNKNOWN = "Sharing could not be read. Nothing was changed."
WRITE_TIMEOUT = 10  # per child; one overall deadline (TOTAL_BUDGET) covers reads, run and retry
TOTAL_BUDGET = 25
LOCK_WAIT = 5
BUSY = "Busy, try again."
_LOCK = threading.Lock()  # one settings change at a time in this server (read, write and retry together)


class BadRequest(Exception):
    """The request does not match the op table (HTTP 400)."""


class Unavailable(Exception):
    """No orch command to run (HTTP 503)."""


class NeedsPerson(Exception):
    """A human-only click without a proof session (HTTP 403): the page is watch-only here."""


try:
    from orch.pageproof import SELF, argv0, child_env, run_with_proof
except ImportError:  # no orch: nothing runs
    SELF = "orch:self"

    def argv0(orch_bin):
        return [str(orch_bin)]

    def child_env(env, orch_bin):
        return {**env, "ORCH_BIN": str(orch_bin)}

    run_with_proof = None


def real_bin(orch_bin):
    """None (the installed server) and SELF both mean `sys.executable -I -P -m orch`; anything else is a test fake."""
    return SELF if orch_bin is None else orch_bin


def _only(args: dict, allowed: tuple[str, ...]) -> None:
    extra = sorted(set(args) - set(allowed))
    if extra:
        raise BadRequest("That request could not be read.")


def _settings_set(args):
    _only(args, ("key", "value"))
    key, value = args.get("key"), args.get("value")
    if not isinstance(key, str) or key not in KEYS:
        raise BadRequest("That setting can not be changed here.")
    if not isinstance(value, str) or value not in KEYS[key][1]:
        raise BadRequest("That value is not allowed.")
    return ["config", "set", key, value]


def _delete_detail(args):
    _only(args, ("ticket",))
    ticket = args.get("ticket")
    if not isinstance(ticket, str) or not TID.fullmatch(ticket):
        raise BadRequest("That is not a ticket.")
    return ["record", "delete-detail", ticket, "--json"]


OPS = {"settings.set": _settings_set, "record.delete_detail": _delete_detail}


def build_argv(op, args) -> list[str]:
    """The argv after the orch command, for one op. Raises BadRequest for anything outside the table."""
    fn = OPS.get(op) if isinstance(op, str) else None
    if fn is None:
        raise BadRequest("That action is not available.")
    if not isinstance(args, dict):
        raise BadRequest("That request could not be read.")
    return fn(args)


def human_env(root: Path, orch_bin) -> dict:
    """environ without the agent tools' variables (orch.adapters.human_environ); refused when that list can not
    be read, so a click never runs with an agent's variables (fail closed)."""
    try:
        from orch.adapters import human_environ

        env = human_environ(os.environ)
    except Exception:  # noqa: BLE001 - an old orch or a bad adapter file
        raise Unavailable("orch could not check who is acting here. Fix that and try again.") from None
    env = {k: v for k, v in env.items() if k not in AGENT_VARS}
    return child_env({**env, "ORCH_ROOT": str(root)}, orch_bin)


def orch(
    root: Path,
    orch_bin,
    argv: list[str],
    proof: str | None = None,
    timeout: float | None = None,
    deadline=None,
):
    orch_bin = real_bin(orch_bin)
    env = human_env(root, orch_bin)
    timeout = WRITE_TIMEOUT if timeout is None else timeout
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0:
            return 124, "", ""
    try:
        if proof is not None:
            if run_with_proof is None:
                raise Unavailable("The orch command is not available here.")
            r = run_with_proof(argv, proof, orch_bin=orch_bin, cwd=root, env=env, timeout=timeout)
        else:
            r = _run(
                [*argv0(orch_bin), *argv], check=False, cwd=root, capture_output=True, text=True,
                timeout=timeout, stdin=subprocess.DEVNULL, env=env,
            )  # fmt: skip
    except subprocess.TimeoutExpired:
        return 124, "", ""
    except OSError:
        raise Unavailable("The orch command could not be started.") from None
    return r.returncode, r.stdout, r.stderr


def _parsed(stdout):
    try:
        out = json.loads(stdout)
    except (ValueError, TypeError, RecursionError):
        return None
    return out if isinstance(out, dict) else None


def _code(out) -> str | None:
    code = (out or {}).get("code")
    return code if isinstance(code, str) else None


def _clean_success(out) -> dict | None:
    """Only parsed, expected fields leave this server; the core's own output is never passed on (L2)."""
    if not isinstance(out, dict):
        return None
    clean: dict = {}
    for key, value in out.items():
        if (
            key in KEYS
            and isinstance(value, (bool, int, str))
            and len(str(value)) <= 20
            or key in ("changed", "widened")
            and isinstance(value, bool)
            or (
                key in ("deleted", "kept", "unreadable", "skipped")
                and isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value < 10**6
            )
            or key == "ticket"
            and isinstance(value, str)
            and TID.fullmatch(value)
        ):
            clean[key] = value
    return clean


def _answer(code, out, timeout_text) -> tuple[int, str, dict | None]:
    """The HTTP answer for one core exit: fixed texts only, never the core's own words or its stderr (L7)."""
    if code == 124:
        return 504, timeout_text, None  # the write may or may not have happened: say nothing about it (L8)
    if code == 0:
        return 200, "", _clean_success(out)
    why = _code(out)
    if why == "changed":
        return 409, CHANGED, None
    if why == "needs_person":
        return 403, PERSON, None
    return 422, MESSAGES.get(why, FAILED), None


def _with_person(root, orch_bin, argv, mint, need, timeout_text, deadline=None):
    """Run without a proof; only when the core says needs_person: mint (person here) and retry once."""
    code, stdout, _ = orch(root, orch_bin, argv, deadline=deadline)
    out = _parsed(stdout)
    if code != 0 and code != 124 and _code(out) == "needs_person":
        if mint is None:
            raise NeedsPerson(PERSON)
        code, stdout, _ = orch(root, orch_bin, argv, proof=mint(*need), deadline=deadline)
        out = _parsed(stdout)
    return _answer(code, out, timeout_text)


def _sharing_refusal(read) -> str | None:
    """Count sharing can not be turned on while the admin switched it off, there is no admin, or the
    counts can not be read (L9)."""
    clean = validated(read("record", "counts", "--days", "30", "--json"))
    state = clean["sharing"]["counts"] if clean else None
    if state in ("on", "off"):
        return None
    return SHARING_LOCKS.get(state, SHARING_UNKNOWN)


def _set(root, orch_bin, args, argv, mint, read, deadline):
    key, value = args["key"], args["value"]
    if key == "insights.share_counts" and value == "on":
        refusal = _sharing_refusal(read)
        if refusal:
            return 409, refusal, None
    observed = current_value(read("record", "settings", "--json"), key)
    if observed is None and mint is None:
        raise NeedsPerson(PERSON)  # an unreadable current value counts as widening (M6)
    allowed = KEYS[key][1]
    guard = [f"--if-current={observed}"] if isinstance(observed, str) and observed in allowed else []
    from orch.config import insights_target

    need = ("insights.settings", insights_target(key, value))
    return _with_person(root, orch_bin, [*argv, *guard, "--json"], mint, need, SET_TIMEOUT, deadline)


def run_op(
    root: Path, orch_bin, op, args, mint=None, read=lambda *argv: None
) -> tuple[int, str, dict | None]:
    """Run one op. Returns (http status, plain text, parsed json or None). `mint(op, target)` is given only when
    the request has the person; `read(*argv)` is the server's read of a CLI answer (None when it fails)."""
    argv = build_argv(op, args)
    if op == "settings.set":
        deadline = time.monotonic() + TOTAL_BUDGET
        if not _LOCK.acquire(timeout=LOCK_WAIT):
            return 503, BUSY, None
        try:
            return _set(root, orch_bin, args, argv, mint, read, deadline)
        finally:
            _LOCK.release()
    need = ("record.delete_detail", args["ticket"])
    return _with_person(root, orch_bin, argv, mint, need, DELETE_TIMEOUT, time.monotonic() + TOTAL_BUDGET)

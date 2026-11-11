"""What the Insights settings page may do: one fixed table of ops, each building exactly one `orch` argv.

No shell, no --by/--from/--as/--dev: who acts comes from the proof (H1, contracts/human-proof.md). Narrowing a
setting runs without a proof; widening and delete-detail need a proof minted by the page session, handed over as
the first line of stdin. Whether a change widens is decided here from a fresh read, never from the request.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .settings import KEYS, TID, current_value, needs_person

_run = subprocess.run  # tests may patch this name, never the global subprocess.run

PERSON = "Open Insights from the dashboard on this computer to do this."
AGENT_VARS = ("ORCH_AGENT", "ORCH_RUN", "ORCH_TICKET", "ORCH_DEV", "ORCH_BY", "ORCH_VIA")


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
    return ["config", "set", key, value, "--json"]


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


def proof_for(op, args, read_settings) -> tuple[str, str] | None:
    """(core op, target) when the click is the person's, else None. A failed read counts as widening."""
    if op == "record.delete_detail":
        return "record.delete_detail", args["ticket"]
    key, value = args["key"], args["value"]
    if needs_person(key, value, current_value(read_settings(), key)):
        return "insights.settings", key
    return None


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


def orch(root: Path, orch_bin, argv: list[str], proof: str | None = None, timeout: int = 60):
    orch_bin = real_bin(orch_bin)
    env = human_env(root, orch_bin)
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
        return 124, "", "That took too long. Please try again."
    except OSError:
        raise Unavailable("The orch command could not be started.") from None
    return r.returncode, r.stdout, r.stderr


def _parsed(stdout):
    try:
        out = json.loads(stdout)
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def run_op(
    root: Path, orch_bin, op, args, mint=None, read_settings=lambda: None
) -> tuple[int, str, dict | None]:
    """Run one op. Returns (http status, plain text, parsed json or None). Nothing runs without a needed proof."""
    argv = build_argv(op, args)
    need = proof_for(op, args, read_settings)
    if need and mint is None:
        raise NeedsPerson(PERSON)
    code, stdout, stderr = orch(root, orch_bin, argv, proof=mint(*need) if need else None)
    if code == 124:
        return 504, "That took too long. Please try again.", None
    out = _parsed(stdout)
    if code == 0:
        return 200, "", out
    msg = (out or {}).get("error")
    if not isinstance(msg, str) or not msg.strip():
        msg = (stderr.strip().splitlines() or ["That did not work."])[0].removeprefix("Refused: ")
    msg = msg.strip().splitlines()[0][:300] if msg.strip() else "That did not work."
    return (403 if (out or {}).get("code") == "needs_person" else 422), msg, None

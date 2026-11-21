"""A helper that starts on an API key (ORCH-659): the key goes only to that one helper, its spend is counted.

Whoever picks the source for a start (the Usage add-on, a person) passes a *credit* to `runs.start`:

    {"account": "<label of the credit, e.g. OpenAI credit>",
     "key": "<NAME of the key in this workspace's key store>",
     "why": "<one plain line: why this start runs there>"}

Only these three plain strings are kept (on the run record and the ticket). The value is read from the key
store by the run's wrapper right before each turn and handed to the helper process alone, the way its adapter
says (agents/*.json `api_key`):

  {"fd_env": NAME}   a pipe: the read end is passed to the helper, NAME holds its number, the value is written
                     into the pipe and the write end closed. A pipe is read once: anything the
                     helper starts later finds it empty. Never in the arguments, the environment or a file.
  {"env": NAME}      the helper process's environment only (for a tool whose shell leaves out *KEY* names).
                     The wrapper's own environment never holds it.
  "set": {..}        plain extra settings for the helper. Never one that changes what the helper may do: a
                     key start keeps the workspace's permission level like any start (ORCH-913: a setting that
                     strips credentials from its commands also forced one tool to ask for everything).
  "drop": [..]       sign-in names removed from the helper's environment, so the picked key is the only one.

Every read is recorded in the run's record as a key use (no value) before the helper starts; a use that cannot
be recorded stops the start. A start on a key always runs one step at a time (no live session: no environment
file, no "use this key?" question, and both tools print their spend there).

Spend comes from the helper's own output, one row per turn in `.orch/run/helper-spend.jsonl`
({"t", "id": "<run>:<turn>", "account", "ticket", "usd"}): a row with usd null is written before the turn and
replaced (a later row with the same id) by the reported dollars after it. A turn that reports nothing, or a
wrapper that was killed, leaves usd null: spend unknown, never 0. The adapter's `spend` says where:
result-cost = `total_cost_usd` of the turn's last result line; turn-tokens = tokens only (no model or price in
the output), so the dollars stay unknown and the tokens are noted. The Usage add-on's spend-log reader counts
the file.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from pathlib import Path

from orch import adapters, keystore
from orch.errors import Refused

SPEND_LOG = "helper-spend.jsonl"
LABEL_MAX = 64
VALUE_MAX = 4096  # far below a pipe's buffer, so writing it never waits on the helper
WHY_MAX = 200
_KEYNAME = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")
_ENVNAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _plain(text: object, n: int) -> str:
    s = " ".join(str(text or "").split())
    return "".join(c for c in s if c.isprintable())[:n].strip()


def spec(name: str, root: Path | None = None) -> dict | None:
    """The adapter's `api_key` block, checked; None when the tool cannot start on a key."""
    try:
        a = adapters.load(name, root)
    except Refused:
        return None
    s = a.get("api_key")
    if not isinstance(s, dict):
        return None
    fd_env, env = s.get("fd_env"), s.get("env")
    if bool(fd_env) == bool(env) or not _ENVNAME.match(str(fd_env or env)):
        return None
    sets = s.get("set") or {}
    drop = s.get("drop") or []
    if not isinstance(sets, dict) or not all(
        _ENVNAME.match(str(k)) and isinstance(v, str) for k, v in sets.items()
    ):
        return None
    if not isinstance(drop, list) or not all(isinstance(d, str) and _ENVNAME.match(d) for d in drop):
        return None
    return {"fd_env": fd_env, "env": env, "set": dict(sets), "drop": list(drop), "spend": s.get("spend")}


def check(root: Path, name: str, credit: dict) -> dict:
    """The credit as it is kept: three plain strings. Refused (plain words) when asked from inside a helper,
    the tool cannot start on a key, the name is not a key-store name, or this workspace has no such token.
    The value is never read here."""
    check_starter()
    if not isinstance(credit, dict):
        raise Refused("A start on an API key needs the credit's name and its key's name.")
    account = _plain(credit.get("account"), LABEL_MAX)
    key = str(credit.get("key") or "")
    why = _plain(credit.get("why"), WHY_MAX)
    if not account:
        raise Refused("A start on an API key needs the credit's name (as Usage shows it).")
    if not _KEYNAME.match(key):
        raise Refused("A start on an API key needs the name of a key in this workspace's key store.")
    s = spec(name, root)
    if s is None or (s["fd_env"] and os.name == "nt"):
        label = name
        with contextlib.suppress(Refused):
            label = adapters.load(name, root)["label"]
        raise Refused(f"{label} cannot start on an API key here.")
    rows = {r["name"]: r for r in keystore.list_keys(root) if r.get("state") != "shadowed"}
    if key not in rows:
        raise Refused(f"There is no key named {key} in this workspace's key store.")
    if rows[key].get("type") != "token":
        raise Refused(f"The key {key} is not stored as a token, so it is not an API key.")
    return {"account": account, "key": key, "why": why}


INSIDE_HELPER = (
    "A helper cannot start another helper on an API key. Only a person, or orch itself when Usage picks a "
    "credit, can."
)


def check_starter() -> None:
    """A start on a key is never asked for from inside a helper (its tool's environment, or an orch run named
    in the environment): otherwise any helper could hand any token of the store to a tool of its choice. A
    person in a terminal and orch's own background starters (no tool, no run) may."""
    from orch import tickets

    if tickets.agent_tool() is not None or os.environ.get("ORCH_RUN") or os.environ.get("ORCH_TICKET"):
        raise Refused(INSIDE_HELPER)


def start_line(credit: dict) -> str:
    """The ticket's line at the start, e.g. 'Runs on OpenAI credit: review work, 12 of 100 dollars used.'"""
    why = credit.get("why")
    return (
        f"Runs on {credit['account']}"
        + (f": {why}" if why else "")
        + ("" if (why or "").endswith(".") else ".")
    )


def _record_use(root: Path, run: str, tid: str, key: str, program: str, action: str) -> None:
    """The key use in the run's record, without the value, before the helper starts (secretrun's writer)."""
    from orch import hider, secretrun

    saved = {k: os.environ.get(k) for k in ("ORCH_RUN", "ORCH_TICKET")}
    os.environ["ORCH_RUN"], os.environ["ORCH_TICKET"] = run, tid
    try:
        h = hider.Hider(keystore.all_needles(root) or {"orch-no-keys": "x" * 32})
        secretrun.Recorder(root, h, action, "helper-start", program).record(key)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class Handoff:
    """One turn's handing over: `env` for the helper, `pass_fds` for Popen, `after_spawn()` writes the value
    into the pipe and closes both ends in this process, `close()` cleans up what is left (always call it)."""

    def __init__(
        self,
        env: dict,
        pass_fds: tuple = (),
        value: str | None = None,
        r: int | None = None,
        w: int | None = None,
    ):
        self.env, self.pass_fds = env, pass_fds
        self._value, self._r, self._w = value, r, w
        self.secret = value  # kept until the turn's output is scrubbed (forget()), then dropped

    def after_spawn(self) -> None:
        if self._r is not None:
            os.close(self._r)
            self._r = None
        if self._w is not None:
            try:
                data = self._value.encode("utf-8")
                while data:  # a key is far below the pipe's buffer; the loop only guards a short write
                    data = data[os.write(self._w, data) :]
            except OSError:
                pass  # the helper went away: it then has no key and says so itself
            finally:
                os.close(self._w)
                self._w = None
        self._value = None

    def close(self) -> None:
        for fd in (self._r, self._w):
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
        self._r = self._w = None
        self._value = None

    def forget(self) -> None:
        self.secret = None


def handoff(root: Path, run: str, tid: str, name: str, credit: dict, env: dict, program: str) -> Handoff:
    """Read the key and prepare the helper's environment for one turn. Refused when the key cannot be read or
    its use cannot be recorded; then the helper does not start."""
    s = spec(name, root)
    if s is None:
        raise Refused("This helper cannot start on an API key here.")
    if s["fd_env"] and os.name == "nt":
        raise Refused("This helper can take an API key only on macOS or Linux for now.")
    _record_use(root, run, tid, credit["key"], program, "env" if s["env"] else "exec")
    value = keystore.get_value(root, credit["key"])
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            raise Refused(f"The key {credit['key']} is a file, not an API key.") from None
    value = value.strip()
    if not value or "\n" in value or "\0" in value or len(value) > VALUE_MAX:
        raise Refused(f"The key {credit['key']} is not one short line, so it is not an API key.")
    out = {k: v for k, v in env.items() if k not in s["drop"] and k not in (s["fd_env"], s["env"])}
    out.update(s["set"])
    if s["env"]:
        out[s["env"]] = value
        h = Handoff(out)
        h.secret = value
        return h
    r, w = os.pipe()
    os.set_inheritable(r, True)
    out[s["fd_env"]] = str(r)
    return Handoff(out, (r,), value, r, w)


def no_core_dumps() -> None:
    """A wrapper that holds a key leaves no memory dump when it crashes (best effort)."""
    with contextlib.suppress(Exception):
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def redact(text: str, value: str | None) -> str:
    return text.replace(value, "[key hidden]") if value and value in text else text


def scrub_log(log: Path, start: int, value: str | None) -> None:
    """The turn's part of the run log without the key handed to it, should the helper have printed it (the run
    log is private; this keeps it out of what is shown from it). The value handed over, not the store's
    current one: a key changed meanwhile is still hidden."""
    if not value:
        return
    try:
        with open(log, "r+b") as f:
            f.seek(start)
            tail = f.read()
            if value.encode() not in tail:
                return
            f.seek(start)
            f.truncate()
            f.write(tail.replace(value.encode(), b"[key hidden]"))
    except OSError:
        pass


# ---- spend ---------------------------------------------------------------------------------------------


def _lines(out: str):
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            yield d


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def turn_spend(name: str, out: str, root: Path | None = None) -> dict:
    """{"usd": dollars | None (unknown), "tokens": n | None} of one turn, from the helper's own output."""
    s = spec(name, root) or {}
    how = s.get("spend")
    if how == "result-cost":  # the turn's last result line says what this process cost
        usd = None
        for d in _lines(out):
            if d.get("type") == "result":
                usd = _num(d.get("total_cost_usd"))
        return {"usd": round(usd, 6) if usd is not None else None, "tokens": None}
    if how == "turn-tokens":  # tokens of each completed turn, no price in the output
        total, seen = 0, False
        for d in _lines(out):
            u = d.get("usage") if d.get("type") == "turn.completed" else None
            if isinstance(u, dict):
                for k in ("input_tokens", "output_tokens"):
                    n = u.get(k)
                    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
                        total, seen = total + n, True
        return {"usd": None, "tokens": total if seen else None}
    return {"usd": None, "tokens": None}


def _log_path(root: Path) -> Path:
    return Path(root) / ".orch" / "run" / SPEND_LOG


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_spend(
    root: Path, row_id: str, tid: str, credit: dict, usd: float | None, tokens: int | None = None
) -> None:
    """One row of the spend log (appended; the last row of an id counts). Never a key."""
    row = {"t": _now(), "id": row_id, "account": credit["account"], "ticket": tid, "usd": usd}
    if tokens is not None:
        row["tokens"] = tokens
    p = _log_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(p, flags, 0o600)
    try:
        os.write(
            fd, (json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8")
        )  # one write: no torn rows
    finally:
        os.close(fd)


def money(usd: float) -> str:
    return f"{usd:.2f}" if usd >= 0.01 or usd == 0 else f"{usd:.4f}".rstrip("0")


def end_line(credit: dict, turns: list[dict]) -> str:
    """The ticket's line at the end of a run on a key."""
    known = [t["usd"] for t in turns if t.get("usd") is not None]
    unknown = len(turns) - len(known)
    tokens = sum(t.get("tokens") or 0 for t in turns)
    acc = credit["account"]
    if turns and not unknown:
        return f"Spent {money(sum(known))} dollars on {acc}."
    tok = f" It used {tokens:,} tokens." if tokens else ""
    if not known:
        return f"Spend on {acc} unknown: the helper did not report it in dollars.{tok}"
    return (
        f"Spent at least {money(sum(known))} dollars on {acc}; "
        f"{unknown} of {len(turns)} steps did not report their spend.{tok}"
    )

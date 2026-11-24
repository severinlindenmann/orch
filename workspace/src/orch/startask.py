"""Before a helper starts, ask the add-ons that want to be asked (manifest `before_start = true`) which
tool, model and account to use, or whether the start should wait (contracts/before-start.schema.json).

The core names no add-on. Without such an add-on nothing is called and a start is exactly as before. An
add-on that does not answer in time, fails or answers something else leaves the start as it is, with one
note. A person's own choice (the tool given for this start, a model a person set on the ticket) is never
changed by an answer.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from orch import addons, tickets

TIMEOUT = 15.0  # seconds; an add-on may switch an account before it answers
MAX_OUT = 64 * 1024
WHY_MAX = 200
SAY_MAX = 200
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


class Wait(Exception):
    """An add-on said the start should wait: `why` in plain words, `until` an ISO time or None."""

    def __init__(self, name: str, why: str, until: str | None):
        super().__init__(why)
        self.name, self.why, self.until = name, why, until


def askers(root: Path) -> dict[str, dict]:
    return {n: m for n, m in sorted(addons.active_manifests(root).items()) if m.get("before_start")}


def request(
    root: Path,
    tid: str,
    by: str,
    mode: str | None,
    agent: str,
    agent_given: bool,
    agents: list[str],
    credit: dict | None = None,
) -> dict:
    """What the add-on gets on stdin: the ticket's plain facts (no history, no note), the start and the
    choices. A start on an API key also names its credit (the label only, never the key's name)."""
    from orch import adapters, modelpick

    t = tickets.load(root, tid)
    cur = modelpick.chosen(t)
    active = set(addons.active_manifests(root))
    return {
        "schema": "orch.before-start/1",
        "ticket": t["id"],
        "key": t.get("key"),
        "title": t.get("title", ""),
        "parent": t.get("parent"),
        "manager": t.get("manager") is True,
        "chat": t.get("general") is True,
        "ext": {k: v for k, v in (t.get("ext") or {}).items() if k in active},
        "by": by,
        "mode": mode,
        "agent": agent,
        "agents": agents,
        "model": cur["name"] if cur else None,
        "model_up": modelpick.moved_up(t),
        "providers": adapters.providers(agents, root),
        "chosen": {"agent": agent_given, "model": bool(cur) and modelpick.by_person(t)},
        **({"credit": {"account": str(credit.get("account") or "")[:64]}} if credit else {}),
    }


def _clean(text: object, n: int) -> str:
    s = " ".join(str(text or "").split())
    return "".join(c for c in s if c.isprintable())[:n].strip()


def _ask(root: Path, name: str, m: dict, req: dict) -> dict | None:
    env = {**os.environ, "ORCH_ADDON": name, "ORCH_ROOT": str(root), "ORCH_BIN": addons.orch_bin()}
    try:
        r = subprocess.run(
            [sys.executable, "-P", "-m", m["run"], "before-start", "--json"],
            cwd=root,
            env=env,
            input=json.dumps(req),
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        if r.returncode != 0 or len(r.stdout) > MAX_OUT:
            return None
        data = json.loads(r.stdout)
    except (subprocess.SubprocessError, OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("go"), bool):
        return None
    return data


def ask(
    root: Path,
    tid: str,
    by: str,
    mode: str | None,
    agent: str,
    agent_given: bool,
    credit: dict | None = None,
) -> tuple[dict, list[str]]:
    """{"agent"?, "model"?, "account"?} to use for this start and the notes to show. Raises Wait.
    credit: a start on an API key ({"account": label, ...}); the request names it, so an add-on can refuse
    it."""
    from orch import adapters, modelpick

    names = askers(root)
    if not names:
        return {}, []
    found = [r["name"] for r in adapters.detect(versions=False) if r.get("found")]
    if agent not in found:
        found.append(agent)
    req = request(root, tid, by, mode, agent, agent_given, found, credit)
    out: dict = {}
    notes: list[str] = []
    for name, m in names.items():
        ans = _ask(root, name, m, req)
        if ans is None:
            notes.append(f"{name} did not answer before the start; the helper starts as usual.")
            continue
        say = _clean(ans.get("say"), SAY_MAX)
        if ans["go"] is False:
            why = _clean(ans.get("why"), WHY_MAX) or f"{name} says this work has to wait."
            until = ans.get("until") if isinstance(ans.get("until"), str) else None
            if until and not _TIME.fullmatch(until):
                until = None
            raise Wait(name, why, until)
        a = ans.get("agent")
        if isinstance(a, str) and _NAME.fullmatch(a) and a != req["agent"]:
            if agent_given:
                pass  # the tool given for this start stays
            elif a in found and "agent" not in out:
                out["agent"] = a
            else:
                notes.append(f"{name} asked for a helper tool that is not set up here; using the usual one.")
        mo = ans.get("model")
        if (
            isinstance(mo, str)
            and mo in modelpick.MODELS
            and not req["chosen"]["model"]
            and "model" not in out
        ):
            out["model"] = mo
        acc = _clean(ans.get("account"), 64)
        if acc and "account" not in out:
            out["account"] = acc
        if say:
            notes.append(say)
    return out, notes


def hold(root: Path, tid: str, w: Wait) -> None:
    """The ticket shows Waiting with the reason. With a time, the usual time wake starts it again."""
    if w.until:
        until = w.until

        def op(ticket):
            ticket["status"] = "waiting"
            ticket["waiting_on"] = {"kind": "time", "until": until, "ref": w.why}
            tickets.add_history(ticket, f"agent:{w.name}", f"Waiting: {w.why}")
    else:

        def op(ticket):
            ticket["status"] = "waiting"
            ticket["waiting_on"] = {"kind": "external", "ref": w.why}
            tickets.add_history(ticket, f"agent:{w.name}", f"Waiting: {w.why}")

    w_now = (tickets.load(root, tid).get("waiting_on") or {}).get("ref")
    if w_now == w.why:
        return  # already waiting for this reason: one history line, not one per try
    tickets.apply_op(root, tid, op, by=f"agent:{w.name}")

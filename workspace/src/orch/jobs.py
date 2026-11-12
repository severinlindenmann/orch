"""Job ingest (contracts/job-events.md): what a long-running program reports about itself.

An agent or a wrapper calls `orch job …` (cli_job) and every call ends here. What this module guarantees:
- everything a job says is *reported by the job*: it never marks anything checked, answers a question or
  approves (the input schema refuses `by`, `seq`, `ticket`, `pid`, `command`; `lost` is written by orch only);
- the call is bound to its run the same way as the record hook (record_hook.require_run: ORCH_RUN +
  ORCH_TICKET name a live claim AND the caller sits inside the claim's process tree); a job belongs to
  exactly one run;
- every string passes the value hider before anything is stored; without a registered hider nothing is
  written;
- an entry is validated against job-event.schema.json (and its tables against blocks.schema.json) after
  hiding; an invalid one is refused with plain words and never stored raw;
- one writer per job (the per-run record lock), state machine and caps of the contract, strict reads;
- stored through record.append_job (the hardened I/O core of the record), never with raw file access here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from orch import record, record_hook, safefile
from orch.errors import Refused

EVENT_CAP = 2000  # stored events per job
JOBS_PER_RUN = 200
INPUT_BYTES = 8 * 1024
LOG_CHARS = 500
QUIET_DEFAULT = 10  # minutes
ACTIVITY_PROGRESS_SECONDS = 5
MORE = "More events were left out."
_FINAL = ("ok", "failed", "cancelled", "lost")
_NOT_ALLOWED_FIELDS = ("by", "seq", "ticket", "pid", "command", "token_hash", "capped")
_MESSAGES = {
    "other_run": "this job belongs to another run.",
    "not_started": "this job has not been started.",
    "already_started": "this job has already been started.",
    "ended": "this job has already ended.",
    "step_finished": "that step is finished and cannot go back.",
    "invalid": "this job entry is not valid.",
    "too_large": "this job entry is too large.",
    "cap": "this job has reached its limit of entries.",
    "not_allowed": "a job cannot report that.",
    "not_active": "this run is not active, so nothing was recorded.",
    "hider_off": "recording is off until key hiding is ready.",
    "no_run": "`orch job` works inside an orch run; a job outside a run is not built yet.",
    "token": "this job needs its write key (ORCH_JOB_TOKEN, given once by `orch job start`).",
    "no_job": "say which job: --job <id> or ORCH_JOB.",
    "not_found": "there is no such job.",
}


class JobError(Refused):
    """A refusal with a contract error code (`{"error", "code"}`, exit 2); the message is plain words."""

    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or _MESSAGES[code])
        self.code = code
        self.extra = {"code": code}


def _load(name):
    return json.loads((Path(__file__).with_name(name)).read_text(encoding="utf-8"))


_BLOCKS, _SCHEMA = _load("blocks.schema.json"), _load("job_event.schema.json")
_REGISTRY = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in (_BLOCKS, _SCHEMA)])
_STORED = Draft202012Validator(_SCHEMA, registry=_REGISTRY, format_checker=FormatChecker())
_INPUT = Draft202012Validator(
    {"$ref": _SCHEMA["$id"] + "#/$defs/input"}, registry=_REGISTRY, format_checker=FormatChecker()
)


def _fields() -> dict[str, set[str]]:
    out = {}
    for part in _SCHEMA["$defs"]["payload"]["allOf"]:
        name = part["if"]["properties"]["type"]["const"]
        out[name] = set(part["then"]["properties"])
    out.pop("lost", None)
    out["start"] -= {"token_hash", "pid", "command"}
    out["log"] -= {"capped"}
    return out


_FIELDS = _fields()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_job_id() -> str:
    return "j_" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(10))


# --- the state machine (the same rules as contracts/validate.py job_replay) ---
def state_of(events: list[dict]) -> str | None:
    state = None
    for ev in events:
        if ev["type"] == "start":
            state = "running"
        elif ev["type"] == "end":
            state = ev["status"]
        elif ev["type"] == "lost":
            state = "lost"
    return state


def is_quiet(events: list[dict], now: datetime) -> bool:
    """A running job with no event for `quiet_minutes` (from `start`) is lost (job-events.md)."""
    if state_of(events) != "running":
        return False
    minutes = events[0].get("quiet_minutes", QUIET_DEFAULT)
    return now - _time(events[-1]["at"]) >= timedelta(minutes=minutes)


def _steps(events: list[dict]) -> dict[str, str]:
    steps: dict[str, str] = {}
    for ev in events:
        if ev["type"] == "step":
            steps[ev["step"]] = ev["state"]
    return steps


def _rule(events: list[dict], ev: dict, cap: int) -> str | None:
    """The refusal code of this (already valid) event against the stored stream, or None."""
    state = state_of(events)
    if state is None and ev["type"] != "start":
        return "not_started"
    if state in _FINAL:
        return "ended"
    if ev["type"] == "start" and state is not None:
        return "already_started"
    if ev["type"] != "end" and len([e for e in events if e["type"] != "lost"]) >= cap:
        return "cap"
    if ev["type"] == "step" and _steps(events).get(ev["step"]) in ("done", "failed", "skipped"):
        return "step_finished"
    if ev["type"] == "progress" and ev.get("total") is not None and ev["done"] > ev["total"]:
        return "invalid"
    return None


# --- building an event ---
def _plain_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise JobError("invalid")
    return value


def _ids(environ) -> tuple[str, str]:
    run, ticket = environ.get("ORCH_RUN"), environ.get("ORCH_TICKET")
    if not run or not ticket:
        raise JobError("no_run")
    return run, ticket


def _prove(root, ids) -> None:
    try:
        record_hook.require_run(root, ids)
    except record_hook.NotRecorded as e:
        if e.reason in record.UNPROVEN_REASONS:
            record.note_unattributed(root, e.reason)
        raise JobError("not_active", e.note) from None


def _writer(root):
    try:
        return record_hook.record_writer(root)
    except record.RecordOff:
        raise JobError("hider_off") from None


def _hidden(writer, inp: dict) -> dict:
    """The input after the value hider (every string and key, every encoded form), with a log text cut."""
    try:
        out = writer.hider.hide_json(inp)
        if isinstance(out.get("text"), str) and out.get("type") == "log":
            out["text"] = writer.hider.hide_cut(out["text"], LOG_CHARS)
        line = json.dumps(out, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if writer.hider.hide_text(line) != line:
            raise JobError("invalid")
        return out
    except (ValueError, TypeError, RecursionError):
        raise JobError("invalid") from None


def _artifact_exists(root, path: str, ticket: str) -> bool:
    try:
        m = re.fullmatch(r"\.orch/tickets/(t_[a-z0-9]{6,16})/artifacts/(.+)", path)
        if m:
            if m[1] != ticket:
                return False
            return safefile.read_ticket_file(root, m[1], "artifacts", m[2], 1) is not None
        return safefile.open_file_ref(root, path, 1) is not None
    except safefile.TooLarge:
        return True


def validate_input(inp) -> dict:
    """The refusal rules of one input line, before anything else is looked at."""
    if not isinstance(inp, dict):
        raise JobError("invalid")
    try:
        size = len(json.dumps(inp, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (ValueError, TypeError, RecursionError):
        raise JobError("invalid") from None
    if size > INPUT_BYTES:
        raise JobError("too_large")
    if any(k in inp for k in _NOT_ALLOWED_FIELDS) or inp.get("type") == "lost":
        raise JobError("not_allowed")
    allowed = _FIELDS.get(inp.get("type"))
    if allowed is None or not set(inp) <= allowed | {"type", "job", "run"}:
        raise JobError("invalid")  # a field the contract does not name is never stored
    return inp


# --- ingest ---
def _text_of(ev: dict, events: list[dict]) -> str:
    title = events[0]["title"] if events else ev.get("title", "Job")
    kind = ev["type"]
    if kind == "start":
        text = ev["title"]
    elif kind == "step":
        text = f"{title}: {ev['label']} ({ev['state']})"
    elif kind == "progress":
        total = ev.get("total")
        text = f"{title}: {ev['done']:g} of {total:g}" if total is not None else f"{title}: {ev['done']:g}"
        if ev.get("unit"):
            text += f" {ev['unit']}"
    elif kind == "artifact":
        text = f"{title}: file {ev.get('label') or ev['path']}"
    elif kind == "metric":
        text = f"{title}: {ev['name']} {ev['value']:g}" + (f" {ev['unit']}" if ev.get("unit") else "")
    elif kind == "table":
        text = f"{title}: {ev['table'].get('title') or 'table'}"
    elif kind == "link":
        text = f"{title}: {ev['label']}"
    elif kind == "end":
        text = f"{title}: {ev['status']}" + (f" ({ev['summary']})" if ev.get("summary") else "")
    else:  # lost
        text = f"{title}: lost ({ev['reason']})"
    return " ".join(text.split())[:480]


def _activity(writer, ev: dict, events: list[dict]) -> None:
    from orch import tickets

    tool = tickets.agent_tool()
    state = state_of([*events, ev])
    writer.append(
        {
            "run": ev["run"],
            "session": None,
            "agent": "main",
            "parent": None,
            "at": ev["at"],
            "ticket": ev["ticket"],
            "harness": tool
            if isinstance(tool, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,31}", tool)
            else "generic",
            "coverage": "full",
            "via": "job",
            "kind": "job",
            "text": _text_of(ev, events),
            "used": None,
            "outcome": None,
            "detail": None,
            "data": {"job": ev["job"], "type": ev["type"], "state": state},
        }
    )


def _wants_activity(ev: dict, events: list[dict]) -> bool:
    if ev["type"] == "log":
        return False
    if ev["type"] != "progress":
        return True
    last = [e for e in events if e["type"] == "progress"]
    return not last or _time(ev["at"]) - _time(last[-1]["at"]) >= timedelta(seconds=ACTIVITY_PROGRESS_SECONDS)


def ingest(root, inp, *, environ=None, job=None, now=None, token=None) -> dict:
    """Store one event of a job (type start makes the job) and return the stored event.

    `inp` is one `$defs/input` object (what a program may write). Raises JobError (plain words, contract
    code) for every refusal; a refused entry is never stored. `start` returns the job's write token once
    (key `token`, never stored); every other type must present it (`token` or ORCH_JOB_TOKEN)."""
    environ = os.environ if environ is None else environ
    inp = validate_input(inp)
    run, ticket = _ids(environ)
    if inp.get("run", run) != run:
        raise JobError("other_run")
    _prove(root, (run, ticket))
    writer = _writer(root)
    is_start = inp.get("type") == "start"
    job_id = job or environ.get("ORCH_JOB")
    if inp.get("job") is not None and job_id and inp["job"] != job_id:
        raise JobError("other_run")
    job_id = job_id or inp.get("job")
    if is_start:
        if job_id:  # a job id is made by orch at start: naming one means the job is already there
            _check_job_id(job_id)
            raise JobError("already_started" if (run, job_id) in _all(root, run) else "invalid")
        job_id = new_job_id()
    if not job_id:
        raise JobError("no_job")
    body = _hidden(writer, {k: v for k, v in inp.items() if k not in ("job", "run")})
    if body.get("type") == "start" and body.get("quiet_minutes") is None:
        body.pop("quiet_minutes", None)
    if not _INPUT.is_valid(body):
        raise JobError("invalid")
    token = token or environ.get("ORCH_JOB_TOKEN")
    minted = secrets.token_hex(16) if is_start else None
    at = _now() if now is None else now.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        _check_job_id(job_id)
        if not is_start:
            _known(root, run, job_id)
        elif len(_all(root, run)) >= JOBS_PER_RUN:
            raise JobError("cap")
        ctx: dict = {}
        if is_start:
            body["token_hash"] = _hash(minted)

        def decide(events, size):
            ev = {
                "v": 1,
                **body,
                "job": job_id,
                "run": run,
                "ticket": ticket,
                "seq": len(events) + 1,
                "at": at,
            }
            if events and not hmac.compare_digest(
                _hash(token) if isinstance(token, str) else "", str(events[0].get("token_hash"))
            ):
                raise JobError("token")
            if events and is_quiet(events, _time(at)):
                lost = {
                    "v": 1,
                    "type": "lost",
                    "job": job_id,
                    "run": run,
                    "ticket": ticket,
                    "by": "orch",
                    "seq": len(events) + 1,
                    "at": at,
                    "reason": "quiet",
                }
                ctx.update(events=events, ev=lost, refuse="ended")
                return lost, False, None
            if body["type"] == "artifact" and not _artifact_exists(root, body["path"], ticket):
                raise JobError("invalid", "that file does not exist in this workspace.")
            code = _rule(events, ev, EVENT_CAP)
            if code is None and ev["type"] != "end" and size + 2048 > record.JOB_BYTES - 16384:
                code = "cap"
            if code == "cap":
                if any(e.get("capped") for e in events):
                    raise JobError("cap")
                more = {
                    "v": 1,
                    "type": "log",
                    "stream": "out",
                    "text": MORE,
                    "capped": True,
                    "job": job_id,
                    "run": run,
                    "ticket": ticket,
                    "seq": len(events) + 1,
                    "at": at,
                }
                ctx.update(events=events, ev=None, refuse="cap")
                return more, False, None
            if code is not None:
                raise JobError(code)
            if not _STORED.is_valid(ev):
                raise JobError("invalid")
            replace = (
                ev["type"] == "progress"
                and events[-1]["type"] == "progress"
                and events[-1]["at"] == at
                and size <= record.JOB_REPLACE_BYTES
            )
            if replace:
                ev["seq"] = events[-1]["seq"]
                events = events[:-1]
            ctx.update(events=events, ev=ev, refuse=None, want=not replace and _wants_activity(ev, events))
            return ev, replace, None

        record.append_job(
            root, run, job_id, decide, valid=_STORED.is_valid, max_jobs=JOBS_PER_RUN if is_start else None
        )
    except record.RecordRefused as e:
        raise JobError(getattr(e, "code", "invalid"), str(e)) from None
    if ctx["refuse"] and ctx["ev"] is None:
        raise JobError(ctx["refuse"])
    stored = ctx["ev"]
    try:
        if stored is not None and (ctx["refuse"] or ctx["want"]):
            _activity(writer, stored, ctx["events"])
    except record.RecordRefused:
        # the job line is stored; leave a gap marker under the (proven) run and say so
        record.note_lost(root, run, "job_activity")
        sys.stderr.write("orch: the job entry was saved, but it could not be added to the run's record.\n")
    if ctx["refuse"]:
        raise JobError(ctx["refuse"])
    shown = {k: v for k, v in stored.items() if k != "token_hash"}
    return {**shown, "token": minted} if is_start else shown


def _check_job_id(job_id) -> None:
    if not isinstance(job_id, str) or not re.fullmatch(r"j_[a-z0-9]{6,32}", job_id):
        raise JobError("invalid", "that is not a job id.")


def _all(root, run=None) -> list[tuple[str, str]]:
    got = record.list_jobs(root, run)
    if got.status != "ok":
        raise (
            record.RecordTampered(got.reason)
            if got.status == "tampered"
            else record.RecordUnavailable(got.reason)
        )
    return got.value


def _known(root, run: str, job_id: str) -> None:
    """The job exists in this run, else other_run (it exists in another run) or not_started."""
    if (run, job_id) in _all(root, run):
        return
    raise JobError("other_run" if any(j == job_id for _, j in _all(root)) else "not_started")


# --- reads ---
def summary(events: list[dict]) -> dict:
    first, last = events[0], events[-1]
    progress = [e for e in events if e["type"] == "progress"]
    return {
        "job": first["job"],
        "run": first["run"],
        "ticket": first["ticket"],
        "title": first.get("title"),
        "state": state_of(events),
        "events": len(events),
        "started_at": first["at"],
        "last_at": last["at"],
        "progress": {k: progress[-1][k] for k in ("done", "total", "unit") if k in progress[-1]}
        if progress
        else None,
        "reported_by": "job",
    }


def list_jobs(root, *, run=None, ticket=None) -> dict:
    """{"status", "jobs": [...]}: a stream that cannot be read is an explicit marker row, never left out."""
    try:
        pairs = _all(root, run)
    except record.RecordRefused as e:
        raise JobError(e.code, str(e)) from None
    rows = []
    for r, j in pairs:
        got = record.read_job(root, r, j, valid=_STORED.is_valid, seen_by="cli")
        if got.status != "ok":
            rows.append(
                {"job": j, "run": r, "status": got.status, "reason": got.reason, "message": got.message}
            )
        elif got.value and (ticket is None or got.value[0]["ticket"] == ticket):
            rows.append({"status": "ok", **summary(got.value)})
        elif not got.value and ticket is None:
            rows.append(
                {"job": j, "run": r, "status": "unavailable", "reason": "empty", "message": "No entries yet."}
            )
    return {"status": "ok", "jobs": rows}


def show_job(root, job_id: str) -> dict:
    _check_job_id(job_id)
    try:
        run = next((r for r, j in _all(root) if j == job_id), None)
    except record.RecordRefused as e:
        raise JobError(e.code, str(e)) from None
    if run is None:
        raise JobError("not_found")
    got = record.read_job(root, run, job_id, valid=_STORED.is_valid, seen_by="cli")
    if got.status != "ok":
        raise JobError("tampered" if got.status == "tampered" else "not_available", got.message)
    if not got.value:
        raise JobError("not_found")
    events = [{k: v for k, v in e.items() if k != "token_hash"} for e in got.value]
    return {"status": "ok", "job": summary(got.value), "events": events}

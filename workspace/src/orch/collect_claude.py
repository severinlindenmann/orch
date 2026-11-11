"""Map the agent tool's stream-json stdout lines to activity events and full detail payloads.

The oneshot wrapper (runs.wrap, via run_record.collect_turn) feeds each stdout line of
its stream_args run to collect. hook_line maps the tool's own hook payload for
`orch record hook` the same way, so both lines of one tool call share the id and
dedupe (adapters.collector picks this module). An optional mapper hider transforms events only;
detail payloads are returned UNHIDDEN. The collector never hides: RecordWriter
must hide both events and details and refuse writes when hiding is unavailable.
"""

import json
import math
import re
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from .collect_execjson import _hash, _hide, _now, _one_line, detail_name
from .record import RecordInvalid
from .record_files import workspace_files

# Tools whose input names the file or folder they touch (activity.md, Files).
_FILE_TOOLS = ("Read", "Edit", "Write", "NotebookEdit", "Glob", "Grep")
HELPER_TOOLS = ("Task", "Agent")  # a call starts a helper (helper.start/end, numbered h_<n> by the log)
# the hook events wired to `orch record hook` (agents/reminder.json, record_hooks)
HOOK_EVENTS = ("PreToolUse", "PostToolUse")


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _name(value: Any) -> str:
    return re.sub(r"[<>\x00-\x1f\x7f]", "", str(value or ""))[:128] or "Tool"


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value) is not None


def _used(kind: str, name: str, source: str, action: str | None = None) -> dict:
    return dict(kind=kind, name=_name(name), action=action, source=source, version=None)


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        )
    return ""


def describe_tool(name: str, inp: dict) -> tuple[dict, Any]:
    """(used, text) of one tool call that is not a helper start: the same for the log and the hook, so the
    two lines of one tool call agree."""
    if name.startswith("mcp__") and len(parts := name.split("__", 2)) == 3:
        used = _used("mcp", parts[1], "harness", _name(parts[2]))
    elif name == "Skill":
        used = _used("skill", inp.get("skill"), "harness")
    else:
        used = _used("tool", name, "builtin")
    if inp.get("description"):
        return used, inp["description"]
    if name == "Bash":
        command = str(inp.get("command") or "").splitlines()
        return used, "Run " + (command[0] if command else "")
    verb = {"Grep": "Search", "Glob": "Find files"}.get(name, name)
    path = next((inp[k] for k in ("file_path", "path", "pattern", "url") if inp.get(k)), "")
    return used, f"{verb} {PurePosixPath(str(path)).name}" if path else verb


def tool_paths(name: str, inp: dict) -> list | None:
    """The raw paths a file tool names (the caller makes them workspace-relative), None for other tools."""
    return [inp.get(k) for k in ("file_path", "notebook_path", "path")] if name in _FILE_TOOLS else None


def hook_line(raw: dict) -> dict | None:
    """The tool's own hook payload (hook_event_name, tool_name, tool_input, tool_use_id; PostToolUse adds
    tool_response) as the event line `orch record hook` takes: a step whose id is the tool-call id, so the
    hook line and the collector's line of one tool call dedupe. PreToolUse: no outcome, no detail;
    PostToolUse (only sent for a call that worked): ok, with input and output as the detail. None: a helper
    start (Task/Agent), left to the log (only the log knows the helper's number). ValueError: not a tool-call
    payload."""
    event = raw.get("hook_event_name")
    tid = raw.get("tool_use_id")
    if event not in HOOK_EVENTS or not isinstance(tid, str) or not tid:
        raise ValueError("not a tool-call hook payload")
    name = raw.get("tool_name")
    name = name if isinstance(name, str) else "Tool"
    if name in HELPER_TOOLS:
        return None
    inp = raw.get("tool_input")
    inp = inp if isinstance(inp, dict) else {}
    used, text = describe_tool(name, inp)
    line = dict(kind="step", id=tid, used=used, text=_one_line(text), outcome=None)
    session = raw.get("session_id")
    if isinstance(session, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", session):
        line["session"] = session
    paths = tool_paths(name, inp)
    if paths is not None:
        line["files"] = paths
    if event == "PostToolUse":
        line["outcome"] = dict(ok=True, error=None, ms=None)
        line["payload"] = {"input": inp, "output": raw.get("tool_response")}
    return line


class StreamJsonMapper:
    def __init__(
        self,
        run: str,
        ticket: str,
        harness: str,
        now: Callable[[], str] = _now,
        hider: Callable[[str], str] | None = None,
        seq_start: int = 0,
        helper_start: int = 0,
        workspace: str | Path | None = None,
    ):
        """`seq_start`: lines the run file already holds when this process starts (a resumed run), so
        default ids `<run>:<seq>` never reuse an earlier id. `helper_start`: helpers started so far.
        `workspace`: the run's workspace root; `files` are made relative to it (outside ones are dropped)."""
        self.run, self.ticket, self.harness, self.now = run, ticket, harness, now
        self.workspace = workspace
        self.hider, self.hidden = hider, hider is not None
        self.seq = seq_start
        self.session: str | None = None
        self.ignored: dict[str, int] = {}
        self.orphans = self.bad_lines = 0
        self._partial = False
        self._pending: dict[str, dict] = {}
        self._helpers: dict[str, tuple[str, str]] = {}
        self._helper_count = helper_start

    def _ignore(self, key: str) -> None:
        self.ignored[key] = self.ignored.get(key, 0) + 1

    def _emit(self, at: str, **fields: Any) -> dict:
        self.seq += 1
        event = dict(
            v=1,
            id=f"{self.run}:{self.seq}",
            seq=self.seq,
            run=self.run,
            session=self.session,
            agent="main",
            parent=None,
            at=at,
            ticket=self.ticket,
            harness=self.harness,
            via="log",
            used=None,
            outcome=None,
            detail=None,
            coverage="full",
        )
        event.update(fields)
        if event["kind"] == "step":
            event["coverage"] = "partial" if self._partial else "full"
            self._partial = False
        return _hide(event, self.hider) if self.hider is not None else event

    def _stable(self, *parts: Any) -> dict:
        """{"id": ...} from the line's own ids when all are usable, else {} (default id `<run>:<seq>`)."""
        if not all(isinstance(x, (str, int)) and not isinstance(x, bool) and str(x) for x in parts):
            return {}
        eid = ":".join([self.run, *map(str, parts)])
        return {"id": eid} if _valid_id(eid) else {}

    def _detail(self, kind: str, eid: str) -> str:
        return f"detail/{self.run}/{detail_name(self.run, kind, eid)}.json"

    def feed_with_detail(self, line: str | bytes) -> list[tuple[dict, dict | None]]:
        try:
            message = json.loads(line.decode("utf-8") if isinstance(line, bytes) else line)
        except (ValueError, UnicodeError, RecursionError):
            self.bad_lines += 1
            return []
        if not isinstance(message, dict):
            self.bad_lines += 1
            return []
        if self.session is None and isinstance(message.get("session_id"), str) and message["session_id"]:
            self.session = message["session_id"]
        stamp = _timestamp(message.get("timestamp"))
        at = stamp.isoformat().replace("+00:00", "Z") if stamp else self.now()
        stamp = stamp or _timestamp(at)  # the clock stands in for a missing line time, so ms stays right
        typ = message.get("type")
        if typ == "system" and message.get("subtype") == "init":
            fields = self._stable(self.session, "init", message.get("uuid"))
            return [
                (self._emit(at, **fields, kind="run.state", text="Working", data={"state": "working"}), None)
            ]
        if typ in ("assistant", "user"):
            body = message.get("message")
            content = body.get("content") if isinstance(body, dict) else None
            if not isinstance(content, list):
                self._ignore(f"{typ}/content")
                return []
            parent_id = message.get("parent_tool_use_id")
            owner = (
                self._helpers.get(parent_id, ("main", None)) if isinstance(parent_id, str) else ("main", None)
            )
            pairs = []
            for index, block in enumerate(content):
                if not isinstance(block, dict):
                    if typ == "assistant":
                        self._partial = True
                    continue
                if typ == "assistant":
                    pairs.extend(self._assistant(block, owner, at, stamp, message.get("uuid"), index))
                elif block.get("type") == "tool_result":
                    pairs.extend(self._finish(block, at, stamp))
            return pairs
        if typ == "rate_limit_event":
            return [(self._rate_limit(message, at), None)]
        if typ == "result":
            return [(event, None) for event in self._result(message, at)]
        key = str(typ)
        if message.get("subtype") is not None:
            key += "/" + str(message["subtype"])
        self._ignore(key[:40])
        return []

    def _assistant(
        self, block: dict, owner: tuple, at: str, stamp: datetime | None, uuid: Any = None, index: int = 0
    ) -> list:
        typ = block.get("type")
        if typ in ("thinking", "redacted_thinking"):
            return []
        if typ == "text":
            text = block.get("text")
            if not isinstance(text, str) or not text.strip():
                return []
            eid = f"{self.run}:{self.seq + 1}"
            if _valid_id(uuid) and _valid_id(f"{self.run}:{uuid}:{index}"):
                eid = f"{self.run}:{uuid}:{index}"  # the line's own uuid: stable across replays and processes
            event = self._emit(
                at,
                id=eid,
                kind="run.state",
                text=_one_line(text),
                data={"state": "working", "say": _one_line(text)},
                agent=owner[0],
                parent=owner[1],
                detail=self._detail("run.state", eid),
            )
            return [(event, {"input": None, "output": text})]
        if typ != "tool_use":
            self._partial = True
            return []
        original = block.get("id")
        if not isinstance(original, str) or not original:
            self._ignore("tool_use/noid")
            return []
        final = original if _valid_id(original) else _hash(original)  # the writer hashes unsafe ids itself
        name = block.get("name")
        name = name if isinstance(name, str) else "Tool"
        inp = block.get("input")
        inp = inp if isinstance(inp, dict) else {}
        agent, parent = owner
        kind = "step"
        if name in HELPER_TOOLS and self._helper_count < 9999:
            self._helper_count += 1
            agent, parent = f"h_{self._helper_count}", agent
            self._helpers[original] = (agent, parent)
            kind, used = "helper.start", _used("helper", "Helper", "harness")
            text = inp.get("description") or inp.get("prompt") or "Helper"
        else:
            used, text = describe_tool(name, inp)
        fields = dict(id=original, kind=kind, used=used, agent=agent, parent=parent, text=_one_line(text))
        if kind == "step" and name in _FILE_TOOLS:
            files = workspace_files(tool_paths(name, inp), self.workspace)
            if files:
                fields["files"] = files
        self._pending[original] = dict(fields=fields, final=final, input=inp, timestamp=stamp)
        return [(self._emit(at, **fields), None)]

    def _finish(self, block: dict, at: str, stamp: datetime | None) -> list:
        original = block.get("tool_use_id")
        pending = self._pending.pop(original, None) if isinstance(original, str) else None
        if pending is None:
            self.orphans += 1
            return []
        fields = pending["fields"].copy()
        content = block.get("content")
        text = _result_text(content)
        if fields["kind"] == "helper.start":
            fields.update(kind="helper.end", text=_one_line(text) or "Done")
        start = pending["timestamp"]
        ms = (stamp - start) // timedelta(milliseconds=1) if stamp and start else None
        if ms is not None and ms < 0:
            ms = None
        ok = not block.get("is_error", False)
        error = next((line for line in text.splitlines() if line.strip()), "Failed")
        fields.update(
            outcome=dict(ok=ok, error=None if ok else _one_line(error, 300), ms=ms),
            detail=self._detail(fields["kind"], pending["final"]),
        )
        return [(self._emit(at, **fields), {"input": pending["input"], "output": content})]

    def _rate_limit(self, message: dict, at: str) -> dict:
        info = message.get("rate_limit_info")
        info = info if isinstance(info, dict) else {}
        window = info.get("rateLimitType")
        window = window[:32] if isinstance(window, str) and window else None
        status = {"allowed_warning": "warning", "rejected": "limited"}.get(info.get("status"), "ok")
        windows = info.get("unifiedWindows")
        selected = windows.get(window) if isinstance(windows, dict) else None
        candidates = [
            selected.get("utilization") if isinstance(selected, dict) else None,
            info.get("utilization"),
        ]
        used = next(
            (v for v in candidates if type(v) in (int, float) and math.isfinite(v)),
            {"ok": 0, "warning": 0.8, "limited": 1.0}[status],
        )
        used = min(1, max(0, used))
        data = dict(used=used, status=status)
        if window is not None:
            data["window"] = window
        text = {
            "ok": "Within your limit",
            "warning": f"{used * 100:g} % of your limit used",
            "limited": "Limit reached",
        }[status]
        uuid = message.get("uuid")
        fields = {"id": f"{self.run}:{uuid}"} if _valid_id(uuid) and _valid_id(f"{self.run}:{uuid}") else {}
        return self._emit(at, **fields, kind="usage", text=text, data=data)

    def _result(self, message: dict, at: str) -> list[dict]:
        events = []
        turns = message.get("num_turns")
        tag = message.get("uuid") or (
            f"{self.session}.{turns}" if self.session and type(turns) is int else None
        )
        denials = message.get("permission_denials")
        for index, denial in enumerate(denials if isinstance(denials, list) else []):
            if not isinstance(denial, dict):
                continue
            name = _name(denial.get("tool_name"))
            tool_id = denial.get("tool_use_id")  # raw: the writer hashes unsafe ids like for the step
            fields = (
                {"id": tool_id}
                if isinstance(tool_id, str) and tool_id
                else self._stable(tag, "denial", index)
            )
            events.append(
                self._emit(
                    at,
                    **fields,
                    kind="denial",
                    text=f"Not allowed: {name}",
                    used=_used("tool", name, "builtin"),
                    outcome=dict(ok=False, error="Not allowed by this workspace", ms=None),
                )
            )
        usage = message.get("usage")
        if isinstance(usage, dict):

            def tokens(key: str) -> int:
                value = usage.get(key)
                return value if type(value) is int and value >= 0 else 0

            ti = sum(
                tokens(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
            )
            to = tokens("output_tokens")
            events.append(
                self._emit(
                    at,
                    **self._stable(tag, "usage"),
                    kind="usage",
                    text=f"Tokens: {ti} in, {to} out",
                    data=dict(tokens_in=ti, tokens_out=to, used=0),
                )
            )
        state = "failed" if message.get("is_error") else "idle"
        data = {"state": state}
        if type(message.get("num_turns")) is int:
            data["turns"] = message["num_turns"]
        events.append(
            self._emit(at, **self._stable(tag, "end"), kind="run.state", text=state.capitalize(), data=data)
        )
        return events

    def feed(self, line: str | bytes) -> list[dict]:
        return [event for event, _ in self.feed_with_detail(line)]

    def events(self, lines: Iterable[str | bytes]) -> Iterator[dict]:
        for line in lines:
            yield from self.feed(line)


def map_stream(lines: Iterable[str | bytes], ctx: dict) -> list[dict]:
    return list(
        StreamJsonMapper(
            ctx["run"], ctx["ticket"], ctx["harness"], now=lambda: ctx["at"], workspace=ctx.get("workspace")
        ).events(lines)
    )


def collect(lines: Iterable[str | bytes], writer: Any, ctx: dict) -> dict:
    mapper = StreamJsonMapper(
        ctx["run"],
        ctx["ticket"],
        ctx["harness"],
        now=_now,
        seq_start=ctx.get("seq_start", 0),
        helper_start=ctx.get("helper_start", 0),
        workspace=ctx.get("workspace"),
    )
    written = deduped = invalid = 0
    for line in lines:
        for event, detail in mapper.feed_with_detail(line):
            try:
                stored = writer.append(event, detail=detail)
            except RecordInvalid:
                invalid += 1  # one bad event must not stop the rest of the run; every other refusal
                continue  # (off, tampered, unavailable) propagates and stops the run loudly
            if stored is None:
                deduped += 1
            else:
                written += 1
    return dict(
        written=written,
        deduped=deduped,
        invalid=invalid,
        bad_lines=mapper.bad_lines,
        orphans=mapper.orphans,
        ignored=mapper.ignored,
    )

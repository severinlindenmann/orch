"""Pure mapping from "exec --json" item stream lines to activity events (format id in the agents data).

Detail paths are pointers only.

HOOK POINT — value hiding (slices 1.5/1.3): the mapper holds NO key values.
Supply a hider to transform every emitted string. Without one, hidden is False.
The record writer must refuse without a registered workspace hider (activity.md,
fail closed), and must also apply that hider to every string in detail payloads.
Supplying a callable here does not establish writer registration or trust.
"""

import hashlib
import json
import re
import shlex
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any


def _hash(text: str) -> str:
    return "x_" + hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()[:32]


def detail_name(run: str, kind: str, event_id: str, ticket: str | None) -> str:
    """The ONLY way a detail file name is made: 32 lowercase hex of a domain-separated sha256 over
    (run, kind, final event id, ticket). No raw id is ever a file name (case-insensitive file systems,
    separators). The ticket is part of the name, so details of two tickets never share a file (a line of
    ticket B can only name a file made for B). A missing ticket hashes as the empty string."""
    data = b"orch.detail/2\0" + b"\0".join(
        x.encode("utf-8", errors="surrogatepass") for x in (run, kind, event_id, ticket or "")
    )
    return hashlib.sha256(data).hexdigest()[:32]


def hide_values(text: str, hider: Callable[[str], str]) -> str:
    """Explicit injection point; deliberately has no pass-through default or key store."""
    return hider(text)


def _hide(value: Any, hider: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return hide_values(value, hider)
    if isinstance(value, dict):
        return {k: _hide(v, hider) for k, v in value.items()}
    if isinstance(value, list):
        return [_hide(v, hider) for v in value]
    return value


def _one_line(text: Any, n: int = 200) -> str:
    return " ".join(str(text).split())[:n]


def _shell_unwrap(cmd: str) -> str:
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return cmd
    if len(parts) == 3 and PurePath(parts[0]).name in ("sh", "bash", "zsh") and parts[1] in ("-c", "-lc"):
        return parts[2]
    return cmd


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ExecJsonMapper:
    def __init__(
        self,
        run: str,
        ticket: str,
        harness: str,
        now: Callable[[], str] = _now,
        hider: Callable[[str], str] | None = None,
    ):
        self.run, self.ticket, self.harness, self.now = run, ticket, harness, now
        self.hider, self.hidden = hider, hider is not None
        self.seq = self.turn = 0
        self.session: str | None = None
        self.warnings: list[str] = []
        self._partial = False

    def _emit(self, **fields: Any) -> dict:
        self.seq += 1
        event = dict(
            v=1,
            id=f"{self.run}:{self.seq}",
            seq=self.seq,
            run=self.run,
            session=self.session,
            agent="main",
            parent=None,
            at=self.now(),
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

    def feed(self, line: str | bytes) -> list[dict]:
        try:
            message = json.loads(line)
        except (ValueError, UnicodeError, RecursionError):
            return []
        if not isinstance(message, dict):
            return []
        kind = message.get("type")
        if kind == "thread.started":
            self.session = message.get("thread_id")
        elif kind == "turn.started":
            self.turn += 1
            return [self._emit(kind="run.state", text="Working", data={"state": "working"})]
        elif kind == "turn.completed":
            usage = message.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            ti, to = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
            return [
                self._emit(
                    kind="usage", text=f"Tokens: {ti} in, {to} out", data={"tokens_in": ti, "tokens_out": to}
                ),
                self._emit(kind="run.state", text="Idle", data={"state": "idle"}),
            ]
        elif kind in ("item.started", "item.completed"):
            item = message.get("item")
            if isinstance(item, dict):
                return self._item(item, kind == "item.completed")
        return []

    def _item(self, item: dict, completed: bool) -> list[dict]:
        typ = item.get("type")
        if typ == "error":
            if len(self.warnings) < 20:
                warning = str(item.get("message", ""))
                self.warnings.append(hide_values(warning, self.hider) if self.hider else warning)
            return []
        if typ in ("reasoning", "todo_list") or (typ == "agent_message" and not completed):
            return []
        if typ not in ("command_execution", "file_change", "mcp_tool_call", "web_search", "agent_message"):
            self._partial = True
            return []
        eid = f"{self.run}:{self.seq + 1}"
        if item.get("id") is not None:
            eid = f"{self.run}:{self.turn}:{item['id']}"
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", eid):
                eid = _hash(eid)
        kind = "run.state" if typ == "agent_message" else "step"
        fields = dict(
            id=eid,
            detail=f"detail/{self.run}/{detail_name(self.run, kind, eid, self.ticket)}.json"
            if completed
            else None,
        )
        if typ == "agent_message":
            say = _one_line(item.get("text", ""))
            return [self._emit(**fields, kind="run.state", text=say, data={"state": "working", "say": say})]
        name, text, action, source, used_kind = "Run command", "", None, "builtin", "tool"
        ok, error = None, None
        if typ == "command_execution":
            text = _shell_unwrap(str(item.get("command", "")))
            code = item.get("exit_code")
            ok = None if code is None else code == 0
            first = str(item.get("aggregated_output") or "").strip().splitlines()[:1]
            if ok is False:
                error = _one_line(f"Exit code {code}: {first[0] if first else ''}", 300)
        else:
            status = item.get("status")
            ok = True if status == "completed" else False if status == "failed" else None
            if typ == "file_change":
                changes = item.get("changes")
                first = changes[0] if isinstance(changes, list) and changes else {}
                path = first.get("path") if isinstance(first, dict) else None
                name, text = "Edit", f"Edit {path}" if path else "Edit files"
            elif typ == "mcp_tool_call":
                name, action = str(item.get("server") or "MCP"), item.get("tool")
                used_kind, source, text = "mcp", "harness", f"{name} {action or ''}"
            else:
                name, text = "Web search", f"Web search {item.get('query') or ''}"
        used = dict(kind=used_kind, name=name, action=action, source=source, version=None)
        outcome = dict(ok=ok, error=error, ms=None) if completed else None
        return [self._emit(**fields, kind="step", text=_one_line(text), used=used, outcome=outcome)]

    def events(self, lines: Iterable[str | bytes]) -> Iterator[dict]:
        for line in lines:
            yield from self.feed(line)


def map_stream(lines: Iterable[str | bytes], ctx: dict) -> list[dict]:
    return list(
        ExecJsonMapper(ctx["run"], ctx["ticket"], ctx["harness"], now=lambda: ctx["at"]).events(lines)
    )

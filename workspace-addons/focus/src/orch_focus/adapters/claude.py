"""Optional mapper `claude-transcript/1`: Claude's transcript / stream-json lines -> run events.

Claude-specific details live only in this file. Feed it one decoded JSON line at a time with `feed`.
"""

from __future__ import annotations

import os
from datetime import datetime

from .. import events as ev

HELPER_TOOLS = ("Task", "Agent")
_WORDS = {
    "Bash": "Run",
    "Read": "Read",
    "Edit": "Edit",
    "Write": "Write",
    "Grep": "Search",
    "Glob": "Find files",
}


def _step_text(name: str, inp: dict) -> str:
    """A plain-words step line for one tool call."""
    if inp.get("description"):
        return str(inp["description"])
    target = inp.get("file_path") or inp.get("path") or inp.get("pattern") or inp.get("url")
    if name == "Bash":
        first = str(inp.get("command", "")).strip().splitlines()[:1]
        return "Run " + (ev.redact(first[0])[:80] if first else "a command")
    verb = _WORDS.get(name, name)
    if target:
        return f"{verb} {os.path.basename(str(target)) or target}"[:120]
    return verb


def _result_text(content) -> str:
    if isinstance(content, list):
        content = " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    text = " ".join(str(content or "").split())
    return text[:200]


def _secs(a: str, b: str) -> float | None:
    try:
        f = lambda s: datetime.fromisoformat(s).timestamp()
        return f(b) - f(a)
    except (ValueError, AttributeError):
        return None


class ClaudeMapper:
    def __init__(self, run: str, ticket: str):
        self.run, self.tid = run, ticket
        self._open: dict[str, dict] = {}  # tool_use id -> {kind, agent, at}
        self._helper_of: dict[str, str] = {}  # helper tool_use id -> h_<n>
        self._n = 0

    def _e(self, agent, kind, text, at=None, **data):
        return ev.make(self.run, self.tid, agent, kind, text, "adapter", at=at, **data)

    def _agent(self, parent: str | None) -> str:
        return self._helper_of.get(parent, "main") if parent else "main"

    def feed(self, line: dict) -> list[dict]:
        t = line.get("type")
        at = line.get("timestamp")
        at = at[:19] + "Z" if isinstance(at, str) and len(at) >= 19 else None
        parent = line.get("parent_tool_use_id")
        if t == "system" and line.get("subtype") == "init":
            return [self._e("main", "run.state", "Working", at, state="working")]
        if t == "assistant":
            return self._assistant(line, at, parent)
        if t == "user":
            return self._user(line, at)
        if t == "rate_limit_event":
            return self._usage(line.get("rate_limit_info") or {}, at)
        if t == "result":
            return self._result(line, at)
        return []

    def _assistant(self, line, at, parent):
        out = []
        agent = self._agent(parent)
        for b in (line.get("message") or {}).get("content") or []:
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue
            tid, name, inp = b.get("id", ""), b.get("name", ""), b.get("input") or {}
            if not tid:
                continue
            if name in HELPER_TOOLS and not parent:
                self._n += 1
                h = f"h_{self._n}"
                self._helper_of[tid] = h
                text = str(inp.get("description") or inp.get("prompt") or "Helper")[:120]
                self._open[tid] = {"kind": "helper", "at": at}
                out.append(self._e(h, "helper.start", text, at, id=tid))
            else:
                self._open[tid] = {"kind": "tool", "at": at, "agent": agent}
                cmd = inp.get("command") if name == "Bash" else None
                out.append(
                    self._e(agent, "tool.start", _step_text(name, inp), at, id=tid, tool=name, command=cmd)
                )
        return out

    def _user(self, line, at):
        out = []
        content = (line.get("message") or {}).get("content")
        if not isinstance(content, list):
            return out
        for b in content:
            if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                continue
            tid = b.get("tool_use_id", "")
            start = self._open.pop(tid, None)
            if start is None:
                continue
            ok = not b.get("is_error")
            text = _result_text(b.get("content"))
            took = _secs(start["at"], at) if start.get("at") and at else None
            ms = int(took * 1000) if took is not None and took >= 0 else None
            if start["kind"] == "helper":
                out.append(
                    self._e(self._helper_of[tid], "helper.end", text or "Done", at, id=tid, ok=ok, ms=ms)
                )
            else:
                out.append(
                    self._e(
                        start["agent"],
                        "tool.end",
                        text or ("Done" if ok else "Failed"),
                        at,
                        id=tid,
                        ok=ok,
                        ms=ms,
                    )
                )
        return out

    def _usage(self, info: dict, at):
        status = {"allowed": "ok", "allowed_warning": "warning", "rejected": "limited"}.get(
            info.get("status"), "ok"
        )
        used = info.get("utilization")
        if not isinstance(used, (int, float)):
            used = {"ok": 0.0, "warning": 0.8, "limited": 1.0}[status]
        used = max(0.0, min(1.0, float(used)))
        text = {"ok": "Within your limit", "warning": f"{round(used * 100)} % of your limit used",
                "limited": "Limit reached"}[status]  # fmt: skip
        return [
            self._e(
                "main",
                "usage",
                text,
                at,
                used=used,
                window=str(info.get("rateLimitType") or "")[:32] or None,
                status=status,
            )
        ]

    def _result(self, line, at):
        out = []
        for d in line.get("permission_denials") or []:
            name = str(d.get("tool_name") or "a tool")[:64]
            out.append(self._e("main", "denial", f"Needs your OK to use {name}", at, tool=name))
        failed = bool(line.get("is_error"))
        out.append(self._e("main", "run.state", "Failed" if failed else "Finished", at,
                           state="failed" if failed else "idle", turns=line.get("num_turns"),
                           denials=len(line.get("permission_denials") or [])))  # fmt: skip
        return out

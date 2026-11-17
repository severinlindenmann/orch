"""What a live helper still has going on that its idle prompt hides (ORCH-267).

A helper can sit at its prompt ("idle") while it is not idle at all:
- it started helpers of its own in the background (the tool's Agent tool with run_in_background). The tool
  shows the prompt while they work; ending the session loses them, and their work starts again from zero;
- a person is talking to it in its own window. Their typed lines never reach the ticket's history, so the
  watcher saw a quiet helper and ended or restarted it in the middle of the conversation.

Both are read from the end of the saved conversation (no AI call, no process list):
- a background helper is running from the tool result that says it was launched until the
  <task-notification> naming the same tool use arrives (any status). One older than MAX_AGE counts as gone
  (a notice lost when the session was resumed must not keep a session open for ever);
- a person typed when a user entry is plain text that orch did not type itself. Inside a session orch only
  types its notice lines (runs_live.NOTICE); the task text of a start or resume arrives right after the start
  (START_GRACE); tool results, task notices and tool wrappers start with "<".

Unknown formats give nothing found, never an error: a tool without these entries is treated as before.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from pathlib import Path

from orch import adapters, runs

TAIL_BYTES = 4 * 1024 * 1024  # the end of the saved conversation that is read
MAX_AGE = 4 * 3600  # a background helper with no finish notice after this long counts as gone
TALK_MINUTES = 30  # a person typed to the helper this recently: it is in a conversation
START_GRACE = 120  # a "user" line this soon after the session started is orch's own task text

_LAUNCHED = "Async agent launched"
_NOTICE = "<task-notification>"
_TOOL_USE_ID = re.compile(r"<tool-use-id>([^<]+)</tool-use-id>")
# what orch types or the tool writes as a "user" line by itself: its notices, the task text of a start, the
# summary after the conversation was compacted
_ORCH_TYPED = (
    "Your task for orch ticket ",
    "New input on orch ticket ",
    "Work on orch ticket ",
    "This session is being continued from a previous conversation",
)
_cache: dict[str, tuple[tuple[int, int], dict]] = {}


def _ts(iso: object) -> float | None:
    """The tool's time (2026-11-17T16:12:43.065Z, milliseconds optional) as seconds, or None."""
    if not isinstance(iso, str):
        return None
    with contextlib.suppress(ValueError):
        return runs._parse(re.sub(r"\.\d+Z$", "Z", iso))
    return None


def _text(content: object) -> str | None:
    """The plain text of a user entry, or None for tool results and anything else."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        parts = [b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if parts and all(isinstance(p, str) for p in parts):
            return "\n".join(parts)
    return None


def _results(content: object) -> list[tuple[str, str]]:
    out = []
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str):
            c = b.get("content")
            text = (
                c
                if isinstance(c, str)
                else " ".join(
                    x.get("text", "")
                    for x in c or []
                    if isinstance(x, dict) and isinstance(x.get("text"), str)
                )
            )
            out.append((b["tool_use_id"], text))
    return out


def scan(lines: list[str]) -> dict:
    """{"agents": {tool_use_id: {"what", "since"}}, "typed_at": float | None} from saved lines."""
    names: dict[str, str] = {}
    agents: dict[str, dict] = {}
    typed_at = None
    for line in lines:
        if '"tool_use' not in line and _NOTICE not in line and '"user"' not in line:
            continue  # most lines are answers and tool output: skip without parsing
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("isSidechain"):
            continue
        msg = d.get("message") if isinstance(d.get("message"), dict) else {}
        content = msg.get("content")
        if d.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use" and isinstance(b.get("id"), str):
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    names[b["id"]] = str(inp.get("description") or "a helper")[:80]
            continue
        if d.get("type") != "user":
            continue
        for tid, text in _results(content):
            if text.startswith(_LAUNCHED):
                agents[tid] = {"what": names.get(tid, "a helper"), "since": _ts(d.get("timestamp"))}
        text = _text(content)
        if text is None or d.get("isMeta") or d.get("isCompactSummary"):
            continue
        if text.lstrip().startswith(_NOTICE):
            for tid in _TOOL_USE_ID.findall(text):
                agents.pop(tid.strip(), None)
            continue
        s = text.strip()
        if s and not s.startswith("<") and not s.startswith(_ORCH_TYPED):
            typed_at = _ts(d.get("timestamp")) or typed_at
    return {"agents": agents, "typed_at": typed_at}


def read(path: Path | None) -> dict:
    """scan() of the end of a saved conversation (cached by size and time); empty when it cannot be read."""
    empty = {"agents": {}, "typed_at": None}
    if path is None:
        return empty
    try:
        st = path.stat()
        key = (st.st_size, st.st_mtime_ns)
        hit = _cache.get(str(path))
        if hit and hit[0] == key:
            return hit[1]
        with path.open("rb") as f:
            f.seek(max(0, st.st_size - TAIL_BYTES))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return empty
    lines = tail.splitlines()
    if st.st_size > TAIL_BYTES and lines:
        lines = lines[1:]  # the first line was cut in the middle
    found = scan(lines)
    if len(_cache) > 64:
        _cache.clear()
    _cache[str(path)] = (key, found)
    return found


def _path(root: Path, rec: dict | None) -> Path | None:
    rec = rec or {}
    sid, agent = rec.get("session"), rec.get("agent")
    if not isinstance(sid, str) or not isinstance(agent, str) or not rec.get("ticket"):
        return None
    with contextlib.suppress(Exception):
        return adapters.transcript_path(agent, sid, root, folder=runs.workdir_for(root, rec, rec["ticket"]))
    return None


def subagents(root: Path, rec: dict | None, now: float | None = None) -> list[dict]:
    """The helpers this run started in the background that have not finished: [{"what", "seconds"}]."""
    now = time.time() if now is None else now
    out = []
    for a in read(_path(root, rec))["agents"].values():
        since = a.get("since")
        age = None if since is None else max(0, int(now - since))
        if age is not None and age > MAX_AGE:
            continue
        out.append({"what": a["what"], "seconds": age})
    return out


def talking(root: Path, rec: dict | None, now: float | None = None) -> bool:
    """A person typed to this helper in its own window within TALK_MINUTES. The task text orch hands the tool
    when it starts or resumes the session (its words vary) arrives within START_GRACE of the start and is not
    counted."""
    now = time.time() if now is None else now
    at = read(_path(root, rec))["typed_at"]
    if at is None or now - at >= TALK_MINUTES * 60:
        return False
    started = _ts((rec or {}).get("started_at")) or 0.0
    return at > started + START_GRACE
